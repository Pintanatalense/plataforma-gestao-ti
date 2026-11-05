"""anexos: anexo restrito ao setor que atende o chamado (ADR-026, PR 3)

Acrescenta ``attachments.is_internal`` (padrão ``false``): os anexos existentes continuam visíveis como hoje.

Volta (downgrade): remove a coluna; os anexos que eram restritos passam a ser visíveis para quem vê o chamado.

Revision ID: c2d3e4f5a6b7c
Revises: b1c2d3e4f5a6b
Create Date: 2026-11-05 21:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "c2d3e4f5a6b7c"
down_revision: Union[str, None] = "b1c2d3e4f5a6b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "attachments", sa.Column("is_internal", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )


def downgrade() -> None:
    op.drop_column("attachments", "is_internal")