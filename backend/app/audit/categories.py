"""
Categoria de cada evento de auditoria (Plano de Evolução, Fase 0 PR 9; S4).

- **security**: acesso, contas, perfis, permissões, configurações de canais e integrações, backups e operações de
  sistema (demonstração, zerar a base). Retenção mínima de 5 anos; nunca apagada pela demonstração.
- **operational**: o dia a dia (chamados, ativos, estoque, organização). Retenção padrão de 2 anos.
"""

SECURITY = "security"
OPERATIONAL = "operational"

_SECURITY_PREFIXES = ("identity.", "system.", "backup.", "integrations.")
_SECURITY_EVENTS = {
    "notifications.email_configured",
    "notifications.email_tested",
    "notifications.channel_unlinked",
    "notifications.rule_created",
    "notifications.rule_updated",
    "notifications.rule_deleted",
    "notifications.whatsapp_connect_requested",
    "notifications.whatsapp_disconnected",
    "notifications.whatsapp_test_sent",
    "organization.company_updated",
    "organization.company_logo_updated",
    "assets.statement_template_changed",
}


def category_for(event_type: str) -> str:
    if event_type.startswith(_SECURITY_PREFIXES) or event_type in _SECURITY_EVENTS:
        return SECURITY
    return OPERATIONAL
