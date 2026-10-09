import uuid
from typing import List
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import get_current_user_id

from app.attachments.schemas import AttachmentOut
from app.attachments.repository import AttachmentRepository
from app.attachments.service import AttachmentService


router = APIRouter(prefix="/attachments", tags=["Anexos"])

def get_attachment_service(db: AsyncSession = Depends(get_db)) -> AttachmentService:
    repo = AttachmentRepository(db)
    return AttachmentService(repo)


@router.post("", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    file: UploadFile = File(...),
    entity_type: str = Form(...),
    entity_id: uuid.UUID = Form(...),
    service: AttachmentService = Depends(get_attachment_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id)
):
    return await service.upload_file(file, entity_type, entity_id, current_user_id)


@router.get("", response_model=List[AttachmentOut])
async def list_attachments(
    entity_type: str,
    entity_id: uuid.UUID,
    service: AttachmentService = Depends(get_attachment_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id)
):
    return await service.list_attachments(entity_type, entity_id)


@router.get("/{attachment_id}/download")
async def download_attachment(
    attachment_id: uuid.UUID,
    service: AttachmentService = Depends(get_attachment_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id)
):
    attachment = await service.get_attachment(attachment_id)
    full_path = service.get_full_path(attachment)
    
    import os
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Arquivo físico não encontrado no disco.")
        
    return FileResponse(
        path=full_path, 
        filename=attachment.filename,
        media_type=attachment.content_type
    )


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    attachment_id: uuid.UUID,
    service: AttachmentService = Depends(get_attachment_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id)
):
    # Idealmente verificaríamos permissões aqui, mas para o MVP simplificamos
    await service.delete_attachment(attachment_id)
