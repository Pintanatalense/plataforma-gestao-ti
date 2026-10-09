from datetime import date
from typing import Any
import uuid

from pydantic import BaseModel, Field


class AssetCategoryBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: str | None = None
    spec_schema: dict[str, Any] = Field(default_factory=dict)


class AssetCategoryCreate(AssetCategoryBase):
    pass


class AssetCategoryUpdate(AssetCategoryBase):
    pass


class AssetCategoryResponse(AssetCategoryBase):
    id: uuid.UUID

    class Config:
        from_attributes = True


class AssetBase(BaseModel):
    tag: str = Field(..., max_length=50)
    name: str = Field(..., max_length=255)
    category_id: uuid.UUID
    status: str = Field("IN_STOCK", max_length=50)
    technical_specs: dict[str, Any] = Field(default_factory=dict)
    purchase_date: date | None = None
    warranty_expires: date | None = None
    notes: str | None = None
    unit_id: uuid.UUID
    employee_id: uuid.UUID | None = None


class AssetCreate(AssetBase):
    pass


class AssetUpdate(AssetBase):
    pass


class AssetResponse(AssetBase):
    id: uuid.UUID
    category: AssetCategoryResponse

    class Config:
        from_attributes = True
