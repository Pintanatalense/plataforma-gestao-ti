"""
MOD-02 — Organização (Repository)

Centraliza as queries no banco de dados para Company, Unit, Sector e Employee.
"""

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.organization.models import Company, Employee, Sector, Unit


class OrganizationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ==========================================================================
    # Company
    # ==========================================================================

    async def get_company(self) -> Company | None:
        """Retorna a única empresa cadastrada."""
        stmt = select(Company).where(Company.is_active.is_(True)).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_company(self, company: Company) -> Company:
        self.session.add(company)
        await self.session.flush()
        return company

    async def update_company(self, company: Company) -> Company:
        # self.session.add(company)  # já está na session se foi fetched
        await self.session.flush()
        return company

    # ==========================================================================
    # Unit
    # ==========================================================================

    async def get_unit(self, unit_id: uuid.UUID, include_inactive: bool = False) -> Unit | None:
        stmt = select(Unit).where(Unit.id == unit_id)
        if not include_inactive:
            stmt = stmt.where(Unit.is_active.is_(True))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_unit_by_code(self, code: str) -> Unit | None:
        # Sem filtro de is_active: a constraint UNIQUE vale para registros inativos também
        stmt = select(Unit).where(Unit.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_units(self, include_inactive: bool = True) -> Sequence[Unit]:
        stmt = select(Unit)
        if not include_inactive:
            stmt = stmt.where(Unit.is_active.is_(True))
        stmt = stmt.order_by(Unit.name)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_unit(self, unit: Unit) -> Unit:
        self.session.add(unit)
        await self.session.flush()
        return unit

    async def update_unit(self, unit: Unit) -> Unit:
        await self.session.flush()
        return unit

    # ==========================================================================
    # Sector
    # ==========================================================================

    async def get_sector(self, sector_id: uuid.UUID, include_inactive: bool = False) -> Sector | None:
        stmt = select(Sector).options(selectinload(Sector.unit)).where(Sector.id == sector_id)
        if not include_inactive:
            stmt = stmt.where(Sector.is_active.is_(True))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_sector_by_code(self, code: str) -> Sector | None:
        stmt = select(Sector).where(Sector.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_sectors(self, unit_id: uuid.UUID | None = None, include_inactive: bool = True) -> Sequence[Sector]:
        stmt = select(Sector).options(selectinload(Sector.unit))
        if not include_inactive:
            stmt = stmt.where(Sector.is_active.is_(True))
        if unit_id:
            stmt = stmt.where(Sector.unit_id == unit_id)
        stmt = stmt.order_by(Sector.name)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_sector(self, sector: Sector) -> Sector:
        self.session.add(sector)
        await self.session.flush()
        return sector

    async def update_sector(self, sector: Sector) -> Sector:
        await self.session.flush()
        return sector

    # ==========================================================================
    # Employee
    # ==========================================================================

    async def get_employee(self, employee_id: uuid.UUID, include_inactive: bool = False) -> Employee | None:
        stmt = select(Employee).options(
            selectinload(Employee.sector).selectinload(Sector.unit)
        ).where(Employee.id == employee_id)
        if not include_inactive:
            stmt = stmt.where(Employee.is_active.is_(True))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_employee_by_registration(self, registration_number: str) -> Employee | None:
        stmt = select(Employee).where(Employee.registration_number == registration_number)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_employees(self, unit_id: uuid.UUID | None = None, sector_id: uuid.UUID | None = None, include_inactive: bool = True) -> Sequence[Employee]:
        stmt = select(Employee).options(
            selectinload(Employee.sector).selectinload(Sector.unit)
        )
        if not include_inactive:
            stmt = stmt.where(Employee.is_active.is_(True))
        if unit_id:
            stmt = stmt.where(Employee.unit_id == unit_id)
        if sector_id:
            stmt = stmt.where(Employee.sector_id == sector_id)
        stmt = stmt.order_by(Employee.name)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_employee(self, employee: Employee) -> Employee:
        self.session.add(employee)
        await self.session.flush()
        return employee

    async def update_employee(self, employee: Employee) -> Employee:
        await self.session.flush()
        return employee
