"""
Central de Mensagens (ADR-025 M3): modelos, prévia, teste, envio, histórico e cancelamento.

Permissões: `notifications.messages.send` (enviar e ver os próprios envios), `notifications.messages.read` (ver todos
os envios) e `notifications.manage` (modelos, alcance a qualquer pessoa, cancelar envio de outra pessoa).
"""
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.repository import AuditRepository
from app.core.access import AccessContext
from app.core.dependencies import get_access_context, require_any_permission
from app.core.exceptions import BusinessRuleException, ForbiddenException, NotFoundException, ValidationException
from app.database import get_db
from app.notifications import messages as svc
from app.notifications.channels import ADAPTERS
from app.notifications.models import Delivery, MessageTemplate, OutboundMessage

SEND = "notifications.messages.send"
READ = "notifications.messages.read"
MANAGE = "notifications.manage"

router = APIRouter(
    prefix="/notifications/messages",
    tags=["Notificações — Central de Mensagens"],
    dependencies=[Depends(require_any_permission(SEND, READ, MANAGE))],
)

DB = Annotated[AsyncSession, Depends(get_db)]
Ctx = Annotated[AccessContext, Depends(get_access_context)]
CODE = re.compile(r"^[a-z0-9_.-]{2,60}$")


def _require(ctx: AccessContext, *codes: str) -> None:
    if not any(ctx.has(code) for code in codes):
        raise ForbiddenException("Permissão necessária: " + " ou ".join(f"'{c}'" for c in codes) + ".")


async def _audit(db: AsyncSession, event_type: str, entity_id: uuid.UUID, data: dict, user_id: uuid.UUID) -> None:
    await AuditRepository(db).create(
        event_type=event_type, entity_type="notification", entity_id=entity_id, data=data, user_id=user_id
    )


# --- Modelos --------------------------------------------------------------------------------------


class TemplateIn(BaseModel):
    code: str = Field(min_length=2, max_length=60)
    name: str = Field(min_length=1, max_length=150)
    channels: list[str] = []
    subject: str = Field("", max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def _code(cls, value: str) -> str:
        if not CODE.match(value):
            raise ValueError("Use letras minúsculas, números, ponto, hífen ou sublinhado.")
        return value

    @field_validator("channels")
    @classmethod
    def _channels(cls, value: list[str]) -> list[str]:
        unknown = [c for c in value if c not in ADAPTERS]
        if unknown:
            raise ValueError(f"Canais desconhecidos: {unknown}")
        return list(dict.fromkeys(value))


def _template_out(t: MessageTemplate) -> dict[str, Any]:
    return {
        "id": str(t.id), "code": t.code, "name": t.name, "channels": t.channels or [], "subject": t.subject,
        "body": t.body, "is_active": t.is_active, "variables": sorted(svc.placeholders(t.subject, t.body)),
    }


async def _get_template(db: AsyncSession, template_id: uuid.UUID) -> MessageTemplate:
    template = (await db.execute(select(MessageTemplate).where(MessageTemplate.id == template_id))).scalar_one_or_none()
    if template is None:
        raise NotFoundException("Modelo", template_id)
    return template


async def _ensure_code_free(db: AsyncSession, code: str, own_id: uuid.UUID | None = None) -> None:
    stmt = select(MessageTemplate.id).where(MessageTemplate.code == code)
    if own_id is not None:
        stmt = stmt.where(MessageTemplate.id != own_id)
    if (await db.execute(stmt)).first() is not None:
        raise BusinessRuleException("Já existe um modelo com este código.")


@router.get("/templates")
async def list_templates(db: DB, ctx: Ctx):
    stmt = select(MessageTemplate).order_by(MessageTemplate.name)
    if not ctx.has(MANAGE):
        stmt = stmt.where(MessageTemplate.is_active.is_(True))
    templates = (await db.execute(stmt)).scalars()
    return {"items": [_template_out(t) for t in templates], "builtin_variables": list(svc.BUILTIN_VARIABLES)}


@router.post("/templates", status_code=201)
async def create_template(body: TemplateIn, db: DB, ctx: Ctx):
    _require(ctx, MANAGE)
    await _ensure_code_free(db, body.code)
    template = MessageTemplate(**body.model_dump(), created_by=ctx.user_id)
    db.add(template)
    await db.flush()
    await _audit(db, "notifications.message_template_created", template.id, {"code": template.code}, ctx.user_id)
    await db.commit()
    return _template_out(template)


@router.put("/templates/{template_id}")
async def update_template(template_id: uuid.UUID, body: TemplateIn, db: DB, ctx: Ctx):
    _require(ctx, MANAGE)
    template = await _get_template(db, template_id)
    await _ensure_code_free(db, body.code, template.id)
    for key, value in body.model_dump().items():
        setattr(template, key, value)
    await db.flush()
    await _audit(db, "notifications.message_template_updated", template.id, {"code": template.code}, ctx.user_id)
    await db.commit()
    return _template_out(template)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(template_id: uuid.UUID, db: DB, ctx: Ctx):
    """Envios antigos guardam o texto que foi usado; o vínculo com o modelo apagado vira nulo."""
    _require(ctx, MANAGE)
    template = await _get_template(db, template_id)
    await _audit(db, "notifications.message_template_deleted", template.id, {"code": template.code}, ctx.user_id)
    # explícito (além do ON DELETE SET NULL): o vínculo some sem depender do banco aplicar a FK
    await db.execute(update(OutboundMessage).where(OutboundMessage.template_id == template.id).values(template_id=None))
    await db.delete(template)
    await db.commit()
    return Response(status_code=204)


# --- Destinatários, prévia e envio ----------------------------------------------------------------


@router.get("/recipients")
async def search_recipients(db: DB, ctx: Ctx, q: str | None = Query(None, max_length=100)):
    _require(ctx, SEND)
    return {"items": await svc.search_recipients(db, ctx, q), "reaches_everyone": svc.reaches_everyone(ctx)}


class DraftIn(BaseModel):
    channel: str
    subject: str = Field("", max_length=200)
    body: str = Field(max_length=4000)
    variables: dict[str, str] = {}
    priority: Literal["low", "normal", "high"] = "normal"
    template_id: uuid.UUID | None = None
    recipient_ids: list[uuid.UUID] = []

    @field_validator("variables")
    @classmethod
    def _variables(cls, value: dict[str, str]) -> dict[str, str]:
        for key, item in value.items():
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$", key) or len(item) > 500:
                raise ValueError("Variável inválida: use nome curto sem espaços e valor de até 500 caracteres.")
        return value


async def _draft(db: AsyncSession, body: DraftIn) -> svc.Draft:
    if body.template_id:
        template = await _get_template(db, body.template_id)
        if not template.is_active:
            raise BusinessRuleException("Este modelo está desativado.")
        if template.channels and body.channel not in template.channels:
            raise BusinessRuleException("Este modelo não é para este canal.")
    draft = svc.Draft(body.channel, body.subject, body.body, body.variables, body.priority, body.template_id)
    await svc.validate_draft(db, draft)
    return draft


@router.post("/preview")
async def preview(body: DraftIn, db: DB, ctx: Ctx):
    """Quem recebe (e quem fica de fora, e por quê) e o texto final, como o canal vai mostrar, para cada um."""
    _require(ctx, SEND)
    draft = await _draft(db, body)
    recipients = await svc.resolve_recipients(db, ctx, draft.channel, body.recipient_ids or [ctx.user_id])
    items = []
    for recipient in recipients:
        item = recipient.summary()
        if recipient.outcome == "queued":
            item["rendered"] = await svc.rendered_preview(db, draft.channel, svc.personalize(draft, recipient))
        items.append(item)
    return {
        "channel": draft.channel,
        "capabilities": ADAPTERS[draft.channel].capabilities.to_dict(),
        "recipients": items,
        "queued": sum(1 for r in recipients if r.outcome == "queued"),
        "skipped": sum(1 for r in recipients if r.outcome != "queued"),
    }


def _message_out(m: OutboundMessage, counts: dict[str, int] | None = None) -> dict[str, Any]:
    return {
        "id": str(m.id), "kind": m.kind, "channel": m.channel, "subject": m.subject, "priority": m.priority,
        "status": m.status, "queued_count": m.queued_count, "skipped_count": m.skipped_count,
        "created_at": m.created_at, "created_by": str(m.created_by) if m.created_by else None,
        "cancelled_at": m.cancelled_at, "deliveries": counts or {},
    }


@router.post("", status_code=201)
async def send(
    body: DraftIn, db: DB, ctx: Ctx, response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=100)],
):
    """Enfileira o envio. Repetir com a mesma `Idempotency-Key` (clique duplo, rede instável) devolve o mesmo envio."""
    _require(ctx, SEND)
    key = svc.idempotency_key(ctx.user_id, idempotency_key)
    existing = await svc.find_by_key(db, key)
    if existing is not None:
        response.status_code = 200
        return _message_out(existing, (await svc.delivery_counts(db, [existing.id])).get(existing.id))
    if not body.recipient_ids:
        raise ValidationException("Escolha ao menos um destinatário.")
    draft = await _draft(db, body)
    recipients = await svc.resolve_recipients(db, ctx, draft.channel, body.recipient_ids)
    try:
        outbound = await svc.enqueue(db, ctx, draft, recipients, key)
    except IntegrityError:  # a mesma chave chegou em paralelo: vale o envio que entrou primeiro
        await db.rollback()
        existing = await svc.find_by_key(db, key)
        response.status_code = 200
        return _message_out(existing, (await svc.delivery_counts(db, [existing.id])).get(existing.id))
    await _audit(db, "notifications.message_sent", outbound.id, {
        "channel": draft.channel, "queued": outbound.queued_count, "skipped": outbound.skipped_count,
        "template_id": str(draft.template_id) if draft.template_id else None,
    }, ctx.user_id)
    await db.commit()
    return _message_out(outbound, {"PENDING": outbound.queued_count})


@router.post("/test", status_code=201)
async def send_test(body: DraftIn, db: DB, ctx: Ctx):
    """Manda a mensagem só para quem está testando, pelo canal escolhido (endereço verificado da própria conta)."""
    _require(ctx, SEND)
    draft = await _draft(db, body)
    recipients = await svc.resolve_recipients(db, ctx, draft.channel, [ctx.user_id])
    if recipients[0].outcome == "no_address":
        raise BusinessRuleException("Vincule este canal à sua conta (Notificações > Minhas preferências) para testar.")
    outbound = await svc.enqueue(db, ctx, draft, recipients, uuid.uuid4().hex, kind="test")
    await db.commit()
    return _message_out(outbound, {"PENDING": outbound.queued_count})


# --- Histórico ------------------------------------------------------------------------------------


def _visible(ctx: AccessContext):
    return None if ctx.has(READ) or ctx.has(MANAGE) else OutboundMessage.created_by == ctx.user_id


@router.get("")
async def list_messages(
    db: DB, ctx: Ctx,
    channel: str | None = None,
    kind: Literal["manual", "test"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    stmt = select(OutboundMessage)
    if (own := _visible(ctx)) is not None:
        stmt = stmt.where(own)
    if channel:
        stmt = stmt.where(OutboundMessage.channel == channel)
    if kind:
        stmt = stmt.where(OutboundMessage.kind == kind)
    if date_from:
        stmt = stmt.where(OutboundMessage.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        stmt = stmt.where(
            OutboundMessage.created_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list((await db.execute(stmt.order_by(OutboundMessage.created_at.desc()).limit(limit).offset(offset))).scalars())
    counts = await svc.delivery_counts(db, [m.id for m in rows])
    return {"total": total, "items": [_message_out(m, counts.get(m.id)) for m in rows]}


async def _get_visible(db: AsyncSession, ctx: AccessContext, message_id: uuid.UUID) -> OutboundMessage:
    stmt = select(OutboundMessage).where(OutboundMessage.id == message_id)
    if (own := _visible(ctx)) is not None:
        stmt = stmt.where(own)
    message = (await db.execute(stmt)).scalar_one_or_none()
    if message is None:
        raise NotFoundException("Envio", message_id)
    return message


@router.get("/{message_id}")
async def get_message(message_id: uuid.UUID, db: DB, ctx: Ctx):
    message = await _get_visible(db, ctx, message_id)
    deliveries = (
        await db.execute(select(Delivery).where(Delivery.message_id == message.id).order_by(Delivery.created_at))
    ).scalars()
    by_user = {
        str(d.recipient_user_id): {
            "delivery_id": str(d.id), "status": d.status, "provider_status": d.provider_status,
            "attempts": d.attempts, "last_error": d.last_error, "sent_at": d.sent_at,
        }
        for d in deliveries
    }
    counts = (await svc.delivery_counts(db, [message.id])).get(message.id)
    return {
        **_message_out(message, counts),
        "body": message.body,
        "variables": message.variables,
        "template_id": str(message.template_id) if message.template_id else None,
        "recipients": [{**r, "delivery": by_user.get(r["user_id"])} for r in message.recipients],
    }


@router.post("/{message_id}/cancel")
async def cancel_message(message_id: uuid.UUID, db: DB, ctx: Ctx):
    """Cancela o que ainda não saiu. Entregas já enviadas ou em envio não voltam atrás."""
    message = await _get_visible(db, ctx, message_id)
    if message.created_by != ctx.user_id:
        _require(ctx, MANAGE)
    if message.status == "CANCELLED":
        raise BusinessRuleException("Este envio já foi cancelado.")
    result = await db.execute(
        update(Delivery)
        .where(Delivery.message_id == message.id, Delivery.status == "PENDING")
        .values(status="CANCELLED")
    )
    message.status = "CANCELLED"
    message.cancelled_at = datetime.now(timezone.utc)
    cancelled = result.rowcount or 0
    await _audit(db, "notifications.message_cancelled", message.id, {"cancelled": cancelled}, ctx.user_id)
    await db.commit()
    counts = (await svc.delivery_counts(db, [message.id])).get(message.id)
    return {**_message_out(message, counts), "cancelled": cancelled}
