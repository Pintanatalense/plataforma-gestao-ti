"""
ADR-016: tokens carregam a versão da sessão (`tv`) e deixam de valer quando ela muda.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.identity.models import Permission, Role, UserAccount
from tests.factories import headers_for

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/identity"
PASSWORD = "senha-forte-1"


async def _user(db: AsyncSession, label: str, roles: tuple[Role, ...] = (), **kwargs) -> UserAccount:
    user = UserAccount(
        email=f"{label}-{uuid.uuid4().hex[:6]}@test.com", hashed_password=hash_password(PASSWORD), **kwargs
    )
    user.roles = list(roles)
    db.add(user)
    await db.commit()
    return user


async def _login_headers(client: AsyncClient, user: UserAccount) -> dict[str, str]:
    resp = await client.post(f"{BASE}/login", data={"username": user.email, "password": PASSWORD})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _me(client: AsyncClient, headers: dict[str, str]) -> int:
    return (await client.get(f"{BASE}/me", headers=headers)).status_code


async def test_login_token_carries_the_session_version(db_session: AsyncSession, client: AsyncClient):
    from app.core.security import decode_access_token

    user = await _user(db_session, "v")
    user.token_version = 7
    await db_session.commit()
    token = (await _login_headers(client, user))["Authorization"].removeprefix("Bearer ")
    assert decode_access_token(token)["tv"] == 7


async def test_token_without_version_claim_is_valid_for_version_zero(client: AsyncClient, db_session: AsyncSession):
    """Tokens emitidos antes do ADR-016 não têm `tv`: valem enquanto o usuário estiver na versão 0."""
    user = await _user(db_session, "legacy")
    old = {"Authorization": f"Bearer {create_access_token({'sub': str(user.id), 'permissions': []})}"}
    assert await _me(client, old) == 200

    user.token_version = 1
    await db_session.commit()
    assert await _me(client, old) == 401


async def test_own_password_change_ends_other_sessions_and_keeps_the_current_one(
    client: AsyncClient, db_session: AsyncSession
):
    user = await _user(db_session, "own")
    laptop = await _login_headers(client, user)
    phone = await _login_headers(client, user)

    resp = await client.post(
        f"{BASE}/me/password", json={"current_password": PASSWORD, "new_password": "nova-senha-forte-2"}, headers=laptop
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == user.email  # os campos do usuário continuam na resposta

    assert await _me(client, laptop) == 401
    assert await _me(client, phone) == 401
    assert await _me(client, {"Authorization": f"Bearer {resp.json()['access_token']}"}) == 200


async def test_admin_password_reset_ends_the_user_sessions_and_clears_lockout(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user(db_session, "admin", is_admin=True)
    victim = await _user(db_session, "victim")
    session = await _login_headers(client, victim)
    victim.failed_login_count = 3
    victim.locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
    await db_session.commit()

    resp = await client.patch(
        f"{BASE}/users/{victim.id}/password", json={"password": "temporaria-123"}, headers=headers_for(admin)
    )
    assert resp.status_code == 200

    assert await _me(client, session) == 401
    await db_session.refresh(victim)
    assert victim.locked_until is None and victim.failed_login_count == 0
    # a senha temporária já funciona (sem esperar o fim do bloqueio)
    login = await client.post(f"{BASE}/login", data={"username": victim.email, "password": "temporaria-123"})
    assert login.status_code == 200


async def test_deactivating_a_user_ends_the_session(client: AsyncClient, db_session: AsyncSession):
    admin = await _user(db_session, "admin", is_admin=True)
    target = await _user(db_session, "target")
    session = await _login_headers(client, target)

    assert (
        await client.patch(f"{BASE}/users/{target.id}", json={"is_active": False}, headers=headers_for(admin))
    ).status_code == 200
    assert await _me(client, session) == 401


async def test_changing_roles_or_admin_flag_ends_the_session(client: AsyncClient, db_session: AsyncSession):
    admin = await _user(db_session, "admin", is_admin=True)
    role = Role(name=f"R-{uuid.uuid4().hex[:6]}")
    db_session.add(role)
    await db_session.commit()

    target = await _user(db_session, "target")
    session = await _login_headers(client, target)
    await client.patch(f"{BASE}/users/{target.id}", json={"role_ids": [str(role.id)]}, headers=headers_for(admin))
    assert await _me(client, session) == 401

    session = await _login_headers(client, target)
    await client.patch(f"{BASE}/users/{target.id}", json={"is_admin": True}, headers=headers_for(admin))
    assert await _me(client, session) == 401


async def test_unchanged_roles_do_not_end_the_session(client: AsyncClient, db_session: AsyncSession):
    admin = await _user(db_session, "admin", is_admin=True)
    target = await _user(db_session, "target")
    session = await _login_headers(client, target)

    resp = await client.patch(
        f"{BASE}/users/{target.id}", json={"role_ids": [], "is_admin": False, "is_active": True}, headers=headers_for(admin)
    )
    assert resp.status_code == 200
    assert await _me(client, session) == 200


async def test_editing_role_permissions_ends_sessions_of_its_users_only(client: AsyncClient, db_session: AsyncSession):
    admin = await _user(db_session, "admin", is_admin=True)
    perm = Permission(code=f"x.y.{uuid.uuid4().hex[:6]}")
    role = Role(name=f"R-{uuid.uuid4().hex[:6]}")
    db_session.add_all([perm, role])
    await db_session.commit()

    member = await _user(db_session, "member", roles=(role,))
    outsider = await _user(db_session, "outsider")
    member_session = await _login_headers(client, member)
    outsider_session = await _login_headers(client, outsider)

    resp = await client.patch(
        f"{BASE}/roles/{role.id}", json={"permission_ids": [str(perm.id)]}, headers=headers_for(admin)
    )
    assert resp.status_code == 200

    assert await _me(client, member_session) == 401
    assert await _me(client, outsider_session) == 200


async def test_deleting_a_role_ends_sessions_of_its_users(client: AsyncClient, db_session: AsyncSession):
    admin = await _user(db_session, "admin", is_admin=True)
    role = Role(name=f"R-{uuid.uuid4().hex[:6]}")
    db_session.add(role)
    await db_session.commit()
    member = await _user(db_session, "member", roles=(role,))
    session = await _login_headers(client, member)

    assert (await client.delete(f"{BASE}/roles/{role.id}", headers=headers_for(admin))).status_code == 204
    assert await _me(client, session) == 401
