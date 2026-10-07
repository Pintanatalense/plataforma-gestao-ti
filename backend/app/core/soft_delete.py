"""
Mixin de exclusão lógica (soft delete) para models SQLAlchemy.

Implementa o padrão de exclusão lógica conforme DEC-004 (histórico permanente).
Entidades com soft delete nunca são removidas fisicamente do banco.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column


class SoftDeleteMixin:
    """
    Mixin que adiciona soft delete a qualquer model.

    Campos adicionados:
        - is_active: indica se o registro está ativo
        - deleted_at: timestamp da exclusão lógica (nullable)

    Uso:
        class MyModel(Base, TimestampMixin, SoftDeleteMixin):
            __tablename__ = "my_table"
            ...

    Importante:
        As queries devem filtrar por is_active=True por padrão.
        Isso é responsabilidade do repository de cada módulo.
    """

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
        index=True,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    def soft_delete(self) -> None:
        """Marca o registro como excluído logicamente."""
        self.is_active = False
        self.deleted_at = datetime.now(timezone.utc)

    def restore(self) -> None:
        """Restaura um registro excluído logicamente."""
        self.is_active = True
        self.deleted_at = None
