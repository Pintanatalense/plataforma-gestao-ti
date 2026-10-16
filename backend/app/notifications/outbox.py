"""
Emissão de eventos de domínio (outbox).

`emit_event` apenas insere uma linha em `domain_events` usando a sessão do chamador: o evento nasce
e morre junto com a transação do negócio. Quem emite não conhece canais, destinatários nem regras.
"""
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import DomainEvent

PRIORITIES = ("low", "normal", "high", "critical")
PRIORITY_RANK = {name: rank for rank, name in enumerate(PRIORITIES)}

OUTBOX_CHANNEL = "outbox"


async def emit_event(
    session: AsyncSession,
    event_type: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    payload: dict[str, Any] | None = None,
    actor_user_id: uuid.UUID | None = None,
    priority: str = "normal",
) -> DomainEvent:
    """Registra o evento na transação corrente. O commit fica com quem chamou."""
    if priority not in PRIORITY_RANK:
        raise ValueError(f"Prioridade inválida: {priority}")

    event = DomainEvent(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        payload=payload or {},
        priority=priority,
    )
    session.add(event)
    await session.flush()

    # Acorda o worker; o NOTIFY só é entregue no COMMIT. É apenas um acelerador: sem ele o worker
    # encontra o evento no próximo ciclo (poll de 5 s), então nada se perde se o NOTIFY falhar.
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        await session.execute(text("SELECT pg_notify(:channel, :payload)"), {"channel": OUTBOX_CHANNEL, "payload": str(event.id)})
    return event
