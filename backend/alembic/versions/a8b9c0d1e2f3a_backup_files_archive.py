"""backup completo: pacote de anexos e logomarca ao lado do dump (Plano de Evolução, Fase 0 PR 13; S10)

``db_backups`` ganha ``files_filename``, ``files_size_bytes``, ``files_checksum_sha256`` e ``files_count`` (nulos
nos backups antigos e nos que já não guardam o pacote). Só acrescenta.

Volta (downgrade): remove as colunas; os arquivos .tar.gz já gerados continuam no volume de backups.

Revision ID: a8b9c0d1e2f3a
Revises: z6d7e8f9a0b1c
Create Date: 2026-10-26 20:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "a8b9c0d1e2f3a"
down_revision: Union[str, None] = "z6d7e8f9a0b1c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("db_backups", sa.Column("files_filename", sa.String(length=255), nullable=True))
    op.add_column("db_backups", sa.Column("files_size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("db_backups", sa.Column("files_checksum_sha256", sa.String(length=64), nullable=True))
    op.add_column("db_backups", sa.Column("files_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    for column in ("files_count", "files_checksum_sha256", "files_size_bytes", "files_filename"):
        op.drop_column("db_backups", column)
