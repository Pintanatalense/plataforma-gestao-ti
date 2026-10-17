"""Canal in-app: grava na caixa de entrada (`notifications`) e avisa as APIs via NOTIFY."""
import uuid
from typing import ClassVar

from sqlalchemy import text

from app.notifications.channels.base import (
    AdapterContext,
    Capabilities,
    ChannelHealth,
    DeliveryResult,
    Message,
    Recipient,
)
from app.notifications.models import Notification

INBOX_CHANNEL = "inbox"

_TYPE_BY_PRIORITY = {"low": "info", "normal": "info", "high": "warning", "critical": "error"}


class InAppAdapter:
    channel: ClassVar[str] = "in_app"
    capabilities: ClassVar[Capabilities] = Capabilities()

    def __init__(self, ctx: AdapterContext) -> None:
        self._session_factory = ctx.session_factory

    async def send(self, recipient: Recipient, message: Message) -> DeliveryResult:
        if not recipient.user_id:
            return DeliveryResult("permanent", error="Entrega in-app exige usuário destinatário.")
        try:
            user_id = uuid.UUID(recipient.user_id)
            entity_id = uuid.UUID(message.entity_id) if message.entity_id else None
        except ValueError:
            return DeliveryResult("permanent", error="Identificador inválido na entrega in-app.")

        try:
            async with self._session_factory() as session:
                notification = Notification(
                    user_id=user_id,
                    title=message.title[:255],
                    message=message.body_text,
                    type=_TYPE_BY_PRIORITY.get(message.priority, "info"),
                    entity_type=message.entity_type,
                    entity_id=entity_id,
                )
                session.add(notification)
                await session.flush()
                if session.get_bind().dialect.name == "postgresql":
                    await session.execute(
                        text("SELECT pg_notify(:channel, :payload)"),
                        {"channel": INBOX_CHANNEL, "payload": f"{user_id}:{notification.id}"},
                    )
                await session.commit()
                return DeliveryResult("ok", provider_message_id=str(notification.id))
        except Exception as exc:
            return DeliveryResult("retryable", error=f"Falha ao gravar notificação: {exc}")

    async def health(self) -> ChannelHealth:
        return ChannelHealth(ok=True, detail="Caixa de entrada local (sempre disponível).")
