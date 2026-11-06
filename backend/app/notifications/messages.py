"""
Central de Mensagens (ADR-025 M3): envio manual a pessoas escolhidas, com modelos, variáveis, prévia e teste.

Não há fila nova: cada destinatário vira uma `deliveries` ligada a um `domain_events` já expandido (como a mensagem
direta) e a `outbound_messages`, e o worker envia com as mesmas retentativas, ritmo e circuito de tudo o mais.

Regras:
- só vai a endereço VERIFICADO (e-mail da conta; demais canais, só depois do vínculo por código);
- quem tem só `notifications.messages.send` alcança pessoas do próprio setor; com `notifications.manage` ou
  `service_desk.tickets.read_all`, qualquer pessoa ativa;
- tetos contra disparo em massa: destinatários por envio e envios por pessoa por hora (`MESSAGES_MAX_*`);
- a prévia usa as mesmas funções de formatação que o adapter usa ao enviar.
"""
import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import escape

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.access import AccessContext
from app.core.exceptions import BusinessRuleException, ValidationException
from app.identity.models import UserAccount
from app.notifications.channel_store import load_channel
from app.notifications.channels import ADAPTERS
from app.notifications.channels.base import Message
from app.notifications.fanout import enabled_channels
from app.notifications.jobs import local_timezone
from app.notifications.linking import load_addresses
from app.notifications.models import Delivery, DomainEvent, OutboundMessage
from app.notifications.templates import html_frame
from app.organization.models import Company, Employee

MANAGE = "notifications.manage"
READ_ALL_TICKETS = "service_desk.tickets.read_all"
EVENT_TYPE = "message.manual"
TEST_MAX_PER_HOUR = 10
LOCAL_CHANNELS = {"in_app", "email"}  # endereço vem da própria conta

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
BUILTIN_VARIABLES = ("nome", "email", "empresa", "data", "hora")
BOLD = re.compile(r"\*\*(.+?)\*\*")
URL = re.compile(r"https?://[^\s<>\"']+")


# --- Variáveis e formatação -----------------------------------------------------------------------


def placeholders(*texts: str) -> set[str]:
    return {name.lower() for text in texts for name in PLACEHOLDER.findall(text or "")}


def fill(text: str, context: dict[str, str]) -> str:
    """Troca `{{nome}}` (com ou sem espaços, sem diferenciar maiúsculas) pelo valor; desconhecida fica como está."""
    return PLACEHOLDER.sub(lambda m: context.get(m.group(1).lower(), m.group(0)), text or "")


def to_text(body: str, formatting: str) -> str:
    """Marcação neutra (`**negrito**`, `- item`, links soltos) no texto do canal."""
    if formatting in ("whatsapp", "slack"):
        return BOLD.sub(r"*\1*", body)
    return BOLD.sub(r"\1", body)


def to_html(body: str) -> str:
    """Marcação neutra em HTML de e-mail: tudo escapado; negrito, listas, links e quebras de linha."""
    def inline(line: str) -> str:
        escaped = escape(line)
        escaped = URL.sub(lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>', escaped)
        return BOLD.sub(r"<strong>\1</strong>", escaped)

    parts: list[str] = []
    items: list[str] = []
    for line in body.splitlines():
        if line.startswith("- "):
            items.append(f"<li>{inline(line[2:])}</li>")
            continue
        if items:
            parts.append("<ul>" + "".join(items) + "</ul>")
            items = []
        parts.append(f'<p style="font-size:15px;color:#334155;margin:8px 0;">{inline(line)}</p>' if line.strip() else "")
    if items:
        parts.append("<ul>" + "".join(items) + "</ul>")
    return "".join(parts)


def build_message(channel: str, subject: str, body: str, priority: str) -> Message:
    formatting = ADAPTERS[channel].capabilities.formatting
    return Message(
        title=subject,
        body_text=to_text(body, formatting),
        body_html=html_frame(subject, to_html(body), link=False) if channel == "email" else None,
        priority=priority,
        entity_type="message",
    )


async def rendered_preview(session: AsyncSession, channel: str, message: Message) -> dict:
    """O que o adapter vai mandar, pelas mesmas funções que ele usa."""
    from app.notifications.channels import slack, telegram, whatsapp
    from app.notifications.channels import whatsapp_evolution as evolution

    stored = await load_channel(session, channel)
    base_url = (stored.config.get("app_base_url") if stored else None) or None
    if channel == "email":
        return {"subject": message.title, "html": message.body_html, "text": message.body_text}
    if channel == "telegram":
        return {"text": telegram.render_text(message, base_url)}
    if channel == "slack":
        return {"text": slack.render_text(message, base_url)}
    if channel == "whatsapp":
        meta = whatsapp.provider_of(stored) != whatsapp.PROVIDER_EVOLUTION
        text = (whatsapp if meta else evolution).render_text(message, base_url)
        note = "Pela Meta, fora da janela de 24 h só vai o modelo aprovado." if meta else None
        return {"text": text, "note": note}
    return {"title": message.title, "text": message.body_text}


# --- Destinatários --------------------------------------------------------------------------------


@dataclass
class Recipient:
    user_id: uuid.UUID
    email: str
    name: str
    sector_id: uuid.UUID | None
    address: str | None = None
    outcome: str = "queued"  # queued, no_address, out_of_scope, inactive, unknown
    context: dict[str, str] = field(default_factory=dict)

    def summary(self) -> dict:
        return {"user_id": str(self.user_id), "email": self.email, "name": self.name, "outcome": self.outcome}


def reaches_everyone(ctx: AccessContext) -> bool:
    return ctx.has(MANAGE) or ctx.has(READ_ALL_TICKETS)


async def search_recipients(session: AsyncSession, ctx: AccessContext, q: str | None, limit: int = 20) -> list[dict]:
    """Pessoas que quem envia pode alcançar, com os canais verificados de cada uma (sem os endereços)."""
    stmt = (
        select(UserAccount, Employee)
        .outerjoin(Employee, Employee.id == UserAccount.employee_id)
        .where(UserAccount.is_active.is_(True))
        .order_by(func.coalesce(Employee.name, UserAccount.email))
        .limit(limit)
    )
    if not reaches_everyone(ctx):
        if ctx.sector_id is None:
            stmt = stmt.where(UserAccount.id == ctx.user_id)
        else:
            stmt = stmt.where(Employee.sector_id == ctx.sector_id)
    if q and q.strip():
        pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(UserAccount.email.ilike(pattern, escape="\\") | Employee.name.ilike(pattern, escape="\\"))
    rows = (await session.execute(stmt)).all()
    linked = await load_addresses(session, {user.id for user, _ in rows})
    return [
        {
            "user_id": str(user.id),
            "name": employee.name if employee else user.email.split("@")[0],
            "email": user.email,
            "channels": sorted(LOCAL_CHANNELS | set(linked.get(user.id, {}))),
        }
        for user, employee in rows
    ]


async def resolve_recipients(
    session: AsyncSession, ctx: AccessContext, channel: str, user_ids: list[uuid.UUID]
) -> list[Recipient]:
    wanted = list(dict.fromkeys(user_ids))  # sem repetição, na ordem pedida
    rows = (
        await session.execute(
            select(UserAccount, Employee)
            .outerjoin(Employee, Employee.id == UserAccount.employee_id)
            .where(UserAccount.id.in_(wanted))
        )
    ).all()
    by_id = {user.id: (user, employee) for user, employee in rows}
    linked = await load_addresses(session, set(by_id)) if channel not in LOCAL_CHANNELS else {}
    everyone = reaches_everyone(ctx)
    company = (await session.execute(select(Company.name).limit(1))).scalar_one_or_none() or "Gestão de TI"
    now = datetime.now(local_timezone())

    found: list[Recipient] = []
    for user_id in wanted:
        if user_id not in by_id:
            found.append(Recipient(user_id, "", "", None, outcome="unknown"))
            continue
        user, employee = by_id[user_id]
        recipient = Recipient(
            user.id, user.email, employee.name if employee else user.email.split("@")[0],
            employee.sector_id if employee else None,
        )
        recipient.context = {
            "nome": recipient.name, "email": user.email, "empresa": company,
            "data": now.strftime("%d/%m/%Y"), "hora": now.strftime("%H:%M"),
        }
        if not user.is_active:
            recipient.outcome = "inactive"
        elif not everyone and user.id != ctx.user_id and (ctx.sector_id is None or recipient.sector_id != ctx.sector_id):
            recipient.outcome = "out_of_scope"
        elif channel == "in_app":
            recipient.address = str(user.id)
        elif channel == "email":
            recipient.address = user.email
        else:
            recipient.address = linked.get(user.id, {}).get(channel)
            if not recipient.address:
                recipient.outcome = "no_address"
        found.append(recipient)
    return found


# --- Envio ----------------------------------------------------------------------------------------


@dataclass
class Draft:
    channel: str
    subject: str
    body: str
    variables: dict[str, str]
    priority: str = "normal"
    template_id: uuid.UUID | None = None


async def validate_draft(session: AsyncSession, draft: Draft) -> None:
    if draft.channel not in ADAPTERS:
        raise ValidationException(f"Canal desconhecido: {draft.channel}")
    if draft.channel not in await enabled_channels(session):
        raise BusinessRuleException("Este canal não está habilitado pela administração.")
    if not draft.body.strip():
        raise ValidationException("Escreva a mensagem.")
    missing = placeholders(draft.subject, draft.body) - set(BUILTIN_VARIABLES) - {k.lower() for k in draft.variables}
    if missing:
        raise ValidationException(f"Preencha as variáveis: {', '.join(sorted(missing))}.")
    max_len = ADAPTERS[draft.channel].capabilities.max_len
    if max_len and len(draft.subject) + len(draft.body) > max_len:
        raise ValidationException(f"A mensagem passa do limite deste canal ({max_len} caracteres).")


def personalize(draft: Draft, recipient: Recipient) -> Message:
    context = {**recipient.context, **{k.lower(): str(v) for k, v in draft.variables.items()}}
    return build_message(draft.channel, fill(draft.subject, context), fill(draft.body, context), draft.priority)


async def _check_hourly_cap(session: AsyncSession, user_id: uuid.UUID, kind: str) -> None:
    cap = TEST_MAX_PER_HOUR if kind == "test" else get_settings().MESSAGES_MAX_PER_HOUR
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    sent = (
        await session.execute(
            select(func.count()).where(
                OutboundMessage.created_by == user_id, OutboundMessage.kind == kind, OutboundMessage.created_at >= since
            )
        )
    ).scalar_one()
    if sent >= cap:
        what = "testes" if kind == "test" else "envios"
        raise BusinessRuleException(f"Limite de {cap} {what} por hora atingido. Tente de novo mais tarde.")


def idempotency_key(user_id: uuid.UUID, client_key: str) -> str:
    return hashlib.sha256(f"message|{user_id}|{client_key}".encode()).hexdigest()


async def find_by_key(session: AsyncSession, key: str) -> OutboundMessage | None:
    return (await session.execute(select(OutboundMessage).where(OutboundMessage.idempotency_key == key))).scalar_one_or_none()


async def enqueue(
    session: AsyncSession, ctx: AccessContext, draft: Draft, recipients: list[Recipient], key: str, kind: str = "manual"
) -> OutboundMessage:
    """Grava o envio e uma entrega por destinatário alcançável. O commit fica com o chamador."""
    if len(recipients) > get_settings().MESSAGES_MAX_RECIPIENTS:
        raise BusinessRuleException(f"No máximo {get_settings().MESSAGES_MAX_RECIPIENTS} destinatários por envio.")
    await _check_hourly_cap(session, ctx.user_id, kind)
    reachable = [r for r in recipients if r.outcome == "queued"]
    if not reachable:
        raise BusinessRuleException("Nenhum destinatário pode receber por este canal (veja a prévia).")

    outbound = OutboundMessage(
        kind=kind, channel=draft.channel, template_id=draft.template_id, subject=draft.subject, body=draft.body,
        variables=draft.variables, priority=draft.priority, recipients=[r.summary() for r in recipients],
        queued_count=len(reachable), skipped_count=len(recipients) - len(reachable), idempotency_key=key,
        created_by=ctx.user_id,
    )
    session.add(outbound)
    await session.flush()
    now = datetime.now(timezone.utc)
    event = DomainEvent(
        event_type=EVENT_TYPE, entity_type="message", entity_id=outbound.id, actor_user_id=ctx.user_id,
        payload={"channel": draft.channel, "kind": kind},  # o texto fica só nas entregas e no envio
        priority=draft.priority, fanned_out_at=now,
    )
    session.add(event)
    await session.flush()
    for recipient in reachable:
        session.add(
            Delivery(
                event_id=event.id, message_id=outbound.id, recipient_user_id=recipient.user_id, channel=draft.channel,
                address=recipient.address, priority=draft.priority,
                message=personalize(draft, recipient).to_dict(), next_attempt_at=now,
                idempotency_key=hashlib.sha256(f"message|{outbound.id}|{recipient.user_id}".encode()).hexdigest(),
            )
        )
    await session.flush()
    return outbound


async def delivery_counts(session: AsyncSession, message_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    rows = await session.execute(
        select(Delivery.message_id, Delivery.status, func.count())
        .where(Delivery.message_id.in_(message_ids))
        .group_by(Delivery.message_id, Delivery.status)
    )
    counts: dict[uuid.UUID, dict[str, int]] = {}
    for message_id, status, n in rows.all():
        counts.setdefault(message_id, {})[status] = n
    return counts
