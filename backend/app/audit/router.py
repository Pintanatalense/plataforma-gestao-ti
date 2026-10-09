"""
MOD-12 — Auditoria (Router)
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.repository import AuditRepository
from app.audit.schemas import AuditLogOut
from app.audit.services import AuditService
from app.core.dependencies import require_permission
from app.database import get_db

router = APIRouter(prefix="/audit", tags=["Auditoria"])

def get_audit_service(db: Annotated[AsyncSession, Depends(get_db)]) -> AuditService:
    return AuditService(AuditRepository(db))

@router.get("", response_model=list[AuditLogOut])
async def list_audit_logs(
    service: Annotated[AuditService, Depends(get_audit_service)],
    limit: int = 100,
    offset: int = 0,
    _: None = Depends(require_permission("admin")),
):
    """Lista todos os logs de auditoria (apenas admin)."""
    return await service.get_all_logs(limit, offset)

@router.get("/{entity_type}/{entity_id}", response_model=list[AuditLogOut])
async def list_entity_audit_logs(
    entity_type: str,
    entity_id: uuid.UUID,
    service: Annotated[AuditService, Depends(get_audit_service)],
    _: None = Depends(require_permission("admin")),
):
    """Lista logs de auditoria para uma entidade específica."""
    return await service.get_entity_history(entity_type, entity_id)
