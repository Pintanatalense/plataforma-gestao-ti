"""
Desmembramento de permissões amplas (Plano de Evolução, Fase 0 PR 6): quem tinha a ampla continua fazendo tudo.

Perfis semeados (instalação, demonstração e QA) com a permissão antiga têm também as novas; a migration faz o mesmo
com perfis e concessões já existentes (teste em PostgreSQL abaixo).
"""

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.identity.permission_catalog import BY_CODE

pytestmark = pytest.mark.asyncio

ROLE_SPLITS = {
    "assets.write": {"assets.categories.manage", "assets.movements.write", "assets.import"},
    "service_desk.tickets.manage": {"service_desk.categories.manage"},
}
GRANT_SPLITS = {"system.backup.manage": {"system.demo.manage", "system.data.reset"}}


async def test_split_permissions_are_in_the_catalog_with_the_same_criticality_as_the_original():
    for old, new in (*ROLE_SPLITS.items(), *GRANT_SPLITS.items()):
        for code in new:
            assert BY_CODE[code].critical == BY_CODE[old].critical, code


@pytest.mark.parametrize("module", ["app.seed_demo", "app.seed_test"])
async def test_seeded_roles_with_a_broad_permission_also_get_the_split_ones(db_session: AsyncSession, module: str):
    import importlib

    roles = await importlib.import_module(module).sync_roles_and_permissions(db_session)
    for role in roles.values():
        codes = {p.code for p in role.permissions}
        for old, new in ROLE_SPLITS.items():
            if old in codes:
                assert new <= codes, (role.name, new - codes)


@pytest.mark.migrations
async def test_migration_gives_split_permissions_only_to_who_already_had_the_broad_one():
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
    await loop.run_in_executor(None, command.upgrade, cfg, "v2f3a4b5c6d7e")

    ids = {k: uuid.uuid4() for k in ("p_write", "p_manage", "p_backup", "r_tech", "r_asset", "r_read", "u_backup", "u_plain")}
    async with engine.begin() as conn:
        for key, code, critical in (("p_write", "assets.write", False), ("p_manage", "service_desk.tickets.manage", False),
                                    ("p_backup", "system.backup.manage", True)):
            await conn.execute(text("INSERT INTO permissions (id, code, is_critical, created_at, updated_at) VALUES (:i, :c, :k, now(), now())"),
                               {"i": ids[key], "c": code, "k": critical})
        for key, name in (("r_tech", "Atende"), ("r_asset", "Patrimonio"), ("r_read", "Nada")):
            await conn.execute(text("INSERT INTO roles (id, name, created_at, updated_at) VALUES (:i, :n, now(), now())"), {"i": ids[key], "n": name})
        await conn.execute(text("INSERT INTO role_permissions VALUES (:r, :p)"), {"r": ids["r_tech"], "p": ids["p_manage"]})
        await conn.execute(text("INSERT INTO role_permissions VALUES (:r, :p)"), {"r": ids["r_asset"], "p": ids["p_write"]})
        for key in ("u_backup", "u_plain"):
            await conn.execute(
                text("INSERT INTO user_accounts (id, email, hashed_password, is_admin, is_active, must_change_password, is_demo, "
                     "token_version, failed_login_count, created_at, updated_at) "
                     "VALUES (:i, :e, 'x', false, true, false, false, 0, 0, now(), now())"),
                {"i": ids[key], "e": f"{key}@test.local"},
            )
        await conn.execute(
            text("INSERT INTO user_critical_grants (id, user_id, permission_id, granted_via, granted_at) VALUES (:i, :u, :p, 'api', now())"),
            {"i": uuid.uuid4(), "u": ids["u_backup"], "p": ids["p_backup"]},
        )

    await loop.run_in_executor(None, command.upgrade, cfg, "w3a4b5c6d7e8f")

    async with engine.connect() as conn:
        async def role_codes(role):
            rows = await conn.execute(text(
                "SELECT p.code FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE rp.role_id = :r"), {"r": role})
            return set(rows.scalars())

        assert await role_codes(ids["r_tech"]) == {"service_desk.tickets.manage", "service_desk.categories.manage"}
        assert await role_codes(ids["r_asset"]) == {"assets.write", "assets.categories.manage", "assets.movements.write", "assets.import"}
        assert await role_codes(ids["r_read"]) == set()
        grants = await conn.execute(text(
            "SELECT u.email, p.code FROM user_critical_grants g JOIN user_accounts u ON u.id = g.user_id "
            "JOIN permissions p ON p.id = g.permission_id"))
        assert set(grants.all()) == {
            ("u_backup@test.local", "system.backup.manage"),
            ("u_backup@test.local", "system.demo.manage"),
            ("u_backup@test.local", "system.data.reset"),
        }
        critical = await conn.execute(text("SELECT code FROM permissions WHERE is_critical AND code IN ('system.demo.manage', 'system.data.reset')"))
        assert len(critical.all()) == 2

    await loop.run_in_executor(None, command.downgrade, cfg, "v2f3a4b5c6d7e")
    async with engine.connect() as conn:
        left = await conn.execute(text("SELECT count(*) FROM permissions WHERE code IN ('assets.import', 'system.demo.manage')"))
        assert left.scalar() == 0
    await loop.run_in_executor(None, command.upgrade, cfg, "head")
    await engine.dispose()
