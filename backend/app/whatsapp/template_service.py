"""
MOD-15 — WhatsApp Integration (Template Service)

Interpolação de variáveis e renderização de respostas rápidas/templates pré-definidos.
"""

from datetime import datetime
import re
from typing import Any
from app.service_desk.models import Ticket


STATUS_LABELS = {
    "OPENED": "Aberto",
    "IN_PROGRESS": "Em Atendimento",
    "PENDING": "Pendente",
    "RESOLVED": "Resolvido",
    "CLOSED": "Encerrado",
}

PRIORITY_LABELS = {
    "LOW": "Baixa",
    "MEDIUM": "Média",
    "HIGH": "Alta",
    "CRITICAL": "Crítica",
}


def render_template(
    template_content: str,
    ticket: Ticket | None = None,
    company_name: str | None = None,
    observacao: str = "",
    extra_context: dict[str, Any] | None = None
) -> str:
    """Substitui variáveis no padrão {{variavel}} pelo contexto correspondente."""
    context: dict[str, str] = {
        "empresa": company_name or "Gestão de TI",
        "observacao": observacao or "",
        "data": datetime.now().strftime("%d/%m/%Y"),
        "hora": datetime.now().strftime("%H:%M"),
    }

    if ticket:
        context["protocolo"] = str(ticket.id)[:8]
        context["titulo"] = ticket.title or ""
        context["status"] = STATUS_LABELS.get(ticket.status, ticket.status)
        context["prioridade"] = PRIORITY_LABELS.get(ticket.priority, ticket.priority)
        
        # Solicitante
        if ticket.requester:
            context["solicitante"] = ticket.requester.name
        else:
            context["solicitante"] = "Colaborador(a)"

        # Atendente
        if ticket.assignee:
            context["atendente"] = getattr(ticket, "assignee_name", None) or (getattr(ticket.assignee, "name", None) or ticket.assignee.email)
        else:
            context["atendente"] = "Equipe de TI"

        # Setor e Unidade
        sector_obj = getattr(ticket, "responsible_sector", None) or getattr(ticket, "origin_sector", None)
        if sector_obj and hasattr(sector_obj, "name"):
            context["setor"] = sector_obj.name
        elif ticket.requester and getattr(ticket.requester, "sector", None):
            context["setor"] = ticket.requester.sector.name
        else:
            context["setor"] = "Suporte de TI"

        unit_obj = getattr(ticket, "origin_unit", None)
        if unit_obj and hasattr(unit_obj, "name"):
            context["unidade"] = unit_obj.name
        elif ticket.requester and getattr(ticket.requester, "unit", None):
            context["unidade"] = ticket.requester.unit.name
        else:
            context["unidade"] = "Matriz"


    if extra_context:
        for k, v in extra_context.items():
            context[k] = str(v)

    rendered = template_content
    for key, val in context.items():
        # Substitui {{key}} ignorando espaços em volta (ex: {{ key }} ou {{key}})
        pattern = re.compile(rf"\{{\{{\s*{re.escape(key)}\s*\}}\}}", re.IGNORECASE)
        rendered = pattern.sub(val, rendered)

    return rendered.strip()
