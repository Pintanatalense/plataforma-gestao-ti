"""auditoria: tipo/e-mail do ator, categoria, IP e requisição; user_id sem FK (Plano de Evolução, Fase 0 PR 9; S4)

1. Novas colunas em ``audit_logs``: ``actor_kind``, ``actor_email``, ``category`` (índice), ``ip``, ``request_id``.
2. Preenchimento das linhas existentes: categoria pela mesma regra do código (``app/audit/categories.py``, regra
   congelada abaixo), ator ``human``/``system`` pela presença de ``user_id``, e-mail do ator a partir da conta (se ela
   ainda existe) e IP a partir de ``data.ip``.
3. ``user_id`` deixa de ter chave estrangeira: apagar uma conta (ex.: da demonstração) não pode apagar nem alterar a
   trilha dela (antes, apagar um usuário de demonstração com trilha falhava por FK).

Volta (downgrade): remove as colunas novas e recria a FK depois de limpar ``user_id`` de contas que não existem mais
(perde só esse vínculo; o e-mail registrado também sai junto com a coluna).

Revision ID: x4b5c6d7e8f9a
Revises: w3a4b5c6d7e8f
Create Date: 2026-10-26 09:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "x4b5c6d7e8f9a"
down_revision: Union[str, None] = "w3a4b5c6d7e8f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Congelado nesta migration (a regra do código pode evoluir).
SECURITY_PREFIXES = ("identity.", "system.", "backup.", "integrations.")
SECURITY_EVENTS = (
    "notifications.email_configured", "notifications.email_tested", "notifications.channel_unlinked",
    "notifications.rule_created", "notifications.rule_updated", "notifications.rule_deleted",
    "notifications.whatsapp_connect_requested", "notifications.whatsapp_disconnected",
    "notifications.whatsapp_test_sent", "organization.company_updated", "organization.company_logo_updated",
    "assets.statement_template_changed",
)


def _user_fk_names(bind) -> list[str]:
    return [
        fk["name"]
        for fk in sa.inspect(bind).get_foreign_keys("audit_logs")
        if fk["referred_table"] == "user_accounts" and fk["constrained_columns"] == ["user_id"] and fk.get("name")
    ]


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("actor_kind", sa.String(length=20), server_default="system", nullable=False))
    op.add_column("audit_logs", sa.Column("actor_email", sa.String(length=255), nullable=True))
    op.add_column("audit_logs", sa.Column("category", sa.String(length=20), server_default="operational", nullable=False))
    op.add_column("audit_logs", sa.Column("ip", sa.String(length=50), nullable=True))
    op.add_column("audit_logs", sa.Column("request_id", sa.String(length=64), nullable=True))
    op.create_index("ix_audit_logs_category", "audit_logs", ["category"])

    bind = op.get_bind()
    prefix_clause = " OR ".join(f"event_type LIKE '{p}%'" for p in SECURITY_PREFIXES)
    bind.execute(
        sa.text(f"UPDATE audit_logs SET category = 'security' WHERE {prefix_clause} OR event_type IN :events").bindparams(
            sa.bindparam("events", expanding=True)
        ),
        {"events": list(SECURITY_EVENTS)},
    )
    bind.execute(sa.text("UPDATE audit_logs SET actor_kind = 'human' WHERE user_id IS NOT NULL"))
    bind.execute(
        sa.text(
            "UPDATE audit_logs a SET actor_email = u.email FROM user_accounts u WHERE u.id = a.user_id"
        )
    )
    bind.execute(sa.text("UPDATE audit_logs SET ip = left(data->>'ip', 50) WHERE data ? 'ip' AND data->>'ip' IS NOT NULL"))

    for name in _user_fk_names(bind):
        op.drop_constraint(name, "audit_logs", type_="foreignkey")


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE audit_logs SET user_id = NULL WHERE user_id IS NOT NULL AND user_id NOT IN (SELECT id FROM user_accounts)")
    )
    op.create_foreign_key("audit_logs_user_id_fkey", "audit_logs", "user_accounts", ["user_id"], ["id"])
    op.drop_index("ix_audit_logs_category", table_name="audit_logs")
    for column in ("request_id", "ip", "category", "actor_email", "actor_kind"):
        op.drop_column("audit_logs", column)
