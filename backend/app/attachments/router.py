import uuid
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.attachments.access import AttachmentAction, ensure_attachment_access
from app.attachments.repository import AttachmentRepository
from app.attachments.schemas import AttachmentOut
from app.attachments.service import AttachmentEntityType, AttachmentService
from app.core.dependencies import get_current_user_id, get_token_payload
from app.database import get_db

router = APIRouter(prefix="/attachments", tags=["Anexos"])


def get_attachment_service(db: AsyncSession = Depends(get_db)) -> AttachmentService:
    return AttachmentService(AttachmentRepository(db))


@router.post("", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    file: UploadFile = File(...),
    entity_type: AttachmentEntityType = Form(...),
    entity_id: uuid.UUID = Form(...),
    service: AttachmentService = Depends(get_attachment_service),
    payload: dict = Depends(get_token_payload),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await ensure_attachment_access(
        db=db, payload=payload, user_id=current_user_id,
        entity_type=entity_type, entity_id=entity_id, action=AttachmentAction.WRITE,
    )
    return await service.upload_file(file, entity_type, entity_id, current_user_id)


@router.get("", response_model=List[AttachmentOut])
async def list_attachments(
    entity_type: AttachmentEntityType,
    entity_id: uuid.UUID,
    service: AttachmentService = Depends(get_attachment_service),
    payload: dict = Depends(get_token_payload),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await ensure_attachment_access(
        db=db, payload=payload, user_id=current_user_id,
        entity_type=entity_type, entity_id=entity_id, action=AttachmentAction.READ,
    )
    return await service.list_attachments(entity_type.value, entity_id)


@router.get("/{attachment_id}/download")
async def download_attachment(
    attachment_id: uuid.UUID,
    service: AttachmentService = Depends(get_attachment_service),
    payload: dict = Depends(get_token_payload),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    attachment = await service.get_attachment(attachment_id)
    await ensure_attachment_access(
        db=db, payload=payload, user_id=current_user_id,
        entity_type=AttachmentEntityType(attachment.entity_type), entity_id=attachment.entity_id,
        action=AttachmentAction.READ, attachment=attachment,
    )
    full_path = service.get_full_path(attachment)
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Arquivo físico não encontrado no disco.")

    return FileResponse(
        path=full_path,
        filename=attachment.filename,
        media_type=attachment.content_type,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    attachment_id: uuid.UUID,
    service: AttachmentService = Depends(get_attachment_service),
    payload: dict = Depends(get_token_payload),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    attachment = await service.get_attachment(attachment_id)
    await ensure_attachment_access(
        db=db, payload=payload, user_id=current_user_id,
        entity_type=AttachmentEntityType(attachment.entity_type), entity_id=attachment.entity_id,
        action=AttachmentAction.DELETE, attachment=attachment,
    )
    await service.delete_attachment(attachment_id)
