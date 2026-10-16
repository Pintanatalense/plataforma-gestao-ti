"""Testes de integração do MOD-03 — Identidade."""

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.identity.models import Permission, Role, UserAccount
from tests.conftest import make_auth_headers

BASE = "/api/v1/identity"


@pytest_asyncio.fixture
async def admin_h(db_session: AsyncSession) -> dict:
    """Cabeçalhos de um administrador real (o usuário do token precisa existir e estar ativo)."""
    user = UserAccount(email="root@test.com", hashed_password=hash_password("senha-forte-1"), is_admin=True)
    db_session.add(user)
    await db_session.commit()
    return make_auth_headers(str(user.id), is_admin=True)


async def _seed_permissions(db: AsyncSession, *codes: str) -> list[Permission]:
    permissions = [Permission(code=code, description=code) for code in codes]
    db.add_all(permissions)
    await db.commit()
    return permissions


async def _seed_user(db: AsyncSession, email: str = "user@test.com", password: str = "senha-forte-1") -> UserAccount:
    permission = Permission(code="organization.units.read")
    role = Role(name="Técnico", permissions=[permission])
    user = UserAccount(email=email, hashed_password=hash_password(password), roles=[role])
    db.add(user)
    await db.commit()
    return user


async def _login(client: AsyncClient, email: str, password: str):
    return await client.post(f"{BASE}/login", data={"username": email, "password": password})


# ------------------------------------------------------------------------------
# Setup inicial (primeiro acesso)
# ------------------------------------------------------------------------------


async def test_setup_status_required_on_empty_database(client: AsyncClient) -> None:
    response = await client.get(f"{BASE}/setup/status")
    assert response.status_code == 200, response.text
    assert response.json() == {"setup_required": True}


async def test_setup_creates_first_admin_and_logs_in(client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed_permissions(db_session, "a.read", "b.read")
    db_session.add(Role(name="Administrador"))
    await db_session.commit()

    response = await client.post(f"{BASE}/setup", json={"email": "ti@empresa.com", "password": "senha-forte-1"})
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]

    me = await client.get(f"{BASE}/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["email"] == "ti@empresa.com"
    assert body["is_admin"] is True
    assert body["must_change_password"] is False
    assert [r["name"] for r in body["roles"]] == ["Administrador"]

    assert (await client.get(f"{BASE}/setup/status")).json() == {"setup_required": False}
    assert (await _login(client, "ti@empresa.com", "senha-forte-1")).status_code == 200


async def test_setup_creates_admin_role_when_seed_missing(client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed_permissions(db_session, "a.read")
    response = await client.post(f"{BASE}/setup", json={"email": "ti@empresa.com", "password": "senha-forte-1"})
    assert response.status_code == 201, response.text

    token = response.json()["access_token"]
    roles = (await client.get(f"{BASE}/roles", headers={"Authorization": f"Bearer {token}"})).json()
    assert roles[0]["name"] == "Administrador"
    assert [p["code"] for p in roles[0]["permissions"]] == ["a.read"]


async def test_setup_blocked_after_first_user(client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed_user(db_session)
    response = await client.post(f"{BASE}/setup", json={"email": "invasor@x.com", "password": "senha-forte-1"})
    assert response.status_code == 409
    assert (await _login(client, "invasor@x.com", "senha-forte-1")).status_code == 401


async def test_setup_rejects_short_password(client: AsyncClient) -> None:
    response = await client.post(f"{BASE}/setup", json={"email": "ti@empresa.com", "password": "curta"})
    assert response.status_code == 422


# ------------------------------------------------------------------------------
# Autenticação
# ------------------------------------------------------------------------------


async def test_login_success_returns_token_with_permissions(client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed_user(db_session)
    response = await _login(client, "user@test.com", "senha-forte-1")
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]

    me = await client.get(f"{BASE}/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["email"] == "user@test.com"
    assert body["roles"][0]["permissions"][0]["code"] == "organization.units.read"


async def test_login_wrong_password(client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed_user(db_session)
    response = await _login(client, "user@test.com", "errada")
    assert response.status_code == 401


async def test_login_inactive_user_is_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await _seed_user(db_session)
    user.soft_delete()
    await db_session.commit()
    response = await _login(client, "user@test.com", "senha-forte-1")
    assert response.status_code == 401


async def test_invalid_token_returns_401(client: AsyncClient) -> None:
    response = await client.get(f"{BASE}/me", headers={"Authorization": "Bearer invalido"})
    assert response.status_code == 401


async def test_change_own_password(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await _seed_user(db_session)
    headers = make_auth_headers(str(user.id))

    response = await client.post(
        f"{BASE}/me/password",
        json={"current_password": "senha-forte-1", "new_password": "nova-senha-123"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["must_change_password"] is False

    assert (await _login(client, "user@test.com", "nova-senha-123")).status_code == 200
    assert (await _login(client, "user@test.com", "senha-forte-1")).status_code == 401


async def test_change_own_password_requires_current_password(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await _seed_user(db_session)
    response = await client.post(
        f"{BASE}/me/password",
        json={"current_password": "errada", "new_password": "nova-senha-123"},
        headers=make_auth_headers(str(user.id)),
    )
    assert response.status_code == 400


# ------------------------------------------------------------------------------
# Permissões e perfis
# ------------------------------------------------------------------------------


async def test_list_permissions(client: AsyncClient, db_session: AsyncSession, admin_h: dict) -> None:
    await _seed_permissions(db_session, "b.read", "a.read")
    response = await client.get(f"{BASE}/permissions", headers=admin_h)
    assert response.status_code == 200, response.text
    assert [p["code"] for p in response.json()] == ["a.read", "b.read"]


async def test_role_crud(client: AsyncClient, db_session: AsyncSession, admin_h: dict) -> None:
    perm_a, perm_b = await _seed_permissions(db_session, "a.read", "b.read")

    response = await client.post(
        f"{BASE}/roles", json={"name": "Gestor", "permission_ids": [str(perm_a.id)]}, headers=admin_h
    )
    assert response.status_code == 201, response.text
    role = response.json()
    assert [p["code"] for p in role["permissions"]] == ["a.read"]

    response = await client.patch(
        f"{BASE}/roles/{role['id']}", json={"permission_ids": [str(perm_b.id)]}, headers=admin_h
    )
    assert response.status_code == 200, response.text
    assert [p["code"] for p in response.json()["permissions"]] == ["b.read"]


async def test_duplicate_role_name_returns_409(client: AsyncClient, admin_h: dict) -> None:
    await client.post(f"{BASE}/roles", json={"name": "Gestor"}, headers=admin_h)
    response = await client.post(f"{BASE}/roles", json={"name": "Gestor"}, headers=admin_h)
    assert response.status_code == 409


async def test_get_unknown_role_returns_404(client: AsyncClient, admin_h: dict) -> None:
    response = await client.get(f"{BASE}/roles/00000000-0000-0000-0000-000000000000", headers=admin_h)
    assert response.status_code == 404


# ------------------------------------------------------------------------------
# Usuários
# ------------------------------------------------------------------------------


async def test_user_crud(client: AsyncClient, db_session: AsyncSession, admin_h: dict) -> None:
    (perm,) = await _seed_permissions(db_session, "a.read")
    role = (await client.post(f"{BASE}/roles", json={"name": "Gestor", "permission_ids": [str(perm.id)]}, headers=admin_h)).json()

    response = await client.post(
        f"{BASE}/users",
        json={"email": "novo@test.com", "password": "senha-forte-1", "role_ids": [role["id"]]},
        headers=admin_h,
    )
    assert response.status_code == 201, response.text
    user = response.json()
    assert user["must_change_password"] is True
    assert user["roles"][0]["name"] == "Gestor"

    response = await client.get(f"{BASE}/users", headers=admin_h)
    assert response.status_code == 200, response.text
    assert [u["email"] for u in response.json() if u["email"] != "root@test.com"] == ["novo@test.com"]

    response = await client.patch(f"{BASE}/users/{user['id']}", json={"role_ids": []}, headers=admin_h)
    assert response.status_code == 200, response.text
    assert response.json()["roles"] == []


async def test_duplicate_email_returns_409(client: AsyncClient, admin_h: dict) -> None:
    payload = {"email": "dup@test.com", "password": "senha-forte-1"}
    await client.post(f"{BASE}/users", json=payload, headers=admin_h)
    response = await client.post(f"{BASE}/users", json=payload, headers=admin_h)
    assert response.status_code == 409


async def test_admin_reset_password_forces_change(client: AsyncClient, db_session: AsyncSession, admin_h: dict) -> None:
    user = await _seed_user(db_session)
    user.must_change_password = False
    await db_session.commit()

    response = await client.patch(
        f"{BASE}/users/{user.id}/password", json={"password": "temporaria-1"}, headers=admin_h
    )
    assert response.status_code == 200, response.text
    assert response.json()["must_change_password"] is True
