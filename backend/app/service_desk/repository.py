"""
MOD-04 — Service Desk (Repository)
"""

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.service_desk.models import Ticket, TicketCategory, TicketInteraction


class ServiceDeskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ==========================================================================
    # Ticket Categories
    # ==========================================================================

    async def list_categories(self, only_active: bool = True) -> Sequence[TicketCategory]:
        stmt = select(TicketCategory)
        if only_active:
            stmt = stmt.where(TicketCategory.is_active == True)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_category(self, category_id: uuid.UUID) -> TicketCategory | None:
        stmt = select(TicketCategory).where(TicketCategory.id == category_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # ==========================================================================
    # Tickets
    # ==========================================================================

    async def get_ticket(self, ticket_id: uuid.UUID) -> Ticket | None:
        """Busca ticket e eager load nas interações."""
        stmt = (
            select(Ticket)
            .options(selectinload(Ticket.interactions))
            .where(Ticket.id == ticket_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_tickets(
        self, requester_id: uuid.UUID | None = None
    ) -> Sequence[Ticket]:
        """
        Lista tickets.
        Se requester_id for fornecido, filtra apenas os tickets abertos por ele.
        """
        stmt = select(Ticket).order_by(Ticket.created_at.desc())
        
        if requester_id:
            stmt = stmt.where(Ticket.requester_id == requester_id)
            
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_ticket(self, ticket: Ticket) -> Ticket:
        self.session.add(ticket)
        await self.session.flush()
        await self.session.refresh(ticket)
        return ticket

    async def update_ticket(self, ticket: Ticket) -> Ticket:
        await self.session.flush()
        await self.session.refresh(ticket)
        return ticket

    # ==========================================================================
    # Ticket Interactions
    # ==========================================================================

    async def create_interaction(self, interaction: TicketInteraction) -> TicketInteraction:
        self.session.add(interaction)
        await self.session.flush()
        await self.session.refresh(interaction)
        return interaction
