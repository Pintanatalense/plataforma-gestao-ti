"""entregas: confirmação do provedor separada de SENT (ADR-025 M1)

``deliveries`` ganha ``provider_status`` (accepted, delivered, read, failed) e ``provider_status_at``, nulos até a
integração confirmar algo, e o índice (canal, id da mensagem no provedor) para achar a entrega quando a confirmação
chega pelo webhook. ``SENT`` continua significando "aceito pelo gateway". Só acrescenta.

Volta (downgrade): remove o índice e as colunas (perde só as confirmações recebidas).

Revision ID: d1e2f3a4b5c6d
Revises: c0d1e2f3a4b5c
Create Date: 2026-10-27 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "d1e2f3a4b5c6d"
down_revision: Union[str, None] = "c0d1e2f3a4b5c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("deliveries", sa.Column("provider_status", sa.String(length=20), nullable=True))
    op.add_column("deliveries", sa.Column("provider_status_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_deliveries_channel_provider_message", "deliveries", ["channel", "provider_message_id"])


def downgrade() -> None:
    op.drop_index("ix_deliveries_channel_provider_message", table_name="deliveries")
    op.drop_column("deliveries", "provider_status_at")
    op.drop_column("deliveries", "provider_status")
