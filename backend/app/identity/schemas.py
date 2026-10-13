"""
MOD-03 — Identidade (Schemas)
"""

from datetime import datetime
import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ==============================================================================
# Permission
# ==============================================================================

class PermissionBase(BaseModel):
    code: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=255)


class PermissionOut(PermissionBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Role
# ==============================================================================

class RoleBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=255)


class RoleCreate(RoleBase):
    permission_ids: list[uuid.UUID] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    permission_ids: Optional[list[uuid.UUID]] = None


class RoleOut(RoleBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    permissions: list[PermissionOut] = []

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# UserAccount
# ==============================================================================

class UserAccountBase(BaseModel):
    employee_id: Optional[uuid.UUID] = None
    email: EmailStr
    must_change_password: bool = True
    is_admin: bool = False
    is_active: bool = True


class UserAccountCreate(UserAccountBase):
    password: str = Field(..., min_length=8)
    role_ids: list[uuid.UUID] = Field(default_factory=list)


class UserAccountUpdate(BaseModel):
    email: Optional[EmailStr] = None
    must_change_password: Optional[bool] = None
    is_admin: Optional[bool] = None
    role_ids: Optional[list[uuid.UUID]] = None
    is_active: Optional[bool] = None


class UserAccountPasswordUpdate(BaseModel):
    """Redefinição de senha por um administrador."""
    password: str = Field(..., min_length=8)


class UserAccountPasswordChange(BaseModel):
    """Troca de senha pelo próprio usuário."""
    current_password: str
    new_password: str = Field(..., min_length=8)


class UserAccountOut(BaseModel):
    id: uuid.UUID
    employee_id: Optional[uuid.UUID] = None
    # str (e não EmailStr) na saída: o dado já está persistido e domínios internos
    # como ".local" são rejeitados pelo email-validator, o que causaria erro 500.
    email: str
    must_change_password: bool
    is_admin: bool
    is_active: bool
    last_login_at: Optional[datetime] = None
    last_login_ip: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    roles: list[RoleOut] = []

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Auth
# ==============================================================================

class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    sub: Optional[str] = None
    roles: list[str] = []
    permissions: list[str] = []


# ==============================================================================
# Setup inicial (primeiro acesso da instalação)
# ==============================================================================

class SetupStatus(BaseModel):
    setup_required: bool


class InitialSetup(BaseModel):
    """Criação do primeiro administrador — só aceita enquanto não houver usuários."""
    email: EmailStr
    password: str = Field(..., min_length=8)
