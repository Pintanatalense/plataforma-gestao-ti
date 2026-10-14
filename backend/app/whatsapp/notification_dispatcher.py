"""
MOD-15 — WhatsApp Integration (Notification Dispatcher)

Disparador de notificações ativas no WhatsApp para eventos de chamados:
- Chamado atribuído a um atendente
- Resposta/interação adicionada pelo técnico
- Mudança de status ou encerramento
"""

import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.organization.models import Employee
from app.service_desk.models import Ticket
from app.whatsapp.models import WhatsAppConfig
from app.whatsapp.queue_service import WhatsAppQueueService

logger = logging.getLogger(__name__)


class WhatsAppNotificationDispatcher:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.queue_service = WhatsAppQueueService(session)

    async def notify_ticket_status_change(self, ticket_id: str, new_status: str, notes: str | None = None) -> bool:
        stmt = (
            select(Ticket)
            .options(selectinload(Ticket.requester))
            .where(Ticket.id == ticket_id)
        )
        ticket = (await self.session.execute(stmt)).scalar_one_or_none()
        if not ticket or not ticket.requester or not ticket.requester.phone:
            return False

        config = (await self.session.execute(select(WhatsAppConfig).limit(1))).scalar_one_or_none()
        if not config or not config.is_enabled:
            return False

        status_labels = {
            "OPENED": "Aberto",
            "IN_PROGRESS": "Em Atendimento",
            "PENDING": "Pendente",
            "RESOLVED": "Resolvido",
            "CLOSED": "Encerrado",
        }
        label = status_labels.get(new_status, new_status)
        obs_text = f"\nObservação: _{notes}_" if notes else ""

        message = (
            f"🔔 *Atualização no seu Chamado #{str(ticket.id)[:8]}*\n\n"
            f"Título: {ticket.title}\n"
            f"Novo Status: *{label}*{obs_text}\n\n"
            f"Para interagir com este chamado, responda com [3] no menu."
        )

        # Enfileira na fila outbox segura (com proteção anti-ban e rate-limiting)
        outbox_item = await self.queue_service.enqueue_message(
            to_phone=ticket.requester.phone,
            message=message,
            priority=2,
            ticket_id=ticket.id
        )
        return outbox_item is not None

