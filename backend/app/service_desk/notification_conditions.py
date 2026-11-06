"""
Condições de chamado que o hub de notificações confere no momento do envio (ADR-025 M5, escalonamento do
ADR-013 §6.3). Fica aqui, e não em `notifications`, para o hub não importar models de chamados (ADR-004): ele só
chama esta função com o id do chamado.

- `first_response`: ainda vale escalonar se o chamado está aberto e ninguém além do solicitante respondeu em
  público (nota interna não conta como resposta ao solicitante);
- `resolved`: ainda vale escalonar se o chamado não foi resolvido nem encerrado.

Chamado inexistente nunca escalona.
"""
import uuid

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import UserAccount
from app.service_desk.models import Ticket, TicketInteraction

CONDITIONS = ("first_response", "resolved")
_FINISHED = ("RESOLVED", "CLOSED")


async def escalation_still_due(session: AsyncSession, ticket_id: uuid.UUID | None, condition: str) -> bool:
    if ticket_id is None or condition not in CONDITIONS:
        return False
    ticket = (await session.execute(select(Ticket.status, Ticket.requester_id).where(Ticket.id == ticket_id))).first()
    if ticket is None or ticket.status in _FINISHED:
        return False
    if condition == "resolved":
        return True
    requester_accounts = select(UserAccount.id).where(UserAccount.employee_id == ticket.requester_id)
    answered = await session.execute(
        select(
            exists().where(
                TicketInteraction.ticket_id == ticket_id,
                TicketInteraction.is_internal.is_(False),
                TicketInteraction.author_id.not_in(requester_accounts),
            )
        )
    )
    return not answered.scalar()
