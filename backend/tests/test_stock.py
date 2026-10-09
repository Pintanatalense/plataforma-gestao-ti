import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import make_auth_headers

from app.organization.models import Company, Unit
from app.identity.models import UserAccount
from app.core.security import hash_password

pytestmark = pytest.mark.asyncio

async def setup_test_data(db_session: AsyncSession):
    company = Company(name="Test Company", cnpj="123")
    db_session.add(company)
    await db_session.commit()

    unit = Unit(name="HQ", code="HQ1", company_id=company.id)
    db_session.add(unit)
    await db_session.commit()

    user = UserAccount(email="test_stock@test.com", hashed_password=hash_password("123"), is_admin=True)
    db_session.add(user)
    await db_session.commit()

    return {"unit": unit, "user": user}

async def test_create_and_list_stock_items(client: AsyncClient, db_session: AsyncSession):
    data = await setup_test_data(db_session)
    user = data["user"]
    unit = data["unit"]

    headers = make_auth_headers(user_id=str(user.id), is_admin=True)
    
    # 1. Create item
    payload = {
        "name": "Teclado USB",
        "description": "Teclado Padrão",
        "unit_id": str(unit.id),
        "initial_quantity": 10,
        "min_quantity": 5
    }
    resp = await client.post("/api/v1/stock/items", json=payload, headers=headers)
    assert resp.status_code == 200
    item = resp.json()
    assert item["name"] == "Teclado USB"
    assert item["quantity"] == 10
    
    # 2. List items
    resp2 = await client.get("/api/v1/stock/items", headers=headers)
    assert resp2.status_code == 200
    items = resp2.json()
    assert len(items) == 1
    assert items[0]["id"] == item["id"]

async def test_stock_movement(client: AsyncClient, db_session: AsyncSession):
    data = await setup_test_data(db_session)
    user = data["user"]
    unit = data["unit"]
    headers = make_auth_headers(user_id=str(user.id), is_admin=True)
    
    # Create item with 0 initial
    item_payload = {
        "name": "Mouse USB",
        "unit_id": str(unit.id),
        "initial_quantity": 0,
        "min_quantity": 2
    }
    resp = await client.post("/api/v1/stock/items", json=item_payload, headers=headers)
    item_id = resp.json()["id"]

    # Add 5 items
    mov_payload = {
        "item_id": item_id,
        "movement_type": "IN",
        "quantity": 5,
        "notes": "Compra nova"
    }
    resp_mov = await client.post("/api/v1/stock/movements", json=mov_payload, headers=headers)
    assert resp_mov.status_code == 200
    
    # Check item quantity
    resp_get = await client.get(f"/api/v1/stock/items/{item_id}", headers=headers)
    assert resp_get.json()["quantity"] == 5

    # Remove 2 items
    mov_out_payload = {
        "item_id": item_id,
        "movement_type": "OUT",
        "quantity": 2,
        "notes": "Entregue a colaborador"
    }
    resp_mov_out = await client.post("/api/v1/stock/movements", json=mov_out_payload, headers=headers)
    assert resp_mov_out.status_code == 200

    # Check item quantity again
    resp_get2 = await client.get(f"/api/v1/stock/items/{item_id}", headers=headers)
    assert resp_get2.json()["quantity"] == 3

    # Check movements list
    resp_list_mov = await client.get(f"/api/v1/stock/movements/item/{item_id}", headers=headers)
    movs = resp_list_mov.json()
    assert len(movs) == 2
