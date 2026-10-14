import uuid
from typing import Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.stock.models import StockCategory, StockItem, StockMovement


class StockRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # --- Categories ---
    async def get_categories(self) -> Sequence[StockCategory]:
        stmt = (
            select(StockCategory)
            .where(StockCategory.is_active == True)  # noqa: E712
            .order_by(StockCategory.name.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_category(self, category_id: uuid.UUID) -> StockCategory | None:
        stmt = (
            select(StockCategory)
            .where(StockCategory.id == category_id, StockCategory.is_active == True)  # noqa: E712
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_category_by_name(self, name: str) -> StockCategory | None:
        stmt = (
            select(StockCategory)
            .where(StockCategory.name == name, StockCategory.is_active == True)  # noqa: E712
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_category(self, category: StockCategory) -> StockCategory:
        self.session.add(category)
        await self.session.flush()
        await self.session.refresh(category)
        return category

    async def update_category(self, category: StockCategory) -> StockCategory:
        self.session.add(category)
        await self.session.flush()
        await self.session.refresh(category)
        return category

    async def delete_category(self, category: StockCategory) -> None:
        category.soft_delete()
        self.session.add(category)
        await self.session.flush()

    # --- Items ---
    async def get_items(self, unit_id: uuid.UUID = None) -> Sequence[StockItem]:
        stmt = (
            select(StockItem)
            .options(joinedload(StockItem.category))
            .order_by(StockItem.name.asc())
        )
        if unit_id:
            stmt = stmt.where(StockItem.unit_id == unit_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_item(self, item_id: uuid.UUID) -> StockItem | None:
        stmt = (
            select(StockItem)
            .options(joinedload(StockItem.category))
            .where(StockItem.id == item_id)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_item(self, item: StockItem) -> StockItem:
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return await self.get_item(item.id)

    async def update_item(self, item: StockItem) -> StockItem:
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return await self.get_item(item.id)

    # --- Movements ---
    async def create_movement(self, movement: StockMovement) -> StockMovement:
        self.session.add(movement)
        await self.session.flush()
        await self.session.refresh(movement)
        return movement

    async def get_movements_by_item(self, item_id: uuid.UUID) -> Sequence[StockMovement]:
        stmt = select(StockMovement).where(StockMovement.item_id == item_id).order_by(StockMovement.created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()
