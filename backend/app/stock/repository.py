import uuid
from typing import Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.stock.models import StockItem, StockMovement

class StockRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_items(self, unit_id: uuid.UUID = None) -> Sequence[StockItem]:
        stmt = select(StockItem)
        if unit_id:
            stmt = stmt.where(StockItem.unit_id == unit_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_item(self, item_id: uuid.UUID) -> StockItem | None:
        return await self.session.get(StockItem, item_id)

    async def create_item(self, item: StockItem) -> StockItem:
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def update_item(self, item: StockItem) -> StockItem:
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def create_movement(self, movement: StockMovement) -> StockMovement:
        self.session.add(movement)
        await self.session.flush()
        await self.session.refresh(movement)
        return movement

    async def get_movements_by_item(self, item_id: uuid.UUID) -> Sequence[StockMovement]:
        stmt = select(StockMovement).where(StockMovement.item_id == item_id).order_by(StockMovement.created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()
