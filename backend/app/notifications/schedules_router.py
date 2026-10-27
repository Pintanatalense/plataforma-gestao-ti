"""
Central de Mensagens — agendamentos (ADR-025 M4): criar, prever datas, editar, pausar, retomar e cancelar.

Permissões: `notifications.messages.schedule` (agendar e mexer nos próprios agendamentos), `notifications.messages.read`
(ver os de todos) e `notifications.manage` (também pausar, editar ou cancelar os de outra pessoa). O conteúdo e os
destinatários passam pelas mesmas validações do envio manual; quem recebe é decidido de novo a cada ocorrência.
"""
import re
import uuid
from datetime import date, datetime, time, timezone
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.repository import AuditRepository
from app.config import get_settings
from app.core.access import AccessContext
from app.core.dependencies import get_access_context, require_any_permission
from app.core.exceptions import BusinessRuleException, ConflictException, ForbiddenException, NotFoundException, ValidationException
from app.database import get_db
from app.notifications import messages as svc
from app.notifications import schedules as sched
from app.notifications.messages_router import DraftIn, _draft, _message_out
from app.notifications.models import MessageSchedule, OutboundMessage

SCHEDULE = sched.SCHEDULE
READ = "notifications.messages.read"
MANAGE = "notifications.manage"

router = APIRouter(
    prefix="/notifications/messages/schedules",
    tags=["Notificações — Central de Mensagens"],
    dependencies=[Depends(require_any_permission(SCHEDULE, READ, MANAGE))],
)

DB = Annotated[AsyncSession, Depends(get_db)]
Ctx = Annotated[AccessContext, Depends(get_access_context)]
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class RuleIn(BaseModel):
    recurrence: Literal["once", "daily", "weekly", "monthly"]
    run_at: datetime | None = None
    time_of_day: str | None = None
    weekdays: list[int] = []
    month_day: int | None = Field(None, ge=1, le=31)
    timezone: str | None = Field(None, max_length=64)
    starts_on: date | None = None
    ends_on: date | None = None
    calendar_id: uuid.UUID | None = None
    non_business_rule: Literal["skip", "next"] = "skip"

    @field_validator("weekdays")
    @classmethod
    def _weekdays(cls, value: list[int]) -> list[int]:
        if any(d not in range(7) for d in value):
            raise ValueError("Dias da semana vão de 0 (segunda) a 6 (domingo).")
        return sorted(set(value))


class ScheduleIn(DraftIn, RuleIn):
    name: str = Field(min_length=1, max_length=150)


class ScheduleUpdate(ScheduleIn):
    version: int


def _normalized_rule(body: RuleIn) -> dict[str, Any]:
    """Valida a regra e devolve só os campos que valem para o tipo escolhido."""
    tz = body.timezone or get_settings().APP_TIMEZONE
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as err:
        raise ValidationException(f"Fuso inválido: {tz}") from err
    rule: dict[str, Any] = {
        "recurrence": body.recurrence, "timezone": tz, "run_at": None, "time_of_day": None, "weekdays": [],
        "month_day": None, "starts_on": None, "ends_on": None, "calendar_id": None, "non_business_rule": "skip",
    }
    if body.recurrence == "once":
        if body.run_at is None:
            raise ValidationException("Informe a data e a hora do envio.")
        if body.run_at.tzinfo is None:
            raise ValidationException("Informe a data e a hora com fuso (ex.: 2026-11-03T09:00:00-03:00).")
        if body.calendar_id:
            raise ValidationException("O calendário de dias úteis vale só para agendamentos recorrentes.")
        rule["run_at"] = body.run_at.astimezone(timezone.utc)
        return rule
    if not body.time_of_day or not HHMM.match(body.time_of_day):
        raise ValidationException("Informe o horário no formato HH:MM.")
    if body.recurrence == "weekly" and not body.weekdays:
        raise ValidationException("Escolha ao menos um dia da semana.")
    if body.recurrence == "monthly" and body.month_day is None:
        raise ValidationException("Escolha o dia do mês.")
    if body.starts_on and body.ends_on and body.ends_on < body.starts_on:
        raise ValidationException("A data final não pode ser antes da inicial.")
    rule.update(
        time_of_day=body.time_of_day,
        weekdays=body.weekdays if body.recurrence == "weekly" else [],
        month_day=body.month_day if body.recurrence == "monthly" else None,
        starts_on=body.starts_on, ends_on=body.ends_on, calendar_id=body.calendar_id,
        non_business_rule=body.non_business_rule if body.calendar_id else "skip",
    )
    return rule


async def _recurrence(db: AsyncSession, rule: dict[str, Any]) -> sched.Recurrence:
    hours, minutes = (int(p) for p in rule["time_of_day"].split(":")) if rule["time_of_day"] else (0, 0)
    return sched.Recurrence(
        kind=rule["recurrence"], timezone_name=rule["timezone"], run_at=rule["run_at"],
        time_of_day=time(hours, minutes) if rule["time_of_day"] else None,
        weekdays=frozenset(rule["weekdays"]), month_day=rule["month_day"], starts_on=rule["starts_on"],
        ends_on=rule["ends_on"], calendar=await sched.load_calendar(db, rule["calendar_id"]),
        non_business_rule=rule["non_business_rule"],
    )


async def _first_run(db: AsyncSession, rule: dict[str, Any]) -> datetime:
    first = sched.next_occurrence(await _recurrence(db, rule), datetime.now(timezone.utc))
    if first is None:
        raise ValidationException("Esta regra não tem nenhuma data futura de envio.")
    return first


async def _check_content(db: AsyncSession, ctx: AccessContext, body: ScheduleIn) -> svc.Draft:
    """Mesmas validações do envio manual, e ao menos uma pessoa precisa poder receber hoje."""
    if not body.recipient_ids:
        raise ValidationException("Escolha ao menos um destinatário.")
    if len(body.recipient_ids) > get_settings().MESSAGES_MAX_RECIPIENTS:
        raise BusinessRuleException(f"No máximo {get_settings().MESSAGES_MAX_RECIPIENTS} destinatários por envio.")
    draft = await _draft(db, body)
    recipients = await svc.resolve_recipients(db, ctx, draft.channel, body.recipient_ids)
    if not any(r.outcome == "queued" for r in recipients):
        raise BusinessRuleException("Nenhum destinatário pode receber por este canal (veja a prévia).")
    return draft


def _require(ctx: AccessContext, *codes: str) -> None:
    if not any(ctx.has(code) for code in codes):
        raise ForbiddenException("Permissão necessária: " + " ou ".join(f"'{c}'" for c in codes) + ".")


async def _audit(db: AsyncSession, event_type: str, schedule: MessageSchedule, data: dict, user_id: uuid.UUID) -> None:
    await AuditRepository(db).create(
        event_type=event_type, entity_type="notification", entity_id=schedule.id, data=data, user_id=user_id
    )


def _visible(ctx: AccessContext):
    return None if ctx.has(READ) or ctx.has(MANAGE) else MessageSchedule.created_by == ctx.user_id


async def _get_visible(db: AsyncSession, ctx: AccessContext, schedule_id: uuid.UUID) -> MessageSchedule:
    stmt = select(MessageSchedule).where(MessageSchedule.id == schedule_id)
    if (own := _visible(ctx)) is not None:
        stmt = stmt.where(own)
    schedule = (await db.execute(stmt)).scalar_one_or_none()
    if schedule is None:
        raise NotFoundException("Agendamento", schedule_id)
    return schedule


async def _get_own_or_managed(db: AsyncSession, ctx: AccessContext, schedule_id: uuid.UUID) -> MessageSchedule:
    schedule = await _get_visible(db, ctx, schedule_id)
    if schedule.created_by == ctx.user_id:
        _require(ctx, SCHEDULE)
    else:
        _require(ctx, MANAGE)
    return schedule


def _schedule_out(s: MessageSchedule) -> dict[str, Any]:
    return {
        "id": str(s.id), "name": s.name, "channel": s.channel, "subject": s.subject, "priority": s.priority,
        "recurrence": s.recurrence, "run_at": s.run_at, "time_of_day": s.time_of_day, "weekdays": s.weekdays or [],
        "month_day": s.month_day, "timezone": s.timezone, "starts_on": s.starts_on, "ends_on": s.ends_on,
        "calendar_id": str(s.calendar_id) if s.calendar_id else None, "non_business_rule": s.non_business_rule,
        "status": s.status, "next_run_at": s.next_run_at, "last_run_at": s.last_run_at,
        "last_outcome": s.last_outcome, "last_error": s.last_error, "runs_count": s.runs_count,
        "recipient_count": len(s.recipient_ids or []), "version": s.version,
        "created_by": str(s.created_by) if s.created_by else None, "created_at": s.created_at,
    }


def _content_fields(body: ScheduleIn, rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": body.name.strip(), "channel": body.channel, "template_id": body.template_id, "subject": body.subject,
        "body": body.body, "variables": body.variables, "priority": body.priority,
        "recipient_ids": [str(r) for r in dict.fromkeys(body.recipient_ids)], **rule,
    }


@router.get("/calendars")
async def list_calendars(db: DB, ctx: Ctx):
    """Calendários de dias úteis do SLA, só nome e fuso, para quem agenda (sem exigir a permissão do SLA)."""
    from app.sla.models import SlaCalendar

    _require(ctx, SCHEDULE)
    rows = (await db.execute(select(SlaCalendar).order_by(SlaCalendar.name))).scalars()
    return {"items": [{"id": str(c.id), "name": c.name, "timezone": c.timezone} for c in rows]}


@router.post("/occurrences")
async def preview_occurrences(body: RuleIn, db: DB, ctx: Ctx):
    """As próximas datas de envio desta regra, para conferir antes de salvar."""
    _require(ctx, SCHEDULE)
    rule = _normalized_rule(body)
    return {"timezone": rule["timezone"], "occurrences": sched.upcoming(await _recurrence(db, rule), datetime.now(timezone.utc))}


@router.get("")
async def list_schedules(db: DB, ctx: Ctx, status: Literal["ACTIVE", "PAUSED", "DONE", "CANCELLED"] | None = None):
    stmt = select(MessageSchedule)
    if (own := _visible(ctx)) is not None:
        stmt = stmt.where(own)
    if status:
        stmt = stmt.where(MessageSchedule.status == status)
    rows = (await db.execute(stmt.order_by(MessageSchedule.next_run_at.is_(None), MessageSchedule.next_run_at, MessageSchedule.created_at.desc()))).scalars()
    return {"items": [_schedule_out(s) for s in rows]}


@router.post("", status_code=201)
async def create_schedule(
    body: ScheduleIn, db: DB, ctx: Ctx, response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=100)],
):
    """Cria o agendamento. Repetir com a mesma `Idempotency-Key` devolve o mesmo, sem criar outro."""
    _require(ctx, SCHEDULE)
    key = svc.idempotency_key(ctx.user_id, "schedule|" + idempotency_key)
    existing = (await db.execute(select(MessageSchedule).where(MessageSchedule.idempotency_key == key))).scalar_one_or_none()
    if existing is not None:
        response.status_code = 200
        return _schedule_out(existing)
    open_count = (
        await db.execute(
            select(func.count()).where(
                MessageSchedule.created_by == ctx.user_id, MessageSchedule.status.in_(sched.OPEN_STATUSES)
            )
        )
    ).scalar_one()
    if open_count >= get_settings().MESSAGES_MAX_ACTIVE_SCHEDULES:
        raise BusinessRuleException(
            f"Limite de {get_settings().MESSAGES_MAX_ACTIVE_SCHEDULES} agendamentos abertos por pessoa. Cancele algum antes."
        )
    rule = _normalized_rule(body)
    await _check_content(db, ctx, body)
    schedule = MessageSchedule(
        **_content_fields(body, rule), next_run_at=await _first_run(db, rule), status="ACTIVE",
        idempotency_key=key, created_by=ctx.user_id,
    )
    db.add(schedule)
    try:
        await db.flush()
    except IntegrityError:  # a mesma chave chegou em paralelo: vale o que entrou primeiro
        await db.rollback()
        existing = (await db.execute(select(MessageSchedule).where(MessageSchedule.idempotency_key == key))).scalar_one()
        response.status_code = 200
        return _schedule_out(existing)
    await _audit(db, "notifications.message_schedule_created", schedule, {
        "name": schedule.name, "channel": schedule.channel, "recurrence": schedule.recurrence,
        "recipients": len(schedule.recipient_ids), "next_run_at": schedule.next_run_at.isoformat(),
    }, ctx.user_id)
    await db.commit()
    return _schedule_out(schedule)


@router.get("/{schedule_id}")
async def get_schedule(schedule_id: uuid.UUID, db: DB, ctx: Ctx):
    schedule = await _get_visible(db, ctx, schedule_id)
    runs = list(
        (
            await db.execute(
                select(OutboundMessage).where(OutboundMessage.schedule_id == schedule.id)
                .order_by(OutboundMessage.created_at.desc()).limit(20)
            )
        ).scalars()
    )
    counts = await svc.delivery_counts(db, [m.id for m in runs])
    future: list[datetime] = []
    if schedule.status == "ACTIVE" and schedule.next_run_at:
        next_run = schedule.next_run_at if schedule.next_run_at.tzinfo else schedule.next_run_at.replace(tzinfo=timezone.utc)
        rule = await sched.recurrence_of(db, schedule)
        future = [next_run, *sched.upcoming(rule, next_run, 4)]
    return {
        **_schedule_out(schedule),
        "body": schedule.body, "variables": schedule.variables, "recipient_ids": schedule.recipient_ids,
        "template_id": str(schedule.template_id) if schedule.template_id else None,
        "upcoming": future,
        "runs": [{**_message_out(m, counts.get(m.id)), "scheduled_for": m.scheduled_for} for m in runs],
    }


@router.put("/{schedule_id}")
async def update_schedule(schedule_id: uuid.UUID, body: ScheduleUpdate, db: DB, ctx: Ctx):
    """Troca conteúdo, destinatários e regra. `version` evita sobrescrever a edição de outra pessoa."""
    schedule = await _get_own_or_managed(db, ctx, schedule_id)
    if schedule.status not in sched.OPEN_STATUSES:
        raise BusinessRuleException("Agendamento encerrado ou cancelado não pode ser editado.")
    if body.version != schedule.version:
        raise ConflictException("Este agendamento foi alterado por outra pessoa. Recarregue e tente de novo.")
    rule = _normalized_rule(body)
    await _check_content(db, ctx, body)
    for name, value in _content_fields(body, rule).items():
        setattr(schedule, name, value)
    if schedule.status == "ACTIVE":
        schedule.next_run_at = await _first_run(db, rule)
    schedule.version += 1
    await db.flush()
    await _audit(db, "notifications.message_schedule_updated", schedule, {
        "name": schedule.name, "recurrence": schedule.recurrence, "version": schedule.version,
    }, ctx.user_id)
    await db.commit()
    return _schedule_out(schedule)


@router.post("/{schedule_id}/pause")
async def pause_schedule(schedule_id: uuid.UUID, db: DB, ctx: Ctx):
    schedule = await _get_own_or_managed(db, ctx, schedule_id)
    if schedule.status != "ACTIVE":
        raise BusinessRuleException("Só agendamento ativo pode ser pausado.")
    schedule.status = "PAUSED"
    schedule.version += 1
    await _audit(db, "notifications.message_schedule_paused", schedule, {"name": schedule.name}, ctx.user_id)
    await db.commit()
    return _schedule_out(schedule)


@router.post("/{schedule_id}/resume")
async def resume_schedule(schedule_id: uuid.UUID, db: DB, ctx: Ctx):
    """Volta a valer a partir de agora: o que venceu enquanto estava pausado não é enviado."""
    schedule = await _get_own_or_managed(db, ctx, schedule_id)
    if schedule.status != "PAUSED":
        raise BusinessRuleException("Só agendamento pausado pode ser retomado.")
    upcoming = sched.next_occurrence(await sched.recurrence_of(db, schedule), datetime.now(timezone.utc))
    if upcoming is None:
        raise BusinessRuleException("Este agendamento não tem mais nenhuma data futura. Edite a regra ou cancele.")
    schedule.status = "ACTIVE"
    schedule.next_run_at = upcoming
    schedule.last_error = None
    schedule.version += 1
    await _audit(db, "notifications.message_schedule_resumed", schedule, {
        "name": schedule.name, "next_run_at": upcoming.isoformat(),
    }, ctx.user_id)
    await db.commit()
    return _schedule_out(schedule)


@router.post("/{schedule_id}/cancel")
async def cancel_schedule(schedule_id: uuid.UUID, db: DB, ctx: Ctx):
    """Nenhuma ocorrência futura sai. Envios já feitos continuam no histórico (e o que estiver pendente lá pode ser
    cancelado pelo histórico)."""
    schedule = await _get_own_or_managed(db, ctx, schedule_id)
    if schedule.status not in sched.OPEN_STATUSES:
        raise BusinessRuleException("Este agendamento já está encerrado ou cancelado.")
    schedule.status = "CANCELLED"
    schedule.next_run_at = None
    schedule.version += 1
    await _audit(db, "notifications.message_schedule_cancelled", schedule, {"name": schedule.name}, ctx.user_id)
    await db.commit()
    return _schedule_out(schedule)
