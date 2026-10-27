"""Job `sla.check` (ADR-017, P4-S3): registra as violações de quem ninguém tocou e avisa a equipe.

A cada execução:
1. Ciclos `RUNNING` com prazo vencido ganham a violação (idempotente, mesmo único `(ciclo, tipo)` das transições).
2. Ciclos `RUNNING` que passaram do `% de alerta` do prazo emitem `ticket.sla_warning`, uma vez por prazo
   (`*_warned_at`; a troca de prioridade rearma).
3. Toda violação ainda não avisada (`notified_at` nulo), venha do job ou de uma transição do chamado, emite
   `ticket.sla_breached` uma vez.

Os ciclos são lidos com `FOR UPDATE SKIP LOCKED`: um chamado sendo alterado agora fica para a próxima execução, sem
esperar nem brigar com a transação dele. Ciclos pausados não têm prazo e ficam de fora. Tudo numa transação (o
chamador faz o commit): evento no outbox e marca de aviso gravam juntos.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.outbox import emit_event
from app.sla.business_time import business_minutes_between
from app.sla.models import SlaBreach, TicketSlaCycle
from app.sla.service import FIRST_RESPONSE, RESOLUTION, SlaService, _aware, _calendar, _now, _target

BATCH = 500
KINDS = ((FIRST_RESPONSE, "first_response"), (RESOLUTION, "resolution"))


@dataclass
class CheckResult:
    breaches: int = 0
    warnings: int = 0
    breach_notices: int = 0


def _ticket_payload(ticket, cycle: TicketSlaCycle, kind: str, due_at: datetime) -> dict:
    calendar = _calendar(cycle)
    return {
        "ticket_id": str(ticket.id),
        "title": ticket.title[:200],
        "priority": ticket.priority,
        "status": ticket.status,
        "requester_employee_id": str(ticket.requester_id),
        "assignee_id": str(ticket.assignee_id) if ticket.assignee_id else None,
        "assigned": ticket.assignee_id is not None,
        "responsible_sector_id": str(ticket.responsible_sector_id),
        "kind": kind,
        "due_at": due_at.isoformat(),
        "due_local": due_at.astimezone(calendar.tz).strftime("%d/%m %H:%M"),
        "policy_name": cycle.snapshot.get("policy_name"),
    }


def _should_warn(cycle: TicketSlaCycle, attr: str, due_at: datetime, now: datetime) -> bool:
    percent = int(cycle.snapshot.get("alert_percent") or 0)
    target = _target(cycle, cycle.priority)
    if not 0 < percent < 100 or target is None or not target.get(attr):
        return False
    left = business_minutes_between(now, due_at, _calendar(cycle))
    return left * 100 <= target[attr] * (100 - percent)


async def check_sla(session: AsyncSession, now: datetime | None = None) -> CheckResult:
    from app.service_desk.models import Ticket  # evita import circular (models de chamado importam sla)

    now = now or _now()
    result = CheckResult()
    sla = SlaService(session)
    pending_first = and_(
        TicketSlaCycle.first_response_at.is_(None),
        TicketSlaCycle.first_response_due_at.is_not(None),
        or_(TicketSlaCycle.first_response_warned_at.is_(None), TicketSlaCycle.first_response_due_at < now),
    )
    pending_resolution = and_(
        TicketSlaCycle.resolved_at.is_(None),
        TicketSlaCycle.resolution_due_at.is_not(None),
        or_(TicketSlaCycle.resolution_warned_at.is_(None), TicketSlaCycle.resolution_due_at < now),
    )
    cycles = (
        await session.execute(
            select(TicketSlaCycle)
            .where(TicketSlaCycle.state == "RUNNING", or_(pending_first, pending_resolution))
            .order_by(TicketSlaCycle.resolution_due_at)
            .limit(BATCH)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    tickets = {}
    if cycles:
        ids = {c.ticket_id for c in cycles}
        tickets = {t.id: t for t in (await session.execute(select(Ticket).where(Ticket.id.in_(ids)))).scalars()}

    for cycle in cycles:
        ticket = tickets.get(cycle.ticket_id)
        if ticket is None:
            continue
        for kind, attr in KINDS:
            due = getattr(cycle, f"{attr}_due_at")
            done = cycle.first_response_at if kind == FIRST_RESPONSE else cycle.resolved_at
            if due is None or done is not None:
                continue
            due = _aware(due)
            if now > due:
                result.breaches += await sla._register_breach(cycle, kind, due, now)
            elif getattr(cycle, f"{attr}_warned_at") is None and _should_warn(cycle, attr, due, now):
                await emit_event(
                    session, event_type="ticket.sla_warning", entity_type="ticket", entity_id=ticket.id,
                    payload=_ticket_payload(ticket, cycle, kind, due), priority="high",
                )
                setattr(cycle, f"{attr}_warned_at", now)
                result.warnings += 1

    result.breach_notices = await _notify_breaches(session, Ticket, now)
    return result


async def _notify_breaches(session: AsyncSession, ticket_model, now: datetime) -> int:
    rows = (
        await session.execute(
            select(SlaBreach, TicketSlaCycle, ticket_model)
            .join(TicketSlaCycle, TicketSlaCycle.id == SlaBreach.cycle_id)
            .join(ticket_model, ticket_model.id == TicketSlaCycle.ticket_id)
            .where(SlaBreach.notified_at.is_(None))
            .order_by(SlaBreach.detected_at)
            .limit(BATCH)
            .with_for_update(of=SlaBreach, skip_locked=True)
        )
    ).all()
    for breach, cycle, ticket in rows:
        await emit_event(
            session, event_type="ticket.sla_breached", entity_type="ticket", entity_id=ticket.id,
            payload=_ticket_payload(ticket, cycle, breach.kind, _aware(breach.due_at)), priority="high",
        )
        breach.notified_at = now
    return len(rows)
