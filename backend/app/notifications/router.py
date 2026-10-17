"""
MOD-11 — Notificações (Router)
"""
import uuid
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.database import AsyncSessionLocal, get_db
from app.identity.models import UserAccount
from app.core.security import decode_access_token
from app.core.dependencies import get_current_user_id
from app.notifications.repository import NotificationRepository
from app.notifications.schemas import NotificationOut
from app.notifications.services import NotificationService, manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["Notificações"])

def get_notification_service(db: Annotated[AsyncSession, Depends(get_db)]) -> NotificationService:
    return NotificationService(NotificationRepository(db))

@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    service: Annotated[NotificationService, Depends(get_notification_service)],
    limit: int = 50,
    offset: int = 0,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Lista notificações do usuário logado."""
    return await service.get_user_notifications(current_user_id, limit, offset)

@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: uuid.UUID,
    service: Annotated[NotificationService, Depends(get_notification_service)],
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Marca notificação como lida."""
    res = await service.mark_as_read(notification_id, current_user_id)
    if not res:
        raise HTTPException(status_code=404, detail="Notification not found")
    return res

@router.post("/read-all")
async def mark_all_read(
    service: Annotated[NotificationService, Depends(get_notification_service)],
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Marca todas as notificações como lidas."""
    count = await service.mark_all_as_read(current_user_id)
    return {"message": "success", "count": count}

# WebSocket endpoint
@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str):
    user_id = None
    try:
        payload = decode_access_token(token)
        if not payload:
            raise Exception("Token inválido")
        user_id = uuid.UUID(payload.get("sub"))
        async with AsyncSessionLocal() as session:
            active = (
                await session.execute(select(UserAccount.is_active).where(UserAccount.id == user_id))
            ).scalar_one_or_none()
        if not active:
            raise Exception("Usuário inexistente ou inativo")
    except Exception as e:
        logger.warning(f"WS authentication failed: {e}")
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, user_id)
    try:
        while True:
            # Mantém conexão viva aguardando mensagens (ex. ping)
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
