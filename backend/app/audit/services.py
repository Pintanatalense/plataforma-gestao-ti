"""
MOD-12 — Auditoria (Services)
"""
import uuid
from app.audit.repository import AuditRepository
from app.audit.schemas import AuditLogOut

class AuditService:
    def __init__(self, repository: AuditRepository):
        self.repository = repository

    async def get_entity_history(self, entity_type: str, entity_id: uuid.UUID) -> list[AuditLogOut]:
        logs = await self.repository.get_by_entity(entity_type, entity_id)
        return [AuditLogOut.model_validate(log) for log in logs]

    async def get_all_logs(self, limit: int = 100, offset: int = 0) -> list[AuditLogOut]:
        logs = await self.repository.get_all(limit, offset)
        return [AuditLogOut.model_validate(log) for log in logs]
