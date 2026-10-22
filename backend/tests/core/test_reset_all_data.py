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
from app.organization.models import Company, Employee, Sector, Unit
from app.stock.models import StockItem
from tests.factories import (
    headers_for,
    make_asset,
    make_asset_category,
    make_employee,
    make_org,
    make_stock_item,
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
    return org


async def test_admin_resets_work_data_and_keeps_accounts(client: AsyncClient, db_session: AsyncSession):
    admin = await make_user(db_session, is_admin=True)
    other = await make_user(db_session)
    await _populate(db_session)

    resp = await client.post(URL, json={"confirmation_phrase": PHRASE}, headers=headers_for(admin, "system.backup.manage"))

    assert resp.status_code == 200, resp.text
    assert resp.json()["summary"]["assets_removed"] == 1
    for model in (Asset, StockItem, Employee, Unit, Sector):
        assert await _count(db_session, model) == 0, model.__name__
    assert await _count(db_session, Company) == 1
    assert await _count(db_session, UserAccount) == 2  # contas continuam
    assert (await db_session.get(UserAccount, other.id)) is not None
    event = (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "system.data.reset"))).scalar_one()
    assert event.user_id == admin.id


async def test_wrong_phrase_deletes_nothing(client: AsyncClient, db_session: AsyncSession):
    admin = await make_user(db_session, is_admin=True)
    await _populate(db_session)

    resp = await client.post(URL, json={"confirmation_phrase": "zerar"}, headers=headers_for(admin, "system.backup.manage"))

    assert resp.status_code >= 400
    assert await _count(db_session, Asset) == 1


async def test_manager_without_admin_flag_is_refused(client: AsyncClient, db_session: AsyncSession):
    manager = await make_user(db_session)
    await _populate(db_session)

    resp = await client.post(URL, json={"confirmation_phrase": PHRASE}, headers=headers_for(manager, "system.backup.manage"))

    assert resp.status_code == 403
    assert await _count(db_session, Asset) == 1
