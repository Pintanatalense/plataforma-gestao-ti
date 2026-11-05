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
            stmt = stmt.where(TicketCategory.is_active.is_(True))
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
        self,
        requester_id: uuid.UUID | None = None,
        sector_id: uuid.UUID | None = None,
        assignee_id: uuid.UUID | None = None,
        is_attendant_scope: bool = False,
        created_by_id: uuid.UUID | None = None,
    ) -> Sequence[Ticket]:
        """
        Lista tickets com suporte a menor privilégio e escopo setorial:
        - is_attendant_scope=True: chamados do seu setor responsável, atribuídos a si, solicitados ou abertos por si.
        - requester_id/created_by_id: só os chamados em que é solicitante ou que abriu (criador).
        - Sem filtros: visualização irrestrita de todos os chamados (Gestão / Administrador).
        """
        stmt = (
            select(Ticket)
            .options(selectinload(Ticket.category))
            .options(selectinload(Ticket.interactions))
            .options(selectinload(Ticket.materials))
            .options(selectinload(Ticket.assets))
            .order_by(Ticket.created_at.desc())
        )
        
        if is_attendant_scope:
            from sqlalchemy import or_
            conditions = []
            if sector_id:
                conditions.append(Ticket.responsible_sector_id == sector_id)
            if assignee_id:
                conditions.append(Ticket.assignee_id == assignee_id)
            if requester_id:
                conditions.append(Ticket.requester_id == requester_id)
            if created_by_id:
                conditions.append(Ticket.created_by_user_id == created_by_id)
            if conditions:
                stmt = stmt.where(or_(*conditions))
        elif requester_id or created_by_id:
            from sqlalchemy import or_
            own = []
            if requester_id:
                own.append(Ticket.requester_id == requester_id)
            if created_by_id:
                own.append(Ticket.created_by_user_id == created_by_id)
            stmt = stmt.where(or_(*own))
            
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

    async def list_tickets_by_asset(self, asset_id: uuid.UUID) -> Sequence[Ticket]:
        stmt = (
            select(Ticket)
            .join(Ticket.assets)
            .where(Asset.id == asset_id)
            .options(
                selectinload(Ticket.category),
                selectinload(Ticket.interactions),
                selectinload(Ticket.assets),
            )
            .order_by(Ticket.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

