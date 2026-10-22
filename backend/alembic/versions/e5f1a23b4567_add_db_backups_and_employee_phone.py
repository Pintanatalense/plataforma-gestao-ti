"""add db backups and employee phone

Revision ID: e5f1a23b4567
Revises: d4e9f71a82b4
Create Date: 2026-10-13 23:08:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'e5f1a23b4567'
down_revision: Union[str, None] = 'd4e9f71a82b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Cria tabela db_backups
    op.create_table(
        'db_backups',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('checksum_sha256', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by_id'], ['user_accounts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('filename')
    )

    # 2. Adiciona campo phone em employees (para identificação no bot do WhatsApp)
    op.add_column('employees', sa.Column('phone', sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column('employees', 'phone')
    op.drop_table('db_backups')
