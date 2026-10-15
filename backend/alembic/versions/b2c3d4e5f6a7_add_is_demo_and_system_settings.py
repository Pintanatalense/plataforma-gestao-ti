"""add is_demo flags and system_settings

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-15 00:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Tabela system_settings
    op.create_table(
        'system_settings',
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('key')
    )

    # 2. Flag is_demo nas entidades de negócio
    tables = [
        'companies',
        'units',
        'sectors',
        'employees',
        'user_accounts',
        'assets',
        'stk_items',
        'sd_ticket',
        'attachments',
    ]

    for tbl in tables:
        op.add_column(tbl, sa.Column('is_demo', sa.Boolean(), server_default='false', nullable=False))
        op.create_index(f'ix_{tbl}_is_demo', tbl, ['is_demo'])


def downgrade() -> None:
    tables = [
        'attachments',
        'sd_ticket',
        'stk_items',
        'assets',
        'user_accounts',
        'employees',
        'sectors',
        'units',
        'companies',
    ]

    for tbl in tables:
        op.drop_index(f'ix_{tbl}_is_demo', table_name=tbl)
        op.drop_column(tbl, 'is_demo')

    op.drop_table('system_settings')
