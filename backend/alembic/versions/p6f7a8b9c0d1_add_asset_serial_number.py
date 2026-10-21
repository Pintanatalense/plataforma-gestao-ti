"""add serial_number to assets

Chave de casamento para a importação de inventário do GLPI Agent (XML):
permite achar um Asset já cadastrado pelo número de série do equipamento.

Revision ID: p6f7a8b9c0d1
Revises: o5d6e7f8a9b0
Create Date: 2026-10-21 11:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "p6f7a8b9c0d1"
down_revision: Union[str, None] = "o5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("serial_number", sa.String(length=100), nullable=True))
    op.create_index("ix_assets_serial_number", "assets", ["serial_number"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_assets_serial_number", table_name="assets")
    op.drop_column("assets", "serial_number")
