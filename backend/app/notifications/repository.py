"""
MOD-11 — Notificações (Repository)
"""
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import Notification

class NotificationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, notification: Notification) -> Notification:
        self.session.add(notification)
        await self.session.commit()
        await self.session.refresh(notification)
        return notification

    async def get_by_user(self, user_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[Notification]:
        stmt = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
        
    async def get_unread_count(self, user_id: uuid.UUID) -> int:
        stmt = select(Notification).where(Notification.user_id == user_id, Notification.is_read.is_(False))
        result = await self.session.execute(stmt)
        return len(result.scalars().all())

    async def mark_as_read(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> Notification | None:
        stmt = (
            update(Notification)
            .where(Notification.id == notification_id, Notification.user_id == user_id)
            .values(is_read=True)
            .returning(Notification)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one_or_none()

    async def mark_all_as_read(self, user_id: uuid.UUID) -> int:
        stmt = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .values(is_read=True)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount
