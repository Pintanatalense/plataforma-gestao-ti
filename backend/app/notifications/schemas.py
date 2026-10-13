"""
MOD-11 — Notificações (Schemas)
"""
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    message: str
    type: str
    is_read: bool
    entity_type: str | None
    entity_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

class NotificationCreate(BaseModel):
    user_id: uuid.UUID
    title: str
    message: str
    type: str = "info"
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
