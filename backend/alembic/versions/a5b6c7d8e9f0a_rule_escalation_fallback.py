"""Regras: escalonamento e canal alternativo (ADR-025 M5)

Acrescenta a ``notification_rules`` o escalonamento (``escalation``, JSON vazio = sem escalonamento) e o canal
alternativo para quando a entrega falha de vez (``fallback_channel``); a ``deliveries``, a condição que a entrega de
escalonamento confere no envio (``escalation_condition``) e a ligação da entrega alternativa com a original
(``fallback_of_id``). Tudo nulo ou vazio no que já existe: nenhuma regra muda de comportamento.

Volta (downgrade): remove as quatro colunas. Entregas de escalonamento ainda pendentes passariam a sair sem conferir
a condição; por isso a volta as cancela antes.

Revision ID: a5b6c7d8e9f0a
Revises: f3a4b5c6d7e8f
Create Date: 2026-10-27 20:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "a5b6c7d8e9f0a"
down_revision: Union[str, None] = "f3a4b5c6d7e8f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notification_rules",
        sa.Column("escalation", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column("notification_rules", sa.Column("fallback_channel", sa.String(length=30), nullable=True))
    op.add_column("deliveries", sa.Column("escalation_condition", sa.String(length=30), nullable=True))
    op.add_column("deliveries", sa.Column("fallback_of_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_deliveries_fallback_of_id", "deliveries", "deliveries", ["fallback_of_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE deliveries SET status = 'CANCELLED' WHERE status = 'PENDING' AND escalation_condition IS NOT NULL"
    )
    op.drop_constraint("fk_deliveries_fallback_of_id", "deliveries", type_="foreignkey")
    op.drop_column("deliveries", "fallback_of_id")
    op.drop_column("deliveries", "escalation_condition")
    op.drop_column("notification_rules", "fallback_channel")
    op.drop_column("notification_rules", "escalation")
