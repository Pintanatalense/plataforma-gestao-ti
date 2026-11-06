"""auditoria imutável: gatilho só-inserção, selo em cadeia de hash e retenção como único DELETE (ADR-023; Plano de Evolução, Fase 0 PR 11; S4)

1. ``audit_logs`` ganha ``chain_pos``, ``prev_hash`` e ``row_hash`` (nulos até o selo) e o índice único
   (``category``, ``chain_pos``); nova tabela ``audit_chain_state`` (fim e âncora de cada cadeia).
2. Funções e gatilhos de ``app/audit/chain_ddl.py`` versão **V1** (congelada): ``audit_logs_guard`` (sem UPDATE,
   DELETE nem TRUNCATE fora do selo e da retenção), ``audit_seal``, ``audit_purge`` e ``audit_verify``.
   Os registros existentes são selados pelo job ``audit.seal`` do worker, em ordem de criação.

Migrations futuras que precisem corrigir dados da auditoria terão de desligar o gatilho de forma explícita e
registrada (``ALTER TABLE audit_logs DISABLE TRIGGER audit_logs_guard`` ... ``ENABLE``) e selar de novo.

Volta (downgrade): remove gatilhos, funções, a tabela de estado e as colunas do selo. Perde só o selo (a cadeia);
os registros ficam.

Revision ID: y5c6d7e8f9a0b
Revises: x4b5c6d7e8f9a
Create Date: 2026-10-26 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.audit.chain_ddl import CHAIN_DDL_V1, CHAIN_DROP_V1

# revision identifiers
revision: str = "y5c6d7e8f9a0b"
down_revision: Union[str, None] = "x4b5c6d7e8f9a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("chain_pos", sa.BigInteger(), nullable=True))
    op.add_column("audit_logs", sa.Column("prev_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("row_hash", sa.String(length=64), nullable=True))
    op.create_index("uq_audit_logs_category_chain_pos", "audit_logs", ["category", "chain_pos"], unique=True)
    op.create_table(
        "audit_chain_state",
        sa.Column("category", sa.String(length=20), primary_key=True),
        sa.Column("last_pos", sa.BigInteger(), nullable=False),
        sa.Column("last_hash", sa.String(length=64), nullable=False),
        sa.Column("anchor_pos", sa.BigInteger(), nullable=False),
        sa.Column("anchor_hash", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    bind = op.get_bind()
    for statement in CHAIN_DDL_V1:
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    bind = op.get_bind()
    for statement in CHAIN_DROP_V1:
        bind.exec_driver_sql(statement)
    op.drop_table("audit_chain_state")
    op.drop_index("uq_audit_logs_category_chain_pos", table_name="audit_logs")
    for column in ("row_hash", "prev_hash", "chain_pos"):
        op.drop_column("audit_logs", column)
