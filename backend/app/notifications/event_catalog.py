"""
Catálogo dos eventos que o hub conhece (ADR-025 M5): o que a tela de regras oferece em vez de um campo de texto livre.

Cada evento diz o rótulo em português, de que área é, que campos do payload servem para `payload_equals` e se aceita
escalonamento (só os de chamado, onde há "respondido" e "resolvido" para conferir). Regra com evento fora do catálogo
continua valendo (as antigas e os prefixos `entidade.*`), mas a tela avisa.
"""
from dataclasses import asdict, dataclass, field

AUDIENCE_LABELS = {
    "requester": "Solicitante do chamado",
    "creator": "Quem abriu o chamado",
    "assignee": "Atendente responsável",
    "sector_attendants": "Atendentes do setor responsável",
    "counterpart": "O outro lado da conversa do chamado",
    "admins": "Administradores",
}
ESCALATION_UNTIL = {
    "first_response": "enquanto ninguém da equipe responder",
    "resolved": "enquanto o chamado não for resolvido",
}


@dataclass(frozen=True)
class EventSpec:
    code: str
    label: str
    area: str
    payload_keys: tuple[str, ...] = field(default_factory=tuple)
    escalation: bool = False


_TICKET_KEYS = ("priority", "status", "responsible_sector_id")

CATALOG: tuple[EventSpec, ...] = (
    EventSpec("ticket.created", "Chamado aberto", "Chamados", _TICKET_KEYS, escalation=True),
    EventSpec("ticket.assigned", "Chamado atribuído", "Chamados", _TICKET_KEYS, escalation=True),
    EventSpec("ticket.status_changed", "Situação do chamado mudou", "Chamados", (*_TICKET_KEYS, "new_status", "old_status")),
    EventSpec("ticket.interaction_added", "Nova mensagem no chamado", "Chamados", (*_TICKET_KEYS, "is_internal")),
    EventSpec("ticket.sla_warning", "SLA perto de vencer", "Chamados", (*_TICKET_KEYS, "kind", "assigned"), escalation=True),
    EventSpec("ticket.sla_breached", "SLA violado", "Chamados", (*_TICKET_KEYS, "kind", "assigned"), escalation=True),
    EventSpec("ticket.children_created", "Subchamados incluídos (aviso consolidado)", "Chamados", _TICKET_KEYS),
    EventSpec("ticket.child_completed", "Subchamado concluído", "Chamados", (*_TICKET_KEYS, "all_required_done")),
    EventSpec("ticket.child_canceled", "Subchamado cancelado (no principal)", "Chamados", (*_TICKET_KEYS, "is_required")),
    EventSpec("ticket.canceled", "Subchamado cancelado (no próprio subchamado)", "Chamados", _TICKET_KEYS),
    EventSpec("ticket.asset_delivered", "Equipamento entregue pelo chamado", "Chamados", _TICKET_KEYS),
    EventSpec("ticket.asset_returned", "Equipamento devolvido pelo chamado", "Chamados", _TICKET_KEYS),
    EventSpec("asset.warranty_expiring", "Garantia perto de vencer", "Patrimônio"),
    EventSpec("stock.below_minimum", "Estoque abaixo do mínimo", "Estoque"),
    EventSpec("backup.failed", "Backup falhou", "Sistema"),
    EventSpec("backup.completed", "Backup concluído", "Sistema"),
    EventSpec("job.failed", "Rotina automática falhou", "Sistema", ("job", "status")),
    EventSpec("channel.degraded", "Canal de envio degradado", "Sistema", ("channel",)),
    EventSpec("identity.critical_changed", "Permissão crítica concedida ou revogada", "Segurança", ("action",)),
    EventSpec("audit.integrity_failed", "Trilha de auditoria alterada", "Segurança"),
)
BY_CODE = {spec.code: spec for spec in CATALOG}


def accepts_escalation(event_type: str) -> bool:
    """Evento exato do catálogo com escalonamento, ou prefixo `ticket.*`."""
    spec = BY_CODE.get(event_type)
    return bool(spec and spec.escalation) or event_type == "ticket.*"


def as_options() -> dict:
    return {
        "events": [asdict(spec) for spec in CATALOG],
        "audiences": AUDIENCE_LABELS,
        "escalation_until": ESCALATION_UNTIL,
    }
