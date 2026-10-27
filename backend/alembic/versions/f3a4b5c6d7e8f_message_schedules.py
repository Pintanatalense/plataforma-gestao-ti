"""Central de Mensagens: agendamentos (ADR-025 M4)

Cria ``message_schedules`` e acrescenta a ``outbound_messages`` o vínculo com o agendamento (``schedule_id``,
``scheduled_for``; nulos em tudo que já existe). Cria a permissão ``notifications.messages.schedule``, concedida só
aos perfis que já têm ``notifications.manage``.

Volta (downgrade): remove as colunas, a tabela (perde os agendamentos; os envios já feitos continuam no histórico) e a
permissão nova (por cascata, os vínculos com perfis).

Revision ID: f3a4b5c6d7e8f
Revises: e2f3a4b5c6d7e
Create Date: 2026-10-27 18:00:00.000000
"""

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "f3a4b5c6d7e8f"
down_revision: Union[str, None] = "e2f3a4b5c6d7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_PERMISSION = "notifications.messages.schedule"
GRANTED_TO_HOLDERS_OF = "notifications.manage"


def upgrade() -> None:
    op.create_table(
        "message_schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("variables", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("recipient_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recurrence", sa.String(length=20), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_of_day", sa.String(length=5), nullable=True),
        sa.Column("weekdays", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("month_day", sa.Integer(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("calendar_id", sa.Uuid(), nullable=True),
        sa.Column("non_business_rule", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outcome", sa.String(length=20), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("runs_count", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["calendar_id"], ["sla_calendars.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["template_id"], ["message_templates.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_message_schedules_due", "message_schedules", ["status", "next_run_at"])
    op.add_column("outbound_messages", sa.Column("schedule_id", sa.Uuid(), nullable=True))
    op.add_column("outbound_messages", sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_outbound_messages_schedule_id", "outbound_messages", "message_schedules", ["schedule_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_outbound_messages_schedule_id", "outbound_messages", ["schedule_id"])

    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    permission_id = bind.execute(sa.text("SELECT id FROM permissions WHERE code = :c"), {"c": NEW_PERMISSION}).scalar()
    if permission_id is None:
        permission_id = uuid.uuid4()
        bind.execute(
            sa.text(
                "INSERT INTO permissions (id, code, is_critical, created_at, updated_at) "
                "VALUES (:id, :c, false, :now, :now)"
            ),
            {"id": permission_id, "c": NEW_PERMISSION, "now": now},
        )
    role_ids = bind.execute(
        sa.text("SELECT rp.role_id FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE p.code = :c"),
        {"c": GRANTED_TO_HOLDERS_OF},
    ).scalars().all()
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
    op.drop_index("ix_outbound_messages_schedule_id", table_name="outbound_messages")
    op.drop_constraint("fk_outbound_messages_schedule_id", "outbound_messages", type_="foreignkey")
    op.drop_column("outbound_messages", "scheduled_for")
    op.drop_column("outbound_messages", "schedule_id")
    op.drop_index("ix_message_schedules_due", table_name="message_schedules")
    op.drop_table("message_schedules")
    op.get_bind().execute(sa.text("DELETE FROM permissions WHERE code = :c"), {"c": NEW_PERMISSION})
