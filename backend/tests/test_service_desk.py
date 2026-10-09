import pytest
from uuid import uuid4
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.organization.models import Employee, Company, Unit, Sector
from app.identity.models import UserAccount, Role, Permission
from app.service_desk.models import TicketCategory
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

    user = UserAccount(email="test@test.com", hashed_password=hash_password("123"), employee_id=employee.id)
    db_session.add(user)
    await db_session.commit()
    
    technician_employee = Employee(name="Tech User", registration_number="456", unit_id=unit.id, sector_id=dept.id)
    db_session.add(technician_employee)
    await db_session.commit()

    tech_user = UserAccount(email="tech@test.com", hashed_password=hash_password("123"), employee_id=technician_employee.id, is_admin=True)
    db_session.add(tech_user)
    await db_session.commit()

    category = TicketCategory(name="Hardware", default_sector_id=dept.id)
    db_session.add(category)
    await db_session.commit()

    return {
        "company": company,
        "unit": unit,
        "dept": dept,
        "employee": employee,
        "user": user,
        "technician_employee": technician_employee,
        "tech_user": tech_user,
        "category": category,
    }


async def test_list_categories(client: AsyncClient, db_session: AsyncSession):
    await setup_test_data(db_session)
    response = await client.get("/api/v1/tickets/categories")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Hardware"


async def test_create_ticket(client: AsyncClient, db_session: AsyncSession):
    data = await setup_test_data(db_session)
    user = data["user"]
    category = data["category"]

    headers = make_auth_headers(user_id=str(user.id), is_admin=False)
    
    payload = {
        "title": "Mouse quebrado",
        "description": "O botão esquerdo não funciona.",
        "priority": "LOW",
        "category_id": str(category.id)
    }

    response = await client.post("/api/v1/tickets", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    resp_data = response.json()
    assert resp_data["title"] == "Mouse quebrado"
    assert resp_data["status"] == "OPENED"
    assert resp_data["requester_id"] == str(user.employee_id)


async def test_ticket_interactions(client: AsyncClient, db_session: AsyncSession):
    data = await setup_test_data(db_session)
    user = data["user"]
    tech = data["tech_user"]
    category = data["category"]

    user_headers = make_auth_headers(user_id=str(user.id), is_admin=False)
    tech_headers = make_auth_headers(user_id=str(tech.id), is_admin=True)
    
    # 1. Create ticket as user
    payload = {
        "title": "Teclado não digita A",
        "description": "Ao apertar A, não sai nada.",
        "priority": "MEDIUM",
        "category_id": str(category.id)
    }
    resp = await client.post("/api/v1/tickets", json=payload, headers=user_headers)
    assert resp.status_code == 201, resp.text
    ticket_id = resp.json()["id"]

    # 2. Add public interaction as tech
    inter_payload = {
        "message": "Vamos trocar o teclado hoje à tarde.",
        "is_internal": False
    }
    resp = await client.post(f"/api/v1/tickets/{ticket_id}/interactions", json=inter_payload, headers=tech_headers)
    assert resp.status_code == 201

    # 3. Add internal interaction as tech
    internal_payload = {
        "message": "O usuário provavelmente derrubou café.",
        "is_internal": True
    }
    resp = await client.post(f"/api/v1/tickets/{ticket_id}/interactions", json=internal_payload, headers=tech_headers)
    assert resp.status_code == 201

    # 4. View ticket as user (should see 1 interaction)
    resp = await client.get(f"/api/v1/tickets/{ticket_id}", headers=user_headers)
    assert resp.status_code == 200
    interactions = resp.json()["interactions"]
    assert len(interactions) == 1
    assert interactions[0]["message"] == "Vamos trocar o teclado hoje à tarde."

    # 5. View ticket as tech (should see 2 interactions)
    resp = await client.get(f"/api/v1/tickets/{ticket_id}", headers=tech_headers)
    assert resp.status_code == 200
    interactions = resp.json()["interactions"]
    assert len(interactions) == 2
