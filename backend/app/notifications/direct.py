"""
Mensagem direta de uma pessoa a outra pessoa (ex.: técnico -> solicitante) pelo hub.

Não passa por regras: o usuário escolhe o destinatário. Mesmo assim vira `deliveries` (retentativa,
circuito, painel) e só vai a endereço VERIFICADO — nunca a um telefone digitado em cadastro.
"""
import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import Delivery, DomainEvent
from app.notifications.outbox import PRIORITY_RANK


async def enqueue_direct_message(
    session: AsyncSession,
    channel: str,
    address: str,
    recipient_user_id: uuid.UUID,
    text: str,
    actor_user_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID | None,
    priority: str = "normal",
) -> Delivery:
    """Cria o evento (já expandido) e a entrega. O commit fica com o chamador."""
    if priority not in PRIORITY_RANK:
        raise ValueError(f"Prioridade inválida: {priority}")
    now = datetime.now(timezone.utc)
    event = DomainEvent(
        event_type=f"{entity_type}.direct_message",
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        payload={"channel": channel},  # o texto fica só na entrega, não no evento
        priority=priority,
        fanned_out_at=now,
    )
    session.add(event)
    await session.flush()
    delivery = Delivery(
        event_id=event.id,
        recipient_user_id=recipient_user_id,
        channel=channel,
        address=address,
        priority=priority,
        message={"title": "", "body_text": text, "priority": priority},
        next_attempt_at=now,
        idempotency_key=hashlib.sha256(f"direct|{event.id}".encode()).hexdigest(),
    )
    session.add(delivery)
    await session.flush()
    return delivery
