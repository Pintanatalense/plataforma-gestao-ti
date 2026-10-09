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

if TYPE_CHECKING:
    from app.organization.models import Unit # type: ignore
    from app.identity.models import UserAccount # type: ignore
    from app.assets.models import Asset # type: ignore
    from app.stock.models import StockItem # type: ignore


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

    items: Mapped[list["InventoryAuditItem"]] = relationship("InventoryAuditItem", back_populates="audit", cascade="all, delete-orphan")
    unit = relationship("Unit")
    auditor = relationship("UserAccount")


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

    audit = relationship("InventoryAudit", back_populates="items")
    asset = relationship("Asset")
    stock_item = relationship("StockItem")
