"""
MOD-02 — Organização (Services)

Regras de negócio para as entidades da organização.
Comunica-se com outros módulos via barramento de eventos (ex: funcionário criado).
"""

import uuid
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event, event_bus
from app.core.exceptions import BusinessRuleException, ConflictException, NotFoundException
from app.organization.models import Company, Employee, Sector, Unit
from app.organization.repository import OrganizationRepository
from app.organization.schemas import (
    CompanyCreate,
    CompanyUpdate,
    EmployeeCreate,
    EmployeeUpdate,
    SectorCreate,
    SectorUpdate,
    UnitCreate,
    UnitUpdate,
)


class OrganizationService:
    def __init__(self, session: AsyncSession):
        self.repo = OrganizationRepository(session)

    # ==========================================================================
    # Company
    # ==========================================================================

    async def get_company(self) -> Company:
        company = await self.repo.get_company()
        if not company:
            raise NotFoundException("Empresa", "não configurada")
        return company

    async def initialize_company(self, schema: CompanyCreate) -> Company:
        existing = await self.repo.get_company()
        if existing:
            raise ConflictException("A empresa já foi inicializada.")
        
        company = Company(name=schema.name, cnpj=schema.cnpj)
        return await self.repo.create_company(company)

    async def update_company(self, schema: CompanyUpdate) -> Company:
        company = await self.get_company()
        if schema.name is not None:
            company.name = schema.name
        if schema.cnpj is not None:
            company.cnpj = schema.cnpj
        
        return await self.repo.update_company(company)

    # ==========================================================================
    # Unit
    # ==========================================================================

    async def get_unit(self, unit_id: uuid.UUID) -> Unit:
        unit = await self.repo.get_unit(unit_id)
        if not unit:
            raise NotFoundException("Unidade", unit_id)
        return unit

    async def list_units(self) -> Sequence[Unit]:
        return await self.repo.list_units()

    async def _ensure_unit_code_available(self, code: str) -> None:
        if await self.repo.get_unit_by_code(code):
            raise ConflictException(f"Já existe uma unidade com o código '{code}'.", {"field": "code"})

    async def create_unit(self, schema: UnitCreate) -> Unit:
        company = await self.get_company()
        if str(schema.company_id) != str(company.id):
            raise ConflictException("ID da empresa inválido.")

        await self._ensure_unit_code_available(schema.code)
        
        unit = Unit(
            company_id=schema.company_id,
            name=schema.name,
            code=schema.code,
            type=schema.type,
            address=schema.address,
        )
        return await self.repo.create_unit(unit)

    async def update_unit(self, unit_id: uuid.UUID, schema: UnitUpdate) -> Unit:
        unit = await self.get_unit(unit_id)
        
        if schema.name is not None:
            unit.name = schema.name
        if schema.code is not None and schema.code != unit.code:
            await self._ensure_unit_code_available(schema.code)
            unit.code = schema.code
        if schema.type is not None:
            unit.type = schema.type
        if schema.address is not None:
            unit.address = schema.address
            
        return await self.repo.update_unit(unit)

    # ==========================================================================
    # Sector
    # ==========================================================================

    async def get_sector(self, sector_id: uuid.UUID) -> Sector:
        sector = await self.repo.get_sector(sector_id)
        if not sector:
            raise NotFoundException("Setor", sector_id)
        return sector

    async def list_sectors(self, unit_id: uuid.UUID | None = None) -> Sequence[Sector]:
        return await self.repo.list_sectors(unit_id)

    async def _ensure_sector_code_available(self, code: str) -> None:
        if await self.repo.get_sector_by_code(code):
            raise ConflictException(f"Já existe um setor com o código '{code}'.", {"field": "code"})

    async def create_sector(self, schema: SectorCreate) -> Sector:
        await self.get_unit(schema.unit_id)  # Valida se a unidade existe
        await self._ensure_sector_code_available(schema.code)
        
        sector = Sector(
            unit_id=schema.unit_id,
            name=schema.name,
            code=schema.code,
        )
        return await self.repo.create_sector(sector)

    async def update_sector(self, sector_id: uuid.UUID, schema: SectorUpdate) -> Sector:
        sector = await self.get_sector(sector_id)
        
        if schema.name is not None:
            sector.name = schema.name
        if schema.code is not None and schema.code != sector.code:
            await self._ensure_sector_code_available(schema.code)
            sector.code = schema.code
            
        return await self.repo.update_sector(sector)

    # ==========================================================================
    # Employee
    # ==========================================================================

    async def get_employee(self, employee_id: uuid.UUID) -> Employee:
        employee = await self.repo.get_employee(employee_id)
        if not employee:
            raise NotFoundException("Colaborador", employee_id)
        return employee

    async def list_employees(self, unit_id: uuid.UUID | None = None, sector_id: uuid.UUID | None = None) -> Sequence[Employee]:
        return await self.repo.list_employees(unit_id, sector_id)

    async def _validate_unit_sector(self, unit_id: uuid.UUID, sector_id: uuid.UUID) -> None:
        """Garante que unidade e setor existem e que o setor pertence à unidade."""
        await self.get_unit(unit_id)
        sector = await self.get_sector(sector_id)
        if sector.unit_id != unit_id:
            raise BusinessRuleException(
                "O setor informado não pertence à unidade do colaborador.",
                rule="employee.sector_in_unit",
            )

    async def create_employee(self, schema: EmployeeCreate) -> Employee:
        await self._validate_unit_sector(schema.unit_id, schema.sector_id)
        
        if schema.manager_id:
            await self.get_employee(schema.manager_id)
            
        existing = await self.repo.get_employee_by_registration(schema.registration_number)
        if existing:
            raise ConflictException("Matrícula já cadastrada.", {"field": "registration_number"})
            
        employee = Employee(
            unit_id=schema.unit_id,
            sector_id=schema.sector_id,
            manager_id=schema.manager_id,
            name=schema.name,
            registration_number=schema.registration_number,
            position=schema.position,
            status=schema.status,
        )
        
        employee = await self.repo.create_employee(employee)
        
        await event_bus.emit(Event(
            event_type="employee.created",
            entity_type="employee",
            entity_id=employee.id,
            data={"registration": employee.registration_number}
        ))
        
        return employee

    async def update_employee(self, employee_id: uuid.UUID, schema: EmployeeUpdate) -> Employee:
        employee = await self.get_employee(employee_id)

        if schema.unit_id is not None or schema.sector_id is not None:
            unit_id = schema.unit_id or employee.unit_id
            sector_id = schema.sector_id or employee.sector_id
            await self._validate_unit_sector(unit_id, sector_id)
            employee.unit_id = unit_id
            employee.sector_id = sector_id
            
        if schema.manager_id is not None:
            if schema.manager_id == employee.id:
                raise BusinessRuleException("Um colaborador não pode ser gestor de si mesmo.")
            await self.get_employee(schema.manager_id)
            employee.manager_id = schema.manager_id
            
        if schema.name is not None:
            employee.name = schema.name
        if schema.position is not None:
            employee.position = schema.position
        if schema.status is not None:
            employee.status = schema.status
            
        if schema.registration_number is not None and schema.registration_number != employee.registration_number:
            existing = await self.repo.get_employee_by_registration(schema.registration_number)
            if existing:
                raise ConflictException("Matrícula já cadastrada.", {"field": "registration_number"})
            employee.registration_number = schema.registration_number
            
        return await self.repo.update_employee(employee)
