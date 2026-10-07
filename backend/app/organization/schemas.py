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


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    cnpj: Optional[str] = Field(None, max_length=20)


class CompanyOut(CompanyBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Unit
# ==============================================================================

class UnitBase(BaseModel):
    company_id: uuid.UUID
    name: str = Field(..., max_length=255)
    code: str = Field(..., max_length=50)
    type: str = Field(default="FILIAL", max_length=20)
    address: Optional[str] = None


class UnitCreate(UnitBase):
    pass


class UnitUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    code: Optional[str] = Field(None, max_length=50)
    type: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = None


class UnitOut(UnitBase):
    id: uuid.UUID
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


class SectorCreate(SectorBase):
    pass


class SectorUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    code: Optional[str] = Field(None, max_length=50)


class SectorOut(SectorBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Employee
# ==============================================================================

class EmployeeBase(BaseModel):
    unit_id: uuid.UUID
    sector_id: uuid.UUID
    manager_id: Optional[uuid.UUID] = None
    name: str = Field(..., max_length=255)
    registration_number: str = Field(..., max_length=50)
    position: Optional[str] = Field(None, max_length=255)
    status: str = Field(default="ATIVO", max_length=20)


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(BaseModel):
    unit_id: Optional[uuid.UUID] = None
    sector_id: Optional[uuid.UUID] = None
    manager_id: Optional[uuid.UUID] = None
    name: Optional[str] = Field(None, max_length=255)
    registration_number: Optional[str] = Field(None, max_length=50)
    position: Optional[str] = Field(None, max_length=255)
    status: Optional[str] = Field(None, max_length=20)


class EmployeeOut(EmployeeBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    deactivated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
