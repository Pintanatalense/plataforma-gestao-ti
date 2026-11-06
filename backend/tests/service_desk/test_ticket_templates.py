"""
Modelos de atendimento (ADR-026, PR 4): listas de subchamados que a tela pré-preenche. O backend nunca cria nada a
partir do modelo; a abertura recebe a lista explícita e aplica as regras de sempre a cada item.
"""

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from tests.factories import headers_for, make_employee, make_org, make_sector, make_ticket_category, make_user

pytestmark = pytest.mark.asyncio

URL = "/api/v1/ticket-templates"
API = "/api/v1/tickets"
MANAGE = "service_desk.templates.manage"


async def _world(db: AsyncSession):
    org = await make_org(db)
    sector_b = await make_sector(db, org.unit)
    cat_p = await make_ticket_category(db, org.sector)
    cat_b = await make_ticket_category(db, sector_b)
    manager = await make_user(db, await make_employee(db, org))
    requester = await make_user(db, await make_employee(db, org))
    return org, sector_b, cat_p, cat_b, manager, requester


def _template(cat_b, name="Processo genérico", **item_extra) -> dict:
    return {
        "name": name,
        "description": "Etapas de outro setor",
        "items": [
            {"category_id": str(cat_b.id), "title": "Etapa 1", "description": "d", "is_required": True, **item_extra},
            {"category_id": str(cat_b.id), "title": "Etapa 2", "description": "d", "is_required": False,
             "default_custom_fields": {"campo": "valor"}},
        ],
    }


async def test_manage_templates_requires_permission_and_is_audited(client: AsyncClient, db_session: AsyncSession):
    _, _, _, cat_b, manager, requester = await _world(db_session)
    assert (await client.post(URL, json=_template(cat_b), headers=headers_for(requester))).status_code == 403

    h = headers_for(manager, MANAGE)
    created = await client.post(URL, json=_template(cat_b), headers=h)
    assert created.status_code == 201, created.text
    data = created.json()
    assert [i["title"] for i in data["items"]] == ["Etapa 1", "Etapa 2"]
    assert [i["sort"] for i in data["items"]] == [0, 1]
    assert data["items"][1]["default_custom_fields"] == {"campo": "valor"}

    # Mesmo nome: 409.
    assert (await client.post(URL, json=_template(cat_b), headers=h)).status_code == 409

    edited = _template(cat_b, name="Processo renomeado")
    edited["items"] = edited["items"][:1]
    updated = await client.put(f"{URL}/{data['id']}", json=edited, headers=h)
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Processo renomeado" and len(updated.json()["items"]) == 1

    assert (await client.delete(f"{URL}/{data['id']}", headers=h)).status_code == 204
    events = set((await db_session.execute(
        select(AuditLog.event_type).where(AuditLog.entity_id == uuid.UUID(data["id"]))
    )).scalars())
    assert events == {"ticket_template.created", "ticket_template.updated", "ticket_template.deactivated"}


async def test_everyone_lists_active_templates_only(client: AsyncClient, db_session: AsyncSession):
    _, _, _, cat_b, manager, requester = await _world(db_session)
    h = headers_for(manager, MANAGE)
    active = (await client.post(URL, json=_template(cat_b, name="Ativo"), headers=h)).json()
    gone = (await client.post(URL, json=_template(cat_b, name="Desativado"), headers=h)).json()
    await client.delete(f"{URL}/{gone['id']}", headers=h)

    hr = headers_for(requester)
    assert [t["id"] for t in (await client.get(URL, headers=hr)).json()] == [active["id"]]
    assert (await client.get(URL, params={"include_inactive": "true"}, headers=hr)).status_code == 403
    assert (await client.get(f"{URL}/{gone['id']}", headers=hr)).status_code == 404
    everything = (await client.get(URL, params={"include_inactive": "true"}, headers=h)).json()
    assert {t["id"] for t in everything} == {active["id"], gone["id"]}


async def test_items_must_use_active_category_and_sector(client: AsyncClient, db_session: AsyncSession):
    org, _, _, cat_b, manager, _ = await _world(db_session)
    h = headers_for(manager, MANAGE)
    inactive = await make_ticket_category(db_session, org.sector, active=False)
    assert (await client.post(URL, json=_template(inactive), headers=h)).status_code == 400
    bad_sector = _template(cat_b, responsible_sector_id=str(uuid.uuid4()))
    assert (await client.post(URL, json=bad_sector, headers=h)).status_code == 400
    assert (await client.post(URL, json={"name": "Vazio", "items": []}, headers=h)).status_code == 422


async def test_opening_records_template_and_applies_routing_to_each_item(
    client: AsyncClient, db_session: AsyncSession
):
    org, sector_b, cat_p, cat_b, manager, requester = await _world(db_session)
    other = await make_sector(db_session, org.unit)
    h = headers_for(manager, MANAGE)
    template = (await client.post(
        URL, json=_template(cat_b, responsible_sector_id=str(other.id)), headers=h
    )).json()

    # A tela copia os itens do modelo para `children`. O item com setor fora do padrão da categoria é recusado
    # para quem não tem route_any_sector, mesmo vindo do modelo.
    children = [
        {k: item[k] for k in ("category_id", "title", "description", "is_required", "responsible_sector_id")}
        for item in template["items"]
    ]
    body = {"title": "P", "description": "d", "category_id": str(cat_p.id), "template_id": template["id"],
            "children": children}
    hr = headers_for(requester)
    assert (await client.post(API, json=body, headers=hr)).status_code == 403

    children[0]["responsible_sector_id"] = None
    resp = await client.post(API, json=body, headers=hr)
    assert resp.status_code == 201, resp.text
    assert resp.json()["template_id"] == template["id"]
    overview = (await client.get(f"{API}/{resp.json()['id']}/children", headers=hr)).json()
    assert {c["responsible_sector_id"] for c in overview["children"]} == {str(sector_b.id)}


async def test_opening_with_inactive_template_is_refused(client: AsyncClient, db_session: AsyncSession):
    _, _, cat_p, cat_b, manager, requester = await _world(db_session)
    h = headers_for(manager, MANAGE)
    template = (await client.post(URL, json=_template(cat_b), headers=h)).json()
    await client.delete(f"{URL}/{template['id']}", headers=h)
    body = {"title": "P", "description": "d", "category_id": str(cat_p.id), "template_id": template["id"]}
    assert (await client.post(API, json=body, headers=headers_for(requester))).status_code == 400


@pytest.mark.pg
@pytest.mark.migrations
async def test_migration_grants_templates_to_category_managers_and_reverts():
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

    async def codes(conn, role) -> set[str]:
        rows = await conn.execute(text(
            "SELECT p.code FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE rp.role_id = :r"
        ), {"r": role})
        return set(rows.scalars())

    try:
        await loop.run_in_executor(None, command.upgrade, cfg, "c2d3e4f5a6b7c")
        ids = {k: uuid.uuid4() for k in ("perm", "manager", "plain")}
        async with engine.begin() as conn:
            # O catálogo de permissões já é semeado por migration anterior; cria só se ainda não existir.
            await conn.execute(text("INSERT INTO permissions (id, code, is_critical, created_at, updated_at) "
                                    "VALUES (:i, 'service_desk.categories.manage', false, now(), now()) "
                                    "ON CONFLICT (code) DO NOTHING"),
                               {"i": ids["perm"]})
            ids["perm"] = (await conn.execute(text(
                "SELECT id FROM permissions WHERE code = 'service_desk.categories.manage'"
            ))).scalar_one()
            for key, name in (("manager", "Gere"), ("plain", "Pede")):
                await conn.execute(text("INSERT INTO roles (id, name, created_at, updated_at) "
                                        "VALUES (:i, :n, now(), now())"), {"i": ids[key], "n": name})
            await conn.execute(text("INSERT INTO role_permissions VALUES (:r, :p)"),
                               {"r": ids["manager"], "p": ids["perm"]})

        await loop.run_in_executor(None, command.upgrade, cfg, "d3e4f5a6b7c8d")
        async with engine.connect() as conn:
            assert await codes(conn, ids["manager"]) == {"service_desk.categories.manage", MANAGE}
            assert await codes(conn, ids["plain"]) == set()
            assert (await conn.execute(text("SELECT to_regclass('public.sd_ticket_templates')"))).scalar()

        await loop.run_in_executor(None, command.downgrade, cfg, "c2d3e4f5a6b7c")
        async with engine.connect() as conn:
            assert await codes(conn, ids["manager"]) == {"service_desk.categories.manage"}
            assert (await conn.execute(text("SELECT to_regclass('public.sd_ticket_templates')"))).scalar() is None
    finally:
        await engine.dispose()
