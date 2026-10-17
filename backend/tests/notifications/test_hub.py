"""Hub de notificações (ADR-013, Fase A): outbox -> fan-out -> despacho -> canais, agenda e segredos."""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.identity.models import Permission, Role, role_permission_association, user_role_association
from app.notifications import channels as channels_module
from app.notifications.channels.base import Capabilities, ChannelHealth, DeliveryResult
from app.notifications.dispatcher import BACKOFF_SECONDS, CIRCUIT_FAILURES, Dispatcher, backoff_delay
from app.notifications.email_service import EmailService, SmtpConfigSchema
from app.notifications.fanout import fan_out_batch
from app.notifications.jobs import (
    compute_next_run,
    ensure_default_jobs,
    job_backup,
    job_retention_cleanup,
    run_due_jobs,
)
from app.notifications.models import (
    ChannelConfig,
    Delivery,
    DeliveryAttempt,
    DomainEvent,
    Notification,
    NotificationRule,
    ScheduledJob,
)
from app.notifications.outbox import emit_event
from app.notifications.rules_seed import DEFAULT_RULES, seed_notification_rules
from tests.factories import (
    headers_for,
    make_employee,
    make_org,
    make_ticket_category,
    make_user,
)

pytestmark = pytest.mark.asyncio

# O pytest carrega o conftest sob outro nome de módulo; importar `tests.conftest` criaria um segundo engine
# (outro SQLite em memória). A fábrica é derivada do engine da sessão de teste.
TestSessionLocal: async_sessionmaker = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _bind_session_factory(db_session: AsyncSession) -> None:
    global TestSessionLocal
    TestSessionLocal = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _no_quiet_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silêncio (20h-07h) dependeria da hora em que o teste roda; ele é testado em test_panel.py."""
    monkeypatch.setattr("app.notifications.fanout.quiet_until", lambda *args, **kwargs: None)


@dataclass
class World:
    requester: object
    attendant: object
    other_attendant: object
    admin: object
    sector_id: uuid.UUID
    category_id: uuid.UUID

    def h_requester(self):
        return headers_for(self.requester)

    def h_attendant(self):
        return headers_for(
            self.attendant, "service_desk.tickets.manage", "service_desk.interactions.internal"
        )


async def _grant(db: AsyncSession, user, role_name: str, permission_code: str | None) -> None:
    role = Role(name=role_name)
    db.add(role)
    await db.flush()
    if permission_code:
        perm = (await db.execute(select(Permission).where(Permission.code == permission_code))).scalar_one_or_none()
        if perm is None:
            perm = Permission(code=permission_code)
            db.add(perm)
            await db.flush()
        await db.execute(role_permission_association.insert().values(role_id=role.id, permission_id=perm.id))
    await db.execute(user_role_association.insert().values(user_id=user.id, role_id=role.id))
    await db.commit()


@pytest.fixture
async def world(db_session: AsyncSession) -> World:
    org = await make_org(db_session)
    category = await make_ticket_category(db_session, org.sector)
    requester = await make_user(db_session, await make_employee(db_session, org))
    attendant = await make_user(db_session, await make_employee(db_session, org))
    other_attendant = await make_user(db_session, await make_employee(db_session, org))
    admin = await make_user(db_session, is_admin=True)
    await _grant(db_session, attendant, "Atendente A", "service_desk.tickets.manage")
    await _grant(db_session, other_attendant, "Atendente B", "service_desk.tickets.manage")
    async with TestSessionLocal() as s:
        await seed_notification_rules(s)
        await s.commit()
    return World(requester, attendant, other_attendant, admin, org.sector.id, category.id)


async def _create_ticket(client: AsyncClient, world: World) -> str:
    resp = await client.post(
        "/api/v1/tickets",
        json={"title": "Sem rede", "description": "d", "priority": "HIGH", "category_id": str(world.category_id)},
        headers=world.h_requester(),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _process_all() -> None:
    """Um ciclo completo do worker, sem sleep."""
    async with TestSessionLocal() as s:
        await fan_out_batch(s)
        await s.commit()
    await Dispatcher(TestSessionLocal).run_once(limit=200)


async def _deliveries(**filters) -> list[Delivery]:
    async with TestSessionLocal() as s:
        stmt = select(Delivery)
        for key, value in filters.items():
            stmt = stmt.where(getattr(Delivery, key) == value)
        return list((await s.execute(stmt)).scalars())


async def _notifications_of(user) -> list[Notification]:
    async with TestSessionLocal() as s:
        return list((await s.execute(select(Notification).where(Notification.user_id == user.id))).scalars())


async def _enable_email(db: AsyncSession) -> None:
    await EmailService(db).update_config(
        SmtpConfigSchema(is_enabled=True, host="smtp.test", username="u", password="s3cret", app_base_url="http://sys")
    )


# --- Outbox ---------------------------------------------------------------------------------------


async def test_event_is_part_of_the_business_transaction(db_session: AsyncSession):
    await emit_event(db_session, "x.rolled_back", "x", None)
    await db_session.rollback()
    assert (await db_session.execute(select(func.count()).select_from(DomainEvent))).scalar_one() == 0

    await emit_event(db_session, "x.committed", "x", None, payload={"a": 1}, priority="high")
    await db_session.commit()
    event = (await db_session.execute(select(DomainEvent))).scalar_one()
    assert (event.event_type, event.priority, event.fanned_out_at) == ("x.committed", "high", None)


async def test_ticket_actions_write_events_to_outbox(client: AsyncClient, db_session: AsyncSession, world: World):
    ticket_id = await _create_ticket(client, world)
    await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"assignee_id": str(world.attendant.id), "status": "IN_PROGRESS"},
        headers=world.h_attendant(),
    )
    await client.post(
        f"/api/v1/tickets/{ticket_id}/interactions",
        json={"message": "Verificando", "is_internal": False},
        headers=world.h_attendant(),
    )
    types = {e.event_type for e in (await db_session.execute(select(DomainEvent))).scalars()}
    assert {"ticket.created", "ticket.assigned", "ticket.status_changed", "ticket.interaction_added"} <= types


# --- Audiência e regras ---------------------------------------------------------------------------


async def test_created_ticket_notifies_sector_attendants_and_confirms_to_requester(
    client: AsyncClient, world: World
):
    await _create_ticket(client, world)
    await _process_all()

    assert len(await _notifications_of(world.attendant)) == 1
    assert len(await _notifications_of(world.other_attendant)) == 1
    confirmation = await _notifications_of(world.requester)
    assert len(confirmation) == 1 and "registrado" in confirmation[0].title
    assert await _notifications_of(world.admin) == []


async def test_internal_note_never_reaches_requester_dec012(client: AsyncClient, world: World):
    ticket_id = await _create_ticket(client, world)
    await client.patch(
        f"/api/v1/tickets/{ticket_id}", json={"assignee_id": str(world.other_attendant.id)}, headers=world.h_attendant()
    )
    await _process_all()
    before = len(await _notifications_of(world.requester))

    resp = await client.post(
        f"/api/v1/tickets/{ticket_id}/interactions",
        json={"message": "Conta bloqueada no AD", "is_internal": True},
        headers=world.h_attendant(),
    )
    assert resp.status_code == 201
    await _process_all()

    assert len(await _notifications_of(world.requester)) == before
    assigned_notes = [n for n in await _notifications_of(world.other_attendant) if "atualização" in n.title]
    assert len(assigned_notes) == 1  # a nota interna vai só para o atendente designado


async def test_public_reply_goes_to_counterpart_only(client: AsyncClient, world: World):
    ticket_id = await _create_ticket(client, world)
    await client.patch(
        f"/api/v1/tickets/{ticket_id}", json={"assignee_id": str(world.attendant.id)}, headers=world.h_attendant()
    )
    await _process_all()
    requester_before = len(await _notifications_of(world.requester))
    attendant_before = len(await _notifications_of(world.attendant))

    await client.post(
        f"/api/v1/tickets/{ticket_id}/interactions",
        json={"message": "Pronto", "is_internal": False},
        headers=world.h_attendant(),
    )
    await _process_all()
    assert len(await _notifications_of(world.requester)) == requester_before + 1
    assert len(await _notifications_of(world.attendant)) == attendant_before  # autor não se autonotifica

    await client.post(
        f"/api/v1/tickets/{ticket_id}/interactions",
        json={"message": "Obrigado", "is_internal": False},
        headers=world.h_requester(),
    )
    await _process_all()
    assert len(await _notifications_of(world.attendant)) == attendant_before + 1


async def test_fan_out_is_idempotent(client: AsyncClient, world: World):
    await _create_ticket(client, world)
    await _process_all()
    total = len(await _deliveries())
    async with TestSessionLocal() as s:
        await s.execute(update(DomainEvent).values(fanned_out_at=None))
        await s.commit()
    await _process_all()
    assert len(await _deliveries()) == total


async def test_disabled_rule_and_disabled_channel_create_no_delivery(client: AsyncClient, world: World):
    # e-mail desabilitado por padrão: só in_app é criado
    await _create_ticket(client, world)
    async with TestSessionLocal() as s:
        await fan_out_batch(s)
        await s.commit()
    assert {d.channel for d in await _deliveries()} == {"in_app"}

    async with TestSessionLocal() as s:
        await s.execute(update(NotificationRule).values(enabled=False))
        await s.commit()
    before = len(await _deliveries())
    await _create_ticket(client, world)
    async with TestSessionLocal() as s:
        await fan_out_batch(s)
        await s.commit()
    assert len(await _deliveries()) == before


async def test_seed_rules_is_idempotent_and_keeps_admin_edits():
    async with TestSessionLocal() as s:
        assert await seed_notification_rules(s) == len(DEFAULT_RULES)
        await s.commit()
    async with TestSessionLocal() as s:
        await s.execute(update(NotificationRule).where(NotificationRule.code == "backup.failed").values(enabled=False))
        await s.commit()
    async with TestSessionLocal() as s:
        assert await seed_notification_rules(s) == 0
        await s.commit()
        rule = (await s.execute(select(NotificationRule).where(NotificationRule.code == "backup.failed"))).scalar_one()
        assert rule.enabled is False


# --- E-mail ---------------------------------------------------------------------------------------


async def test_email_delivery_sent_via_smtp(client: AsyncClient, db_session: AsyncSession, world: World):
    await _enable_email(db_session)
    await _create_ticket(client, world)
    with patch("app.notifications.channels.email.send_smtp_raw", return_value=("ok", "")) as smtp:
        await _process_all()

    sent_to = {call.args[1] for call in smtp.call_args_list}
    assert {world.attendant.email, world.other_attendant.email, world.requester.email} == sent_to
    emails = await _deliveries(channel="email")
    assert emails and all(d.status == "SENT" and d.attempts == 1 for d in emails)
    html = smtp.call_args_list[0].args[3]
    assert "http://sys/service-desk/" in html  # link absoluto montado com app_base_url


async def test_email_transient_failure_backs_off_then_succeeds(client: AsyncClient, db_session: AsyncSession, world: World):
    await _enable_email(db_session)
    await _create_ticket(client, world)
    with patch("app.notifications.channels.email.send_smtp_raw", return_value=("retryable", "timeout")):
        await _process_all()
    delivery = (await _deliveries(channel="email", recipient_user_id=world.requester.id))[0]
    assert (delivery.status, delivery.attempts, delivery.last_error) == ("PENDING", 1, "timeout")
    assert delivery.next_attempt_at > datetime.now(timezone.utc).replace(tzinfo=None) or delivery.next_attempt_at.tzinfo

    async with TestSessionLocal() as s:
        await s.execute(update(Delivery).values(next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        await s.commit()
    with patch("app.notifications.channels.email.send_smtp_raw", return_value=("ok", "")):
        await Dispatcher(TestSessionLocal).run_once(limit=200)
    delivery = (await _deliveries(channel="email", recipient_user_id=world.requester.id))[0]
    assert (delivery.status, delivery.attempts) == ("SENT", 2)


async def test_email_permanent_failure_goes_dead_with_attempt_log(
    client: AsyncClient, db_session: AsyncSession, world: World
):
    await _enable_email(db_session)
    await _create_ticket(client, world)
    with patch("app.notifications.channels.email.send_smtp_raw", return_value=("permanent", "550 no such user")):
        await _process_all()
    dead = await _deliveries(channel="email", status="DEAD")
    assert dead and all(d.attempts == 1 for d in dead)
    async with TestSessionLocal() as s:
        attempts = list((await s.execute(select(DeliveryAttempt))).scalars())
    assert any(a.outcome == "permanent" and "550" in (a.error or "") for a in attempts)


async def test_smtp_password_is_stored_encrypted_and_masked_by_api(client: AsyncClient, db_session: AsyncSession, world: World):
    admin_headers = headers_for(world.admin)
    body = SmtpConfigSchema(is_enabled=True, host="smtp.x", username="u", password="Super-Secret-1").model_dump()
    assert (await client.put("/api/v1/notifications/email/config", json=body, headers=admin_headers)).status_code == 200

    row = (await db_session.execute(select(ChannelConfig).where(ChannelConfig.channel == "email"))).scalar_one()
    assert "Super-Secret-1" not in (row.secrets_encrypted or "") and row.secrets_encrypted
    assert "password" not in row.config
    got = (await client.get("/api/v1/notifications/email/config", headers=admin_headers)).json()
    assert got["password"] == "********" and got["host"] == "smtp.x"
    assert (await EmailService(db_session).get_config()).password == "Super-Secret-1"

    # reenvio com senha mascarada preserva a senha
    body["password"] = "********"
    await client.put("/api/v1/notifications/email/config", json=body, headers=admin_headers)
    db_session.expire_all()
    assert (await EmailService(db_session).get_config()).password == "Super-Secret-1"


async def test_legacy_smtp_setting_is_read_then_replaced_on_save(db_session: AsyncSession):
    from app.core.settings_model import SystemSetting

    db_session.add(
        SystemSetting(key="smtp_config", value="SMTP", metadata_json={"is_enabled": True, "host": "old.host", "password": "old"})
    )
    await db_session.commit()
    service = EmailService(db_session)
    assert (await service.get_config()).host == "old.host"

    await service.update_config(await service.get_config())
    assert (await db_session.execute(select(func.count()).select_from(SystemSetting).where(SystemSetting.key == "smtp_config"))).scalar_one() == 0
    assert (await service.get_config()).password == "old"


# --- Despacho: retentativa, circuito, recuperação -------------------------------------------------


class FlakyAdapter:
    channel = "flaky"
    capabilities = Capabilities()
    outcome = "retryable"

    def __init__(self, ctx):
        pass

    async def send(self, recipient, message):
        return DeliveryResult(self.outcome, error="boom")

    async def health(self):
        return ChannelHealth(ok=False)


async def _flaky_delivery(db: AsyncSession, **overrides) -> Delivery:
    event = DomainEvent(event_type="t.e", entity_type="t", payload={}, fanned_out_at=datetime.now(timezone.utc))
    db.add(event)
    await db.flush()
    fields = {
        "event_id": event.id,
        "channel": "flaky",
        "address": "x",
        "message": {"title": "t", "body_text": "b"},
        "idempotency_key": uuid.uuid4().hex + uuid.uuid4().hex,
        **overrides,
    }
    delivery = Delivery(**fields)
    db.add(delivery)
    await db.commit()
    return delivery


async def test_retries_exhaust_to_dead_letter(db_session: AsyncSession):
    with patch.dict(channels_module.ADAPTERS, {"flaky": FlakyAdapter}):
        delivery = await _flaky_delivery(db_session, max_attempts=3)
        dispatcher = Dispatcher(TestSessionLocal)
        for _ in range(3):
            async with TestSessionLocal() as s:
                await s.execute(update(Delivery).values(next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
                await s.commit()
            assert await dispatcher.run_once() == 1
    final = (await _deliveries(id=delivery.id))[0]
    assert (final.status, final.attempts, final.last_error) == ("DEAD", 3, "boom")


async def test_circuit_opens_after_consecutive_failures_and_announces_once(db_session: AsyncSession):
    with patch.dict(channels_module.ADAPTERS, {"flaky": FlakyAdapter}):
        for _ in range(CIRCUIT_FAILURES + 2):
            await _flaky_delivery(db_session)
        dispatcher = Dispatcher(TestSessionLocal)
        for _ in range(CIRCUIT_FAILURES):
            await dispatcher.run_once(limit=1)
        # circuito aberto: nada mais é reivindicado, e a fila não consome tentativas
        assert await dispatcher.run_once() == 0
    async with TestSessionLocal() as s:
        events = list((await s.execute(select(DomainEvent).where(DomainEvent.event_type == "channel.degraded"))).scalars())
        waiting = list((await s.execute(select(Delivery).where(Delivery.attempts == 0))).scalars())
    assert len(events) == 1 and events[0].payload["channel"] == "flaky"
    assert len(waiting) == 2


async def test_stuck_sending_returns_to_pending(db_session: AsyncSession):
    delivery = await _flaky_delivery(
        db_session, status="SENDING", locked_at=datetime.now(timezone.utc) - timedelta(minutes=10)
    )
    fresh = await _flaky_delivery(db_session, status="SENDING", locked_at=datetime.now(timezone.utc))
    assert await Dispatcher(TestSessionLocal).recover_stuck() == 1
    assert (await _deliveries(id=delivery.id))[0].status == "PENDING"
    assert (await _deliveries(id=fresh.id))[0].status == "SENDING"


async def test_higher_priority_is_sent_first(db_session: AsyncSession):
    order: list[str] = []

    class Recording(FlakyAdapter):
        async def send(self, recipient, message):
            order.append(recipient.address)
            return DeliveryResult("ok")

    with patch.dict(channels_module.ADAPTERS, {"flaky": Recording}):
        await _flaky_delivery(db_session, address="low", priority="low")
        await _flaky_delivery(db_session, address="critical", priority="critical")
        await _flaky_delivery(db_session, address="normal", priority="normal")
        await Dispatcher(TestSessionLocal).run_once()
    assert order == ["critical", "normal", "low"]


async def test_backoff_grows_and_respects_retry_after():
    assert timedelta(seconds=BACKOFF_SECONDS[0] * 0.8) <= backoff_delay(1) <= timedelta(seconds=BACKOFF_SECONDS[0] * 1.2)
    assert backoff_delay(4) > backoff_delay(2)
    assert backoff_delay(99) <= timedelta(seconds=BACKOFF_SECONDS[-1] * 1.2)
    assert backoff_delay(1, retry_after=90) == timedelta(seconds=90)


# --- Agenda e jobs --------------------------------------------------------------------------------


async def test_compute_next_run_daily_uses_system_timezone():
    now = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)  # 09:00 em Fortaleza (UTC-3)
    assert compute_next_run("daily:02:00", now) == datetime(2026, 10, 17, 5, 0, tzinfo=timezone.utc)
    assert compute_next_run("daily:10:00", now) == datetime(2026, 10, 16, 13, 0, tzinfo=timezone.utc)
    assert compute_next_run("every:15", now) == now + timedelta(minutes=15)
    with pytest.raises(ValueError):
        compute_next_run("weekly:1", now)


async def test_default_jobs_created_once():
    async with TestSessionLocal() as s:
        assert await ensure_default_jobs(s) == 2
        await s.commit()
    async with TestSessionLocal() as s:
        assert await ensure_default_jobs(s) == 0


async def test_due_job_runs_once_and_records_status():
    calls: list[str] = []

    async def fake(_factory):
        calls.append("run")

    async def failing(_factory):
        raise RuntimeError("disk full")

    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    async with TestSessionLocal() as s:
        s.add(ScheduledJob(name="t.ok", schedule="every:60", next_run_at=past))
        s.add(ScheduledJob(name="t.bad", schedule="every:60", next_run_at=past))
        s.add(ScheduledJob(name="t.later", schedule="every:60", next_run_at=past + timedelta(hours=2)))
        await s.commit()
    with patch.dict("app.notifications.jobs.JOBS", {"t.ok": fake, "t.bad": failing, "t.later": fake}):
        assert await run_due_jobs(TestSessionLocal) == 2
        assert await run_due_jobs(TestSessionLocal) == 0  # próxima execução já foi gravada
    async with TestSessionLocal() as s:
        jobs = {j.name: j for j in (await s.execute(select(ScheduledJob))).scalars()}
    assert calls == ["run"]
    assert (jobs["t.ok"].last_status, jobs["t.bad"].last_status) == ("ok", "error")
    assert "disk full" in jobs["t.bad"].last_error and jobs["t.later"].last_status is None


async def test_backup_failure_raises_critical_event_for_admins(db_session: AsyncSession, world: World):
    async def broken(self, user_id=None):
        raise RuntimeError("pg_dump ausente")

    with patch("app.backup.services.BackupService.create_backup", broken):
        with pytest.raises(RuntimeError):
            await job_backup(TestSessionLocal)
    event = (await db_session.execute(select(DomainEvent).where(DomainEvent.event_type == "backup.failed"))).scalar_one()
    assert event.priority == "critical" and "pg_dump" in event.payload["error"]

    await _process_all()
    alert = await _notifications_of(world.admin)
    assert len(alert) == 1 and alert[0].type == "error" and "backup" in alert[0].title.lower()


async def test_backup_success_emits_completed_but_default_rule_stays_silent(db_session: AsyncSession, world: World):
    with patch("app.backup.services.BackupService.create_backup", side_effect=None) as create:
        create.return_value = type("B", (), {"id": uuid.uuid4(), "filename": "b.sql.gz", "size_bytes": 10})()
        await job_backup(TestSessionLocal)
    assert (await db_session.execute(select(DomainEvent).where(DomainEvent.event_type == "backup.completed"))).scalar_one()
    await _process_all()
    assert await _notifications_of(world.admin) == []


async def test_retention_removes_old_finished_data_and_keeps_open_deliveries(db_session: AsyncSession):
    old = datetime.now(timezone.utc) - timedelta(days=120)
    async with TestSessionLocal() as s:
        done = DomainEvent(event_type="a", entity_type="a", payload={}, created_at=old, fanned_out_at=old)
        busy = DomainEvent(event_type="b", entity_type="b", payload={}, created_at=old, fanned_out_at=old)
        recent = DomainEvent(event_type="c", entity_type="c", payload={})
        s.add_all([done, busy, recent])
        await s.flush()
        s.add(Delivery(event_id=done.id, channel="in_app", address="x", status="SENT", message={}, idempotency_key="k1" * 32))
        s.add(Delivery(event_id=busy.id, channel="in_app", address="x", status="PENDING", message={}, idempotency_key="k2" * 32))
        await s.commit()
    await job_retention_cleanup(TestSessionLocal)
    async with TestSessionLocal() as s:
        remaining = {e.event_type for e in (await s.execute(select(DomainEvent))).scalars()}
    assert remaining == {"b", "c"}


async def test_backup_db_url_keeps_password_for_pg_dump():
    """str(url) devolve '***' no lugar da senha; o worker precisa da senha real para o pg_dump."""
    from sqlalchemy.engine import make_url

    from app.backup.services import BackupService

    class FakeSession:
        def get_bind(self):
            return type("Bind", (), {"url": make_url("postgresql+asyncpg://u:s3nh4@db:5432/x")})()

    service = BackupService.__new__(BackupService)
    service.session = FakeSession()
    assert "s3nh4" in service._get_active_db_url()
