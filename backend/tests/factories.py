"""
Fábricas compartilhadas pelos testes de baseline.

Substituem o ``setup_test_data`` duplicado nos arquivos de teste antigos (que
permanecem como estão). Todas usam a sessão de teste e fazem commit, como os
testes existentes.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import count
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetCategory
from app.core.security import hash_password
from app.identity.models import UserAccount
from app.organization.models import Company, Employee, Sector, Unit
from app.service_desk.models import TicketCategory
from app.stock.models import StockItem
from tests.conftest import make_auth_headers

_seq = count(1)


def _n() -> int:
    return next(_seq)


@dataclass
class Org:
    company: Company
    unit: Unit
    sector: Sector


async def make_org(db: AsyncSession) -> Org:
    n = _n()
    company = Company(name=f"Empresa {n}")
    db.add(company)
    await db.commit()
    unit = Unit(name=f"Unidade {n}", code=f"U{n}", company_id=company.id)
    db.add(unit)
    await db.commit()
    sector = Sector(name=f"Setor {n}", code=f"S{n}", unit_id=unit.id)
    db.add(sector)
    await db.commit()
    return Org(company, unit, sector)


async def make_unit(db: AsyncSession, company: Company) -> Unit:
    n = _n()
    unit = Unit(name=f"Unidade extra {n}", code=f"UX{n}", company_id=company.id)
    db.add(unit)
    await db.commit()
    return unit


async def make_sector(db: AsyncSession, unit: Unit) -> Sector:
    n = _n()
    sector = Sector(name=f"Setor extra {n}", code=f"SX{n}", unit_id=unit.id)
    db.add(sector)
    await db.commit()
    return sector


async def make_employee(db: AsyncSession, org: Org) -> Employee:
    n = _n()
    emp = Employee(
        name=f"Colaborador {n}",
        registration_number=f"MAT{n}",
        unit_id=org.unit.id,
        sector_id=org.sector.id,
    )
    db.add(emp)
    await db.commit()
    return emp


async def make_user(
    db: AsyncSession,
    employee: Employee | None = None,
    *,
    is_admin: bool = False,
) -> UserAccount:
    n = _n()
    user = UserAccount(
        email=f"user{n}@test.local",
        hashed_password=hash_password("123"),
        employee_id=employee.id if employee else None,
        is_admin=is_admin,
    )
    db.add(user)
    await db.commit()
    return user


def headers_for(user: UserAccount, *permissions: str, is_admin: bool | None = None) -> dict[str, str]:
    """Cabeçalhos JWT como o login real emitiria (claims is_admin e permissions)."""
    claims: dict[str, Any] = {
        "is_admin": user.is_admin if is_admin is None else is_admin,
        "permissions": list(permissions),
    }
    return make_auth_headers(user_id=str(user.id), **claims)


async def make_ticket_category(
    db: AsyncSession, sector: Sector | None = None, *, active: bool = True, name: str | None = None
) -> TicketCategory:
    cat = TicketCategory(
        name=name or f"Categoria {_n()}",
        default_sector_id=sector.id if sector else None,
        is_active=active,
    )
    db.add(cat)
    await db.commit()
    return cat


async def make_asset_category(db: AsyncSession) -> AssetCategory:
    cat = AssetCategory(name=f"Cat. ativo {_n()}", spec_schema={})
    db.add(cat)
    await db.commit()
    return cat


async def make_asset(
    db: AsyncSession,
    org: Org,
    category: AssetCategory,
    *,
    status: str = "IN_STOCK",
    employee: Employee | None = None,
) -> Asset:
    asset = Asset(
        tag=f"PAT-{_n()}",
        name="Notebook",
        category_id=category.id,
        status=status,
        technical_specs={},
        unit_id=org.unit.id,
        employee_id=employee.id if employee else None,
    )
    db.add(asset)
    await db.commit()
    return asset


async def make_stock_item(db: AsyncSession, unit: Unit, quantity: int = 10) -> StockItem:
    item = StockItem(name=f"Insumo {_n()}", unit_id=unit.id, quantity=quantity, min_quantity=0)
    db.add(item)
    await db.commit()
    return item
