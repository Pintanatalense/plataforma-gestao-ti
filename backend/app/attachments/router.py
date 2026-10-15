import os
import uuid
from typing import List
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import get_current_user_id, get_token_payload

from app.attachments.schemas import AttachmentOut
from app.attachments.repository import AttachmentRepository
from app.attachments.service import AttachmentService


router = APIRouter(prefix="/attachments", tags=["Anexos"])

def get_attachment_service(db: AsyncSession = Depends(get_db)) -> AttachmentService:
    repo = AttachmentRepository(db)
    return AttachmentService(repo)


async def verify_entity_access(
    entity_type: str,
    entity_id: uuid.UUID,
    payload: dict,
    current_user_id: uuid.UUID,
    db: AsyncSession
) -> None:
    if payload.get("is_admin", False):
        return

    if entity_type == "TICKET":
        from app.identity.repository import IdentityRepository
        from app.service_desk.services import ServiceDeskService
        
        permissions = payload.get("permissions", [])
        is_technician = "service_desk.tickets.manage" in permissions
        can_read_all = "service_desk.tickets.read_all" in permissions
        
        repo_ident = IdentityRepository(db)
        user = await repo_ident.get_user(current_user_id)
        emp_id = user.employee_id if user else None
        
        sd_service = ServiceDeskService(db)
        await sd_service.get_ticket_for_user(
            ticket_id=entity_id,
            user_employee_id=emp_id,
            is_technician=is_technician,
            can_read_all=can_read_all,
            user_id=current_user_id,
        )


@router.post("", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    file: UploadFile = File(...),
    entity_type: str = Form(...),
    entity_id: uuid.UUID = Form(...),
    service: AttachmentService = Depends(get_attachment_service),
    payload: dict = Depends(get_token_payload),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    await verify_entity_access(entity_type, entity_id, payload, current_user_id, db)
    return await service.upload_file(file, entity_type, entity_id, current_user_id)


@router.get("", response_model=List[AttachmentOut])
async def list_attachments(
    entity_type: str,
    entity_id: uuid.UUID,
    service: AttachmentService = Depends(get_attachment_service),
    payload: dict = Depends(get_token_payload),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    await verify_entity_access(entity_type, entity_id, payload, current_user_id, db)
    return await service.list_attachments(entity_type, entity_id)


@router.get("/{attachment_id}/download")
async def download_attachment(
    attachment_id: uuid.UUID,
    service: AttachmentService = Depends(get_attachment_service),
    payload: dict = Depends(get_token_payload),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    attachment = await service.get_attachment(attachment_id)
    await verify_entity_access(attachment.entity_type, attachment.entity_id, payload, current_user_id, db)
    full_path = service.get_full_path(attachment)
    
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
    payload: dict = Depends(get_token_payload),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    attachment = await service.get_attachment(attachment_id)
    await verify_entity_access(attachment.entity_type, attachment.entity_id, payload, current_user_id, db)
    await service.delete_attachment(attachment_id)
