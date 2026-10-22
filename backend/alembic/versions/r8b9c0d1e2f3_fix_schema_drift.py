"""fix schema drift between models and migrations

Duas diferenças em que o MODELO estava certo e a migration ficou para trás:

* ix_stk_categories_is_active: todas as tabelas com SoftDeleteMixin têm índice em is_active; a migration
  d4e9f71a82b4 criou stk_categories sem ele.
* wa_templates.code: a migration a1b2c3d4e5f6 criou a unicidade duas vezes (UNIQUE CONSTRAINT e índice único
  ix_wa_templates_code). Mantém só o índice, que é o que o model declara; a unicidade continua garantida.

As demais diferenças (índices is_demo, ix_asset_movements_ticket_id, ON DELETE SET NULL de
db_backups.created_by_id e a tabela system_settings) eram o MODELO atrasado e foram corrigidas nos models
e no env.py, sem mudança de banco.

Revision ID: r8b9c0d1e2f3
Revises: q7a8b9c0d1e2
Create Date: 2026-10-22 14:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers
revision: str = "r8b9c0d1e2f3"
down_revision: Union[str, None] = "q7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF [NOT] EXISTS: bancos criados por caminhos diferentes (create_all em homologação, restore de dump) podem
    # já estar no estado final.
    op.execute("CREATE INDEX IF NOT EXISTS ix_stk_categories_is_active ON stk_categories (is_active)")
    op.execute("ALTER TABLE wa_templates DROP CONSTRAINT IF EXISTS wa_templates_code_key")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_stk_categories_is_active")
    # Recria a restrição duplicada só para voltar ao estado anterior.
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'wa_templates_code_key') THEN "
        "ALTER TABLE wa_templates ADD CONSTRAINT wa_templates_code_key UNIQUE (code); "
        "END IF; END $$"
    )
