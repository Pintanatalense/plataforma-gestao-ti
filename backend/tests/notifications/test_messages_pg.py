"""Central de Mensagens contra PostgreSQL real: a migration concede as permissões novas só a quem já administrava
notificações, e a volta remove o que criou sem tocar no resto (ADR-025 M3)."""
import asyncio
import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = [pytest.mark.pg, pytest.mark.asyncio, pytest.mark.migrations]

BEFORE = "d1e2f3a4b5c6d"


async def test_migration_grants_message_permissions_only_to_notification_admins_and_reverts():
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

    async def move(action, rev: str) -> None:
        await asyncio.to_thread(action, cfg, rev)

    await move(command.upgrade, BEFORE)
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO permissions (id, code, is_critical, created_at, updated_at) "
            "VALUES (gen_random_uuid(), 'notifications.manage', false, now(), now())"
        ))
        for name in ("Operação", "Atendente"):
            await conn.execute(text("INSERT INTO roles (id, name, created_at, updated_at) VALUES (gen_random_uuid(), :n, now(), now())"), {"n": name})
        await conn.execute(text(
            "INSERT INTO role_permissions (role_id, permission_id) SELECT r.id, p.id FROM roles r, permissions p "
            "WHERE r.name = 'Operação' AND p.code = 'notifications.manage'"
        ))
        await conn.execute(text(
            "INSERT INTO domain_events (id, event_type, entity_type, payload, priority, created_at) "
            "VALUES (gen_random_uuid(), 'x.y', 'x', '{}'::jsonb, 'normal', now())"
        ))
        await conn.execute(text(
            "INSERT INTO deliveries (id, event_id, channel, address, status, priority, message, attempts, max_attempts, "
            "next_attempt_at, idempotency_key, created_at) SELECT gen_random_uuid(), id, 'email', 'a@b.c', 'SENT', 'normal', "
            "'{}'::jsonb, 1, 5, now(), 'k-antiga', now() FROM domain_events"
        ))

    async def grants() -> set[tuple[str, str]]:
        async with engine.connect() as conn:
            rows = await conn.execute(text(
                "SELECT r.name, p.code FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
                "JOIN permissions p ON p.id = rp.permission_id WHERE p.code LIKE 'notifications.messages.%'"
            ))
            return {(name, code) for name, code in rows.all()}

    await move(command.upgrade, "head")
    assert await grants() == {("Operação", "notifications.messages.send"), ("Operação", "notifications.messages.read")}
    async with engine.connect() as conn:
        old = (await conn.execute(text("SELECT message_id FROM deliveries WHERE idempotency_key = 'k-antiga'"))).scalar_one()
        tables = {r[0] for r in (await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))).all()}
    assert old is None and {"message_templates", "outbound_messages"} <= tables

    await move(command.upgrade, "head")  # rodar de novo não duplica nada
    assert len(await grants()) == 2

    await move(command.downgrade, BEFORE)
    async with engine.connect() as conn:
        codes = set((await conn.execute(text("SELECT code FROM permissions"))).scalars())
        tables = {r[0] for r in (await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))).all()}
        delivery = (await conn.execute(text("SELECT count(*) FROM deliveries"))).scalar_one()
    assert "notifications.manage" in codes and not {c for c in codes if c.startswith("notifications.messages.")}
    assert "outbound_messages" not in tables and "message_templates" not in tables and delivery == 1
    await engine.dispose()
