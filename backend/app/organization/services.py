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

    async def get_unit(self, unit_id: uuid.UUID, include_inactive: bool = False) -> Unit:
        unit = await self.repo.get_unit(unit_id, include_inactive=include_inactive)
        if not unit:
            raise NotFoundException("Unidade", unit_id)
        return unit

    async def list_units(self, include_inactive: bool = True) -> Sequence[Unit]:
        return await self.repo.list_units(include_inactive=include_inactive)

    async def _ensure_unit_code_available(self, code: str) -> None:
        if await self.repo.get_unit_by_code(code):
            raise ConflictException(f"Já existe uma unidade com o código '{code}'.", {"field": "code"})

    async def create_unit(self, schema: UnitCreate) -> Unit:
        company = await self.get_company()
        company_id = schema.company_id or company.id

        await self._ensure_unit_code_available(schema.code)
        
        unit = Unit(
            company_id=company_id,
            name=schema.name,
            code=schema.code,
            type=schema.type,
            address=schema.address,
            is_active=schema.is_active if schema.is_active is not None else True,
        )
        return await self.repo.create_unit(unit)

    async def update_unit(self, unit_id: uuid.UUID, schema: UnitUpdate) -> Unit:
        unit = await self.get_unit(unit_id, include_inactive=True)
        
        if schema.name is not None:
            unit.name = schema.name
        if schema.code is not None and schema.code != unit.code:
            await self._ensure_unit_code_available(schema.code)
            unit.code = schema.code
        if schema.type is not None:
            unit.type = schema.type
        if schema.address is not None:
            unit.address = schema.address
        if schema.is_active is not None:
            unit.is_active = schema.is_active
            if not schema.is_active and unit.deleted_at is None:
                unit.soft_delete()
            elif schema.is_active and unit.deleted_at is not None:
                unit.restore()
            
        return await self.repo.update_unit(unit)

    async def delete_unit(self, unit_id: uuid.UUID) -> None:
        unit = await self.get_unit(unit_id, include_inactive=True)
        unit.soft_delete()
        await self.repo.update_unit(unit)

    # ==========================================================================
    # Sector
    # ==========================================================================

    async def get_sector(self, sector_id: uuid.UUID, include_inactive: bool = False) -> Sector:
        sector = await self.repo.get_sector(sector_id, include_inactive=include_inactive)
        if not sector:
            raise NotFoundException("Setor", sector_id)
        return sector

    async def list_sectors(self, unit_id: uuid.UUID | None = None, include_inactive: bool = True) -> Sequence[Sector]:
        return await self.repo.list_sectors(unit_id, include_inactive=include_inactive)

    async def _ensure_sector_code_available(self, code: str) -> None:
        if await self.repo.get_sector_by_code(code):
            raise ConflictException(f"Já existe um setor com o código '{code}'.", {"field": "code"})

    async def create_sector(self, schema: SectorCreate) -> Sector:
        await self.get_unit(schema.unit_id, include_inactive=True)  # Valida se a unidade existe
        await self._ensure_sector_code_available(schema.code)
        
        sector = Sector(
            unit_id=schema.unit_id,
            name=schema.name,
            code=schema.code,
            is_active=schema.is_active if schema.is_active is not None else True,
        )
        return await self.repo.create_sector(sector)

    async def update_sector(self, sector_id: uuid.UUID, schema: SectorUpdate) -> Sector:
        sector = await self.get_sector(sector_id, include_inactive=True)
        
        if schema.name is not None:
            sector.name = schema.name
        if schema.code is not None and schema.code != sector.code:
            await self._ensure_sector_code_available(schema.code)
            sector.code = schema.code
        if schema.unit_id is not None:
            await self.get_unit(schema.unit_id, include_inactive=True)
            sector.unit_id = schema.unit_id
        if schema.is_active is not None:
            sector.is_active = schema.is_active
            if not schema.is_active and sector.deleted_at is None:
                sector.soft_delete()
            elif schema.is_active and sector.deleted_at is not None:
                sector.restore()
            
        return await self.repo.update_sector(sector)

    async def delete_sector(self, sector_id: uuid.UUID) -> None:
        sector = await self.get_sector(sector_id, include_inactive=True)
        sector.soft_delete()
        await self.repo.update_sector(sector)

    # ==========================================================================
    # Employee
    # ==========================================================================

    async def get_employee(self, employee_id: uuid.UUID, include_inactive: bool = False) -> Employee:
        employee = await self.repo.get_employee(employee_id, include_inactive=include_inactive)
        if not employee:
            raise NotFoundException("Colaborador", employee_id)
        return employee

    async def list_employees(self, unit_id: uuid.UUID | None = None, sector_id: uuid.UUID | None = None, include_inactive: bool = True) -> Sequence[Employee]:
        return await self.repo.list_employees(unit_id, sector_id, include_inactive=include_inactive)

    async def _validate_unit_sector(self, unit_id: uuid.UUID, sector_id: uuid.UUID) -> None:
        """Garante que unidade e setor existem e que o setor pertence à unidade."""
        await self.get_unit(unit_id, include_inactive=True)
        sector = await self.get_sector(sector_id, include_inactive=True)
        if sector.unit_id != unit_id:
            raise BusinessRuleException(
                "O setor informado não pertence à unidade do colaborador.",
                rule="employee.sector_in_unit",
            )

    async def create_employee(self, schema: EmployeeCreate) -> Employee:
        sector = await self.get_sector(schema.sector_id, include_inactive=True)
        unit_id = schema.unit_id or sector.unit_id
        await self._validate_unit_sector(unit_id, schema.sector_id)
        
        if schema.manager_id:
            await self.get_employee(schema.manager_id, include_inactive=True)
            
        reg = schema.registration_number or schema.registration
        if not reg:
            raise BusinessRuleException("Matrícula é obrigatória.")

        existing = await self.repo.get_employee_by_registration(reg)
        if existing:
            raise ConflictException("Matrícula já cadastrada.", {"field": "registration_number"})
            
        employee = Employee(
            unit_id=unit_id,
            sector_id=schema.sector_id,
            manager_id=schema.manager_id,
            name=schema.name,
            registration_number=reg,
            position=schema.position or schema.job_title,
            status=schema.status or "ATIVO",
            is_active=schema.is_active if schema.is_active is not None else True,
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
        employee = await self.get_employee(employee_id, include_inactive=True)

        if schema.sector_id is not None:
            sector = await self.get_sector(schema.sector_id, include_inactive=True)
            unit_id = schema.unit_id or sector.unit_id
            await self._validate_unit_sector(unit_id, schema.sector_id)
            employee.unit_id = unit_id
            employee.sector_id = schema.sector_id
        elif schema.unit_id is not None:
            await self._validate_unit_sector(schema.unit_id, employee.sector_id)
            employee.unit_id = schema.unit_id
            
        if schema.manager_id is not None:
            if schema.manager_id == employee.id:
                raise BusinessRuleException("Um colaborador não pode ser gestor de si mesmo.")
            await self.get_employee(schema.manager_id, include_inactive=True)
            employee.manager_id = schema.manager_id
            
        if schema.name is not None:
            employee.name = schema.name
        pos = schema.position if schema.position is not None else schema.job_title
        if pos is not None:
            employee.position = pos
        if schema.status is not None:
            employee.status = schema.status
            
        reg = schema.registration_number if schema.registration_number is not None else schema.registration
        if reg is not None and reg != employee.registration_number:
            existing = await self.repo.get_employee_by_registration(reg)
            if existing:
                raise ConflictException("Matrícula já cadastrada.", {"field": "registration_number"})
            employee.registration_number = reg

        if schema.is_active is not None:
            employee.is_active = schema.is_active
            if not schema.is_active and employee.deleted_at is None:
                employee.soft_delete()
                employee.status = "DESLIGADO"
            elif schema.is_active and employee.deleted_at is not None:
                employee.restore()
                if employee.status == "DESLIGADO":
                    employee.status = "ATIVO"
            
        return await self.repo.update_employee(employee)

    async def delete_employee(self, employee_id: uuid.UUID) -> None:
        employee = await self.get_employee(employee_id, include_inactive=True)
        employee.soft_delete()
        employee.status = "DESLIGADO"
        await self.repo.update_employee(employee)
