"""
Mixins de timestamps para models SQLAlchemy.

Fornece campos created_at e updated_at automáticos em UTC.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """
    Mixin que adiciona created_at e updated_at a qualquer model.

    Uso:
        class MyModel(Base, TimestampMixin):
            __tablename__ = "my_table"
            ...
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
