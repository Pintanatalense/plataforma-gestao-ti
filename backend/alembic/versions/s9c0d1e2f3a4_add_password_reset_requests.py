"""add password_reset_requests (recuperação de senha, ADR-018)

Tabela de pedidos de recuperação de senha: guarda só o hash do token e o hash do e-mail. Migration aditiva
(não altera nenhuma tabela existente).

Revision ID: s9c0d1e2f3a4
Revises: r8b9c0d1e2f3
Create Date: 2026-10-22 16:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "s9c0d1e2f3a4"
down_revision: Union[str, None] = "r8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "password_reset_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("requested_ip", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_password_reset_requests_user_id", "password_reset_requests", ["user_id"])
    op.create_index("ix_password_reset_requests_email_hash", "password_reset_requests", ["email_hash"])
    op.create_index("ix_password_reset_requests_token_hash", "password_reset_requests", ["token_hash"], unique=True)
    op.create_index("ix_password_reset_requests_requested_ip", "password_reset_requests", ["requested_ip"])


def downgrade() -> None:
    op.drop_table("password_reset_requests")
