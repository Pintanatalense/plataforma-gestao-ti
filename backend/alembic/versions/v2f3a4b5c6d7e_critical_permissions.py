"""permissões críticas: concessão individual (Plano de Evolução, Fase 0 PR 5; S5/A2)

1. ``permissions`` ganha módulo, rótulo, risco e ``is_critical`` (o seed preenche rótulo/módulo/risco pelo catálogo).
2. Nova tabela ``user_critical_grants``.
3. Nova permissão ``identity.critical.grant``; as críticas são marcadas.
4. **Acesso preservado:** quem hoje tem uma crítica (por ``is_admin`` ou por perfil) recebe a concessão individual
   equivalente (origem ``migration``), com registro na auditoria. Administradores recebem também
   ``identity.critical.grant`` (hoje já concediam tudo).
5. As críticas saem de todos os perfis.

Volta (downgrade): devolve as críticas antigas ao perfil "Administrador" (comportamento do seed anterior), apaga as
concessões, a permissão nova e as colunas. É com perda: quem tinha crítica só por concessão individual e não está no
perfil "Administrador" deixa de tê-la; a auditoria das concessões permanece.

Revision ID: v2f3a4b5c6d7e
Revises: u1e2f3a4b5c6d
Create Date: 2026-10-25 15:00:00.000000
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "v2f3a4b5c6d7e"
down_revision: Union[str, None] = "u1e2f3a4b5c6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Congelado nesta migration (o catálogo do código pode mudar depois).
OLD_CRITICAL = ("system.data.import", "system.backup.manage", "system.backup.download")
GRANT = "identity.critical.grant"
CRITICAL = (*OLD_CRITICAL, GRANT)


def upgrade() -> None:
    op.add_column("permissions", sa.Column("module", sa.String(length=50), nullable=True))
    op.add_column("permissions", sa.Column("label", sa.String(length=150), nullable=True))
    op.add_column("permissions", sa.Column("risk", sa.String(length=20), nullable=True))
    op.add_column(
        "permissions", sa.Column("is_critical", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    op.create_table(
        "user_critical_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.Column("granted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("granted_via", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "permission_id", name="uq_user_critical_grants_user_permission"),
    )
    op.create_index("ix_user_critical_grants_user_id", "user_critical_grants", ["user_id"])

    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    if bind.execute(sa.text("SELECT 1 FROM permissions WHERE code = :c"), {"c": GRANT}).first() is None:
        bind.execute(
            sa.text(
                "INSERT INTO permissions (id, code, description, is_critical, created_at, updated_at) "
                "VALUES (:id, :code, :d, true, :now, :now)"
            ),
            {"id": uuid.uuid4(), "code": GRANT, "d": "Conceder e revogar permissões críticas de outros usuários", "now": now},
        )
    bind.execute(sa.text("UPDATE permissions SET is_critical = true WHERE code IN :codes").bindparams(
        sa.bindparam("codes", expanding=True)), {"codes": list(CRITICAL)})

    perm_ids = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT id, code FROM permissions WHERE code IN :codes").bindparams(sa.bindparam("codes", expanding=True)),
            {"codes": list(CRITICAL)},
        )
    }
    admins = bind.execute(sa.text("SELECT id FROM user_accounts WHERE is_admin = true AND deleted_at IS NULL")).scalars().all()
    via_roles = bind.execute(
        sa.text(
            "SELECT DISTINCT ur.user_id, p.code FROM user_roles ur "
            "JOIN role_permissions rp ON rp.role_id = ur.role_id "
            "JOIN permissions p ON p.id = rp.permission_id "
            "JOIN user_accounts u ON u.id = ur.user_id "
            "WHERE p.code IN :codes AND u.deleted_at IS NULL"
        ).bindparams(sa.bindparam("codes", expanding=True)),
        {"codes": list(OLD_CRITICAL)},
    ).all()

    wanted: set[tuple[uuid.UUID, str]] = {(uid, code) for uid in admins for code in CRITICAL}
    wanted |= {(row.user_id, row.code) for row in via_roles}
    for user_id, code in sorted(wanted, key=lambda item: (str(item[0]), item[1])):
        if code not in perm_ids:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO user_critical_grants (id, user_id, permission_id, granted_via, reason, granted_at) "
                "VALUES (:id, :u, :p, 'migration', :r, :now)"
            ),
            {"id": uuid.uuid4(), "u": user_id, "p": perm_ids[code], "r": "acesso existente preservado na atualização", "now": now},
        )
        bind.execute(
            sa.text(
                "INSERT INTO audit_logs (id, event_type, entity_type, entity_id, data, user_id, created_at, updated_at) "
                "VALUES (:id, 'identity.critical_granted', 'user', :u, CAST(:data AS jsonb), NULL, :now, :now)"
            ),
            {"id": uuid.uuid4(), "u": user_id, "now": now,
             "data": json.dumps({"permission": code, "via": "migration", "reason": "acesso existente preservado na atualização"})},
        )

    bind.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE is_critical = true)")
    )


def downgrade() -> None:
    bind = op.get_bind()
    admin_role = bind.execute(sa.text("SELECT id FROM roles WHERE name = 'Administrador'")).scalar()
    if admin_role is not None:
        for perm_id in bind.execute(
            sa.text("SELECT id FROM permissions WHERE code IN :codes").bindparams(sa.bindparam("codes", expanding=True)),
            {"codes": list(OLD_CRITICAL)},
        ).scalars():
            exists = bind.execute(
                sa.text("SELECT 1 FROM role_permissions WHERE role_id = :r AND permission_id = :p"), {"r": admin_role, "p": perm_id}
            ).first()
            if exists is None:
                bind.execute(sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:r, :p)"), {"r": admin_role, "p": perm_id})

    op.drop_index("ix_user_critical_grants_user_id", table_name="user_critical_grants")
    op.drop_table("user_critical_grants")
    bind.execute(sa.text("DELETE FROM permissions WHERE code = :c"), {"c": GRANT})
    op.drop_column("permissions", "is_critical")
    op.drop_column("permissions", "risk")
    op.drop_column("permissions", "label")
    op.drop_column("permissions", "module")
