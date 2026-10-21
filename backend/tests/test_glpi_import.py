"""
Testes de integração da importação de ativos via inventário GLPI Agent.
"""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.movements.models import AssetMovement
from tests.factories import headers_for, make_asset, make_asset_category, make_org, make_user

pytestmark = pytest.mark.asyncio

URL_ANALYZE = "/api/v1/assets/glpi-import/analyze"
URL_EXECUTE = "/api/v1/assets/glpi-import/execute"


def _xml_file(filename: str, serial: str | None, hostname: str = "HOST1") -> tuple[str, tuple]:
    ssn = f"<SSN>{serial}</SSN>" if serial else ""
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<REQUEST>
  <CONTENT>
    <BIOS>{ssn}<SMANUFACTURER>LENOVO</SMANUFACTURER><SMODEL>ThinkPad</SMODEL></BIOS>
    <HARDWARE><NAME>{hostname}</NAME><CHASSIS_TYPE>Notebook</CHASSIS_TYPE></HARDWARE>
    <CPUS><NAME>Intel i5</NAME></CPUS>
    <MEMORIES><CAPACITY>8192</CAPACITY></MEMORIES>
    <OPERATINGSYSTEM><FULL_NAME>Windows 11</FULL_NAME></OPERATINGSYSTEM>
  </CONTENT>
  <DEVICEID>{hostname}-2026-01-01-00-00-00</DEVICEID>
  <QUERY>INVENTORY</QUERY>
</REQUEST>"""
    return ("files", (filename, content.encode("utf-8"), "text/xml"))


async def test_analyze_detects_matched_existing_asset(client: AsyncClient, db_session: AsyncSession):
    org = await make_org(db_session)
    category = await make_asset_category(db_session)
    asset = await make_asset(db_session, org, category)
    asset.serial_number = "SN-MATCHED-1"
    await db_session.commit()

    admin = await make_user(db_session, is_admin=True)
    headers = headers_for(admin, "assets.write")

    resp = await client.post(
        URL_ANALYZE,
        files=[_xml_file("one.xml", serial="SN-MATCHED-1")],
        headers=headers,
    )
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["status"] == "MATCHED"
    assert rows[0]["matched_asset_id"] == str(asset.id)
    assert rows[0]["matched_asset_tag"] == asset.tag


async def test_analyze_detects_new_asset_for_unknown_serial(client: AsyncClient, db_session: AsyncSession):
    admin = await make_user(db_session, is_admin=True)
    headers = headers_for(admin, "assets.write")

    resp = await client.post(
        URL_ANALYZE,
        files=[_xml_file("two.xml", serial="SN-NEVER-SEEN")],
        headers=headers,
    )
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert rows[0]["status"] == "NEW"
    assert rows[0]["serial_number"] == "SN-NEVER-SEEN"


async def test_analyze_rejects_more_than_twenty_files(client: AsyncClient, db_session: AsyncSession):
    admin = await make_user(db_session, is_admin=True)
    headers = headers_for(admin, "assets.write")

    files = [_xml_file(f"f{i}.xml", serial=f"SN-{i}") for i in range(21)]
    resp = await client.post(URL_ANALYZE, files=files, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_analyze_oversized_file_is_row_error_rest_of_batch_ok(client: AsyncClient, db_session: AsyncSession):
    admin = await make_user(db_session, is_admin=True)
    headers = headers_for(admin, "assets.write")

    oversized = ("files", ("huge.xml", b"x" * (5 * 1024 * 1024 + 1), "text/xml"))
    files = [oversized, _xml_file("ok.xml", serial="SN-OK")]
    resp = await client.post(URL_ANALYZE, files=files, headers=headers)
    assert resp.status_code == 200
    rows = {r["filename"]: r for r in resp.json()["rows"]}
    assert rows["huge.xml"]["status"] == "ERROR"
    assert rows["ok.xml"]["status"] == "NEW"


async def test_execute_update_does_not_create_spurious_movement_and_preserves_sibling_specs(
    client: AsyncClient, db_session: AsyncSession
):
    org = await make_org(db_session)
    category = await make_asset_category(db_session)
    asset = await make_asset(db_session, org, category)
    asset.serial_number = "SN-UPDATE-1"
    asset.technical_specs = {"custom": "valor digitado pelo admin"}
    await db_session.commit()
    await db_session.refresh(asset)

    movements_before = (
        (await db_session.execute(select(AssetMovement).where(AssetMovement.asset_id == asset.id)))
        .scalars()
        .all()
    )

    admin = await make_user(db_session, is_admin=True)
    headers = headers_for(admin, "assets.write")

    decisions = [{"filename": "one.xml", "action": "update", "asset_id": str(asset.id)}]
    resp = await client.post(
        URL_EXECUTE,
        files=[_xml_file("one.xml", serial="SN-UPDATE-1", hostname="UPDATED-HOST")],
        data={"decisions": json.dumps(decisions)},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["updated_count"] == 1
    assert body["results"][0]["outcome"] == "updated"

    movements_after = (
        (await db_session.execute(select(AssetMovement).where(AssetMovement.asset_id == asset.id)))
        .scalars()
        .all()
    )
    assert len(movements_after) == len(movements_before)

    await db_session.refresh(asset)
    assert asset.technical_specs["custom"] == "valor digitado pelo admin"
    assert asset.technical_specs["hostname"] == "UPDATED-HOST"
    assert asset.technical_specs["cpu"] == "Intel i5"


async def test_execute_create_requires_tag_category_unit(client: AsyncClient, db_session: AsyncSession):
    admin = await make_user(db_session, is_admin=True)
    headers = headers_for(admin, "assets.write")

    decisions = [{"filename": "new.xml", "action": "create"}]
    resp = await client.post(
        URL_EXECUTE,
        files=[_xml_file("new.xml", serial="SN-NEW-1")],
        data={"decisions": json.dumps(decisions)},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["error_count"] == 1
    assert body["results"][0]["outcome"] == "error"

    count_assets = (await db_session.execute(select(Asset))).scalars().all()
    assert len(count_assets) == 0


async def test_execute_create_with_required_fields_creates_asset_with_initial_stock_movement(
    client: AsyncClient, db_session: AsyncSession
):
    org = await make_org(db_session)
    category = await make_asset_category(db_session)

    admin = await make_user(db_session, is_admin=True)
    headers = headers_for(admin, "assets.write")

    decisions = [
        {
            "filename": "new.xml",
            "action": "create",
            "tag": "PAT-GLPI-1",
            "category_id": str(category.id),
            "unit_id": str(org.unit.id),
        }
    ]
    resp = await client.post(
        URL_EXECUTE,
        files=[_xml_file("new.xml", serial="SN-NEW-2", hostname="NEW-HOST")],
        data={"decisions": json.dumps(decisions)},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["created_count"] == 1
    asset_id = body["results"][0]["asset_id"]
    assert asset_id is not None

    asset = await db_session.get(Asset, uuid.UUID(asset_id))
    assert asset.serial_number == "SN-NEW-2"
    assert asset.tag == "PAT-GLPI-1"
    assert asset.technical_specs["hostname"] == "NEW-HOST"
    assert asset.technical_specs["cpu"] == "Intel i5"
    assert asset.name == "ThinkPad"  # nome sugerido vem do modelo (SMODEL), não do hostname

    movements = (
        (await db_session.execute(select(AssetMovement).where(AssetMovement.asset_id == asset.id)))
        .scalars()
        .all()
    )
    assert len(movements) == 1
    assert movements[0].movement_type == "INITIAL_STOCK"


async def test_execute_create_duplicate_tag_is_row_error_other_rows_still_succeed(
    client: AsyncClient, db_session: AsyncSession
):
    org = await make_org(db_session)
    category = await make_asset_category(db_session)
    existing = await make_asset(db_session, org, category)

    admin = await make_user(db_session, is_admin=True)
    headers = headers_for(admin, "assets.write")

    decisions = [
        {
            "filename": "dup.xml",
            "action": "create",
            "tag": existing.tag,
            "category_id": str(category.id),
            "unit_id": str(org.unit.id),
        },
        {
            "filename": "ok.xml",
            "action": "create",
            "tag": "PAT-GLPI-OK",
            "category_id": str(category.id),
            "unit_id": str(org.unit.id),
        },
    ]
    resp = await client.post(
        URL_EXECUTE,
        files=[
            _xml_file("dup.xml", serial="SN-DUP"),
            _xml_file("ok.xml", serial="SN-OK-2"),
        ],
        data={"decisions": json.dumps(decisions)},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    results = {r["filename"]: r for r in body["results"]}
    assert results["dup.xml"]["outcome"] == "error"
    assert results["ok.xml"]["outcome"] == "created"


async def test_analyze_requires_assets_write_permission(client: AsyncClient, db_session: AsyncSession):
    user = await make_user(db_session)
    headers = headers_for(user)  # sem permissões

    resp = await client.post(
        URL_ANALYZE,
        files=[_xml_file("one.xml", serial="SN-X")],
        headers=headers,
    )
    assert resp.status_code == 403


async def test_execute_requires_assets_write_permission(client: AsyncClient, db_session: AsyncSession):
    user = await make_user(db_session)
    headers = headers_for(user)  # sem permissões

    resp = await client.post(
        URL_EXECUTE,
        files=[_xml_file("one.xml", serial="SN-X")],
        data={"decisions": json.dumps([{"filename": "one.xml", "action": "skip"}])},
        headers=headers,
    )
    assert resp.status_code == 403
