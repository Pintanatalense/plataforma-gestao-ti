"""Testes de integração do MOD-02 — Organização."""

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.identity.models import UserAccount
from tests.conftest import make_auth_headers

BASE = "/api/v1/organization"
ADMIN_ID = uuid.uuid4()
REGULAR_ID = uuid.uuid4()
ADMIN = make_auth_headers(str(ADMIN_ID), is_admin=True)


@pytest_asyncio.fixture(autouse=True)
async def _users(db_session: AsyncSession) -> None:
    """O usuário do token precisa existir e estar ativo no banco."""
    db_session.add_all(
        [
            UserAccount(id=ADMIN_ID, email="admin@org.test", hashed_password=hash_password("x"), is_admin=True),
            UserAccount(id=REGULAR_ID, email="regular@org.test", hashed_password=hash_password("x")),
        ]
    )
    await db_session.commit()


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
    headers = make_auth_headers(str(REGULAR_ID), permissions=["organization.units.read"])
    response = await client.get(f"{BASE}/sectors", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_permission_grants_access(client: AsyncClient) -> None:
    headers = make_auth_headers(str(REGULAR_ID), permissions=["organization.units.read"])
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


async def test_logo_upload_accepts_png_and_rejects_html_and_svg(client: AsyncClient, db_session: AsyncSession):
    from tests.factories import headers_for, make_user

    admin = await make_user(db_session, is_admin=True)
    h = headers_for(admin)
    url = "/api/v1/organization/company/logo"
    from app.organization.models import Company

    db_session.add(Company(name="Logo Corp"))
    await db_session.commit()

    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    ok = await client.post(url, files={"file": ("../../x.html", png, "image/png")}, headers=h)
    assert ok.status_code == 200
    assert ok.json()["logo_url"].startswith("/static/logo.png?v=")

    html = await client.post(url, files={"file": ("logo.png", b"<script>alert(1)</script>", "image/png")}, headers=h)
    assert html.status_code == 422
    svg = await client.post(url, files={"file": ("logo.svg", b"<svg onload=alert(1)/>", "image/svg+xml")}, headers=h)
    assert svg.status_code == 422


JPEG = b"\xff\xd8\xff" + b"0" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
LOGO_URL = "/api/v1/organization/company/logo"


async def _admin_headers(db_session: AsyncSession):
    from tests.factories import headers_for, make_user

    return headers_for(await make_user(db_session, is_admin=True))


async def test_uploaded_logo_is_persisted_and_served_by_company_public(client: AsyncClient, db_session: AsyncSession):
    """Antes, update_company ignorava logo_url: /company/public devolvia sempre null depois do upload."""
    from sqlalchemy import select

    from app.organization.models import Company

    h = await _admin_headers(db_session)
    db_session.add(Company(name="Logo Persist"))
    await db_session.commit()

    sent = (await client.post(LOGO_URL, files={"file": ("x.png", PNG, "image/png")}, headers=h)).json()["logo_url"]

    public = (await client.get("/api/v1/organization/company/public")).json()
    assert public["logo_url"] == sent
    stored = (await db_session.execute(select(Company.logo_url))).scalar_one()
    assert stored == sent


async def test_replacing_the_logo_keeps_a_single_file_and_a_new_url(client: AsyncClient, db_session: AsyncSession):
    import os

    from app.config import get_settings

    h = await _admin_headers(db_session)
    from app.organization.models import Company

    db_session.add(Company(name="Logo Replace"))
    await db_session.commit()

    await client.post(LOGO_URL, files={"file": ("a.png", PNG, "image/png")}, headers=h)
    second = (await client.post(LOGO_URL, files={"file": ("b.jpg", JPEG, "image/jpeg")}, headers=h)).json()["logo_url"]

    assert second.startswith("/static/logo.jpg?v=")
    assert (await client.get("/api/v1/organization/company/public")).json()["logo_url"] == second
    logos = [f for f in os.listdir(str(get_settings().static_dir)) if f.startswith("logo.")]
    assert logos == ["logo.jpg"]


async def test_logo_upload_without_a_company_is_404_and_writes_no_file(client: AsyncClient, db_session: AsyncSession):
    import os

    from app.config import get_settings

    h = await _admin_headers(db_session)
    static_dir = str(get_settings().static_dir)
    before = set(os.listdir(static_dir)) if os.path.isdir(static_dir) else set()

    resp = await client.post(LOGO_URL, files={"file": ("a.png", PNG, "image/png")}, headers=h)

    assert resp.status_code == 404
    after = set(os.listdir(static_dir)) if os.path.isdir(static_dir) else set()
    assert after == before


async def test_patch_company_rejects_an_external_logo_url(client: AsyncClient, db_session: AsyncSession):
    from app.organization.models import Company

    h = await _admin_headers(db_session)
    db_session.add(Company(name="Logo Patch"))
    await db_session.commit()
    url = "/api/v1/organization/company"

    for bad in ("https://tracker.example.com/pixel.png", "//evil.example/x.png", "/static/../etc/passwd", "javascript:alert(1)"):
        resp = await client.patch(url, json={"logo_url": bad}, headers=h)
        assert resp.status_code == 422, bad

    ok = await client.patch(url, json={"logo_url": "/static/logo.png?v=123"}, headers=h)
    assert ok.status_code == 200 and ok.json()["logo_url"] == "/static/logo.png?v=123"
