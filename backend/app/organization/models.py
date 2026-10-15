"""
MOD-02 — Organização (Models)

Contém as entidades de negócio responsáveis por modelar a hierarquia
da empresa: Company, Unit, Sector e Employee.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.soft_delete import SoftDeleteMixin
from app.core.timestamps import TimestampMixin
from app.database import Base

if TYPE_CHECKING:
    from app.identity.models import UserAccount  # type: ignore

from app.stock.models import StockItem



class Company(Base, TimestampMixin, SoftDeleteMixin):
    """Representação única da empresa (Single Tenant)."""
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cnpj: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    units: Mapped[list["Unit"]] = relationship("Unit", back_populates="company", cascade="all, delete-orphan")


class Unit(Base, TimestampMixin, SoftDeleteMixin):
    """Matriz ou Filiais da empresa."""
    __tablename__ = "units"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(20), default="FILIAL", nullable=False)  # "MATRIZ" ou "FILIAL"
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    company: Mapped["Company"] = relationship("Company", back_populates="units")
    sectors: Mapped[list["Sector"]] = relationship("Sector", back_populates="unit", cascade="all, delete-orphan")
    employees: Mapped[list["Employee"]] = relationship("Employee", back_populates="unit", foreign_keys="[Employee.unit_id]")
    stock_items: Mapped[list[StockItem]] = relationship("StockItem", back_populates="unit", cascade="all, delete-orphan")


class Sector(Base, TimestampMixin, SoftDeleteMixin):
    """Setores/Departamentos dentro de uma unidade."""
    __tablename__ = "sectors"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    unit: Mapped["Unit"] = relationship("Unit", back_populates="sectors", lazy="selectin")
    employees: Mapped[list["Employee"]] = relationship("Employee", back_populates="sector", foreign_keys="[Employee.sector_id]")


class Employee(Base, TimestampMixin, SoftDeleteMixin):
    """Colaboradores vinculados a unidades e setores."""
    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"), nullable=False)
    sector_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sectors.id"), nullable=False)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"), nullable=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    registration_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    position: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ATIVO", nullable=False)  # "ATIVO", "AFASTADO", "DESLIGADO"
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    unit: Mapped["Unit"] = relationship("Unit", back_populates="employees", foreign_keys=[unit_id], lazy="selectin")
    sector: Mapped["Sector"] = relationship("Sector", back_populates="employees", foreign_keys=[sector_id], lazy="selectin")
    
    manager: Mapped["Employee | None"] = relationship("Employee", remote_side=[id], back_populates="subordinates")
    subordinates: Mapped[list["Employee"]] = relationship("Employee", back_populates="manager")

    user_account: Mapped["UserAccount | None"] = relationship("UserAccount", back_populates="employee", uselist=False)