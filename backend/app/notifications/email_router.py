"""
MOD-11 — Notificações por E-mail (Router)

Rotas administrativas para configuração e teste de conexão do servidor SMTP.
"""

import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.audit.repository import AuditRepository
from app.core.dependencies import get_current_user_id, require_any_permission
from app.notifications.email_service import EmailService, SmtpConfigSchema, SmtpTestEmailRequest

router = APIRouter(prefix="/notifications/email", tags=["Notificações — E-mail & SMTP"])

EMAIL_AUDIT_ENTITY = uuid.uuid5(uuid.NAMESPACE_OID, "channel:email")


@router.get(
    "/config",
    response_model=SmtpConfigSchema,
    summary="Obtém as configurações atuais de SMTP do sistema",
    dependencies=[Depends(require_any_permission("notifications.manage", "system.backup.manage"))]
)
async def get_smtp_config(
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = EmailService(session)
    config = await service.get_config()
    # Mascarar a senha para não expor na interface/API
    safe_config = config.model_copy()
    if safe_config.password:
        safe_config.password = "********"
    return safe_config


@router.put(
    "/config",
    response_model=SmtpConfigSchema,
    summary="Atualiza as configurações de SMTP do sistema",
    dependencies=[Depends(require_any_permission("notifications.manage", "system.backup.manage"))]
)
async def update_smtp_config(
    body: SmtpConfigSchema,
    session: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
    service = EmailService(session)
    updated = await service.update_config(body)
    # Sem segredos na trilha: só o que mudou de configuração, nunca a senha.
    await AuditRepository(session).create(
        event_type="notifications.email_configured", entity_type="notification", entity_id=EMAIL_AUDIT_ENTITY,
        data={"enabled": updated.is_enabled, "host": updated.host, "port": updated.port,
              "security": updated.security, "username": updated.username}, user_id=user_id,
    )
    await session.commit()
    safe_config = updated.model_copy()
    if safe_config.password:
        safe_config.password = "********"
    return safe_config


@router.post(
    "/test",
    summary="Testa a conectividade e realiza envio de validação para o e-mail informado",
    dependencies=[Depends(require_any_permission("notifications.manage", "system.backup.manage"))]
)
async def test_smtp_connection(
    body: SmtpTestEmailRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
    service = EmailService(session)
    success, message = await service.test_smtp(body)
    await AuditRepository(session).create(
        event_type="notifications.email_tested", entity_type="notification", entity_id=EMAIL_AUDIT_ENTITY,
        data={"success": success, "host": body.host or None}, user_id=user_id,
    )
    await session.commit()
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Falha na validação SMTP: {message}"
        )
    return {"success": True, "message": message, "target_email": body.target_email}
