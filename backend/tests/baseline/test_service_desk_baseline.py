"""
Baseline — Service Desk (MOD-04).

Grupo A: comportamento atual que deve continuar verde.
Grupo B: defeito conhecido, travado com ``xfail(strict=True)``. Quando o defeito
for corrigido o teste passa a falhar (XPASS strict) e deve ser atualizado
conscientemente.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attachments.models import Attachment
from app.service_desk.models import TicketMaterial, ticket_assets
from tests.factories import (
    headers_for,
    make_asset,
    make_asset_category,
    make_employee,
    make_org,
    make_stock_item,
    make_ticket_category,
    make_user,
)

pytestmark = pytest.mark.asyncio

API = "/api/v1/tickets"


async def _env(db: AsyncSession):
    """Setor, solicitante, segundo solicitante e técnico (admin) com colaborador."""
    org = await make_org(db)
    emp_a = await make_employee(db, org)
    emp_b = await make_employee(db, org)
    emp_t = await make_employee(db, org)
    user_a = await make_user(db, emp_a)
    user_b = await make_user(db, emp_b)
    tech = await make_user(db, emp_t, is_admin=True)
    cat = await make_ticket_category(db, org.sector)
    return {
        "org": org,
        "user_a": user_a,
        "user_b": user_b,
        "tech": tech,
        "emp_a": emp_a,
        "cat": cat,
        "h_a": headers_for(user_a),
        "h_b": headers_for(user_b),
        "h_t": headers_for(tech),
    }


async def _open_ticket(client: AsyncClient, headers: dict, category_id, **extra) -> dict:
    payload = {"title": "Chamado", "description": "Descrição", "category_id": str(category_id), **extra}
    resp = await client.post(API, json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Grupo A — abertura
# ---------------------------------------------------------------------------


async def test_open_requires_employee_link(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    orphan = await make_user(db_session, None, is_admin=True)
    resp = await client.post(
        API,
        json={"title": "x", "description": "y", "category_id": str(env["cat"].id)},
        headers=headers_for(orphan),
    )
    assert resp.status_code == 403


async def test_open_requires_authentication(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    resp = await client.post(API, json={"title": "x", "description": "y", "category_id": str(env["cat"].id)})
    assert resp.status_code == 401


async def test_open_with_inactive_category_is_rejected(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    inactive = await make_ticket_category(db_session, env["org"].sector, active=False)
    resp = await client.post(
        API,
        json={"title": "x", "description": "y", "category_id": str(inactive.id)},
        headers=env["h_a"],
    )
    assert resp.status_code == 400


async def test_open_without_category_and_sector_is_rejected(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    resp = await client.post(API, json={"title": "x", "description": "y"}, headers=env["h_a"])
    assert resp.status_code == 400


async def test_open_without_category_with_explicit_sector(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    resp = await client.post(
        API,
        json={"title": "x", "description": "y", "responsible_sector_id": str(env["org"].sector.id)},
        headers=env["h_a"],
    )
    assert resp.status_code == 201
    assert resp.json()["responsible_sector_id"] == str(env["org"].sector.id)


async def test_open_routes_to_category_default_sector(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    ticket = await _open_ticket(client, env["h_a"], env["cat"].id)
    assert ticket["responsible_sector_id"] == str(env["org"].sector.id)
    assert ticket["origin_sector_id"] == str(env["org"].sector.id)
    assert ticket["status"] == "OPENED"
    assert ticket["requester_id"] == str(env["emp_a"].id)


async def test_open_links_assets(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    asset = await make_asset(db_session, env["org"], await make_asset_category(db_session))
    ticket = await _open_ticket(client, env["h_a"], env["cat"].id, asset_ids=[str(asset.id)])
    rows = (await db_session.execute(select(ticket_assets))).all()
    assert [(str(r.ticket_id), str(r.asset_id)) for r in rows] == [(ticket["id"], str(asset.id))]


# ---------------------------------------------------------------------------
# Grupo A — visibilidade
# ---------------------------------------------------------------------------


async def test_list_is_scoped_by_requester(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    ta = await _open_ticket(client, env["h_a"], env["cat"].id)
    tb = await _open_ticket(client, env["h_b"], env["cat"].id)

    ids_a = {t["id"] for t in (await client.get(API, headers=env["h_a"])).json()}
    ids_b = {t["id"] for t in (await client.get(API, headers=env["h_b"])).json()}
    ids_t = {t["id"] for t in (await client.get(API, headers=env["h_t"])).json()}

    assert ids_a == {ta["id"]}
    assert ids_b == {tb["id"]}
    assert ids_t == {ta["id"], tb["id"]}


async def test_other_requester_cannot_read_ticket(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    ta = await _open_ticket(client, env["h_a"], env["cat"].id)
    assert (await client.get(f"{API}/{ta['id']}", headers=env["h_b"])).status_code == 403
    assert (await client.get(f"{API}/{ta['id']}", headers=env["h_t"])).status_code == 200


async def test_internal_notes_hidden_from_requester_in_list_and_detail(
    client: AsyncClient, db_session: AsyncSession
):
    env = await _env(db_session)
    t = await _open_ticket(client, env["h_a"], env["cat"].id)
    for msg, internal in (("publica", False), ("interna", True)):
        r = await client.post(
            f"{API}/{t['id']}/interactions", json={"message": msg, "is_internal": internal}, headers=env["h_t"]
        )
        assert r.status_code == 201

    listed = (await client.get(API, headers=env["h_a"])).json()[0]["interactions"]
    detail = (await client.get(f"{API}/{t['id']}", headers=env["h_a"])).json()["interactions"]
    assert [i["message"] for i in listed] == ["publica"]
    assert [i["message"] for i in detail] == ["publica"]

    tech_view = (await client.get(f"{API}/{t['id']}", headers=env["h_t"])).json()["interactions"]
    assert {i["message"] for i in tech_view} == {"publica", "interna"}


# ---------------------------------------------------------------------------
# Grupo A — atualização e estados
# ---------------------------------------------------------------------------


async def test_patch_requires_technician(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    t = await _open_ticket(client, env["h_a"], env["cat"].id)
    resp = await client.patch(f"{API}/{t['id']}", json={"status": "IN_PROGRESS"}, headers=env["h_a"])
    assert resp.status_code == 403


async def test_permission_claim_makes_technician(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    t = await _open_ticket(client, env["h_a"], env["cat"].id)
    emp = await make_employee(db_session, env["org"])
    agent = await make_user(db_session, emp)  # não admin
    resp = await client.patch(
        f"{API}/{t['id']}",
        json={"status": "IN_PROGRESS", "assignee_id": str(agent.id)},
        headers=headers_for(agent, "service_desk.tickets.manage"),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "IN_PROGRESS"
    assert resp.json()["assignee_id"] == str(agent.id)


async def test_closed_ticket_cannot_be_reopened(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    t = await _open_ticket(client, env["h_a"], env["cat"].id)
    assert (await client.patch(f"{API}/{t['id']}", json={"status": "CLOSED"}, headers=env["h_t"])).status_code == 200
    resp = await client.patch(f"{API}/{t['id']}", json={"status": "OPENED"}, headers=env["h_t"])
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


async def test_invalid_status_is_rejected_by_schema(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    t = await _open_ticket(client, env["h_a"], env["cat"].id)
    resp = await client.patch(f"{API}/{t['id']}", json={"status": "BANANA"}, headers=env["h_t"])
    assert resp.status_code == 422


async def test_open_can_jump_straight_to_closed(client: AsyncClient, db_session: AsyncSession):
    """Hoje não há máquina de estados: OPENED -> CLOSED é aceito."""
    env = await _env(db_session)
    t = await _open_ticket(client, env["h_a"], env["cat"].id)
    resp = await client.patch(f"{API}/{t['id']}", json={"status": "CLOSED"}, headers=env["h_t"])
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Grupo A — interações
# ---------------------------------------------------------------------------


async def test_interaction_on_closed_ticket_is_rejected(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    t = await _open_ticket(client, env["h_a"], env["cat"].id)
    await client.patch(f"{API}/{t['id']}", json={"status": "CLOSED"}, headers=env["h_t"])
    resp = await client.post(f"{API}/{t['id']}/interactions", json={"message": "oi"}, headers=env["h_a"])
    assert resp.status_code == 400


async def test_requester_cannot_create_internal_note(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    t = await _open_ticket(client, env["h_a"], env["cat"].id)
    resp = await client.post(
        f"{API}/{t['id']}/interactions", json={"message": "x", "is_internal": True}, headers=env["h_a"]
    )
    assert resp.status_code == 403


async def test_other_requester_cannot_comment(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    t = await _open_ticket(client, env["h_a"], env["cat"].id)
    resp = await client.post(f"{API}/{t['id']}/interactions", json={"message": "x"}, headers=env["h_b"])
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Grupo A — materiais (consumo de estoque)
# ---------------------------------------------------------------------------


async def test_material_debits_stock(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    item = await make_stock_item(db_session, env["org"].unit, quantity=5)
    t = await _open_ticket(client, env["h_a"], env["cat"].id)
    resp = await client.post(
        f"{API}/{t['id']}/materials", json={"stock_item_id": str(item.id), "quantity": 2}, headers=env["h_t"]
    )
    assert resp.status_code == 201, resp.text
    await db_session.refresh(item)
    assert item.quantity == 3


async def test_material_with_insufficient_stock_leaves_no_trace(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    item = await make_stock_item(db_session, env["org"].unit, quantity=1)
    t = await _open_ticket(client, env["h_a"], env["cat"].id)
    resp = await client.post(
        f"{API}/{t['id']}/materials", json={"stock_item_id": str(item.id), "quantity": 9}, headers=env["h_t"]
    )
    assert resp.status_code == 400
    await db_session.refresh(item)
    assert item.quantity == 1
    assert (await db_session.execute(select(func.count()).select_from(TicketMaterial))).scalar_one() == 0


async def test_material_requires_technician(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    item = await make_stock_item(db_session, env["org"].unit)
    t = await _open_ticket(client, env["h_a"], env["cat"].id)
    resp = await client.post(
        f"{API}/{t['id']}/materials", json={"stock_item_id": str(item.id), "quantity": 1}, headers=env["h_a"]
    )
    assert resp.status_code == 403


async def test_material_on_closed_ticket_is_rejected(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    item = await make_stock_item(db_session, env["org"].unit)
    t = await _open_ticket(client, env["h_a"], env["cat"].id)
    await client.patch(f"{API}/{t['id']}", json={"status": "CLOSED"}, headers=env["h_t"])
    resp = await client.post(
        f"{API}/{t['id']}/materials", json={"stock_item_id": str(item.id), "quantity": 1}, headers=env["h_t"]
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Grupo A — categorias
# ---------------------------------------------------------------------------


async def test_category_write_requires_technician(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    assert (await client.post(f"{API}/categories", json={"name": "Nova"}, headers=env["h_a"])).status_code == 403
    created = await client.post(f"{API}/categories", json={"name": "Nova"}, headers=env["h_t"])
    assert created.status_code == 201
    cid = created.json()["id"]
    assert (await client.patch(f"{API}/categories/{cid}", json={"name": "X"}, headers=env["h_a"])).status_code == 403
    assert (await client.patch(f"{API}/categories/{cid}", json={"name": "X"}, headers=env["h_t"])).status_code == 200


async def test_inactive_category_is_hidden_from_list_but_old_tickets_survive(
    client: AsyncClient, db_session: AsyncSession
):
    env = await _env(db_session)
    t = await _open_ticket(client, env["h_a"], env["cat"].id)
    resp = await client.patch(f"{API}/categories/{env['cat'].id}", json={"is_active": False}, headers=env["h_t"])
    assert resp.status_code == 200

    names = {c["id"] for c in (await client.get(f"{API}/categories")).json()}
    assert str(env["cat"].id) not in names
    detail = await client.get(f"{API}/{t['id']}", headers=env["h_a"])
    assert detail.status_code == 200
    assert detail.json()["category_id"] == str(env["cat"].id)


@pytest.mark.legacy_behavior
async def test_category_default_sector_cannot_be_cleared(client: AsyncClient, db_session: AsyncSession):
    """Hoje enviar null em default_sector_id é ignorado (services.py: `is not None`)."""
    env = await _env(db_session)
    resp = await client.patch(
        f"{API}/categories/{env['cat'].id}", json={"default_sector_id": None}, headers=env["h_t"]
    )
    assert resp.status_code == 200
    assert resp.json()["default_sector_id"] == str(env["org"].sector.id)


# ---------------------------------------------------------------------------
# Grupo B — defeitos conhecidos (xfail strict)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="R1: GET /tickets/categories não exige autenticação")
async def test_categories_list_requires_authentication(client: AsyncClient, db_session: AsyncSession):
    await _env(db_session)
    resp = await client.get(f"{API}/categories")
    assert resp.status_code == 401


@pytest.mark.xfail(strict=True, reason="R1: anexos sem autorização por entidade")
async def test_attachments_of_foreign_ticket_are_forbidden(
    client: AsyncClient, db_session: AsyncSession, monkeypatch, tmp_path
):
    import app.attachments.service as attachment_service

    monkeypatch.setattr(attachment_service, "UPLOADS_DIR", str(tmp_path))
    env = await _env(db_session)
    t = await _open_ticket(client, env["h_a"], env["cat"].id)
    db_session.add(
        Attachment(
            filename="rg.pdf",
            content_type="application/pdf",
            size_bytes=1,
            file_path="ticket/x/y.pdf",
            entity_type="TICKET",
            entity_id=__import__("uuid").UUID(t["id"]),
        )
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/attachments", params={"entity_type": "TICKET", "entity_id": t["id"]}, headers=env["h_b"]
    )
    assert resp.status_code == 403
