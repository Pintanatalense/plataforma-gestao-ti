"""Auditoria (Plano de Evolução, Fase 0 PR 9; S4): ator, IP confiável, categoria, retenção e trilha preservada."""

import asyncio
import gzip
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.audit.categories import category_for
from app.audit.models import AuditLog
from app.audit.repository import AuditRepository
from app.audit.retention import apply_audit_retention
from app.config import Settings, get_settings
from app.database import get_db
from app.identity.models import UserAccount
from app.main import app
from tests.factories import make_user

pytestmark = pytest.mark.asyncio


async def test_categories():
    assert category_for("identity.login_failed") == "security"
    assert category_for("system.data.reset") == "security"
    assert category_for("notifications.email_configured") == "security"
    assert category_for("ticket.created") == "operational"
    assert category_for("notifications.delivery_resent") == "operational"


async def test_login_audit_records_actor_trusted_ip_category_and_request(db_session: AsyncSession):
    async def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    try:
        transport = ASGITransport(app=app, client=("203.0.113.9", 5555))
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.post(
                "/api/v1/identity/login",
                data={"username": "ninguem@test.com", "password": "x" * 10},
                headers={"X-Forwarded-For": "8.8.8.8", "X-Request-ID": "req-abcdef123"},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 401
    log = (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "identity.login_failed"))).scalar_one()
    assert (log.category, log.ip, log.request_id) == ("security", "203.0.113.9", "req-abcdef123")


async def test_ip_comes_from_the_request_even_when_the_event_does_not_carry_it(db_session: AsyncSession):
    """Eventos sem ``data.ip`` (chamados, ativos...) também ganham o IP confiável da requisição."""
    user = await make_user(db_session)

    @app.post("/__test_audit_ip", include_in_schema=False)
    async def _write():
        await AuditRepository(db_session).create("ticket.created", "ticket", uuid.uuid4(), {}, user.id)
        await db_session.commit()
        return {}

    try:
        transport = ASGITransport(app=app, client=("198.51.100.20", 1))
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            assert (await ac.post("/__test_audit_ip")).status_code == 200
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/__test_audit_ip"]
    log = (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "ticket.created"))).scalar_one()
    assert (log.category, log.ip, log.actor_kind, log.actor_email) == ("operational", "198.51.100.20", "human", user.email)


async def test_system_events_and_deleted_accounts_keep_their_trail(db_session: AsyncSession):
    user = await make_user(db_session)
    repo = AuditRepository(db_session)
    await repo.create("backup.failed", "backup", uuid.uuid4(), {}, None)
    await repo.create("identity.user_updated", "user", user.id, {}, user.id)
    await db_session.commit()

    await db_session.execute(delete(UserAccount).where(UserAccount.id == user.id))  # sem FK: a trilha fica
    await db_session.commit()
    db_session.expire_all()

    rows = {r.event_type: r for r in (await db_session.execute(select(AuditLog))).scalars()}
    assert rows["backup.failed"].actor_kind == "system" and rows["backup.failed"].category == "security"
    kept = rows["identity.user_updated"]
    assert kept.user_id == user.id and kept.user is None and kept.user_email == user.email


async def test_retention_archives_with_checksum_then_deletes_only_expired_rows(
    db_session: AsyncSession, monkeypatch, tmp_path: Path
):
    monkeypatch.setattr(get_settings(), "BACKUP_STORAGE_PATH", str(tmp_path))
    now = datetime.now(timezone.utc)

    def log(event: str, days_ago: int) -> AuditLog:
        return AuditLog(event_type=event, entity_type="x", entity_id=uuid.uuid4(), data={"n": days_ago},
                        created_at=now - timedelta(days=days_ago))

    db_session.add_all([
        log("ticket.created", 10), log("ticket.created", 800),           # operacional: 2 anos
        log("identity.login_success", 800), log("identity.login_success", 2000),  # segurança: 5 anos
    ])
    await db_session.commit()

    removed = await apply_audit_retention(db_session)
    assert removed == {"security": 1, "operational": 1}
    left = sorted((r.event_type, r.data["n"]) for r in (await db_session.execute(select(AuditLog))).scalars())
    assert left == [("identity.login_success", 800), ("ticket.created", 10)]

    archives = sorted((tmp_path / "audit-archive").glob("*.jsonl.gz"))
    assert len(archives) == 2
    for archive in archives:
        digest, name = archive.with_name(archive.name + ".sha256").read_text(encoding="utf-8").split()
        assert name == archive.name and digest == hashlib.sha256(archive.read_bytes()).hexdigest()
    rows = [json.loads(line) for a in archives for line in gzip.open(a, "rt", encoding="utf-8")]
    assert sorted(r["data"]["n"] for r in rows) == [800, 2000]


async def test_security_retention_cannot_go_below_five_years():
    with pytest.raises(ValidationError):
        Settings(SECRET_KEY="a" * 40, APP_ENCRYPTION_KEY=get_settings().APP_ENCRYPTION_KEY, AUDIT_RETENTION_SECURITY_DAYS=365)


async def test_demo_and_qa_cleanup_keep_the_whole_trail(db_session: AsyncSession):
    """Desde o PR 11 a auditoria só sai pela retenção (ADR-023): nem a trilha operacional é apagada."""
    from app.seed_demo import clean_database
    from app.seed_test import clean_test_database

    for clean in (clean_database, clean_test_database):
        repo = AuditRepository(db_session)
        await repo.create("identity.login_success", "user", uuid.uuid4(), {})
        await repo.create("ticket.created", "ticket", uuid.uuid4(), {})
        await db_session.commit()
        await clean(db_session)
        await db_session.commit()
        kinds = {r.category for r in (await db_session.execute(select(AuditLog))).scalars()}
        assert kinds == {"security", "operational"}


@pytest.mark.migrations
async def test_migration_backfills_the_new_columns_and_drops_the_user_fk():
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
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, command.upgrade, cfg, "w3a4b5c6d7e8f")

    uid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO user_accounts (id, email, hashed_password, is_admin, is_active, must_change_password, is_demo, "
                 "token_version, failed_login_count, created_at, updated_at) "
                 "VALUES (:i, 'ana@test.local', 'x', false, true, false, false, 0, 0, now(), now())"), {"i": uid})
        for event, user, data in (("identity.login_success", uid, '{"ip": "203.0.113.1"}'), ("ticket.created", uid, "{}"),
                                  ("backup.failed", None, "{}")):
            await conn.execute(
                text("INSERT INTO audit_logs (id, event_type, entity_type, entity_id, data, user_id, created_at, updated_at) "
                     "VALUES (:i, :e, 'x', :i, CAST(:d AS jsonb), :u, now(), now())"),
                {"i": uuid.uuid4(), "e": event, "d": data, "u": user},
            )

    await loop.run_in_executor(None, command.upgrade, cfg, "x4b5c6d7e8f9a")
    async with engine.begin() as conn:
        rows = {r.event_type: r for r in (await conn.execute(text("SELECT * FROM audit_logs"))).all()}
        assert (rows["identity.login_success"].category, rows["identity.login_success"].ip) == ("security", "203.0.113.1")
        assert (rows["ticket.created"].category, rows["ticket.created"].actor_kind, rows["ticket.created"].actor_email) == (
            "operational", "human", "ana@test.local")
        assert rows["backup.failed"].actor_kind == "system"
        await conn.execute(text("DELETE FROM user_accounts WHERE id = :i"), {"i": uid})  # sem FK: não falha
        assert (await conn.execute(text("SELECT count(*) FROM audit_logs WHERE user_id = :i"), {"i": uid})).scalar() == 2

    await loop.run_in_executor(None, command.downgrade, cfg, "w3a4b5c6d7e8f")
    async with engine.connect() as conn:
        orphan = (await conn.execute(text("SELECT count(*) FROM audit_logs WHERE user_id IS NOT NULL"))).scalar()
        assert orphan == 0
    await loop.run_in_executor(None, command.upgrade, cfg, "head")
    await engine.dispose()
