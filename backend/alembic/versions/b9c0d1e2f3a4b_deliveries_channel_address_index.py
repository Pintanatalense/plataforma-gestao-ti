"""índice em deliveries (canal, endereço, envio) para o teto por pessoa por hora do WhatsApp (Fase 0 PR 14)

A contagem "enviadas para este número na última hora" (ritmo anti-banimento, ADR-019 C3) varria a tabela inteira de
entregas. Só acrescenta o índice. Volta (downgrade): remove o índice.

Revision ID: b9c0d1e2f3a4b
Revises: a8b9c0d1e2f3a
Create Date: 2026-10-26 22:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers
revision: str = "b9c0d1e2f3a4b"
down_revision: Union[str, None] = "a8b9c0d1e2f3a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_deliveries_channel_address_sent", "deliveries", ["channel", "address", "sent_at"])


def downgrade() -> None:
    op.drop_index("ix_deliveries_channel_address_sent", table_name="deliveries")
