import uuid
from typing import TYPE_CHECKING
from sqlalchemy import Boolean, String, Integer, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.core.timestamps import TimestampMixin
from app.core.soft_delete import SoftDeleteMixin


class StockCategory(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "stk_categories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    spec_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    items: Mapped[list["StockItem"]] = relationship("StockItem", back_populates="category")


class StockItem(Base, TimestampMixin):
    __tablename__ = "stk_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    min_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stk_categories.id"), nullable=True)
    technical_specs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    category: Mapped["StockCategory | None"] = relationship("StockCategory", back_populates="items")
    unit = relationship("Unit", back_populates="stock_items")
    movements = relationship("StockMovement", back_populates="item", cascade="all, delete-orphan")


class StockMovement(Base, TimestampMixin):
    __tablename__ = "stk_movements"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stk_items.id"), nullable=False)
    
    # Types: IN, OUT, ADJUST
    movement_type: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_accounts.id"), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    item = relationship("StockItem", back_populates="movements")
    author = relationship("UserAccount")
