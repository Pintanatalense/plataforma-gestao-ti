"""agenda do worker: execuções com concessão (job_runs) e nova tentativa (ADR-024; Plano de Evolução, Fase 0 PR 12)

1. ``job_runs``: uma linha por execução, com concessão (``lease_until``) e no máximo uma ``running`` por job
   (índice único parcial).
2. ``scheduled_jobs.retry_attempt``: quantas tentativas seguidas falharam (0 = em dia).

Só acrescenta; nenhum dado existente muda. Volta (downgrade): remove a tabela e a coluna (perde o histórico de
execuções; a agenda continua).

Revision ID: z6d7e8f9a0b1c
Revises: y5c6d7e8f9a0b
Create Date: 2026-10-26 16:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "z6d7e8f9a0b1c"
down_revision: Union[str, None] = "y5c6d7e8f9a0b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scheduled_jobs", sa.Column("retry_attempt", sa.Integer(), server_default="0", nullable=False))
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("isolated", sa.Boolean(), nullable=False),
        sa.Column("worker_id", sa.String(length=120), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_job_runs_job_name", "job_runs", ["job_name"])
    op.create_index("ix_job_runs_job_started", "job_runs", ["job_name", "started_at"])
    op.create_index(
        "uq_job_runs_one_running", "job_runs", ["job_name"], unique=True,
        postgresql_where=sa.text("status = 'running'"), sqlite_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index("uq_job_runs_one_running", table_name="job_runs")
    op.drop_index("ix_job_runs_job_started", table_name="job_runs")
    op.drop_index("ix_job_runs_job_name", table_name="job_runs")
    op.drop_table("job_runs")
    op.drop_column("scheduled_jobs", "retry_attempt")
