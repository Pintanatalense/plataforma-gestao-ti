"""
Baseline — Ativos e Movimentações (MOD-05/06).

Grupo A: comportamento atual. ``legacy_behavior`` marca comportamento que a
Etapa 3 reescreverá de propósito. Grupo B: defeitos conhecidos (xfail strict).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    headers_for,
    make_asset,
    make_asset_category,
    make_employee,
    make_org,
    make_unit,
    make_user,
)

pytestmark = pytest.mark.asyncio

ASSETS = "/api/v1/assets"
MOVEMENTS = "/api/v1/movements/"


async def _env(db: AsyncSession):
    org = await make_org(db)
    cat = await make_asset_category(db)
    emp = await make_employee(db, org)
    admin = await make_user(db, None, is_admin=True)
    return {"org": org, "cat": cat, "emp": emp, "admin": admin, "h": headers_for(admin)}


def _payload(env, **over) -> dict:
    base = {
        "tag": "PAT-1",
        "name": "Notebook",
        "category_id": str(env["cat"].id),
        "status": "IN_STOCK",
        "technical_specs": {},
        "unit_id": str(env["org"].unit.id),
    }
    base.update(over)
    return base


async def _movement_types(client: AsyncClient, env, asset_id: str) -> list[str]:
    resp = await client.get(f"/api/v1/movements/asset/{asset_id}", headers=env["h"])
    assert resp.status_code == 200
    return [m["movement_type"] for m in resp.json()]


# ---------------------------------------------------------------------------
# Grupo A — cadastro
# ---------------------------------------------------------------------------


async def test_duplicate_tag_is_rejected(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    assert (await client.post(ASSETS, json=_payload(env), headers=env["h"])).status_code == 200
    resp = await client.post(ASSETS, json=_payload(env), headers=env["h"])
    assert resp.status_code == 422


async def test_create_without_employee_records_initial_stock(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    asset = (await client.post(ASSETS, json=_payload(env), headers=env["h"])).json()
    assert await _movement_types(client, env, asset["id"]) == ["INITIAL_STOCK"]


async def test_create_with_employee_records_assignment(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    payload = _payload(env, status="IN_USE", employee_id=str(env["emp"].id))
    asset = (await client.post(ASSETS, json=payload, headers=env["h"])).json()
    assert await _movement_types(client, env, asset["id"]) == ["ASSIGNMENT"]


# ---------------------------------------------------------------------------
# Grupo A — PUT /assets/{id} gera o movimento deduzido
# ---------------------------------------------------------------------------


async def _create(client, env, **over) -> dict:
    resp = await client.post(ASSETS, json=_payload(env, **over), headers=env["h"])
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _put(client, env, asset_id: str, **over):
    return await client.put(f"{ASSETS}/{asset_id}", json=_payload(env, **over), headers=env["h"])


async def test_put_without_change_records_no_movement(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    asset = await _create(client, env)
    assert (await _put(client, env, asset["id"], name="Outro nome")).status_code == 200
    assert await _movement_types(client, env, asset["id"]) == ["INITIAL_STOCK"]


async def test_put_assign_then_return(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    asset = await _create(client, env)
    await _put(client, env, asset["id"], status="IN_USE", employee_id=str(env["emp"].id))
    await _put(client, env, asset["id"], status="IN_STOCK", employee_id=None)
    assert sorted(await _movement_types(client, env, asset["id"])) == ["ASSIGNMENT", "INITIAL_STOCK", "RETURN"]


async def test_put_unit_change_is_transfer(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    other_unit = await make_unit(db_session, env["org"].company)
    asset = await _create(client, env)
    await _put(client, env, asset["id"], unit_id=str(other_unit.id))
    assert sorted(await _movement_types(client, env, asset["id"])) == ["INITIAL_STOCK", "TRANSFER"]


async def test_put_status_maintenance_and_decommission(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    asset = await _create(client, env)
    await _put(client, env, asset["id"], status="MAINTENANCE")
    await _put(client, env, asset["id"], status="DECOMMISSIONED")
    assert sorted(await _movement_types(client, env, asset["id"])) == [
        "DECOMMISSION",
        "INITIAL_STOCK",
        "MAINTENANCE",
    ]


async def test_put_rejects_invalid_status_string(client: AsyncClient, db_session: AsyncSession):
    """Vocabulário de status é estritamente validado por Enum (422)."""
    env = await _env(db_session)
    asset = await _create(client, env)
    resp = await _put(client, env, asset["id"], status="QUALQUER_COISA")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Grupo A — POST /movements/
# ---------------------------------------------------------------------------


async def test_post_movement_updates_asset(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    asset = await _create(client, env)
    resp = await client.post(
        MOVEMENTS,
        json={
            "asset_id": asset["id"],
            "movement_type": "ASSIGNMENT",
            "to_employee_id": str(env["emp"].id),
            "status_to": "IN_USE",
        },
        headers=env["h"],
    )
    assert resp.status_code == 200, resp.text
    current = (await client.get(f"{ASSETS}/{asset['id']}", headers=env["h"])).json()
    assert current["status"] == "IN_USE"
    assert current["employee_id"] == str(env["emp"].id)


async def test_post_movement_for_unknown_asset_is_404(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    resp = await client.post(
        MOVEMENTS,
        json={"asset_id": "00000000-0000-0000-0000-000000000001", "movement_type": "TRANSFER"},
        headers=env["h"],
    )
    assert resp.status_code == 404


async def test_post_movement_maintenance_preserves_holder(client: AsyncClient, db_session: AsyncSession):
    """Manutenção sem to_employee_id preserva o responsável atual."""
    env = await _env(db_session)
    asset = await _create(client, env, status="IN_USE", employee_id=str(env["emp"].id))
    resp = await client.post(
        MOVEMENTS,
        json={"asset_id": asset["id"], "movement_type": "MAINTENANCE", "status_to": "MAINTENANCE"},
        headers=env["h"],
    )
    assert resp.status_code == 200
    current = (await client.get(f"{ASSETS}/{asset['id']}", headers=env["h"])).json()
    assert current["employee_id"] == str(env["emp"].id)


# ---------------------------------------------------------------------------
# Grupo A — autenticação e permissões
# ---------------------------------------------------------------------------


async def test_assets_require_authentication(client: AsyncClient, db_session: AsyncSession):
    await _env(db_session)
    assert (await client.get(ASSETS)).status_code == 401


async def test_assets_forbidden_without_permission(client: AsyncClient, db_session: AsyncSession):
    _ = await _env(db_session)
    plain = await make_user(db_session, None)
    assert (await client.get(ASSETS, headers=headers_for(plain))).status_code == 403


async def test_read_permission_allows_read_but_not_write(client: AsyncClient, db_session: AsyncSession):
    env = await _env(db_session)
    reader = await make_user(db_session, None)
    h = headers_for(reader, "assets.read")
    assert (await client.get(ASSETS, headers=h)).status_code == 200
    assert (await client.post(ASSETS, json=_payload(env), headers=h)).status_code == 403


async def test_movement_permission_uses_asset_write(client: AsyncClient, db_session: AsyncSession):
    """Movimentações usam 'assets.write' consistentemente com o restante do módulo."""
    env = await _env(db_session)
    asset = await make_asset(db_session, env["org"], env["cat"])
    writer = await make_user(db_session, None)
    body = {"asset_id": str(asset.id), "movement_type": "TRANSFER"}
    assert (await client.post(MOVEMENTS, json=body, headers=headers_for(writer, "assets.write"))).status_code == 200


# ---------------------------------------------------------------------------
# Defeitos corrigidos (R2)
# ---------------------------------------------------------------------------


async def test_second_assignment_of_in_use_asset_is_conflict(client: AsyncClient, db_session: AsyncSession):
    """R2 corrigido: entrega duplicada em ativo em uso retorna 409 Conflict."""
    env = await _env(db_session)
    other = await make_employee(db_session, env["org"])
    asset = await _create(client, env, status="IN_USE", employee_id=str(env["emp"].id))
    resp = await client.post(
        MOVEMENTS,
        json={
            "asset_id": asset["id"],
            "movement_type": "ASSIGNMENT",
            "to_employee_id": str(other.id),
            "status_to": "IN_USE",
        },
        headers=env["h"],
    )
    assert resp.status_code == 409


async def test_invalid_movement_type_is_rejected(client: AsyncClient, db_session: AsyncSession):
    """R2 corrigido: movement_type inválido é rejeitado com 422."""
    env = await _env(db_session)
    asset = await _create(client, env)
    resp = await client.post(
        MOVEMENTS, json={"asset_id": asset["id"], "movement_type": "XYZ"}, headers=env["h"]
    )
    assert resp.status_code == 422
