import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import make_auth_headers

from app.audit.models import AuditLog
from app.core.security import hash_password
from app.identity.models import UserAccount

pytestmark = pytest.mark.asyncio


async def test_list_audit_logs(client: AsyncClient, db_session: AsyncSession):
    admin_user = UserAccount(email="admin_audit@test.com", hashed_password=hash_password("123"), is_admin=True)
    db_session.add(admin_user)
    await db_session.commit()

    entity_id = uuid.uuid4()
    log1 = AuditLog(
        event_type="asset.created",
        entity_type="ASSET",
        entity_id=entity_id,
        user_id=admin_user.id,
        data={"name": "Notebook Dell", "tag": "PAT-001"},
    )
    log2 = AuditLog(
        event_type="ticket.updated",
        entity_type="TICKET",
        entity_id=uuid.uuid4(),
        user_id=admin_user.id,
        data={"status": "IN_PROGRESS"},
    )
    db_session.add_all([log1, log2])
    await db_session.commit()

    headers = make_auth_headers(user_id=str(admin_user.id), is_admin=True)

    # 1. Listar todos os logs (admin)
    resp = await client.get("/api/v1/audit", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2

    # 2. Filtrar por entidade
    resp_entity = await client.get(f"/api/v1/audit/ASSET/{entity_id}", headers=headers)
    assert resp_entity.status_code == 200
    entity_data = resp_entity.json()
    assert len(entity_data) == 1
    assert entity_data[0]["entity_type"] == "ASSET"
    assert entity_data[0]["event_type"] == "asset.created"
