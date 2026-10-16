import io
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attachments.models import Attachment
from app.config import get_settings
from app.service_desk.models import Ticket
from tests.factories import (
    headers_for,
    make_asset,
    make_asset_category,
    make_employee,
    make_org,
    make_ticket_category,
    make_user,
)

pytestmark = pytest.mark.asyncio

PDF = b"%PDF-1.4\n% conteudo de teste\n"
URL = "/api/v1/attachments"


async def _asset_and_admin(db: AsyncSession):
    org = await make_org(db)
    cat = await make_asset_category(db)
    asset = await make_asset(db, org, cat)
    admin = await make_user(db, is_admin=True)
    return org, asset, admin


def _pdf(name: str = "termo.pdf", body: bytes = PDF):
    return {"file": (name, io.BytesIO(body), "application/pdf")}


async def test_admin_upload_list_download_delete_asset_attachment(client: AsyncClient, db_session: AsyncSession):
    _, asset, admin = await _asset_and_admin(db_session)
    h = headers_for(admin)
    data = {"entity_type": "ASSET", "entity_id": str(asset.id)}

    up = await client.post(URL, files=_pdf(), data=data, headers=h)
    assert up.status_code == 201
    att = up.json()
    assert att["filename"] == "termo.pdf"

    lst = await client.get(URL, params=data, headers=h)
    assert [a["id"] for a in lst.json()] == [att["id"]]

    down = await client.get(f"{URL}/{att['id']}/download", headers=h)
    assert down.status_code == 200
    assert down.content == PDF
    assert down.headers["content-disposition"].startswith("attachment")
    assert down.headers["x-content-type-options"] == "nosniff"

    assert (await client.delete(f"{URL}/{att['id']}", headers=h)).status_code == 204
    assert (await client.get(URL, params=data, headers=h)).json() == []


async def test_stored_path_is_inside_configured_root_and_ignores_client_name(
    client: AsyncClient, db_session: AsyncSession
):
    _, asset, admin = await _asset_and_admin(db_session)
    up = await client.post(
        URL,
        files={"file": ("../../evil.pdf", io.BytesIO(PDF), "application/pdf")},
        data={"entity_type": "ASSET", "entity_id": str(asset.id)},
        headers=headers_for(admin),
    )
    assert up.status_code == 201
    assert up.json()["filename"] == "evil.pdf"

    row = (await db_session.execute(select(Attachment))).scalars().one()
    root = get_settings().attachment_storage_dir.resolve()
    full = (root / row.file_path).resolve()
    assert root in full.parents and full.exists()
    assert "." not in full.name


@pytest.mark.parametrize("bad", ["../../../tmp/pwn", "asset/../x", "TICKET_INTERACTION", "x"])
async def test_entity_type_is_a_closed_list(client: AsyncClient, db_session: AsyncSession, bad: str):
    _, asset, admin = await _asset_and_admin(db_session)
    r = await client.post(
        URL, files=_pdf(), data={"entity_type": bad, "entity_id": str(asset.id)}, headers=headers_for(admin)
    )
    assert r.status_code == 422


async def test_rejects_disallowed_type_and_mismatched_content(client: AsyncClient, db_session: AsyncSession):
    _, asset, admin = await _asset_and_admin(db_session)
    h = headers_for(admin)
    data = {"entity_type": "ASSET", "entity_id": str(asset.id)}

    html = {"file": ("a.html", io.BytesIO(b"<script>alert(1)</script>"), "text/html")}
    assert (await client.post(URL, files=html, data=data, headers=h)).status_code == 415

    disguised = {"file": ("a.pdf", io.BytesIO(b"<script>alert(1)</script>"), "application/pdf")}
    assert (await client.post(URL, files=disguised, data=data, headers=h)).status_code == 415


async def test_rejects_oversized_file(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    _, asset, admin = await _asset_and_admin(db_session)
    monkeypatch.setattr(get_settings(), "ATTACHMENT_MAX_SIZE_MB", 0)
    r = await client.post(
        URL, files=_pdf(), data={"entity_type": "ASSET", "entity_id": str(asset.id)}, headers=headers_for(admin)
    )
    assert r.status_code == 413


async def test_unknown_asset_is_404(client: AsyncClient, db_session: AsyncSession):
    admin = await make_user(db_session, is_admin=True)
    r = await client.post(
        URL, files=_pdf(), data={"entity_type": "ASSET", "entity_id": str(uuid.uuid4())}, headers=headers_for(admin)
    )
    assert r.status_code == 404


async def test_asset_attachments_require_asset_permissions(client: AsyncClient, db_session: AsyncSession):
    org, asset, admin = await _asset_and_admin(db_session)
    emp = await make_employee(db_session, org)
    plain = await make_user(db_session, emp)
    data = {"entity_type": "ASSET", "entity_id": str(asset.id)}

    up = await client.post(URL, files=_pdf(), data=data, headers=headers_for(admin))
    att_id = up.json()["id"]

    h = headers_for(plain, "service_desk.tickets.create")
    assert (await client.get(URL, params=data, headers=h)).status_code == 403
    assert (await client.post(URL, files=_pdf(), data=data, headers=h)).status_code == 403
    assert (await client.get(f"{URL}/{att_id}/download", headers=h)).status_code == 403
    assert (await client.delete(f"{URL}/{att_id}", headers=h)).status_code == 403

    reader = headers_for(plain, "assets.read")
    assert (await client.get(URL, params=data, headers=reader)).status_code == 200
    assert (await client.delete(f"{URL}/{att_id}", headers=reader)).status_code == 403

    writer = headers_for(plain, "assets.write")
    assert (await client.delete(f"{URL}/{att_id}", headers=writer)).status_code == 204


async def test_ticket_attachment_follows_ticket_visibility(client: AsyncClient, db_session: AsyncSession):
    org = await make_org(db_session)
    cat = await make_ticket_category(db_session, org.sector)
    owner_emp = await make_employee(db_session, org)
    other_emp = await make_employee(db_session, org)
    owner = await make_user(db_session, owner_emp)
    other = await make_user(db_session, other_emp)
    ticket = Ticket(
        title="t",
        description="d",
        requester_id=owner_emp.id,
        origin_unit_id=org.unit.id,
        origin_sector_id=org.sector.id,
        responsible_sector_id=org.sector.id,
        category_id=cat.id,
    )
    db_session.add(ticket)
    await db_session.commit()
    data = {"entity_type": "TICKET", "entity_id": str(ticket.id)}

    up = await client.post(URL, files=_pdf("foto.pdf"), data=data, headers=headers_for(owner))
    assert up.status_code == 201
    att_id = up.json()["id"]

    assert (await client.get(URL, params=data, headers=headers_for(other))).status_code == 403
    assert (await client.get(f"{URL}/{att_id}/download", headers=headers_for(other))).status_code == 403
    assert (await client.get(f"{URL}/{att_id}/download", headers=headers_for(owner))).status_code == 200
    assert (await client.delete(f"{URL}/{att_id}", headers=headers_for(owner))).status_code == 204
