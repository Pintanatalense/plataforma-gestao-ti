import uuid
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.inventory_audit.models import InventoryAudit, InventoryAuditItem
from app.inventory_audit.schemas import InventoryAuditCreate, InventoryAuditUpdate, InventoryAuditItemCreate, InventoryAuditItemUpdate


class InventoryAuditRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, audit_id: uuid.UUID) -> Optional[InventoryAudit]:
        stmt = select(InventoryAudit).where(
            InventoryAudit.id == audit_id,
            InventoryAudit.deleted_at.is_(None)
        ).options(
            selectinload(InventoryAudit.items)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self, unit_id: Optional[uuid.UUID] = None) -> List[InventoryAudit]:
        stmt = select(InventoryAudit).where(InventoryAudit.deleted_at.is_(None))
        if unit_id:
            stmt = stmt.where(InventoryAudit.unit_id == unit_id)
        stmt = stmt.order_by(InventoryAudit.created_at.desc())
        
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, data: InventoryAuditCreate) -> InventoryAudit:
        audit = InventoryAudit(**data.model_dump())
        self.session.add(audit)
        await self.session.flush()
        await self.session.refresh(audit)
        return audit

    async def update(self, audit: InventoryAudit, data: InventoryAuditUpdate) -> InventoryAudit:
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(audit, key, value)
        await self.session.flush()
        await self.session.refresh(audit)
        return audit
        
    async def get_item_by_id(self, item_id: uuid.UUID) -> Optional[InventoryAuditItem]:
        stmt = select(InventoryAuditItem).where(InventoryAuditItem.id == item_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def add_item(self, data: InventoryAuditItemCreate) -> InventoryAuditItem:
        item = InventoryAuditItem(**data.model_dump())
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item
        
    async def update_item(self, item: InventoryAuditItem, data: InventoryAuditItemUpdate) -> InventoryAuditItem:
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(item, key, value)
        await self.session.flush()
        await self.session.refresh(item)
        return item
