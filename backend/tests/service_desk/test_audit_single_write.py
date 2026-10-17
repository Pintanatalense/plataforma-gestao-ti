import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.listener import setup_audit_listener
from app.audit.models import AuditLog
from tests.factories import headers_for, make_employee, make_org, make_ticket_category, make_user

pytestmark = pytest.mark.asyncio


async def test_ticket_created_is_audited_exactly_once(client: AsyncClient, db_session: AsyncSession):
    setup_audit_listener()  # o lifespan real registra o listener global; os testes não executam o lifespan
    org = await make_org(db_session)
    cat = await make_ticket_category(db_session, org.sector)
    emp = await make_employee(db_session, org)
    user = await make_user(db_session, emp)
    h = headers_for(user)

    resp = await client.post(
        "/api/v1/tickets", json={"title": "Sem rede", "description": "d", "priority": "LOW", "category_id": str(cat.id)},
        headers=h,
    )
    assert resp.status_code == 201
    ticket_id = resp.json()["id"]

    count = (
        await db_session.execute(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.event_type == "ticket.created", AuditLog.entity_id == __import__("uuid").UUID(ticket_id)
            )
        )
    ).scalar_one()
    assert count == 1

    history = (await client.get(f"/api/v1/tickets/{ticket_id}/history", headers=h)).json()
    assert [e["event_type"] for e in history].count("ticket.created") == 1
