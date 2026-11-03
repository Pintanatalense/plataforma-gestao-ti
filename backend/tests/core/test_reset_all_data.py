"""Zerar a base: só administrador, com frase de confirmação e backup; mantém usuários e configuração."""

from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.audit.models import AuditLog
from app.backup.services import BackupService
from app.identity.models import UserAccount
from app.organization.models import Employee, Sector, Unit
from app.service_desk.models import Ticket, TicketInteraction
from app.stock.models import StockItem
from tests.factories import (
    headers_for,
    make_asset,
    make_asset_category,
    make_employee,
    make_org,
    make_stock_item,
    make_ticket_category,
    make_user,
)

pytestmark = pytest.mark.asyncio

URL = "/api/v1/system/demo/reset-all"
PHRASE = "ZERAR TODA A BASE"


@pytest.fixture(autouse=True)
def fake_backup(monkeypatch):
    async def recent(self, max_age_hours=24):
        return True, SimpleNamespace(filename="backup_teste.sql.gz")

    monkeypatch.setattr(BackupService, "get_recent_valid_backup", recent)


async def _count(db: AsyncSession, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar() or 0


async def _populate(db: AsyncSession):
    org = await make_org(db)
    emp = await make_employee(db, org)
    cat = await make_asset_category(db)
    await make_asset(db, org, cat, employee=emp)
    await make_stock_item(db, org.unit)
    category = await make_ticket_category(db, org.sector)
    user = await make_user(db, emp)
    ticket = Ticket(
        title="Chamado", description="x", priority="LOW", status="OPENED", custom_fields={}, requester_id=emp.id,
        origin_unit_id=org.unit.id, origin_sector_id=org.sector.id, responsible_sector_id=org.sector.id,
        category_id=category.id,
    )
    db.add(ticket)
    await db.commit()
    db.add(TicketInteraction(ticket_id=ticket.id, author_id=user.id, message="oi", is_internal=False))
    await db.commit()
    return org


async def test_admin_resets_work_data_and_keeps_accounts(client: AsyncClient, db_session: AsyncSession):
    admin = await make_user(db_session, is_admin=True)
    other = await make_user(db_session)
    await _populate(db_session)

    resp = await client.post(URL, json={"confirmation_phrase": PHRASE}, headers=headers_for(admin, "system.data.reset"))

    assert resp.status_code == 200, resp.text
    assert resp.json()["summary"]["assets_removed"] == 1
    assert resp.json()["summary"]["tickets_removed"] == 1
    for model in (Asset, StockItem, Employee, Ticket, TicketInteraction):
        assert await _count(db_session, model) == 0, model.__name__
    # a estrutura inicial (setor de TI) é recriada e as categorias voltam a apontar para ela
    sectors = (await db_session.execute(select(Sector))).scalars().all()
    assert [s.code for s in sectors] == ["TI-00"]
    assert await _count(db_session, Unit) == 1
    assert (await db_session.execute(select(UserAccount).where(UserAccount.employee_id.is_not(None)))).first() is None
    assert await _count(db_session, UserAccount) == 3  # contas continuam (admin, outro e o do colaborador)
    assert (await db_session.get(UserAccount, other.id)) is not None
    event = (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "system.data.reset"))).scalar_one()
    assert event.user_id == admin.id


async def test_wrong_phrase_deletes_nothing(client: AsyncClient, db_session: AsyncSession):
    admin = await make_user(db_session, is_admin=True)
    await _populate(db_session)

    resp = await client.post(URL, json={"confirmation_phrase": "zerar"}, headers=headers_for(admin, "system.data.reset"))

    assert resp.status_code >= 400
    assert await _count(db_session, Asset) == 1


async def test_manager_without_admin_flag_is_refused(client: AsyncClient, db_session: AsyncSession):
    manager = await make_user(db_session)
    await _populate(db_session)

    resp = await client.post(URL, json={"confirmation_phrase": PHRASE}, headers=headers_for(manager, "system.data.reset"))

    assert resp.status_code == 403
    assert await _count(db_session, Asset) == 1
