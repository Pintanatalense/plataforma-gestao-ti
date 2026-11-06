"""chamados: criador registrado e abertura em nome de outra pessoa (chamados vinculados, PR 1)

1. ``sd_ticket`` ganha ``created_by_user_id`` (quem abriu; pode ser diferente do solicitante) e ``creator_unknown``.
   O criador dos chamados existentes vem do ator do evento ``ticket.created`` na auditoria, se a conta ainda existe;
   os que não têm esse registro (seeds, demonstração, trilha já expirada) ficam com ``creator_unknown = true``.
   Depois disso a ``CHECK`` exige criador ou a marca, e o gatilho ``sd_ticket_creator_guard``
   (``app/service_desk/creator_ddl.py``, V1 congelada) impede um chamado NOVO de usar a marca: a exceção vale só para
   as linhas que esta migration marcou, nunca por data.
2. Permissão nova ``service_desk.tickets.create_on_behalf`` (abrir em nome de outra pessoa), sem concessão automática.

Volta (downgrade): remove gatilho, ``CHECK``, colunas (perde o registro de quem abriu) e a permissão (por cascata, os
vínculos com perfis). Nenhum chamado é apagado.

Revision ID: e5f6a7b8c9d0e
Revises: a5b6c7d8e9f0a
Create Date: 2026-11-05 10:00:00.000000
"""

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.service_desk.creator_ddl import CREATOR_GUARD_DDL_V1, CREATOR_GUARD_DROP_V1

# revision identifiers
revision: str = "e5f6a7b8c9d0e"
down_revision: Union[str, None] = "a5b6c7d8e9f0a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CREATE_ON_BEHALF = "service_desk.tickets.create_on_behalf"


def upgrade() -> None:
    op.add_column("sd_ticket", sa.Column("created_by_user_id", sa.Uuid(), nullable=True))
    op.add_column(
        "sd_ticket", sa.Column("creator_unknown", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    op.create_foreign_key(
        "fk_sd_ticket_created_by_user_id", "sd_ticket", "user_accounts", ["created_by_user_id"], ["id"]
    )
    op.create_index("ix_sd_ticket_created_by_user_id", "sd_ticket", ["created_by_user_id"])

    bind = op.get_bind()
    # Criador = ator do primeiro "ticket.created" da trilha, se a conta ainda existe.
    bind.execute(
        sa.text(
            """
            UPDATE sd_ticket t SET created_by_user_id = a.user_id
            FROM (
                SELECT DISTINCT ON (entity_id) entity_id, user_id
                FROM audit_logs
                WHERE entity_type = 'ticket' AND event_type = 'ticket.created' AND user_id IS NOT NULL
                ORDER BY entity_id, created_at
            ) a
            WHERE t.id = a.entity_id AND EXISTS (SELECT 1 FROM user_accounts u WHERE u.id = a.user_id)
            """
        )
    )
    bind.execute(sa.text("UPDATE sd_ticket SET creator_unknown = true WHERE created_by_user_id IS NULL"))
    op.create_check_constraint(
        "ck_sd_ticket_creator_known", "sd_ticket", "created_by_user_id IS NOT NULL OR creator_unknown"
    )
    for statement in CREATOR_GUARD_DDL_V1:
        bind.exec_driver_sql(statement)

    if bind.execute(sa.text("SELECT 1 FROM permissions WHERE code = :c"), {"c": CREATE_ON_BEHALF}).first() is None:
        now = datetime.now(timezone.utc)
        bind.execute(
            sa.text(
                "INSERT INTO permissions (id, code, is_critical, created_at, updated_at) "
                "VALUES (:id, :c, false, :now, :now)"
            ),
            {"id": uuid.uuid4(), "c": CREATE_ON_BEHALF, "now": now},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for statement in CREATOR_GUARD_DROP_V1:
        bind.exec_driver_sql(statement)
    op.drop_constraint("ck_sd_ticket_creator_known", "sd_ticket", type_="check")
    op.drop_index("ix_sd_ticket_created_by_user_id", table_name="sd_ticket")
    op.drop_constraint("fk_sd_ticket_created_by_user_id", "sd_ticket", type_="foreignkey")
    op.drop_column("sd_ticket", "creator_unknown")
    op.drop_column("sd_ticket", "created_by_user_id")
    bind.execute(sa.text("DELETE FROM permissions WHERE code = :c"), {"c": CREATE_ON_BEHALF})
