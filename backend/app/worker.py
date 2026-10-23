"""
Worker de notificações (ADR-013): um único processo que expande eventos em entregas, envia,
executa a agenda e publica o heartbeat.

    python -m app.worker                  # loop principal
    python -m app.worker --healthcheck    # exit 0 se o heartbeat tem menos de 60 s
"""
import asyncio
import logging
import signal
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.models_registry  # noqa: F401
from app.core.request_logging import setup_logging
from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.notifications.dispatcher import Dispatcher
from app.notifications.fanout import fan_out_batch
from app.notifications.jobs import ensure_default_jobs, run_due_jobs
from app.notifications.models import WorkerHeartbeat
from app.notifications.outbox import OUTBOX_CHANNEL
from app.notifications.rules_seed import seed_notification_rules
from app.notifications.telegram_poller import poll_forever

logger = logging.getLogger("worker")

WORKER_NAME = "notifier"
POLL_SECONDS = 5.0
HEARTBEAT_EVERY = timedelta(seconds=10)
RECOVER_EVERY = timedelta(seconds=60)
HEARTBEAT_MAX_AGE = timedelta(seconds=60)


def _asyncpg_dsn() -> str:
    return get_settings().DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


async def listen_for_wakeups(wake: asyncio.Event, stop: asyncio.Event) -> None:
    """Acorda o worker quando há evento novo. Só acelera: sem isto o poll de 5 s continua valendo."""
    import asyncpg

    while not stop.is_set():
        conn = None
        try:
            conn = await asyncpg.connect(_asyncpg_dsn())
            await conn.add_listener(OUTBOX_CHANNEL, lambda *_: wake.set())
            while not stop.is_set() and not conn.is_closed():
                await asyncio.sleep(1)
        except Exception as exc:
            logger.warning("LISTEN/NOTIFY indisponível (%s); seguindo só com poll.", exc)
            await asyncio.sleep(10)
        finally:
            if conn is not None and not conn.is_closed():
                await conn.close()


async def beat(session: AsyncSession, info: dict) -> None:
    now = datetime.now(timezone.utc)
    row = (await session.execute(select(WorkerHeartbeat).where(WorkerHeartbeat.name == WORKER_NAME))).scalar_one_or_none()
    if row is None:
        session.add(WorkerHeartbeat(name=WORKER_NAME, beat_at=now, info=info))
    else:
        row.beat_at = now
        row.info = info


async def run_cycle(dispatcher: Dispatcher) -> tuple[int, int, int]:
    """Um ciclo: fan-out, envio e agenda. Retorna (eventos expandidos, entregas tentadas, jobs rodados)."""
    async with AsyncSessionLocal() as session:
        expanded = await fan_out_batch(session)
        await session.commit()
    sent = await dispatcher.run_once()
    jobs = await run_due_jobs(AsyncSessionLocal)
    return expanded, sent, jobs


async def run(stop: asyncio.Event) -> None:
    async with AsyncSessionLocal() as session:
        created = await seed_notification_rules(session)
        jobs = await ensure_default_jobs(session)
        await session.commit()
    logger.info("Worker iniciado (regras novas: %d, jobs novos: %d)", created, jobs)

    dispatcher = Dispatcher(AsyncSessionLocal)
    wake = asyncio.Event()
    listener = None
    if engine.dialect.name == "postgresql":
        listener = asyncio.create_task(listen_for_wakeups(wake, stop))
    # Entrada do Telegram (long polling): fica ociosa enquanto o canal está desabilitado.
    poller = asyncio.create_task(poll_forever(AsyncSessionLocal, stop, wake))

    last_beat = datetime.min.replace(tzinfo=timezone.utc)
    last_recover = last_beat
    totals = {"events": 0, "deliveries": 0, "jobs": 0}

    try:
        while not stop.is_set():
            try:
                expanded, sent, jobs_run = await run_cycle(dispatcher)
                totals["events"] += expanded
                totals["deliveries"] += sent
                totals["jobs"] += jobs_run
            except Exception:
                logger.exception("Falha no ciclo do worker")
                expanded = sent = 0

            now = datetime.now(timezone.utc)
            if now - last_recover >= RECOVER_EVERY:
                recovered = await dispatcher.recover_stuck()
                if recovered:
                    logger.warning("%d entrega(s) travadas em SENDING voltaram para PENDING", recovered)
                last_recover = now
            if now - last_beat >= HEARTBEAT_EVERY:
                async with AsyncSessionLocal() as session:
                    await beat(session, {**totals, "open_circuits": sorted(dispatcher.circuit.open_channels(now))})
                    await session.commit()
                last_beat = now

            if expanded == 0 and sent == 0:
                try:
                    await asyncio.wait_for(wake.wait(), timeout=POLL_SECONDS)
                except asyncio.TimeoutError:
                    pass
                wake.clear()
    finally:
        if listener:
            listener.cancel()
        poller.cancel()


async def healthcheck() -> int:
    try:
        async with AsyncSessionLocal() as session:
            beat_at = (
                await session.execute(select(WorkerHeartbeat.beat_at).where(WorkerHeartbeat.name == WORKER_NAME))
            ).scalar_one_or_none()
    finally:
        await engine.dispose()
    if beat_at is None:
        return 1
    if beat_at.tzinfo is None:
        beat_at = beat_at.replace(tzinfo=timezone.utc)
    return 0 if datetime.now(timezone.utc) - beat_at < HEARTBEAT_MAX_AGE else 1


async def _main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass
    try:
        await run(stop)
    finally:
        await engine.dispose()
        logger.info("Worker encerrado")


if __name__ == "__main__":
    setup_logging(get_settings().LOG_LEVEL)
    if "--healthcheck" in sys.argv:
        sys.exit(asyncio.run(healthcheck()))
    asyncio.run(_main())
