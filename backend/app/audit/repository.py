"""
MOD-12 — Auditoria (Repository)
"""
import uuid
from typing import Any

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.identity.models import UserAccount

class AuditRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, event_type: str, entity_type: str, entity_id: uuid.UUID, data: dict[str, Any], user_id: uuid.UUID | None = None) -> AuditLog:
        log = AuditLog(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            data=data,
            user_id=user_id
        )
        self.session.add(log)
        await self.session.flush()
        await self.session.refresh(log)
        return log

    async def get_by_entity(self, entity_type: str, entity_id: uuid.UUID) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.entity_type == entity_type)
            .where(AuditLog.entity_id == entity_id)
            .order_by(AuditLog.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[AuditLog]:
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _filters(
        event_type: str | None,
        entity_type: str | None,
        user: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> list:
        conditions = []
        if event_type:
            conditions.append(AuditLog.event_type == event_type)
        if entity_type:
            conditions.append(AuditLog.entity_type == entity_type)
        if user:
            # só o texto digitado, escapado: % e _ do usuário não viram curinga
            escaped = user.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append(
                AuditLog.user_id.in_(select(UserAccount.id).where(UserAccount.email.ilike(f"%{escaped}%", escape="\\")))
            )
        if date_from:
            conditions.append(AuditLog.created_at >= date_from)
        if date_to:
            conditions.append(AuditLog.created_at <= date_to)
        return conditions

    async def search(
        self,
        *,
        event_type: str | None = None,
        entity_type: str | None = None,
        user: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditLog], int]:
        conditions = self._filters(event_type, entity_type, user, date_from, date_to)
        total = await self.session.scalar(select(func.count()).select_from(AuditLog).where(*conditions))
        stmt = (
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc(), AuditLog.id)
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), int(total or 0)

    async def event_types(self) -> list[str]:
        result = await self.session.execute(select(AuditLog.event_type).distinct().order_by(AuditLog.event_type))
        return list(result.scalars().all())
