"""
MOD-15 — WhatsApp Integration (Models)

Tabelas para configuração do bot e persistência de sessões/estados conversacionais:
- WhatsAppConfig (wa_configs)
- WhatsAppSession (wa_sessions)
"""

import uuid
from datetime import datetime
from sqlalchemy import Boolean, String, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.core.timestamps import TimestampMixin


class WhatsAppConfig(Base, TimestampMixin):
    __tablename__ = "wa_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(50), default="NONE", nullable=False)  # "EVOLUTION_API", "META_CLOUD_API", "MOCK" (só desenvolvimento), "NONE"
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    api_url: Mapped[str] = mapped_column(String(255), default="http://evolution-api:8080", nullable=False)
    api_key: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    instance_name: Mapped[str] = mapped_column(String(100), default="gestao_ti", nullable=False)
    webhook_secret: Mapped[str | None] = mapped_column(String(100), nullable=True)
    
    welcome_message: Mapped[str] = mapped_column(
        Text,
        default="Olá! Bem-vindo ao atendimento de TI via WhatsApp. Digite [1] para abrir chamado, [2] para consultar seus chamados ou [3] para responder a um chamado.",
        nullable=False
    )

    # Proteção Anti-Ban e Humanização de Disparos
    anti_ban_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    min_delay_seconds: Mapped[int] = mapped_column(default=4, nullable=False)
    max_delay_seconds: Mapped[int] = mapped_column(default=10, nullable=False)
    simulate_typing: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    typing_duration_seconds: Mapped[int] = mapped_column(default=2, nullable=False)
    max_messages_per_minute: Mapped[int] = mapped_column(default=12, nullable=False)
    cooldown_per_recipient_seconds: Mapped[int] = mapped_column(default=15, nullable=False)
    emergency_pause: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class WhatsAppSession(Base, TimestampMixin):
    __tablename__ = "wa_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    phone: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    
    # Estados da Máquina de Atendimento
    # IDLE, AWAITING_REGISTRATION_LINK, AWAITING_CATEGORY, AWAITING_TITLE, AWAITING_DESCRIPTION, AWAITING_INTERACTION_TICKET, AWAITING_INTERACTION_MSG
    state: Mapped[str] = mapped_column(String(50), default="IDLE", nullable=False)
    
    current_ticket_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sd_ticket.id", ondelete="SET NULL"), nullable=True)
    current_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sd_ticket_category.id", ondelete="SET NULL"), nullable=True)
    
    context_data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    employee = relationship("Employee", lazy="selectin")
    current_ticket = relationship("Ticket", lazy="selectin")


class WhatsAppTemplate(Base, TimestampMixin):
    """Templates de mensagens pré-definidas para respostas rápidas e notificações."""
    __tablename__ = "wa_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="SERVICE_DESK", index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class WhatsAppOutbox(Base, TimestampMixin):
    """Fila de envios com controle de taxa e proteção anti-bloqueio."""
    __tablename__ = "wa_outbox"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    to_phone: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    
    # PENDING, SENDING, SENT, FAILED, CANCELLED
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True, nullable=False)
    priority: Mapped[int] = mapped_column(default=2, nullable=False)  # 1-Alta, 2-Normal, 3-Baixa
    
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sd_ticket.id", ondelete="SET NULL"), nullable=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("wa_templates.id", ondelete="SET NULL"), nullable=True)
    
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(default=3, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    ticket = relationship("app.service_desk.models.Ticket", lazy="selectin")
    template = relationship("WhatsAppTemplate", lazy="selectin")

