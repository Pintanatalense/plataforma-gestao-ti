"""
Fan-out: lê eventos ainda não expandidos e cria as entregas (`deliveries`) conforme as regras.

Roda dentro de uma única transação por lote: marcar `fanned_out_at` e criar as entregas são atômicos.
"""
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.audience import resolve_audience
from app.notifications.channels import ADAPTERS
from app.notifications.models import ChannelConfig, Delivery, DomainEvent, NotificationRule
from app.notifications.outbox import PRIORITY_RANK
from app.notifications.prefs import Prefs, allows, load_prefs, quiet_until
from app.notifications.templates import render

logger = logging.getLogger(__name__)

ALWAYS_ENABLED_CHANNELS = {"in_app"}


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
    channel: str
    message: dict
    next_attempt_at: datetime
    key: str


async def plan_event(
    session: AsyncSession, event: DomainEvent, rules: list[NotificationRule], channels_on: set[str], now: datetime
) -> list[PlannedDelivery]:
    """Quem recebe o quê, por onde e quando. Não grava nada (usado pelo fan-out e pelo simulador)."""
    planned: list[PlannedDelivery] = []
    seen: set[tuple[str, str]] = set()  # (user_id, canal): um destinatário recebe uma vez por canal e evento
    for rule in rules:
        if not rule_matches_event(rule, event):
            continue
        exclude_actor = (rule.condition or {}).get("exclude_actor", True)
        audience = await resolve_audience(session, event, list(rule.audience or []), exclude_actor)
        message = render(rule.template_code, event.payload or {}, event.priority).to_dict()
        prefs_by_user = await load_prefs(session, {m.user_id for m in audience})
        for member in audience:
            prefs = prefs_by_user.get(member.user_id, Prefs())
            for channel in rule.channels or []:
                if channel not in ADAPTERS or channel not in channels_on:
                    logger.debug("Canal %s indisponível; regra %s ignorada para %s", channel, rule.name, member.user_id)
                    continue
                if not allows(prefs, channel, event.event_type):
                    continue
                if (str(member.user_id), channel) in seen:
                    continue
                seen.add((str(member.user_id), channel))
                # Fora do horário de silêncio o e-mail espera o fim da janela; in-app é imediato.
                when = now if channel == "in_app" else (quiet_until(prefs, now, event.priority) or now)
                planned.append(
                    PlannedDelivery(
                        rule, member.user_id, member.email, channel, message, when,
                        make_idempotency_key(event.id, rule.id, member.user_id, channel),
                    )
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
                    address=plan.email if plan.channel == "email" else str(plan.user_id),
                    priority=event.priority,
                    message=plan.message,
                    next_attempt_at=plan.next_attempt_at,
                    idempotency_key=plan.key,
                )
            )
        event.fanned_out_at = now

    await session.flush()
    return len(events)
