"""merge whatsapp/antiban and asset state machine heads

Revision ID: h8c9d0e1f2a3
Revises: b2c3d4e5f6a7, g7b8c9d0e1f2
Create Date: 2026-10-15 12:00:00.000000

As duas cadeias (a1b2.. -> b2c3.. e g7b8..) partiam de f6a7b8c9d0e1 e alteram
tabelas independentes; esta revisão apenas as une em uma única cabeça.
"""

from typing import Sequence, Union

# revision identifiers
revision: str = "h8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = ("b2c3d4e5f6a7", "g7b8c9d0e1f2")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
