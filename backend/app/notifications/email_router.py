"""
MOD-11 — Notificações por E-mail (Router)

Rotas administrativas para configuração e teste de conexão do servidor SMTP.
"""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import require_any_permission
from app.notifications.email_service import EmailService, SmtpConfigSchema, SmtpTestEmailRequest

router = APIRouter(prefix="/notifications/email", tags=["Notificações — E-mail & SMTP"])


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
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = EmailService(session)
    updated = await service.update_config(body)
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
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = EmailService(session)
    success, message = await service.test_smtp(body)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Falha na validação SMTP: {message}"
        )
    return {"success": True, "message": message, "target_email": body.target_email}
