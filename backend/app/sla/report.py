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
- **Chamados vinculados (ADR-026):** os mesmos indicadores separados por tipo (avulso, principal e subchamado) e os
  subchamados por setor responsável. O tempo total do processo é o do principal, quando a categoria dele tem política.
  Ciclos `CANCELED` ficam fora, como os `SUPERSEDED`. Para os principais abertos, dois sinais separados: o SLA do
  próprio principal venceu (`process_overdue`) e há subchamado obrigatório atrasado (`steps_overdue`).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.sla import service as sla_service
from app.sla.business_time import business_minutes_between
from app.sla.models import TicketSlaCycle
from app.sla.schemas import SlaAttention, SlaGroup, SlaProcesses, SlaReport
from app.sla.service import ACTIVE_STATES, FINAL_STATES, _aware, _calendar, in_alert_zone, pending_deadlines

ATTENTION_LIMIT = 50
PRIORITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
PRIORITY_LABELS = {"CRITICAL": "Crítica", "HIGH": "Alta", "MEDIUM": "Média", "LOW": "Baixa"}
NO_CATEGORY = "Sem categoria"
KIND_LABELS = {"standalone": "Avulsos", "parent": "Principais (processo inteiro)", "child": "Subchamados (etapas)"}
_CLOSED = ("RESOLVED", "CLOSED", "CANCELED")


def _kind(parent_ticket_id, has_children: bool) -> str:
    if parent_ticket_id is not None:
        return "child"
    return "parent" if has_children else "standalone"


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
    from app.organization.models import Sector
    from app.service_desk.models import Ticket, TicketCategory  # evita import circular

    now = now or sla_service._now()  # pelo módulo: os testes trocam o relógio lá
    child = Ticket.__table__.alias("child_ticket")
    has_children = exists().where(child.c.parent_ticket_id == Ticket.id).correlate(Ticket)
    finished = (
        select(
            TicketSlaCycle, TicketCategory.id, TicketCategory.name, Ticket.parent_ticket_id,
            has_children.label("has_children"), Ticket.responsible_sector_id, Sector.name,
        )
        .join(Ticket, Ticket.id == TicketSlaCycle.ticket_id)
        .outerjoin(TicketCategory, TicketCategory.id == Ticket.category_id)
        .outerjoin(Sector, Sector.id == Ticket.responsible_sector_id)
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
    by_kind: dict[str, _Totals] = defaultdict(_Totals)
    child_by_sector: dict[str, _Totals] = defaultdict(_Totals)
    sector_names: dict[str, str] = {}
    rows = (await session.execute(finished)).all()
    for cycle, category_id, category_name, parent_id, with_children, sector_id, sector_name in rows:
        key = str(category_id) if category_id else "none"
        category_names[key] = category_name or NO_CATEGORY
        kind = _kind(parent_id, with_children)
        buckets = [total, by_category[key], by_priority[cycle.priority], by_kind[kind]]
        if kind == "child":
            sector_names[str(sector_id)] = sector_name or "?"
            buckets.append(child_by_sector[str(sector_id)])
        for bucket in buckets:
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
        by_kind=[by_kind[k].group(k, label) for k, label in KIND_LABELS.items() if k in by_kind],
        child_by_sector=sorted(
            (t.group(k, sector_names[k]) for k, t in child_by_sector.items()), key=lambda g: g.label.casefold()
        ),
    )

    active = (
        await session.execute(
            select(TicketSlaCycle, Ticket.title, Ticket.parent_ticket_id, Ticket.is_required)
            .join(Ticket, Ticket.id == TicketSlaCycle.ticket_id)
            .where(TicketSlaCycle.state.in_(ACTIVE_STATES))
        )
    ).all()
    attention: list[SlaAttention] = []
    late_tickets: set = set()
    parents_with_late_steps: set = set()
    for cycle, title, parent_id, is_required in active:
        report.open += 1
        pending = pending_deadlines(cycle)
        late = [(kind, due) for kind, _, due in pending if now > due]
        risky = [(kind, due) for kind, attr, due in pending if not late and in_alert_zone(cycle, attr, due, now)]
        if late:
            report.overdue += 1
            late_tickets.add(cycle.ticket_id)
            if parent_id is not None and is_required:
                parents_with_late_steps.add(parent_id)
        elif risky:
            report.at_risk += 1
        for kind, due in (late or risky)[:1]:  # o prazo mais urgente: a primeira resposta vem antes da resolução
            attention.append(SlaAttention(
                ticket_id=cycle.ticket_id, title=title, priority=cycle.priority, kind=kind, due_at=due, overdue=bool(late),
            ))
    attention.sort(key=lambda a: (not a.overdue, a.due_at))
    report.attention = attention[:ATTENTION_LIMIT]

    open_parents = set(
        (await session.execute(
            select(Ticket.id).where(Ticket.status.not_in(_CLOSED), has_children)
        )).scalars()
    )
    report.processes = SlaProcesses(
        open=len(open_parents),
        process_overdue=len(open_parents & late_tickets),
        steps_overdue=len(open_parents & parents_with_late_steps),
    )
    return report
