"""chamados vinculados: principal e subchamados (ADR-026)

Acrescenta a ``sd_ticket``:
- ``parent_ticket_id`` (FK para o próprio ``sd_ticket``, ``ON DELETE RESTRICT``, indexada) e a ``CHECK`` que impede um
  chamado de ser pai de si mesmo;
- ``is_required`` (etapa obrigatória, padrão ``true``);
- ``replaces_ticket_id`` (subchamado que substitui uma etapa cancelada).

O status ``CANCELED`` e o estado de SLA ``CANCELED`` são só valores novos em colunas de texto.

Dados: a regra padrão ``ticket.created.requester`` passa a ignorar o ``ticket.created`` de cada subchamado (o
solicitante e o criador recebem um aviso só, ``ticket.children_created``), apenas se a condição dela ainda é a original;
uma regra editada pelo administrador fica como está.

Volta (downgrade): subchamados cancelados passam a ``CLOSED`` (o status não existe na versão anterior), as colunas são
removidas (os vínculos se perdem; nenhum chamado é apagado) e a condição da regra volta à original, se não foi editada.

Revision ID: a9b0c1d2e3f4a
Revises: f7a8b9c0d1e2f
Create Date: 2026-11-05 17:00:00.000000
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "a9b0c1d2e3f4a"
down_revision: Union[str, None] = "f7a8b9c0d1e2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RULE_CODE = "ticket.created.requester"
ORIGINAL_CONDITION = {"exclude_actor": False}
NEW_CONDITION = {"exclude_actor": False, "payload_equals": {"parent_ticket_id": None}}


def _swap_rule_condition(expected: dict, new: dict) -> None:
    bind = op.get_bind()
    row = bind.execute(
        sa.text("SELECT id, condition FROM notification_rules WHERE code = :c"), {"c": RULE_CODE}
    ).first()
    if row is None:
        return
    current = row.condition if isinstance(row.condition, dict) else json.loads(row.condition or "{}")
    if current != expected:
        return
    bind.execute(
        sa.text("UPDATE notification_rules SET condition = CAST(:c AS JSONB) WHERE id = :id"),
        {"c": json.dumps(new), "id": row.id},
    )


def upgrade() -> None:
    op.add_column("sd_ticket", sa.Column("parent_ticket_id", sa.Uuid(), nullable=True))
    op.add_column(
        "sd_ticket", sa.Column("is_required", sa.Boolean(), server_default=sa.text("true"), nullable=False)
    )
    op.add_column("sd_ticket", sa.Column("replaces_ticket_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_sd_ticket_parent_ticket_id", "sd_ticket", "sd_ticket", ["parent_ticket_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_foreign_key(
        "fk_sd_ticket_replaces_ticket_id", "sd_ticket", "sd_ticket", ["replaces_ticket_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_sd_ticket_parent_ticket_id", "sd_ticket", ["parent_ticket_id"])
    op.create_check_constraint(
        "ck_sd_ticket_not_own_parent", "sd_ticket", "parent_ticket_id IS NULL OR parent_ticket_id <> id"
    )
    _swap_rule_condition(ORIGINAL_CONDITION, NEW_CONDITION)


def downgrade() -> None:
    _swap_rule_condition(NEW_CONDITION, ORIGINAL_CONDITION)
    op.execute("UPDATE sd_ticket SET status = 'CLOSED' WHERE status = 'CANCELED'")
    op.execute("UPDATE ticket_sla_cycles SET state = 'SUPERSEDED' WHERE state = 'CANCELED'")
    op.drop_constraint("ck_sd_ticket_not_own_parent", "sd_ticket", type_="check")
    op.drop_index("ix_sd_ticket_parent_ticket_id", table_name="sd_ticket")
    op.drop_constraint("fk_sd_ticket_replaces_ticket_id", "sd_ticket", type_="foreignkey")
    op.drop_constraint("fk_sd_ticket_parent_ticket_id", "sd_ticket", type_="foreignkey")
    op.drop_column("sd_ticket", "replaces_ticket_id")
    op.drop_column("sd_ticket", "is_required")
    op.drop_column("sd_ticket", "parent_ticket_id")
