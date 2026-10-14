"""add stock categories and item specs

Revision ID: d4e9f71a82b4
Revises: c2a8f41e9b03
Create Date: 2026-10-13 20:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers
revision: str = 'd4e9f71a82b4'
down_revision: Union[str, None] = 'c2a8f41e9b03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Cria tabela stk_categories
    op.create_table(
        'stk_categories',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('spec_schema', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # 2. Adiciona category_id e technical_specs em stk_items
    op.add_column('stk_items', sa.Column('category_id', sa.UUID(), nullable=True))
    op.add_column(
        'stk_items',
        sa.Column('technical_specs', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False)
    )
    op.create_foreign_key(
        'fk_stk_items_category_id_stk_categories',
        'stk_items',
        'stk_categories',
        ['category_id'],
        ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_stk_items_category_id_stk_categories', 'stk_items', type_='foreignkey')
    op.drop_column('stk_items', 'technical_specs')
    op.drop_column('stk_items', 'category_id')
    op.drop_table('stk_categories')
