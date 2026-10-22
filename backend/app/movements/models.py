"""
MOD-06 — Movimentações (Models)

Entidades para histórico e transição de ativos.
- AssetMovement
"""

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timestamps import TimestampMixin
from app.database import Base

if TYPE_CHECKING:
    pass  # type: ignore


class MovementType(enum.StrEnum):
    INITIAL_STOCK = "INITIAL_STOCK"
    RESERVATION = "RESERVATION"
    RESERVATION_CANCEL = "RESERVATION_CANCEL"
    ASSIGNMENT = "ASSIGNMENT"
    RETURN = "RETURN"
    INSPECTION_RELEASE = "INSPECTION_RELEASE"
    TRANSFER = "TRANSFER"
    MAINTENANCE = "MAINTENANCE"
    DECOMMISSION = "DECOMMISSION"


class AssetMovement(Base, TimestampMixin):
    __tablename__ = "asset_movements"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)

    # "INITIAL_STOCK", "RESERVATION", "RESERVATION_CANCEL", "ASSIGNMENT", "RETURN", "INSPECTION_RELEASE", "TRANSFER", "MAINTENANCE", "DECOMMISSION"
    movement_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # State tracking
    from_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("units.id"), nullable=True)
    to_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("units.id"), nullable=True)

    from_employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    to_employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"), nullable=True)

    # Optional status change tracking
    status_from: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status_to: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Vínculo formal com Chamado do Service Desk (quando aplicável)
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sd_ticket.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Details
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Performed by (who registered the movement in the system)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_accounts.id"), nullable=False)

    asset = relationship("Asset")
    author = relationship("UserAccount")
    ticket = relationship("Ticket", foreign_keys=[ticket_id])

    # Note: These relationships avoid circular imports by referring to string class names,
    # but we will resolve them appropriately in the application logic.
    from_unit = relationship("Unit", foreign_keys=[from_unit_id])
    to_unit = relationship("Unit", foreign_keys=[to_unit_id])
    from_employee = relationship("Employee", foreign_keys=[from_employee_id])
    to_employee = relationship("Employee", foreign_keys=[to_employee_id])
