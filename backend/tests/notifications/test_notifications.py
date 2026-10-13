import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import make_auth_headers

from app.identity.models import UserAccount
from app.core.security import hash_password
from app.notifications.models import Notification

pytestmark = pytest.mark.asyncio


async def setup_test_user(db_session: AsyncSession):
    user = UserAccount(email="test_notifications@test.com", hashed_password=hash_password("123"), is_admin=False)
    db_session.add(user)
    await db_session.commit()
    return user


async def test_list_and_read_notifications(client: AsyncClient, db_session: AsyncSession):
    user = await setup_test_user(db_session)
    headers = make_auth_headers(user_id=str(user.id), is_admin=False)

    # Cria notificações diretamente no banco
    notif1 = Notification(
        user_id=user.id,
        title="Novo Chamado",
        message="Chamado #10 atribuído a você",
        type="INFO",
        is_read=False,
    )
    notif2 = Notification(
        user_id=user.id,
        title="Alerta de Estoque",
        message="Item abaixo da cota mínima",
        type="WARNING",
        is_read=False,
    )
    db_session.add_all([notif1, notif2])
    await db_session.commit()

    # 1. Listar notificações
    resp = await client.get("/api/v1/notifications", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["is_read"] is False

    # 2. Marcar uma como lida
    resp_read = await client.post(f"/api/v1/notifications/{notif1.id}/read", headers=headers)
    assert resp_read.status_code == 200
    assert resp_read.json()["is_read"] is True

    # 3. Marcar todas como lidas
    resp_read_all = await client.post("/api/v1/notifications/read-all", headers=headers)
    assert resp_read_all.status_code == 200
    assert resp_read_all.json()["message"] == "success"

    # 4. Verificar se ambas agora estão lidas
    resp_check = await client.get("/api/v1/notifications", headers=headers)
    assert resp_check.status_code == 200
    for item in resp_check.json():
        assert item["is_read"] is True
