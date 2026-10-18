"""add user notification preferences

Revision ID: k1f2a3b4c5d6
Revises: j0e1f2a3b4c5
Create Date: 2026-10-17 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "k1f2a3b4c5d6"
down_revision: Union[str, None] = "j0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "user_notification_prefs",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("channels_disabled", JSONB, nullable=False, server_default="[]"),
        sa.Column("categories_disabled", JSONB, nullable=False, server_default="[]"),
        sa.Column("quiet_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("quiet_start", sa.String(5), nullable=False, server_default="20:00"),
        sa.Column("quiet_end", sa.String(5), nullable=False, server_default="07:00"),
        sa.Column("critical_bypass", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("user_notification_prefs")
