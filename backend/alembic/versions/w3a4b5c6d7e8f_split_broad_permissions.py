"""desmembra permissões amplas (Plano de Evolução, Fase 0 PR 6)

Novas permissões e quem as recebe (só quem já fazia aquilo, para o acesso continuar idêntico):

| antiga | nova | recebe |
|---|---|---|
| ``assets.write`` | ``assets.categories.manage``, ``assets.movements.write``, ``assets.import`` | perfis que têm ``assets.write`` |
| ``service_desk.tickets.manage`` | ``service_desk.categories.manage`` | perfis que têm ``service_desk.tickets.manage`` |
| ``system.backup.manage`` (crítica) | ``system.demo.manage``, ``system.data.reset`` (críticas) | contas com concessão individual de ``system.backup.manage`` (auditado) |

A antiga continua existindo e protegendo o que sobrou nela. O seed preenche rótulo, módulo e risco pelo catálogo.

Volta (downgrade): apaga as permissões novas (e, por cascata, os vínculos com perfis e as concessões). Sem perda de
acesso, porque as rotas antigas voltam a exigir a permissão ampla que ninguém perdeu.

Revision ID: w3a4b5c6d7e8f
Revises: v2f3a4b5c6d7e
Create Date: 2026-10-25 17:00:00.000000
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "w3a4b5c6d7e8f"
down_revision: Union[str, None] = "v2f3a4b5c6d7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE_SPLITS = {
    "assets.write": ("assets.categories.manage", "assets.movements.write", "assets.import"),
    "service_desk.tickets.manage": ("service_desk.categories.manage",),
}
GRANT_SPLITS = {"system.backup.manage": ("system.demo.manage", "system.data.reset")}
CRITICAL = {"system.demo.manage", "system.data.reset"}
NEW = [code for codes in (*ROLE_SPLITS.values(), *GRANT_SPLITS.values()) for code in codes]
REASON = "acesso existente preservado no desmembramento de permissões"


def _permission_id(bind, code: str, now: datetime) -> uuid.UUID:
    found = bind.execute(sa.text("SELECT id FROM permissions WHERE code = :c"), {"c": code}).scalar()
    if found is not None:
        return found
    new_id = uuid.uuid4()
    bind.execute(
        sa.text(
            "INSERT INTO permissions (id, code, is_critical, created_at, updated_at) VALUES (:id, :c, :crit, :now, :now)"
        ),
        {"id": new_id, "c": code, "crit": code in CRITICAL, "now": now},
    )
    return new_id


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    ids = {code: _permission_id(bind, code, now) for code in NEW}

    for old, new_codes in ROLE_SPLITS.items():
        role_ids = bind.execute(
            sa.text(
                "SELECT rp.role_id FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE p.code = :c"
            ),
            {"c": old},
        ).scalars().all()
        for role_id in role_ids:
            for code in new_codes:
                exists = bind.execute(
                    sa.text("SELECT 1 FROM role_permissions WHERE role_id = :r AND permission_id = :p"),
                    {"r": role_id, "p": ids[code]},
                ).first()
                if exists is None:
                    bind.execute(
                        sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:r, :p)"),
                        {"r": role_id, "p": ids[code]},
                    )

    for old, new_codes in GRANT_SPLITS.items():
        holders = bind.execute(
            sa.text(
                "SELECT g.user_id FROM user_critical_grants g JOIN permissions p ON p.id = g.permission_id WHERE p.code = :c"
            ),
            {"c": old},
        ).scalars().all()
        for user_id in holders:
            for code in new_codes:
                exists = bind.execute(
                    sa.text("SELECT 1 FROM user_critical_grants WHERE user_id = :u AND permission_id = :p"),
                    {"u": user_id, "p": ids[code]},
                ).first()
                if exists is not None:
                    continue
                bind.execute(
                    sa.text(
                        "INSERT INTO user_critical_grants (id, user_id, permission_id, granted_via, reason, granted_at) "
                        "VALUES (:id, :u, :p, 'migration', :r, :now)"
                    ),
                    {"id": uuid.uuid4(), "u": user_id, "p": ids[code], "r": REASON, "now": now},
                )
                bind.execute(
                    sa.text(
                        "INSERT INTO audit_logs (id, event_type, entity_type, entity_id, data, user_id, created_at, updated_at) "
                        "VALUES (:id, 'identity.critical_granted', 'user', :u, CAST(:data AS jsonb), NULL, :now, :now)"
                    ),
                    {"id": uuid.uuid4(), "u": user_id, "now": now,
                     "data": json.dumps({"permission": code, "via": "migration", "reason": REASON})},
                )


def downgrade() -> None:
    bind = op.get_bind()
    codes = sa.bindparam("codes", expanding=True)
    sub = sa.text("SELECT id FROM permissions WHERE code IN :codes").bindparams(codes)
    ids = bind.execute(sub, {"codes": NEW}).scalars().all()
    for perm_id in ids:
        bind.execute(sa.text("DELETE FROM user_critical_grants WHERE permission_id = :p"), {"p": perm_id})
        bind.execute(sa.text("DELETE FROM role_permissions WHERE permission_id = :p"), {"p": perm_id})
        bind.execute(sa.text("DELETE FROM permissions WHERE id = :p"), {"p": perm_id})
