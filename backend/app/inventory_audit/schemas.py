import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class InventoryAuditItemBase(BaseModel):
    item_type: str = Field(..., description="ASSET or STOCK")
    asset_id: Optional[uuid.UUID] = None
    stock_item_id: Optional[uuid.UUID] = None
    expected_status: Optional[str] = None
    expected_quantity: Optional[int] = None
    actual_status: Optional[str] = None
    actual_quantity: Optional[int] = None
    notes: Optional[str] = None


class InventoryAuditItemCreate(InventoryAuditItemBase):
    audit_id: uuid.UUID


class InventoryAuditItemUpdate(BaseModel):
    actual_status: Optional[str] = None
    actual_quantity: Optional[int] = None
    notes: Optional[str] = None


class InventoryAuditItemOut(InventoryAuditItemBase):
    id: uuid.UUID
    audit_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InventoryAuditBase(BaseModel):
    name: str = Field(..., max_length=255)
    unit_id: uuid.UUID
    auditor_id: uuid.UUID


class InventoryAuditCreate(InventoryAuditBase):
    pass


class InventoryAuditUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class InventoryAuditOut(InventoryAuditBase):
    id: uuid.UUID
    status: str
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InventoryAuditWithItemsOut(InventoryAuditOut):
    items: List[InventoryAuditItemOut] = []
