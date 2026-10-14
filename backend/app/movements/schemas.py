import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.assets.models import AssetStatus
from app.movements.models import MovementType


class AssetMovementCreate(BaseModel):
    asset_id: uuid.UUID
    movement_type: MovementType
    to_unit_id: uuid.UUID | None = None
    to_employee_id: uuid.UUID | None = None
    status_to: AssetStatus | None = None
    ticket_id: uuid.UUID | None = None
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
    ticket_id: uuid.UUID | None = None
    notes: str | None = None
    author_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AssetReserveRequest(BaseModel):
    employee_id: uuid.UUID | None = None
    ticket_id: uuid.UUID | None = None
    notes: str | None = None


class AssetDeliveryRequest(BaseModel):
    employee_id: uuid.UUID
    ticket_id: uuid.UUID | None = None
    notes: str | None = None


class AssetReturnRequest(BaseModel):
    ticket_id: uuid.UUID | None = None
    notes: str | None = None


class AssetInspectionRequest(BaseModel):
    approved: bool
    send_to_maintenance: bool = False
    notes: str | None = None
