"""
MOD-04 — Service Desk (Services)

Implementa as regras de negócio de visualização e transição de chamados.
"""

import logging
import uuid
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import (
    BusinessRuleException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    StateTransitionException,
    ValidationException,
)
from app.identity.models import UserAccount
from app.notifications.outbox import emit_event
from app.organization.models import Employee
from app.service_desk.access import TicketAccess, evaluate_ticket_access
from app.service_desk.models import Ticket, TicketCategory, TicketInteraction, TicketMaterial
from app.service_desk.repository import ServiceDeskRepository
from app.sla.report import sla_report
from app.sla.service import REOPEN_TO, SlaService, _now as sla_now
from app.service_desk.schemas import (
    CategoryCount,
    ChildrenOverview,
    ChildrenProgress,
    ChildTicketSpec,
    ChildTicketSummary,
    TicketsReport,
    TicketCreate,
    TicketInteractionCreate,
    TicketUpdate,
    TicketCategoryCreate,
    TicketCategoryUpdate,
    TicketMaterialCreate,
)

if TYPE_CHECKING:
    from app.core.access import AccessContext

logger = logging.getLogger(__name__)

CLOSED_STATUSES = ("RESOLVED", "CLOSED")


class ServiceDeskService:
    def __init__(self, session: AsyncSession, stock_service=None) -> None:
        self.session = session
        self.repo = ServiceDeskRepository(session)
        self.stock_service = stock_service

    # ==========================================================================
    # Categories
    # ==========================================================================
    
    async def list_categories(self) -> Sequence[TicketCategory]:
        return await self.repo.list_categories()

    async def _check_sla_policy(self, policy_id: uuid.UUID | None, can_manage_sla: bool) -> None:
        if not can_manage_sla:
            raise ForbiddenException("Escolher o SLA da categoria exige a permissão Gerenciar SLA.")
        if policy_id is not None:
            from app.sla.models import SlaPolicy

            if await self.session.get(SlaPolicy, policy_id) is None:
                raise ValidationException("Política de SLA não encontrada")

    async def create_category(self, schema: TicketCategoryCreate, can_manage_sla: bool = False) -> TicketCategory:
        if schema.sla_policy_id is not None:
            await self._check_sla_policy(schema.sla_policy_id, can_manage_sla)
        cat = TicketCategory(
            name=schema.name,
            description=schema.description,
            is_active=schema.is_active,
            default_sector_id=schema.default_sector_id,
            form_schema=schema.form_schema or [],
            sla_policy_id=schema.sla_policy_id,
        )
        return await self.repo.create_category(cat)

    async def update_category(
        self, category_id: uuid.UUID, schema: TicketCategoryUpdate, can_manage_sla: bool = False,
        user_id: uuid.UUID | None = None,
    ) -> TicketCategory:
        cat = await self.repo.get_category(category_id)
        if not cat:
            raise NotFoundException("TicketCategory", category_id)
        # Só vale para chamados novos: os abertos guardaram a cópia da política no ciclo (ADR-017).
        if "sla_policy_id" in schema.model_fields_set and schema.sla_policy_id != cat.sla_policy_id:
            await self._check_sla_policy(schema.sla_policy_id, can_manage_sla)
            from app.audit.repository import AuditRepository

            await AuditRepository(self.session).create(
                "ticket_category.sla_changed", "ticket_category", cat.id,
                {"from": str(cat.sla_policy_id) if cat.sla_policy_id else None,
                 "to": str(schema.sla_policy_id) if schema.sla_policy_id else None},
                user_id=user_id,
            )
            cat.sla_policy_id = schema.sla_policy_id

        if schema.name is not None:
            cat.name = schema.name
        if schema.description is not None:
            cat.description = schema.description
        if schema.is_active is not None:
            cat.is_active = schema.is_active
        if schema.default_sector_id is not None:
            cat.default_sector_id = schema.default_sector_id
        if schema.form_schema is not None:
            cat.form_schema = schema.form_schema

        return await self.repo.update_category(cat)

    # ==========================================================================
    # Tickets
    # ==========================================================================

    async def get_ticket_for_user(
        self,
        ticket_id: uuid.UUID,
        user_employee_id: uuid.UUID | None = None,
        is_technician: bool = False,
        can_read_all: bool = False,
        user_id: uuid.UUID | None = None,
        sector_id: uuid.UUID | None = None
    ) -> Ticket:
        """
        Busca um ticket e garante as regras de menor privilégio e escopo (``app.service_desk.access``):
        - Gestores ou Administradores (can_read_all=True) veem qualquer chamado.
        - Atendentes (is_technician=True) veem chamados do seu setor responsável e os atribuídos a si.
        - Solicitante e quem abriu o chamado (criador) veem o chamado.
        """
        ticket = await self.repo.get_ticket(ticket_id)
        if not ticket:
            raise NotFoundException("Chamado", ticket_id)
        access = await self.ticket_access(
            ticket, user_employee_id=user_employee_id, user_id=user_id, sector_id=sector_id,
            is_technician=is_technician, can_read_all=can_read_all,
        )
        if access.can_view:
            return ticket
        if is_technician:
            raise ForbiddenException("Você não tem acesso a chamados de outros setores.")
        raise ForbiddenException("Você não tem acesso a este chamado.")

    async def ticket_access(
        self,
        ticket: Ticket,
        *,
        user_employee_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        sector_id: uuid.UUID | None,
        is_technician: bool,
        can_read_all: bool,
    ) -> TicketAccess:
        """Avalia o acesso; resolve o setor do atendente pelo colaborador quando o escopo não o trouxe."""
        if is_technician and sector_id is None and user_employee_id is not None:
            emp = await self.session.get(Employee, user_employee_id)
            if emp:
                sector_id = emp.sector_id
        return evaluate_ticket_access(
            ticket, user_employee_id=user_employee_id, user_id=user_id, sector_id=sector_id,
            is_technician=is_technician, can_read_all=can_read_all,
            parent_created_by_user_id=await self._parent_creator(ticket),
        )

    async def can_see_internal(self, ticket: Ticket, can_internal_notes: bool, **scope) -> bool:
        """Notas internas: a permissão de sempre; num subchamado, só para o setor dele (ADR-026, nível ``internal``)."""
        if not can_internal_notes:
            return False
        if ticket.parent_ticket_id is None:
            return True
        return (await self.ticket_access(ticket, **scope)).is_sector_attendant

    async def visible_parent_ids(self, tickets: Sequence[Ticket], **scope) -> set[uuid.UUID]:
        """Principais que quem pede pode ver: o campo ``parent_ticket_id`` só aparece para eles."""
        parent_ids = {t.parent_ticket_id for t in tickets if t.parent_ticket_id}
        visible = set()
        for parent_id in parent_ids:
            parent = await self.repo.get_ticket(parent_id)
            if parent is not None and (await self.ticket_access(parent, **scope)).can_view:
                visible.add(parent_id)
        return visible

    async def list_tickets_for_user(
        self,
        user_employee_id: uuid.UUID | None,
        user_id: uuid.UUID | None = None,
        sector_id: uuid.UUID | None = None,
        is_technician: bool = False,
        can_read_all: bool = False
    ) -> Sequence[Ticket]:
        # 1. Gestores / Administradores com can_read_all veem todos os chamados
        if can_read_all:
            return await self.repo.list_tickets()

        # 2. Atendentes veem chamados destinados ao seu setor, atribuídos a si, solicitados ou abertos por si
        if is_technician:
            return await self.repo.list_tickets(
                requester_id=user_employee_id,
                sector_id=sector_id,
                assignee_id=user_id,
                created_by_id=user_id,
                is_attendant_scope=True,
            )

        # 3. Os demais veem os chamados em que são solicitantes ou que abriram
        if not user_employee_id and not user_id:
            return []
        return await self.repo.list_tickets(requester_id=user_employee_id, created_by_id=user_id)

    async def resolve_requester(
        self,
        requested_employee_id: uuid.UUID | None,
        *,
        own_employee_id: uuid.UUID | None,
        can_create_on_behalf: bool,
    ) -> Employee:
        """
        Solicitante do chamado: sem ``requester_id`` (ou com o próprio colaborador), é quem abre; outro colaborador
        exige ``service_desk.tickets.create_on_behalf`` e precisa existir ativo.
        """
        if requested_employee_id is None or requested_employee_id == own_employee_id:
            if own_employee_id is None:
                raise ForbiddenException("Apenas colaboradores vinculados a um Employee podem abrir chamados.")
            own = await self.session.get(Employee, own_employee_id)
            if own is None:
                raise ForbiddenException("Apenas colaboradores vinculados a um Employee podem abrir chamados.")
            return own  # como antes: quem tem conta ativa abre para si mesmo
        if not can_create_on_behalf:
            raise ForbiddenException(
                "Abrir chamado em nome de outra pessoa exige a permissão Abrir chamados em nome de outra pessoa."
            )
        employee = await self.session.get(Employee, requested_employee_id)
        if employee is None or not employee.is_active or employee.deleted_at is not None or employee.status == "DESLIGADO":
            raise BusinessRuleException("Solicitante inválido ou inativo.")
        return employee

    async def resolve_responsible_sector(
        self,
        category: TicketCategory | None,
        requested_sector_id: uuid.UUID | None,
        *,
        can_route_any_sector: bool,
    ) -> uuid.UUID:
        """
        Direcionamento por categoria, único para chamados e subchamados:
        - categoria com setor padrão: vai para ele; outro setor só com ``service_desk.tickets.route_any_sector``;
        - categoria sem setor padrão, ou sem categoria: o setor informado é obrigatório e precisa existir ativo.
        """
        from app.organization.models import Sector

        default_sector_id = category.default_sector_id if category is not None else None
        if default_sector_id is not None:
            if requested_sector_id is None or requested_sector_id == default_sector_id:
                return default_sector_id
            if not can_route_any_sector:
                raise ForbiddenException(
                    "Esta categoria é direcionada a um setor definido. Escolher outro setor exige a permissão "
                    "Direcionar chamados a qualquer setor."
                )
        if requested_sector_id is None:
            raise BusinessRuleException(
                "Setor responsável não definido. Informe-o manualmente ou selecione uma categoria com roteamento automático."
            )
        sector = await self.session.get(Sector, requested_sector_id)
        if sector is None or not sector.is_active or sector.deleted_at is not None:
            raise BusinessRuleException("Setor responsável inválido ou inativo.")
        return requested_sector_id

    async def create_ticket(
        self,
        schema: TicketCreate, 
        requester_id: uuid.UUID,
        origin_unit_id: uuid.UUID,
        origin_sector_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        can_route_any_sector: bool = False,
    ) -> Ticket:
        """
        ``user_id`` é quem abre (criador) e é obrigatório: todo chamado novo registra quem o abriu, mesmo quando o
        solicitante (``requester_id``) é outra pessoa.

        ``schema.children``: subchamados criados na mesma transação (ADR-026); um filho inválido desfaz tudo.
        ``schema.template_id``: o modelo usado pela tela (só rastreio; precisa estar ativo).
        """
        if schema.template_id is not None:
            from app.service_desk.templates import TicketTemplateService

            await TicketTemplateService(self.session).ensure_usable(schema.template_id)
        parent = await self._create_ticket_core(
            title=schema.title, description=schema.description, priority=schema.priority,
            category_id=schema.category_id, custom_fields=schema.custom_fields,
            responsible_sector_id=schema.responsible_sector_id, asset_ids=schema.asset_ids,
            requester_id=requester_id, origin_unit_id=origin_unit_id, origin_sector_id=origin_sector_id,
            user_id=user_id, can_route_any_sector=can_route_any_sector, template_id=schema.template_id,
        )
        if schema.children:
            await self._create_children(
                parent, schema.children, user_id=user_id, can_route_any_sector=can_route_any_sector
            )
        return parent

    async def _create_ticket_core(
        self,
        *,
        title: str,
        description: str,
        priority: str,
        category_id: uuid.UUID | None,
        custom_fields: dict | None,
        responsible_sector_id: uuid.UUID | None,
        asset_ids: list[uuid.UUID] | None,
        requester_id: uuid.UUID,
        origin_unit_id: uuid.UUID,
        origin_sector_id: uuid.UUID,
        user_id: uuid.UUID,
        can_route_any_sector: bool,
        parent_ticket_id: uuid.UUID | None = None,
        is_required: bool = True,
        replaces_ticket_id: uuid.UUID | None = None,
        child_batch_id: str | None = None,
        template_id: uuid.UUID | None = None,
    ) -> Ticket:
        """Regras comuns a chamado e subchamado: direcionamento, formulário, SLA, auditoria e outbox. Sem commit."""
        if user_id is None:
            raise ValidationException("Todo chamado precisa registrar quem o abriu.")

        cat = None
        if category_id:
            cat = await self.repo.get_category(category_id)
            if not cat or not cat.is_active:
                raise BusinessRuleException("Categoria inválida ou inativa.")
        responsible_sector_id = await self.resolve_responsible_sector(
            cat, responsible_sector_id, can_route_any_sector=can_route_any_sector
        )

        if cat is not None:
            # Validação dos pré-requisitos vinculados ao formulário da categoria
            if cat.form_schema:
                provided_fields = custom_fields or {}
                for field in cat.form_schema:
                    field_id = field.get("id") or field.get("name") or field.get("key")
                    label = field.get("label") or field_id or "Campo"
                    is_required = field.get("required", False)
                    field_type = field.get("type", "text")

                    if is_required:
                        val = provided_fields.get(field_id) if field_id else None
                        if val is None or (isinstance(val, str) and not val.strip()) or (isinstance(val, bool) and not val):
                            raise BusinessRuleException(
                                f"O pré-requisito '{label}' é obrigatório para abrir chamado nesta categoria."
                            )

                    # Validação de consistência se preenchido
                    if field_id in provided_fields:
                        val = provided_fields[field_id]
                        if field_type == "select" and field.get("options") and val:
                            if val not in field.get("options", []):
                                raise BusinessRuleException(
                                    f"Opção '{val}' inválida para o pré-requisito '{label}'."
                                )

        # Verificar se o sistema está em modo DEMO ou se o solicitante é demo
        is_demo_ticket = False
        try:
            from app.core.settings_model import SystemSetting
            from app.organization.models import Employee
            from sqlalchemy import select
            stmt_mode = select(SystemSetting).where(SystemSetting.key == "system_mode")
            s_mode = (await self.session.execute(stmt_mode)).scalar_one_or_none()
            if s_mode and s_mode.value == "DEMO":
                is_demo_ticket = True
            else:
                emp_stmt = select(Employee.is_demo).where(Employee.id == requester_id)
                emp_demo = (await self.session.execute(emp_stmt)).scalar_one_or_none()
                if emp_demo:
                    is_demo_ticket = True
        except Exception:
            pass

        ticket = Ticket(
            title=title,
            description=description,
            priority=priority,
            category_id=category_id,
            custom_fields=custom_fields or {},
            requester_id=requester_id,
            origin_unit_id=origin_unit_id,
            origin_sector_id=origin_sector_id,
            responsible_sector_id=responsible_sector_id,
            status="OPENED",
            is_demo=is_demo_ticket,
            created_by_user_id=user_id,
            parent_ticket_id=parent_ticket_id,
            is_required=is_required,
            replaces_ticket_id=replaces_ticket_id,
            template_id=template_id,
        )

        if asset_ids:
            assets = await self.repo.get_assets_by_ids(asset_ids)
            ticket.assets = list(assets)

        ticket = await self.repo.create_ticket(ticket)
        loaded_ticket = await self.repo.get_ticket(ticket.id)
        await SlaService(self.session).start(loaded_ticket)  # sem política ativa na categoria: não faz nada

        audit_data = {
            "title": loaded_ticket.title,
            "priority": loaded_ticket.priority,
            "status": loaded_ticket.status,
            "category_id": str(loaded_ticket.category_id) if loaded_ticket.category_id else None,
            "requester_id": str(loaded_ticket.requester_id),
            "responsible_sector_id": str(loaded_ticket.responsible_sector_id),
        }
        if parent_ticket_id is not None:
            audit_data["parent_ticket_id"] = str(parent_ticket_id)
            audit_data["is_required"] = is_required
        if replaces_ticket_id is not None:
            audit_data["replaces_ticket_id"] = str(replaces_ticket_id)
        await self._record_audit_event(
            event_type="ticket.created", ticket_id=loaded_ticket.id, data=audit_data, user_id=user_id
        )
        extra = {"child_batch_id": child_batch_id} if child_batch_id else {}
        await self._emit_ticket_event("ticket.created", loaded_ticket, user_id, **extra)

        return loaded_ticket

    # ==========================================================================
    # Chamados vinculados (ADR-026)
    # ==========================================================================

    async def _create_children(
        self,
        parent: Ticket,
        specs: list[ChildTicketSpec],
        *,
        user_id: uuid.UUID,
        can_route_any_sector: bool,
        replaces: Ticket | None = None,
    ) -> list[Ticket]:
        """Cria os filhos de um lote: herdam o solicitante e a origem do principal; o criador é quem os acrescenta.

        Registra ``ticket.children_added`` no principal e emite ``ticket.children_created`` (um aviso por lote ao
        solicitante e ao criador do principal). O ``ticket.created`` de cada filho leva ``parent_ticket_id``, que a
        regra do solicitante ignora.
        """
        if parent.parent_ticket_id is not None:
            raise BusinessRuleException("Um subchamado não pode ter subchamados (um nível só).")
        batch_id = str(uuid.uuid4())
        children = []
        for spec in specs:
            children.append(await self._create_ticket_core(
                title=spec.title, description=spec.description, priority=spec.priority or parent.priority,
                category_id=spec.category_id, custom_fields=spec.custom_fields,
                responsible_sector_id=spec.responsible_sector_id, asset_ids=None,
                requester_id=parent.requester_id, origin_unit_id=parent.origin_unit_id,
                origin_sector_id=parent.origin_sector_id, user_id=user_id, can_route_any_sector=can_route_any_sector,
                parent_ticket_id=parent.id, is_required=True if replaces else spec.is_required,
                replaces_ticket_id=replaces.id if replaces else None, child_batch_id=batch_id,
            ))

        sector_names = await self._sector_names({c.responsible_sector_id for c in children})
        items = [
            {
                "ticket_id": str(c.id),
                "title": c.title[:200],
                "is_required": c.is_required,
                "responsible_sector_id": str(c.responsible_sector_id),
                "sector_name": sector_names.get(c.responsible_sector_id, ""),
                "category_name": c.category.name if c.category else "",
            }
            for c in children
        ]
        await self._record_audit_event(
            event_type="ticket.children_added", ticket_id=parent.id, data={"children": items}, user_id=user_id
        )
        await self._emit_ticket_event(
            "ticket.children_created", parent, user_id, child_batch_id=batch_id, children=items
        )
        return children

    async def _sector_names(self, sector_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        from app.organization.models import Sector

        if not sector_ids:
            return {}
        rows = await self.session.execute(select(Sector.id, Sector.name).where(Sector.id.in_(sector_ids)))
        return {row.id: row.name for row in rows.all()}

    async def _parent_creator(self, ticket: Ticket) -> uuid.UUID | None:
        if ticket.parent_ticket_id is None:
            return None
        return (
            await self.session.execute(select(Ticket.created_by_user_id).where(Ticket.id == ticket.parent_ticket_id))
        ).scalar_one_or_none()

    async def _access_for(self, ticket: Ticket, ctx: "AccessContext") -> TicketAccess:
        return await self.ticket_access(
            ticket, user_employee_id=ctx.employee_id, user_id=ctx.user_id, sector_id=ctx.sector_id,
            is_technician=ctx.is_technician, can_read_all=ctx.can_read_all,
        )

    async def _load_child_and_parent(self, child_id: uuid.UUID) -> tuple[Ticket, Ticket]:
        child = await self.repo.get_ticket(child_id)
        if not child:
            raise NotFoundException("Chamado", child_id)
        if child.parent_ticket_id is None:
            raise BusinessRuleException("Esta ação vale só para subchamados.")
        # Trava o principal antes de ler o estado dos filhos: serializa com o encerramento e com novas inclusões.
        await self.repo.lock_ticket_status(child.parent_ticket_id)
        parent = await self.repo.get_ticket(child.parent_ticket_id, populate_existing=True)
        child = await self.repo.get_ticket(child_id, populate_existing=True)
        return child, parent

    @staticmethod
    def _ensure_parent_open(parent: Ticket) -> None:
        if parent.status in CLOSED_STATUSES:
            raise ConflictException("O chamado principal já foi resolvido ou encerrado.")

    async def add_children(
        self, parent_id: uuid.UUID, specs: list[ChildTicketSpec], ctx: "AccessContext"
    ) -> list[Ticket]:
        """Inclui subchamados depois da abertura: solicitante ou criador do principal, ou atendente do setor dele."""
        status = await self.repo.lock_ticket_status(parent_id)
        if status is None:
            raise NotFoundException("Chamado", parent_id)
        parent = await self.repo.get_ticket(parent_id, populate_existing=True)
        access = await self._access_for(parent, ctx)
        if not (access.is_requester_or_creator or access.is_sector_attendant):
            raise ForbiddenException("Só o solicitante, quem abriu ou o setor do chamado incluem subchamados.")
        self._ensure_parent_open(parent)
        return await self._create_children(
            parent, specs, user_id=ctx.user_id, can_route_any_sector=ctx.can_route_any_sector
        )

    async def children_progress(self, parent: Ticket, children: Sequence[Ticket] | None = None) -> ChildrenProgress:
        if children is None:
            children = await self.repo.list_children(parent.id)
            await SlaService(self.session).attach(children)
        parent_sla = getattr(parent, "sla", None)
        progress = ChildrenProgress(total=len(children), process_overdue=bool(parent_sla and parent_sla.overdue))
        for child in children:
            done = child.status in CLOSED_STATUSES
            progress.done += done
            progress.canceled += child.status == "CANCELED"
            progress.required_pending += child.is_required and not done
            sla = getattr(child, "sla", None)
            late = bool(sla and sla.overdue)
            progress.overdue += late
            progress.steps_overdue += late and child.is_required
        return progress

    async def list_children_for_user(self, parent_id: uuid.UUID, ctx: "AccessContext") -> ChildrenOverview:
        """Resumo dos filhos (nível ``track``): quem pode ver o principal."""
        parent = await self.get_ticket_for_user(
            parent_id, user_employee_id=ctx.employee_id, is_technician=ctx.is_technician,
            can_read_all=ctx.can_read_all, user_id=ctx.user_id, sector_id=ctx.sector_id,
        )
        children = await self.repo.list_children(parent.id)
        await SlaService(self.session).attach([parent, *children])
        sector_names = await self._sector_names({c.responsible_sector_id for c in children})
        replaced_by = {c.replaces_ticket_id: c.id for c in children if c.replaces_ticket_id}
        summaries = [
            ChildTicketSummary(
                id=c.id, title=c.title, status=c.status, is_required=c.is_required,
                responsible_sector_id=c.responsible_sector_id,
                responsible_sector_name=sector_names.get(c.responsible_sector_id),
                category_id=c.category_id, category_name=c.category.name if c.category else None,
                assignee_name=c.assignee_name, created_at=c.created_at, replaces_ticket_id=c.replaces_ticket_id,
                replaced_by_ticket_id=replaced_by.get(c.id),
                resolution_due_at=c.sla.resolution_due_at if c.sla else None,
                overdue=bool(c.sla and c.sla.overdue), at_risk=bool(c.sla and c.sla.at_risk),
            )
            for c in children
        ]
        return ChildrenOverview(progress=await self.children_progress(parent, children), children=summaries)

    async def can_view_ticket(self, ticket_id: uuid.UUID, ctx: "AccessContext") -> bool:
        ticket = await self.repo.get_ticket(ticket_id)
        return ticket is not None and (await self._access_for(ticket, ctx)).can_view

    async def cancel_child(self, child_id: uuid.UUID, reason: str, ctx: "AccessContext") -> Ticket:
        """Cancela uma etapa: atendente do setor do filho ou do setor do principal, sempre com justificativa.

        Cancelado não conta como concluído: uma etapa obrigatória cancelada continua travando o principal até ser
        substituída ou dispensada.
        """
        child, parent = await self._load_child_and_parent(child_id)
        if child.status in CLOSED_STATUSES or child.status == "CANCELED":
            raise ConflictException("Este subchamado já foi concluído ou cancelado.")
        child_access = await self._access_for(child, ctx)
        parent_access = await self._access_for(parent, ctx)
        if not (child_access.is_sector_attendant or parent_access.is_sector_attendant):
            raise ForbiddenException("Só o setor do subchamado ou o do chamado principal cancelam uma etapa.")

        actor_sector_id = await self._actor_sector(ctx)
        old_status = child.status
        await self.repo.create_interaction(TicketInteraction(
            ticket_id=child.id, author_id=ctx.user_id, message=f"Etapa cancelada. Motivo: {reason}", is_internal=False
        ))
        child.status = "CANCELED"
        await self.repo.update_ticket(child)
        await SlaService(self.session).canceled(child)

        await self._record_audit_event(
            event_type="ticket.canceled", ticket_id=child.id,
            data={
                "reason": reason, "old_status": old_status,
                "canceled_by_sector_id": str(actor_sector_id) if actor_sector_id else None,
                "parent_ticket_id": str(parent.id),
            },
            user_id=ctx.user_id,
        )
        await self._record_audit_event(
            event_type="ticket.child_canceled", ticket_id=parent.id,
            data={"child_ticket_id": str(child.id), "title": child.title, "is_required": child.is_required,
                  "reason": reason},
            user_id=ctx.user_id,
        )
        await self._emit_ticket_event("ticket.canceled", child, ctx.user_id, reason=reason[:300])
        await self._emit_ticket_event(
            "ticket.child_canceled", parent, ctx.user_id, child_ticket_id=str(child.id),
            child_title=child.title[:200], is_required=child.is_required, reason=reason[:300],
        )
        return await self.repo.get_ticket(child.id)

    async def replace_child(
        self, child_id: uuid.UUID, reason: str, spec: ChildTicketSpec, ctx: "AccessContext"
    ) -> Ticket:
        """Substitui uma etapa cancelada por um subchamado novo e obrigatório. O cancelado fica como estava."""
        child, parent = await self._load_child_and_parent(child_id)
        if not (await self._access_for(parent, ctx)).is_sector_attendant:
            raise ForbiddenException("Só o setor do chamado principal substitui uma etapa.")
        if child.status != "CANCELED":
            raise ConflictException("Só um subchamado cancelado pode ser substituído.")
        if any(c.replaces_ticket_id == child.id for c in await self.repo.list_children(parent.id)):
            raise ConflictException("Este subchamado já foi substituído.")
        self._ensure_parent_open(parent)

        [new_child] = await self._create_children(
            parent, [spec], user_id=ctx.user_id, can_route_any_sector=ctx.can_route_any_sector, replaces=child
        )
        was_required = child.is_required
        child.is_required = False
        await self.repo.update_ticket(child)
        await self._record_audit_event(
            event_type="ticket.requirement_changed", ticket_id=child.id,
            data={"is_required": False, "was_required": was_required,
                  "reason": f"Substituído por #{str(new_child.id)[:8]}. {reason}",
                  "replaced_by_ticket_id": str(new_child.id)},
            user_id=ctx.user_id,
        )
        await self._record_audit_event(
            event_type="ticket.child_replaced", ticket_id=parent.id,
            data={"old_ticket_id": str(child.id), "new_ticket_id": str(new_child.id), "reason": reason},
            user_id=ctx.user_id,
        )
        return new_child

    async def set_child_requirement(
        self, child_id: uuid.UUID, is_required: bool, reason: str, ctx: "AccessContext"
    ) -> Ticket:
        """Torna uma etapa obrigatória ou não (setor do principal, com justificativa). Nada do filho é apagado."""
        child, parent = await self._load_child_and_parent(child_id)
        if not (await self._access_for(parent, ctx)).is_sector_attendant:
            raise ForbiddenException("Só o setor do chamado principal muda a obrigatoriedade de uma etapa.")
        self._ensure_parent_open(parent)
        if is_required and child.status == "CANCELED":
            raise ConflictException("Uma etapa cancelada não volta a ser obrigatória: substitua-a por outra.")
        if child.is_required == is_required:
            return child
        child.is_required = is_required
        await self.repo.update_ticket(child)
        data = {"is_required": is_required, "was_required": not is_required, "reason": reason,
                "child_ticket_id": str(child.id)}
        await self._record_audit_event(
            event_type="ticket.requirement_changed", ticket_id=child.id, data=data, user_id=ctx.user_id
        )
        await self._record_audit_event(
            event_type="ticket.requirement_changed", ticket_id=parent.id, data=data, user_id=ctx.user_id
        )
        return await self.repo.get_ticket(child.id)

    async def _actor_sector(self, ctx: "AccessContext") -> uuid.UUID | None:
        if ctx.sector_id is not None or ctx.employee_id is None:
            return ctx.sector_id
        emp = await self.session.get(Employee, ctx.employee_id)
        return emp.sector_id if emp else None

    async def _ensure_children_done(self, parent: Ticket) -> None:
        """Recusa resolver ou encerrar o principal com etapa obrigatória pendente (cancelada inclusive)."""
        pending = [
            c for c in await self.repo.list_children(parent.id) if c.is_required and c.status not in CLOSED_STATUSES
        ]
        if pending:
            listed = "; ".join(f"#{str(c.id)[:8]} {c.title} ({self._translate_status(c.status)})" for c in pending)
            raise BusinessRuleException(
                f"Há subchamados obrigatórios pendentes: {listed}. Conclua, substitua ou dispense essas etapas antes.",
                rule="required_children_pending",
            )

    async def _child_completed(self, child: Ticket, user_id: uuid.UUID | None) -> None:
        """Um filho concluiu: avisa o principal; quando zera os obrigatórios, avisa também o setor do principal."""
        parent = await self.repo.get_ticket(child.parent_ticket_id)
        if parent is None:
            return
        progress = await self.children_progress(parent)
        await self._record_audit_event(
            event_type="ticket.child_completed", ticket_id=parent.id,
            data={"child_ticket_id": str(child.id), "title": child.title, "status": child.status,
                  "required_pending": progress.required_pending},
            user_id=user_id,
        )
        await self._emit_ticket_event(
            "ticket.child_completed", parent, user_id, child_ticket_id=str(child.id), child_title=child.title[:200],
            required_pending=progress.required_pending, all_required_done=progress.required_pending == 0,
        )

    async def update_ticket(
        self, 
        ticket_id: uuid.UUID, 
        schema: TicketUpdate, 
        is_technician: bool,
        user_employee_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        sector_id: uuid.UUID | None = None,
        can_read_all: bool = False,
        can_reopen_late: bool = False,
    ) -> Ticket:
        ticket = await self.repo.get_ticket(ticket_id)
        if not ticket:
            raise NotFoundException("Chamado", ticket_id)

        access = await self.ticket_access(
            ticket, user_employee_id=user_employee_id, user_id=user_id, sector_id=sector_id,
            is_technician=is_technician, can_read_all=can_read_all,
        )

        # Regras de autorização para alteração do chamado
        if not access.is_sector_attendant:
            if ticket.parent_ticket_id is not None:
                # Subchamado (ADR-026): só o setor dele atende; solicitante e criadores acompanham e comentam.
                raise ForbiddenException("Só o setor responsável altera um subchamado.")
            if not access.is_requester_or_creator:
                raise ForbiddenException("Apenas o atendente responsável pelo setor ou o solicitante podem gerenciar este chamado.")

            # Solicitante (ou quem abriu) só tem permissão para finalizar/encerrar o chamado (RESOLVED ou CLOSED)
            if (
                schema.status not in ("RESOLVED", "CLOSED")
                or schema.priority is not None
                or schema.assignee_id is not None
                or schema.category_id is not None
                or schema.responsible_sector_id is not None
            ):
                raise ForbiddenException("Solicitante só tem permissão para finalizar ou encerrar seu próprio chamado.")

        old_status = ticket.status
        old_priority = ticket.priority
        old_assignee = ticket.assignee_id
        old_category_id = ticket.category_id

        if schema.status is not None and ticket.status == "RESOLVED" and schema.status in REOPEN_TO and not can_reopen_late:
            await self._ensure_reopen_window(ticket)  # antes de mexer em qualquer campo do chamado

        closing = schema.status in CLOSED_STATUSES and old_status not in CLOSED_STATUSES
        if closing and ticket.parent_ticket_id is None:
            # Trava o principal antes de olhar os filhos: uma inclusão simultânea espera e depois vê o encerramento.
            await self.repo.lock_ticket_status(ticket.id)
            await self._ensure_children_done(ticket)

        if schema.category_id is not None:
            cat = await self.repo.get_category(schema.category_id)
            if not cat or not cat.is_active:
                raise BusinessRuleException("Categoria inválida ou inativa.")
            ticket.category_id = schema.category_id

        if schema.assignee_id is not None:
            ticket.assignee_id = schema.assignee_id

        if schema.priority is not None:
            ticket.priority = schema.priority

        if schema.status is not None:
            # Regras de máquina de estados simples:
            if ticket.status == "CLOSED" and schema.status != "CLOSED":
                raise StateTransitionException("Chamado", ticket.status, schema.status)
            if ticket.status == "CANCELED":
                raise StateTransitionException("Chamado", ticket.status, schema.status)
            ticket.status = schema.status

        if schema.custom_fields is not None:
            ticket.custom_fields = schema.custom_fields

        if schema.asset_ids is not None:
            assets = await self.repo.get_assets_by_ids(schema.asset_ids)
            ticket.assets = list(assets)

        await self.repo.update_ticket(ticket)

        # SLA (ADR-017), na mesma transação: categoria e prioridade primeiro, depois a resposta, por fim o status
        # (assim "responder e resolver" na mesma chamada conta a primeira resposta antes de fechar o ciclo).
        sla = SlaService(self.session)
        if schema.category_id is not None and schema.category_id != old_category_id:
            await sla.category_changed(ticket)
        if schema.priority is not None and schema.priority != old_priority:
            await sla.priority_changed(ticket)

        # Se houver notas de justificativa/resolução, cria interação no chamado
        if schema.notes and schema.notes.strip():
            try:
                interaction = TicketInteraction(
                    ticket_id=ticket.id,
                    author_id=user_id or ticket.assignee_id or ticket.requester_id,
                    message=schema.notes.strip(),
                    is_internal=False
                )
                await self.repo.create_interaction(interaction)
            except Exception:
                logger.exception("Falha ao registrar nota de status como interação")
            else:
                author = await self.session.get(UserAccount, user_id) if user_id else None
                await sla.interaction_added(ticket, author.employee_id if author else None, False)
        if schema.status is not None and schema.status != old_status:
            await sla.status_changed(ticket, old_status, schema.status)

        # Emissão e gravação de eventos para histórico do ciclo de vida
        if schema.status is not None and schema.status != old_status:
            await self._record_audit_event(
                event_type="ticket.status_changed",
                ticket_id=ticket.id,
                data={
                    "old_status": old_status, 
                    "new_status": schema.status,
                    "notes": schema.notes
                },
                user_id=user_id
            )
            await self._emit_ticket_event(
                "ticket.status_changed", ticket, user_id, old_status=old_status, new_status=schema.status
            )
            if schema.status in ("RESOLVED", "CLOSED"):
                await self._record_audit_event(
                    event_type="ticket.closed",
                    ticket_id=ticket.id,
                    data={"status": schema.status, "notes": schema.notes},
                    user_id=user_id
                )

        if schema.priority is not None and schema.priority != old_priority:
            await self._record_audit_event(
                event_type="ticket.priority_changed",
                ticket_id=ticket.id,
                data={"old_priority": old_priority, "new_priority": schema.priority},
                user_id=user_id
            )

        if schema.assignee_id is not None and schema.assignee_id != old_assignee:
            await self._record_audit_event(
                event_type="ticket.assigned",
                ticket_id=ticket.id,
                data={"assignee_id": str(schema.assignee_id)},
                user_id=user_id
            )
            await self._emit_ticket_event("ticket.assigned", ticket, user_id)

        if closing and ticket.parent_ticket_id is not None:
            await self._child_completed(ticket, user_id)

        return await self.repo.get_ticket(ticket.id)

    # ==========================================================================
    # Interactions (Comentários e Chat)
    # ==========================================================================

    async def add_interaction(
        self, 
        ticket_id: uuid.UUID, 
        schema: TicketInteractionCreate, 
        author_id: uuid.UUID,
        user_employee_id: uuid.UUID | None,
        is_technician: bool = False,
        can_read_all: bool = False,
        can_internal_notes: bool = False,
        sector_id: uuid.UUID | None = None
    ) -> TicketInteraction:
        ticket = await self.get_ticket_for_user(
            ticket_id=ticket_id,
            user_employee_id=user_employee_id,
            is_technician=is_technician,
            can_read_all=can_read_all,
            user_id=author_id,
            sector_id=sector_id,
        )

        if ticket.status in ("CLOSED", "CANCELED"):
            raise BusinessRuleException("Não é possível adicionar interações a um chamado fechado.")

        access = await self.ticket_access(
            ticket, user_employee_id=user_employee_id, user_id=author_id, sector_id=sector_id,
            is_technician=is_technician, can_read_all=can_read_all,
        )
        can_internal = is_technician or can_internal_notes
        if ticket.parent_ticket_id is not None:
            # Subchamado (ADR-026): nota interna só do setor dele, nunca de quem só acompanha.
            can_internal = can_internal and access.is_sector_attendant
        if schema.is_internal and not can_internal:
            raise ForbiddenException("Apenas técnicos ou gestores podem criar notas internas.")

        interaction = TicketInteraction(
            ticket_id=ticket.id,
            author_id=author_id,
            message=schema.message,
            is_internal=schema.is_internal
        )
        created_interaction = await self.repo.create_interaction(interaction)
        # Quem abriu em nome de outra pessoa está do lado do solicitante: o comentário dele não é a primeira resposta.
        if not ((access.is_creator or access.is_parent_creator) and not access.is_sector_attendant):
            await SlaService(self.session).interaction_added(ticket, user_employee_id, schema.is_internal)

        await self._record_audit_event(
            event_type="ticket.interaction_added",
            ticket_id=ticket.id,
            data={
                "message": schema.message[:150],
                "is_internal": schema.is_internal
            },
            user_id=author_id
        )

        # Notificação via outbox (mesma transação). A regra DEC-012 (nota interna jamais ao solicitante)
        # vive no seletor de audiência `counterpart`.
        # Consulta explícita: não depende de o usuário (e o colaborador dele) já estar carregado na sessão.
        author = (
            await self.session.execute(
                select(UserAccount.email, Employee.name)
                .outerjoin(Employee, Employee.id == UserAccount.employee_id)
                .where(UserAccount.id == author_id)
            )
        ).first()
        author_name = None
        if author:
            author_name = author.name or author.email.split("@")[0].title()
        await self._emit_ticket_event(
            "ticket.interaction_added",
            ticket,
            author_id,
            is_internal=schema.is_internal,
            author_name=author_name,
            excerpt=schema.message[:300],
        )

        return created_interaction

    # ==========================================================================
    # Materials (Consumo de Estoque)
    # ==========================================================================

    async def add_material_to_ticket(
        self,
        ticket_id: uuid.UUID,
        schema: TicketMaterialCreate,
        author_id: uuid.UUID,
        user_employee_id: uuid.UUID | None,
        is_technician: bool,
        can_read_all: bool = False,
        sector_id: uuid.UUID | None = None
    ) -> TicketMaterial:
        if not is_technician:
            raise ForbiddenException("Apenas técnicos podem gerenciar materiais e estoque.")

        ticket = await self.get_ticket_for_user(
            ticket_id=ticket_id,
            user_employee_id=user_employee_id,
            is_technician=is_technician,
            can_read_all=can_read_all,
            user_id=author_id,
            sector_id=sector_id,
        )

        if ticket.status == "CLOSED":
            raise BusinessRuleException("Não é possível adicionar materiais a um chamado fechado.")

        if not self.stock_service:
            raise BusinessRuleException("Serviço de estoque não está disponível no contexto.")

        # Deduzir do estoque (lança HTTPException caso falhe)
        from app.stock.schemas import StockMovementCreate
        mov_schema = StockMovementCreate(
            item_id=schema.stock_item_id,
            movement_type="OUT",
            quantity=schema.quantity,
            notes=f"Consumo via chamado {ticket.id}"
        )
        await self.stock_service.add_movement(mov_schema, author_id)

        # Adicionar o registro no ticket
        material = TicketMaterial(
            ticket_id=ticket.id,
            stock_item_id=schema.stock_item_id,
            quantity=schema.quantity,
            author_id=author_id
        )
        created_material = await self.repo.create_material(material)

        await self._record_audit_event(
            event_type="ticket.material_added",
            ticket_id=ticket.id,
            data={
                "stock_item_id": str(schema.stock_item_id),
                "quantity": schema.quantity
            },
            user_id=author_id
        )

        return created_material

    # ==========================================================================
    # Assets Lifecycle (Reserva, Entrega, Devolução e Inspeção)
    # ==========================================================================

    async def list_tickets_by_asset(self, asset_id: uuid.UUID) -> list[Ticket]:
        return list(await self.repo.list_tickets_by_asset(asset_id))

    async def link_asset_to_ticket(
        self,
        ticket_id: uuid.UUID,
        asset_id: uuid.UUID,
        author_id: uuid.UUID,
        is_technician: bool = False,
    ):
        if not is_technician:
            raise ForbiddenException("Apenas técnicos ou gestores podem vincular ativos a chamados.")

        ticket = await self.repo.get_ticket(ticket_id)
        if not ticket:
            raise NotFoundException("Ticket", ticket_id)

        if not any(a.id == asset_id for a in ticket.assets):
            assets_to_add = await self.repo.get_assets_by_ids([asset_id])
            if not assets_to_add:
                raise NotFoundException("Asset", asset_id)
            ticket.assets.append(assets_to_add[0])
            await self.session.flush()

            await self._record_audit_event(
                event_type="ticket.asset_linked",
                ticket_id=ticket.id,
                data={
                    "asset_id": str(asset_id),
                    "asset_name": assets_to_add[0].name,
                    "asset_tag": assets_to_add[0].tag,
                },
                user_id=author_id,
            )

        return ticket

    async def unlink_asset_from_ticket(
        self,
        ticket_id: uuid.UUID,
        asset_id: uuid.UUID,
        author_id: uuid.UUID,
        is_technician: bool = False,
    ):
        if not is_technician:
            raise ForbiddenException("Apenas técnicos ou gestores podem desvincular ativos de chamados.")

        ticket = await self.repo.get_ticket(ticket_id)
        if not ticket:
            raise NotFoundException("Ticket", ticket_id)

        asset_to_remove = next((a for a in ticket.assets if a.id == asset_id), None)
        if asset_to_remove:
            ticket.assets.remove(asset_to_remove)
            await self.session.flush()

            await self._record_audit_event(
                event_type="ticket.asset_unlinked",
                ticket_id=ticket.id,
                data={
                    "asset_id": str(asset_id),
                    "asset_name": asset_to_remove.name,
                    "asset_tag": asset_to_remove.tag,
                },
                user_id=author_id,
            )

        return ticket

    async def reserve_ticket_asset(
        self,
        ticket_id: uuid.UUID,
        asset_id: uuid.UUID,
        author_id: uuid.UUID,
        user_employee_id: uuid.UUID | None,
        is_technician: bool = False,
        employee_id: uuid.UUID | None = None,
        notes: str | None = None,
        can_read_all: bool = False,
        sector_id: uuid.UUID | None = None,
    ):
        if not is_technician:
            raise ForbiddenException("Apenas técnicos podem gerenciar o ciclo de ativos.")

        ticket = await self.get_ticket_for_user(
            ticket_id=ticket_id,
            user_employee_id=user_employee_id,
            is_technician=is_technician,
            can_read_all=can_read_all,
            user_id=author_id,
            sector_id=sector_id,
        )

        # Se o ativo ainda não estiver associado na lista do chamado, associa automaticamente
        if not any(a.id == asset_id for a in ticket.assets):
            assets_to_add = await self.repo.get_assets_by_ids([asset_id])
            if assets_to_add:
                ticket.assets.append(assets_to_add[0])
                await self.session.flush()

        from app.assets.repository import AssetRepository
        from app.movements.repository import AssetMovementRepository
        from app.movements.services import AssetMovementService

        mov_service = AssetMovementService(AssetMovementRepository(self.session), AssetRepository(self.session))
        target_employee = employee_id or ticket.requester_id
        movement = await mov_service.reserve_asset(
            asset_id=asset_id,
            author_id=author_id,
            employee_id=target_employee,
            ticket_id=ticket.id,
            notes=notes or f"Ativo reservado para o chamado #{str(ticket.id)[:8]}.",
        )

        await self._record_audit_event(
            event_type="ticket.asset_reserved",
            ticket_id=ticket.id,
            data={
                "asset_id": str(asset_id),
                "notes": notes,
            },
            user_id=author_id,
        )

        return movement

    async def deliver_ticket_asset(
        self,
        ticket_id: uuid.UUID,
        asset_id: uuid.UUID,
        author_id: uuid.UUID,
        user_employee_id: uuid.UUID | None,
        is_technician: bool = False,
        employee_id: uuid.UUID | None = None,
        notes: str | None = None,
        can_read_all: bool = False,
        sector_id: uuid.UUID | None = None,
    ):
        if not is_technician:
            raise ForbiddenException("Apenas técnicos podem entregar ativos.")

        ticket = await self.get_ticket_for_user(
            ticket_id=ticket_id,
            user_employee_id=user_employee_id,
            is_technician=is_technician,
            can_read_all=can_read_all,
            user_id=author_id,
            sector_id=sector_id,
        )

        if not any(a.id == asset_id for a in ticket.assets):
            assets_to_add = await self.repo.get_assets_by_ids([asset_id])
            if assets_to_add:
                ticket.assets.append(assets_to_add[0])
                await self.session.flush()

        from app.assets.repository import AssetRepository
        from app.movements.repository import AssetMovementRepository
        from app.movements.services import AssetMovementService

        mov_service = AssetMovementService(AssetMovementRepository(self.session), AssetRepository(self.session))
        target_employee = employee_id or ticket.requester_id
        movement = await mov_service.deliver_asset(
            asset_id=asset_id,
            author_id=author_id,
            employee_id=target_employee,
            ticket_id=ticket.id,
            notes=notes or f"Ativo entregue ao solicitante via chamado #{str(ticket.id)[:8]}.",
        )

        await self._record_audit_event(
            event_type="ticket.asset_delivered",
            ticket_id=ticket.id,
            data={
                "asset_id": str(asset_id),
                "notes": notes,
            },
            user_id=author_id,
        )
        await self._emit_asset_event("ticket.asset_delivered", ticket, asset_id, author_id)

        return movement

    async def _emit_asset_event(self, event_type: str, ticket: Ticket, asset_id: uuid.UUID, actor_id: uuid.UUID) -> None:
        """Equipamento entregue ou devolvido também vai ao outbox (ADR-025 M5), ao lado da auditoria."""
        from app.assets.models import Asset

        asset = await self.session.get(Asset, asset_id)
        await self._emit_ticket_event(
            event_type, ticket, actor_id, asset_id=str(asset_id),
            asset_tag=asset.tag if asset else "", asset_name=asset.name if asset else "",
        )

    async def return_ticket_asset(
        self,
        ticket_id: uuid.UUID,
        asset_id: uuid.UUID,
        author_id: uuid.UUID,
        user_employee_id: uuid.UUID | None,
        is_technician: bool = False,
        notes: str | None = None,
        can_read_all: bool = False,
        sector_id: uuid.UUID | None = None,
    ):
        if not is_technician:
            raise ForbiddenException("Apenas técnicos podem registrar devolução de ativos.")

        ticket = await self.get_ticket_for_user(
            ticket_id=ticket_id,
            user_employee_id=user_employee_id,
            is_technician=is_technician,
            can_read_all=can_read_all,
            user_id=author_id,
            sector_id=sector_id,
        )

        from app.assets.repository import AssetRepository
        from app.movements.repository import AssetMovementRepository
        from app.movements.services import AssetMovementService

        mov_service = AssetMovementService(AssetMovementRepository(self.session), AssetRepository(self.session))
        movement = await mov_service.return_asset(
            asset_id=asset_id,
            author_id=author_id,
            ticket_id=ticket.id,
            notes=notes or f"Ativo devolvido via chamado #{str(ticket.id)[:8]} (aguarda inspeção).",
        )

        await self._record_audit_event(
            event_type="ticket.asset_returned",
            ticket_id=ticket.id,
            data={
                "asset_id": str(asset_id),
                "notes": notes,
            },
            user_id=author_id,
        )
        await self._emit_asset_event("ticket.asset_returned", ticket, asset_id, author_id)

        return movement

    async def inspect_ticket_asset(
        self,
        ticket_id: uuid.UUID,
        asset_id: uuid.UUID,
        approved: bool,
        author_id: uuid.UUID,
        user_employee_id: uuid.UUID | None,
        is_technician: bool = False,
        notes: str | None = None,
        send_to_maintenance: bool = False,
        can_read_all: bool = False,
        sector_id: uuid.UUID | None = None,
    ):
        if not is_technician:
            raise ForbiddenException("Apenas técnicos podem inspecionar ativos.")

        ticket = await self.get_ticket_for_user(
            ticket_id=ticket_id,
            user_employee_id=user_employee_id,
            is_technician=is_technician,
            can_read_all=can_read_all,
            user_id=author_id,
            sector_id=sector_id,
        )

        from app.assets.repository import AssetRepository
        from app.movements.repository import AssetMovementRepository
        from app.movements.services import AssetMovementService

        mov_service = AssetMovementService(AssetMovementRepository(self.session), AssetRepository(self.session))
        movement = await mov_service.inspect_asset(
            asset_id=asset_id,
            author_id=author_id,
            approved=approved,
            ticket_id=ticket.id,
            notes=notes or f"Inspeção técnica concluída via chamado #{str(ticket.id)[:8]}.",
            send_to_maintenance=send_to_maintenance,
        )

        await self._record_audit_event(
            event_type="ticket.asset_inspected",
            ticket_id=ticket.id,
            data={
                "asset_id": str(asset_id),
                "approved": approved,
                "notes": notes,
            },
            user_id=author_id,
        )

        return movement

    # ==========================================================================
    # History & Audit Trail (Vida do Chamado)
    # ==========================================================================

    async def get_ticket_history(
        self,
        ticket_id: uuid.UUID,
        user_employee_id: uuid.UUID | None,
        is_technician: bool = False,
        can_read_all: bool = False,
        can_see_internal: bool = False,
        user_id: uuid.UUID | None = None,
        sector_id: uuid.UUID | None = None
    ) -> list[dict]:
        ticket = await self.get_ticket_for_user(
            ticket_id=ticket_id,
            user_employee_id=user_employee_id,
            is_technician=is_technician,
            can_read_all=can_read_all,
            user_id=user_id,
            sector_id=sector_id,
        )

        from app.audit.models import AuditLog
        from sqlalchemy import select

        stmt = (
            select(AuditLog)
            .where(AuditLog.entity_type == "ticket", AuditLog.entity_id == ticket_id)
            .order_by(AuditLog.created_at.asc())
        )
        res = await self.session.execute(stmt)
        logs = list(res.scalars().all())

        can_view_int = await self.can_see_internal(
            ticket, is_technician or can_see_internal, user_employee_id=user_employee_id, user_id=user_id,
            sector_id=sector_id, is_technician=is_technician, can_read_all=can_read_all,
        )
        history = []
        for log in logs:
            if not can_view_int and log.event_type == "ticket.interaction_added" and log.data.get("is_internal"):
                continue

            action, desc = self._format_history_description(log.event_type, log.data, log.user_name)
            history.append({
                "id": log.id,
                "event_type": log.event_type,
                "action": action,
                "description": desc,
                "user_name": log.user_name,
                "user_email": log.user_email,
                "data": log.data,
                "created_at": log.created_at
            })

        has_created = any(h["event_type"] == "ticket.created" for h in history)
        if not has_created:
            history.insert(0, {
                "id": uuid.uuid4(),
                "event_type": "ticket.created",
                "action": "Abertura de Chamado",
                "description": f"Chamado aberto com prioridade {ticket.priority}.",
                "user_name": ticket.requester_name or "Solicitante",
                "user_email": None,
                "data": {"status": "OPENED", "priority": ticket.priority},
                "created_at": ticket.created_at
            })

        return history

    async def get_tickets_summary_report(self, start: date | None = None, end: date | None = None) -> TicketsReport:
        """Resumo gerencial (Gestão e Administração): chamados criados no período e indicadores de SLA.

        As datas são dias no fuso `APP_TIMEZONE`, com `end` incluído; sem datas, todo o histórico. As contagens saem
        agregadas do banco (antes carregava todos os chamados em memória).
        """
        if start and end and start > end:
            raise ValidationException("A data inicial deve ser anterior ou igual à final.")
        from app.notifications.jobs import local_timezone  # import tardio: o módulo de jobs importa serviços

        tz = local_timezone()
        start_at = datetime.combine(start, time.min, tz) if start else None
        end_at = datetime.combine(end + timedelta(days=1), time.min, tz) if end else None

        def in_period(stmt):
            if start_at is not None:
                stmt = stmt.where(Ticket.created_at >= start_at)
            if end_at is not None:
                stmt = stmt.where(Ticket.created_at < end_at)
            return stmt

        status_counts = {"OPENED": 0, "IN_PROGRESS": 0, "PENDING": 0, "RESOLVED": 0, "CLOSED": 0, "CANCELED": 0}
        priority_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
        for column, counts in ((Ticket.status, status_counts), (Ticket.priority, priority_counts)):
            rows = await self.session.execute(in_period(select(column, func.count()).group_by(column)))
            for value, count in rows.all():
                if value in counts:
                    counts[value] = count
        category_rows = await self.session.execute(
            in_period(
                select(TicketCategory.name, func.count(Ticket.id))
                .select_from(Ticket)
                .outerjoin(TicketCategory, TicketCategory.id == Ticket.category_id)
                .group_by(TicketCategory.name)
            )
        )
        by_category = sorted(
            (CategoryCount(category=name or "Sem Categoria", count=count) for name, count in category_rows.all()),
            key=lambda c: (-c.count, c.category.casefold()),
        )
        total = (await self.session.execute(in_period(select(func.count(Ticket.id))))).scalar_one()

        resolved_or_closed = status_counts["RESOLVED"] + status_counts["CLOSED"]
        resolution_rate = round((resolved_or_closed / total) * 100, 1) if total > 0 else 100.0

        return TicketsReport(
            start=start, end=end, total_tickets=total, resolution_rate_percent=resolution_rate,
            by_status=status_counts, by_priority=priority_counts, by_category=by_category,
            sla=await sla_report(self.session, start_at, end_at),
        )

    def _format_history_description(self, event_type: str, data: dict, user_name: str | None) -> tuple[str, str]:
        by_user = f" por {user_name}" if user_name else ""
        if event_type == "ticket.created":
            prio = data.get("priority", "LOW")
            return "Abertura de Chamado", f"Chamado aberto{by_user} com prioridade {prio}."
        elif event_type == "ticket.status_changed":
            old_s = self._translate_status(data.get("old_status", ""))
            new_s = self._translate_status(data.get("new_status", ""))
            note = f" (Obs: {data['notes']})" if data.get("notes") else ""
            return "Mudança de Status", f"Status alterado de '{old_s}' para '{new_s}'{by_user}.{note}"
        elif event_type == "ticket.closed":
            s = self._translate_status(data.get("status", "CLOSED"))
            note = f" (Resolução: {data['notes']})" if data.get("notes") else ""
            return "Finalização", f"Chamado finalizado ({s}){by_user}.{note}"
        elif event_type == "ticket.priority_changed":
            return "Mudança de Prioridade", f"Prioridade alterada de {data.get('old_priority')} para {data.get('new_priority')}{by_user}."
        elif event_type == "ticket.assigned":
            return "Atribuição", f"Chamado atribuído a técnico responsável{by_user}."
        elif event_type == "ticket.interaction_added":
            is_int = data.get("is_internal", False)
            tipo = "Nota interna" if is_int else "Resposta/Interação pública"
            return "Nova Interação", f"{tipo} adicionada{by_user}."
        elif event_type == "ticket.material_added":
            qtd = data.get("quantity", 1)
            return "Consumo de Insumo", f"Insumo do estoque lançado (Qtd: {qtd}){by_user}."
        elif event_type == "ticket.asset_linked":
            tag = data.get("asset_tag", "")
            name = data.get("asset_name", "")
            return "Equipamento Vinculado", f"Ativo #{tag} ({name}) vinculado ao chamado{by_user}."
        elif event_type == "ticket.asset_unlinked":
            tag = data.get("asset_tag", "")
            name = data.get("asset_name", "")
            return "Equipamento Desvinculado", f"Ativo #{tag} ({name}) desvinculado do chamado{by_user}."
        elif event_type == "ticket.asset_reserved":
            return "Equipamento Reservado", f"Ativo patrimonial reservado para o chamado{by_user}."
        elif event_type == "ticket.asset_delivered":
            return "Equipamento Entregue", f"Ativo entregue ao solicitante com emissão de Termo de Responsabilidade{by_user}."
        elif event_type == "ticket.asset_returned":
            return "Equipamento Devolvido", f"Ativo devolvido fisicamente e encaminhado para inspeção técnica{by_user}."
        elif event_type == "ticket.asset_inspected":
            aprovado = "Aprovado e liberado para estoque" if data.get("approved") else "Reprovado (encaminhado para manutenção)"
            return "Inspeção Técnica de Ativo", f"Conferência concluída: {aprovado}{by_user}."
        elif event_type == "ticket.children_added":
            children = data.get("children") or []
            sectors = ", ".join(c.get("sector_name") or "?" for c in children)
            return "Subchamados Incluídos", f"{len(children)} subchamado(s) incluído(s){by_user}: {sectors}."
        elif event_type == "ticket.child_completed":
            return "Etapa Concluída", f"Subchamado '{data.get('title', '')}' concluído."
        elif event_type == "ticket.child_canceled":
            return "Etapa Cancelada", f"Subchamado '{data.get('title', '')}' cancelado{by_user}. Motivo: {data.get('reason', '')}"
        elif event_type == "ticket.canceled":
            return "Cancelamento", f"Subchamado cancelado{by_user}. Motivo: {data.get('reason', '')}"
        elif event_type == "ticket.child_replaced":
            return "Etapa Substituída", f"Etapa cancelada substituída por outro subchamado{by_user}. Motivo: {data.get('reason', '')}"
        elif event_type == "ticket.requirement_changed":
            kind = "obrigatória" if data.get("is_required") else "não obrigatória"
            return "Obrigatoriedade", f"Etapa marcada como {kind}{by_user}. Motivo: {data.get('reason', '')}"
        return event_type, f"Ação '{event_type}' executada{by_user}."

    def _translate_status(self, status: str) -> str:
        mapping = {
            "OPENED": "Aberto",
            "IN_PROGRESS": "Em Atendimento",
            "PENDING": "Pendente",
            "RESOLVED": "Resolvido",
            "CLOSED": "Encerrado",
            "CANCELED": "Cancelado",
        }
        return mapping.get(status, status)

    async def _ensure_reopen_window(self, ticket: Ticket) -> None:
        """Reabrir só vale por `TICKET_REOPEN_DAYS` dias depois de resolvido (quem tem Gerenciar SLA pode além disso)."""
        days = get_settings().TICKET_REOPEN_DAYS
        resolved_at = await SlaService(self.session).resolved_at(ticket)
        if resolved_at is not None and sla_now() - resolved_at > timedelta(days=days):
            raise ValidationException(
                f"O prazo para reabrir este chamado ({days} dias após a resolução) acabou. Abra um novo chamado."
            )

    async def _emit_ticket_event(self, event_type: str, ticket: Ticket, actor_id: uuid.UUID | None, **extra) -> None:
        """Registra o fato no outbox (mesma transação do chamado); o worker decide quem é avisado e por onde."""
        priority = {"LOW": "low", "HIGH": "high", "CRITICAL": "high"}.get(ticket.priority, "normal")
        payload = {
            "ticket_id": str(ticket.id),
            "title": ticket.title[:200],
            "priority": ticket.priority,
            "status": ticket.status,
            "requester_employee_id": str(ticket.requester_id),
            "assignee_id": str(ticket.assignee_id) if ticket.assignee_id else None,
            "responsible_sector_id": str(ticket.responsible_sector_id),
            # Seletor `creator` e regra do solicitante (ignora o `ticket.created` de cada subchamado), ADR-026.
            "created_by_user_id": str(ticket.created_by_user_id) if ticket.created_by_user_id else None,
            "parent_ticket_id": str(ticket.parent_ticket_id) if ticket.parent_ticket_id else None,
            **extra,
        }
        await emit_event(
            self.session, event_type, "ticket", ticket.id, payload, actor_user_id=actor_id, priority=priority
        )

    async def _record_audit_event(
        self, event_type: str, ticket_id: uuid.UUID, data: dict, user_id: uuid.UUID | None
    ) -> None:
        """Grava o evento na mesma transação do chamado (única escrita; não emitir também no event_bus)."""
        try:
            from app.audit.repository import AuditRepository
            audit_repo = AuditRepository(self.session)
            await audit_repo.create(
                event_type=event_type,
                entity_type="ticket",
                entity_id=ticket_id,
                data=data,
                user_id=user_id,
            )
        except Exception:
            logger.exception("Falha ao gravar registro de auditoria no banco")
