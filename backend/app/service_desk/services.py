"""
MOD-04 — Service Desk (Services)

Implementa as regras de negócio de visualização e transição de chamados.
"""

import logging
import uuid
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.core.exceptions import (
    BusinessRuleException,
    ForbiddenException,
    NotFoundException,
    StateTransitionException,
)
from app.organization.models import Employee
from app.service_desk.models import Ticket, TicketCategory, TicketInteraction, TicketMaterial
from app.service_desk.repository import ServiceDeskRepository
from app.service_desk.schemas import (
    TicketCreate,
    TicketInteractionCreate,
    TicketUpdate,
    TicketCategoryCreate,
    TicketCategoryUpdate,
    TicketMaterialCreate,
)


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

    async def create_category(self, schema: TicketCategoryCreate) -> TicketCategory:
        cat = TicketCategory(
            name=schema.name,
            description=schema.description,
            is_active=schema.is_active,
            default_sector_id=schema.default_sector_id,
            form_schema=schema.form_schema or []
        )
        return await self.repo.create_category(cat)

    async def update_category(self, category_id: uuid.UUID, schema: TicketCategoryUpdate) -> TicketCategory:
        cat = await self.repo.get_category(category_id)
        if not cat:
            raise NotFoundException("TicketCategory", category_id)

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
        Busca um ticket e garante as regras de menor privilégio e escopo:
        - Gestores ou Administradores (can_read_all=True) veem qualquer chamado.
        - Atendentes (is_technician=True) veem chamados do seu setor responsável, atribuídos a si ou abertos por si.
        - Solicitantes comuns só veem seus próprios chamados.
        """
        ticket = await self.repo.get_ticket(ticket_id)
        if not ticket:
            raise NotFoundException("Chamado", ticket_id)

        if can_read_all:
            return ticket

        if is_technician:
            if sector_id is None and user_employee_id is not None:
                emp = await self.session.get(Employee, user_employee_id)
                if emp:
                    sector_id = emp.sector_id

            if (
                can_read_all
                or (sector_id is not None and ticket.responsible_sector_id == sector_id)
                or (user_id is not None and ticket.assignee_id == user_id)
                or (user_employee_id is not None and ticket.requester_id == user_employee_id)
            ):
                return ticket
            raise ForbiddenException("Você não tem acesso a chamados de outros setores.")

        if not user_employee_id or ticket.requester_id != user_employee_id:
            raise ForbiddenException("Você não tem acesso a este chamado.")

        return ticket

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

        # 2. Atendentes veem chamados destinados ao seu setor, atribuídos a si ou abertos por si
        if is_technician:
            return await self.repo.list_tickets(
                requester_id=user_employee_id,
                sector_id=sector_id,
                assignee_id=user_id,
                is_attendant_scope=True,
            )

        # 3. Solicitantes veem apenas os próprios chamados
        if not user_employee_id:
            return []
        return await self.repo.list_tickets(requester_id=user_employee_id)

    async def create_ticket(
        self, 
        schema: TicketCreate, 
        requester_id: uuid.UUID,
        origin_unit_id: uuid.UUID,
        origin_sector_id: uuid.UUID,
        user_id: uuid.UUID | None = None
    ) -> Ticket:
        responsible_sector_id = schema.responsible_sector_id
        
        if schema.category_id:
            cat = await self.repo.get_category(schema.category_id)
            if not cat or not cat.is_active:
                raise BusinessRuleException("Categoria inválida ou inativa.")
            if not responsible_sector_id:
                responsible_sector_id = cat.default_sector_id
            
            # Validação dos pré-requisitos vinculados ao formulário da categoria
            if cat.form_schema:
                provided_fields = schema.custom_fields or {}
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
        
        if not responsible_sector_id:
            raise BusinessRuleException("Setor responsável não definido. Informe-o manualmente ou selecione uma categoria com roteamento automático.")

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
            title=schema.title,
            description=schema.description,
            priority=schema.priority,
            category_id=schema.category_id,
            custom_fields=schema.custom_fields or {},
            requester_id=requester_id,
            origin_unit_id=origin_unit_id,
            origin_sector_id=origin_sector_id,
            responsible_sector_id=responsible_sector_id,
            status="OPENED",
            is_demo=is_demo_ticket
        )
        
        if schema.asset_ids:
            assets = await self.repo.get_assets_by_ids(schema.asset_ids)
            ticket.assets = list(assets)
            
        ticket = await self.repo.create_ticket(ticket)
        loaded_ticket = await self.repo.get_ticket(ticket.id)

        await self._record_audit_event(
            event_type="ticket.created",
            ticket_id=loaded_ticket.id,
            data={
                "title": loaded_ticket.title,
                "priority": loaded_ticket.priority,
                "status": loaded_ticket.status,
                "category_id": str(loaded_ticket.category_id) if loaded_ticket.category_id else None
            },
            user_id=user_id
        )

        return loaded_ticket

    async def update_ticket(
        self, 
        ticket_id: uuid.UUID, 
        schema: TicketUpdate, 
        is_technician: bool,
        user_employee_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        sector_id: uuid.UUID | None = None,
        can_read_all: bool = False
    ) -> Ticket:
        ticket = await self.repo.get_ticket(ticket_id)
        if not ticket:
            raise NotFoundException("Chamado", ticket_id)

        is_requester = (user_employee_id is not None and ticket.requester_id == user_employee_id)
        is_sector_attendant = is_technician and (
            can_read_all
            or (sector_id is not None and ticket.responsible_sector_id == sector_id)
            or (user_id is not None and ticket.assignee_id == user_id)
        )

        # Regras de autorização para alteração do chamado
        if not is_sector_attendant:
            if not is_requester:
                raise ForbiddenException("Apenas o atendente responsável pelo setor ou o solicitante podem gerenciar este chamado.")
            
            # Solicitante só tem permissão para finalizar/encerrar seu próprio chamado (RESOLVED ou CLOSED)
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
            ticket.status = schema.status

        if schema.custom_fields is not None:
            ticket.custom_fields = schema.custom_fields

        if schema.asset_ids is not None:
            assets = await self.repo.get_assets_by_ids(schema.asset_ids)
            ticket.assets = list(assets)

        updated_ticket = await self.repo.update_ticket(ticket)

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

        if ticket.status == "CLOSED":
            raise BusinessRuleException("Não é possível adicionar interações a um chamado fechado.")

        can_internal = is_technician or can_internal_notes
        if schema.is_internal and not can_internal:
            raise ForbiddenException("Apenas técnicos ou gestores podem criar notas internas.")

        interaction = TicketInteraction(
            ticket_id=ticket.id,
            author_id=author_id,
            message=schema.message,
            is_internal=schema.is_internal
        )
        created_interaction = await self.repo.create_interaction(interaction)

        await self._record_audit_event(
            event_type="ticket.interaction_added",
            ticket_id=ticket.id,
            data={
                "message": schema.message[:150],
                "is_internal": schema.is_internal
            },
            user_id=author_id
        )

        # Disparo seguro de notificação por e-mail (respeitando DEC-012)
        try:
            from app.identity.models import UserAccount
            from app.notifications.email_service import EmailService
            from sqlalchemy import select
            stmt_author = select(UserAccount).where(UserAccount.id == author_id)
            author = (await self.session.execute(stmt_author)).scalar_one_or_none()
            if author:
                email_svc = EmailService(self.session)
                await email_svc.notify_ticket_interaction(
                    ticket=ticket,
                    interaction=created_interaction,
                    author=author
                )
        except Exception:
            logger.exception("Falha ao processar notificações por e-mail do chamado %s", ticket.id)

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

        return movement

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

        can_view_int = is_technician or can_see_internal
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

    async def get_tickets_summary_report(self) -> dict:
        """Gera resumo gerencial de métricas para o perfil de Gestão e Administração."""
        tickets = await self.repo.list_tickets()
        total = len(tickets)
        status_counts = {"OPENED": 0, "IN_PROGRESS": 0, "PENDING": 0, "RESOLVED": 0, "CLOSED": 0}
        priority_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
        by_category: dict[str, int] = {}

        for t in tickets:
            st = t.status
            if st in status_counts:
                status_counts[st] += 1
            prio = t.priority
            if prio in priority_counts:
                priority_counts[prio] += 1
            cat_name = t.category.name if t.category else "Sem Categoria"
            by_category[cat_name] = by_category.get(cat_name, 0) + 1

        resolved_or_closed = status_counts["RESOLVED"] + status_counts["CLOSED"]
        resolution_rate = round((resolved_or_closed / total) * 100, 1) if total > 0 else 100.0

        return {
            "total_tickets": total,
            "resolution_rate_percent": resolution_rate,
            "by_status": status_counts,
            "by_priority": priority_counts,
            "by_category": [{"category": k, "count": v} for k, v in by_category.items()],
        }

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
        return event_type, f"Ação '{event_type}' executada{by_user}."

    def _translate_status(self, status: str) -> str:
        mapping = {
            "OPENED": "Aberto",
            "IN_PROGRESS": "Em Atendimento",
            "PENDING": "Pendente",
            "RESOLVED": "Resolvido",
            "CLOSED": "Encerrado",
        }
        return mapping.get(status, status)

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
