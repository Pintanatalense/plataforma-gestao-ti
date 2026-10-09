import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.movements.models import AssetMovement


class AssetMovementRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_movements_by_asset(self, asset_id: uuid.UUID) -> Sequence[AssetMovement]:
        stmt = (
            select(AssetMovement)
            .where(AssetMovement.asset_id == asset_id)
            .order_by(AssetMovement.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_movement(self, movement: AssetMovement) -> AssetMovement:
        self.session.add(movement)
        await self.session.flush()
        return movement
