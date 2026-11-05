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
    actor_kind: str = "system"
    category: str = "operational"
    ip: str | None = None
    request_id: str | None = None
    created_at: datetime


class AuditChainStatusOut(BaseModel):
    """Resultado da verificação da cadeia de uma categoria (``problem`` vazio = íntegra)."""

    category: str
    checked: int
    last_pos: int
    last_hash: str
    problem: str | None = None
