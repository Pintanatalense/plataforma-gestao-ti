"""
MOD-08 - Inventário (Models)
"""

import uuid
from typing import TYPE_CHECKING
from datetime import datetime

from sqlalchemy import ForeignKey, String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.soft_delete import SoftDeleteMixin
from app.core.timestamps import TimestampMixin
from app.database import Base

from app.organization.models import Unit
from app.identity.models import UserAccount
from app.assets.models import Asset
from app.stock.models import StockItem


class InventoryAudit(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "inventory_audits"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # "OPENED", "IN_PROGRESS", "CLOSED", "CANCELLED"
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="OPENED")
    
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"), nullable=False)
    auditor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_accounts.id"), nullable=False)
    
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    items: Mapped[list["InventoryAuditItem"]] = relationship(
        "InventoryAuditItem", back_populates="audit", cascade="all, delete-orphan", lazy="selectin"
    )
    unit: Mapped[Unit | None] = relationship("Unit", lazy="selectin")
    auditor: Mapped[UserAccount | None] = relationship("UserAccount", lazy="selectin")

    @property
    def unit_name(self) -> str:
        if self.unit:
            return self.unit.name
        return ""

    @property
    def auditor_name(self) -> str:
        if self.auditor:
            if hasattr(self.auditor, "employee") and self.auditor.employee and self.auditor.employee.name:
                reg = getattr(self.auditor.employee, "registration_number", None)
                return f"{self.auditor.employee.name} ({reg})" if reg else self.auditor.employee.name
            return self.auditor.email
        return ""


class InventoryAuditItem(Base, TimestampMixin):
    __tablename__ = "inventory_audit_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_audits.id"), nullable=False)
    
    # Podemos auditar tanto Ativos (Assets) quanto Estoque (StockItems)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    stock_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stk_items.id"), nullable=True)
    
    item_type: Mapped[str] = mapped_column(String(20), nullable=False) # "ASSET" ou "STOCK"

    # Status e Quantidades
    expected_status: Mapped[str | None] = mapped_column(String(50), nullable=True) # Para Assets (ex: IN_USE)
    actual_status: Mapped[str | None] = mapped_column(String(50), nullable=True) # Para Assets (ex: FOUND, MISSING)
    
    expected_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True) # Para Stock
    actual_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True) # Para Stock
    
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    audit: Mapped[InventoryAudit] = relationship("InventoryAudit", back_populates="items")
    asset: Mapped[Asset | None] = relationship("Asset", lazy="selectin")
    stock_item: Mapped[StockItem | None] = relationship("StockItem", lazy="selectin")

    @property
    def item_name(self) -> str:
        if self.item_type == "ASSET" and self.asset:
            return self.asset.name
        if self.item_type == "STOCK" and self.stock_item:
            return self.stock_item.name
        return ""

    @property
    def item_code(self) -> str:
        if self.item_type == "ASSET" and self.asset:
            return self.asset.tag
        if self.item_type == "STOCK" and self.stock_item:
            return ""
        return ""
