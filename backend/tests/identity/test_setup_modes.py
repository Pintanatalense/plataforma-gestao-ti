"""Primeiro acesso: base limpa x demonstração, e o catálogo inicial que torna a base limpa utilizável."""
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import AssetCategory
from app.core.settings_model import SystemSetting
from app.core.starter_catalog import ASSET_CATEGORIES, TI_SECTOR_CODE, TICKET_CATEGORIES, seed_starter_catalog
from app.organization.models import Company, Sector, Unit
from app.service_desk.models import TicketCategory

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


async def test_demo_setup_loads_example_data_on_top_of_the_same_catalog(client: AsyncClient, db_session: AsyncSession):
    await _installed_base(db_session)
    resp = await client.post(SETUP, json={**ADMIN, "setup_mode": "DEMO"})
    assert resp.status_code == 201, resp.text

    assert await _count(db_session, TicketCategory) == len(TICKET_CATEGORIES)
    demo_sectors = (await db_session.execute(select(func.count()).select_from(Sector).where(Sector.is_demo.is_(True)))).scalar_one()
    assert demo_sectors > 0
    mode = (await db_session.execute(select(SystemSetting).where(SystemSetting.key == "system_mode"))).scalar_one()
    assert mode.value == "DEMO"


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
