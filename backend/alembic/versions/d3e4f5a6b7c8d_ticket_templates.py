"""chamados: modelos de atendimento (ADR-026, PR 4)

Cria ``sd_ticket_templates`` e ``sd_ticket_template_items`` (lista de subchamados que a tela pré-preenche) e
``sd_ticket.template_id`` (rastreio; ``ON DELETE SET NULL``). Cria a permissão ``service_desk.templates.manage`` e a
concede aos perfis que já gerenciam categorias de chamados (``service_desk.categories.manage``).

Volta (downgrade): remove a permissão, a coluna e as tabelas (os modelos se perdem; nenhum chamado é apagado).

Revision ID: d3e4f5a6b7c8d
Revises: c2d3e4f5a6b7c
Create Date: 2026-11-05 22:00:00.000000
"""

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision: str = "d3e4f5a6b7c8d"
down_revision: Union[str, None] = "c2d3e4f5a6b7c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_PERMISSION = "service_desk.templates.manage"
GRANTED_TO_HOLDERS_OF = "service_desk.categories.manage"


def upgrade() -> None:
    op.create_table(
        "sd_ticket_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "sd_ticket_template_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "template_id", sa.Uuid(), sa.ForeignKey("sd_ticket_templates.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("sd_ticket_category.id"), nullable=False),
        sa.Column("responsible_sector_id", sa.Uuid(), sa.ForeignKey("sectors.id"), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("default_custom_fields", JSONB(), nullable=False),
        sa.Column("is_required", sa.Boolean(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
    )
    op.create_index("ix_sd_ticket_template_items_template_id", "sd_ticket_template_items", ["template_id"])
    op.add_column("sd_ticket", sa.Column("template_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_sd_ticket_template_id", "sd_ticket", "sd_ticket_templates", ["template_id"], ["id"], ondelete="SET NULL"
    )

    bind = op.get_bind()
    permission_id = bind.execute(sa.text("SELECT id FROM permissions WHERE code = :c"), {"c": NEW_PERMISSION}).scalar()
    if permission_id is None:
        permission_id = uuid.uuid4()
        bind.execute(
            sa.text(
                "INSERT INTO permissions (id, code, is_critical, created_at, updated_at) "
                "VALUES (:id, :c, false, :now, :now)"
            ),
            {"id": permission_id, "c": NEW_PERMISSION, "now": datetime.now(timezone.utc)},
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
    op.get_bind().execute(sa.text("DELETE FROM permissions WHERE code = :c"), {"c": NEW_PERMISSION})
    op.drop_constraint("fk_sd_ticket_template_id", "sd_ticket", type_="foreignkey")
    op.drop_column("sd_ticket", "template_id")
    op.drop_index("ix_sd_ticket_template_items_template_id", table_name="sd_ticket_template_items")
    op.drop_table("sd_ticket_template_items")
    op.drop_table("sd_ticket_templates")