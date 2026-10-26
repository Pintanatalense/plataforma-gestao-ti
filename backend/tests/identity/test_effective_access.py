"""Acesso efetivo (Plano de Evolução, Fase 0 PR 8): o que a conta pode e por quê, pela mesma regra da autorização."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.critical import CriticalGrantService
from app.identity.models import Permission, Role, user_role_association
from app.identity.permission_catalog import CATALOG, sync_permission_catalog
from tests.factories import headers_for, make_user

pytestmark = pytest.mark.asyncio


async def _get(client, user, viewer):
    resp = await client.get(f"/api/v1/identity/users/{user.id}/effective-access", headers=headers_for(viewer, "identity.users.read"))
    assert resp.status_code == 200, resp.text
    return {p["code"]: p for p in resp.json()}


async def test_effective_access_lists_role_permissions_with_their_source(client: AsyncClient, db_session: AsyncSession):
    await sync_permission_catalog(db_session)
    perm = (await db_session.execute(select(Permission).where(Permission.code == "assets.read"))).scalar_one()
    user = await make_user(db_session)
    role = Role(name="Leitura de ativos", permissions=[perm])
    db_session.add(role)
    await db_session.flush()
    await db_session.execute(user_role_association.insert().values(user_id=user.id, role_id=role.id))
    await db_session.commit()

    access = await _get(client, user, await make_user(db_session))
    assert set(access) == {"assets.read"}
    assert access["assets.read"]["sources"] == ["Perfil Leitura de ativos"]
    assert access["assets.read"]["module_label"] == "Patrimônio e ativos"
    assert access["assets.read"]["risk_label"] == "Leitura"


async def test_admin_has_every_common_permission_and_criticals_only_when_granted(
    client: AsyncClient, db_session: AsyncSession
):
    await sync_permission_catalog(db_session)
    admin = await make_user(db_session, is_admin=True)
    await CriticalGrantService(db_session).grant(admin.id, "system.backup.download", via="cli", reason="teste")
    await db_session.commit()

    access = await _get(client, admin, await make_user(db_session))
    common = {spec.code for spec in CATALOG if not spec.critical}
    assert common <= set(access)
    assert access["audit.read"]["sources"] == ["Administrador"]
    assert access["system.backup.download"]["sources"] == ["Concessão individual"]
    assert "system.backup.manage" not in access


async def test_effective_access_requires_users_read(client: AsyncClient, db_session: AsyncSession):
    user = await make_user(db_session)
    resp = await client.get(f"/api/v1/identity/users/{user.id}/effective-access", headers=headers_for(user))
    assert resp.status_code == 403


async def test_permissions_listing_brings_portuguese_module_and_risk_labels(client: AsyncClient, db_session: AsyncSession):
    await sync_permission_catalog(db_session)
    await db_session.commit()
    viewer = await make_user(db_session)
    resp = await client.get("/api/v1/identity/permissions", headers=headers_for(viewer, "identity.roles.read"))
    item = next(p for p in resp.json() if p["code"] == "system.data.import")
    assert (item["module_label"], item["risk_label"], item["is_critical"]) == ("Sistema, dados e backups", "Execução", True)
