"""
MOD-15 — WhatsApp (Models)

Só as respostas rápidas (wa_templates). Configuração, sessões e fila de envio foram para o hub de
notificações (channel_configs, conversation_sessions, deliveries) — ADR-013 fase D.
"""

import uuid
from sqlalchemy import Boolean, String, Text

from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.core.timestamps import TimestampMixin


class WhatsAppTemplate(Base, TimestampMixin):
    """Templates de mensagens pré-definidas para respostas rápidas e notificações."""
    __tablename__ = "wa_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="SERVICE_DESK", index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
