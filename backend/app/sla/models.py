"""Modelos de SLA (ADR-017). Esta etapa só cria as tabelas; a integração com chamados vem depois."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timestamps import TimestampMixin
from app.database import Base

REOPEN_RULES = ("RESTART", "CONTINUE")
CYCLE_STATES = ("RUNNING", "PAUSED", "MET", "BREACHED", "SUPERSEDED")
BREACH_KINDS = ("FIRST_RESPONSE", "RESOLUTION")


class SlaCalendar(Base, TimestampMixin):
    __tablename__ = "sla_calendars"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/Sao_Paulo")
    # {"0": [["08:00", "18:00"]], ...}: dia da semana (0 = segunda) -> intervalos de expediente
    weekly_hours: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    holidays: Mapped[list["SlaHoliday"]] = relationship(
        "SlaHoliday", back_populates="calendar", cascade="all, delete-orphan", order_by="SlaHoliday.day"
    )


class SlaHoliday(Base):
    __tablename__ = "sla_holidays"
    __table_args__ = (UniqueConstraint("calendar_id", "day", name="uq_sla_holidays_calendar_day"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    calendar_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sla_calendars.id", ondelete="CASCADE"), nullable=False, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    calendar: Mapped["SlaCalendar"] = relationship("SlaCalendar", back_populates="holidays")


class SlaPolicy(Base, TimestampMixin):
    __tablename__ = "sla_policies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    calendar_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sla_calendars.id"), nullable=False, index=True)
    # Só PENDING (padrão) e IN_PROGRESS são aceitos; OPENED nunca (o relógio não pode nascer pausado).
    pause_statuses: Mapped[list] = mapped_column(JSONB, nullable=False, default=lambda: ["PENDING"])
    reopen_rule: Mapped[str] = mapped_column(String(16), nullable=False, default="RESTART")
    alert_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=80)

    calendar: Mapped["SlaCalendar"] = relationship("SlaCalendar")
    targets: Mapped[list["SlaPolicyTarget"]] = relationship(
        "SlaPolicyTarget", back_populates="policy", cascade="all, delete-orphan"
    )


class SlaPolicyTarget(Base):
    __tablename__ = "sla_policy_targets"
    __table_args__ = (UniqueConstraint("policy_id", "priority", name="uq_sla_policy_targets_policy_priority"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sla_policies.id", ondelete="CASCADE"), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(50), nullable=False)
    first_response_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    resolution_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    policy: Mapped["SlaPolicy"] = relationship("SlaPolicy", back_populates="targets")


class TicketSlaCycle(Base, TimestampMixin):
    """Um ciclo de SLA de um chamado. `snapshot` guarda a cópia da política e do calendário vigentes no início."""

    __tablename__ = "ticket_sla_cycles"
    __table_args__ = (UniqueConstraint("ticket_id", "cycle", name="uq_ticket_sla_cycles_ticket_cycle"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sd_ticket.id", ondelete="CASCADE"), nullable=False, index=True)
    cycle: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sla_policies.id", ondelete="SET NULL"), nullable=True)
    priority: Mapped[str] = mapped_column(String(50), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_response_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remaining_first_response_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remaining_resolution_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paused_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING", index=True)

    breaches: Mapped[list["SlaBreach"]] = relationship("SlaBreach", back_populates="cycle", cascade="all, delete-orphan")


class SlaBreach(Base):
    __tablename__ = "sla_breaches"
    __table_args__ = (UniqueConstraint("cycle_id", "kind", name="uq_sla_breaches_cycle_kind"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    cycle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ticket_sla_cycles.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    cycle: Mapped["TicketSlaCycle"] = relationship("TicketSlaCycle", back_populates="breaches")
