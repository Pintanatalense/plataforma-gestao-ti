"""Central de Mensagens: modelos, envios e permissões (ADR-025 M3)

Cria ``message_templates`` e ``outbound_messages``, acrescenta ``deliveries.message_id`` (nulo em tudo que já existe)
e as permissões ``notifications.messages.send`` e ``notifications.messages.read``, concedidas só aos perfis que já têm
``notifications.manage`` (quem administrava o hub continua podendo tudo; ninguém mais ganha acesso). O seed preenche
rótulo, módulo e risco pelo catálogo.

Volta (downgrade): remove a coluna, as tabelas (perde o histórico de envios da Central; as entregas continuam) e as
permissões novas (por cascata, os vínculos com perfis).

Revision ID: e2f3a4b5c6d7e
Revises: d1e2f3a4b5c6d
Create Date: 2026-10-27 12:00:00.000000
"""

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "e2f3a4b5c6d7e"
down_revision: Union[str, None] = "d1e2f3a4b5c6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_PERMISSIONS = ("notifications.messages.send", "notifications.messages.read")
GRANTED_TO_HOLDERS_OF = "notifications.manage"


def upgrade() -> None:
    op.create_table(
        "message_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("channels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "outbound_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("variables", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("recipients", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("queued_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["template_id"], ["message_templates.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_outbound_messages_author_created", "outbound_messages", ["created_by", "created_at"])
    op.add_column("deliveries", sa.Column("message_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_deliveries_message_id", "deliveries", "outbound_messages", ["message_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_deliveries_message_id", "deliveries", ["message_id"])

    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    role_ids = bind.execute(
        sa.text("SELECT rp.role_id FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE p.code = :c"),
        {"c": GRANTED_TO_HOLDERS_OF},
    ).scalars().all()
    for code in NEW_PERMISSIONS:
        permission_id = bind.execute(sa.text("SELECT id FROM permissions WHERE code = :c"), {"c": code}).scalar()
        if permission_id is None:
            permission_id = uuid.uuid4()
            bind.execute(
                sa.text(
                    "INSERT INTO permissions (id, code, is_critical, created_at, updated_at) "
                    "VALUES (:id, :c, false, :now, :now)"
                ),
                {"id": permission_id, "c": code, "now": now},
            )
        for role_id in role_ids:
            exists = bind.execute(
                sa.text("SELECT 1 FROM role_permissions WHERE role_id = :r AND permission_id = :p"),
                {"r": role_id, "p": permission_id},
            ).first()
            if exists is None:
                bind.execute(
                    sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:r, :p)"),
                    {"r": role_id, "p": permission_id},
                )


def downgrade() -> None:
    op.drop_index("ix_deliveries_message_id", table_name="deliveries")
    op.drop_constraint("fk_deliveries_message_id", "deliveries", type_="foreignkey")
    op.drop_column("deliveries", "message_id")
    op.drop_index("ix_outbound_messages_author_created", table_name="outbound_messages")
    op.drop_table("outbound_messages")
    op.drop_table("message_templates")
    bind = op.get_bind()
    for code in NEW_PERMISSIONS:
        bind.execute(sa.text("DELETE FROM permissions WHERE code = :c"), {"c": code})
