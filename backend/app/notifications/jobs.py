"""
Agenda do worker (ADR-013, D8): tabela `scheduled_jobs` + funções registradas.

Formatos de agenda: `every:<minutos>` e `daily:HH:MM` (fuso `APP_TIMEZONE`, padrão America/Fortaleza).
"""
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.notifications.channels.base import SessionFactory
from app.notifications.models import Delivery, DomainEvent, Notification, ScheduledJob
from app.notifications.outbox import emit_event

logger = logging.getLogger(__name__)

EVENT_RETENTION_DAYS = 90
READ_NOTIFICATION_RETENTION_DAYS = 180

DEFAULT_JOBS: dict[str, str] = {
    "backup.daily": "daily:02:00",
    "retention.cleanup": "daily:03:30",
}


def local_timezone():
    name = get_settings().APP_TIMEZONE
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        logger.warning("Fuso %s indisponível (instale tzdata); usando UTC-3 fixo.", name)
        return timezone(timedelta(hours=-3))


def compute_next_run(schedule: str, now: datetime) -> datetime:
    """Próxima execução estritamente depois de `now` (datetimes com fuso)."""
    kind, _, arg = schedule.partition(":")
    if kind == "every":
        return now + timedelta(minutes=max(int(arg), 1))
    if kind == "daily":
        hour, minute = (int(part) for part in arg.split(":"))
        local_now = now.astimezone(local_timezone())
        candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= local_now:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)
    raise ValueError(f"Agenda inválida: {schedule}")


async def ensure_default_jobs(session: AsyncSession) -> int:
    """Cria os jobs padrão ausentes (sem commit). Não altera agenda de jobs existentes."""
    existing = set((await session.execute(select(ScheduledJob.name))).scalars())
    now = datetime.now(timezone.utc)
    created = 0
    for name, schedule in DEFAULT_JOBS.items():
        if name not in existing:
            session.add(ScheduledJob(name=name, schedule=schedule, next_run_at=compute_next_run(schedule, now)))
            created += 1
    await session.flush()
    return created


# --- Jobs -----------------------------------------------------------------------------------------


async def job_backup(session_factory: SessionFactory) -> None:
    """Gera o backup agendado e avisa os administradores (falha = prioridade crítica)."""
    from app.backup.services import BackupService

    async with session_factory() as session:
        try:
            backup = await BackupService(session).create_backup(user_id=None)
        except Exception as exc:
            await emit_event(
                session,
                event_type="backup.failed",
                entity_type="backup",
                entity_id=None,
                payload={"error": str(exc)[:500]},
                priority="critical",
            )
            await session.commit()
            raise
        await emit_event(
            session,
            event_type="backup.completed",
            entity_type="backup",
            entity_id=backup.id,
            payload={"filename": backup.filename, "size_bytes": backup.size_bytes},
        )
        await session.commit()


async def job_retention_cleanup(session_factory: SessionFactory) -> None:
    """Apaga eventos/entregas antigos já tratados e notificações lidas antigas."""
    now = datetime.now(timezone.utc)
    events_cutoff = now - timedelta(days=EVENT_RETENTION_DAYS)
    notif_cutoff = now - timedelta(days=READ_NOTIFICATION_RETENTION_DAYS)
    async with session_factory() as session:
        old_events = select(DomainEvent.id).where(
            DomainEvent.created_at < events_cutoff, DomainEvent.fanned_out_at.is_not(None)
        )
        # Entregas ainda em andamento ficam; só o que já terminou sai junto com o evento.
        open_events = select(Delivery.event_id).where(Delivery.status.in_(("PENDING", "SENDING")))
        removable = old_events.where(DomainEvent.id.not_in(open_events))
        await session.execute(delete(Delivery).where(Delivery.event_id.in_(removable)))
        await session.execute(delete(DomainEvent).where(DomainEvent.id.in_(removable)))
        await session.execute(
            delete(Notification).where(Notification.is_read.is_(True), Notification.created_at < notif_cutoff)
        )
        await session.commit()


JOBS: dict[str, Callable[[SessionFactory], Awaitable[None]]] = {
    "backup.daily": job_backup,
    "retention.cleanup": job_retention_cleanup,
}


async def run_due_jobs(session_factory: SessionFactory) -> int:
    """Executa os jobs vencidos. A próxima execução é gravada antes de rodar (não repete se travar)."""
    now = datetime.now(timezone.utc)
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
        names = [job.name for job in due]
        await session.commit()

    for name in names:
        func = JOBS.get(name)
        status, error = "ok", None
        if func is None:
            status, error = "error", "Job sem função registrada."
        else:
            try:
                await func(session_factory)
            except Exception as exc:
                logger.exception("Job %s falhou", name)
                status, error = "error", str(exc)[:1000]
        async with session_factory() as session:
            job = (await session.execute(select(ScheduledJob).where(ScheduledJob.name == name))).scalar_one()
            job.last_run_at = datetime.now(timezone.utc)
            job.last_status = status
            job.last_error = error
            await session.commit()
    return len(names)
