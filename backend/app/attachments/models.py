import uuid
from sqlalchemy import Boolean, String, Integer, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.core.timestamps import TimestampMixin
from app.core.soft_delete import SoftDeleteMixin


class Attachment(Base, TimestampMixin, SoftDeleteMixin):
    """Modelo para metadados de anexos armazenados em disco (MOD-10)."""
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    
    # Informações do Arquivo
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False) # Caminho relativo onde o arquivo está salvo
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    # Polimorfismo / Vínculo com outras entidades
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True) # Ex: TICKET, TICKET_INTERACTION, ASSET
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    
    # Restrito ao setor que atende o chamado (ADR-026): some da listagem e o download direto dá 404 para os demais.
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)

    # Autoria
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True)
