"""
MOD-12: a trilha registra os eventos de identidade/empresa (login, usuários, perfis, senhas) sem segredos,
e a listagem tem filtros, total e teto de página.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.core.security import hash_password
from app.identity.models import UserAccount
from app.organization.models import Company
from tests.factories import headers_for, make_user

pytestmark = pytest.mark.asyncio

ID = "/api/v1/identity"
PASSWORD = "senha-forte-1"


async def _events(db: AsyncSession, event_type: str | None = None) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.created_at)
    if event_type:
        stmt = stmt.where(AuditLog.event_type == event_type)
    return list((await db.execute(stmt)).scalars().all())


async def _account(db: AsyncSession, email: str, **kw) -> UserAccount:
    user = UserAccount(email=email, hashed_password=hash_password(PASSWORD), **kw)
    db.add(user)
    await db.commit()
    return user


async def _admin(db: AsyncSession) -> tuple[UserAccount, dict]:
    admin = await make_user(db, is_admin=True)
    return admin, headers_for(admin, "audit.read")


async def test_login_success_and_failure_are_audited_without_secrets(client: AsyncClient, db_session: AsyncSession):
    user = await _account(db_session, "ana@test.com")
    assert (await client.post(f"{ID}/login", data={"username": user.email, "password": "errada-123"})).status_code == 401
    assert (await client.post(f"{ID}/login", data={"username": "ninguem@test.com", "password": "segredo-digitado"})).status_code == 401
    assert (await client.post(f"{ID}/login", data={"username": user.email, "password": PASSWORD})).status_code == 200

    kinds = [e.event_type for e in await _events(db_session)]
    assert kinds == ["identity.login_failed", "identity.login_failed", "identity.login_success"]
    dump = " ".join(str(e.data) for e in await _events(db_session))
    assert "errada-123" not in dump and "segredo-digitado" not in dump and "ninguem@test.com" not in dump
    failed_known, failed_unknown, ok = await _events(db_session)
    assert failed_known.user_id == user.id and failed_known.data["known_account"] is True
    assert failed_unknown.user_id is None and failed_unknown.data["known_account"] is False
    assert ok.user_id == user.id


async def test_lockout_attempts_are_audited(client: AsyncClient, db_session: AsyncSession):
    user = await _account(db_session, "bloq@test.com")
    for _ in range(5):
        await client.post(f"{ID}/login", data={"username": user.email, "password": "errada-123"})
    blocked = await client.post(f"{ID}/login", data={"username": user.email, "password": PASSWORD})
    assert blocked.status_code == 429
    assert [e.event_type for e in await _events(db_session, "identity.login_blocked")] == ["identity.login_blocked"]
    assert (await _events(db_session, "identity.login_failed"))[-1].data["locked_now"] is True


async def test_user_and_role_changes_are_audited_with_the_actor(client: AsyncClient, db_session: AsyncSession):
    admin = await make_user(db_session, is_admin=True)
    h = headers_for(admin, "identity.users.create", "identity.users.update", "identity.users.delete", "identity.roles.create", "identity.roles.update", "identity.roles.delete")

    role = (await client.post(f"{ID}/roles", json={"name": "Auditores", "description": "x", "permission_ids": []}, headers=h)).json()
    created = await client.post(
        f"{ID}/users", json={"email": "novo@test.com", "password": PASSWORD, "role_ids": [role["id"]]}, headers=h
    )
    assert created.status_code == 201
    uid = created.json()["id"]
    assert (await client.patch(f"{ID}/users/{uid}", json={"email": "novo2@test.com", "is_admin": False}, headers=h)).status_code == 200
    assert (await client.patch(f"{ID}/users/{uid}/password", json={"password": "outra-senha-9"}, headers=h)).status_code == 200
    assert (await client.patch(f"{ID}/roles/{role['id']}", json={"description": "y"}, headers=h)).status_code == 200
    assert (await client.delete(f"{ID}/users/{uid}", headers=h)).status_code in (200, 204)
    assert (await client.delete(f"{ID}/roles/{role['id']}", headers=h)).status_code in (200, 204)

    kinds = [e.event_type for e in await _events(db_session)]
    assert kinds == [
        "identity.role_created", "identity.user_created", "identity.user_updated",
        "identity.password_reset_by_admin", "identity.role_updated", "identity.user_deactivated", "identity.role_deleted",
    ]
    assert all(e.user_id == admin.id for e in await _events(db_session))
    updated = (await _events(db_session, "identity.user_updated"))[0]
    assert updated.data == {"changed": ["email"]}  # is_admin enviado igual ao atual não conta como mudança
    dump = " ".join(str(e.data) for e in await _events(db_session))
    assert "outra-senha-9" not in dump and PASSWORD not in dump


async def test_own_password_change_is_audited(client: AsyncClient, db_session: AsyncSession):
    user = await _account(db_session, "troca@test.com")
    login = (await client.post(f"{ID}/login", data={"username": user.email, "password": PASSWORD})).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    resp = await client.post(f"{ID}/me/password", json={"current_password": PASSWORD, "new_password": "nova-senha-77"}, headers=headers)
    assert resp.status_code == 200
    events = await _events(db_session, "identity.password_changed")
    assert len(events) == 1 and events[0].user_id == user.id
    assert "nova-senha-77" not in str(events[0].data)


async def test_company_changes_are_audited_by_field_name_only(client: AsyncClient, db_session: AsyncSession):
    admin = await make_user(db_session, is_admin=True)
    db_session.add(Company(name="Acme", cnpj="11.111.111/0001-11"))
    await db_session.commit()
    h = headers_for(admin, "organization.company.update")
    assert (await client.patch("/api/v1/organization/company", json={"cnpj": "22.222.222/0001-22"}, headers=h)).status_code == 200
    event = (await _events(db_session, "organization.company_updated"))[0]
    assert event.data == {"changed": ["cnpj"]} and event.user_id == admin.id
    assert "22.222.222" not in str(event.data)


async def test_list_has_user_fields_total_and_filters(client: AsyncClient, db_session: AsyncSession):
    admin, h = await _admin(db_session)
    other = await _account(db_session, "pedro.souza@test.com")
    now = datetime.now(timezone.utc)
    for i in range(5):
        db_session.add(AuditLog(event_type="a.evento", entity_type="X", entity_id=uuid.uuid4(), data={}, user_id=admin.id, created_at=now - timedelta(days=i)))
    db_session.add(AuditLog(event_type="b.evento", entity_type="Y", entity_id=uuid.uuid4(), data={}, user_id=other.id, created_at=now))
    await db_session.commit()

    page = await client.get("/api/v1/audit?limit=2&offset=0", headers=h)
    assert page.status_code == 200 and len(page.json()) == 2
    assert page.headers["X-Total-Count"] == "6"
    assert {"user_email", "user_name"} <= set(page.json()[0])

    by_event = await client.get("/api/v1/audit?event_type=b.evento", headers=h)
    assert [r["user_email"] for r in by_event.json()] == ["pedro.souza@test.com"]
    assert by_event.headers["X-Total-Count"] == "1"

    by_user = await client.get("/api/v1/audit?user=souza", headers=h)
    assert by_user.headers["X-Total-Count"] == "1"
    wildcard = await client.get("/api/v1/audit?user=%25", headers=h)  # "%" digitado não vira curinga
    assert wildcard.headers["X-Total-Count"] == "0"

    since = (now - timedelta(days=1, hours=1)).isoformat()
    by_date = await client.get("/api/v1/audit", params={"date_from": since, "event_type": "a.evento"}, headers=h)
    assert by_date.headers["X-Total-Count"] == "2"


async def test_page_size_is_capped_and_event_types_listed(client: AsyncClient, db_session: AsyncSession):
    admin, h = await _admin(db_session)
    db_session.add(AuditLog(event_type="z.evento", entity_type="X", entity_id=uuid.uuid4(), data={}, user_id=None))
    await db_session.commit()
    assert (await client.get("/api/v1/audit?limit=100000", headers=h)).status_code == 422
    assert (await client.get("/api/v1/audit?limit=0", headers=h)).status_code == 422
    assert "z.evento" in (await client.get("/api/v1/audit/event-types", headers=h)).json()


async def test_audit_endpoints_require_the_permission(client: AsyncClient, db_session: AsyncSession):
    user = await make_user(db_session)
    h = headers_for(user)
    assert (await client.get("/api/v1/audit", headers=h)).status_code == 403
    assert (await client.get("/api/v1/audit/event-types", headers=h)).status_code == 403
