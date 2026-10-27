"""Migration do M5 (ADR-025) contra PostgreSQL real: regras e entregas existentes ficam sem escalonamento e sem canal
alternativo; a volta cancela escalonamentos pendentes (que sairiam sem conferir a condição) e remove só as colunas."""
import asyncio
import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = [pytest.mark.pg, pytest.mark.asyncio, pytest.mark.migrations]

BEFORE = "f3a4b5c6d7e8f"
TARGET = "a5b6c7d8e9f0a"


async def test_migration_keeps_existing_rules_unchanged_and_reverts_safely():
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
            "INSERT INTO notification_rules (id, name, enabled, event_type, condition, audience, channels, template_code, "
            "created_at, updated_at) VALUES (gen_random_uuid(), 'antiga', true, 'ticket.created', '{}'::jsonb, "
            "'[\"requester\"]'::jsonb, '[\"in_app\"]'::jsonb, 'generic', now(), now())"
        ))
        await conn.execute(text(
            "INSERT INTO domain_events (id, event_type, entity_type, payload, priority, created_at) "
            "VALUES (gen_random_uuid(), 'ticket.created', 'ticket', '{}'::jsonb, 'normal', now())"
        ))
        for key in ("k-normal", "k-escalonamento"):
            await conn.execute(text(
                "INSERT INTO deliveries (id, event_id, channel, address, status, priority, message, attempts, max_attempts, "
                "next_attempt_at, idempotency_key, created_at) SELECT gen_random_uuid(), id, 'in_app', 'x', 'PENDING', "
                "'normal', '{}'::jsonb, 0, 5, now(), :k, now() FROM domain_events"
            ), {"k": key})

    await move(command.upgrade, TARGET)
    async with engine.begin() as conn:
        rule = (await conn.execute(text("SELECT escalation, fallback_channel FROM notification_rules"))).one()
        assert rule.escalation == {} and rule.fallback_channel is None
        assert (await conn.execute(text("SELECT count(*) FROM deliveries WHERE escalation_condition IS NULL"))).scalar_one() == 2
        await conn.execute(text("UPDATE deliveries SET escalation_condition = 'first_response' WHERE idempotency_key = 'k-escalonamento'"))

    await move(command.downgrade, BEFORE)
    async with engine.connect() as conn:
        status = dict((await conn.execute(text("SELECT idempotency_key, status FROM deliveries"))).all())
        columns = set((await conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name IN ('deliveries', 'notification_rules')"
        ))).scalars())
    assert status == {"k-normal": "PENDING", "k-escalonamento": "CANCELLED"}
    assert not {"escalation", "fallback_channel", "escalation_condition", "fallback_of_id"} & columns
    await engine.dispose()
