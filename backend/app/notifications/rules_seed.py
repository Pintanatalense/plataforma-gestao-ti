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
