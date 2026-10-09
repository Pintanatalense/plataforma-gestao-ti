"""
Barramento de eventos interno (in-process pub/sub).

Permite comunicação desacoplada entre módulos sem acesso direto.
Cada módulo pode emitir eventos e outros módulos podem escutar.

Este barramento é síncrono e in-process. Não utiliza filas externas.
Adequado para o monólito modular conforme DEC-013.
"""

import logging
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

# Tipo para handlers de evento
EventHandler = Callable[["Event"], Coroutine[Any, Any, None]]


@dataclass
class Event:
    """
    Evento base do sistema.

    Atributos:
        event_type: identificador do tipo de evento (ex: "ticket.created")
        entity_type: tipo da entidade relacionada (ex: "ticket")
        entity_id: UUID da entidade
        data: payload do evento
        user_id: UUID do usuário que originou a ação (nullable para eventos de sistema)
        timestamp: momento da emissão do evento
    """

    event_type: str
    entity_type: str
    entity_id: UUID
    data: dict[str, Any] = field(default_factory=dict)
    user_id: UUID | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventBus:
    """
    Barramento de eventos in-process.

    Exemplo de uso:

        # No módulo que emite:
        await event_bus.emit(Event(
            event_type="ticket.created",
            entity_type="ticket",
            entity_id=ticket.id,
            data={"number": ticket.number, "title": ticket.title},
            user_id=current_user.id,
        ))

        # No módulo que escuta:
        @event_bus.on("ticket.created")
        async def handle_ticket_created(event: Event):
            await notification_service.notify(...)
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._global_handlers: list[EventHandler] = []

    def on(self, event_type: str) -> Callable[[EventHandler], EventHandler]:
        """
        Decorador para registrar handler de evento.

        Args:
            event_type: tipo de evento a escutar (ex: "ticket.created")
        """
        def decorator(handler: EventHandler) -> EventHandler:
            self._handlers[event_type].append(handler)
            logger.debug("Handler registrado: %s → %s", event_type, handler.__name__)
            return handler
        return decorator

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Registra handler programaticamente."""
        self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Registra handler para todos os eventos (útil para auditoria)."""
        self._global_handlers.append(handler)

    async def emit(self, event: Event) -> None:
        """
        Emite um evento para todos os handlers registrados.

        Os handlers são executados sequencialmente.
        Um erro em um handler não impede a execução dos demais.
        """
        handlers = self._handlers.get(event.event_type, [])
        all_handlers = handlers + self._global_handlers

        if not all_handlers:
            logger.debug("Evento sem handlers: %s", event.event_type)
            return

        logger.info(
            "Emitindo evento: %s (entity=%s, id=%s, handlers=%d)",
            event.event_type,
            event.entity_type,
            event.entity_id,
            len(all_handlers),
        )

        for handler in all_handlers:
            try:
                await handler(event)
            except Exception:
                logger.exception(
                    "Erro no handler %s para evento %s",
                    handler.__name__,
                    event.event_type,
                )


# Instância global do barramento de eventos
event_bus = EventBus()
