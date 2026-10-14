"""add whatsapp tables

Revision ID: f6a7b8c9d0e1
Revises: e5f1a23b4567
Create Date: 2026-10-13 23:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f1a23b4567'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Cria tabela wa_configs
    op.create_table(
        'wa_configs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('api_url', sa.String(length=255), nullable=False),
        sa.Column('api_key', sa.String(length=255), nullable=False),
        sa.Column('instance_name', sa.String(length=100), nullable=False),
        sa.Column('webhook_secret', sa.String(length=100), nullable=True),
        sa.Column('welcome_message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # 2. Cria tabela wa_sessions
    op.create_table(
        'wa_sessions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('phone', sa.String(length=30), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=True),
        sa.Column('state', sa.String(length=50), nullable=False),
        sa.Column('current_ticket_id', sa.UUID(), nullable=True),
        sa.Column('current_category_id', sa.UUID(), nullable=True),
        sa.Column('context_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('last_interaction_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['current_ticket_id'], ['sd_ticket.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['current_category_id'], ['sd_ticket_category.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('phone')
    )
    op.create_index('ix_wa_sessions_phone', 'wa_sessions', ['phone'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_wa_sessions_phone', table_name='wa_sessions')
    op.drop_table('wa_sessions')
    op.drop_table('wa_configs')
