"""backup.failed: acrescenta o canal `preferred` (WhatsApp) à regra semeada

O seed só cria regras que ainda não existem, então instalações antigas não ganhariam a mudança. Só toca a regra
`backup.failed` quando ela ainda está exatamente como foi semeada (`["in_app", "email"]`); regra editada pelo
administrador não é alterada. Migration de dados, reversível.

Revision ID: u1e2f3a4b5c6d
Revises: t0d1e2f3a4b5
Create Date: 2026-10-24 10:00:00.000000
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "u1e2f3a4b5c6d"
down_revision: Union[str, None] = "t0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEEDED = ["in_app", "email"]
UPDATED = ["in_app", "email", "preferred"]


def _swap(old: list[str], new: list[str]) -> None:
    bind = op.get_bind()
    row = bind.execute(sa.text("SELECT id, channels FROM notification_rules WHERE code = 'backup.failed'")).first()
    if row is None:
        return
    channels = row.channels if isinstance(row.channels, list) else json.loads(row.channels or "[]")
    if channels != old:
        return
    bind.execute(
        sa.text("UPDATE notification_rules SET channels = CAST(:channels AS jsonb) WHERE id = :id"),
        {"channels": json.dumps(new), "id": row.id},
    )


def upgrade() -> None:
    _swap(SEEDED, UPDATED)


def downgrade() -> None:
    _swap(UPDATED, SEEDED)
