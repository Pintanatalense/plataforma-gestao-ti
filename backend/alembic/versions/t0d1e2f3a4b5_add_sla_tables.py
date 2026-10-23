"""add SLA tables (ADR-017)

Calendários, feriados, políticas, alvos, ciclos por chamado e violações, mais `sla_policy_id` na categoria
de chamado. Migration aditiva. Cria o calendário "Horário comercial" e a política "Padrão", **inativa e sem
vínculo com nenhuma categoria**: nada muda no comportamento dos chamados até o administrador ligar.

Revision ID: t0d1e2f3a4b5
Revises: s9c0d1e2f3a4
Create Date: 2026-10-22 21:00:00.000000
"""

import json
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "t0d1e2f3a4b5"
down_revision: Union[str, None] = "s9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOW = sa.text("now()")

# prioridade, minutos úteis de primeira resposta, minutos úteis de resolução (ADR-017)
DEFAULT_TARGETS = [
    ("CRITICAL", 30, 4 * 60),
    ("HIGH", 60, 8 * 60),
    ("MEDIUM", 4 * 60, 24 * 60),
    ("LOW", 8 * 60, 48 * 60),
]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "sla_calendars",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("weekly_hours", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "sla_holidays",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("calendar_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["calendar_id"], ["sla_calendars.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("calendar_id", "day", name="uq_sla_holidays_calendar_day"),
    )
    op.create_index("ix_sla_holidays_calendar_id", "sla_holidays", ["calendar_id"])
    op.create_table(
        "sla_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("calendar_id", sa.Uuid(), nullable=False),
        sa.Column("pause_statuses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reopen_rule", sa.String(length=16), nullable=False),
        sa.Column("alert_percent", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["calendar_id"], ["sla_calendars.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_sla_policies_calendar_id", "sla_policies", ["calendar_id"])
    op.create_table(
        "sla_policy_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("priority", sa.String(length=50), nullable=False),
        sa.Column("first_response_minutes", sa.Integer(), nullable=False),
        sa.Column("resolution_minutes", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["sla_policies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_id", "priority", name="uq_sla_policy_targets_policy_priority"),
    )
    op.create_index("ix_sla_policy_targets_policy_id", "sla_policy_targets", ["policy_id"])
    op.create_table(
        "ticket_sla_cycles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("cycle", sa.Integer(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=True),
        sa.Column("priority", sa.String(length=50), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_response_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remaining_first_response_minutes", sa.Integer(), nullable=True),
        sa.Column("remaining_resolution_minutes", sa.Integer(), nullable=True),
        sa.Column("paused_minutes", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["ticket_id"], ["sd_ticket.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["policy_id"], ["sla_policies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticket_id", "cycle", name="uq_ticket_sla_cycles_ticket_cycle"),
    )
    op.create_index("ix_ticket_sla_cycles_ticket_id", "ticket_sla_cycles", ["ticket_id"])
    op.create_index("ix_ticket_sla_cycles_state", "ticket_sla_cycles", ["state"])
    op.create_table(
        "sla_breaches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cycle_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["cycle_id"], ["ticket_sla_cycles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cycle_id", "kind", name="uq_sla_breaches_cycle_kind"),
    )
    op.create_index("ix_sla_breaches_cycle_id", "sla_breaches", ["cycle_id"])

    op.add_column("sd_ticket_category", sa.Column("sla_policy_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_sd_ticket_category_sla_policy_id", "sd_ticket_category", "sla_policies", ["sla_policy_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_sd_ticket_category_sla_policy_id", "sd_ticket_category", ["sla_policy_id"])

    _seed_default_policy()


def _seed_default_policy() -> None:
    """Calendário comercial e política "Padrão" inativa, sem categoria vinculada."""
    conn = op.get_bind()
    calendar_id, policy_id = uuid.uuid4(), uuid.uuid4()
    weekly = {str(day): [["08:00", "18:00"]] for day in range(5)}
    conn.execute(
        sa.text(
            "INSERT INTO sla_calendars (id, name, timezone, weekly_hours) "
            "VALUES (:id, :name, :tz, CAST(:weekly AS jsonb))"
        ),
        {"id": calendar_id, "name": "Horário comercial", "tz": "America/Sao_Paulo", "weekly": json.dumps(weekly)},
    )
    conn.execute(
        sa.text(
            "INSERT INTO sla_policies (id, name, description, is_active, calendar_id, pause_statuses, reopen_rule, alert_percent) "
            "VALUES (:id, :name, :description, false, :calendar_id, CAST(:pause AS jsonb), 'RESTART', 80)"
        ),
        {
            "id": policy_id,
            "name": "Padrão",
            "description": "Política sugerida (ADR-017). Inativa até o administrador ligar e vincular a categorias.",
            "calendar_id": calendar_id,
            "pause": json.dumps(["PENDING"]),
        },
    )
    for priority, first_response, resolution in DEFAULT_TARGETS:
        conn.execute(
            sa.text(
                "INSERT INTO sla_policy_targets (id, policy_id, priority, first_response_minutes, resolution_minutes) "
                "VALUES (:id, :policy_id, :priority, :fr, :res)"
            ),
            {"id": uuid.uuid4(), "policy_id": policy_id, "priority": priority, "fr": first_response, "res": resolution},
        )


def downgrade() -> None:
    op.drop_index("ix_sd_ticket_category_sla_policy_id", table_name="sd_ticket_category")
    op.drop_constraint("fk_sd_ticket_category_sla_policy_id", "sd_ticket_category", type_="foreignkey")
    op.drop_column("sd_ticket_category", "sla_policy_id")
    op.drop_table("sla_breaches")
    op.drop_table("ticket_sla_cycles")
    op.drop_table("sla_policy_targets")
    op.drop_table("sla_policies")
    op.drop_table("sla_holidays")
    op.drop_table("sla_calendars")
