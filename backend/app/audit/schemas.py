"""
MOD-12 — Auditoria (Schemas)
"""
from datetime import datetime
from typing import Any
import uuid

from pydantic import BaseModel

class AuditLogOut(BaseModel):
    id: uuid.UUID
    event_type: str
    entity_type: str
    entity_id: uuid.UUID
    data: dict[str, Any]
    user_id: uuid.UUID | None
    created_at: datetime
    
    class Config:
        from_attributes = True
