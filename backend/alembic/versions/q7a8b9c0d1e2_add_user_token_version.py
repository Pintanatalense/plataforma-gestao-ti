"""add token_version to user_accounts

Versão da sessão (ADR-016): cada token JWT carrega a versão vigente do usuário e deixa de valer
quando ela é incrementada (troca/reset de senha, desativação, mudança de perfil).
Usuários existentes começam em 0, igual a um token emitido antes desta migration (sem o claim `tv`),
portanto ninguém é deslogado ao aplicar.

Revision ID: q7a8b9c0d1e2
Revises: p6f7a8b9c0d1
Create Date: 2026-10-22 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "q7a8b9c0d1e2"
down_revision: Union[str, None] = "p6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_accounts",
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("user_accounts", "token_version")
