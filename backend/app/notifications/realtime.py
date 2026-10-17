"""
Tempo real entre processos (ADR-013, D7): o worker grava a notificação e executa
`NOTIFY inbox, '<user_id>:<notification_id>'`; cada processo da API escuta e empurra para os
WebSockets locais daquele usuário. É só aceleração: o cliente sempre busca as não lidas pela REST.
"""
import asyncio
import logging
import uuid

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.notifications.channels.in_app import INBOX_CHANNEL
from app.notifications.models import Notification
from app.notifications.schemas import NotificationOut
from app.notifications.services import manager

logger = logging.getLogger(__name__)


async def _push(payload: str) -> None:
    try:
        raw_user, raw_notification = payload.split(":", 1)
        user_id, notification_id = uuid.UUID(raw_user), uuid.UUID(raw_notification)
    except ValueError:
        logger.warning("Payload de NOTIFY inválido: %r", payload)
        return
    if user_id not in manager.active_connections:
        return  # ninguém deste processo para receber
    async with AsyncSessionLocal() as session:
        notification = (
            await session.execute(select(Notification).where(Notification.id == notification_id))
        ).scalar_one_or_none()
    if notification is None:
        return
    out = NotificationOut.model_validate(notification)
    await manager.send_personal_message({"type": "NEW_NOTIFICATION", "payload": out.model_dump(mode="json")}, user_id)


async def run_inbox_listener(stop: asyncio.Event) -> None:
    import asyncpg

    dsn = get_settings().DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    pending: set[asyncio.Task] = set()

    def on_notify(_conn, _pid, _channel, payload: str) -> None:
        task = asyncio.create_task(_push(payload))
        pending.add(task)
        task.add_done_callback(pending.discard)

    while not stop.is_set():
        conn = None
        try:
            conn = await asyncpg.connect(dsn)
            await conn.add_listener(INBOX_CHANNEL, on_notify)
            logger.info("Escutando NOTIFY %s para o WebSocket de notificações", INBOX_CHANNEL)
            while not stop.is_set() and not conn.is_closed():
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Listener do inbox indisponível (%s); nova tentativa em 10 s.", exc)
            await asyncio.sleep(10)
        finally:
            if conn is not None and not conn.is_closed():
                await conn.close()
