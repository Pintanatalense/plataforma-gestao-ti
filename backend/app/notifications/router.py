"""
MOD-11 — Notificações (Router do usuário)

Caixa de entrada, preferências e WebSocket. Tudo no escopo do usuário autenticado;
a administração (entregas, regras, canais) fica em `admin_router.py`.
"""
import logging
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user_id
from app.core.security import create_access_token, decode_access_token
from app.database import AsyncSessionLocal, get_db
from app.identity.models import UserAccount
from app.notifications.models import Notification, UserNotificationPref
from app.notifications.prefs import CATEGORIES, HHMM
from app.notifications.repository import NotificationRepository
from app.notifications.schemas import NotificationOut
from app.notifications.services import NotificationService, manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["Notificações"])

WS_TICKET_TTL = timedelta(seconds=60)
EXTERNAL_CHANNELS = ("email",)


def get_notification_service(db: Annotated[AsyncSession, Depends(get_db)]) -> NotificationService:
    return NotificationService(NotificationRepository(db))


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    limit: int = 50,
    offset: int = 0,
    is_read: bool | None = None,
    type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    """Lista notificações do usuário logado, com filtros (lida/não lida, tipo, período)."""
    limit = max(1, min(limit, 200))
    stmt = select(Notification).where(Notification.user_id == current_user_id)
    if is_read is not None:
        stmt = stmt.where(Notification.is_read.is_(is_read))
    if type:
        stmt = stmt.where(Notification.type == type)
    if date_from:
        stmt = stmt.where(Notification.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        stmt = stmt.where(Notification.created_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc))
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit).offset(max(offset, 0))
    return [NotificationOut.model_validate(n) for n in (await db.execute(stmt)).scalars()]


@router.get("/unread-count")
async def unread_count(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
    total = (
        await db.execute(
            select(func.count()).select_from(Notification).where(
                Notification.user_id == current_user_id, Notification.is_read.is_(False)
            )
        )
    ).scalar_one()
    return {"count": total}


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: uuid.UUID,
    service: Annotated[NotificationService, Depends(get_notification_service)],
    current_user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
    """Marca notificação como lida."""
    res = await service.mark_as_read(notification_id, current_user_id)
    if not res:
        raise HTTPException(status_code=404, detail="Notification not found")
    return res


@router.post("/read-all")
async def mark_all_read(
    service: Annotated[NotificationService, Depends(get_notification_service)],
    current_user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
    """Marca todas as notificações como lidas."""
    count = await service.mark_all_as_read(current_user_id)
    return {"message": "success", "count": count}


# --- Preferências ---------------------------------------------------------------------------------


class PrefsPayload(BaseModel):
    channels_disabled: list[str] = []
    categories_disabled: list[str] = []
    quiet_enabled: bool = True
    quiet_start: str = "20:00"
    quiet_end: str = "07:00"
    critical_bypass: bool = True

    @field_validator("channels_disabled")
    @classmethod
    def _external_only(cls, value: list[str]) -> list[str]:
        invalid = [c for c in value if c not in EXTERNAL_CHANNELS]
        if invalid:
            raise ValueError(f"Canais não configuráveis: {invalid} (a caixa de entrada não pode ser desligada).")
        return sorted(set(value))

    @field_validator("categories_disabled")
    @classmethod
    def _known_categories(cls, value: list[str]) -> list[str]:
        invalid = [c for c in value if c not in CATEGORIES]
        if invalid:
            raise ValueError(f"Categorias desconhecidas: {invalid}")
        return sorted(set(value))

    @field_validator("quiet_start", "quiet_end")
    @classmethod
    def _hhmm(cls, value: str) -> str:
        if not HHMM.match(value):
            raise ValueError("Use o formato HH:MM.")
        return value


class PrefsResponse(PrefsPayload):
    timezone: str
    available_channels: list[str] = list(EXTERNAL_CHANNELS)
    available_categories: list[str] = list(CATEGORIES)


def _prefs_response(row: UserNotificationPref | None) -> PrefsResponse:
    from app.config import get_settings

    base = PrefsPayload()
    if row is not None:
        base = PrefsPayload(
            channels_disabled=list(row.channels_disabled or []),
            categories_disabled=list(row.categories_disabled or []),
            quiet_enabled=row.quiet_enabled,
            quiet_start=row.quiet_start,
            quiet_end=row.quiet_end,
            critical_bypass=row.critical_bypass,
        )
    return PrefsResponse(**base.model_dump(), timezone=get_settings().APP_TIMEZONE)


@router.get("/prefs", response_model=PrefsResponse)
async def get_prefs(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
    row = (
        await db.execute(select(UserNotificationPref).where(UserNotificationPref.user_id == current_user_id))
    ).scalar_one_or_none()
    return _prefs_response(row)


@router.put("/prefs", response_model=PrefsResponse)
async def update_prefs(
    body: PrefsPayload,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
    row = (
        await db.execute(select(UserNotificationPref).where(UserNotificationPref.user_id == current_user_id))
    ).scalar_one_or_none()
    if row is None:
        row = UserNotificationPref(user_id=current_user_id)
        db.add(row)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    await db.commit()
    return _prefs_response(row)


# --- WebSocket ------------------------------------------------------------------------------------


@router.post("/ws-ticket")
async def create_ws_ticket(current_user_id: Annotated[uuid.UUID, Depends(get_current_user_id)]):
    """Ticket de uso no WebSocket (60 s). O token de acesso nunca vai na URL (apareceria no log do Nginx)."""
    return {"ticket": create_access_token({"sub": str(current_user_id), "typ": "ws"}, expires_delta=WS_TICKET_TTL)}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, ticket: str):
    user_id = None
    try:
        payload = decode_access_token(ticket)
        if not payload or payload.get("typ") != "ws":
            raise Exception("Ticket inválido")
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
