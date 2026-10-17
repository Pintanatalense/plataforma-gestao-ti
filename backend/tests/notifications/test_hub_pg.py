"""Hub de notificações contra PostgreSQL real (TEST_DATABASE_URL): SKIP LOCKED, NOTIFY e migration."""
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.identity.models import UserAccount
from app.notifications import channels as channels_module
from app.notifications.channels.base import Capabilities, ChannelHealth, DeliveryResult
from app.notifications.channels.in_app import INBOX_CHANNEL
from app.notifications.dispatcher import Dispatcher
from app.notifications.fanout import fan_out_batch
from app.notifications.models import Delivery, DomainEvent, Notification, NotificationRule
from app.notifications.outbox import OUTBOX_CHANNEL, emit_event

pytestmark = [pytest.mark.pg, pytest.mark.asyncio]


@pytest.fixture
async def maker():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _asyncpg_dsn() -> str:
    return os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")


class CountingAdapter:
    channel = "counting"
    capabilities = Capabilities()
    sent: list[str] = []

    def __init__(self, ctx):
        pass

    async def send(self, recipient, message):
        await asyncio.sleep(0.005)
        CountingAdapter.sent.append(recipient.address)
        return DeliveryResult("ok")

    async def health(self):
        return ChannelHealth(ok=True)


async def _seed_deliveries(maker, n: int) -> None:
    async with maker() as s:
        event = DomainEvent(event_type="t", entity_type="t", payload={}, fanned_out_at=datetime.now(timezone.utc))
        s.add(event)
        await s.flush()
        for i in range(n):
            s.add(
                Delivery(
                    event_id=event.id, channel="counting", address=f"d{i}", message={}, idempotency_key=f"{i:064d}"
                )
            )
        await s.commit()


async def test_two_dispatchers_never_send_the_same_delivery(maker):
    CountingAdapter.sent = []
    await _seed_deliveries(maker, 60)
    original = dict(channels_module.ADAPTERS)
    channels_module.ADAPTERS["counting"] = CountingAdapter
    try:
        a, b = Dispatcher(maker), Dispatcher(maker)

        async def drain(d: Dispatcher) -> None:
            while await d.run_once(limit=5):
                pass

        await asyncio.gather(drain(a), drain(b))
    finally:
        channels_module.ADAPTERS.clear()
        channels_module.ADAPTERS.update(original)

    assert len(CountingAdapter.sent) == 60 and len(set(CountingAdapter.sent)) == 60
    async with maker() as s:
        assert (await s.execute(select(func.count()).select_from(Delivery).where(Delivery.status == "SENT"))).scalar_one() == 60


async def test_two_fanouts_split_events_without_duplicating_deliveries(maker):
    async with maker() as s:
        user = UserAccount(email="u@x.y", hashed_password="x")
        s.add(user)
        await s.flush()
        s.add(
            NotificationRule(
                name="r", event_type="x.*", audience=[f"user:{user.id}"], channels=["in_app"], template_code="generic"
            )
        )
        await s.flush()
        for i in range(30):
            s.add(DomainEvent(event_type="x.happened", entity_type="x", payload={"title": f"e{i}"}))
        await s.commit()

    async def run_fanout() -> None:
        while True:
            async with maker() as s:
                n = await fan_out_batch(s, limit=4)
                await s.commit()
            if n == 0:
                return

    await asyncio.gather(run_fanout(), run_fanout())
    async with maker() as s:
        deliveries = (await s.execute(select(func.count()).select_from(Delivery))).scalar_one()
        pending = (await s.execute(select(func.count()).select_from(DomainEvent).where(DomainEvent.fanned_out_at.is_(None)))).scalar_one()
    assert (deliveries, pending) == (30, 0)


async def test_commit_notifies_worker_and_in_app_notifies_api(maker):
    import asyncpg

    outbox_events: list[str] = []
    inbox_events: list[str] = []
    conn = await asyncpg.connect(_asyncpg_dsn())
    await conn.add_listener(OUTBOX_CHANNEL, lambda *a: outbox_events.append(a[3]))
    await conn.add_listener(INBOX_CHANNEL, lambda *a: inbox_events.append(a[3]))
    try:
        async with maker() as s:
            user = UserAccount(email="n@x.y", hashed_password="x")
            s.add(user)
            await s.flush()
            user_id = user.id
            event = await emit_event(s, "x.happened", "x", None)
            await asyncio.sleep(0.2)
            assert outbox_events == []  # NOTIFY só é entregue no COMMIT
            await s.commit()
        await asyncio.sleep(0.3)
        assert outbox_events == [str(event.id)]

        from app.notifications.channels.base import AdapterContext, Message, Recipient
        from app.notifications.channels.in_app import InAppAdapter

        result = await InAppAdapter(AdapterContext(maker)).send(
            Recipient(address=str(user_id), user_id=str(user_id)), Message(title="t", body_text="b")
        )
        await asyncio.sleep(0.3)
        assert result.outcome == "ok"
        assert inbox_events == [f"{user_id}:{result.provider_message_id}"]
        async with maker() as s:
            assert (await s.execute(select(func.count()).select_from(Notification))).scalar_one() == 1
    finally:
        await conn.close()


@pytest.mark.migrations
async def test_migration_creates_hub_tables_and_encrypts_legacy_smtp_password():
    """Instalação anterior à Fase A: a senha SMTP em texto puro vira segredo cifrado em channel_configs."""
    from alembic import command
    from alembic.config import Config

    url = os.environ["TEST_DATABASE_URL"]
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    backend = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    os.environ["DATABASE_URL"] = url

    def upgrade(rev: str) -> None:
        command.upgrade(cfg, rev)

    await asyncio.to_thread(upgrade, "i9d0e1f2a3b4")
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO system_settings (key, value, metadata_json) VALUES ('smtp_config', 'SMTP', CAST(:j AS JSONB))"),
            {"j": '{"is_enabled": true, "host": "smtp.legacy", "password": "plain-pass", "port": 25}'},
        )
    await asyncio.to_thread(upgrade, "head")

    async with engine.connect() as conn:
        row = (await conn.execute(text("SELECT enabled, config, secrets_encrypted FROM channel_configs WHERE channel='email'"))).one()
        legacy = (await conn.execute(text("SELECT count(*) FROM system_settings WHERE key='smtp_config'"))).scalar_one()
        tables = {r[0] for r in (await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))).all()}
    await engine.dispose()

    assert {"domain_events", "deliveries", "delivery_attempts", "notification_rules", "channel_configs", "scheduled_jobs", "worker_heartbeat"} <= tables
    assert row.enabled is True and row.config["host"] == "smtp.legacy" and "password" not in row.config
    assert row.secrets_encrypted and "plain-pass" not in row.secrets_encrypted
    assert legacy == 0
    from app.core.crypto import decrypt_json

    assert decrypt_json(row.secrets_encrypted) == {"password": "plain-pass"}
