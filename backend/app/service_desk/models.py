"""
MOD-04 — Service Desk (Models)

Entidades do módulo de Service Desk:
- TicketCategory
- Ticket
- TicketInteraction
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timestamps import TimestampMixin
from app.database import Base

if TYPE_CHECKING:
    from app.organization.models import Employee  # type: ignore
    from app.identity.models import UserAccount  # type: ignore


class TicketCategory(Base, TimestampMixin):
    __tablename__ = "sd_ticket_category"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Ticket(Base, TimestampMixin):
    __tablename__ = "sd_ticket"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Enum-like strings: LOW, MEDIUM, HIGH, CRITICAL
    priority: Mapped[str] = mapped_column(String(50), nullable=False, default="LOW")
    
    # Enum-like strings: OPENED, IN_PROGRESS, PENDING, RESOLVED, CLOSED
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="OPENED")

    # Relacionamentos Externos
    requester_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), nullable=False)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user_accounts.id"), nullable=True)
    
    # Relacionamento Interno
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sd_ticket_category.id"), nullable=True)

    # Relationships
    category: Mapped["TicketCategory | None"] = relationship("TicketCategory")
    interactions: Mapped[list["TicketInteraction"]] = relationship("TicketInteraction", back_populates="ticket", cascade="all, delete-orphan")


class TicketInteraction(Base, TimestampMixin):
    __tablename__ = "sd_ticket_interaction"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sd_ticket.id"), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_accounts.id"), nullable=False)
    
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="interactions")
