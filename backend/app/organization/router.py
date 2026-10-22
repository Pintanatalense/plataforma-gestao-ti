"""
MOD-02 — Organização (Router)
"""

import uuid

from fastapi import APIRouter, Depends, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
import os
import aiofiles

from app.core.dependencies import require_permission, get_token_payload
from app.config import get_settings
from app.core.exceptions import ValidationException
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

_LOGO_MAX_BYTES = 2 * 1024 * 1024
_LOGO_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
)

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


@router.post("/company/logo", summary="Upload da logomarca do sistema", dependencies=[Depends(require_permission("organization.company.update"))])
async def upload_company_logo(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Aceita apenas PNG/JPEG/WebP (até 2 MB), conferindo a assinatura do arquivo; SVG/HTML são recusados."""
    content = await file.read(_LOGO_MAX_BYTES + 1)
    if len(content) > _LOGO_MAX_BYTES:
        raise ValidationException("A logomarca deve ter no máximo 2 MB.")
    extension = next((ext for sig, ext in _LOGO_SIGNATURES if content.startswith(sig)), None)
    if extension is None and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        extension = ".webp"
    if extension is None:
        raise ValidationException("Formato de logomarca inválido. Use PNG, JPEG ou WebP.")

    static_dir = str(get_settings().static_dir)
    os.makedirs(static_dir, exist_ok=True)
    for old in os.listdir(static_dir):
        if old.startswith("logo."):
            os.remove(os.path.join(static_dir, old))

    filename = f"logo{extension}"
    async with aiofiles.open(os.path.join(static_dir, filename), "wb") as out_file:
        await out_file.write(content)

    logo_url = f"/static/{filename}"
    service = OrganizationService(db)
    await service.update_company(CompanyUpdate(logo_url=logo_url))
    return {"logo_url": logo_url, "message": "Logo atualizada com sucesso"}


@router.get("/company/public", summary="Busca informações públicas da empresa (nome e logo)")
async def get_company_public(db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    from app.core.exceptions import NotFoundException
    try:
        company = await service.get_company()
        return {"name": company.name, "logo_url": company.logo_url}
    except NotFoundException:
        return {"name": "Gestão de TI", "logo_url": None}


# ==============================================================================
# Unit
# ==============================================================================

@router.get("/units", response_model=list[UnitOut], dependencies=[Depends(require_permission("organization.units.read"))])
async def list_units(include_inactive: bool = True, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.list_units(include_inactive=include_inactive)


@router.post("/units", response_model=UnitOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("organization.units.create"))])
async def create_unit(schema: UnitCreate, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.create_unit(schema)


@router.get("/units/{unit_id}", response_model=UnitOut, dependencies=[Depends(require_permission("organization.units.read"))])
async def get_unit(unit_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.get_unit(unit_id, include_inactive=True)


@router.patch("/units/{unit_id}", response_model=UnitOut, dependencies=[Depends(require_permission("organization.units.update"))])
async def update_unit(unit_id: uuid.UUID, schema: UnitUpdate, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.update_unit(unit_id, schema)


@router.delete("/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("organization.units.update"))])
async def delete_unit(unit_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    await service.delete_unit(unit_id)
    return None


# ==============================================================================
# Sector
# ==============================================================================

@router.get("/sectors", response_model=list[SectorOut], dependencies=[Depends(require_permission("organization.sectors.read"))])
async def list_sectors(unit_id: uuid.UUID | None = None, include_inactive: bool = True, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.list_sectors(unit_id=unit_id, include_inactive=include_inactive)


@router.post("/sectors", response_model=SectorOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("organization.sectors.create"))])
async def create_sector(schema: SectorCreate, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.create_sector(schema)


@router.get("/sectors/{sector_id}", response_model=SectorOut, dependencies=[Depends(require_permission("organization.sectors.read"))])
async def get_sector(sector_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.get_sector(sector_id, include_inactive=True)


@router.patch("/sectors/{sector_id}", response_model=SectorOut, dependencies=[Depends(require_permission("organization.sectors.update"))])
async def update_sector(sector_id: uuid.UUID, schema: SectorUpdate, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.update_sector(sector_id, schema)


@router.delete("/sectors/{sector_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("organization.sectors.update"))])
async def delete_sector(sector_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    await service.delete_sector(sector_id)
    return None


# ==============================================================================
# Employee
# ==============================================================================

@router.get("/employees/me/details", response_model=EmployeeOut, summary="Busca o colaborador do usuário logado")
async def get_my_employee(
    payload: dict = Depends(get_token_payload), 
    db: AsyncSession = Depends(get_db)
):
    user_id = uuid.UUID(payload["sub"])
    from app.identity.repository import IdentityRepository
    repo = IdentityRepository(db)
    user = await repo.get_user(user_id)
    if not user or not user.employee_id:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Employee", user_id)
    service = OrganizationService(db)
    return await service.get_employee(user.employee_id, include_inactive=True)


@router.get("/employees", response_model=list[EmployeeOut], dependencies=[Depends(require_permission("organization.employees.read"))])
async def list_employees(unit_id: uuid.UUID | None = None, sector_id: uuid.UUID | None = None, include_inactive: bool = True, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.list_employees(unit_id=unit_id, sector_id=sector_id, include_inactive=include_inactive)


@router.post("/employees", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("organization.employees.create"))])
async def create_employee(schema: EmployeeCreate, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.create_employee(schema)


@router.get("/employees/{employee_id}", response_model=EmployeeOut, dependencies=[Depends(require_permission("organization.employees.read"))])
async def get_employee(employee_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.get_employee(employee_id, include_inactive=True)


@router.patch("/employees/{employee_id}", response_model=EmployeeOut, dependencies=[Depends(require_permission("organization.employees.update"))])
async def update_employee(employee_id: uuid.UUID, schema: EmployeeUpdate, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    return await service.update_employee(employee_id, schema)


@router.delete("/employees/{employee_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("organization.employees.update"))])
async def delete_employee(employee_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = OrganizationService(db)
    await service.delete_employee(employee_id)
    return None
