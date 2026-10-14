"""
MOD-14 — Backups do Banco de Dados (Schemas)
"""

from datetime import datetime
import uuid
from pydantic import BaseModel, ConfigDict


class DatabaseBackupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    size_bytes: int
    checksum_sha256: str
    status: str
    error_message: str | None = None
    created_at: datetime
    created_by_id: uuid.UUID | None = None
    created_by_email: str | None = None
