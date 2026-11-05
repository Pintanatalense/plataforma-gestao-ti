"""
MOD-12 — Auditoria (Services)
"""
import uuid
from datetime import datetime
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

    async def search(
        self,
        *,
        event_type: str | None,
        entity_type: str | None,
        user: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
        category: str | None = None,
    ) -> tuple[list[AuditLogOut], int]:
        logs, total = await self.repository.search(
            event_type=event_type, entity_type=entity_type, user=user,
            date_from=date_from, date_to=date_to, category=category, limit=limit, offset=offset,
        )
        return [AuditLogOut.model_validate(log) for log in logs], total

    async def event_types(self) -> list[str]:
        return await self.repository.event_types()
