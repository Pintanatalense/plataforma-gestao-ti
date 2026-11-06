"""
Migration v2f3a4b5c6d7e (permissões críticas): o acesso de hoje é preservado em concessões individuais e a volta
devolve as críticas ao perfil Administrador. Só com PostgreSQL descartável (marcador ``migrations``).
"""

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = [pytest.mark.asyncio, pytest.mark.migrations]

BEFORE = "u1e2f3a4b5c6d"
TARGET = "v2f3a4b5c6d7e"


def _cfg(url: str) -> Config:
    backend = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    os.environ["DATABASE_URL"] = url
    return cfg


async def _alembic(fn, cfg, rev):
    await asyncio.get_running_loop().run_in_executor(None, fn, cfg, rev)


async def test_upgrade_preserves_current_access_and_downgrade_restores_the_admin_role():
    url = os.environ["TEST_DATABASE_URL"]
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    cfg = _cfg(url)
    await _alembic(command.upgrade, cfg, BEFORE)

    ids = {k: uuid.uuid4() for k in ("admin", "role_holder", "plain", "deleted_admin", "r_admin", "r_plain", "p_manage", "p_download", "p_import", "p_read")}
    async with engine.begin() as conn:
        for key, code in (("p_manage", "system.backup.manage"), ("p_download", "system.backup.download"),
                          ("p_import", "system.data.import"), ("p_read", "audit.read")):
            await conn.execute(text("INSERT INTO permissions (id, code, created_at, updated_at) VALUES (:i, :c, now(), now())"),
                               {"i": ids[key], "c": code})
        await conn.execute(text("INSERT INTO roles (id, name, created_at, updated_at) VALUES (:i, 'Administrador', now(), now()), (:j, 'Leitor', now(), now())"),
                           {"i": ids["r_admin"], "j": ids["r_plain"]})
        for perm in ("p_manage", "p_download", "p_import", "p_read"):
            await conn.execute(text("INSERT INTO role_permissions VALUES (:r, :p)"), {"r": ids["r_admin"], "p": ids[perm]})
        await conn.execute(text("INSERT INTO role_permissions VALUES (:r, :p)"), {"r": ids["r_plain"], "p": ids["p_read"]})
        for key, is_admin, deleted in (("admin", True, False), ("role_holder", False, False), ("plain", False, False), ("deleted_admin", True, True)):
            await conn.execute(
                text("INSERT INTO user_accounts (id, email, hashed_password, is_admin, is_active, must_change_password, is_demo, "
                     "token_version, failed_login_count, created_at, updated_at, deleted_at) "
                     "VALUES (:i, :e, 'x', :a, true, false, false, 0, 0, now(), now(), CASE WHEN :d THEN now() END)"),
                {"i": ids[key], "e": f"{key}@test.local", "a": is_admin, "d": deleted},
            )
        await conn.execute(text("INSERT INTO user_roles VALUES (:u, :r)"), {"u": ids["role_holder"], "r": ids["r_admin"]})
        await conn.execute(text("INSERT INTO user_roles VALUES (:u, :r)"), {"u": ids["plain"], "r": ids["r_plain"]})

    await _alembic(command.upgrade, cfg, TARGET)

    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT u.email, p.code, g.granted_via FROM user_critical_grants g "
            "JOIN user_accounts u ON u.id = g.user_id JOIN permissions p ON p.id = g.permission_id"))).all()
        grants = {(r.email, r.code) for r in rows}
        assert {r.granted_via for r in rows} == {"migration"}
        assert grants == {
            ("admin@test.local", "system.backup.manage"), ("admin@test.local", "system.backup.download"),
            ("admin@test.local", "system.data.import"), ("admin@test.local", "identity.critical.grant"),
            ("role_holder@test.local", "system.backup.manage"), ("role_holder@test.local", "system.backup.download"),
            ("role_holder@test.local", "system.data.import"),
        }
        role_codes = set((await conn.execute(text(
            "SELECT p.code FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id"))).scalars())
        assert role_codes == {"audit.read"}
        audits = (await conn.execute(text("SELECT count(*) FROM audit_logs WHERE event_type = 'identity.critical_granted'"))).scalar()
        assert audits == len(grants)

    await _alembic(command.downgrade, cfg, BEFORE)
    async with engine.connect() as conn:
        admin_codes = set((await conn.execute(text(
            "SELECT p.code FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE rp.role_id = :r"),
            {"r": ids["r_admin"]})).scalars())
        assert admin_codes == {"audit.read", "system.backup.manage", "system.backup.download", "system.data.import"}
        assert (await conn.execute(text("SELECT to_regclass('user_critical_grants')"))).scalar() is None
        assert (await conn.execute(text("SELECT count(*) FROM permissions WHERE code = 'identity.critical.grant'"))).scalar() == 0

    await _alembic(command.upgrade, cfg, "head")
    await engine.dispose()
