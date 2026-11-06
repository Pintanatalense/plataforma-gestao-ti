"""
Agendamento de mensagens da Central (ADR-025 M4).

Não há agendador novo: o job `messages.schedules` (a cada minuto, na agenda do ADR-024) pega os agendamentos vencidos
com `SKIP LOCKED`, cria o envio da ocorrência pelo mesmo caminho do envio manual (`messages.enqueue`) e avança
`next_run_at` na mesma transação. A chave do envio é `schedule_id|instante`, então a mesma ocorrência nunca sai duas vezes.

Regras:
- a ocorrência sai com as permissões e o setor ATUAIS de quem agendou: conta desativada ou sem
  `notifications.messages.schedule` pausa o agendamento; pessoa que saiu do setor fica de fora;
- ocorrência perdida durante uma parada sai atrasada até `MESSAGES_SCHEDULE_TOLERANCE_MINUTES`; depois disso é pulada
  e registrada (`missed`). De várias perdidas seguidas, só a mais recente ainda pode sair;
- com calendário do SLA, dia sem expediente ou feriado é pulado (`skip`) ou vai para o próximo dia útil (`next`);
- falha da ocorrência (ninguém alcançável, teto por hora) fica em `last_outcome = failed` e o agendamento segue.
"""
import calendar as month_calendar
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.repository import AuditRepository
from app.config import get_settings
from app.core.access import load_access_context
from app.core.exceptions import BusinessRuleException, ValidationException
from app.notifications import messages as svc
from app.notifications.channels.base import SessionFactory
from app.notifications.models import MessageSchedule
from app.sla.business_time import BusinessCalendar

logger = logging.getLogger(__name__)

SCHEDULE = "notifications.messages.schedule"
RECURRENCES = ("once", "daily", "weekly", "monthly")
NON_BUSINESS_RULES = ("skip", "next")
OPEN_STATUSES = ("ACTIVE", "PAUSED")
BATCH = 20
_LOOKBACK_DAYS = 31  # uma ocorrência de dia não útil pode cair até aqui à frente com a regra `next`
_MAX_DAYS = 800
_MAX_SKIPS = 10_000


# --- Recorrência (funções puras) ------------------------------------------------------------------


@dataclass(frozen=True)
class Recurrence:
    kind: str
    timezone_name: str
    run_at: datetime | None = None
    time_of_day: time | None = None
    weekdays: frozenset[int] = field(default_factory=frozenset)
    month_day: int | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    calendar: BusinessCalendar | None = None
    non_business_rule: str = "skip"


def _matches(rule: Recurrence, day: date) -> bool:
    if rule.kind == "daily":
        return True
    if rule.kind == "weekly":
        return day.weekday() in rule.weekdays
    last = month_calendar.monthrange(day.year, day.month)[1]
    return day.day == min(rule.month_day or 1, last)


def _business(rule: Recurrence, day: date) -> bool:
    return rule.calendar is None or bool(rule.calendar.intervals_on(day))


def _next_business(rule: Recurrence, day: date) -> date | None:
    for offset in range(1, _LOOKBACK_DAYS + 1):
        candidate = day + timedelta(days=offset)
        if _business(rule, candidate):
            return candidate
    return None


def next_occurrence(rule: Recurrence, after: datetime) -> datetime | None:
    """Primeira ocorrência estritamente depois de `after` (UTC), ou None se não há mais nenhuma."""
    if rule.kind == "once":
        return rule.run_at if rule.run_at and rule.run_at > after else None
    tz = ZoneInfo(rule.timezone_name)
    day = after.astimezone(tz).date() - timedelta(days=_LOOKBACK_DAYS)
    if rule.starts_on and day < rule.starts_on:
        day = rule.starts_on
    for _ in range(_MAX_DAYS):
        if rule.ends_on and day > rule.ends_on:
            return None
        if _matches(rule, day):
            target = day
            if not _business(rule, day):
                target = _next_business(rule, day) if rule.non_business_rule == "next" else None
            if target is not None and not (rule.ends_on and target > rule.ends_on):
                moment = datetime.combine(target, rule.time_of_day, tzinfo=tz).astimezone(timezone.utc)
                if moment > after:
                    return moment
        day += timedelta(days=1)
    return None


def upcoming(rule: Recurrence, after: datetime, count: int = 5) -> list[datetime]:
    found: list[datetime] = []
    cursor = after
    while len(found) < count and (moment := next_occurrence(rule, cursor)) is not None:
        found.append(moment)
        cursor = moment
    return found


async def load_calendar(session: AsyncSession, calendar_id: uuid.UUID | None) -> BusinessCalendar | None:
    from sqlalchemy.orm import selectinload

    from app.sla.models import SlaCalendar

    if calendar_id is None:
        return None
    stored = (
        await session.execute(
            select(SlaCalendar).where(SlaCalendar.id == calendar_id).options(selectinload(SlaCalendar.holidays))
        )
    ).scalar_one_or_none()
    if stored is None:
        raise ValidationException("Calendário não encontrado.")
    return BusinessCalendar.from_dict({
        "timezone": stored.timezone, "weekly_hours": stored.weekly_hours,
        "holidays": [h.day.isoformat() for h in stored.holidays],
    })


async def recurrence_of(session: AsyncSession, schedule: MessageSchedule) -> Recurrence:
    hours, _, minutes = (schedule.time_of_day or "").partition(":")
    run_at = schedule.run_at
    if run_at is not None and run_at.tzinfo is None:  # SQLite devolve sem fuso
        run_at = run_at.replace(tzinfo=timezone.utc)
    return Recurrence(
        kind=schedule.recurrence,
        timezone_name=schedule.timezone,
        run_at=run_at,
        time_of_day=time(int(hours), int(minutes)) if schedule.time_of_day else None,
        weekdays=frozenset(schedule.weekdays or ()),
        month_day=schedule.month_day,
        starts_on=schedule.starts_on,
        ends_on=schedule.ends_on,
        calendar=await load_calendar(session, schedule.calendar_id),
        non_business_rule=schedule.non_business_rule,
    )


# --- Execução -------------------------------------------------------------------------------------


@dataclass
class RunResult:
    sent: int = 0
    failed: int = 0
    missed: int = 0
    paused: int = 0


def occurrence_key(schedule_id: uuid.UUID, moment: datetime) -> str:
    return hashlib.sha256(f"schedule|{schedule_id}|{moment.astimezone(timezone.utc).isoformat()}".encode()).hexdigest()


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


async def _fire(session: AsyncSession, schedule: MessageSchedule, moment: datetime, result: RunResult) -> None:
    ctx = await load_access_context(session, schedule.created_by) if schedule.created_by else None
    if ctx is None or not ctx.has(SCHEDULE):
        schedule.status = "PAUSED"
        schedule.last_outcome = "failed"
        schedule.last_error = "Pausado: quem agendou está sem acesso ou sem a permissão de agendar mensagens."
        result.paused += 1
        return
    key = occurrence_key(schedule.id, moment)
    if await svc.find_by_key(session, key) is not None:
        schedule.last_outcome, schedule.last_error = "sent", None
        return
    draft = svc.Draft(
        schedule.channel, schedule.subject, schedule.body, schedule.variables or {}, schedule.priority,
        schedule.template_id,
    )
    try:
        # validação e tetos acontecem antes de qualquer gravação: falha aqui não deixa nada pela metade
        await svc.validate_draft(session, draft)
        recipients = await svc.resolve_recipients(
            session, ctx, draft.channel, [uuid.UUID(str(r)) for r in schedule.recipient_ids or []]
        )
        outbound = await svc.enqueue(session, ctx, draft, recipients, key, kind="scheduled")
    except (BusinessRuleException, ValidationException) as err:
        schedule.last_outcome, schedule.last_error = "failed", err.message
        result.failed += 1
        return
    outbound.schedule_id = schedule.id
    outbound.scheduled_for = moment
    await session.flush()
    await AuditRepository(session).create(
        event_type="notifications.scheduled_message_sent", entity_type="notification", entity_id=outbound.id,
        data={"schedule_id": str(schedule.id), "scheduled_for": moment.isoformat(),
              "queued": outbound.queued_count, "skipped": outbound.skipped_count},
        user_id=schedule.created_by,
    )
    schedule.last_outcome, schedule.last_error = "sent", None
    schedule.runs_count += 1
    result.sent += 1


async def process(session: AsyncSession, schedule: MessageSchedule, now: datetime, result: RunResult) -> None:
    """Uma ocorrência vencida: sai (ou é pulada, se atrasou demais) e o agendamento avança para a próxima."""
    rule = await recurrence_of(session, schedule)
    moment = _utc(schedule.next_run_at)
    for _ in range(_MAX_SKIPS):  # várias perdidas seguidas: fica com a mais recente
        following = next_occurrence(rule, moment)
        if following is None or following > now:
            break
        logger.warning("Agendamento %s: ocorrência de %s perdida (worker parado)", schedule.id, moment.isoformat())
        result.missed += 1
        moment = following
    tolerance = timedelta(minutes=get_settings().MESSAGES_SCHEDULE_TOLERANCE_MINUTES)
    if now - moment > tolerance:
        late = int((now - moment).total_seconds() // 60)
        schedule.last_outcome = "missed"
        schedule.last_error = f"Ocorrência de {moment.isoformat()} pulada: {late} min de atraso (tolerância {tolerance.seconds // 60} min)."
        result.missed += 1
    else:
        await _fire(session, schedule, moment, result)
    schedule.last_run_at = now
    if schedule.status == "ACTIVE":
        schedule.next_run_at = next_occurrence(rule, moment)
        if schedule.next_run_at is None:
            schedule.status = "DONE"


async def run_due_schedules(session_factory: SessionFactory, now: datetime | None = None) -> RunResult:
    """Processa os agendamentos vencidos em lotes. Dois workers ao mesmo tempo não pegam o mesmo agendamento."""
    now = now or datetime.now(timezone.utc)
    result = RunResult()
    while True:
        async with session_factory() as session:
            due = list(
                (
                    await session.execute(
                        select(MessageSchedule)
                        .where(MessageSchedule.status == "ACTIVE", MessageSchedule.next_run_at <= now)
                        .order_by(MessageSchedule.next_run_at)
                        .limit(BATCH)
                        .with_for_update(skip_locked=True)
                    )
                ).scalars()
            )
            for schedule in due:
                await process(session, schedule, now, result)
            await session.commit()
        if len(due) < BATCH:
            return result
