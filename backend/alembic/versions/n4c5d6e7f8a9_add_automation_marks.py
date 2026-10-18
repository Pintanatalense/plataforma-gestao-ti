"""add automation_marks (memory of the proactive automations)

Guarda "já avisei" das automações de estoque baixo e garantia a vencer (ADR-013, fase F), para
que cada fato seja avisado uma vez e rearmado quando deixar de existir.

Revision ID: n4c5d6e7f8a9
Revises: m3b4c5d6e7f8
Create Date: 2026-10-19 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "n4c5d6e7f8a9"
down_revision: Union[str, None] = "m3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "automation_marks",
        sa.Column("key", sa.String(length=200), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("automation_marks")
