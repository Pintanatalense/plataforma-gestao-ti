"""
MOD-05 — Ativos (Models)

Entidades do módulo de Gestão Patrimonial:
- AssetCategory
- Asset
"""

import enum
import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.soft_delete import SoftDeleteMixin
from app.core.timestamps import TimestampMixin
from app.database import Base
from app.organization.models import Employee, Unit


class AssetStatus(enum.StrEnum):
    IN_STOCK = "IN_STOCK"
    RESERVED = "RESERVED"
    IN_USE = "IN_USE"
    PENDING_INSPECTION = "PENDING_INSPECTION"
    MAINTENANCE = "MAINTENANCE"
    DECOMMISSIONED = "DECOMMISSIONED"


class AssetCategory(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "asset_categories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    spec_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    assets: Mapped[list["Asset"]] = relationship("Asset", back_populates="category")


class Asset(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tag: Mapped[str] = mapped_column(String(50), nullable=False, unique=True) # Patrimônio
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asset_categories.id"), nullable=False)

    # "IN_STOCK", "IN_USE", "MAINTENANCE", "DECOMMISSIONED"
    status: Mapped[str] = mapped_column(String(50), nullable=False, default=AssetStatus.IN_STOCK.value)

    technical_specs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    warranty_expires: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    # Localização / Responsável
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"), nullable=False)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"), nullable=True)

    category: Mapped["AssetCategory"] = relationship("AssetCategory", back_populates="assets")

    # Relationships for organization (avoiding circular imports with simple string reference where needed)
    # They would need to be added to Unit and Employee as well to be fully bidirectional,
    # but for now we just define the one-way relation or rely on string resolution.
    unit = relationship("Unit")
    employee = relationship("Employee")
