"""add asset state machine and ticket link

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-10-14 09:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'g7b8c9d0e1f2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Adiciona coluna ticket_id em asset_movements
    op.add_column(
        'asset_movements',
        sa.Column('ticket_id', sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        'fk_asset_movements_ticket_id',
        'asset_movements',
        'sd_ticket',
        ['ticket_id'],
        ['id'],
        ondelete='SET NULL'
    )
    op.create_index(
        'ix_asset_movements_ticket_id',
        'asset_movements',
        ['ticket_id'],
        unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_asset_movements_ticket_id', table_name='asset_movements')
    op.drop_constraint('fk_asset_movements_ticket_id', 'asset_movements', type_='foreignkey')
    op.drop_column('asset_movements', 'ticket_id')
