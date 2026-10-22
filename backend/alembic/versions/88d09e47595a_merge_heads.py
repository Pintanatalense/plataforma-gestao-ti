"""merge heads

Revision ID: 88d09e47595a
Revises: b2c3d4e5f6a7, g7b8c9d0e1f2
Create Date: 2026-10-15 10:59:53.868867
"""

from typing import Sequence, Union



# revision identifiers
revision: str = '88d09e47595a'
down_revision: Union[str, None] = ('b2c3d4e5f6a7', 'g7b8c9d0e1f2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
