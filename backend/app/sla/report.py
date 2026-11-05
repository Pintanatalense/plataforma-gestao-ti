"""Indicadores de SLA (ADR-017, P4-S5), calculados só com os fatos gravados nos ciclos e nas violações.

- **Período:** ciclos encerrados (`MET`/`BREACHED`) com `resolved_at` em `[início, fim)`. Cada ciclo conta uma vez; um
  chamado reaberto com `RESTART` tem um ciclo novo e conta de novo. Ciclos `SUPERSEDED` (troca de categoria) ficam de
  fora.
- **Cumprimento:** `MET / (MET + BREACHED)`; sem ciclo encerrado no período, `None` (não é 100%).
- **Tempos médios (minutos úteis, calendário guardado no ciclo):** resolução = do início do ciclo à resolução, menos as
  pausas; primeira resposta = do início do ciclo à primeira resposta, só quando ela aconteceu neste ciclo (a pausa antes
  da primeira resposta conta como tempo gasto).
- **Agora** (não depende do período): ciclos abertos, atrasados (prazo pendente vencido) e em risco (acima do % de
  alerta), com a lista dos que pedem atenção.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.sla import service as sla_service
from app.sla.business_time import business_minutes_between
from app.sla.models import TicketSlaCycle
from app.sla.schemas import SlaAttention, SlaGroup, SlaReport
from app.sla.service import ACTIVE_STATES, FINAL_STATES, _aware, _calendar, in_alert_zone, pending_deadlines

ATTENTION_LIMIT = 50
PRIORITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
PRIORITY_LABELS = {"CRITICAL": "Crítica", "HIGH": "Alta", "MEDIUM": "Média", "LOW": "Baixa"}
NO_CATEGORY = "Sem categoria"


@dataclass
class _Totals:
    met: int = 0
    breached: int = 0
    first: list[int] = field(default_factory=list)
    resolution: list[int] = field(default_factory=list)

    def add(self, cycle: TicketSlaCycle) -> None:
        calendar = _calendar(cycle)
        started, resolved = _aware(cycle.started_at), _aware(cycle.resolved_at)
        if cycle.state == "MET":
            self.met += 1
        else:
            self.breached += 1
        self.resolution.append(max(0, business_minutes_between(started, resolved, calendar) - cycle.paused_minutes))
        if cycle.first_response_at is not None and _aware(cycle.first_response_at) >= started:
            self.first.append(business_minutes_between(started, _aware(cycle.first_response_at), calendar))

    def group(self, key: str, label: str) -> SlaGroup:
        done = self.met + self.breached
        return SlaGroup(
            key=key, label=label, met=self.met, breached=self.breached,
            compliance_percent=round(self.met * 100 / done, 1) if done else None,
            avg_first_response_minutes=round(sum(self.first) / len(self.first)) if self.first else None,
            avg_resolution_minutes=round(sum(self.resolution) / len(self.resolution)) if self.resolution else None,
        )


async def sla_report(
    session: AsyncSession, start: datetime | None = None, end: datetime | None = None, now: datetime | None = None
) -> SlaReport:
    from app.service_desk.models import Ticket, TicketCategory  # evita import circular

    now = now or sla_service._now()  # pelo módulo: os testes trocam o relógio lá
    finished = (
        select(TicketSlaCycle, TicketCategory.id, TicketCategory.name)
        .join(Ticket, Ticket.id == TicketSlaCycle.ticket_id)
        .outerjoin(TicketCategory, TicketCategory.id == Ticket.category_id)
        .where(TicketSlaCycle.state.in_(FINAL_STATES), TicketSlaCycle.resolved_at.is_not(None))
    )
    if start is not None:
        finished = finished.where(TicketSlaCycle.resolved_at >= start)
    if end is not None:
        finished = finished.where(TicketSlaCycle.resolved_at < end)

    total = _Totals()
    by_category: dict[str, _Totals] = defaultdict(_Totals)
    category_names: dict[str, str] = {}
    by_priority: dict[str, _Totals] = defaultdict(_Totals)
    for cycle, category_id, category_name in (await session.execute(finished)).all():
        key = str(category_id) if category_id else "none"
        category_names[key] = category_name or NO_CATEGORY
        for bucket in (total, by_category[key], by_priority[cycle.priority]):
            bucket.add(cycle)

    report = SlaReport(
        total=total.group("total", "Total"),
        by_category=sorted(
            (t.group(k, category_names[k]) for k, t in by_category.items()), key=lambda g: g.label.casefold()
        ),
        by_priority=[
            by_priority[p].group(p, PRIORITY_LABELS.get(p, p))
            for p in [*PRIORITY_ORDER, *sorted(set(by_priority) - set(PRIORITY_ORDER))]
            if p in by_priority
        ],
    )

    active = (
        await session.execute(
            select(TicketSlaCycle, Ticket.title)
            .join(Ticket, Ticket.id == TicketSlaCycle.ticket_id)
            .where(TicketSlaCycle.state.in_(ACTIVE_STATES))
        )
    ).all()
    attention: list[SlaAttention] = []
    for cycle, title in active:
        report.open += 1
        pending = pending_deadlines(cycle)
        late = [(kind, due) for kind, _, due in pending if now > due]
        risky = [(kind, due) for kind, attr, due in pending if not late and in_alert_zone(cycle, attr, due, now)]
        if late:
            report.overdue += 1
        elif risky:
            report.at_risk += 1
        for kind, due in (late or risky)[:1]:  # o prazo mais urgente: a primeira resposta vem antes da resolução
            attention.append(SlaAttention(
                ticket_id=cycle.ticket_id, title=title, priority=cycle.priority, kind=kind, due_at=due, overdue=bool(late),
            ))
    attention.sort(key=lambda a: (not a.overdue, a.due_at))
    report.attention = attention[:ATTENTION_LIMIT]
    return report
