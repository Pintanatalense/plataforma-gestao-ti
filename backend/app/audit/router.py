"""
MOD-12 — Auditoria (Router)
"""
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
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
    response: Response,
    service: Annotated[AuditService, Depends(get_audit_service)],
    event_type: str | None = Query(None, max_length=100),
    entity_type: str | None = Query(None, max_length=50),
    user: str | None = Query(None, max_length=100, description="Trecho do e-mail do usuário"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: None = Depends(require_permission("audit.read")),
):
    """Lista a trilha de auditoria (mais recentes primeiro), com filtros. O total vem em `X-Total-Count`."""
    items, total = await service.search(
        event_type=event_type, entity_type=entity_type, user=user,
        date_from=date_from, date_to=date_to, limit=limit, offset=offset,
    )
    response.headers["X-Total-Count"] = str(total)
    return items


@router.get("/event-types", response_model=list[str])
async def list_audit_event_types(
    service: Annotated[AuditService, Depends(get_audit_service)],
    _: None = Depends(require_permission("audit.read")),
):
    """Tipos de evento já registrados (alimenta o filtro da tela)."""
    return await service.event_types()


@router.get("/{entity_type}/{entity_id}", response_model=list[AuditLogOut])
async def list_entity_audit_logs(
    entity_type: str,
    entity_id: uuid.UUID,
    service: Annotated[AuditService, Depends(get_audit_service)],
    _: None = Depends(require_permission("audit.read")),
):
    """Lista logs de auditoria para uma entidade específica."""
    return await service.get_entity_history(entity_type, entity_id)
