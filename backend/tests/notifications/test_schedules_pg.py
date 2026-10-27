"""Agendamento de mensagens contra PostgreSQL real (ADR-025 M4): dois workers ao mesmo tempo, queda no meio da
ocorrência e a migration (permissão só para quem administrava notificações; volta remove só o que criou)."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.identity.models import UserAccount
from app.notifications import schedules as sched
from app.notifications.models import Delivery, MessageSchedule, OutboundMessage

pytestmark = [pytest.mark.pg, pytest.mark.asyncio]


@pytest.fixture
async def maker():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _due_schedule(maker) -> MessageSchedule:
    async with maker() as s:
        author = UserAccount(email="autor@test.local", hashed_password="x", is_admin=True)
        recipient = UserAccount(email="destino@test.local", hashed_password="x")
        s.add_all([author, recipient])
        await s.flush()
        schedule = MessageSchedule(
            name="Diário", channel="in_app", subject="Aviso", body="Oi {{nome}}", variables={}, priority="normal",
            recipient_ids=[str(recipient.id)], recurrence="daily", time_of_day="09:00", weekdays=[],
            timezone="America/Sao_Paulo", non_business_rule="skip", status="ACTIVE",
            next_run_at=datetime.now(timezone.utc) - timedelta(minutes=2), idempotency_key="k" * 64,
            created_by=author.id,
        )
        s.add(schedule)
        await s.commit()
        return schedule


async def _count(maker, model) -> int:
    async with maker() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


async def test_two_workers_at_once_send_the_occurrence_a_single_time(maker):
    await _due_schedule(maker)
    results = await asyncio.gather(*(sched.run_due_schedules(maker) for _ in range(4)))
    assert sum(r.sent for r in results) == 1
    assert await _count(maker, OutboundMessage) == 1 and await _count(maker, Delivery) == 1


async def test_crash_in_the_middle_leaves_nothing_half_done_and_the_next_run_sends(maker):
    schedule = await _due_schedule(maker)
    with patch("app.notifications.messages.enqueue", side_effect=RuntimeError("worker caiu")):
        with pytest.raises(RuntimeError):
            await sched.run_due_schedules(maker)
    assert await _count(maker, OutboundMessage) == 0
    async with maker() as s:
        still_due = await s.get(MessageSchedule, schedule.id)
        assert still_due.next_run_at <= datetime.now(timezone.utc) and still_due.runs_count == 0
    assert (await sched.run_due_schedules(maker)).sent == 1
    assert await _count(maker, OutboundMessage) == 1


@pytest.mark.migrations
async def test_migration_grants_schedule_permission_only_to_notification_admins_and_reverts():
    from alembic import command
    from alembic.config import Config

    before = "e2f3a4b5c6d7e"
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

    async def move(action, rev: str) -> None:
        await asyncio.to_thread(action, cfg, rev)

    await move(command.upgrade, before)
    async with engine.begin() as conn:
        for name in ("Operação", "Atendente"):
            await conn.execute(text("INSERT INTO roles (id, name, created_at, updated_at) VALUES (gen_random_uuid(), :n, now(), now())"), {"n": name})
        await conn.execute(text(
            "INSERT INTO role_permissions (role_id, permission_id) SELECT r.id, p.id FROM roles r, permissions p "
            "WHERE r.name = 'Operação' AND p.code = 'notifications.messages.send'"
        ))
        # o M3 concede send/read a quem tem notifications.manage; aqui o perfil "Operação" recebe manage direto
        await conn.execute(text(
            "INSERT INTO permissions (id, code, is_critical, created_at, updated_at) "
            "SELECT gen_random_uuid(), 'notifications.manage', false, now(), now() "
            "WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'notifications.manage')"
        ))
        await conn.execute(text(
            "INSERT INTO role_permissions (role_id, permission_id) SELECT r.id, p.id FROM roles r, permissions p "
            "WHERE r.name = 'Operação' AND p.code = 'notifications.manage'"
        ))
        await conn.execute(text(
            "INSERT INTO outbound_messages (id, kind, channel, subject, body, variables, priority, recipients, "
            "queued_count, skipped_count, status, idempotency_key, created_at, updated_at) VALUES (gen_random_uuid(), "
            "'manual', 'in_app', 'S', 'B', '{}'::jsonb, 'normal', '[]'::jsonb, 1, 0, 'QUEUED', 'k-antiga', now(), now())"
        ))

    async def grants() -> set[tuple[str, str]]:
        async with engine.connect() as conn:
            rows = await conn.execute(text(
                "SELECT r.name, p.code FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
                "JOIN permissions p ON p.id = rp.permission_id WHERE p.code = 'notifications.messages.schedule'"
            ))
            return {(name, code) for name, code in rows.all()}

    await move(command.upgrade, "head")
    assert await grants() == {("Operação", "notifications.messages.schedule")}
    async with engine.connect() as conn:
        old = (await conn.execute(text("SELECT schedule_id FROM outbound_messages WHERE idempotency_key = 'k-antiga'"))).scalar_one()
    assert old is None

    await move(command.downgrade, before)
    async with engine.connect() as conn:
        codes = set((await conn.execute(text("SELECT code FROM permissions"))).scalars())
        tables = {r[0] for r in (await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))).all()}
        kept = (await conn.execute(text("SELECT count(*) FROM outbound_messages"))).scalar_one()
    assert "notifications.messages.schedule" not in codes and "notifications.manage" in codes
    assert "message_schedules" not in tables and kept == 1
    await engine.dispose()
