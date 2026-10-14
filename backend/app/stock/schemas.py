from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StockCategoryBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    spec_schema: dict[str, Any] = Field(default_factory=dict)


class StockCategoryCreate(StockCategoryBase):
    pass


class StockCategoryUpdate(StockCategoryBase):
    pass


class StockCategoryResponse(StockCategoryBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StockItemBase(BaseModel):
    name: str
    description: Optional[str] = None
    unit_id: UUID
    min_quantity: int = 0
    category_id: Optional[UUID] = None
    technical_specs: dict[str, Any] = Field(default_factory=dict)


class StockItemCreate(StockItemBase):
    initial_quantity: int = 0


class StockItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    min_quantity: Optional[int] = None
    category_id: Optional[UUID] = None
    technical_specs: Optional[dict[str, Any]] = None


class StockItemResponse(StockItemBase):
    id: UUID
    quantity: int
    created_at: datetime
    updated_at: datetime
    category: Optional[StockCategoryResponse] = None

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
