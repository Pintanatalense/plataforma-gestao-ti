"""
MOD-11 — Notificações (Administração do hub)

Entregas, reenvio/cancelamento, regras (CRUD + simulação), saúde dos canais e agenda do worker.
Tudo exige `notifications.manage`; ações que alteram estado são auditadas.
"""
import hashlib
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.repository import AuditRepository
from app.core.dependencies import get_current_user_id, require_permission
from app.core.exceptions import BusinessRuleException, NotFoundException
from app.database import AsyncSessionLocal, get_db
from app.identity.models import UserAccount
from app.notifications.channels import ADAPTERS, build_adapter
from app.notifications.channels.base import AdapterContext
from app.notifications.fanout import enabled_channels, plan_event
from app.notifications.models import (
    Delivery,
    DeliveryAttempt,
    DomainEvent,
    NotificationRule,
    JobRun,
    ScheduledJob,
    WorkerHeartbeat,
)
from app.notifications.outbox import PRIORITY_RANK
from app.notifications.templates import TEMPLATES

router = APIRouter(
    prefix="/notifications/admin",
    tags=["Notificações — Administração"],
    dependencies=[Depends(require_permission("notifications.manage"))],
)

DB = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[uuid.UUID, Depends(get_current_user_id)]

FIXED_SELECTORS = {"requester", "assignee", "sector_attendants", "counterpart", "admins"}
CONDITION_KEYS = {"min_priority", "exclude_actor", "payload_equals"}
EVENT_TYPE = re.compile(r"^[a-z_]+(\.[a-z_]+)*(\.\*)?$")
DELIVERY_STATUSES = ("PENDING", "SENDING", "SENT", "DEAD", "SKIPPED", "CANCELLED")


async def _audit(db: AsyncSession, event_type: str, entity_id: uuid.UUID | None, data: dict, user_id: uuid.UUID) -> None:
    # A trilha exige um id de entidade; jobs não têm uuid próprio, então derivamos um estável do nome.
    entity_id = entity_id or uuid.uuid5(uuid.NAMESPACE_OID, f"notification-job:{data.get('job', '')}")
    await AuditRepository(db).create(
        event_type=event_type, entity_type="notification", entity_id=entity_id, data=data, user_id=user_id
    )


# --- Entregas -------------------------------------------------------------------------------------


def _like_escape(text: str) -> str:
    """Só o texto digitado: % e _ do usuário não viram curinga (mesmo cuidado da busca da auditoria)."""
    return text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _origin_of(rule_id: object, event_type: str | None) -> str:
    """De onde veio a entrega: regra, mensagem direta de uma pessoa, resposta do robô ou outra rotina do sistema."""
    if rule_id is not None:
        return "rule"
    if event_type and event_type.endswith(".direct_message"):
        return "direct"
    if event_type == "conversation.reply":
        return "conversation"
    return "system"


def _origin_clause(origin: str):
    if origin == "rule":
        return Delivery.rule_id.is_not(None)
    if origin == "direct":
        return and_(Delivery.rule_id.is_(None), DomainEvent.event_type.like("%.direct_message"))
    if origin == "conversation":
        return and_(Delivery.rule_id.is_(None), DomainEvent.event_type == "conversation.reply")
    return and_(
        Delivery.rule_id.is_(None),
        DomainEvent.event_type.not_like("%.direct_message"),
        DomainEvent.event_type != "conversation.reply",
    )


def _delivery_out(d: Delivery, event_type: str | None, email: str | None) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "event_id": str(d.event_id),
        "event_type": event_type,
        "channel": d.channel,
        "status": d.status,
        "priority": d.priority,
        "recipient_email": email,
        "address": d.address,
        "title": (d.message or {}).get("title"),
        "attempts": d.attempts,
        "max_attempts": d.max_attempts,
        "last_error": d.last_error,
        "next_attempt_at": d.next_attempt_at,
        "created_at": d.created_at,
        "sent_at": d.sent_at,
        "provider_status": d.provider_status,
        "provider_status_at": d.provider_status_at,
        "origin": _origin_of(d.rule_id, event_type),
    }


@router.get("/deliveries")
async def list_deliveries(
    db: DB,
    channel: str | None = None,
    status: str | None = None,
    event_type: str | None = None,
    recipient: str | None = Query(None, description="trecho do e-mail do destinatário"),
    date_from: date | None = None,
    date_to: date | None = None,
    origin: Literal["rule", "direct", "conversation", "system"] | None = None,
    provider_status: Literal["accepted", "delivered", "read", "failed", "none"] | None = Query(
        None, description="confirmação do provedor; 'none' = sem confirmação"
    ),
    address: str | None = Query(None, max_length=255, description="trecho do endereço (e-mail, telefone, chat)"),
    q: str | None = Query(None, max_length=100, description="trecho do título ou do texto da mensagem"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    base = (
        select(Delivery, DomainEvent.event_type, UserAccount.email)
        .join(DomainEvent, DomainEvent.id == Delivery.event_id)
        .outerjoin(UserAccount, UserAccount.id == Delivery.recipient_user_id)
    )
    if channel:
        base = base.where(Delivery.channel == channel)
    if status:
        base = base.where(Delivery.status == status)
    if event_type:
        base = base.where(DomainEvent.event_type == event_type)
    if recipient:
        base = base.where(UserAccount.email.ilike(f"%{recipient}%"))
    if date_from:
        base = base.where(Delivery.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        base = base.where(Delivery.created_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc))
    if origin:
        base = base.where(_origin_clause(origin))
    if provider_status == "none":
        base = base.where(Delivery.provider_status.is_(None))
    elif provider_status:
        base = base.where(Delivery.provider_status == provider_status)
    if address and address.strip():
        base = base.where(Delivery.address.ilike(f"%{_like_escape(address)}%", escape="\\"))
    if q and q.strip():
        pattern = f"%{_like_escape(q)}%"
        base = base.where(
            or_(
                Delivery.message["title"].as_string().ilike(pattern, escape="\\"),
                Delivery.message["body_text"].as_string().ilike(pattern, escape="\\"),
            )
        )

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(base.order_by(Delivery.created_at.desc()).limit(limit).offset(offset))).all()
    return {"total": total, "items": [_delivery_out(d, et, email) for d, et, email in rows]}


async def _get_delivery(db: AsyncSession, delivery_id: uuid.UUID) -> Delivery:
    delivery = (await db.execute(select(Delivery).where(Delivery.id == delivery_id))).scalar_one_or_none()
    if delivery is None:
        raise NotFoundException("Entrega", delivery_id)
    return delivery


@router.get("/deliveries/{delivery_id}")
async def get_delivery(delivery_id: uuid.UUID, db: DB):
    delivery = await _get_delivery(db, delivery_id)
    event = (await db.execute(select(DomainEvent).where(DomainEvent.id == delivery.event_id))).scalar_one()
    email = None
    if delivery.recipient_user_id:
        email = (
            await db.execute(select(UserAccount.email).where(UserAccount.id == delivery.recipient_user_id))
        ).scalar_one_or_none()
    attempts = (
        await db.execute(
            select(DeliveryAttempt).where(DeliveryAttempt.delivery_id == delivery_id).order_by(DeliveryAttempt.attempt_no)
        )
    ).scalars()
    return {
        **_delivery_out(delivery, event.event_type, email),
        "attempt_log": [
            {
                "attempt_no": a.attempt_no,
                "started_at": a.started_at,
                "finished_at": a.finished_at,
                "outcome": a.outcome,
                "error": a.error,
            }
            for a in attempts
        ],
        "event_payload": event.payload,
    }


@router.post("/deliveries/{delivery_id}/resend", status_code=201)
async def resend_delivery(delivery_id: uuid.UUID, db: DB, user_id: CurrentUser):
    """Cria uma NOVA entrega ligada ao mesmo evento (a original continua como histórico)."""
    original = await _get_delivery(db, delivery_id)
    if original.status != "DEAD":
        raise BusinessRuleException("Só entregas com falha definitiva (DEAD) podem ser reenviadas.")
    clone = Delivery(
        event_id=original.event_id,
        rule_id=original.rule_id,
        recipient_user_id=original.recipient_user_id,
        channel=original.channel,
        address=original.address,
        priority=original.priority,
        message=original.message,
        max_attempts=original.max_attempts,
        idempotency_key=hashlib.sha256(f"resend|{original.id}|{uuid.uuid4()}".encode()).hexdigest(),
    )
    db.add(clone)
    await db.flush()
    await _audit(db, "notifications.delivery_resent", clone.id, {"from_delivery": str(original.id)}, user_id)
    await db.commit()
    return {"id": str(clone.id), "status": clone.status}


@router.post("/deliveries/{delivery_id}/cancel")
async def cancel_delivery(delivery_id: uuid.UUID, db: DB, user_id: CurrentUser):
    delivery = await _get_delivery(db, delivery_id)
    if delivery.status != "PENDING":
        raise BusinessRuleException("Só entregas pendentes (PENDING) podem ser canceladas.")
    delivery.status = "CANCELLED"
    await _audit(db, "notifications.delivery_cancelled", delivery.id, {}, user_id)
    await db.commit()
    return {"id": str(delivery.id), "status": delivery.status}


# --- Regras ---------------------------------------------------------------------------------------


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    enabled: bool = True
    event_type: str = Field(max_length=100)
    condition: dict[str, Any] = {}
    audience: list[str] = Field(min_length=1)
    channels: list[str] = Field(min_length=1)
    template_code: str = "generic"

    @field_validator("event_type")
    @classmethod
    def _event_type(cls, value: str) -> str:
        if not EVENT_TYPE.match(value):
            raise ValueError("Use 'entidade.fato' ou o prefixo 'entidade.*'.")
        return value

    @field_validator("condition")
    @classmethod
    def _condition(cls, value: dict) -> dict:
        unknown = set(value) - CONDITION_KEYS
        if unknown:
            raise ValueError(f"Condições desconhecidas: {sorted(unknown)}")
        if "min_priority" in value and value["min_priority"] not in PRIORITY_RANK:
            raise ValueError("min_priority inválida.")
        return value

    @field_validator("audience")
    @classmethod
    def _audience(cls, value: list[str]) -> list[str]:
        for selector in value:
            if selector in FIXED_SELECTORS:
                continue
            if selector.startswith("role:") and len(selector) > 5:
                continue
            if selector.startswith("user:"):
                try:
                    uuid.UUID(selector[5:])
                    continue
                except ValueError:
                    pass
            raise ValueError(f"Seletor de audiência inválido: {selector}")
        return value

    @field_validator("channels")
    @classmethod
    def _channels(cls, value: list[str]) -> list[str]:
        invalid = [c for c in value if c not in ADAPTERS and c != "preferred"]
        if invalid:
            raise ValueError(f"Canais desconhecidos: {invalid}. Disponíveis: {sorted(ADAPTERS)} e 'preferred'")
        return value

    @field_validator("template_code")
    @classmethod
    def _template(cls, value: str) -> str:
        if value != "generic" and value not in TEMPLATES:
            raise ValueError(f"Modelo desconhecido: {value}")
        return value


def _rule_out(r: NotificationRule) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "code": r.code,
        "is_system": r.code is not None,
        "name": r.name,
        "enabled": r.enabled,
        "event_type": r.event_type,
        "condition": r.condition or {},
        "audience": r.audience or [],
        "channels": r.channels or [],
        "template_code": r.template_code,
    }


async def _get_rule(db: AsyncSession, rule_id: uuid.UUID) -> NotificationRule:
    rule = (await db.execute(select(NotificationRule).where(NotificationRule.id == rule_id))).scalar_one_or_none()
    if rule is None:
        raise NotFoundException("Regra", rule_id)
    return rule


@router.get("/rules")
async def list_rules(db: DB):
    rules = (await db.execute(select(NotificationRule).order_by(NotificationRule.event_type, NotificationRule.name))).scalars()
    return {
        "items": [_rule_out(r) for r in rules],
        "options": {
            "channels": [*sorted(ADAPTERS), "preferred"],
            "templates": ["generic", *sorted(TEMPLATES)],
            "selectors": [*sorted(FIXED_SELECTORS), "role:<perfil>", "user:<id>"],
        },
    }


@router.post("/rules", status_code=201)
async def create_rule(body: RuleIn, db: DB, user_id: CurrentUser):
    rule = NotificationRule(**body.model_dump())
    db.add(rule)
    await db.flush()
    await _audit(db, "notifications.rule_created", rule.id, {"name": rule.name, "event_type": rule.event_type}, user_id)
    await db.commit()
    return _rule_out(rule)


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: uuid.UUID, body: RuleIn, db: DB, user_id: CurrentUser):
    rule = await _get_rule(db, rule_id)
    for key, value in body.model_dump().items():
        setattr(rule, key, value)
    await _audit(db, "notifications.rule_updated", rule.id, {"name": rule.name, "enabled": rule.enabled}, user_id)
    await db.commit()
    return _rule_out(rule)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: uuid.UUID, db: DB, user_id: CurrentUser):
    rule = await _get_rule(db, rule_id)
    if rule.code is not None:
        raise BusinessRuleException("Regras do sistema não podem ser excluídas; desative-as.")
    await _audit(db, "notifications.rule_deleted", rule.id, {"name": rule.name}, user_id)
    await db.delete(rule)
    await db.commit()


class SimulationIn(BaseModel):
    event_type: str
    priority: str = "normal"
    actor_user_id: uuid.UUID | None = None
    payload: dict[str, Any] = {}

    @field_validator("priority")
    @classmethod
    def _priority(cls, value: str) -> str:
        if value not in PRIORITY_RANK:
            raise ValueError("Prioridade inválida.")
        return value


@router.post("/rules/simulate")
async def simulate(body: SimulationIn, db: DB):
    """Se este evento ocorresse agora, quem receberia o quê, por qual canal e quando (nada é gravado)."""
    event = DomainEvent(
        id=uuid.uuid4(),
        event_type=body.event_type,
        entity_type=body.event_type.split(".")[0],
        actor_user_id=body.actor_user_id,
        payload=body.payload,
        priority=body.priority,
    )
    rules = list((await db.execute(select(NotificationRule).where(NotificationRule.enabled.is_(True)))).scalars())
    plans = await plan_event(db, event, rules, await enabled_channels(db), datetime.now(timezone.utc))
    return {
        "deliveries": [
            {
                "rule": p.rule.name,
                "recipient_email": p.email,
                "channel": p.channel,
                "title": p.message.get("title"),
                "send_at": p.next_attempt_at,
            }
            for p in plans
        ]
    }


# --- Saúde dos canais -----------------------------------------------------------------------------


@router.get("/channels")
async def channel_health(db: DB):
    from app.notifications.models import ChannelConfig

    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)

    configs = {c.channel: c for c in (await db.execute(select(ChannelConfig))).scalars()}
    counts: dict[str, dict[str, int]] = {}
    for channel, status, n in (await db.execute(select(Delivery.channel, Delivery.status, func.count()).group_by(Delivery.channel, Delivery.status))).all():
        counts.setdefault(channel, {})[status] = n
    last_sent = dict((await db.execute(select(Delivery.channel, func.max(Delivery.sent_at)).where(Delivery.status == "SENT").group_by(Delivery.channel))).all())
    oldest_pending = dict((await db.execute(select(Delivery.channel, func.min(Delivery.next_attempt_at)).where(Delivery.status == "PENDING").group_by(Delivery.channel))).all())
    attempts_hour = {
        (channel, outcome): n
        for channel, outcome, n in (
            await db.execute(
                select(Delivery.channel, DeliveryAttempt.outcome, func.count())
                .join(Delivery, Delivery.id == DeliveryAttempt.delivery_id)
                .where(DeliveryAttempt.finished_at >= hour_ago)
                .group_by(Delivery.channel, DeliveryAttempt.outcome)
            )
        ).all()
    }

    heartbeat = (await db.execute(select(WorkerHeartbeat).where(WorkerHeartbeat.name == "notifier"))).scalar_one_or_none()
    worker_status, open_circuits = "stopped", []
    if heartbeat is not None:
        beat_at = heartbeat.beat_at if heartbeat.beat_at.tzinfo else heartbeat.beat_at.replace(tzinfo=timezone.utc)
        worker_status = "healthy" if (now - beat_at).total_seconds() < 60 else "stale"
        open_circuits = list((heartbeat.info or {}).get("open_circuits", []))

    unfanned = (
        await db.execute(select(func.count(), func.min(DomainEvent.created_at)).where(DomainEvent.fanned_out_at.is_(None)))
    ).one()

    channels = []
    for name in sorted(ADAPTERS):
        cfg = configs.get(name)
        last_error = (
            await db.execute(
                select(DeliveryAttempt.error, DeliveryAttempt.finished_at)
                .join(Delivery, Delivery.id == DeliveryAttempt.delivery_id)
                .where(Delivery.channel == name, DeliveryAttempt.outcome != "ok")
                .order_by(DeliveryAttempt.finished_at.desc())
                .limit(1)
            )
        ).first()
        failures = sum(n for (ch, outcome), n in attempts_hour.items() if ch == name and outcome != "ok")
        total_attempts = sum(n for (ch, _), n in attempts_hour.items() if ch == name)
        channels.append(
            {
                "channel": name,
                "enabled": True if name == "in_app" else bool(cfg and cfg.enabled),
                "circuit_open": name in open_circuits,
                "pending": counts.get(name, {}).get("PENDING", 0),
                "dead": counts.get(name, {}).get("DEAD", 0),
                "sent": counts.get(name, {}).get("SENT", 0),
                "last_sent_at": last_sent.get(name),
                "oldest_pending_at": oldest_pending.get(name),
                "failures_last_hour": failures,
                "attempts_last_hour": total_attempts,
                "last_error": last_error[0] if last_error else None,
                "last_error_at": last_error[1] if last_error else None,
            }
        )
    return {
        "worker": {
            "status": worker_status,
            "beat_at": heartbeat.beat_at if heartbeat else None,
            "totals": (heartbeat.info or {}) if heartbeat else {},
        },
        "events_waiting": {"count": unfanned[0], "oldest_at": unfanned[1]},
        "channels": channels,
    }


@router.post("/channels/{channel}/test")
async def test_channel(channel: str, db: DB):
    adapter = build_adapter(channel, AdapterContext(session_factory=AsyncSessionLocal))
    if adapter is None:
        raise NotFoundException("Canal", channel)
    health = await adapter.health()
    return {"channel": channel, "ok": health.ok, "detail": health.detail}


# --- Agenda ---------------------------------------------------------------------------------------


@router.get("/jobs")
async def list_jobs(db: DB):
    jobs = (await db.execute(select(ScheduledJob).order_by(ScheduledJob.name))).scalars()
    return {
        "items": [
            {
                "name": j.name,
                "schedule": j.schedule,
                "enabled": j.enabled,
                "next_run_at": j.next_run_at,
                "last_run_at": j.last_run_at,
                "last_status": j.last_status,
                "last_error": j.last_error,
                "retry_attempt": j.retry_attempt,
            }
            for j in jobs
        ]
    }


class JobPatch(BaseModel):
    enabled: bool | None = None


async def _get_job(db: AsyncSession, name: str) -> ScheduledJob:
    job = (await db.execute(select(ScheduledJob).where(ScheduledJob.name == name))).scalar_one_or_none()
    if job is None:
        raise NotFoundException("Job", name)
    return job


@router.patch("/jobs/{name}")
async def patch_job(name: str, body: JobPatch, db: DB, user_id: CurrentUser):
    job = await _get_job(db, name)
    if body.enabled is not None:
        job.enabled = body.enabled
    await _audit(db, "notifications.job_updated", None, {"job": name, "enabled": job.enabled}, user_id)
    await db.commit()
    return {"name": job.name, "enabled": job.enabled}


@router.get("/jobs/{name}/runs")
async def list_job_runs(name: str, db: DB, limit: int = Query(20, ge=1, le=100)):
    """Histórico das execuções (mais recentes primeiro): status, tentativa, duração e erro."""
    await _get_job(db, name)
    runs = (
        await db.execute(select(JobRun).where(JobRun.job_name == name).order_by(JobRun.started_at.desc()).limit(limit))
    ).scalars()
    return {
        "items": [
            {
                "id": r.id,
                "status": r.status,
                "attempt": r.attempt,
                "isolated": r.isolated,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "duration_ms": r.duration_ms,
                "error": r.error,
            }
            for r in runs
        ]
    }


@router.post("/jobs/{name}/run")
async def run_job_now(name: str, db: DB, user_id: CurrentUser):
    """Antecipa a próxima execução para agora; o worker pega no próximo ciclo (até 5 s)."""
    job = await _get_job(db, name)
    if not job.enabled:
        raise BusinessRuleException("O job está desativado.")
    job.next_run_at = datetime.now(timezone.utc)
    await _audit(db, "notifications.job_run_requested", None, {"job": name}, user_id)
    await db.commit()
    return {"name": job.name, "next_run_at": job.next_run_at}
