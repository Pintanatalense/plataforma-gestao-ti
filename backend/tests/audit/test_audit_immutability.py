"""Auditoria imutável no PostgreSQL (ADR-023; Plano de Evolução, Fase 0 PR 11; S4): gatilho, cadeia e retenção."""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.audit.chain import seal_pending, verify_chain
from app.audit.models import AuditChainState, AuditLog
from app.audit.repository import AuditRepository
from app.audit.retention import apply_audit_retention
from app.config import get_settings
from app.database import Base
from app.notifications.jobs import job_audit_verify
from app.notifications.models import DomainEvent

pytestmark = [pytest.mark.pg, pytest.mark.asyncio]


@pytest.fixture
async def maker():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _log(session, event: str, days_ago: int = 0, **data) -> AuditLog:
    log = AuditLog(event_type=event, entity_type="x", entity_id=uuid.uuid4(), data=data,
                   created_at=datetime.now(timezone.utc) - timedelta(days=days_ago))
    session.add(log)
    await session.flush()
    return log


async def _refused(maker, sql: str) -> str:
    async with maker() as session:
        with pytest.raises(DBAPIError) as exc:
            await session.execute(text(sql))
        await session.rollback()
    return str(exc.value)


async def test_table_is_insert_only_even_for_the_owner(maker):
    async with maker() as session:
        await _log(session, "ticket.created")
        await session.commit()
    assert "alteração recusada" in await _refused(maker, "UPDATE audit_logs SET data = '{}'")
    assert "exclusão só pela retenção" in await _refused(maker, "DELETE FROM audit_logs")
    assert "TRUNCATE recusado" in await _refused(maker, "TRUNCATE audit_logs")
    assert "selo da cadeia" in await _refused(
        maker,
        "INSERT INTO audit_logs (id, event_type, entity_type, entity_id, data, actor_kind, category, row_hash, "
        "created_at, updated_at) VALUES (gen_random_uuid(), 'x', 'x', gen_random_uuid(), '{}', 'system', "
        "'operational', 'forjado', now(), now())",
    )


async def test_seal_builds_one_chain_per_category_and_verify_finds_tampering(maker):
    async with maker() as session:
        for event in ("identity.login_success", "ticket.created", "identity.login_failed", "ticket.updated"):
            await _log(session, event, ip="203.0.113.1")
        await session.commit()
        assert await seal_pending(session) == 4
        assert await seal_pending(session) == 0
        rows = list((await session.execute(select(AuditLog).order_by(AuditLog.category, AuditLog.chain_pos))).scalars())
        by_category = {}
        for row in rows:
            by_category.setdefault(row.category, []).append(row)
        for chain in by_category.values():
            assert [r.chain_pos for r in chain] == [1, 2]
            assert chain[0].prev_hash == "0" * 64 and chain[1].prev_hash == chain[0].row_hash
        statuses = await verify_chain(session)
        assert [(s.category, s.checked, s.problem) for s in statuses] == [("operational", 2, None), ("security", 2, None)]

        # alguém com superusuário desliga o gatilho e muda um registro: a verificação aponta
        victim = by_category["security"][0].id
        await session.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER audit_logs_guard"))
        await session.execute(text("UPDATE audit_logs SET data = '{\"ip\": \"10.0.0.1\"}' WHERE id = :i"), {"i": victim})
        await session.execute(text("DELETE FROM audit_logs WHERE category = 'operational' AND chain_pos = 1"))
        await session.execute(text("ALTER TABLE audit_logs ENABLE TRIGGER audit_logs_guard"))
        await session.commit()
        problems = {s.category: s.problem for s in await verify_chain(session)}
        assert problems == {"operational": "posição 1 ausente (a seguinte é 2)", "security": "posição 1: conteúdo alterado"}


async def test_verify_job_records_and_alerts_when_the_chain_breaks(maker):
    async with maker() as session:
        await _log(session, "ticket.created")
        await session.commit()
        await seal_pending(session)
        await session.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER audit_logs_guard"))
        await session.execute(text("UPDATE audit_logs SET entity_type = 'y'"))
        await session.execute(text("ALTER TABLE audit_logs ENABLE TRIGGER audit_logs_guard"))
        await session.commit()

    await job_audit_verify(maker)
    async with maker() as session:
        failure = (await session.execute(select(AuditLog).where(AuditLog.event_type == "audit.integrity_failed"))).scalar_one()
        assert failure.category == "security" and failure.data["problems"][0]["category"] == "operational"
        event = (await session.execute(select(DomainEvent).where(DomainEvent.event_type == "audit.integrity_failed"))).scalar_one()
        assert event.priority == "critical"


async def test_retention_purges_only_the_expired_sealed_prefix(maker, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "BACKUP_STORAGE_PATH", str(tmp_path))
    async with maker() as session:
        await _log(session, "ticket.created", days_ago=900, n=1)
        await _log(session, "ticket.created", days_ago=800, n=2)
        await _log(session, "ticket.created", days_ago=10, n=3)
        await _log(session, "identity.login_success", days_ago=2000, n=4)
        await _log(session, "identity.login_success", days_ago=800, n=5)
        await session.commit()

        assert await apply_audit_retention(session) == {"security": 1, "operational": 2}
        left = sorted(r.data["n"] for r in (await session.execute(select(AuditLog))).scalars())
        assert left == [3, 5]
        state = {s.category: s for s in (await session.execute(select(AuditChainState))).scalars()}
        assert (state["operational"].anchor_pos, state["security"].anchor_pos) == (2, 1)
        assert all(s.problem is None for s in await verify_chain(session))  # a cadeia continua da âncora

        # a função do banco recusa o que a aplicação não pode pedir
        for sql, message in (
            ("SELECT audit_purge('security', 365, 2)", "exige pelo menos 1825 dias"),
            ("SELECT audit_purge('operational', 30, 3)", "só registros vencidos"),
            ("SELECT audit_purge('operational', 730, 1)", "fora da cadeia"),
        ):
            with pytest.raises(DBAPIError, match=message):
                await session.execute(text(sql))
            await session.rollback()


async def test_demo_cleanup_no_longer_deletes_any_trail(maker):
    from app.seed_demo import clean_database
    from app.seed_test import clean_test_database

    async with maker() as session:
        for clean in (clean_database, clean_test_database):
            repo = AuditRepository(session)
            await repo.create("identity.login_success", "user", uuid.uuid4(), {})
            await repo.create("ticket.created", "ticket", uuid.uuid4(), {})
            await session.commit()
            await clean(session)
            await session.commit()
        kinds = sorted(r.category for r in (await session.execute(select(AuditLog))).scalars())
        assert kinds == ["operational", "operational", "security", "security"]
