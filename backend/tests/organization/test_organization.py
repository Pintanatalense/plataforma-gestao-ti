"""Testes de integração do MOD-02 — Organização."""

from httpx import AsyncClient

from tests.conftest import make_auth_headers

BASE = "/api/v1/organization"
ADMIN = make_auth_headers(is_admin=True)


async def _create_company(client: AsyncClient) -> dict:
    response = await client.post(f"{BASE}/company", json={"name": "ACME", "cnpj": "11.111.111/0001-11"}, headers=ADMIN)
    assert response.status_code == 201, response.text
    return response.json()


async def _create_unit(client: AsyncClient, company_id: str, code: str = "MAT-01") -> dict:
    response = await client.post(
        f"{BASE}/units",
        json={"company_id": company_id, "name": f"Unidade {code}", "code": code, "type": "MATRIZ"},
        headers=ADMIN,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_sector(client: AsyncClient, unit_id: str, code: str = "TI") -> dict:
    response = await client.post(
        f"{BASE}/sectors", json={"unit_id": unit_id, "name": f"Setor {code}", "code": code}, headers=ADMIN
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_structure(client: AsyncClient) -> tuple[dict, dict, dict]:
    company = await _create_company(client)
    unit = await _create_unit(client, company["id"])
    sector = await _create_sector(client, unit["id"])
    return company, unit, sector


# ------------------------------------------------------------------------------
# Autenticação / autorização
# ------------------------------------------------------------------------------


async def test_requires_authentication(client: AsyncClient) -> None:
    response = await client.get(f"{BASE}/units")
    assert response.status_code == 401


async def test_missing_permission_returns_403(client: AsyncClient) -> None:
    headers = make_auth_headers(permissions=["organization.units.read"])
    response = await client.get(f"{BASE}/sectors", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_permission_grants_access(client: AsyncClient) -> None:
    headers = make_auth_headers(permissions=["organization.units.read"])
    response = await client.get(f"{BASE}/units", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


# ------------------------------------------------------------------------------
# Empresa
# ------------------------------------------------------------------------------


async def test_get_company_not_configured_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"{BASE}/company", headers=ADMIN)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_initialize_company_only_once(client: AsyncClient) -> None:
    await _create_company(client)
    response = await client.post(f"{BASE}/company", json={"name": "Outra"}, headers=ADMIN)
    assert response.status_code == 409


async def test_update_company(client: AsyncClient) -> None:
    await _create_company(client)
    response = await client.patch(f"{BASE}/company", json={"name": "ACME Ltda"}, headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["name"] == "ACME Ltda"


# ------------------------------------------------------------------------------
# Unidades e setores
# ------------------------------------------------------------------------------


async def test_unit_crud(client: AsyncClient) -> None:
    company = await _create_company(client)
    unit = await _create_unit(client, company["id"])

    response = await client.get(f"{BASE}/units", headers=ADMIN)
    assert [u["id"] for u in response.json()] == [unit["id"]]

    response = await client.patch(f"{BASE}/units/{unit['id']}", json={"name": "Sede"}, headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["name"] == "Sede"


async def test_get_unknown_unit_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"{BASE}/units/00000000-0000-0000-0000-000000000000", headers=ADMIN)
    assert response.status_code == 404


async def test_duplicate_unit_code_returns_409(client: AsyncClient) -> None:
    company = await _create_company(client)
    await _create_unit(client, company["id"], code="F-01")
    response = await client.post(
        f"{BASE}/units", json={"company_id": company["id"], "name": "X", "code": "F-01"}, headers=ADMIN
    )
    assert response.status_code == 409


async def test_sector_requires_existing_unit(client: AsyncClient) -> None:
    response = await client.post(
        f"{BASE}/sectors",
        json={"unit_id": "00000000-0000-0000-0000-000000000000", "name": "TI", "code": "TI"},
        headers=ADMIN,
    )
    assert response.status_code == 404


async def test_list_sectors_filtered_by_unit(client: AsyncClient) -> None:
    company = await _create_company(client)
    unit_a = await _create_unit(client, company["id"], code="A")
    unit_b = await _create_unit(client, company["id"], code="B")
    sector_a = await _create_sector(client, unit_a["id"], code="TI-A")
    await _create_sector(client, unit_b["id"], code="TI-B")

    response = await client.get(f"{BASE}/sectors", params={"unit_id": unit_a["id"]}, headers=ADMIN)
    assert [s["id"] for s in response.json()] == [sector_a["id"]]


# ------------------------------------------------------------------------------
# Colaboradores
# ------------------------------------------------------------------------------


async def test_employee_crud(client: AsyncClient) -> None:
    _, unit, sector = await _create_structure(client)
    payload = {"unit_id": unit["id"], "sector_id": sector["id"], "name": "Maria", "registration_number": "001"}

    response = await client.post(f"{BASE}/employees", json=payload, headers=ADMIN)
    assert response.status_code == 201, response.text
    employee = response.json()
    assert employee["status"] == "ATIVO"

    response = await client.patch(
        f"{BASE}/employees/{employee['id']}", json={"position": "Analista"}, headers=ADMIN
    )
    assert response.status_code == 200
    assert response.json()["position"] == "Analista"


async def test_duplicate_registration_returns_409(client: AsyncClient) -> None:
    _, unit, sector = await _create_structure(client)
    payload = {"unit_id": unit["id"], "sector_id": sector["id"], "name": "Maria", "registration_number": "001"}
    await client.post(f"{BASE}/employees", json=payload, headers=ADMIN)

    response = await client.post(f"{BASE}/employees", json={**payload, "name": "João"}, headers=ADMIN)
    assert response.status_code == 409


async def test_employee_sector_must_belong_to_unit(client: AsyncClient) -> None:
    company, unit_a, sector_a = await _create_structure(client)
    unit_b = await _create_unit(client, company["id"], code="B")

    payload = {"unit_id": unit_b["id"], "sector_id": sector_a["id"], "name": "Maria", "registration_number": "001"}
    response = await client.post(f"{BASE}/employees", json=payload, headers=ADMIN)
    assert response.status_code == 400
