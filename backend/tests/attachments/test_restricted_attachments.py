"""
Anexos restritos (ADR-026, PR 3): o anexo marcado ``is_internal`` segue a regra das notas internas do chamado.
Para quem não as vê, ele não existe: some da listagem, e o download e a exclusão por id dão 404.
"""

import io

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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

PDF = b"%PDF-1.4\n% conteudo restrito\n"
URL = "/api/v1/attachments"
API = "/api/v1/tickets"
MANAGE = "service_desk.tickets.manage"


def _pdf():
    return {"file": ("laudo.pdf", io.BytesIO(PDF), "application/pdf")}


async def _attendant(db: AsyncSession, org, sector):
    emp = await make_employee(db, org)
    emp.sector_id = sector.id
    await db.commit()
    return await make_user(db, emp)


async def _world(client: AsyncClient, db: AsyncSession):
    """Principal no setor P com um filho no setor B; `opener` abriu em nome do solicitante."""
    org = await make_org(db)
    sector_b = await make_sector(db, org.unit)
    cat_p = await make_ticket_category(db, org.sector)
    cat_b = await make_ticket_category(db, sector_b)
    requester_emp = await make_employee(db, org)
    requester = await make_user(db, requester_emp)
    opener = await make_user(db, await make_employee(db, org))
    att_p = await _attendant(db, org, org.sector)
    att_b = await _attendant(db, org, sector_b)
    body = {
        "title": "P", "description": "d", "category_id": str(cat_p.id), "requester_id": str(requester_emp.id),
        "children": [{"category_id": str(cat_b.id), "title": "E", "description": "d"}],
    }
    resp = await client.post(API, json=body, headers=headers_for(opener, "service_desk.tickets.create_on_behalf"))
    assert resp.status_code == 201, resp.text
    parent_id = resp.json()["id"]
    overview = (await client.get(f"{API}/{parent_id}/children", headers=headers_for(requester))).json()
    child_id = overview["children"][0]["id"]
    return requester, opener, att_p, att_b, parent_id, child_id


async def _upload(client: AsyncClient, ticket_id: str, headers, is_internal: bool):
    data = {"entity_type": "TICKET", "entity_id": ticket_id, "is_internal": str(is_internal).lower()}
    return await client.post(URL, files=_pdf(), data=data, headers=headers)


async def _listed(client: AsyncClient, ticket_id: str, headers) -> set[str]:
    resp = await client.get(URL, params={"entity_type": "TICKET", "entity_id": ticket_id}, headers=headers)
    assert resp.status_code == 200, resp.text
    return {a["id"] for a in resp.json()}


async def test_restricted_attachment_is_invisible_outside_the_child_sector(
    client: AsyncClient, db_session: AsyncSession
):
    requester, opener, att_p, att_b, _, child_id = await _world(client, db_session)
    hb = headers_for(att_b, MANAGE)
    restricted = (await _upload(client, child_id, hb, True)).json()
    public = (await _upload(client, child_id, hb, False)).json()
    assert restricted["is_internal"] is True

    # O setor do filho vê e baixa os dois.
    assert await _listed(client, child_id, hb) == {restricted["id"], public["id"]}
    assert (await client.get(f"{URL}/{restricted['id']}/download", headers=hb)).content == PDF

    # Solicitante e quem abriu o principal: só o público; o restrito dá 404 no link direto e na exclusão.
    for user in (requester, opener):
        h = headers_for(user)
        assert await _listed(client, child_id, h) == {public["id"]}
        assert (await client.get(f"{URL}/{restricted['id']}/download", headers=h)).status_code == 404
        assert (await client.delete(f"{URL}/{restricted['id']}", headers=h)).status_code == 404
        assert (await client.get(f"{URL}/{public['id']}/download", headers=h)).status_code == 200

    # O atendente do principal não vê o filho de outro setor: 403 na listagem e no download.
    hp = headers_for(att_p, MANAGE)
    assert (await client.get(f"{URL}/{restricted['id']}/download", headers=hp)).status_code in (403, 404)
    assert (await client.get(
        URL, params={"entity_type": "TICKET", "entity_id": child_id}, headers=hp
    )).status_code == 403


async def test_only_who_sees_internal_notes_uploads_restricted(client: AsyncClient, db_session: AsyncSession):
    requester, opener, att_p, att_b, parent_id, child_id = await _world(client, db_session)
    for user, ticket_id in ((requester, child_id), (opener, child_id), (requester, parent_id)):
        assert (await _upload(client, ticket_id, headers_for(user), True)).status_code == 403
        assert (await _upload(client, ticket_id, headers_for(user), False)).status_code == 201
    # No principal, o setor dele envia anexos restritos que o solicitante não vê.
    hp = headers_for(att_p, MANAGE)
    restricted = (await _upload(client, parent_id, hp, True)).json()
    assert restricted["id"] not in await _listed(client, parent_id, headers_for(requester))
    assert restricted["id"] in await _listed(client, parent_id, hp)


async def test_asset_attachments_cannot_be_restricted(client: AsyncClient, db_session: AsyncSession):
    org = await make_org(db_session)
    asset = await make_asset(db_session, org, await make_asset_category(db_session))
    admin = await make_user(db_session, is_admin=True)
    data = {"entity_type": "ASSET", "entity_id": str(asset.id), "is_internal": "true"}
    resp = await client.post(URL, files=_pdf(), data=data, headers=headers_for(admin))
    assert resp.status_code == 422


async def test_existing_attachments_stay_public(client: AsyncClient, db_session: AsyncSession):
    requester, _, _, att_b, _, child_id = await _world(client, db_session)
    data = {"entity_type": "TICKET", "entity_id": child_id}
    up = await client.post(URL, files=_pdf(), data=data, headers=headers_for(att_b, MANAGE))
    assert up.status_code == 201 and up.json()["is_internal"] is False
    assert up.json()["id"] in await _listed(client, child_id, headers_for(requester))


@pytest.mark.pg
@pytest.mark.migrations
async def test_migration_adds_and_drops_is_internal():
    import asyncio
    import os
    from pathlib import Path

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

    async def has_column() -> bool:
        async with engine.connect() as conn:
            rows = await conn.execute(text(
                "SELECT 1 FROM information_schema.columns WHERE table_name = 'attachments' AND column_name = 'is_internal'"
            ))
            return rows.first() is not None

    try:
        await loop.run_in_executor(None, command.upgrade, cfg, "c2d3e4f5a6b7c")
        assert await has_column()
        await loop.run_in_executor(None, command.downgrade, cfg, "b1c2d3e4f5a6b")
        assert not await has_column()
    finally:
        await engine.dispose()
