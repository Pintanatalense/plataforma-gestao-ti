"""
MOD-03 — Identidade (Models)

Contém as entidades responsáveis por usuários do sistema, contas de acesso,
e a camada de RBAC (Role-Based Access Control) associada ao colaborador.
"""

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Table, Column, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.soft_delete import SoftDeleteMixin
from app.core.timestamps import TimestampMixin
from app.database import Base

from app.organization.models import Employee


# Tabela associativa entre UserAccount e Role
user_role_association = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("user_accounts.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

# Tabela associativa entre Role e Permission
role_permission_association = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class UserAccount(Base, TimestampMixin, SoftDeleteMixin):
    """Conta de acesso do sistema, 1:1 com Employee."""
    __tablename__ = "user_accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"), unique=True, nullable=True)

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Flags de acesso
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # Superadmin
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    
    # Versão da sessão: todo token carrega a versão vigente (claim `tv`); incrementar invalida os tokens
    # já emitidos (troca/reset de senha, desativação, mudança de perfil). Ver ADR-016.
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    # Bloqueio temporário após tentativas de login inválidas
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(String(50), nullable=True)

    employee: Mapped["Employee | None"] = relationship("Employee", back_populates="user_account", lazy="selectin")
    roles: Mapped[list["Role"]] = relationship("Role", secondary=user_role_association, back_populates="users")


class Role(Base, TimestampMixin):
    """Perfil de acesso (Ex: TÉCNICO_TI, GESTOR, COLABORADOR)."""
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    users: Mapped[list["UserAccount"]] = relationship("UserAccount", secondary=user_role_association, back_populates="roles")
    permissions: Mapped[list["Permission"]] = relationship("Permission", secondary=role_permission_association, back_populates="roles")


class Permission(Base, TimestampMixin):
    """Permissão granular (Ex: tickets.read, tickets.create, assets.delete)."""
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)  # module.resource.action
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    roles: Mapped[list["Role"]] = relationship("Role", secondary=role_permission_association, back_populates="permissions")
