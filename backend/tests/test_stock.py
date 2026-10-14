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


async def test_stock_categories_crud(client: AsyncClient, db_session: AsyncSession):
    data = await setup_test_data(db_session)
    user = data["user"]
    headers = make_auth_headers(user_id=str(user.id), is_admin=True)

    # 1. Create category
    cat_payload = {
        "name": "Cabos & Conectores",
        "description": "Cabos de rede e vídeo",
        "spec_schema": {
            "tipo": {"label": "Tipo de Cabo", "required": True},
            "comprimento": {"label": "Comprimento (metros)", "required": False}
        }
    }
    resp = await client.post("/api/v1/stock/categories", json=cat_payload, headers=headers)
    assert resp.status_code == 201
    created_cat = resp.json()
    assert created_cat["name"] == "Cabos & Conectores"
    assert "tipo" in created_cat["spec_schema"]
    cat_id = created_cat["id"]

    # 2. List categories
    resp_list = await client.get("/api/v1/stock/categories", headers=headers)
    assert resp_list.status_code == 200
    cats = resp_list.json()
    assert any(c["id"] == cat_id for c in cats)

    # 3. Get category by ID
    resp_get = await client.get(f"/api/v1/stock/categories/{cat_id}", headers=headers)
    assert resp_get.status_code == 200
    assert resp_get.json()["id"] == cat_id

    # 4. Update category
    update_payload = {
        "name": "Cabos, Adaptadores & Conectores",
        "description": "Cabos de rede, adaptadores e conectores de vídeo",
        "spec_schema": {
            "tipo": {"label": "Tipo de Cabo", "required": True},
            "comprimento": {"label": "Comprimento (metros)", "required": False},
            "blindado": {"label": "Blindado", "required": False}
        }
    }
    resp_up = await client.put(f"/api/v1/stock/categories/{cat_id}", json=update_payload, headers=headers)
    assert resp_up.status_code == 200
    assert resp_up.json()["name"] == "Cabos, Adaptadores & Conectores"
    assert "blindado" in resp_up.json()["spec_schema"]

    # 5. Delete category
    resp_del = await client.delete(f"/api/v1/stock/categories/{cat_id}", headers=headers)
    assert resp_del.status_code == 204

    # 6. Verify deleted (should return 404)
    resp_after = await client.get(f"/api/v1/stock/categories/{cat_id}", headers=headers)
    assert resp_after.status_code == 404


async def test_stock_item_with_category_and_specs(client: AsyncClient, db_session: AsyncSession):
    data = await setup_test_data(db_session)
    user = data["user"]
    unit = data["unit"]
    headers = make_auth_headers(user_id=str(user.id), is_admin=True)

    # 1. Create category
    cat_payload = {
        "name": "Toners & Cartuchos",
        "description": "Suprimentos de impressão",
        "spec_schema": {
            "modelo": {"label": "Modelo", "required": True},
            "cor": {"label": "Cor", "required": True},
            "rendimento": {"label": "Rendimento Estimado", "required": False}
        }
    }
    resp_cat = await client.post("/api/v1/stock/categories", json=cat_payload, headers=headers)
    assert resp_cat.status_code == 201
    cat_id = resp_cat.json()["id"]

    # 2. Create item linked to category and with custom specs
    item_payload = {
        "name": "Toner HP 105A Preto",
        "description": "Toner compatível com HP Neverstop 1000",
        "unit_id": str(unit.id),
        "initial_quantity": 4,
        "min_quantity": 2,
        "category_id": cat_id,
        "technical_specs": {
            "modelo": "W1105A",
            "cor": "Preto",
            "rendimento": "1000 páginas"
        }
    }
    resp_item = await client.post("/api/v1/stock/items", json=item_payload, headers=headers)
    assert resp_item.status_code == 200
    item_data = resp_item.json()
    assert item_data["category_id"] == cat_id
    assert item_data["technical_specs"]["modelo"] == "W1105A"
    assert item_data["category"]["name"] == "Toners & Cartuchos"
    item_id = item_data["id"]

    # 3. Retrieve item by ID
    resp_get = await client.get(f"/api/v1/stock/items/{item_id}", headers=headers)
    assert resp_get.status_code == 200
    fetched = resp_get.json()
    assert fetched["category"]["id"] == cat_id
    assert fetched["technical_specs"]["cor"] == "Preto"

    # 4. Update item specs
    update_payload = {
        "technical_specs": {
            "modelo": "W1105A",
            "cor": "Preto",
            "rendimento": "1200 páginas"
        }
    }
    resp_patch = await client.put(f"/api/v1/stock/items/{item_id}", json=update_payload, headers=headers)
    assert resp_patch.status_code == 200
    assert resp_patch.json()["technical_specs"]["rendimento"] == "1200 páginas"
