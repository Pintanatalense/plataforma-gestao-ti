from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.security import create_access_token, hash_password
from app.identity.models import UserAccount
from tests.conftest import make_auth_headers

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/identity"
PASSWORD = "senha-forte-1"


async def _user(db: AsyncSession, email: str, **kwargs) -> UserAccount:
    user = UserAccount(email=email, hashed_password=hash_password(PASSWORD), **kwargs)
    db.add(user)
    await db.commit()
    return user


async def _login(client: AsyncClient, email: str, password: str = PASSWORD):
    return await client.post(f"{BASE}/login", data={"username": email, "password": password})


async def test_token_of_unknown_user_is_rejected(client: AsyncClient):
    forged = make_auth_headers(is_admin=True)  # sub aleatório, assinatura válida
    assert (await client.get(f"{BASE}/users", headers=forged)).status_code == 401


async def test_deactivated_user_loses_access_immediately(client: AsyncClient, db_session: AsyncSession):
    user = await _user(db_session, "ativo@test.com")
    token = (await _login(client, user.email)).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get(f"{BASE}/me", headers=headers)).status_code == 200

    user.soft_delete()
    await db_session.commit()
    assert (await client.get(f"{BASE}/me", headers=headers)).status_code == 401


async def test_admin_claim_is_ignored_when_user_is_not_admin_in_database(client: AsyncClient, db_session: AsyncSession):
    user = await _user(db_session, "comum@test.com")
    headers = make_auth_headers(str(user.id), is_admin=True)
    assert (await client.get(f"{BASE}/users", headers=headers)).status_code == 403


async def test_login_locks_after_repeated_failures(client: AsyncClient, db_session: AsyncSession):
    user = await _user(db_session, "alvo@test.com")
    for _ in range(5):
        assert (await _login(client, user.email, "errada")).status_code == 401

    locked = await _login(client, user.email)  # senha correta, mas conta bloqueada
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "ACCOUNT_LOCKED"

    await db_session.refresh(user)
    user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()
    assert (await _login(client, user.email)).status_code == 200


async def test_successful_login_resets_failure_counter(client: AsyncClient, db_session: AsyncSession):
    user = await _user(db_session, "reset@test.com")
    for _ in range(4):
        await _login(client, user.email, "errada")
    assert (await _login(client, user.email)).status_code == 200
    for _ in range(4):
        await _login(client, user.email, "errada")
    assert (await _login(client, user.email)).status_code == 200  # 4+4 não acumula


async def test_password_change_is_enforced_by_the_server(client: AsyncClient, db_session: AsyncSession):
    user = await _user(db_session, "novo@test.com", must_change_password=True)
    token = (await _login(client, user.email)).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    blocked = await client.get("/api/v1/tickets", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    assert (await client.get(f"{BASE}/me", headers=headers)).status_code == 200

    changed = await client.post(
        f"{BASE}/me/password", json={"current_password": PASSWORD, "new_password": "outra-senha-forte-2"}, headers=headers
    )
    assert changed.status_code == 200
    # ADR-016: a troca encerra as sessões antigas; o token novo, devolvido na resposta, segue valendo
    assert (await client.get(f"{BASE}/me", headers=headers)).status_code == 401
    fresh = {"Authorization": f"Bearer {changed.json()['access_token']}"}
    assert (await client.get(f"{BASE}/me", headers=fresh)).status_code == 200
    assert (await client.get("/api/v1/tickets/categories", headers=fresh)).status_code == 200


@pytest.mark.parametrize("key", ["CHANGE-ME-IN-PRODUCTION", "curta", "x" * 20, "alguma-coisa-CHANGE-ME-" + "a" * 20])
async def test_weak_secret_key_is_rejected(key: str):
    with pytest.raises(ValidationError):
        Settings(SECRET_KEY=key, _env_file=None)


async def test_strong_secret_key_is_accepted():
    assert Settings(SECRET_KEY="a" * 40, _env_file=None).SECRET_KEY == "a" * 40
    assert create_access_token({"sub": "x"})
