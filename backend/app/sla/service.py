"""Ciclos de SLA dos chamados (ADR-017, P4-S2): criação, pausa, retomada, resolução, reabertura e trocas.

Tudo roda na MESMA transação do chamado (o chamador faz o commit). O ciclo guarda uma cópia (`snapshot`) da política e
do calendário vigentes no início: depois disso nada é lido da política, então editar ou desativar uma política só vale
para chamados novos. Tempos em UTC; minutos úteis pelo calendário do ciclo (`app.sla.business_time`).

Convenções:
- Violação só quando `agora > vencimento` (estritamente); resolver exatamente no vencimento cumpre o prazo.
- Ciclo `PAUSED` não tem vencimento (`*_due_at` nulos); os minutos úteis que faltam ficam em `remaining_*_minutes`.
- `BREACHED` quando há QUALQUER violação registrada no ciclo (primeira resposta ou resolução).
- Violação registrada nunca é apagada (único `(ciclo, tipo)`); o job `sla.check` (`app.sla.checker`) registra a de
  quem ninguém tocou e avisa a equipe.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.sla.business_time import BusinessCalendar, add_business_minutes, business_minutes_between
from app.sla.models import SlaBreach, SlaCalendar, SlaPolicy, TicketSlaCycle
from app.sla.schemas import SlaInfo

ACTIVE_STATES = ("RUNNING", "PAUSED")
FINAL_STATES = ("MET", "BREACHED")
REOPEN_TO = ("OPENED", "IN_PROGRESS", "PENDING")  # destinos permitidos a partir de RESOLVED
FIRST_RESPONSE, RESOLUTION = "FIRST_RESPONSE", "RESOLUTION"


def _now() -> datetime:
    """Ponto único do relógio (os testes o substituem)."""
    return datetime.now(timezone.utc)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _calendar(cycle: TicketSlaCycle) -> BusinessCalendar:
    return BusinessCalendar.from_dict(cycle.snapshot["calendar"])


def _target(cycle: TicketSlaCycle, priority: str) -> dict | None:
    return (cycle.snapshot.get("targets") or {}).get((priority or "").upper())


def pending_deadlines(cycle: TicketSlaCycle) -> list[tuple[str, str, datetime]]:
    """Prazos ainda abertos de um ciclo `RUNNING`: (tipo, atributo, vencimento). Pausado não tem prazo."""
    if cycle.state != "RUNNING":
        return []
    pending = []
    if cycle.first_response_at is None and cycle.first_response_due_at is not None:
        pending.append((FIRST_RESPONSE, "first_response", _aware(cycle.first_response_due_at)))
    if cycle.resolved_at is None and cycle.resolution_due_at is not None:
        pending.append((RESOLUTION, "resolution", _aware(cycle.resolution_due_at)))
    return pending


def in_alert_zone(cycle: TicketSlaCycle, attr: str, due_at: datetime, now: datetime) -> bool:
    """Faltam no máximo `100 - alert_percent`% do alvo; `alert_percent` fora de 1–99 desliga o alerta."""
    percent = int(cycle.snapshot.get("alert_percent") or 0)
    target = _target(cycle, cycle.priority)
    if not 0 < percent < 100 or target is None or not target.get(attr):
        return False
    left = business_minutes_between(now, due_at, _calendar(cycle))
    return left * 100 <= target[attr] * (100 - percent)


class SlaService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ leitura

    async def _cycles(self, ticket_id: uuid.UUID, lock: bool = False) -> list[TicketSlaCycle]:
        stmt = select(TicketSlaCycle).where(TicketSlaCycle.ticket_id == ticket_id).order_by(TicketSlaCycle.cycle)
        if lock:  # serializa duas transições do mesmo chamado (no SQLite é ignorado)
            stmt = stmt.with_for_update()
        return list((await self.session.execute(stmt)).scalars())

    async def _active_policy(self, category_id: uuid.UUID | None) -> SlaPolicy | None:
        if category_id is None:
            return None
        from app.service_desk.models import TicketCategory  # evita import circular (models de chamado importam sla)

        category = await self.session.get(TicketCategory, category_id)
        if category is None or category.sla_policy_id is None:
            return None
        policy = (
            await self.session.execute(
                select(SlaPolicy)
                .where(SlaPolicy.id == category.sla_policy_id, SlaPolicy.is_active.is_(True))
                .options(selectinload(SlaPolicy.targets), selectinload(SlaPolicy.calendar).selectinload(SlaCalendar.holidays))
            )
        ).scalar_one_or_none()
        return policy

    @staticmethod
    def _snapshot(policy: SlaPolicy) -> dict:
        calendar = BusinessCalendar.from_dict(
            {
                "timezone": policy.calendar.timezone,
                "weekly_hours": policy.calendar.weekly_hours,
                "holidays": [h.day.isoformat() for h in policy.calendar.holidays],
            }
        )
        return {
            "policy_name": policy.name,
            "calendar": calendar.to_dict(),
            "pause_statuses": list(policy.pause_statuses or []),
            "reopen_rule": policy.reopen_rule,
            "alert_percent": policy.alert_percent,
            "targets": {
                t.priority.upper(): {"first_response": t.first_response_minutes, "resolution": t.resolution_minutes}
                for t in policy.targets
            },
        }

    # ------------------------------------------------------------------ relógio do ciclo

    @staticmethod
    def _consumed(cycle: TicketSlaCycle, now: datetime, calendar: BusinessCalendar) -> int:
        """Minutos úteis já gastos, fora das pausas (com o ciclo pausado o relógio parou em `paused_at`)."""
        end = _aware(cycle.paused_at) if cycle.paused_at else now
        return max(0, business_minutes_between(_aware(cycle.started_at), end, calendar) - cycle.paused_minutes)

    def _apply_targets(self, cycle: TicketSlaCycle, now: datetime) -> None:
        """Recalcula os vencimentos com os alvos da prioridade do ciclo, descontando o que já foi consumido.

        Se o alvo já estourou, o vencimento é retroativo (instante em que o consumo atingiu o alvo).
        """
        target = _target(cycle, cycle.priority)
        if target is None:
            return
        calendar = _calendar(cycle)
        consumed = self._consumed(cycle, now, calendar)
        paused = cycle.state == "PAUSED"
        wanted = []
        has_first_response_clock = cycle.first_response_due_at is not None or cycle.remaining_first_response_minutes is not None
        if cycle.first_response_at is None and has_first_response_clock:
            wanted.append(("first_response", target["first_response"]))
        wanted.append(("resolution", target["resolution"]))
        for kind, minutes in wanted:
            if paused:
                remaining = max(0, minutes - consumed)
                setattr(cycle, f"remaining_{kind}_minutes", remaining)
                setattr(cycle, f"{kind}_due_at", None)
            elif consumed >= minutes:
                setattr(cycle, f"{kind}_due_at", add_business_minutes(_aware(cycle.started_at), minutes + cycle.paused_minutes, calendar))
            else:
                setattr(cycle, f"{kind}_due_at", add_business_minutes(now, minutes - consumed, calendar))

    async def _register_breach(self, cycle: TicketSlaCycle, kind: str, due_at: datetime, now: datetime) -> bool:
        """Registra a violação se ainda não existe; devolve True só quando esta chamada a criou."""
        exists = (
            await self.session.execute(select(SlaBreach.id).where(SlaBreach.cycle_id == cycle.id, SlaBreach.kind == kind))
        ).first()
        if exists:
            return False
        try:
            async with self.session.begin_nested():
                self.session.add(SlaBreach(cycle_id=cycle.id, kind=kind, due_at=due_at, detected_at=now))
                await self.session.flush()
        except IntegrityError:  # outra transação registrou no mesmo instante: idempotente
            return False
        return True

    async def _register_overdue(self, cycle: TicketSlaCycle, now: datetime) -> None:
        if cycle.state != "RUNNING":
            return
        if cycle.first_response_at is None and cycle.first_response_due_at and now > _aware(cycle.first_response_due_at):
            await self._register_breach(cycle, FIRST_RESPONSE, _aware(cycle.first_response_due_at), now)
        if cycle.resolved_at is None and cycle.resolution_due_at and now > _aware(cycle.resolution_due_at):
            await self._register_breach(cycle, RESOLUTION, _aware(cycle.resolution_due_at), now)

    async def _has_breach(self, cycle: TicketSlaCycle) -> bool:
        count = (await self.session.execute(select(func.count()).select_from(SlaBreach).where(SlaBreach.cycle_id == cycle.id))).scalar_one()
        return count > 0

    async def _pause(self, cycle: TicketSlaCycle, now: datetime) -> None:
        if cycle.state != "RUNNING":
            return
        await self._register_overdue(cycle, now)
        calendar = _calendar(cycle)
        if cycle.first_response_at is None and cycle.first_response_due_at is not None:
            cycle.remaining_first_response_minutes = business_minutes_between(now, _aware(cycle.first_response_due_at), calendar)
            cycle.first_response_due_at = None
        if cycle.resolution_due_at is not None:
            cycle.remaining_resolution_minutes = business_minutes_between(now, _aware(cycle.resolution_due_at), calendar)
            cycle.resolution_due_at = None
        cycle.paused_at = now
        cycle.state = "PAUSED"

    def _resume(self, cycle: TicketSlaCycle, now: datetime) -> None:
        if cycle.state != "PAUSED":
            return
        calendar = _calendar(cycle)
        cycle.paused_minutes += business_minutes_between(_aware(cycle.paused_at), now, calendar)
        if cycle.remaining_first_response_minutes is not None:
            cycle.first_response_due_at = add_business_minutes(now, cycle.remaining_first_response_minutes, calendar)
        if cycle.remaining_resolution_minutes is not None:
            cycle.resolution_due_at = add_business_minutes(now, cycle.remaining_resolution_minutes, calendar)
        cycle.remaining_first_response_minutes = cycle.remaining_resolution_minutes = None
        cycle.paused_at = None
        cycle.state = "RUNNING"

    async def _audit(self, ticket_id: uuid.UUID, event_type: str, data: dict) -> None:
        from app.audit.repository import AuditRepository

        await AuditRepository(self.session).create(
            event_type=event_type, entity_type="ticket", entity_id=ticket_id, data=data, user_id=None
        )

    async def _new_cycle(
        self, ticket, snapshot: dict, number: int, started_at: datetime, *, paused_minutes: int = 0,
        first_response_at: datetime | None = None, policy_id: uuid.UUID | None = None, with_first_response: bool = True,
    ) -> TicketSlaCycle | None:
        priority = (ticket.priority or "").upper()
        cycle = TicketSlaCycle(
            ticket_id=ticket.id, cycle=number, policy_id=policy_id, priority=priority, snapshot=snapshot,
            started_at=started_at, paused_minutes=paused_minutes, first_response_at=first_response_at, state="RUNNING",
        )
        target = _target(cycle, priority)
        if target is None:  # a política não define esta prioridade: sem relógio
            return None
        calendar = _calendar(cycle)
        if with_first_response and first_response_at is None:
            cycle.first_response_due_at = add_business_minutes(started_at, target["first_response"], calendar)
        cycle.resolution_due_at = add_business_minutes(started_at, target["resolution"], calendar)
        self.session.add(cycle)
        await self.session.flush()
        return cycle

    # ------------------------------------------------------------------ eventos do chamado

    async def start(self, ticket) -> TicketSlaCycle | None:
        """Criação do chamado: abre o ciclo 1 se a categoria tem política ativa e ela cobre a prioridade."""
        policy = await self._active_policy(ticket.category_id)
        if policy is None:
            return None
        # O relógio parte do momento da criação (o chamador acabou de criá-lo); `_now()` é o relógio dos testes.
        return await self._new_cycle(ticket, self._snapshot(policy), 1, _now(), policy_id=policy.id)

    async def interaction_added(self, ticket, author_employee_id: uuid.UUID | None, is_internal: bool) -> None:
        """Primeira resposta: interação pública de quem não é o solicitante (nota interna e o próprio solicitante não contam)."""
        if is_internal or author_employee_id == ticket.requester_id:
            return
        cycles = await self._cycles(ticket.id, lock=True)
        active = next((c for c in reversed(cycles) if c.state in ACTIVE_STATES), None)
        if active is None or active.first_response_at is not None:
            return
        now = _now()
        await self._register_overdue(active, now)
        active.first_response_at = now
        active.remaining_first_response_minutes = None

    async def status_changed(self, ticket, old_status: str, new_status: str) -> None:
        cycles = await self._cycles(ticket.id, lock=True)
        if not cycles:
            return
        last, now = cycles[-1], _now()
        if old_status == "RESOLVED" and new_status in REOPEN_TO:
            if last.state in FINAL_STATES:
                await self._reopen(ticket, last, new_status, now)
            return
        active = last if last.state in ACTIVE_STATES else None
        if new_status in ("RESOLVED", "CLOSED"):
            if active is not None:
                await self._resolve(active, now)
            return
        if active is None:
            return
        if new_status in (active.snapshot.get("pause_statuses") or []):
            await self._pause(active, now)
        else:
            self._resume(active, now)

    async def canceled(self, ticket) -> None:
        """Subchamado cancelado (ADR-026): o ciclo aberto termina como `CANCELED`, fora dos indicadores de cumprimento.

        Violações já registradas ficam no ciclo; nenhuma nova é registrada no cancelamento.
        """
        cycles = await self._cycles(ticket.id, lock=True)
        if cycles and cycles[-1].state in ACTIVE_STATES:
            cycle = cycles[-1]
            self._resume(cycle, _now())
            cycle.state = "CANCELED"

    async def _resolve(self, cycle: TicketSlaCycle, now: datetime) -> None:
        self._resume(cycle, now)  # resolvido enquanto pausado: o tempo parado não conta contra o prazo
        await self._register_overdue(cycle, now)
        cycle.resolved_at = now
        cycle.state = "BREACHED" if await self._has_breach(cycle) else "MET"

    async def _reopen(self, ticket, last: TicketSlaCycle, new_status: str, now: datetime) -> None:
        calendar = _calendar(last)
        rule = last.snapshot.get("reopen_rule", "RESTART")
        if rule == "CONTINUE":
            due = _aware(last.resolution_due_at) if last.resolution_due_at else now
            remaining = business_minutes_between(_aware(last.resolved_at), due, calendar) if last.resolved_at else 0
            if last.first_response_at is None and last.first_response_due_at is not None:
                first_due = _aware(last.first_response_due_at)
                first_left = business_minutes_between(_aware(last.resolved_at), first_due, calendar) if last.resolved_at else 0
                last.first_response_due_at = add_business_minutes(now, first_left, calendar)
            if last.resolved_at:
                last.paused_minutes += business_minutes_between(_aware(last.resolved_at), now, calendar)  # o tempo resolvido não conta
            last.resolved_at = None
            last.state = "RUNNING"
            last.resolution_due_at = add_business_minutes(now, remaining, calendar)
            last.first_response_warned_at = last.resolution_warned_at = None  # prazo novo: o alerta vale de novo
            cycle = last
        else:
            cycle = await self._new_cycle(
                ticket, last.snapshot, last.cycle + 1, now, first_response_at=last.first_response_at,
                policy_id=last.policy_id, with_first_response=False,
            )
            if cycle is None:
                return
        await self._audit(ticket.id, "ticket.sla_reopened", {"rule": rule, "cycle": cycle.cycle, "status": new_status})
        if new_status in (cycle.snapshot.get("pause_statuses") or []):
            await self._pause(cycle, now)

    async def priority_changed(self, ticket) -> None:
        cycles = await self._cycles(ticket.id, lock=True)
        active = next((c for c in reversed(cycles) if c.state in ACTIVE_STATES), None)
        if active is None:
            return
        priority = (ticket.priority or "").upper()
        if _target(active, priority) is None:  # a política não cobre a nova prioridade: mantém os prazos
            return
        now = _now()
        active.priority = priority
        active.first_response_warned_at = active.resolution_warned_at = None  # prazos novos: o alerta vale de novo
        self._apply_targets(active, now)
        await self._register_overdue(active, now)

    async def category_changed(self, ticket) -> None:
        """Categoria nova: o ciclo atual vira SUPERSEDED e (se a nova política vale) um novo parte do início do chamado."""
        if ticket.status in ("RESOLVED", "CLOSED"):
            return  # chamado encerrado (com ou sem ciclo): trocar a categoria não abre relógio nem muda o resultado
        cycles = await self._cycles(ticket.id, lock=True)
        last = cycles[-1] if cycles else None
        if last is not None and last.state in FINAL_STATES:
            return
        policy = await self._active_policy(ticket.category_id)
        active = last if last is not None and last.state in ACTIVE_STATES else None
        if active is not None and policy is not None and active.policy_id == policy.id:
            return  # mesma política: os prazos já são os certos
        if active is None and policy is None:
            return
        now = _now()
        carried_pause = 0
        first_response_at = None
        if active is not None:
            await self._register_overdue(active, now)
            carried_pause = active.paused_minutes
            if active.state == "PAUSED":
                carried_pause += business_minutes_between(_aware(active.paused_at), now, _calendar(active))
            first_response_at = active.first_response_at
            active.state = "SUPERSEDED"
            await self._audit(ticket.id, "ticket.sla_cycle_superseded", {"cycle": active.cycle, "category_id": str(ticket.category_id) if ticket.category_id else None})
        elif last is not None:
            carried_pause, first_response_at = last.paused_minutes, last.first_response_at
        if policy is None:
            await self.session.flush()
            return
        snapshot = self._snapshot(policy)
        # "Início original" do chamado: o primeiro ciclo (ou, se nunca houve, a criação do chamado).
        started = _aware(cycles[0].started_at) if cycles else _aware(ticket.created_at or now)
        cycle = await self._new_cycle(
            ticket, snapshot, (last.cycle + 1) if last else 1, started, paused_minutes=carried_pause,
            first_response_at=first_response_at, policy_id=policy.id,
        )
        if cycle is None:
            return
        self._apply_targets(cycle, now)  # desconta o que já foi consumido desde a abertura; pode já nascer vencido
        await self._register_overdue(cycle, now)
        if ticket.status in (snapshot["pause_statuses"] or []):
            await self._pause(cycle, now)

    # ------------------------------------------------------------------ reabertura e leitura

    async def resolved_at(self, ticket) -> datetime | None:
        """Quando o chamado foi resolvido pela última vez (ciclo; para chamados sem SLA, a auditoria)."""
        cycles = await self._cycles(ticket.id)
        if cycles and cycles[-1].state != "SUPERSEDED":
            for cycle in reversed(cycles):
                if cycle.resolved_at is not None:
                    return _aware(cycle.resolved_at)
        from app.audit.models import AuditLog

        rows = (
            await self.session.execute(
                select(AuditLog)
                .where(AuditLog.entity_id == ticket.id, AuditLog.event_type == "ticket.closed")
                .order_by(AuditLog.created_at.desc())
                .limit(10)
            )
        ).scalars()
        for row in rows:
            if (row.data or {}).get("status") == "RESOLVED":
                return _aware(row.created_at)
        return None

    async def attach(self, tickets) -> None:
        """Coloca `ticket.sla` (SlaInfo) em cada chamado, com uma consulta só."""
        tickets = [t for t in tickets if t is not None]
        ids = [t.id for t in tickets]
        by_ticket: dict[uuid.UUID, list[TicketSlaCycle]] = {}
        breaches: dict[uuid.UUID, list[str]] = {}
        if ids:
            rows = (
                await self.session.execute(
                    select(TicketSlaCycle).where(TicketSlaCycle.ticket_id.in_(ids)).order_by(TicketSlaCycle.cycle)
                )
            ).scalars()
            for cycle in rows:
                by_ticket.setdefault(cycle.ticket_id, []).append(cycle)
            cycle_ids = [c.id for cs in by_ticket.values() for c in cs]
            if cycle_ids:
                for breach in (await self.session.execute(select(SlaBreach).where(SlaBreach.cycle_id.in_(cycle_ids)))).scalars():
                    breaches.setdefault(breach.cycle_id, []).append(breach.kind)
        now = _now()
        for ticket in tickets:
            history = by_ticket.get(ticket.id, [])
            cycle = history[-1] if history and history[-1].state != "SUPERSEDED" else None  # substituído = sem relógio
            if cycle is None:
                ticket.sla = SlaInfo()
                continue
            pending = pending_deadlines(cycle)
            overdue = any(now > due for _, _, due in pending)
            ticket.sla = SlaInfo(
                state=cycle.state, policy_name=cycle.snapshot.get("policy_name"), cycle=cycle.cycle, priority=cycle.priority,
                first_response_due_at=cycle.first_response_due_at, resolution_due_at=cycle.resolution_due_at,
                first_response_at=cycle.first_response_at, resolved_at=cycle.resolved_at, paused=cycle.state == "PAUSED",
                breaches=sorted(breaches.get(cycle.id, [])), overdue=overdue,
                at_risk=not overdue and any(in_alert_zone(cycle, attr, due, now) for _, attr, due in pending),
            )
