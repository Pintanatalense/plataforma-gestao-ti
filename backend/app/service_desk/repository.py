"""
MOD-04 — Service Desk (Repository)
"""

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.service_desk.models import Ticket, TicketCategory, TicketInteraction, TicketMaterial
from app.assets.models import Asset


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

    async def create_category(self, category: TicketCategory) -> TicketCategory:
        self.session.add(category)
        await self.session.flush()
        await self.session.refresh(category)
        return category

    async def update_category(self, category: TicketCategory) -> TicketCategory:
        await self.session.flush()
        await self.session.refresh(category)
        return category

    # ==========================================================================
    # Tickets
    # ==========================================================================

    async def get_ticket(self, ticket_id: uuid.UUID) -> Ticket | None:
        """Busca ticket e eager load nas interações, categoria e insumos."""
        stmt = (
            select(Ticket)
            .options(selectinload(Ticket.category))
            .options(selectinload(Ticket.interactions))
            .options(selectinload(Ticket.materials))
            .options(selectinload(Ticket.assets))
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
        stmt = (
            select(Ticket)
            .options(selectinload(Ticket.category))
            .options(selectinload(Ticket.interactions))
            .options(selectinload(Ticket.materials))
            .options(selectinload(Ticket.assets))
            .order_by(Ticket.created_at.desc())
        )
        
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

    async def get_assets_by_ids(self, asset_ids: list[uuid.UUID]) -> Sequence[Asset]:
        stmt = select(Asset).where(Asset.id.in_(asset_ids))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    # ==========================================================================
    # Ticket Interactions
    # ==========================================================================

    async def create_interaction(self, interaction: TicketInteraction) -> TicketInteraction:
        self.session.add(interaction)
        await self.session.flush()
        await self.session.refresh(interaction)
        return interaction

    # ==========================================================================
    # Ticket Materials
    # ==========================================================================

    async def create_material(self, material: TicketMaterial) -> TicketMaterial:
        self.session.add(material)
        await self.session.flush()
        await self.session.refresh(material)
        return material
