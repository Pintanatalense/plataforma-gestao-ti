"""
Processamento de mensagens recebidas, independente do canal: deduplicação, engine e fila de respostas.

A resposta NUNCA volta no corpo de um webhook/polling: vira uma entrega (`deliveries`) do canal de
origem, enviada pelo worker com retentativa, circuito e visibilidade no painel.
"""
import hashlib
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.conversation.engine import ConversationEngine
from app.notifications.models import Delivery, DomainEvent, InboundMessage

logger = logging.getLogger(__name__)


async def enqueue_replies(
    session: AsyncSession, channel: str, external_id: str, user_id: uuid.UUID | None, message_id: str, replies: list[str]
) -> None:
    """Cria o evento `conversation.reply` (já expandido) e uma entrega por resposta. Sem horário de silêncio."""
    if not replies:
        return
    now = datetime.now(timezone.utc)
    event = DomainEvent(
        event_type="conversation.reply",
        entity_type="conversation",
        payload={"channel": channel},  # nada do conteúdo da conversa fica no evento
        priority="high",
        fanned_out_at=now,
    )
    session.add(event)
    await session.flush()
    for index, text in enumerate(replies):
        session.add(
            Delivery(
                event_id=event.id,
                recipient_user_id=user_id,
                channel=channel,
                address=external_id,
                priority="high",
                message={"title": "", "body_text": text, "priority": "high"},
                next_attempt_at=now,
                idempotency_key=hashlib.sha256(f"reply|{channel}|{message_id}|{index}".encode()).hexdigest(),
            )
        )
    await session.flush()


async def process_inbound(session: AsyncSession, channel: str, message_id: str, external_id: str, text: str) -> bool:
    """Executa a mensagem uma única vez. Retorna False se já tinha sido processada (reentrega)."""
    try:
        async with session.begin_nested():
            session.add(InboundMessage(channel=channel, message_id=message_id, external_id=external_id))
            await session.flush()
    except IntegrityError:
        logger.info("Mensagem %s/%s já processada; ignorando reentrega.", channel, message_id)
        return False

    replies, user_id = await ConversationEngine(session).handle(channel, external_id, text)
    await enqueue_replies(session, channel, external_id, user_id, message_id, replies)
    return True
