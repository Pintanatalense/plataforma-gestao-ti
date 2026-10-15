"""
MOD-14 — Backups do Banco de Dados (Models)

Entidade de rastreabilidade e histórico de backups do PostgreSQL:
- DatabaseBackup (db_backups)
"""

import uuid
from sqlalchemy import String, Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.core.timestamps import TimestampMixin


class DatabaseBackup(Base, TimestampMixin):
    __tablename__ = "db_backups"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SUCCESS")  # "SUCCESS", "FAILED"
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user_accounts.id"), nullable=True)

    created_by = relationship("UserAccount", lazy="selectin")

    @property
    def created_by_email(self) -> str | None:
        return self.created_by.email if self.created_by else "Sistema / Automático"
