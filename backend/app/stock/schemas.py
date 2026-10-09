from pydantic import BaseModel, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime

class StockItemBase(BaseModel):
    name: str
    description: Optional[str] = None
    unit_id: UUID
    min_quantity: int = 0

class StockItemCreate(StockItemBase):
    initial_quantity: int = 0

class StockItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    min_quantity: Optional[int] = None

class StockItemResponse(StockItemBase):
    id: UUID
    quantity: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class StockMovementBase(BaseModel):
    item_id: UUID
    movement_type: str
    quantity: int
    notes: Optional[str] = None

class StockMovementCreate(StockMovementBase):
    pass

class StockMovementResponse(StockMovementBase):
    id: UUID
    author_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
