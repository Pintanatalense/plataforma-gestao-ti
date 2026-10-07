"""
MOD-02 — Organização (Router)
"""

import uuid
from typing import Sequence

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_permission
from app.database import get_db
from app.organization.schemas import (
    CompanyCreate,
    CompanyOut,
    CompanyUpdate,
    EmployeeCreate,
    EmployeeOut,
    EmployeeUpdate,
    SectorCreate,
    SectorOut,
    SectorUpdate,
    UnitCreate,
    UnitOut,
    UnitUpdate,
)
from app.organization.services import OrganizationService

router = APIRouter(prefix="/organization", tags=["Organization"])

# ==============================================================================
# Company
# ==============================================================================

@router.get("/company", response_model=CompanyOut, dependencies=[Depends(require_permission("organization.company.read"))])
async def get_company(db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.get_company()


@router.post("/company", response_model=CompanyOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("organization.company.create"))])
async def initialize_company(schema: CompanyCreate, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.initialize_company(schema)


@router.patch("/company", response_model=CompanyOut, dependencies=[Depends(require_permission("organization.company.update"))])
async def update_company(schema: CompanyUpdate, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.update_company(schema)


# ==============================================================================
# Unit
# ==============================================================================

@router.get("/units", response_model=list[UnitOut], dependencies=[Depends(require_permission("organization.units.read"))])
async def list_units(db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.list_units()


@router.post("/units", response_model=UnitOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("organization.units.create"))])
async def create_unit(schema: UnitCreate, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.create_unit(schema)


@router.get("/units/{unit_id}", response_model=UnitOut, dependencies=[Depends(require_permission("organization.units.read"))])
async def get_unit(unit_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.get_unit(unit_id)


@router.patch("/units/{unit_id}", response_model=UnitOut, dependencies=[Depends(require_permission("organization.units.update"))])
async def update_unit(unit_id: uuid.UUID, schema: UnitUpdate, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.update_unit(unit_id, schema)


# ==============================================================================
# Sector
# ==============================================================================

@router.get("/sectors", response_model=list[SectorOut], dependencies=[Depends(require_permission("organization.sectors.read"))])
async def list_sectors(unit_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.list_sectors(unit_id)


@router.post("/sectors", response_model=SectorOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("organization.sectors.create"))])
async def create_sector(schema: SectorCreate, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.create_sector(schema)


@router.get("/sectors/{sector_id}", response_model=SectorOut, dependencies=[Depends(require_permission("organization.sectors.read"))])
async def get_sector(sector_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.get_sector(sector_id)


@router.patch("/sectors/{sector_id}", response_model=SectorOut, dependencies=[Depends(require_permission("organization.sectors.update"))])
async def update_sector(sector_id: uuid.UUID, schema: SectorUpdate, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.update_sector(sector_id, schema)


# ==============================================================================
# Employee
# ==============================================================================

@router.get("/employees", response_model=list[EmployeeOut], dependencies=[Depends(require_permission("organization.employees.read"))])
async def list_employees(unit_id: uuid.UUID | None = None, sector_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.list_employees(unit_id, sector_id)


@router.post("/employees", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("organization.employees.create"))])
async def create_employee(schema: EmployeeCreate, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.create_employee(schema)


@router.get("/employees/{employee_id}", response_model=EmployeeOut, dependencies=[Depends(require_permission("organization.employees.read"))])
async def get_employee(employee_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.get_employee(employee_id)


@router.patch("/employees/{employee_id}", response_model=EmployeeOut, dependencies=[Depends(require_permission("organization.employees.update"))])
async def update_employee(employee_id: uuid.UUID, schema: EmployeeUpdate, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.update_employee(employee_id, schema)
