"""
Worker de notificações (ADR-013; papéis e agenda isolada: ADR-024, Plano de Evolução Fase 0 PR 12).

Dois laços independentes, cada um com o seu heartbeat:

* **entregas** (``notifier``): expande eventos em entregas, envia, recupera entregas travadas e recebe o Telegram;
* **agenda** (``scheduler``): roda os jobs (``app/notifications/job_runner.py``). Um job lento ou preso nunca
  atrasa uma notificação: os laços não se esperam e os jobs pesados rodam em subprocesso com tempo máximo.

    python -m app.worker                       # papel em WORKER_ROLE (padrão: all = os dois laços)
    python -m app.worker --role delivery       # só entregas  (ex.: contêiner separado)
    python -m app.worker --role jobs           # só a agenda
    python -m app.worker --healthcheck         # exit 0 se os heartbeats do papel têm menos de 60 s
    python -m app.worker --run-job NOME ...    # uso interno: subprocesso de um job isolado
"""
import argparse
import asyncio
import logging
import os
import signal
import sys
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.models_registry  # noqa: F401
from app.core.request_logging import setup_logging
from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.notifications.dispatcher import Dispatcher
from app.notifications.fanout import fan_out_batch
from app.notifications.job_runner import claim_due, recover_interrupted, run_claimed, run_job_in_child
from app.notifications.jobs import ensure_default_jobs
from app.notifications.models import WorkerHeartbeat
from app.notifications.outbox import OUTBOX_CHANNEL
from app.notifications.rules_seed import seed_notification_rules
from app.notifications.telegram_poller import poll_forever

logger = logging.getLogger("worker")

WORKER_NAME = "notifier"  # laço de entregas (nome mantido: a tela e o /health já o leem)
SCHEDULER_NAME = "scheduler"
ROLES = {"all": (WORKER_NAME, SCHEDULER_NAME), "delivery": (WORKER_NAME,), "jobs": (SCHEDULER_NAME,)}
POLL_SECONDS = 5.0
JOBS_POLL_SECONDS = 5.0
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


async def beat(session: AsyncSession, info: dict, name: str = WORKER_NAME) -> None:
    now = datetime.now(timezone.utc)
    row = (await session.execute(select(WorkerHeartbeat).where(WorkerHeartbeat.name == name))).scalar_one_or_none()
    if row is None:
        session.add(WorkerHeartbeat(name=name, beat_at=now, info=info))
    else:
        row.beat_at = now
        row.info = info


async def run_cycle(dispatcher: Dispatcher) -> tuple[int, int]:
    """Um ciclo de entregas: fan-out e envio. Retorna (eventos expandidos, entregas tentadas)."""
    async with AsyncSessionLocal() as session:
        expanded = await fan_out_batch(session)
        await session.commit()
    sent = await dispatcher.run_once()
    return expanded, sent


async def jobs_loop(stop: asyncio.Event, session_factory=AsyncSessionLocal, poll_seconds: float = JOBS_POLL_SECONDS) -> None:
    """Laço da agenda: cada execução reservada vira uma tarefa própria; o laço segue reservando as outras."""
    running: set[asyncio.Task] = set()
    last_beat = datetime.min.replace(tzinfo=timezone.utc)
    totals = {"jobs": 0, "interrupted": 0}
    try:
        while not stop.is_set():
            try:
                totals["interrupted"] += await recover_interrupted(session_factory)
                for name, run_id in await claim_due(session_factory):
                    task = asyncio.create_task(run_claimed(session_factory, name, run_id), name=f"job:{name}")
                    running.add(task)
                    task.add_done_callback(running.discard)
                    totals["jobs"] += 1
            except Exception:
                logger.exception("Falha no laço da agenda")
            now = datetime.now(timezone.utc)
            if now - last_beat >= HEARTBEAT_EVERY:
                try:
                    async with session_factory() as session:
                        await beat(session, {**totals, "running": sorted(t.get_name() for t in running)}, SCHEDULER_NAME)
                        await session.commit()
                    last_beat = now
                except Exception:
                    logger.exception("Falha ao publicar o heartbeat da agenda")
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
            except asyncio.TimeoutError:
                pass
    finally:
        for task in running:  # o subprocesso de um job isolado é encerrado junto (CancelledError)
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)


async def run(stop: asyncio.Event, role: str = "all") -> None:
    async with AsyncSessionLocal() as session:
        created = await seed_notification_rules(session)
        jobs = await ensure_default_jobs(session)
        await session.commit()
    logger.info("Worker iniciado (papel: %s; regras novas: %d, jobs novos: %d)", role, created, jobs)

    scheduler = asyncio.create_task(jobs_loop(stop)) if role in ("all", "jobs") else None
    try:
        if role in ("all", "delivery"):
            await delivery_loop(stop)
        else:
            await stop.wait()
    finally:
        if scheduler is not None:
            stop.set()
            await scheduler


async def delivery_loop(stop: asyncio.Event) -> None:
    dispatcher = Dispatcher(AsyncSessionLocal)
    wake = asyncio.Event()
    listener = None
    if engine.dialect.name == "postgresql":
        listener = asyncio.create_task(listen_for_wakeups(wake, stop))
    # Entrada do Telegram (long polling): fica ociosa enquanto o canal está desabilitado.
    poller = asyncio.create_task(poll_forever(AsyncSessionLocal, stop, wake))

    last_beat = datetime.min.replace(tzinfo=timezone.utc)
    last_recover = last_beat
    totals = {"events": 0, "deliveries": 0}

    try:
        while not stop.is_set():
            try:
                expanded, sent = await run_cycle(dispatcher)
                totals["events"] += expanded
                totals["deliveries"] += sent
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


async def healthcheck(role: str = "all") -> int:
    try:
        async with AsyncSessionLocal() as session:
            beats = dict(
                (
                    await session.execute(
                        select(WorkerHeartbeat.name, WorkerHeartbeat.beat_at).where(WorkerHeartbeat.name.in_(ROLES[role]))
                    )
                ).all()
            )
    finally:
        await engine.dispose()
    now = datetime.now(timezone.utc)
    for name in ROLES[role]:
        beat_at = beats.get(name)
        if beat_at is None:
            return 1
        if beat_at.tzinfo is None:
            beat_at = beat_at.replace(tzinfo=timezone.utc)
        if now - beat_at >= HEARTBEAT_MAX_AGE:
            return 1
    return 0


async def _main(role: str) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass
    try:
        await run(stop, role)
    finally:
        await engine.dispose()
        logger.info("Worker encerrado")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument("--role", choices=sorted(ROLES), default=os.environ.get("WORKER_ROLE", "all"))
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--run-job", dest="run_job")
    parser.add_argument("--run-id")
    parser.add_argument("--target")
    args = parser.parse_args(argv)
    if args.role not in ROLES:
        parser.error(f"WORKER_ROLE inválido: {args.role}")
    return args


if __name__ == "__main__":
    setup_logging(get_settings().LOG_LEVEL)
    args = _parse_args(sys.argv[1:])
    if args.healthcheck:
        sys.exit(asyncio.run(healthcheck(args.role)))
    if args.run_job:
        sys.exit(asyncio.run(run_job_in_child(args.run_job, uuid.UUID(args.run_id), args.target)))
    asyncio.run(_main(args.role))
