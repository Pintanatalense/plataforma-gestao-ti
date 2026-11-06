"""chamados: só quem tem permissão troca o setor definido pela categoria (chamados vinculados, PR 1)

**Mudança de comportamento.** Até aqui qualquer pessoa escolhia, ao abrir um chamado, um setor diferente do padrão da
categoria. Cria a permissão ``service_desk.tickets.route_any_sector`` e a concede aos perfis que já têm
``service_desk.tickets.manage``, para os atendentes continuarem fazendo o que fazem hoje; os demais perdem a troca
livre (a regra fica em ``ServiceDeskService.resolve_responsible_sector``).

Volta (downgrade): remove a permissão (por cascata, os vínculos com perfis). Para voltar à troca livre também é
preciso reverter o código.

Revision ID: f7a8b9c0d1e2f
Revises: e5f6a7b8c9d0e
Create Date: 2026-11-05 10:30:00.000000
"""

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "f7a8b9c0d1e2f"
down_revision: Union[str, None] = "e5f6a7b8c9d0e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_PERMISSION = "service_desk.tickets.route_any_sector"
GRANTED_TO_HOLDERS_OF = "service_desk.tickets.manage"


def upgrade() -> None:
    bind = op.get_bind()
    permission_id = bind.execute(sa.text("SELECT id FROM permissions WHERE code = :c"), {"c": NEW_PERMISSION}).scalar()
    if permission_id is None:
        permission_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        bind.execute(
            sa.text(
                "INSERT INTO permissions (id, code, is_critical, created_at, updated_at) "
                "VALUES (:id, :c, false, :now, :now)"
            ),
            {"id": permission_id, "c": NEW_PERMISSION, "now": now},
        )
    role_ids = bind.execute(
        sa.text("SELECT rp.role_id FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE p.code = :c"),
        {"c": GRANTED_TO_HOLDERS_OF},
    ).scalars().all()
    for role_id in role_ids:
        exists = bind.execute(
            sa.text("SELECT 1 FROM role_permissions WHERE role_id = :r AND permission_id = :p"),
            {"r": role_id, "p": permission_id},
        ).first()
        if exists is None:
            bind.execute(
                sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:r, :p)"),
                {"r": role_id, "p": permission_id},
            )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM permissions WHERE code = :c"), {"c": NEW_PERMISSION})
