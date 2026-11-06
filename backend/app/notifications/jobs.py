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
from app.notifications.automations import job_stock_low_check, job_warranty_check
from app.notifications.models import Delivery, DomainEvent, Notification, ScheduledJob
from app.notifications.outbox import emit_event

logger = logging.getLogger(__name__)

EVENT_RETENTION_DAYS = 90
READ_NOTIFICATION_RETENTION_DAYS = 180

DEFAULT_JOBS: dict[str, str] = {
    "backup.daily": "daily:02:00",
    "retention.cleanup": "daily:03:30",
    "stock.low_check": "every:30",
    "assets.warranty_check": "daily:08:00",
    "whatsapp.health_check": "every:5",
    "audit.retention": "daily:04:00",
    "audit.seal": "every:1",
    "audit.verify": "daily:04:30",
    "sla.check": "every:5",
    "messages.schedules": "every:1",
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


async def job_audit_retention(session_factory: SessionFactory) -> None:
    """Arquiva e apaga a auditoria vencida (segurança: 5 anos ou mais; operacional: 2 anos por padrão)."""
    from app.audit.retention import apply_audit_retention

    async with session_factory() as session:
        removed = await apply_audit_retention(session)
    if any(removed.values()):
        logger.info("Retenção da auditoria: %s", removed)


async def job_audit_seal(session_factory: SessionFactory) -> None:
    """Sela os registros novos na cadeia de hash da auditoria (ADR-023)."""
    from app.audit.chain import seal_pending

    async with session_factory() as session:
        await seal_pending(session)


async def job_audit_verify(session_factory: SessionFactory) -> None:
    """Recalcula a cadeia da auditoria; se quebrou, registra na própria auditoria e avisa os administradores.

    O fim de cada cadeia (posição e hash) vai para o log todos os dias: guardado fora do servidor, serve de âncora
    contra quem tivesse acesso de superusuário ao banco.
    """
    import uuid

    from app.audit.chain import seal_pending, verify_chain
    from app.audit.repository import AuditRepository

    async with session_factory() as session:
        await seal_pending(session)
        statuses = await verify_chain(session)
        broken = [s for s in statuses if s.problem]
        for status in statuses:
            logger.info("Cadeia da auditoria %s: %d verificados, fim %d (%s)%s", status.category, status.checked,
                        status.last_pos, status.last_hash, f" PROBLEMA: {status.problem}" if status.problem else "")
        if not broken:
            return
        problems = [{"category": s.category, "problem": s.problem} for s in broken]
        logger.error("Cadeia da auditoria quebrada: %s", problems)
        await AuditRepository(session).create(
            "audit.integrity_failed", "audit_chain", uuid.uuid5(uuid.NAMESPACE_URL, "gti:audit-chain"), {"problems": problems}
        )
        await emit_event(
            session, event_type="audit.integrity_failed", entity_type="audit_chain", entity_id=None,
            payload={"problems": problems}, priority="critical",
        )
        await session.commit()


async def job_sla_check(session_factory: SessionFactory) -> None:
    """Registra violações de SLA de quem ninguém tocou e avisa a equipe (proximidade e violação; ADR-017)."""
    from app.sla.checker import check_sla

    async with session_factory() as session:
        result = await check_sla(session)
        await session.commit()
    if result.breaches or result.warnings or result.breach_notices:
        logger.info("SLA: %d violações novas, %d alertas de proximidade, %d avisos de violação",
                    result.breaches, result.warnings, result.breach_notices)


async def job_message_schedules(session_factory: SessionFactory) -> None:
    """Envia as ocorrências vencidas dos agendamentos da Central de Mensagens (ADR-025 M4)."""
    from app.notifications.schedules import run_due_schedules

    result = await run_due_schedules(session_factory)
    if result.sent or result.failed or result.missed or result.paused:
        logger.info("Agendamentos: %d enviados, %d com falha, %d perdidos, %d pausados",
                    result.sent, result.failed, result.missed, result.paused)


async def job_whatsapp_health(session_factory: SessionFactory) -> None:
    """Vigia a saúde dos canais a cada 5 minutos. O nome continua o de quando só olhava o WhatsApp (a agenda e o
    histórico de execuções já o conhecem); desde o ADR-025 M2 cobre também os outros canais habilitados."""
    try:
        await _watch_whatsapp(session_factory)
    finally:
        await _watch_other_channels(session_factory)


# Canais vigiados pela checagem periódica (fora o WhatsApp, que tem a sua). A caixa de entrada é local e não cai.
WATCHED_CHANNELS = ("email", "telegram", "slack", "webpush")


async def _watch_other_channels(session_factory: SessionFactory) -> None:
    """Mesma regra do WhatsApp: duas checagens seguidas com falha geram UM `channel.degraded` por queda; voltar a
    funcionar rearma o aviso. Se o circuito do envio já abriu (e já avisou), não avisa de novo."""
    from app.notifications.channel_store import load_channel
    from app.notifications.channels import build_adapter
    from app.notifications.channels.base import AdapterContext
    from app.notifications.models import AutomationMark, WorkerHeartbeat

    heartbeat = None
    async with session_factory() as session:
        heartbeat = (await session.execute(select(WorkerHeartbeat).where(WorkerHeartbeat.name == "notifier"))).scalar_one_or_none()
    open_circuits = set(((heartbeat.info or {}) if heartbeat else {}).get("open_circuits", []))

    for channel in WATCHED_CHANNELS:
        seen_key, alerted_key = f"{channel}.down.seen", f"{channel}.down.alerted"
        async with session_factory() as session:
            stored = await load_channel(session, channel)
            marks = set((await session.execute(select(AutomationMark.key).where(AutomationMark.key.in_((seen_key, alerted_key))))).scalars())
            healthy, detail = True, ""
            if stored is not None and stored.enabled:
                try:
                    health = await build_adapter(channel, AdapterContext(session_factory=session_factory)).health()
                    healthy, detail = health.ok, health.detail
                except Exception as exc:  # um canal com erro não impede a checagem dos outros
                    healthy, detail = False, f"{type(exc).__name__}: {exc}"
            if healthy:
                if marks:
                    await session.execute(delete(AutomationMark).where(AutomationMark.key.in_((seen_key, alerted_key))))
            elif seen_key not in marks:
                session.add(AutomationMark(key=seen_key))
            elif alerted_key not in marks:
                if channel not in open_circuits:
                    await emit_event(
                        session, event_type="channel.degraded", entity_type="channel", entity_id=None,
                        payload={"channel": channel, "error": f"Checagem periódica falhou: {detail}"[:300]},
                        priority="high",
                    )
                session.add(AutomationMark(key=alerted_key))
            await session.commit()


async def _watch_whatsapp(session_factory: SessionFactory) -> None:
    """Avisa os administradores quando a sessão do WhatsApp (Evolution) cai, mesmo sem tráfego de mensagens.

    Reaproveita o evento `channel.degraded` (regra para administradores por caixa de entrada e e-mail, nunca pelo
    próprio WhatsApp). Debounce de uma checagem (5 min) e um único aviso por queda: as marcas somem ao reconectar.
    """
    from sqlalchemy import delete

    from app.notifications.channel_store import load_channel
    from app.notifications.channels import whatsapp_evolution as evolution
    from app.notifications.channels.whatsapp import PROVIDER_EVOLUTION, WHATSAPP_CHANNEL, provider_of
    from app.notifications.models import AutomationMark

    seen_key, alerted_key = "whatsapp.down.seen", "whatsapp.down.alerted"
    async with session_factory() as session:
        stored = await load_channel(session, WHATSAPP_CHANNEL)
        if stored is None or not stored.enabled or provider_of(stored) != PROVIDER_EVOLUTION:
            await session.execute(delete(AutomationMark).where(AutomationMark.key.in_((seen_key, alerted_key))))
            await session.commit()
            return
        instance = stored.config.get("instance_name") or evolution.DEFAULT_INSTANCE
        state, detail = await evolution.connection_state(instance)
        if state == "open" and not stored.config.get("display_phone"):
            # o número pareado alimenta o link wa.me do vínculo; a consulta de status da tela não grava
            from app.notifications.channel_store import save_channel

            phone = await evolution.owner_phone(instance)
            if phone:
                await save_channel(session, WHATSAPP_CHANNEL, stored.enabled, {**stored.config, "display_phone": phone},
                                   dict(stored.secrets))
        marks = set((await session.execute(select(AutomationMark.key).where(AutomationMark.key.in_((seen_key, alerted_key))))).scalars())
        if state == "open":
            if marks:
                await session.execute(delete(AutomationMark).where(AutomationMark.key.in_((seen_key, alerted_key))))
        elif seen_key not in marks:
            session.add(AutomationMark(key=seen_key))
        elif alerted_key not in marks:
            reason = detail or f"estado da sessão: {'sem instância' if state == 'missing' else state}"
            await emit_event(
                session, event_type="channel.degraded", entity_type="channel", entity_id=None,
                payload={"channel": WHATSAPP_CHANNEL, "error": f"WhatsApp desconectado ({reason}). Leia o QR code de novo em Canais de comunicação."},
                priority="high",
            )
            session.add(AutomationMark(key=alerted_key))
        await session.commit()


JOBS: dict[str, Callable[[SessionFactory], Awaitable[None]]] = {
    "backup.daily": job_backup,
    "retention.cleanup": job_retention_cleanup,
    "stock.low_check": job_stock_low_check,
    "assets.warranty_check": job_warranty_check,
    "whatsapp.health_check": job_whatsapp_health,
    "audit.retention": job_audit_retention,
    "audit.seal": job_audit_seal,
    "audit.verify": job_audit_verify,
    "sla.check": job_sla_check,
    "messages.schedules": job_message_schedules,
}


# Execução (concessão, subprocesso, tempo máximo, nova tentativa): app/notifications/job_runner.py
from app.notifications.job_runner import run_due_jobs  # noqa: E402, F401
