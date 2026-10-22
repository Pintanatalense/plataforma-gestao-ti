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


# ---------------------------------------------------------------------------
# Regressões da revisão: série duplicada, JSON inválido e nomes repetidos
# ---------------------------------------------------------------------------


def _create_decision(filename: str, tag: str, category_id, unit_id) -> dict:
    return {"filename": filename, "action": "create", "tag": tag, "category_id": str(category_id), "unit_id": str(unit_id)}


async def test_serial_number_is_unique_in_the_database(db_session: AsyncSession):
    from sqlalchemy.exc import IntegrityError

    org = await make_org(db_session)
    category = await make_asset_category(db_session)
    first = await make_asset(db_session, org, category)
    second = await make_asset(db_session, org, category)
    first.serial_number = "SN-UNIQUE"
    await db_session.commit()
    second.serial_number = "SN-UNIQUE"
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_execute_same_serial_twice_in_batch_second_is_row_error(client: AsyncClient, db_session: AsyncSession):
    org = await make_org(db_session)
    category = await make_asset_category(db_session)
    admin = await make_user(db_session, is_admin=True)
    headers = headers_for(admin, "assets.write")

    decisions = [
        _create_decision("a.xml", "TAG-A", category.id, org.unit.id),
        _create_decision("b.xml", "TAG-B", category.id, org.unit.id),
    ]
    resp = await client.post(
        URL_EXECUTE,
        files=[_xml_file("a.xml", serial="SN-DUP"), _xml_file("b.xml", serial="SN-DUP")],
        data={"decisions": json.dumps(decisions)},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [r["outcome"] for r in body["results"]] == ["created", "error"]
    assert "SN-DUP" in body["results"][1]["error_message"]
    assert body["created_count"] == 1 and body["error_count"] == 1


async def test_analyze_serial_of_inactive_asset_is_row_error(client: AsyncClient, db_session: AsyncSession):
    org = await make_org(db_session)
    category = await make_asset_category(db_session)
    asset = await make_asset(db_session, org, category)
    asset.serial_number = "SN-INACTIVE"
    asset.is_active = False
    await db_session.commit()

    admin = await make_user(db_session, is_admin=True)
    resp = await client.post(
        URL_ANALYZE, files=[_xml_file("a.xml", serial="SN-INACTIVE")], headers=headers_for(admin, "assets.write")
    )
    assert resp.status_code == 200
    row = resp.json()["rows"][0]
    assert row["status"] == "ERROR"
    assert asset.tag in row["error_message"]


async def test_execute_update_with_serial_owned_by_another_asset_is_row_error(client: AsyncClient, db_session: AsyncSession):
    org = await make_org(db_session)
    category = await make_asset_category(db_session)
    owner = await make_asset(db_session, org, category)
    owner.serial_number = "SN-OWNER"
    other = await make_asset(db_session, org, category)
    await db_session.commit()

    admin = await make_user(db_session, is_admin=True)
    decisions = [{"filename": "a.xml", "action": "update", "asset_id": str(other.id)}]
    resp = await client.post(
        URL_EXECUTE,
        files=[_xml_file("a.xml", serial="SN-OWNER")],
        data={"decisions": json.dumps(decisions)},
        headers=headers_for(admin, "assets.write"),
    )
    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["outcome"] == "error"
    assert owner.tag in result["error_message"]


@pytest.mark.parametrize("bad", ["{nao-json", "{}", '"texto"', '[{"filename": "a.xml"}]'])
async def test_execute_invalid_decisions_is_422_not_500(client: AsyncClient, db_session: AsyncSession, bad: str):
    admin = await make_user(db_session, is_admin=True)
    resp = await client.post(
        URL_EXECUTE,
        files=[_xml_file("a.xml", serial="SN-X")],
        data={"decisions": bad},
        headers=headers_for(admin, "assets.write"),
    )
    assert resp.status_code == 422


async def test_repeated_filenames_are_rejected(client: AsyncClient, db_session: AsyncSession):
    admin = await make_user(db_session, is_admin=True)
    headers = headers_for(admin, "assets.write")
    files = [_xml_file("a.xml", serial="SN-1"), _xml_file("a.xml", serial="SN-2")]

    analyze = await client.post(URL_ANALYZE, files=files, headers=headers)
    assert analyze.status_code == 422
    assert "a.xml" in analyze.json()["error"]["message"]

    execute = await client.post(URL_EXECUTE, files=files, data={"decisions": "[]"}, headers=headers)
    assert execute.status_code == 422
