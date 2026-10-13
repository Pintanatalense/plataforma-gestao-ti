"""
MOD-02 — Organização (Schemas)
"""

from datetime import datetime
import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ==============================================================================
# Company
# ==============================================================================

class CompanyBase(BaseModel):
    name: str = Field(..., max_length=255)
    cnpj: Optional[str] = Field(None, max_length=20)
    logo_url: Optional[str] = Field(None, max_length=255)


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    cnpj: Optional[str] = Field(None, max_length=20)
    logo_url: Optional[str] = Field(None, max_length=255)


class CompanyOut(CompanyBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


from pydantic import BaseModel, ConfigDict, Field, computed_field


# ==============================================================================
# Unit
# ==============================================================================

class UnitBase(BaseModel):
    name: str = Field(..., max_length=255)
    code: str = Field(..., max_length=50)
    type: str = Field(default="FILIAL", max_length=20)
    address: Optional[str] = None
    is_active: bool = True


class UnitCreate(UnitBase):
    company_id: Optional[uuid.UUID] = None


class UnitUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    code: Optional[str] = Field(None, max_length=50)
    type: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = None
    is_active: Optional[bool] = None


class UnitOut(UnitBase):
    id: uuid.UUID
    company_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Sector
# ==============================================================================

class SectorBase(BaseModel):
    unit_id: uuid.UUID
    name: str = Field(..., max_length=255)
    code: str = Field(..., max_length=50)
    is_active: bool = True


class SectorCreate(SectorBase):
    pass


class SectorUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    code: Optional[str] = Field(None, max_length=50)
    unit_id: Optional[uuid.UUID] = None
    is_active: Optional[bool] = None


class SectorOut(SectorBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    unit: Optional[UnitOut] = None

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Employee
# ==============================================================================

class EmployeeBase(BaseModel):
    sector_id: uuid.UUID
    unit_id: Optional[uuid.UUID] = None
    manager_id: Optional[uuid.UUID] = None
    name: str = Field(..., max_length=255)
    registration_number: Optional[str] = Field(None, max_length=50)
    registration: Optional[str] = Field(None, max_length=50)
    position: Optional[str] = Field(None, max_length=255)
    job_title: Optional[str] = Field(None, max_length=255)
    status: str = Field(default="ATIVO", max_length=20)
    is_active: bool = True


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(BaseModel):
    unit_id: Optional[uuid.UUID] = None
    sector_id: Optional[uuid.UUID] = None
    manager_id: Optional[uuid.UUID] = None
    name: Optional[str] = Field(None, max_length=255)
    registration_number: Optional[str] = Field(None, max_length=50)
    registration: Optional[str] = Field(None, max_length=50)
    position: Optional[str] = Field(None, max_length=255)
    job_title: Optional[str] = Field(None, max_length=255)
    status: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None


class EmployeeOut(BaseModel):
    id: uuid.UUID
    unit_id: uuid.UUID
    sector_id: uuid.UUID
    manager_id: Optional[uuid.UUID] = None
    name: str
    registration_number: str
    position: Optional[str] = None
    status: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deactivated_at: Optional[datetime] = None
    sector: Optional[SectorOut] = None
    unit: Optional[UnitOut] = None

    @computed_field
    def registration(self) -> str:
        return self.registration_number

    @computed_field
    def job_title(self) -> Optional[str]:
        return self.position

    model_config = ConfigDict(from_attributes=True)
