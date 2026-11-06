"""
Execução dos jobs da agenda (Plano de Evolução, Fase 0 PR 12; ADR-024).

- **Uma execução por vez:** cada execução é uma linha ``running`` em ``job_runs`` (índice único parcial por job),
  com concessão (``lease_until``) renovada a cada 20 s enquanto roda.
- **Queda do worker:** concessão vencida vira ``interrupted`` e entra na nova tentativa.
- **Tempo máximo:** jobs leves rodam no próprio processo com ``asyncio.wait_for``; os pesados ou com trabalho
  bloqueante (``ISOLATED_JOBS``) rodam num **subprocesso** por execução, encerrado à força (com os filhos, ex.:
  ``pg_dump``) ao passar do tempo. Timeout do asyncio não interrompe código bloqueante; matar o processo, sim.
- **Nova tentativa:** falha, tempo esgotado ou interrupção agendam outra tentativa em 1, 2, 4... minutos (sem
  passar da próxima execução normal), até ``MAX_ATTEMPTS``; depois disso o job volta à agenda normal.

Os jobs gravam por upsert/condição (repetir uma execução não muda o resultado), então a nova tentativa é segura.
"""

import asyncio
import logging
import os
import signal
import socket
import sys
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.notifications.channels.base import SessionFactory
from app.notifications.models import AutomationMark, JobRun, ScheduledJob

logger = logging.getLogger(__name__)

LEASE = timedelta(seconds=60)
RENEW_SECONDS = 20
MAX_ATTEMPTS = 3
RETRY_BASE = timedelta(minutes=1)
KILL_GRACE_SECONDS = 5
DEFAULT_MAX_SECONDS = 300
JOB_MAX_SECONDS: dict[str, int] = {
    "backup.daily": 1800,
    "audit.retention": 1800,
    "audit.verify": 1800,
    "retention.cleanup": 900,
    "whatsapp.health_check": 120,  # WhatsApp + Telegram + Slack, cada um com tempo máximo de rede próprio
}
# Rodam em subprocesso próprio: chamam programas externos, podem demorar ou ter trecho bloqueante.
ISOLATED_JOBS = {"backup.daily", "audit.retention", "audit.verify", "retention.cleanup"}
# Já avisam a própria falha com evento específico (não duplicar com `job.failed`).
OWN_FAILURE_EVENT = {"backup.daily"}
_TARGET_PREFIXES = ("app.", "tests.")


def max_seconds(name: str) -> int:
    return JOB_MAX_SECONDS.get(name, DEFAULT_MAX_SECONDS)


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"[:120]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _schedule_retry(job: ScheduledJob, attempt: int, status: str, now: datetime) -> bool:
    """Agenda a nova tentativa. Retorna True quando esta foi a última tentativa e falhou."""
    if status == "ok":
        job.retry_attempt = 0
        return False
    if attempt < MAX_ATTEMPTS:
        job.retry_attempt = attempt
        retry_at = now + RETRY_BASE * (2 ** (attempt - 1))
        next_run = job.next_run_at if job.next_run_at.tzinfo else job.next_run_at.replace(tzinfo=timezone.utc)
        if retry_at < next_run:
            job.next_run_at = retry_at
        logger.warning("Job %s: %s na tentativa %d; nova tentativa até %s", job.name, status, attempt, job.next_run_at)
        return False
    job.retry_attempt = 0
    logger.error("Job %s: %s na tentativa %d (última); volta à agenda normal", job.name, status, attempt)
    return True


async def _announce_final_failure(session, job: ScheduledJob, status: str, error: str | None, attempt: int) -> None:
    """`job.failed` no outbox (ADR-025 M5), na mesma transação que registra o resultado. O backup tem aviso próprio."""
    if job.name in OWN_FAILURE_EVENT:
        return
    from app.notifications.outbox import emit_event

    mark = f"job.failed.{job.name}"
    if await session.get(AutomationMark, mark) is not None:  # já avisado; rearma quando o job voltar a dar certo
        return
    session.add(AutomationMark(key=mark))
    await emit_event(
        session, event_type="job.failed", entity_type="job", entity_id=None,
        payload={"job": job.name, "status": status, "error": (error or "")[:300], "attempts": attempt},
        priority="high",
    )


async def recover_interrupted(session_factory: SessionFactory) -> int:
    """Execuções ``running`` com concessão vencida (worker caiu ou travou) viram ``interrupted``."""
    now = _now()
    async with session_factory() as session:
        stale = list(
            (
                await session.execute(
                    select(JobRun)
                    .where(JobRun.status == "running", JobRun.lease_until < now)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        for run in stale:
            run.status = "interrupted"
            run.finished_at = now
            run.error = "Concessão vencida: o worker caiu ou travou durante a execução."
            job = await session.get(ScheduledJob, run.job_name)
            if job is not None:
                job.last_run_at, job.last_status, job.last_error = now, "interrupted", run.error
                if _schedule_retry(job, run.attempt, "interrupted", now):
                    await _announce_final_failure(session, job, "interrupted", run.error, run.attempt)
        await session.commit()
    for run in stale:
        logger.warning("Job %s: execução %s interrompida (concessão vencida)", run.job_name, run.id)
    return len(stale)


async def claim_due(session_factory: SessionFactory) -> list[tuple[str, uuid.UUID]]:
    """Reserva os jobs vencidos: grava a próxima execução e abre a linha ``running`` (uma por job)."""
    from app.notifications.jobs import compute_next_run

    now = _now()
    claimed: list[tuple[str, uuid.UUID]] = []
    async with session_factory() as session:
        due = list(
            (
                await session.execute(
                    select(ScheduledJob)
                    .where(ScheduledJob.enabled.is_(True), ScheduledJob.next_run_at <= now)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        for job in due:
            job.next_run_at = compute_next_run(job.schedule, now)
            running = (
                await session.execute(select(JobRun.id).where(JobRun.job_name == job.name, JobRun.status == "running"))
            ).first()
            if running is not None:
                logger.warning("Job %s ainda em execução: esta rodada foi pulada", job.name)
                continue
            run = JobRun(
                id=uuid.uuid4(), job_name=job.name, status="running", attempt=job.retry_attempt + 1,
                isolated=job.name in ISOLATED_JOBS, worker_id=worker_id(), started_at=now, lease_until=now + LEASE,
            )
            session.add(run)
            claimed.append((job.name, run.id))
        try:
            await session.commit()
        except IntegrityError:  # outro worker abriu a mesma execução no mesmo instante
            await session.rollback()
            logger.warning("Disputa ao reservar jobs; nada reservado nesta rodada")
            return []
    return claimed


async def _renew_lease(session_factory: SessionFactory, run_id: uuid.UUID) -> None:
    while True:
        await asyncio.sleep(RENEW_SECONDS)
        try:
            async with session_factory() as session:
                await session.execute(
                    update(JobRun)
                    .where(JobRun.id == run_id, JobRun.status == "running")
                    .values(lease_until=_now() + LEASE)
                )
                await session.commit()
        except Exception:
            logger.exception("Falha ao renovar a concessão da execução %s", run_id)


async def _run_in_process(func, session_factory: SessionFactory, limit: int) -> tuple[str, str | None]:
    try:
        await asyncio.wait_for(func(session_factory), timeout=limit)
    except asyncio.TimeoutError:
        return "timeout", f"Passou do tempo máximo ({limit} s) e foi cancelado."
    except Exception as exc:
        logger.exception("Job falhou")
        return "error", str(exc)[:1000] or exc.__class__.__name__
    return "ok", None


def _kill_tree(proc: asyncio.subprocess.Process, force: bool = False) -> None:
    try:
        if os.name == "posix":  # o grupo inteiro: o filho e o que ele chamou (pg_dump)
            os.killpg(proc.pid, signal.SIGKILL if force else signal.SIGTERM)
        elif force:
            proc.kill()
        else:
            proc.terminate()
    except ProcessLookupError:
        pass


async def _run_isolated(name: str, func, run_id: uuid.UUID, limit: int) -> tuple[str, str | None]:
    target = f"{func.__module__}:{func.__qualname__}"
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.worker", "--run-job", name, "--run-id", str(run_id), "--target", target,
        stdin=asyncio.subprocess.DEVNULL,
        **({"start_new_session": True} if os.name == "posix" else {}),
    )
    try:
        code = await asyncio.wait_for(proc.wait(), timeout=limit)
    except asyncio.TimeoutError:
        _kill_tree(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=KILL_GRACE_SECONDS)
        except asyncio.TimeoutError:
            _kill_tree(proc, force=True)
            await proc.wait()
        return "timeout", f"Passou do tempo máximo ({limit} s); o processo foi encerrado."
    except asyncio.CancelledError:  # worker parando: não deixa o filho órfão
        _kill_tree(proc)
        raise
    return ("ok", None) if code == 0 else ("error", None)


async def _finish(session_factory: SessionFactory, name: str, run_id: uuid.UUID, status: str, error: str | None) -> None:
    now = _now()
    async with session_factory() as session:
        run = await session.get(JobRun, run_id)
        if run is not None:
            if status == "error" and error is None:
                error = run.error or "O subprocesso terminou com erro (veja o log do worker)."
            started = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=timezone.utc)
            run.status, run.finished_at, run.error, run.lease_until = status, now, error, None
            run.duration_ms = int((now - started).total_seconds() * 1000)
        job = (await session.execute(select(ScheduledJob).where(ScheduledJob.name == name).with_for_update())).scalar_one_or_none()
        if job is not None:
            job.last_run_at, job.last_status, job.last_error = now, status, error
            attempt = run.attempt if run is not None else 1
            if _schedule_retry(job, attempt, status, now):
                await _announce_final_failure(session, job, status, error, attempt)
            elif status == "ok":
                await session.execute(delete(AutomationMark).where(AutomationMark.key == f"job.failed.{name}"))
        await session.commit()


async def run_claimed(session_factory: SessionFactory, name: str, run_id: uuid.UUID) -> str:
    from app.notifications.jobs import JOBS

    func = JOBS.get(name)
    renew = asyncio.create_task(_renew_lease(session_factory, run_id))
    try:
        if func is None:
            status, error = "error", "Job sem função registrada."
        elif name in ISOLATED_JOBS:
            status, error = await _run_isolated(name, func, run_id, max_seconds(name))
        else:
            status, error = await _run_in_process(func, session_factory, max_seconds(name))
    finally:
        renew.cancel()
    await _finish(session_factory, name, run_id, status, error)
    return status


async def run_due_jobs(session_factory: SessionFactory) -> int:
    """Recupera interrompidas, reserva as vencidas e executa todas (em paralelo). Retorna quantas rodaram."""
    await recover_interrupted(session_factory)
    claimed = await claim_due(session_factory)
    await asyncio.gather(*(run_claimed(session_factory, name, run_id) for name, run_id in claimed))
    return len(claimed)


async def run_job_in_child(name: str, run_id: uuid.UUID, target: str) -> int:
    """Lado do subprocesso (``python -m app.worker --run-job``): roda o job e grava o erro na execução."""
    import importlib

    from app.database import AsyncSessionLocal, engine

    module_name, _, attr = target.partition(":")
    if not module_name.startswith(_TARGET_PREFIXES) or not attr:
        print(f"Alvo de job recusado: {target}", file=sys.stderr)
        return 2
    func = importlib.import_module(module_name)
    for part in attr.split("."):
        func = getattr(func, part)
    try:
        await func(AsyncSessionLocal)
        return 0
    except Exception as exc:
        logger.exception("Job %s falhou (subprocesso)", name)
        async with AsyncSessionLocal() as session:
            await session.execute(update(JobRun).where(JobRun.id == run_id).values(error=(str(exc)[:1000] or exc.__class__.__name__)))
            await session.commit()
        return 1
    finally:
        await engine.dispose()
