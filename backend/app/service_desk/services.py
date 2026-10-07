"""
MOD-04 — Service Desk (Services)

Implementa as regras de negócio de visualização e transição de chamados.
"""

import uuid
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BusinessRuleException,
    ForbiddenException,
    NotFoundException,
    StateTransitionException,
)
from app.service_desk.models import Ticket, TicketCategory, TicketInteraction
from app.service_desk.repository import ServiceDeskRepository
from app.service_desk.schemas import (
    TicketCreate,
    TicketInteractionCreate,
    TicketUpdate,
)


class ServiceDeskService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = ServiceDeskRepository(session)

    # ==========================================================================
    # Categories
    # ==========================================================================
    
    async def list_categories(self) -> Sequence[TicketCategory]:
        return await self.repo.list_categories()

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
            
            # Filtra interações internas para o usuário final! (DEC-012)
            ticket.interactions = [i for i in ticket.interactions if not i.is_internal]

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

    async def create_ticket(self, schema: TicketCreate, requester_id: uuid.UUID) -> Ticket:
        if schema.category_id:
            cat = await self.repo.get_category(schema.category_id)
            if not cat or not cat.is_active:
                raise BusinessRuleException("Categoria inválida ou inativa.")

        ticket = Ticket(
            title=schema.title,
            description=schema.description,
            priority=schema.priority,
            category_id=schema.category_id,
            requester_id=requester_id,
            status="OPENED"
        )
        return await self.repo.create_ticket(ticket)

    async def update_ticket(
        self, ticket_id: uuid.UUID, schema: TicketUpdate, is_technician: bool
    ) -> Ticket:
        # Apenas técnicos alteram status/prioridade/responsável (em teoria)
        if not is_technician:
            raise ForbiddenException("Apenas técnicos podem gerenciar chamados.")

        ticket = await self.repo.get_ticket(ticket_id)
        if not ticket:
            raise NotFoundException("Chamado", ticket_id)

        if schema.category_id is not None:
            cat = await self.repo.get_category(schema.category_id)
            if not cat or not cat.is_active:
                raise BusinessRuleException("Categoria inválida ou inativa.")
            ticket.category_id = schema.category_id

        if schema.assignee_id is not None:
            # TODO: Ideal seria checar via IdentityService se assignee_id é um técnico válido
            ticket.assignee_id = schema.assignee_id

        if schema.priority is not None:
            ticket.priority = schema.priority

        if schema.status is not None:
            # Regras de máquina de estados simples:
            if ticket.status == "CLOSED" and schema.status != "CLOSED":
                raise StateTransitionException("Chamado", ticket.status, schema.status)
            ticket.status = schema.status

        return await self.repo.update_ticket(ticket)

    # ==========================================================================
    # Interactions (Comentários)
    # ==========================================================================

    async def add_interaction(
        self, 
        ticket_id: uuid.UUID, 
        schema: TicketInteractionCreate, 
        author_id: uuid.UUID,
        user_employee_id: uuid.UUID | None,
        is_technician: bool
    ) -> TicketInteraction:
        
        # O get_ticket_for_user já valida a permissão de visualização do ticket
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
        return await self.repo.create_interaction(interaction)
