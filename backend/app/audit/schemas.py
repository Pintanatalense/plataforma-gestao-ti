"""
MOD-12 — Auditoria (Schemas)
"""
from datetime import datetime
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict

class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    entity_type: str
    entity_id: uuid.UUID
    data: dict[str, Any]
    user_id: uuid.UUID | None
    user_email: str | None = None
    user_name: str | None = None
    created_at: datetime
