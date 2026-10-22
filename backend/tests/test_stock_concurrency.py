"""Concorrência real de estoque: exige PostgreSQL descartável (TEST_DATABASE_URL), pois o SQLite ignora FOR UPDATE."""

import asyncio
import os

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.database import Base
from app.identity.models import UserAccount
from app.organization.models import Company, Unit
from app.stock.models import StockItem
from app.stock.repository import StockRepository
from app.stock.schemas import StockMovementCreate
from app.stock.services import StockService

pytestmark = [pytest.mark.pg, pytest.mark.asyncio]


async def test_concurrent_outputs_never_lose_updates():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as s:
        company = Company(name="C")
        s.add(company)
        await s.flush()
        unit = Unit(company_id=company.id, name="U", code="U1")
        user = UserAccount(email="a@b.c", hashed_password=hash_password("x"))
        s.add_all([unit, user])
        await s.flush()
        item = StockItem(name="Cabo", unit_id=unit.id, quantity=30, min_quantity=0)
        s.add(item)
        await s.commit()
        item_id, user_id = item.id, user.id

    async def one_output() -> str:
        async with maker() as s:
            svc = StockService(StockRepository(s))
            try:
                await svc.add_movement(StockMovementCreate(item_id=item_id, movement_type="OUT", quantity=1), user_id)
                await s.commit()
                return "ok"
            except Exception:
                await s.rollback()
                return "fail"

    results = await asyncio.gather(*[one_output() for _ in range(40)])

    async with maker() as s:
        final = (await s.get(StockItem, item_id)).quantity
    await engine.dispose()

    assert results.count("ok") == 30  # só 30 unidades existiam
    assert final == 0
