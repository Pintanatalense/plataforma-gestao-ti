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
        self, ticket_id: uuid.UUID, user_employee_id: uuid.UUID | None, is_technician: bool
    ) -> Ticket:
        """
        Busca um ticket e garante as regras de visualização:
        - Técnicos (is_technician=True) veem tudo.
        - Colaboradores (is_technician=False) só veem seus próprios chamados.
        """
        ticket = await self.repo.get_ticket(ticket_id)
        if not ticket:
            raise NotFoundException("Chamado", ticket_id)

        if not is_technician:
            if not user_employee_id or ticket.requester_id != user_employee_id:
                raise ForbiddenException("Você não tem acesso a este chamado.")

        return ticket

    async def list_tickets_for_user(
        self, user_employee_id: uuid.UUID | None, is_technician: bool
    ) -> Sequence[Ticket]:
        if is_technician:
            return await self.repo.list_tickets()
        else:
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
            status="OPENED"
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
        user_id: uuid.UUID | None = None
    ) -> Ticket:
        ticket = await self.repo.get_ticket(ticket_id)
        if not ticket:
            raise NotFoundException("Chamado", ticket_id)

        is_requester = (user_employee_id is not None and ticket.requester_id == user_employee_id)

        # Regras de autorização para alteração do chamado
        if not is_technician:
            if not is_requester:
                raise ForbiddenException("Apenas técnicos ou o próprio solicitante podem gerenciar este chamado.")
            
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
        is_technician: bool
    ) -> TicketInteraction:
        ticket = await self.get_ticket_for_user(ticket_id, user_employee_id, is_technician)

        if ticket.status == "CLOSED":
            raise BusinessRuleException("Não é possível adicionar interações a um chamado fechado.")

        if schema.is_internal and not is_technician:
            raise ForbiddenException("Apenas técnicos podem criar notas internas.")

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
        is_technician: bool
    ) -> TicketMaterial:
        if not is_technician:
            raise ForbiddenException("Apenas técnicos podem gerenciar materiais e estoque.")

        ticket = await self.get_ticket_for_user(ticket_id, user_employee_id, is_technician)

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
    # History & Audit Trail (Vida do Chamado)
    # ==========================================================================

    async def get_ticket_history(
        self,
        ticket_id: uuid.UUID,
        user_employee_id: uuid.UUID | None,
        is_technician: bool
    ) -> list[dict]:
        ticket = await self.get_ticket_for_user(ticket_id, user_employee_id, is_technician)

        from app.audit.models import AuditLog
        from sqlalchemy import select

        stmt = (
            select(AuditLog)
            .where(AuditLog.entity_type == "ticket", AuditLog.entity_id == ticket_id)
            .order_by(AuditLog.created_at.asc())
        )
        res = await self.session.execute(stmt)
        logs = list(res.scalars().all())

        history = []
        for log in logs:
            if not is_technician and log.event_type == "ticket.interaction_added" and log.data.get("is_internal"):
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

        try:
            from app.core.events import Event, event_bus
            await event_bus.emit(Event(
                event_type=event_type,
                entity_type="ticket",
                entity_id=ticket_id,
                data=data,
                user_id=user_id,
            ))
        except Exception:
            logger.exception("Falha ao emitir evento no event_bus")

