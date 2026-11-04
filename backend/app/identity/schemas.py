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
    module: Optional[str] = None
    label: Optional[str] = None
    risk: Optional[str] = None
    is_critical: bool = False
    module_label: Optional[str] = None
    risk_label: Optional[str] = None
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


class PasswordChangeOut(BaseModel):
    """Resposta da troca da própria senha: as sessões antigas caem e este token substitui o atual."""

    access_token: str
    token_type: str = "bearer"


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
    # Permissões críticas concedidas individualmente (nunca vêm de perfil nem do is_admin).
    critical_permissions: list[str] = []

    model_config = ConfigDict(from_attributes=True)


class EffectivePermissionOut(BaseModel):
    """Uma permissão que a conta TEM, e de onde ela vem (calculado pelo backend, mesma regra da autorização)."""
    code: str
    label: str
    description: str
    module: str
    module_label: str
    risk: str
    risk_label: str
    is_critical: bool
    sources: list[str]


class CriticalGrantIn(BaseModel):
    permission: str = Field(..., max_length=100)
    reason: str = Field(..., min_length=5, max_length=255)


class CriticalRevokeIn(BaseModel):
    reason: str = Field(..., min_length=5, max_length=255)


class CriticalGrantOut(BaseModel):
    permission: str
    label: str
    granted_via: str
    granted_at: datetime
    granted_by_user_id: Optional[uuid.UUID] = None
    reason: Optional[str] = None


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
    """Criação do primeiro administrador — escolha entre base limpa empresarial ou demonstração."""
    email: EmailStr
    password: str = Field(..., min_length=8)
    setup_mode: str = Field("CLEAN", description="CLEAN para base limpa empresarial, DEMO para dados fictícios")
    company_name: str | None = Field(None, description="Nome da empresa contratante")
    company_cnpj: str | None = Field(None, description="CNPJ da empresa contratante")


class UserAccountPasswordChangeOut(UserAccountOut, PasswordChangeOut):
    """Usuário atualizado + token novo."""


class PasswordResetRequestIn(BaseModel):
    email: EmailStr


class PasswordResetConfirmIn(BaseModel):
    token: str = Field(..., min_length=20, max_length=200)
    new_password: str = Field(..., min_length=8, max_length=128)


class PasswordResetStatusOut(BaseModel):
    """Público: a tela só mostra "Esqueci minha senha" quando `enabled` é verdadeiro."""
    enabled: bool


class PasswordResetAcceptedOut(BaseModel):
    message: str


class PasswordResetConfigIn(BaseModel):
    enabled: bool


class PasswordResetConfigOut(BaseModel):
    enabled: bool
    smtp_ready: bool
