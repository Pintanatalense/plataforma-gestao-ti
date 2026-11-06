import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class AttachmentOut(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    entity_type: str
    entity_id: uuid.UUID
    uploaded_by_id: uuid.UUID | None
    is_internal: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
