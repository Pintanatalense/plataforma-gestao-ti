"""
Listener global para interceptar eventos do barramento e gravar logs de auditoria.
"""
import logging
from app.core.events import Event, event_bus
from app.database import AsyncSessionLocal
from app.audit.repository import AuditRepository

logger = logging.getLogger(__name__)

async def _audit_handler(event: Event) -> None:
    try:
        async with AsyncSessionLocal() as session:
            repo = AuditRepository(session)
            await repo.create(
                event_type=event.event_type,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                data=event.data,
                user_id=event.user_id,
            )
            await session.commit()
    except Exception:
        logger.exception("Falha ao gravar log de auditoria para o evento %s", event.event_type)

def setup_audit_listener() -> None:
    """Registra o handler de auditoria no barramento de eventos."""
    event_bus.subscribe_all(_audit_handler)
    logger.info("Audit listener configurado.")
