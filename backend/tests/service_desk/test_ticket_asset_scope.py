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


async def _scenario(db: AsyncSession):
    org = await make_org(db)
    other_sector = await make_sector(db, org.unit)
    cat = await make_ticket_category(db, org.sector)
    requester = await make_employee(db, org)
    ticket = Ticket(
        title="Notebook novo", description="d", requester_id=requester.id, origin_unit_id=org.unit.id,
        origin_sector_id=org.sector.id, responsible_sector_id=org.sector.id, category_id=cat.id,
    )
    db.add(ticket)
    await db.commit()
    asset = await make_asset(db, org, await make_asset_category(db))

    tech_emp = await make_employee(db, org)  # mesmo setor do chamado
    tech = await make_user(db, tech_emp)
    stranger_emp = await make_employee(db, org)
    stranger_emp.sector_id = other_sector.id  # outro setor
    await db.commit()
    stranger = await make_user(db, stranger_emp)
    return ticket, asset, tech, stranger


async def test_technician_of_another_sector_cannot_move_assets_through_foreign_ticket(
    client: AsyncClient, db_session: AsyncSession
):
    ticket, asset, tech, stranger = await _scenario(db_session)
    url = f"/api/v1/tickets/{ticket.id}/assets/{asset.id}/deliver"

    denied = await client.post(url, json={}, headers=headers_for(stranger, "service_desk.tickets.manage"))
    assert denied.status_code == 403

    allowed = await client.post(url, json={}, headers=headers_for(tech, "service_desk.tickets.manage"))
    assert allowed.status_code == 200


async def test_non_technician_cannot_run_asset_lifecycle(client: AsyncClient, db_session: AsyncSession):
    ticket, asset, tech, _ = await _scenario(db_session)
    r = await client.post(f"/api/v1/tickets/{ticket.id}/assets/{asset.id}/reserve", json={}, headers=headers_for(tech))
    assert r.status_code == 403


async def test_invalid_body_is_422_not_500(client: AsyncClient, db_session: AsyncSession):
    ticket, asset, tech, _ = await _scenario(db_session)
    r = await client.post(
        f"/api/v1/tickets/{ticket.id}/assets/{asset.id}/reserve",
        json={"employee_id": "nao-e-uuid"},
        headers=headers_for(tech, "service_desk.tickets.manage"),
    )
    assert r.status_code == 422
