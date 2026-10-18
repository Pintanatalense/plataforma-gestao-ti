"""add channel addresses, link codes, conversation sessions and inbound messages

Revision ID: l2a3b4c5d6e7
Revises: k1f2a3b4c5d6
Create Date: 2026-10-18 10:00:00.000000
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "l2a3b4c5d6e7"
down_revision: Union[str, None] = "k1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = postgresql.JSONB(astext_type=sa.Text())

# Regras padrão que passam a entregar também no canal externo preferido de cada pessoa.
PREFERRED_RULE_CODES = (
    "ticket.created.staff",
    "ticket.created.requester",
    "ticket.assigned.assignee",
    "ticket.assigned.requester",
    "ticket.status_changed",
    "ticket.interaction_added",
)


def upgrade() -> None:
    op.create_table(
        "user_channel_addresses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("channel", "address", name="uq_channel_address"),
        sa.UniqueConstraint("user_id", "channel", name="uq_user_channel"),
    )
    op.create_index("ix_user_channel_addresses_user_id", "user_channel_addresses", ["user_id"])

    op.create_table(
        "channel_link_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_channel_link_codes_user_id", "channel_link_codes", ["user_id"])
    op.create_index("ix_channel_link_codes_code_hash", "channel_link_codes", ["code_hash"])

    op.create_table(
        "conversation_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("state", sa.String(40), nullable=False, server_default="IDLE"),
        sa.Column("context", JSONB, nullable=False, server_default="{}"),
        sa.Column("last_interaction_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("channel", "external_id", name="uq_conversation_sender"),
    )

    op.create_table(
        "inbound_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("message_id", sa.String(100), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("channel", "message_id", name="uq_inbound_message"),
    )

    # Acrescenta o canal "preferred" às regras padrão que ainda não o têm (edições do admin são preservadas).
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, channels FROM notification_rules WHERE code = ANY(:codes)"),
        {"codes": list(PREFERRED_RULE_CODES)},
    ).all()
    for rule_id, channels in rows:
        channels = list(channels or [])
        if "preferred" not in channels:
            conn.execute(
                sa.text("UPDATE notification_rules SET channels = CAST(:c AS JSONB) WHERE id = :id"),
                {"c": json.dumps([*channels, "preferred"]), "id": rule_id},
            )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, channels FROM notification_rules")).all()
    for rule_id, channels in rows:
        if "preferred" in (channels or []):
            kept = [c for c in channels if c != "preferred"]
            conn.execute(
                sa.text("UPDATE notification_rules SET channels = CAST(:c AS JSONB) WHERE id = :id"),
                {"c": json.dumps(kept), "id": rule_id},
            )
    op.drop_table("inbound_messages")
    op.drop_table("conversation_sessions")
    op.drop_index("ix_channel_link_codes_code_hash", table_name="channel_link_codes")
    op.drop_index("ix_channel_link_codes_user_id", table_name="channel_link_codes")
    op.drop_table("channel_link_codes")
    op.drop_index("ix_user_channel_addresses_user_id", table_name="user_channel_addresses")
    op.drop_table("user_channel_addresses")
