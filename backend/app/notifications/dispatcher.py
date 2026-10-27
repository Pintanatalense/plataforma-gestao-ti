"""
Despacho de entregas: reivindica `PENDING`, envia FORA da transação, registra tentativa e resultado.

Semântica at-least-once (ADR-013 §4.3): `SENDING` é gravado antes do envio; se o processo morrer
entre o envio e o commit do resultado, a recuperação devolve a entrega a `PENDING` e ela pode duplicar.
"""
import asyncio
import logging
import random
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, select, update

from app.notifications.channels import build_adapter
from app.notifications.channels.base import AdapterContext, DeliveryResult, Message, Recipient, SessionFactory
from app.notifications.channel_store import rate_override
from app.notifications.models import ChannelConfig, Delivery, DeliveryAttempt
from app.notifications.outbox import emit_event

logger = logging.getLogger(__name__)

BACKOFF_SECONDS = (30, 120, 600, 3600, 21600)
STUCK_AFTER = timedelta(minutes=5)
CIRCUIT_FAILURES = 5
CIRCUIT_OPEN_FOR = timedelta(minutes=5)

_PRIORITY_ORDER = {"critical": 3, "high": 2, "normal": 1, "low": 0}


def backoff_delay(attempts: int, retry_after: int | None = None) -> timedelta:
    """Atraso antes da próxima tentativa (`attempts` = tentativas já feitas), com jitter de ±20%."""
    if retry_after:
        return timedelta(seconds=retry_after)
    base = BACKOFF_SECONDS[min(max(attempts, 1), len(BACKOFF_SECONDS)) - 1]
    return timedelta(seconds=base * random.uniform(0.8, 1.2))


def effective_rate(ceiling: float | None, override: float | None) -> float | None:
    """Ritmo aplicado: o do administrador, nunca acima do teto do canal."""
    if override is None:
        return ceiling
    return override if ceiling is None else min(ceiling, override)


class ChannelCircuit:
    """Pausa um canal após falhas consecutivas, sem consumir tentativas das entregas."""

    def __init__(self) -> None:
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, datetime] = {}

    def is_open(self, channel: str, now: datetime) -> bool:
        until = self._open_until.get(channel)
        return until is not None and until > now

    def open_channels(self, now: datetime) -> set[str]:
        return {c for c in self._open_until if self.is_open(c, now)}

    def record_success(self, channel: str) -> None:
        self._failures.pop(channel, None)
        self._open_until.pop(channel, None)

    def record_failure(self, channel: str, now: datetime) -> bool:
        """Retorna True quando o canal acabou de passar de saudável para degradado."""
        before = self._failures.get(channel, 0)
        self._failures[channel] = before + 1
        if self._failures[channel] >= CIRCUIT_FAILURES:
            self._open_until[channel] = now + CIRCUIT_OPEN_FOR
            return before + 1 == CIRCUIT_FAILURES
        return False


class Dispatcher:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._ctx = AdapterContext(session_factory=session_factory)
        self._adapters: dict[str, object] = {}
        self._last_send: dict[str, float] = {}
        self._rate_override: dict[str, float | None] = {}
        self.circuit = ChannelCircuit()

    def _adapter(self, channel: str):
        if channel not in self._adapters:
            self._adapters[channel] = build_adapter(channel, self._ctx)
        return self._adapters[channel]

    async def recover_stuck(self) -> int:
        """`SENDING` abandonado (processo morreu) volta a `PENDING`."""
        limit = datetime.now(timezone.utc) - STUCK_AFTER
        async with self._session_factory() as session:
            result = await session.execute(
                update(Delivery)
                .where(Delivery.status == "SENDING", Delivery.locked_at < limit)
                .values(status="PENDING", locked_at=None)
            )
            await session.commit()
            return result.rowcount or 0

    async def _claim(self, limit: int) -> list[Delivery]:
        now = datetime.now(timezone.utc)
        paused = self.circuit.open_channels(now)
        stmt = select(Delivery).where(Delivery.status == "PENDING", Delivery.next_attempt_at <= now)
        if paused:
            stmt = stmt.where(Delivery.channel.not_in(paused))
        stmt = (
            stmt.order_by(
                case(_PRIORITY_ORDER, value=Delivery.priority, else_=1).desc(), Delivery.next_attempt_at
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        async with self._session_factory() as session:
            batch = list((await session.execute(stmt)).scalars().all())
            for delivery in batch:
                delivery.status = "SENDING"
                delivery.locked_at = now
            await session.commit()
            if batch:
                # Limite do administrador (só para baixo do teto do canal), relido a cada lote: mudar na tela vale já.
                configs = await session.execute(
                    select(ChannelConfig.channel, ChannelConfig.config).where(
                        ChannelConfig.channel.in_({d.channel for d in batch})
                    )
                )
                self._rate_override = {channel: rate_override(config) for channel, config in configs.all()}
        return batch

    async def _throttle(self, channel: str, rate_per_second: float | None) -> None:
        if not rate_per_second:
            return
        wait = self._last_send.get(channel, 0.0) + 1.0 / rate_per_second - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_send[channel] = time.monotonic()

    async def _send(self, delivery: Delivery) -> DeliveryResult:
        adapter = self._adapter(delivery.channel)
        if adapter is None:
            return DeliveryResult("permanent", error=f"Canal desconhecido: {delivery.channel}")
        rate = effective_rate(adapter.capabilities.rate_per_second, self._rate_override.get(delivery.channel))
        await self._throttle(delivery.channel, rate)
        recipient = Recipient(
            address=delivery.address,
            user_id=str(delivery.recipient_user_id) if delivery.recipient_user_id else None,
        )
        try:
            return await adapter.send(recipient, Message.from_dict(delivery.message))
        except Exception as exc:
            logger.exception("Adapter %s lançou exceção", delivery.channel)
            return DeliveryResult("retryable", error=f"{type(exc).__name__}: {exc}")

    async def _record(self, delivery_id, started: datetime, result: DeliveryResult) -> bool:
        """Grava tentativa e novo estado. Retorna True se o canal acabou de degradar."""
        finished = datetime.now(timezone.utc)
        if result.deferred:
            async with self._session_factory() as session:
                delivery = (
                    await session.execute(select(Delivery).where(Delivery.id == delivery_id).with_for_update())
                ).scalar_one()
                delivery.status = "PENDING"
                delivery.locked_at = None
                delivery.next_attempt_at = finished + timedelta(seconds=max(result.retry_after_seconds or 1, 1))
                await session.commit()
            return False
        async with self._session_factory() as session:
            delivery = (
                await session.execute(select(Delivery).where(Delivery.id == delivery_id).with_for_update())
            ).scalar_one()
            delivery.attempts += 1
            delivery.locked_at = None
            delivery.last_error = result.error
            session.add(
                DeliveryAttempt(
                    delivery_id=delivery.id,
                    attempt_no=delivery.attempts,
                    started_at=started,
                    finished_at=finished,
                    outcome=result.outcome,
                    error=(result.error or "")[:2000] or None,
                )
            )
            degraded = False
            if result.outcome == "ok":
                delivery.status = "SENT"
                delivery.sent_at = finished
                delivery.provider_message_id = result.provider_message_id
                self.circuit.record_success(delivery.channel)
            elif result.outcome == "permanent" or delivery.attempts >= delivery.max_attempts:
                delivery.status = "DEAD"
                degraded = result.outcome == "retryable" and self.circuit.record_failure(delivery.channel, finished)
            else:
                delivery.status = "PENDING"
                delivery.next_attempt_at = finished + backoff_delay(delivery.attempts, result.retry_after_seconds)
                degraded = self.circuit.record_failure(delivery.channel, finished)
            channel, error = delivery.channel, result.error
            await session.commit()

        if degraded:
            await self._announce_degraded(channel, error)
        return degraded

    async def _announce_degraded(self, channel: str, error: str | None) -> None:
        async with self._session_factory() as session:
            await emit_event(
                session,
                event_type="channel.degraded",
                entity_type="channel",
                entity_id=None,
                payload={"channel": channel, "error": (error or "")[:300]},
                priority="high",
            )
            await session.commit()
        logger.warning("Canal %s degradado: entregas pausadas por %s", channel, CIRCUIT_OPEN_FOR)

    async def run_once(self, limit: int = 20) -> int:
        """Reivindica e envia um lote. Retorna quantas entregas foram tentadas."""
        batch = await self._claim(limit)
        for delivery in batch:
            started = datetime.now(timezone.utc)
            result = await self._send(delivery)
            await self._record(delivery.id, started, result)
        return len(batch)
