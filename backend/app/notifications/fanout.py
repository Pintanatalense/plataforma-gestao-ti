"""
Fan-out: lê eventos ainda não expandidos e cria as entregas (`deliveries`) conforme as regras.

Roda dentro de uma única transação por lote: marcar `fanned_out_at` e criar as entregas são atômicos.
"""
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.audience import resolve_audience
from app.notifications.channels import ADAPTERS
from app.notifications.linking import load_addresses
from app.notifications.models import ChannelConfig, Delivery, DomainEvent, NotificationRule
from app.notifications.outbox import PRIORITY_RANK
from app.notifications.prefs import Prefs, allows, load_prefs, quiet_until
from app.notifications.templates import render

logger = logging.getLogger(__name__)

ALWAYS_ENABLED_CHANNELS = {"in_app"}
# Pseudo-canal de regra: expande para cada canal externo VERIFICADO da pessoa (ex.: Telegram vinculado).
PREFERRED = "preferred"


def rule_matches_event(rule: NotificationRule, event: DomainEvent) -> bool:
    pattern = rule.event_type
    if pattern.endswith(".*"):
        if not event.event_type.startswith(pattern[:-1]):
            return False
    elif pattern != event.event_type:
        return False

    condition = rule.condition or {}
    min_priority = condition.get("min_priority")
    if min_priority and PRIORITY_RANK.get(event.priority, 1) < PRIORITY_RANK.get(min_priority, 0):
        return False
    for key, expected in (condition.get("payload_equals") or {}).items():
        if (event.payload or {}).get(key) != expected:
            return False
    return True


def make_idempotency_key(event_id: object, rule_id: object, user_id: object, channel: str) -> str:
    return hashlib.sha256(f"{event_id}|{rule_id}|{user_id}|{channel}".encode()).hexdigest()


async def _enabled_channels(session: AsyncSession) -> set[str]:
    rows = (await session.execute(select(ChannelConfig.channel).where(ChannelConfig.enabled.is_(True)))).scalars()
    return set(rows) | ALWAYS_ENABLED_CHANNELS


@dataclass
class PlannedDelivery:
    rule: NotificationRule
    user_id: object
    email: str
    address: str
    channel: str
    message: dict
    next_attempt_at: datetime
    key: str
    escalation_condition: str | None = None


async def _plan_audience(
    session: AsyncSession, event: DomainEvent, rule: NotificationRule, selectors: list[str], channels: list[str],
    message: dict, channels_on: set[str], at: datetime, seen: set[tuple[str, str]],
    escalation_condition: str | None = None,
) -> list[PlannedDelivery]:
    exclude_actor = (rule.condition or {}).get("exclude_actor", True)
    audience = await resolve_audience(session, event, selectors, exclude_actor)
    member_ids = {m.user_id for m in audience}
    prefs_by_user = await load_prefs(session, member_ids)
    linked = await load_addresses(session, member_ids) if PREFERRED in channels else {}
    planned: list[PlannedDelivery] = []
    for member in audience:
        prefs = prefs_by_user.get(member.user_id, Prefs())
        external = linked.get(member.user_id, {})
        wanted = [c for c in channels if c != PREFERRED]
        wanted += [c for c in external if c not in wanted] if PREFERRED in channels else []
        for channel in wanted:
            if channel not in ADAPTERS or channel not in channels_on:
                logger.debug("Canal %s indisponível; regra %s ignorada para %s", channel, rule.name, member.user_id)
                continue
            if not allows(prefs, channel, event.event_type):
                continue
            if (str(member.user_id), channel) in seen:
                continue
            seen.add((str(member.user_id), channel))
            # Fora do horário de silêncio o e-mail espera o fim da janela; in-app é imediato.
            when = at if channel == "in_app" else (quiet_until(prefs, at, event.priority) or at)
            if channel == "email":
                address = member.email
            elif channel == "in_app":
                address = str(member.user_id)
            elif channel in external:
                address = external[channel]
            else:
                continue  # canal externo sem endereço verificado para esta pessoa
            key = make_idempotency_key(event.id, rule.id, member.user_id, channel)
            if escalation_condition:
                key = hashlib.sha256(f"{key}|escalation".encode()).hexdigest()
            planned.append(
                PlannedDelivery(rule, member.user_id, member.email, address, channel, message, when, key, escalation_condition)
            )
    return planned


def escalation_message(rule: NotificationRule, event: DomainEvent, minutes: int, until: str) -> dict:
    message = render(rule.template_code, event.payload or {}, event.priority).to_dict()
    reason = "sem resposta" if until == "first_response" else "sem solução"
    message["title"] = f"Escalonado ({reason} há {minutes} min): {message.get('title', '')}"
    return message


async def plan_event(
    session: AsyncSession, event: DomainEvent, rules: list[NotificationRule], channels_on: set[str], now: datetime
) -> list[PlannedDelivery]:
    """Quem recebe o quê, por onde e quando. Não grava nada (usado pelo fan-out e pelo simulador).

    Regra com escalonamento (ADR-013 §6.3, só chamados) planeja também as entregas de escalonamento, para daqui a
    `after_minutes`; o despacho confere a condição (`until`) na hora e, se ela não vale mais, a entrega vira SKIPPED.
    """
    planned: list[PlannedDelivery] = []
    seen: set[tuple[str, str]] = set()  # (user_id, canal): um destinatário recebe uma vez por canal e evento
    escalation_seen: set[tuple[str, str]] = set()
    for rule in rules:
        if not rule_matches_event(rule, event):
            continue
        message = render(rule.template_code, event.payload or {}, event.priority).to_dict()
        planned += await _plan_audience(
            session, event, rule, list(rule.audience or []), list(rule.channels or []), message, channels_on, now, seen
        )
        escalation = rule.escalation or {}
        minutes = escalation.get("after_minutes")
        if minutes and event.entity_type == "ticket":
            until = escalation.get("until", "first_response")
            planned += await _plan_audience(
                session, event, rule, list(escalation.get("audience") or []),
                list(escalation.get("channels") or rule.channels or []),
                escalation_message(rule, event, minutes, until), channels_on, now + timedelta(minutes=minutes),
                escalation_seen, escalation_condition=until,
            )
    return planned


async def enabled_channels(session: AsyncSession) -> set[str]:
    return await _enabled_channels(session)


async def fan_out_batch(session: AsyncSession, limit: int = 50) -> int:
    """Expande até `limit` eventos. Retorna quantos foram processados. O commit fica com o chamador."""
    stmt = (
        select(DomainEvent)
        .where(DomainEvent.fanned_out_at.is_(None))
        .order_by(DomainEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    events = list((await session.execute(stmt)).scalars().all())
    if not events:
        return 0

    rules = list((await session.execute(select(NotificationRule).where(NotificationRule.enabled.is_(True)))).scalars())
    channels_on = await _enabled_channels(session)
    now = datetime.now(timezone.utc)

    for event in events:
        for plan in await plan_event(session, event, rules, channels_on, now):
            exists = (
                await session.execute(select(Delivery.id).where(Delivery.idempotency_key == plan.key))
            ).scalar_one_or_none()
            if exists:
                continue
            session.add(
                Delivery(
                    event_id=event.id,
                    rule_id=plan.rule.id,
                    recipient_user_id=plan.user_id,
                    channel=plan.channel,
                    address=plan.address,
                    priority=event.priority,
                    message=plan.message,
                    next_attempt_at=plan.next_attempt_at,
                    idempotency_key=plan.key,
                    escalation_condition=plan.escalation_condition,
                )
            )
        event.fanned_out_at = now

    await session.flush()
    return len(events)
