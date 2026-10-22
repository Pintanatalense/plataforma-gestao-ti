import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.organization.models import Employee, Company, Unit, Sector
from app.identity.models import UserAccount
from app.assets.models import AssetCategory
from app.core.security import hash_password
from tests.conftest import make_auth_headers

pytestmark = pytest.mark.asyncio


async def setup_test_data(db_session: AsyncSession):
    company = Company(name="Test Company", cnpj="123")
    db_session.add(company)
    await db_session.commit()

    unit = Unit(name="HQ", code="HQ1", company_id=company.id)
    db_session.add(unit)
    await db_session.commit()

    dept = Sector(name="IT", code="IT1", unit_id=unit.id)
    db_session.add(dept)
    await db_session.commit()

    employee = Employee(name="Test User", registration_number="123", unit_id=unit.id, sector_id=dept.id)
    db_session.add(employee)
    await db_session.commit()

    user = UserAccount(email="test@test.com", hashed_password=hash_password("123"), employee_id=employee.id, is_admin=True)
    db_session.add(user)
    await db_session.commit()

    category = AssetCategory(name="Notebook", spec_schema={"cpu": {"type": "string"}})
    db_session.add(category)
    await db_session.commit()

    return {
        "company": company,
        "unit": unit,
        "dept": dept,
        "employee": employee,
        "user": user,
        "category": category,
    }


async def test_create_category(client: AsyncClient, db_session: AsyncSession):
    data = await setup_test_data(db_session)
    user = data["user"]

    headers = make_auth_headers(user_id=str(user.id), is_admin=True)
    
    payload = {
        "name": "Monitor",
        "description": "Monitores de vídeo",
        "spec_schema": {"resolution": {"type": "string"}}
    }

    response = await client.post("/api/v1/assets/categories", json=payload, headers=headers)
    assert response.status_code == 200
    resp_data = response.json()
    assert resp_data["name"] == "Monitor"
    assert "resolution" in resp_data["spec_schema"]


async def test_create_and_list_asset(client: AsyncClient, db_session: AsyncSession):
    data = await setup_test_data(db_session)
    user = data["user"]
    category = data["category"]
    unit = data["unit"]

    headers = make_auth_headers(user_id=str(user.id), is_admin=True)
    
    payload = {
        "tag": "PAT-1001",
        "name": "Notebook Dell XPS",
        "category_id": str(category.id),
        "status": "IN_STOCK",
        "technical_specs": {"cpu": "Intel Core i7"},
        "unit_id": str(unit.id)
    }

    response = await client.post("/api/v1/assets", json=payload, headers=headers)
    assert response.status_code == 200
    resp_data = response.json()
    assert resp_data["tag"] == "PAT-1001"
    asset_id = resp_data["id"]

    # List assets
    list_response = await client.get("/api/v1/assets", headers=headers)
    assert list_response.status_code == 200
    list_data = list_response.json()
    assert len(list_data) == 1
    assert list_data[0]["id"] == asset_id
    assert list_data[0]["category"]["name"] == "Notebook"


async def test_update_asset_creates_movement(client: AsyncClient, db_session: AsyncSession):
    data = await setup_test_data(db_session)
    user = data["user"]
    category = data["category"]
    unit = data["unit"]
    employee = data["employee"]

    headers = make_auth_headers(user_id=str(user.id), is_admin=True)
    
    # 1. Create asset in stock
    payload = {
        "tag": "PAT-1002",
        "name": "Notebook Thinkpad",
        "category_id": str(category.id),
        "status": "IN_STOCK",
        "technical_specs": {},
        "unit_id": str(unit.id)
    }
    response = await client.post("/api/v1/assets", json=payload, headers=headers)
    assert response.status_code == 200
    asset_id = response.json()["id"]

    # 2. Update asset to be assigned to employee
    update_payload = {
        **payload,
        "status": "IN_USE",
        "employee_id": str(employee.id)
    }
    update_response = await client.put(f"/api/v1/assets/{asset_id}", json=update_payload, headers=headers)
    assert update_response.status_code == 200

    # 3. Check movements
    mov_response = await client.get(f"/api/v1/movements/asset/{asset_id}", headers=headers)
    assert mov_response.status_code == 200
    movements = mov_response.json()
    
    # Expected movements: 1. INITIAL_STOCK on create, 2. ASSIGNMENT on update
    assert len(movements) == 2
    assert movements[0]["movement_type"] == "ASSIGNMENT"
    assert movements[0]["status_to"] == "IN_USE"
    assert movements[0]["to_employee_id"] == str(employee.id)

    assert movements[1]["movement_type"] == "INITIAL_STOCK"
