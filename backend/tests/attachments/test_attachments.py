import io
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import make_auth_headers

from app.core.security import hash_password
from app.identity.models import UserAccount

pytestmark = pytest.mark.asyncio


async def test_upload_list_and_delete_attachment(client: AsyncClient, db_session: AsyncSession):
    user = UserAccount(email="test_attach@test.com", hashed_password=hash_password("123"), is_admin=True)
    db_session.add(user)
    await db_session.commit()

    headers = make_auth_headers(user_id=str(user.id), is_admin=True)
    entity_id = str(uuid.uuid4())

    file_content = b"Teste de conteudo do anexo"
    files = {"file": ("manual.txt", io.BytesIO(file_content), "text/plain")}
    data = {"entity_type": "ASSET", "entity_id": entity_id}

    # 1. Upload
    resp_upload = await client.post("/api/v1/attachments", files=files, data=data, headers=headers)
    assert resp_upload.status_code == 201
    attach_data = resp_upload.json()
    assert attach_data["filename"] == "manual.txt"
    assert attach_data["entity_type"] == "ASSET"
    attachment_id = attach_data["id"]

    # 2. List
    resp_list = await client.get(
        f"/api/v1/attachments?entity_type=ASSET&entity_id={entity_id}",
        headers=headers,
    )
    assert resp_list.status_code == 200
    list_data = resp_list.json()
    assert len(list_data) == 1
    assert list_data[0]["id"] == attachment_id

    # 3. Download
    resp_down = await client.get(f"/api/v1/attachments/{attachment_id}/download", headers=headers)
    assert resp_down.status_code == 200
    assert resp_down.content == file_content

    # 4. Delete
    resp_del = await client.delete(f"/api/v1/attachments/{attachment_id}", headers=headers)
    assert resp_del.status_code == 204

    # 5. List after delete
    resp_list_after = await client.get(
        f"/api/v1/attachments?entity_type=ASSET&entity_id={entity_id}",
        headers=headers,
    )
    assert resp_list_after.status_code == 200
    assert len(resp_list_after.json()) == 0
