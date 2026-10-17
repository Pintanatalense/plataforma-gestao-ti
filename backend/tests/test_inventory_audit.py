import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.inventory_audit.models import InventoryAudit


@pytest.mark.asyncio
async def test_create_inventory_audit(
    client: AsyncClient, db_session: AsyncSession
):
    from tests.conftest import make_auth_headers
    # Precisamos de um unit e user
    from app.organization.models import Unit, Company
    from app.identity.models import UserAccount
    import uuid
    
    company = Company(name="Test Company")
    db_session.add(company)
    await db_session.flush()

    # Criar uma Unit para o teste (ou usar a existente no DB seed)
    unit = Unit(name=f"Unit {uuid.uuid4()}", code=f"c{uuid.uuid4().hex[:8]}", type="FILIAL", company_id=company.id)
    db_session.add(unit)
    await db_session.flush()

    # Criar user
    user = UserAccount(email=f"auditor{uuid.uuid4()}@test.com", hashed_password="hash", is_admin=True)
    db_session.add(user)
    await db_session.flush()

    payload = {
        "name": "Inventário Geral",
        "unit_id": str(unit.id),
        "auditor_id": str(user.id)
    }

    admin_token_headers = make_auth_headers(user_id=str(user.id), is_admin=True)

    response = await client.post(
        "/api/v1/inventory",
        json=payload,
        headers=admin_token_headers
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["name"] == "Inventário Geral"
    assert data["status"] == "OPENED"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_and_update_inventory_audit(
    client: AsyncClient, db_session: AsyncSession
):
    from tests.conftest import make_auth_headers
    from app.organization.models import Unit, Company
    from app.identity.models import UserAccount
    import uuid
    
    company = Company(name="Test Company")
    db_session.add(company)
    await db_session.flush()

    unit = Unit(name=f"Unit {uuid.uuid4()}", code=f"c{uuid.uuid4().hex[:8]}", type="FILIAL", company_id=company.id)
    db_session.add(unit)
    await db_session.flush()

    user = UserAccount(email=f"auditor2{uuid.uuid4()}@test.com", hashed_password="hash", is_admin=True)
    db_session.add(user)
    await db_session.flush()

    # Cria direto no banco
    audit = InventoryAudit(
        name="Inventário Teste",
        unit_id=unit.id,
        auditor_id=user.id,
        status="OPENED"
    )
    db_session.add(audit)
    await db_session.commit()
    await db_session.refresh(audit)

    # Lista
    admin_token_headers = make_auth_headers(user_id=str(user.id), is_admin=True)
    response = await client.get("/api/v1/inventory", headers=admin_token_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    
    # Atualiza
    update_payload = {
        "status": "IN_PROGRESS"
    }
    resp_update = await client.patch(
        f"/api/v1/inventory/{audit.id}",
        json=update_payload,
        headers=admin_token_headers
    )
    assert resp_update.status_code == 200
    data_up = resp_update.json()
    assert data_up["status"] == "IN_PROGRESS"
    assert data_up["start_date"] is not None  # start_date deve ser setado automaticamente
