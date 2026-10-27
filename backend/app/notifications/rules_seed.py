"""
Regras de notificação padrão (ADR-013 §3.3). Semeadas uma única vez por `code`:
regras já existentes (inclusive editadas ou desativadas pelo administrador) nunca são sobrescritas.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import NotificationRule

DEFAULT_RULES: list[dict] = [
    {
        "code": "ticket.created.staff",
        "name": "Novo chamado → atendentes do setor responsável",
        "event_type": "ticket.created",
        "audience": ["sector_attendants"],
        "channels": ["in_app", "email", "preferred"],
        "template_code": "ticket.created.staff",
    },
    {
        "code": "ticket.created.requester",
        "name": "Novo chamado → confirmação ao solicitante",
        "event_type": "ticket.created",
        "condition": {"exclude_actor": False},
        "audience": ["requester"],
        "channels": ["in_app", "email", "preferred"],
        "template_code": "ticket.created.requester",
    },
    {
        "code": "ticket.assigned.assignee",
        "name": "Chamado atribuído → atendente designado",
        "event_type": "ticket.assigned",
        "audience": ["assignee"],
        "channels": ["in_app", "email", "preferred"],
        "template_code": "ticket.assigned",
    },
    {
        "code": "ticket.assigned.requester",
        "name": "Chamado atribuído → solicitante",
        "event_type": "ticket.assigned",
        "audience": ["requester"],
        "channels": ["in_app", "preferred"],
        "template_code": "ticket.assigned",
    },
    {
        "code": "ticket.status_changed",
        "name": "Mudança de status → solicitante e atendente",
        "event_type": "ticket.status_changed",
        "audience": ["requester", "assignee"],
        "channels": ["in_app", "preferred"],
        "template_code": "ticket.status_changed",
    },
    {
        "code": "ticket.interaction_added",
        "name": "Nova interação → outro lado do atendimento (nota interna só equipe)",
        "event_type": "ticket.interaction_added",
        "audience": ["counterpart"],
        "channels": ["in_app", "email", "preferred"],
        "template_code": "ticket.interaction_added",
    },
    {
        "code": "ticket.sla_warning.assignee",
        "name": "SLA perto de vencer → atendente responsável",
        "event_type": "ticket.sla_warning",
        "audience": ["assignee"],
        "channels": ["in_app", "preferred"],
        "template_code": "ticket.sla_warning",
    },
    {
        "code": "ticket.sla_warning.sector",
        "name": "SLA perto de vencer, chamado sem responsável → atendentes do setor",
        "event_type": "ticket.sla_warning",
        "condition": {"payload_equals": {"assigned": False}},
        "audience": ["sector_attendants"],
        "channels": ["in_app", "preferred"],
        "template_code": "ticket.sla_warning",
    },
    {
        "code": "ticket.sla_breached",
        "name": "SLA violado → responsável, atendentes do setor e gestão",
        "event_type": "ticket.sla_breached",
        "audience": ["assignee", "sector_attendants", "role:Gestão"],
        "channels": ["in_app", "email", "preferred"],
        "template_code": "ticket.sla_breached",
    },
    {
        "code": "backup.failed",
        "name": "Falha de backup → administradores",
        "event_type": "backup.failed",
        "audience": ["admins"],
        "channels": ["in_app", "email", "preferred"],
        "template_code": "backup.failed",
    },
    {
        "code": "backup.completed",
        "name": "Backup concluído → administradores (desativada por padrão)",
        "event_type": "backup.completed",
        "enabled": False,
        "audience": ["admins"],
        "channels": ["in_app"],
        "template_code": "backup.completed",
    },
    {
        "code": "stock.below_minimum",
        "name": "Estoque abaixo do mínimo → administradores e gestão",
        "event_type": "stock.below_minimum",
        "audience": ["admins", "role:Gestão"],
        "channels": ["in_app", "email", "preferred"],
        "template_code": "stock.below_minimum",
    },
    {
        "code": "asset.warranty_expiring",
        "name": "Garantia perto de vencer (30 e 7 dias) → administradores e gestão",
        "event_type": "asset.warranty_expiring",
        "audience": ["admins", "role:Gestão"],
        "channels": ["in_app", "email", "preferred"],
        "template_code": "asset.warranty_expiring",
    },
    {
        "code": "identity.critical_changed",
        "name": "Permissão crítica concedida ou revogada → administradores",
        "event_type": "identity.critical_changed",
        "condition": {"exclude_actor": False},
        "audience": ["admins"],
        "channels": ["in_app", "email"],
        "template_code": "identity.critical_changed",
    },
    {
        "code": "audit.integrity_failed",
        "name": "Trilha de auditoria alterada (cadeia de hash não confere) → administradores",
        "event_type": "audit.integrity_failed",
        "audience": ["admins"],
        "channels": ["in_app", "email"],
        "template_code": "audit.integrity_failed",
    },
    {
        "code": "channel.degraded",
        "name": "Canal degradado → administradores",
        "event_type": "channel.degraded",
        "audience": ["admins"],
        "channels": ["in_app", "email"],
        "template_code": "channel.degraded",
    },
]


async def seed_notification_rules(session: AsyncSession) -> int:
    """Cria as regras padrão que ainda não existem. Retorna quantas foram criadas (sem commit)."""
    existing = set((await session.execute(select(NotificationRule.code).where(NotificationRule.code.is_not(None)))).scalars())
    created = 0
    for spec in DEFAULT_RULES:
        if spec["code"] in existing:
            continue
        session.add(NotificationRule(**{"condition": {}, "enabled": True, **spec}))
        created += 1
    await session.flush()
    return created
