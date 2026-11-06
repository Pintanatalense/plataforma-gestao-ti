"""Contexto de acesso único (Plano de Evolução, Fase 0 PR 7). O comportamento das rotas é o da matriz deste pacote."""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessContext, build_access_context, load_access_context
from app.identity.models import Permission, Role, UserCriticalGrant, role_permission_association, user_role_association
from app.identity.permission_catalog import sync_permission_catalog
from tests.factories import make_employee, make_org, make_user

pytestmark = pytest.mark.asyncio


def _ctx(*perms: str, is_admin: bool = False, employee_id=None) -> AccessContext:
    return AccessContext(user_id=uuid.uuid4(), is_admin=is_admin, permissions=frozenset(perms), employee_id=employee_id)


async def test_admin_has_every_permission_except_critical_ones():
    admin = _ctx(is_admin=True)
    assert admin.has("assets.read") and admin.is_technician and admin.can_read_all and admin.can_view_reports
    assert not admin.has("system.backup.manage")
    assert _ctx("system.backup.manage", is_admin=True).has("system.backup.manage")


async def test_ticket_flags_follow_the_permissions():
    tech = _ctx("service_desk.tickets.manage")
    assert tech.is_technician and tech.can_internal_notes and not tech.can_read_all
    notes = _ctx("service_desk.interactions.internal")
    assert notes.can_internal_notes and not notes.is_technician
    scope = tech.ticket_scope()
    assert scope == {
        "user_employee_id": None, "user_id": tech.user_id, "sector_id": None, "is_technician": True, "can_read_all": False
    }


async def test_asset_reading_is_by_permission_or_ownership():
    emp = uuid.uuid4()
    mine, other = SimpleNamespace(employee_id=emp), SimpleNamespace(employee_id=uuid.uuid4())
    own = _ctx("assets.read_own", employee_id=emp)
    assert own.can_read_asset(mine) and not own.can_read_asset(other)
    assert _ctx("assets.read").can_read_asset(other)
    assert not _ctx(employee_id=emp).can_read_asset(mine)
    assert not _ctx("assets.read_own").can_read_asset(SimpleNamespace(employee_id=None))


async def test_built_context_carries_the_employee_unit_and_sector(db_session: AsyncSession):
    org = await make_org(db_session)
    emp = await make_employee(db_session, org)
    user = await make_user(db_session, emp)
    ctx = await build_access_context(db_session, user.id, is_admin=False, permissions=["assets.read"])
    assert (ctx.employee_id, ctx.unit_id, ctx.sector_id) == (emp.id, org.unit.id, org.sector.id)
    orphan = await make_user(db_session)
    empty = await build_access_context(db_session, orphan.id, is_admin=True, permissions=None)
    assert (empty.employee_id, empty.sector_id, empty.permissions) == (None, None, frozenset())


async def test_chat_context_uses_current_db_permissions_like_the_login(db_session: AsyncSession):
    """Sem token: perfis sem críticas + concessões individuais; conta inativa não tem contexto."""
    await sync_permission_catalog(db_session)
    perms = {p.code: p for p in (await db_session.execute(select(Permission))).scalars()}
    role = Role(name="Chat", permissions=[perms["service_desk.tickets.manage"]])
    db_session.add(role)
    await db_session.flush()
    await db_session.execute(
        role_permission_association.insert().values(role_id=role.id, permission_id=perms["system.data.import"].id)
    )
    org = await make_org(db_session)
    user = await make_user(db_session, await make_employee(db_session, org))
    await db_session.execute(user_role_association.insert().values(user_id=user.id, role_id=role.id))
    db_session.add(UserCriticalGrant(user_id=user.id, permission_id=perms["system.backup.download"].id, granted_via="api"))
    await db_session.commit()

    ctx = await load_access_context(db_session, user.id)
    assert ctx.is_technician and ctx.sector_id == org.sector.id
    assert "system.backup.download" in ctx.permissions and "system.data.import" not in ctx.permissions
    assert ctx.name.startswith("Colaborador")

    user.is_active = False
    await db_session.commit()
    assert await load_access_context(db_session, user.id) is None
