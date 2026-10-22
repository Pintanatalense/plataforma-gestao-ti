import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.assets.models import Asset, AssetCategory


class AssetRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_category(self, category_id: uuid.UUID) -> AssetCategory | None:
        return await self.session.get(AssetCategory, category_id)

    async def list_categories(self) -> Sequence[AssetCategory]:
        stmt = select(AssetCategory).where(AssetCategory.is_active.is_(True)).order_by(AssetCategory.name)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_category(self, category: AssetCategory) -> AssetCategory:
        self.session.add(category)
        await self.session.flush()
        return category

    async def update_category(self, category: AssetCategory) -> AssetCategory:
        await self.session.flush()
        return category

    async def get_asset(self, asset_id: uuid.UUID) -> Asset | None:
        stmt = (
            select(Asset)
            .options(
                selectinload(Asset.category),
                selectinload(Asset.unit),
                selectinload(Asset.employee),
            )
            .where(Asset.id == asset_id, Asset.is_active.is_(True))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_asset_for_update(self, asset_id: uuid.UUID) -> Asset | None:
        stmt = select(Asset).options(selectinload(Asset.category)).where(Asset.id == asset_id, Asset.is_active.is_(True)).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
        
    async def get_asset_by_tag(self, tag: str) -> Asset | None:
        stmt = (
            select(Asset)
            .options(
                selectinload(Asset.category),
                selectinload(Asset.unit),
                selectinload(Asset.employee),
            )
            .where(Asset.tag == tag, Asset.is_active.is_(True))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_asset_by_serial_number(self, serial_number: str, include_inactive: bool = False) -> Asset | None:
        # O índice único vale também para ativos inativos; por isso há a opção de enxergá-los.
        stmt = (
            select(Asset)
            .options(
                selectinload(Asset.category),
                selectinload(Asset.unit),
                selectinload(Asset.employee),
            )
            .where(Asset.serial_number == serial_number)
        )
        if not include_inactive:
            stmt = stmt.where(Asset.is_active.is_(True))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_assets(self, unit_id: uuid.UUID | None = None, employee_id: uuid.UUID | None = None) -> Sequence[Asset]:
        stmt = (
            select(Asset)
            .options(
                selectinload(Asset.category),
                selectinload(Asset.unit),
                selectinload(Asset.employee),
            )
            .where(Asset.is_active.is_(True))
        )
        if unit_id:
            stmt = stmt.where(Asset.unit_id == unit_id)
        if employee_id:
            stmt = stmt.where(Asset.employee_id == employee_id)
            
        stmt = stmt.order_by(Asset.name)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_asset(self, asset: Asset) -> Asset:
        self.session.add(asset)
        await self.session.flush()
        return asset

    async def update_asset(self, asset: Asset) -> Asset:
        await self.session.flush()
        return asset
