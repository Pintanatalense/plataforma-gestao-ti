"""add notification hub (outbox, deliveries, rules, channel configs, scheduled jobs)

Revision ID: j0e1f2a3b4c5
Revises: i9d0e1f2a3b4
Create Date: 2026-10-16 10:00:00.000000
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "j0e1f2a3b4c5"
down_revision: Union[str, None] = "i9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "domain_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("fanned_out_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_domain_events_event_type", "domain_events", ["event_type"])
    op.create_index("ix_domain_events_pending", "domain_events", ["fanned_out_at", "created_at"])

    op.create_table(
        "notification_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(100), nullable=True, unique=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("condition", JSONB, nullable=False, server_default="{}"),
        sa.Column("audience", JSONB, nullable=False, server_default="[]"),
        sa.Column("channels", JSONB, nullable=False, server_default="[]"),
        sa.Column("template_code", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notification_rules_event_type", "notification_rules", ["event_type"])

    op.create_table(
        "deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("domain_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", sa.Uuid(), sa.ForeignKey("notification_rules.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "recipient_user_id", sa.Uuid(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("message", JSONB, nullable=False, server_default="{}"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_deliveries_event_id", "deliveries", ["event_id"])
    op.create_index("ix_deliveries_dispatch", "deliveries", ["status", "next_attempt_at"])

    op.create_table(
        "delivery_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("delivery_id", sa.Uuid(), sa.ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_delivery_attempts_delivery_id", "delivery_attempts", ["delivery_id"])

    op.create_table(
        "channel_configs",
        sa.Column("channel", sa.String(30), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("config", JSONB, nullable=False, server_default="{}"),
        sa.Column("secrets_encrypted", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "scheduled_jobs",
        sa.Column("name", sa.String(100), primary_key=True),
        sa.Column("schedule", sa.String(50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(20), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )

    op.create_table(
        "worker_heartbeat",
        sa.Column("name", sa.String(50), primary_key=True),
        sa.Column("beat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("info", JSONB, nullable=False, server_default="{}"),
    )

    _move_legacy_smtp_config()


def _move_legacy_smtp_config() -> None:
    """Passa a configuração SMTP antiga (senha em texto puro) para channel_configs, com a senha cifrada."""
    conn = op.get_bind()
    row = conn.execute(sa.text("SELECT metadata_json FROM system_settings WHERE key = 'smtp_config'")).first()
    if row is None or not row[0]:
        return
    legacy = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    password = legacy.pop("password", "")
    enabled = bool(legacy.pop("is_enabled", False))

    secrets_encrypted = None
    if password:
        from app.core.crypto import encrypt_json  # exige APP_ENCRYPTION_KEY no ambiente

        secrets_encrypted = encrypt_json({"password": password})

    conn.execute(
        sa.text(
            "INSERT INTO channel_configs (channel, enabled, config, secrets_encrypted) "
            "VALUES ('email', :enabled, CAST(:config AS JSONB), :secrets)"
        ),
        {"enabled": enabled, "config": json.dumps(legacy), "secrets": secrets_encrypted},
    )
    conn.execute(sa.text("DELETE FROM system_settings WHERE key = 'smtp_config'"))


def downgrade() -> None:
    op.drop_table("worker_heartbeat")
    op.drop_table("scheduled_jobs")
    op.drop_table("channel_configs")
    op.drop_index("ix_delivery_attempts_delivery_id", table_name="delivery_attempts")
    op.drop_table("delivery_attempts")
    op.drop_index("ix_deliveries_dispatch", table_name="deliveries")
    op.drop_index("ix_deliveries_event_id", table_name="deliveries")
    op.drop_table("deliveries")
    op.drop_index("ix_notification_rules_event_type", table_name="notification_rules")
    op.drop_table("notification_rules")
    op.drop_index("ix_domain_events_pending", table_name="domain_events")
    op.drop_index("ix_domain_events_event_type", table_name="domain_events")
    op.drop_table("domain_events")
