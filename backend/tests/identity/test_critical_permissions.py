"""Permissões críticas (Plano de Evolução, Fase 0 PR 5; S5/A2): só por concessão individual, nunca por perfil ou is_admin."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.core.security import hash_password
from app.identity.critical import CriticalGrantService
from app.identity.models import Permission, Role, UserAccount, UserCriticalGrant
from app.identity.permission_catalog import CATALOG, CRITICAL_CODES, sync_permission_catalog
from app.identity.services import IdentityService
from app.notifications.models import DomainEvent
from tests.factories import headers_for, make_user

pytestmark = pytest.mark.asyncio

BACKUPS = "/api/v1/system/backups"
GRANT = "identity.critical.grant"


async def test_catalog_codes_are_unique_and_the_critical_set_is_explicit():
    codes = [spec.code for spec in CATALOG]
    assert len(codes) == len(set(codes))
    assert CRITICAL_CODES == {GRANT, "system.data.import", "system.backup.manage", "system.backup.download"}
    assert all(spec.risk in ("leitura", "alteracao", "aprovacao", "execucao", "administracao") for spec in CATALOG)


@pytest.mark.parametrize(
    "perms,expected",
    [((), 403), (("system.backup.manage",), 200)],
)
async def test_admin_needs_an_explicit_grant_for_critical_routes(
    client: AsyncClient, db_session: AsyncSession, perms, expected
):
    admin = await make_user(db_session, is_admin=True)
    assert (await client.get(BACKUPS, headers=headers_for(admin, *perms))).status_code == expected


async def test_admin_still_passes_every_non_critical_permission(client: AsyncClient, db_session: AsyncSession):
    admin = await make_user(db_session, is_admin=True)
    h = headers_for(admin)
    assert (await client.get("/api/v1/audit", headers=h)).status_code == 200
    # require_any_permission(notifications.manage | system.backup.manage): admin passa pela comum
    assert (await client.get("/api/v1/notifications/email/config", headers=h)).status_code == 200


async def test_sync_strips_critical_permissions_from_every_role(db_session: AsyncSession):
    await sync_permission_catalog(db_session)
    perms = (await db_session.execute(select(Permission))).scalars().all()
    role = Role(name="Com crítica", permissions=list(perms))
    db_session.add(role)
    await db_session.commit()

    await sync_permission_catalog(db_session)
    await db_session.commit()
    await db_session.refresh(role, ["permissions"])
    assert role.permissions and not {p.code for p in role.permissions} & CRITICAL_CODES
    labels = {p.code: (p.label, p.is_critical) for p in perms}
    assert labels["system.backup.download"] == ("Baixar backups", True)


async def test_token_ignores_critical_from_a_role_and_includes_the_individual_grant(db_session: AsyncSession):
    await sync_permission_catalog(db_session)
    manage = (await db_session.execute(select(Permission).where(Permission.code == "system.backup.manage"))).scalar_one()
    download = (await db_session.execute(select(Permission).where(Permission.code == "system.backup.download"))).scalar_one()
    role = Role(name="Perfil adulterado")
    db_session.add(role)
    await db_session.flush()
    # gravação direta no banco (o serviço recusaria)
    from app.identity.models import role_permission_association

    await db_session.execute(role_permission_association.insert().values(role_id=role.id, permission_id=manage.id))
    user = UserAccount(email="op@test.local", hashed_password=hash_password("Senha-forte-1"), roles=[role])
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserCriticalGrant(user_id=user.id, permission_id=download.id, granted_via="api"))
    await db_session.commit()

    token = await IdentityService(db_session).authenticate("op@test.local", "Senha-forte-1", "203.0.113.1")
    from app.core.security import decode_access_token

    perms = set(decode_access_token(token)["permissions"])
    assert "system.backup.download" in perms
    assert "system.backup.manage" not in perms


async def test_role_with_a_critical_permission_is_rejected(client: AsyncClient, db_session: AsyncSession):
    await sync_permission_catalog(db_session)
    await db_session.commit()
    admin = await make_user(db_session, is_admin=True)
    critical = (await db_session.execute(select(Permission).where(Permission.code == "system.data.import"))).scalar_one()
    resp = await client.post(
        "/api/v1/identity/roles",
        json={"name": "Importador", "permission_ids": [str(critical.id)]},
        headers=headers_for(admin),
    )
    assert resp.status_code == 400  # regra de negócio
    assert "críticas" in resp.json()["error"]["message"]


async def test_initial_setup_grants_every_critical_permission_with_audit(client: AsyncClient, db_session: AsyncSession):
    resp = await client.post(
        "/api/v1/identity/setup",
        json={"email": "dono@empresa.com.br", "password": "Instalador-2026-Aa1!", "setup_mode": "CLEAN"},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    assert (await client.get(BACKUPS, headers={"Authorization": f"Bearer {token}"})).status_code == 200

    me = (await client.get("/api/v1/identity/me", headers={"Authorization": f"Bearer {token}"})).json()
    assert set(me["critical_permissions"]) == CRITICAL_CODES
    events = (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "identity.critical_granted"))).scalars().all()
    assert {e.data["permission"] for e in events} == CRITICAL_CODES
    assert all(e.data["via"] == "setup" for e in events)


async def _granter(db: AsyncSession) -> UserAccount:
    await sync_permission_catalog(db)
    granter = await make_user(db, is_admin=True)
    await CriticalGrantService(db).grant(granter.id, GRANT, via="cli", reason="teste")
    await db.commit()
    return granter


async def test_grant_by_api_is_audited_and_notifies_admins(client: AsyncClient, db_session: AsyncSession):
    granter = await _granter(db_session)
    target = await make_user(db_session)
    url = f"/api/v1/identity/users/{target.id}/critical-permissions"

    resp = await client.post(
        url, json={"permission": "system.backup.download", "reason": "plantão de backup"}, headers=headers_for(granter, GRANT)
    )
    assert resp.status_code == 201, resp.text
    assert [g["permission"] for g in resp.json()] == ["system.backup.download"]

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event_type == "identity.critical_granted", AuditLog.entity_id == target.id)
        )
    ).scalar_one()
    assert audit.user_id == granter.id and audit.data["via"] == "api" and audit.data["reason"] == "plantão de backup"
    event = (
        await db_session.execute(select(DomainEvent).where(DomainEvent.event_type == "identity.critical_changed"))
    ).scalars().all()[-1]
    assert event.payload["action"] == "granted" and event.payload["target_email"] == target.email


async def test_grant_by_api_refuses_self_unknown_and_actors_without_the_grant_permission(
    client: AsyncClient, db_session: AsyncSession
):
    granter = await _granter(db_session)
    target = await make_user(db_session)
    plain_admin = await make_user(db_session, is_admin=True)
    body = {"permission": "system.backup.download", "reason": "motivo qualquer"}

    own = await client.post(f"/api/v1/identity/users/{granter.id}/critical-permissions", json=body, headers=headers_for(granter, GRANT))
    assert own.status_code == 403
    no_perm = await client.post(
        f"/api/v1/identity/users/{target.id}/critical-permissions", json=body, headers=headers_for(plain_admin)
    )
    assert no_perm.status_code == 403
    not_critical = await client.post(
        f"/api/v1/identity/users/{target.id}/critical-permissions",
        json={"permission": "audit.read", "reason": "motivo qualquer"},
        headers=headers_for(granter, GRANT),
    )
    assert not_critical.status_code == 400


async def test_revoke_ends_sessions_and_keeps_at_least_one_granter(client: AsyncClient, db_session: AsyncSession):
    granter = await _granter(db_session)
    target = await make_user(db_session)
    service = CriticalGrantService(db_session)
    await service.grant(target.id, "system.backup.manage", via="api", actor_id=granter.id, reason="teste")
    await db_session.commit()
    old_headers = headers_for(target, "system.backup.manage")
    assert (await client.get(BACKUPS, headers=old_headers)).status_code == 200

    resp = await client.request(
        "DELETE",
        f"/api/v1/identity/users/{target.id}/critical-permissions/system.backup.manage",
        json={"reason": "fim do plantão"},
        headers=headers_for(granter, GRANT),
    )
    assert resp.status_code == 200 and resp.json() == []
    assert (await client.get(BACKUPS, headers=old_headers)).status_code == 401  # token antigo deixou de valer

    other = await make_user(db_session)
    last = await client.request(
        "DELETE",
        f"/api/v1/identity/users/{granter.id}/critical-permissions/{GRANT}",
        json={"reason": "tentando ficar sem ninguém"},
        headers=headers_for(other, GRANT),
    )
    assert last.status_code == 409


async def test_cli_recovery_grants_everything_to_an_active_account(db_session: AsyncSession, monkeypatch, capsys):
    import contextlib

    from app import cli

    user = await make_user(db_session, is_admin=True)

    @contextlib.asynccontextmanager
    async def _session():
        yield db_session

    monkeypatch.setattr(cli, "AsyncSessionLocal", _session)
    assert await cli.grant_critical(user.email.upper(), "perdi o acesso") == 0
    assert await cli.grant_critical("ninguem@test.local", "x") == 1

    await db_session.refresh(user, ["critical_grants"])
    assert set(user.critical_permissions) == CRITICAL_CODES
    vias = (await db_session.execute(select(UserCriticalGrant.granted_via).where(UserCriticalGrant.user_id == user.id))).scalars()
    assert set(vias) == {"cli"}
    assert "concedida" in capsys.readouterr().out
