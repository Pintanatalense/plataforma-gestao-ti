"""
Regressões da auditoria: quem tem só identity.users.* / identity.roles.* não pode virar admin,
assumir contas de admin, conceder o que não tem nem deixar o sistema sem administrador.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.identity.models import Permission, Role, UserAccount
from tests.factories import headers_for

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/identity"
MANAGER_PERMS = ("identity.users.create", "identity.users.update", "identity.roles.create", "identity.roles.update")


async def _permission(db: AsyncSession, code: str) -> Permission:
    perm = Permission(code=code)
    db.add(perm)
    await db.commit()
    return perm


async def _role(db: AsyncSession, name: str, *codes: str) -> Role:
    role = Role(name=name)
    role.permissions = [await _permission(db, c) for c in codes]
    db.add(role)
    await db.commit()
    return role


async def _user(db: AsyncSession, label: str, *, is_admin: bool = False, roles: tuple[Role, ...] = ()) -> UserAccount:
    user = UserAccount(
        email=f"{label}-{uuid.uuid4().hex[:6]}@test.local", hashed_password=hash_password("senha-forte-1"), is_admin=is_admin
    )
    user.roles = list(roles)
    db.add(user)
    await db.commit()
    return user


def _as(user: UserAccount, *perms: str, is_admin: bool | None = None) -> dict[str, str]:
    return headers_for(user, *perms, is_admin=is_admin)


NEW_USER = {"email": "novo@example.com", "password": "senha-forte-1", "must_change_password": True}


# ----------------------------------------------------------------------------- criação de usuários


async def test_non_admin_cannot_create_an_admin(client: AsyncClient, db_session: AsyncSession):
    manager = await _user(db_session, "manager")
    resp = await client.post(f"{BASE}/users", json={**NEW_USER, "is_admin": True}, headers=_as(manager, *MANAGER_PERMS))
    assert resp.status_code == 403


async def test_admin_can_create_an_admin(client: AsyncClient, db_session: AsyncSession):
    admin = await _user(db_session, "admin", is_admin=True)
    resp = await client.post(f"{BASE}/users", json={**NEW_USER, "is_admin": True}, headers=_as(admin))
    assert resp.status_code == 201 and resp.json()["is_admin"] is True


async def test_non_admin_cannot_assign_a_role_with_permissions_they_lack(client: AsyncClient, db_session: AsyncSession):
    strong = await _role(db_session, "Forte", "system.backup.manage", "audit.read")
    manager = await _user(db_session, "manager")
    resp = await client.post(
        f"{BASE}/users", json={**NEW_USER, "role_ids": [str(strong.id)]}, headers=_as(manager, *MANAGER_PERMS)
    )
    assert resp.status_code == 403
    assert "system.backup.manage" in resp.json()["error"]["message"]


async def test_non_admin_can_assign_a_role_within_their_own_permissions(client: AsyncClient, db_session: AsyncSession):
    role = await _role(db_session, "Leitura", "audit.read")
    manager = await _user(db_session, "manager")
    resp = await client.post(
        f"{BASE}/users",
        json={**NEW_USER, "role_ids": [str(role.id)]},
        headers=_as(manager, *MANAGER_PERMS, "audit.read"),
    )
    assert resp.status_code == 201


# ----------------------------------------------------------------------------- alteração de usuários


async def test_non_admin_cannot_promote_themselves(client: AsyncClient, db_session: AsyncSession):
    manager = await _user(db_session, "manager")
    resp = await client.patch(f"{BASE}/users/{manager.id}", json={"is_admin": True}, headers=_as(manager, *MANAGER_PERMS))
    assert resp.status_code == 403


async def test_non_admin_cannot_escalate_via_roles_on_themselves(client: AsyncClient, db_session: AsyncSession):
    strong = await _role(db_session, "Forte", "system.backup.manage")
    manager = await _user(db_session, "manager")
    resp = await client.patch(
        f"{BASE}/users/{manager.id}", json={"role_ids": [str(strong.id)]}, headers=_as(manager, *MANAGER_PERMS)
    )
    assert resp.status_code == 403


async def test_non_admin_cannot_reset_the_password_of_an_admin(client: AsyncClient, db_session: AsyncSession):
    admin = await _user(db_session, "admin", is_admin=True)
    manager = await _user(db_session, "manager")
    resp = await client.patch(
        f"{BASE}/users/{admin.id}/password", json={"password": "troca-12345"}, headers=_as(manager, *MANAGER_PERMS)
    )
    assert resp.status_code == 403
    await db_session.refresh(admin)
    assert admin.must_change_password is False  # a conta do admin não foi tocada


@pytest.mark.parametrize("method,suffix,body", [("patch", "", {"is_active": False}), ("delete", "", None)])
async def test_non_admin_cannot_deactivate_or_delete_an_admin(
    client: AsyncClient, db_session: AsyncSession, method, suffix, body
):
    admin = await _user(db_session, "admin", is_admin=True)
    manager = await _user(db_session, "manager")
    kwargs = {"json": body} if body is not None else {}
    resp = await getattr(client, method)(f"{BASE}/users/{admin.id}{suffix}", headers=_as(manager, *MANAGER_PERMS), **kwargs)
    assert resp.status_code == 403


async def test_non_admin_cannot_manage_a_user_with_more_permissions(client: AsyncClient, db_session: AsyncSession):
    strong = await _role(db_session, "Forte", "system.backup.manage")
    boss = await _user(db_session, "boss", roles=(strong,))
    manager = await _user(db_session, "manager")
    resp = await client.patch(
        f"{BASE}/users/{boss.id}/password", json={"password": "troca-12345"}, headers=_as(manager, *MANAGER_PERMS)
    )
    assert resp.status_code == 403


async def test_non_admin_can_manage_an_ordinary_user(client: AsyncClient, db_session: AsyncSession):
    peer = await _user(db_session, "peer")
    manager = await _user(db_session, "manager")
    resp = await client.patch(
        f"{BASE}/users/{peer.id}/password", json={"password": "troca-12345"}, headers=_as(manager, *MANAGER_PERMS)
    )
    assert resp.status_code == 200


# ----------------------------------------------------------------------------- último administrador


async def test_cannot_deactivate_demote_or_delete_the_last_admin(client: AsyncClient, db_session: AsyncSession):
    admin = await _user(db_session, "admin", is_admin=True)
    headers = _as(admin)

    assert (await client.patch(f"{BASE}/users/{admin.id}", json={"is_active": False}, headers=headers)).status_code == 409
    assert (await client.patch(f"{BASE}/users/{admin.id}", json={"is_admin": False}, headers=headers)).status_code == 409
    assert (await client.delete(f"{BASE}/users/{admin.id}", headers=headers)).status_code == 409


async def test_can_remove_an_admin_when_another_active_admin_remains(client: AsyncClient, db_session: AsyncSession):
    first = await _user(db_session, "admin1", is_admin=True)
    second = await _user(db_session, "admin2", is_admin=True)

    resp = await client.patch(f"{BASE}/users/{second.id}", json={"is_admin": False}, headers=_as(first))
    assert resp.status_code == 200

    # agora `first` é o único: não pode mais ser removido
    assert (await client.delete(f"{BASE}/users/{first.id}", headers=_as(first))).status_code == 409


async def test_inactive_admin_does_not_count_as_a_remaining_admin(client: AsyncClient, db_session: AsyncSession):
    active = await _user(db_session, "admin1", is_admin=True)
    gone = await _user(db_session, "admin2", is_admin=True)
    gone.is_active = False
    await db_session.commit()

    resp = await client.delete(f"{BASE}/users/{active.id}", headers=_as(active))
    assert resp.status_code == 409


# ----------------------------------------------------------------------------- perfis


async def test_non_admin_cannot_create_a_role_with_permissions_they_lack(client: AsyncClient, db_session: AsyncSession):
    perm = await _permission(db_session, "system.backup.manage")
    manager = await _user(db_session, "manager")
    resp = await client.post(
        f"{BASE}/roles",
        json={"name": "Super", "permission_ids": [str(perm.id)]},
        headers=_as(manager, *MANAGER_PERMS),
    )
    assert resp.status_code == 403


async def test_non_admin_cannot_rewrite_or_delete_a_role_holding_more_than_they_have(
    client: AsyncClient, db_session: AsyncSession
):
    strong = await _role(db_session, "Forte", "system.backup.manage")
    manager = await _user(db_session, "manager")
    headers = _as(manager, *MANAGER_PERMS)

    assert (await client.patch(f"{BASE}/roles/{strong.id}", json={"description": "x"}, headers=headers)).status_code == 403
    assert (await client.delete(f"{BASE}/roles/{strong.id}", headers=headers)).status_code == 403


async def test_admin_can_create_any_role(client: AsyncClient, db_session: AsyncSession):
    perm = await _permission(db_session, "system.backup.manage")
    admin = await _user(db_session, "admin", is_admin=True)
    resp = await client.post(
        f"{BASE}/roles", json={"name": "Backup", "permission_ids": [str(perm.id)]}, headers=_as(admin)
    )
    assert resp.status_code == 201
