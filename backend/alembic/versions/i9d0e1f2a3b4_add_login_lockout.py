"""add login lockout columns to user_accounts

Revision ID: i9d0e1f2a3b4
Revises: h8c9d0e1f2a3
Create Date: 2026-10-15 13:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "i9d0e1f2a3b4"
down_revision: Union[str, None] = "h8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_accounts",
        sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "user_accounts",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_accounts", "locked_until")
    op.drop_column("user_accounts", "failed_login_count")
