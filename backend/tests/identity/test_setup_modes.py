"""Primeiro acesso: base limpa x demonstração, e o catálogo inicial que torna a base limpa utilizável."""
import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetCategory
from app.core.demo_service import DemoManagementService
from app.core.settings_model import SystemSetting
from app.core.starter_catalog import ASSET_CATEGORIES, TI_SECTOR_CODE, TICKET_CATEGORIES, seed_starter_catalog
from app.identity.models import UserAccount
from app.organization.models import Company, Employee, Sector, Unit
from app.service_desk.models import Ticket, TicketCategory
from app.stock.models import StockItem

pytestmark = pytest.mark.asyncio

SETUP = "/api/v1/identity/setup"
ADMIN = {"email": "ti@empresa.com", "password": "senha-forte-1"}


async def _installed_base(db: AsyncSession) -> Company:
    """O que o seed do container cria antes do primeiro acesso: empresa padrão e a unidade Matriz."""
    company = Company(name="Empresa Padrão", cnpj="00.000.000/0001-00")
    db.add(company)
    await db.flush()
    db.add(Unit(company_id=company.id, name="Matriz", code="MAT-01", type="MATRIZ"))
    await db.commit()
    return company


async def _count(db: AsyncSession, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def test_clean_setup_names_the_company_and_leaves_a_usable_catalog(client: AsyncClient, db_session: AsyncSession):
    await _installed_base(db_session)
    resp = await client.post(SETUP, json={**ADMIN, "setup_mode": "CLEAN", "company_name": "Acme Tecnologia Ltda", "company_cnpj": "11.222.333/0001-44"})
    assert resp.status_code == 201, resp.text

    company = (await db_session.execute(select(Company))).scalar_one()
    assert (company.name, company.cnpj, company.is_demo) == ("Acme Tecnologia Ltda", "11.222.333/0001-44", False)

    sector = (await db_session.execute(select(Sector).where(Sector.code == TI_SECTOR_CODE))).scalar_one()
    assert sector.is_demo is False
    categories = list((await db_session.execute(select(TicketCategory))).scalars())
    assert len(categories) == len(TICKET_CATEGORIES)
    assert {c.default_sector_id for c in categories} == {sector.id}  # chamados nascem com setor responsável
    assert await _count(db_session, AssetCategory) == len(ASSET_CATEGORIES)

    mode = (await db_session.execute(select(SystemSetting).where(SystemSetting.key == "system_mode"))).scalar_one()
    assert mode.value == "PRODUCTION"
    assert (await client.get("/api/v1/identity/setup/status")).json() == {"setup_required": False}


async def test_demo_setup_loads_a_rich_example_on_top_of_the_same_catalog(client: AsyncClient, db_session: AsyncSession):
    await _installed_base(db_session)
    resp = await client.post(SETUP, json={**ADMIN, "setup_mode": "DEMO"})
    assert resp.status_code == 201, resp.text

    assert await _count(db_session, TicketCategory) == len(TICKET_CATEGORIES)
    tickets = list((await db_session.execute(select(Ticket))).scalars())
    assert len(tickets) == 6 and all(t.is_demo for t in tickets)
    assert {t.status for t in tickets} >= {"OPENED", "IN_PROGRESS", "PENDING", "RESOLVED", "CLOSED"}
    assert all(t.category_id is not None for t in tickets)

    items = list((await db_session.execute(select(StockItem))).scalars())
    assert len(items) == 5 and sum(1 for i in items if i.quantity <= i.min_quantity) == 3  # alimenta o alerta de estoque baixo

    today = date.today()
    soon = [a for a in (await db_session.execute(select(Asset))).scalars() if a.warranty_expires and a.warranty_expires <= today + timedelta(days=30)]
    assert len(soon) == 2  # alimenta o alerta de garantia

    # No exemplo, as categorias passam a apontar para o setor de TI de exemplo (onde está o atendente de exemplo).
    sectors = {s.id: s for s in (await db_session.execute(select(Sector))).scalars()}
    assert {sectors[c.default_sector_id].is_demo for c in (await db_session.execute(select(TicketCategory))).scalars()} == {True}
    mode = (await db_session.execute(select(SystemSetting).where(SystemSetting.key == "system_mode"))).scalar_one()
    assert mode.value == "DEMO"


async def test_cleaning_the_example_keeps_the_real_catalog_and_returns_to_production(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    await _installed_base(db_session)
    if db_session.bind.dialect.name == "sqlite":
        await db_session.execute(text("PRAGMA foreign_keys=ON"))  # o Postgres impõe FKs; o SQLite dos testes, por padrão, não
    token = (await client.post(SETUP, json={**ADMIN, "setup_mode": "DEMO"})).json()["access_token"]

    async def recent_backup(self, max_age_hours=24):
        return True, SimpleNamespace(id=uuid.uuid4(), filename="seguranca.sql.gz", created_at=None, size_bytes=1)

    monkeypatch.setattr("app.backup.services.BackupService.get_recent_valid_backup", recent_backup)
    admin_id = (await db_session.execute(select(UserAccount.id).where(UserAccount.email == ADMIN["email"]))).scalar_one()
    result = await DemoManagementService(db_session).clean_demo_data(admin_id, "LIMPAR DADOS DE DEMONSTRACAO")
    assert result["success"] is True

    for model in (Ticket, StockItem):
        assert await _count(db_session, model) == 0
    assert await _count(db_session, Company) == 1  # só a empresa real; a de exemplo saiu
    assert (await db_session.execute(select(func.count()).select_from(Employee).where(Employee.is_demo.is_(True)))).scalar_one() == 0

    ti = (await db_session.execute(select(Sector).where(Sector.code == TI_SECTOR_CODE))).scalar_one()
    categories = list((await db_session.execute(select(TicketCategory))).scalars())
    assert len(categories) == len(TICKET_CATEGORIES)
    assert {c.default_sector_id for c in categories} == {ti.id}  # voltaram ao setor de TI real
    assert (await db_session.execute(select(Unit).where(Unit.code == "MAT-01"))).scalar_one()  # a Matriz real continua
    assert (await client.get("/api/v1/identity/me", headers={"Authorization": f"Bearer {token}"})).status_code == 200
    mode = (await db_session.execute(select(SystemSetting).where(SystemSetting.key == "system_mode"))).scalar_one()
    assert mode.value == "PRODUCTION"


async def test_starter_catalog_is_idempotent_and_keeps_user_edits(db_session: AsyncSession):
    await _installed_base(db_session)
    first = await seed_starter_catalog(db_session)
    assert first == {"sectors": 1, "ticket_categories": len(TICKET_CATEGORIES), "asset_categories": len(ASSET_CATEGORIES)}

    renamed = (await db_session.execute(select(TicketCategory).where(TicketCategory.name == "Outros"))).scalar_one()
    renamed.description = "Texto do cliente"
    await db_session.commit()
    assert await seed_starter_catalog(db_session) == {"sectors": 0, "ticket_categories": 0, "asset_categories": 0}
    await db_session.refresh(renamed)
    assert renamed.description == "Texto do cliente"


async def test_starter_catalog_does_not_invent_a_company(db_session: AsyncSession):
    assert await seed_starter_catalog(db_session) == {"sectors": 0, "ticket_categories": 0, "asset_categories": 0}
    assert await _count(db_session, Sector) == 0
