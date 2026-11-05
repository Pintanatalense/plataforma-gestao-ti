"""SLA: marcas de alerta de proximidade nos ciclos e de aviso nas violações (ADR-017 P4-S3)

Só acrescenta colunas nulas. Violações que já existiam são dadas como avisadas (`notified_at = detected_at`), para o
primeiro `sla.check` não disparar avisos antigos. Volta (downgrade): remove as colunas.

Revision ID: c0d1e2f3a4b5c
Revises: b9c0d1e2f3a4b
Create Date: 2026-10-27 09:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "c0d1e2f3a4b5c"
down_revision: Union[str, None] = "b9c0d1e2f3a4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ticket_sla_cycles", sa.Column("first_response_warned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ticket_sla_cycles", sa.Column("resolution_warned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sla_breaches", sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE sla_breaches SET notified_at = detected_at")


def downgrade() -> None:
    op.drop_column("sla_breaches", "notified_at")
    op.drop_column("ticket_sla_cycles", "resolution_warned_at")
    op.drop_column("ticket_sla_cycles", "first_response_warned_at")
