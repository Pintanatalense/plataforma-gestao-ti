"""
MOD-11 — Notificações (Services)
"""
import uuid
import json
import logging
from typing import Any

from app.notifications.repository import NotificationRepository
from app.notifications.schemas import NotificationCreate, NotificationOut
from app.notifications.models import Notification

logger = logging.getLogger(__name__)

class NotificationConnectionManager:
    """Gerencia as conexões WebSocket ativas por usuário."""
    def __init__(self):
        # map user_id -> list of websocket connections
        self.active_connections: dict[uuid.UUID, list[Any]] = {}

    async def connect(self, websocket: Any, user_id: uuid.UUID):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        logger.info("WS conectado: usuário %s", user_id)

    def disconnect(self, websocket: Any, user_id: uuid.UUID):
        if user_id in self.active_connections:
            try:
                self.active_connections[user_id].remove(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
            except ValueError:
                pass
        logger.info("WS desconectado: usuário %s", user_id)

    async def send_personal_message(self, message: dict, user_id: uuid.UUID):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_text(json.dumps(message))
                except Exception:
                    pass

manager = NotificationConnectionManager()

class NotificationService:
    def __init__(self, repository: NotificationRepository):
        self.repository = repository

    async def create_notification(self, data: NotificationCreate) -> NotificationOut:
        notification = Notification(
            user_id=data.user_id,
            title=data.title,
            message=data.message,
            type=data.type,
            entity_type=data.entity_type,
            entity_id=data.entity_id
        )
        created = await self.repository.create(notification)
        out = NotificationOut.model_validate(created)
        
        # Dispatch WS message
        await manager.send_personal_message(
            {"type": "NEW_NOTIFICATION", "payload": out.model_dump(mode="json")},
            data.user_id
        )
        
        return out

    async def get_user_notifications(self, user_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[NotificationOut]:
        items = await self.repository.get_by_user(user_id, limit, offset)
        return [NotificationOut.model_validate(i) for i in items]
        
    async def mark_as_read(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> NotificationOut | None:
        updated = await self.repository.mark_as_read(notification_id, user_id)
        if updated:
            return NotificationOut.model_validate(updated)
        return None

    async def mark_all_as_read(self, user_id: uuid.UUID) -> int:
        return await self.repository.mark_all_as_read(user_id)
