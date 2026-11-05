"""
Direcionamento por categoria (chamados vinculados, PR 1) — **mudança de comportamento**, testada à parte.

Antes qualquer pessoa escolhia um setor diferente do padrão da categoria. Agora isso exige
``service_desk.tickets.route_any_sector``, dada pela migration ``f7a8b9c0d1e2f`` a quem já tinha
``service_desk.tickets.manage`` (os atendentes não perdem nada).
"""

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    headers_for,
    make_employee,
    make_org,
    make_sector,
    make_ticket_category,
    make_user,
)

pytestmark = pytest.mark.asyncio

API = "/api/v1/tickets"
ROUTE = "service_desk.tickets.route_any_sector"
MANAGE = "service_desk.tickets.manage"


async def _world(db: AsyncSession):
    org = await make_org(db)
    other_sector = await make_sector(db, org.unit)
    opener = await make_user(db, await make_employee(db, org))
    cat = await make_ticket_category(db, org.sector)
    return org, other_sector, opener, cat


def _body(cat, **extra) -> dict:
    return {"title": "Pedido", "description": "d", "category_id": str(cat.id), **extra}


async def test_category_sector_is_used_when_none_or_the_same_is_chosen(client: AsyncClient, db_session: AsyncSession):
    org, _, opener, cat = await _world(db_session)
    resp = await client.post(API, json=_body(cat), headers=headers_for(opener))
    assert resp.status_code == 201
    assert resp.json()["responsible_sector_id"] == str(org.sector.id)
    same = await client.post(API, json=_body(cat, responsible_sector_id=str(org.sector.id)), headers=headers_for(opener))
    assert same.status_code == 201


@pytest.mark.parametrize(
    "perms,expected",
    [((), 403), ((MANAGE,), 403), ((ROUTE,), 201), ((MANAGE, ROUTE), 201)],
)
async def test_other_sector_than_category_requires_route_permission(
    client: AsyncClient, db_session: AsyncSession, perms, expected
):
    _, other_sector, opener, cat = await _world(db_session)
    resp = await client.post(
        API, json=_body(cat, responsible_sector_id=str(other_sector.id)), headers=headers_for(opener, *perms)
    )
    assert resp.status_code == expected, resp.text
    if expected == 201:
        assert resp.json()["responsible_sector_id"] == str(other_sector.id)


async def test_category_without_default_sector_requires_an_active_sector(
    client: AsyncClient, db_session: AsyncSession
):
    _, other_sector, opener, _ = await _world(db_session)
    free_cat = await make_ticket_category(db_session, None)
    h = headers_for(opener)
    assert (await client.post(API, json=_body(free_cat), headers=h)).status_code == 400
    ok = await client.post(API, json=_body(free_cat, responsible_sector_id=str(other_sector.id)), headers=h)
    assert ok.status_code == 201, ok.text
    other_sector.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()
    gone = await client.post(API, json=_body(free_cat, responsible_sector_id=str(other_sector.id)), headers=h)
    assert gone.status_code == 400


async def test_admin_keeps_routing_to_any_sector(client: AsyncClient, db_session: AsyncSession):
    org, other_sector, _, cat = await _world(db_session)
    admin = await make_user(db_session, await make_employee(db_session, org), is_admin=True)
    resp = await client.post(API, json=_body(cat, responsible_sector_id=str(other_sector.id)), headers=headers_for(admin))
    assert resp.status_code == 201, resp.text


@pytest.mark.parametrize("module", ["app.seed_demo", "app.seed_test"])
async def test_seeded_attendant_roles_get_route_permission(db_session: AsyncSession, module: str):
    """Perfis semeados com ``tickets.manage`` (demonstração e QA) já nascem com a troca de setor."""
    import importlib

    roles = await importlib.import_module(module).sync_roles_and_permissions(db_session)
    for role in roles.values():
        codes = {p.code for p in role.permissions}
        if MANAGE in codes:
            assert ROUTE in codes, role.name


async def test_install_seed_attendant_role_lists_route_permission():
    import inspect

    from app import seed

    assert f'"{ROUTE}"' in inspect.getsource(seed)


@pytest.mark.migrations
async def test_migration_grants_route_only_to_who_attends_tickets():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

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
    await loop.run_in_executor(None, command.upgrade, cfg, "e5f6a7b8c9d0e")

    ids = {k: uuid.uuid4() for k in ("p_manage", "r_tech", "r_plain")}
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO permissions (id, code, is_critical, created_at, updated_at) "
                                "VALUES (:i, :c, false, now(), now())"), {"i": ids["p_manage"], "c": MANAGE})
        for key, name in (("r_tech", "Atende"), ("r_plain", "Pede")):
            await conn.execute(text("INSERT INTO roles (id, name, created_at, updated_at) VALUES (:i, :n, now(), now())"),
                               {"i": ids[key], "n": name})
        await conn.execute(text("INSERT INTO role_permissions VALUES (:r, :p)"), {"r": ids["r_tech"], "p": ids["p_manage"]})

    await loop.run_in_executor(None, command.upgrade, cfg, "f7a8b9c0d1e2f")

    async def role_codes(conn, role):
        r = await conn.execute(text(
            "SELECT p.code FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE rp.role_id = :r"
        ), {"r": role})
        return set(r.scalars())

    async with engine.connect() as conn:
        assert await role_codes(conn, ids["r_tech"]) == {MANAGE, ROUTE}
        assert await role_codes(conn, ids["r_plain"]) == set()

    await loop.run_in_executor(None, command.downgrade, cfg, "e5f6a7b8c9d0e")
    async with engine.connect() as conn:
        assert await role_codes(conn, ids["r_tech"]) == {MANAGE}
        left = await conn.execute(text("SELECT count(*) FROM permissions WHERE code = :c"), {"c": ROUTE})
        assert left.scalar() == 0
    await loop.run_in_executor(None, command.upgrade, cfg, "head")
    await engine.dispose()
