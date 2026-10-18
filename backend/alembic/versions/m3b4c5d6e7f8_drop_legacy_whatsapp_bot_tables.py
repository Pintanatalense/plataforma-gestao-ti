"""drop legacy WhatsApp bot tables (config, sessions, outbox)

O bot, a fila com anti-ban e a configuração por provedor foram substituídos pelo canal WhatsApp do hub
de notificações (Meta Cloud API): channel_configs, conversation_sessions e deliveries (ADR-013, fase D).
`wa_templates` (respostas rápidas) permanece.

Os dados removidos são descartáveis: a fila nunca teve consumidor e as sessões só guardavam estado de
diálogo. A configuração antiga (Evolution/Mock) não tem equivalente na Meta Cloud API; reconfigure o canal
em Notificações > Entregas e regras.

Revision ID: m3b4c5d6e7f8
Revises: l2a3b4c5d6e7
Create Date: 2026-10-19 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers
revision: str = "m3b4c5d6e7f8"
down_revision: Union[str, None] = "l2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("wa_outbox")  # referencia wa_templates e sd_ticket
    op.drop_table("wa_sessions")  # referencia employees, sd_ticket e sd_ticket_category
    op.drop_table("wa_configs")


def downgrade() -> None:
    raise NotImplementedError(
        "Migration irreversível: as tabelas do bot antigo foram aposentadas. "
        "Restaure um backup anterior à fase D se precisar delas."
    )
