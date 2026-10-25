"""
Caracterização do acesso atual (Plano de Evolução, Fase 0 PR 4): quem vê e faz o quê nos chamados e ativos,
por perfil e setor. Congela o comportamento de HOJE para os PRs de permissões e de contexto de acesso único
(``AccessContext``) provarem que nada mudou sem querer. Mudança intencional atualiza a matriz no mesmo PR.

Cenário: chamado T aberto por um solicitante do setor A, com setor responsável A.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.service_desk.models import Ticket
from tests.factories import (
    headers_for,
    make_asset,
    make_asset_category,
    make_employee,
    make_org,
    make_sector,
    make_ticket_category,
    make_user,
)

pytestmark = pytest.mark.asyncio

API = "/api/v1/tickets"
MANAGE = "service_desk.tickets.manage"
READ_ALL = "service_desk.tickets.read_all"

# perfil: (permissões, setor do colaborador, é admin)
PROFILES = {
    "solicitante": ((), "A", False),
    "outro_solicitante": ((), "A", False),
    "atendente_setor_a": ((MANAGE,), "A", False),
    "atendente_setor_b": ((MANAGE,), "B", False),
    "atendente_b_atribuido": ((MANAGE,), "B", False),
    "gestao_read_all": ((READ_ALL,), "B", False),
    "notas_internas_sem_manage": (("service_desk.interactions.internal",), "B", False),
    "admin": ((), "B", True),
}

# perfil: (vê na lista, detalhe, histórico, comentário público, nota interna, PATCH prioridade)
EXPECTED = {
    "solicitante": (True, 200, 200, 201, 403, 403),
    "outro_solicitante": (False, 403, 403, 403, 403, 403),
    "atendente_setor_a": (True, 200, 200, 201, 201, 200),
    "atendente_setor_b": (False, 403, 403, 403, 403, 403),
    "atendente_b_atribuido": (True, 200, 200, 201, 201, 200),
    "gestao_read_all": (True, 200, 200, 201, 403, 403),
    "notas_internas_sem_manage": (False, 403, 403, 403, 403, 403),
    "admin": (True, 200, 200, 201, 201, 200),
}


async def _scenario(db: AsyncSession):
    org = await make_org(db)
    sector_b = await make_sector(db, org.unit)
    sectors = {"A": org.sector, "B": sector_b}
    users = {}
    for name, (perms, sector, is_admin) in PROFILES.items():
        emp = await make_employee(db, org)
        emp.sector_id = sectors[sector].id
        user = await make_user(db, emp, is_admin=is_admin)
        users[name] = (user, headers_for(user, *perms), emp)
    await db.commit()
    cat = await make_ticket_category(db, org.sector)
    return org, sectors, users, cat


async def _open(client: AsyncClient, headers, cat) -> str:
    resp = await client.post(API, json={"title": "T", "description": "d", "category_id": str(cat.id)}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.parametrize("profile", list(EXPECTED))
async def test_ticket_access_by_profile_and_sector(client: AsyncClient, db_session: AsyncSession, profile: str):
    _, _, users, cat = await _scenario(db_session)
    ticket_id = await _open(client, users["solicitante"][1], cat)
    ticket = await db_session.get(Ticket, uuid.UUID(ticket_id))
    ticket.assignee_id = users["atendente_b_atribuido"][0].id
    await db_session.commit()

    h = users[profile][1]
    in_list = any(t["id"] == ticket_id for t in (await client.get(API, headers=h)).json())
    detail = (await client.get(f"{API}/{ticket_id}", headers=h)).status_code
    history = (await client.get(f"{API}/{ticket_id}/history", headers=h)).status_code
    public = (await client.post(f"{API}/{ticket_id}/interactions", json={"message": "oi", "is_internal": False}, headers=h)).status_code
    internal = (await client.post(f"{API}/{ticket_id}/interactions", json={"message": "nota", "is_internal": True}, headers=h)).status_code
    patch = (await client.patch(f"{API}/{ticket_id}", json={"priority": "HIGH"}, headers=h)).status_code

    assert (in_list, detail, history, public, internal, patch) == EXPECTED[profile]


@pytest.mark.parametrize(
    "perms,is_admin,expected",
    [
        ((), False, 403),
        (("service_desk.reports.read",), False, 200),
        ((MANAGE,), False, 403),
        ((READ_ALL,), False, 403),
        ((), True, 200),
    ],
)
async def test_ticket_reports_require_reports_permission(
    client: AsyncClient, db_session: AsyncSession, perms, is_admin, expected
):
    org = await make_org(db_session)
    user = await make_user(db_session, await make_employee(db_session, org), is_admin=is_admin)
    resp = await client.get(f"{API}/reports/summary", headers=headers_for(user, *perms))
    assert resp.status_code == expected


@pytest.mark.parametrize(
    "perms,is_admin,expected",
    [((), False, 403), ((MANAGE,), False, 201), ((READ_ALL,), False, 403), ((), True, 201)],
)
async def test_ticket_category_write_requires_technician(
    client: AsyncClient, db_session: AsyncSession, perms, is_admin, expected
):
    org = await make_org(db_session)
    user = await make_user(db_session, await make_employee(db_session, org), is_admin=is_admin)
    resp = await client.post(
        f"{API}/categories",
        json={"name": "Nova", "default_sector_id": str(org.sector.id)},
        headers=headers_for(user, *perms),
    )
    assert resp.status_code == expected


# --- Ativos ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "perms,owner,expected_detail,expected_statement,expected_tickets",
    [
        (("assets.read",), False, 200, 200, 200),
        (("assets.read_own",), True, 200, 200, 200),
        (("assets.read_own",), False, 403, 403, 403),
        ((), True, 403, 403, 403),
        # Hoje: tickets.read lista os chamados do ativo sem filtro de setor (revisar no AccessContext, S1).
        (("service_desk.tickets.read",), False, 403, 403, 200),
    ],
)
async def test_asset_detail_statement_and_tickets_by_permission_and_ownership(
    client: AsyncClient, db_session: AsyncSession, perms, owner, expected_detail, expected_statement, expected_tickets
):
    org = await make_org(db_session)
    emp = await make_employee(db_session, org)
    other = await make_employee(db_session, org)
    user = await make_user(db_session, emp)
    asset = await make_asset(
        db_session, org, await make_asset_category(db_session), status="IN_USE", employee=emp if owner else other
    )
    h = headers_for(user, *perms)

    assert (await client.get(f"/api/v1/assets/{asset.id}", headers=h)).status_code == expected_detail
    assert (await client.get(f"/api/v1/assets/{asset.id}/responsibility-statement", headers=h)).status_code == expected_statement
    assert (await client.get(f"/api/v1/assets/{asset.id}/tickets", headers=h)).status_code == expected_tickets


async def test_asset_list_requires_assets_read_even_for_owner(client: AsyncClient, db_session: AsyncSession):
    org = await make_org(db_session)
    emp = await make_employee(db_session, org)
    user = await make_user(db_session, emp)
    await make_asset(db_session, org, await make_asset_category(db_session), status="IN_USE", employee=emp)

    assert (await client.get("/api/v1/assets", headers=headers_for(user, "assets.read_own"))).status_code == 403
    mine = await client.get("/api/v1/assets/me", headers=headers_for(user))
    assert mine.status_code == 200 and len(mine.json()) == 1
