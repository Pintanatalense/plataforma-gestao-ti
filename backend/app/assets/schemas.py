import uuid
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.assets.models import AssetStatus


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

    model_config = ConfigDict(from_attributes=True)


class AssetBase(BaseModel):
    tag: str = Field(..., max_length=50)
    serial_number: str | None = Field(None, max_length=100)
    name: str = Field(..., max_length=255)
    category_id: uuid.UUID
    status: AssetStatus = Field(default=AssetStatus.IN_STOCK)
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


class AssetUnitSimple(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    type: str

    model_config = ConfigDict(from_attributes=True)


class AssetEmployeeSimple(BaseModel):
    id: uuid.UUID
    name: str
    registration_number: str
    position: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AssetResponse(AssetBase):
    id: uuid.UUID
    category: AssetCategoryResponse
    unit: AssetUnitSimple | None = None
    employee: AssetEmployeeSimple | None = None

    model_config = ConfigDict(from_attributes=True)
