"""chamados: chaves de idempotência das rotas de criação (ADR-026, PR 2b)

Cria ``sd_idempotency_keys``: ``UNIQUE (user_id, key)`` válida em todas as rotas, a operação (``endpoint`` e
``target_id``), o hash do corpo e os chamados criados. O job ``retention.cleanup`` apaga as chaves com mais de 48 h.

Volta (downgrade): remove a tabela; as chaves são descartáveis.

Revision ID: b1c2d3e4f5a6b
Revises: a9b0c1d2e3f4a
Create Date: 2026-11-05 19:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision: str = "b1c2d3e4f5a6b"
down_revision: Union[str, None] = "a9b0c1d2e3f4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sd_idempotency_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("endpoint", sa.String(length=60), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_ids", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "key", name="uq_sd_idempotency_keys_user_key"),
    )
    op.create_index("ix_sd_idempotency_keys_created_at", "sd_idempotency_keys", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_sd_idempotency_keys_created_at", table_name="sd_idempotency_keys")
    op.drop_table("sd_idempotency_keys")
