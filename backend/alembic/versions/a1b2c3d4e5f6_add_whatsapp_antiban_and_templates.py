"""add whatsapp antiban, templates and outbox

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-10-14 18:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Adiciona campos de proteção anti-ban em wa_configs
    op.add_column('wa_configs', sa.Column('anti_ban_enabled', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('wa_configs', sa.Column('min_delay_seconds', sa.Integer(), server_default='4', nullable=False))
    op.add_column('wa_configs', sa.Column('max_delay_seconds', sa.Integer(), server_default='10', nullable=False))
    op.add_column('wa_configs', sa.Column('simulate_typing', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('wa_configs', sa.Column('typing_duration_seconds', sa.Integer(), server_default='2', nullable=False))
    op.add_column('wa_configs', sa.Column('max_messages_per_minute', sa.Integer(), server_default='12', nullable=False))
    op.add_column('wa_configs', sa.Column('cooldown_per_recipient_seconds', sa.Integer(), server_default='15', nullable=False))
    op.add_column('wa_configs', sa.Column('emergency_pause', sa.Boolean(), server_default='false', nullable=False))

    # 2. Cria tabela wa_templates
    op.create_table(
        'wa_templates',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('category', sa.String(length=50), server_default='SERVICE_DESK', nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )
    op.create_index('ix_wa_templates_code', 'wa_templates', ['code'], unique=True)
    op.create_index('ix_wa_templates_category', 'wa_templates', ['category'])

    # 3. Cria tabela wa_outbox (Fila com Anti-Ban)
    op.create_table(
        'wa_outbox',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('to_phone', sa.String(length=30), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='PENDING', nullable=False),
        sa.Column('priority', sa.Integer(), server_default='2', nullable=False),
        sa.Column('ticket_id', sa.UUID(), nullable=True),
        sa.Column('template_id', sa.UUID(), nullable=True),
        sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('max_attempts', sa.Integer(), server_default='3', nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['sd_ticket.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['template_id'], ['wa_templates.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_wa_outbox_to_phone', 'wa_outbox', ['to_phone'])
    op.create_index('ix_wa_outbox_status', 'wa_outbox', ['status'])


def downgrade() -> None:
    op.drop_index('ix_wa_outbox_status', table_name='wa_outbox')
    op.drop_index('ix_wa_outbox_to_phone', table_name='wa_outbox')
    op.drop_table('wa_outbox')

    op.drop_index('ix_wa_templates_category', table_name='wa_templates')
    op.drop_index('ix_wa_templates_code', table_name='wa_templates')
    op.drop_table('wa_templates')

    op.drop_column('wa_configs', 'emergency_pause')
    op.drop_column('wa_configs', 'cooldown_per_recipient_seconds')
    op.drop_column('wa_configs', 'max_messages_per_minute')
    op.drop_column('wa_configs', 'typing_duration_seconds')
    op.drop_column('wa_configs', 'simulate_typing')
    op.drop_column('wa_configs', 'max_delay_seconds')
    op.drop_column('wa_configs', 'min_delay_seconds')
    op.drop_column('wa_configs', 'anti_ban_enabled')
