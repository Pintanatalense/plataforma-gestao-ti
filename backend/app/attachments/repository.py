import uuid
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.attachments.models import Attachment


class AttachmentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, attachment_id: uuid.UUID) -> Optional[Attachment]:
        stmt = select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_entity(
        self, entity_type: str, entity_id: uuid.UUID, include_internal: bool = True
    ) -> List[Attachment]:
        stmt = select(Attachment).where(
            Attachment.entity_type == entity_type,
            Attachment.entity_id == entity_id,
            Attachment.deleted_at.is_(None)
        ).order_by(Attachment.created_at.desc())
        if not include_internal:
            stmt = stmt.where(Attachment.is_internal.is_(False))

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, attachment: Attachment) -> Attachment:
        self.session.add(attachment)
        await self.session.flush()
        await self.session.refresh(attachment)
        return attachment
        
    async def soft_delete(self, attachment: Attachment) -> None:
        from datetime import datetime, timezone
        attachment.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()
