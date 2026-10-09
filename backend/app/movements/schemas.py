from datetime import datetime
import uuid

from pydantic import BaseModel, Field


class AssetMovementCreate(BaseModel):
    asset_id: uuid.UUID
    movement_type: str
    to_unit_id: uuid.UUID | None = None
    to_employee_id: uuid.UUID | None = None
    status_to: str | None = None
    notes: str | None = None


class AssetMovementResponse(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    movement_type: str
    from_unit_id: uuid.UUID | None = None
    to_unit_id: uuid.UUID | None = None
    from_employee_id: uuid.UUID | None = None
    to_employee_id: uuid.UUID | None = None
    status_from: str | None = None
    status_to: str | None = None
    notes: str | None = None
    author_id: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True
