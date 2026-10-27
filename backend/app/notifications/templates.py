"""
Modelos de mensagem por `template_code`. Recebem o payload do evento e devolvem a mensagem
já renderizada (texto e HTML escapado). Nunca recebem dados além do payload mínimo do evento.
"""
from collections.abc import Callable
from html import escape
from typing import Any

from app.notifications.channels.base import Message

STATUS_LABELS = {
    "OPENED": "Aberto",
    "IN_PROGRESS": "Em atendimento",
    "PENDING": "Pendente",
    "RESOLVED": "Resolvido",
    "CLOSED": "Encerrado",
}
PRIORITY_LABELS = {"LOW": "Baixa", "MEDIUM": "Média", "HIGH": "Alta", "CRITICAL": "Crítica"}


def _html_card(heading: str, lines: list[str], quote: str | None = None, link: bool = True) -> str:
    body = "".join(f'<p style="font-size:15px;color:#334155;margin:8px 0;">{escape(line)}</p>' for line in lines)
    quote_html = (
        '<div style="background:#f8fafc;border-left:4px solid #3b82f6;padding:12px;margin:14px 0;'
        f'border-radius:4px;color:#475569;font-size:14px;white-space:pre-wrap;">{escape(quote)}</div>'
        if quote
        else ""
    )
    return html_frame(heading, body + quote_html, link)


def html_frame(heading: str, inner_html: str, link: bool = True) -> str:
    """Moldura dos e-mails do sistema. `inner_html` já vem escapado por quem chama."""
    button = (
        '<p style="margin:20px 0 8px;"><a href="{{link}}" style="background:#2563eb;color:#fff;padding:10px 18px;'
        'text-decoration:none;border-radius:6px;font-weight:bold;font-size:14px;">Abrir no sistema</a></p>'
        if link
        else ""
    )
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:640px;margin:0 auto;'
        'padding:24px;border:1px solid #e2e8f0;border-radius:8px;">'
        f'<h2 style="color:#1e293b;margin:0 0 12px;font-size:19px;">{escape(heading)}</h2>{inner_html}{button}'
        '<hr style="border:0;border-top:1px solid #f1f5f9;margin:20px 0 10px;">'
        '<p style="font-size:12px;color:#94a3b8;margin:0;">Mensagem automática da Plataforma de Gestão de TI. '
        "Não responda a este e-mail.</p></div>"
    )


def _ticket_ref(p: dict[str, Any]) -> str:
    return f"#{str(p.get('ticket_id', ''))[:8]}"


def _ticket_link(p: dict[str, Any]) -> str | None:
    return f"/service-desk/{p['ticket_id']}" if p.get("ticket_id") else None


def _build(
    event_priority: str, title: str, lines: list[str], payload: dict[str, Any], quote: str | None = None
) -> Message:
    text = "\n".join(lines) + (f"\n\n{quote}" if quote else "")
    return Message(
        title=title,
        body_text=text,
        body_html=_html_card(title, lines, quote),
        link=_ticket_link(payload),
        priority=event_priority,
        entity_type="ticket",
        entity_id=str(payload["ticket_id"]) if payload.get("ticket_id") else None,
    )


def ticket_created_staff(p: dict[str, Any], priority: str) -> Message:
    return _build(
        priority,
        f"Novo chamado {_ticket_ref(p)}: {p.get('title', '')}",
        [f"Prioridade: {PRIORITY_LABELS.get(p.get('priority', ''), p.get('priority', '-'))}", "Aguardando atendimento."],
        p,
    )


def ticket_created_requester(p: dict[str, Any], priority: str) -> Message:
    return _build(
        priority,
        f"Chamado {_ticket_ref(p)} registrado",
        [f"Recebemos o seu chamado: {p.get('title', '')}.", "Você será avisado a cada atualização."],
        p,
    )


def ticket_assigned(p: dict[str, Any], priority: str) -> Message:
    return _build(
        priority,
        f"Chamado {_ticket_ref(p)} atribuído",
        [f"{p.get('title', '')}", "O chamado tem um atendente responsável."],
        p,
    )


def ticket_status_changed(p: dict[str, Any], priority: str) -> Message:
    new = STATUS_LABELS.get(p.get("new_status", ""), p.get("new_status", ""))
    old = STATUS_LABELS.get(p.get("old_status", ""), p.get("old_status", ""))
    return _build(
        priority,
        f"Chamado {_ticket_ref(p)}: {new}",
        [f"{p.get('title', '')}", f"Situação alterada de {old} para {new}."],
        p,
    )


def ticket_interaction_added(p: dict[str, Any], priority: str) -> Message:
    internal = bool(p.get("is_internal"))
    author = p.get("author_name") or "Um participante"
    kind = "uma nota interna" if internal else "uma nova mensagem"
    return _build(
        priority,
        f"Chamado {_ticket_ref(p)}: nova atualização",
        [f"{author} registrou {kind} em: {p.get('title', '')}"],
        p,
        quote=p.get("excerpt"),
    )


SLA_KIND_LABELS = {"FIRST_RESPONSE": "primeira resposta", "RESOLUTION": "resolução"}


def ticket_sla_warning(p: dict[str, Any], priority: str) -> Message:
    kind = SLA_KIND_LABELS.get(p.get("kind", ""), "prazo")
    return _build(
        priority,
        f"Chamado {_ticket_ref(p)}: prazo de {kind} perto de vencer",
        [f"{p.get('title', '')}", f"O prazo de {kind} vence em {p.get('due_local', '-')}."],
        p,
    )


def ticket_sla_breached(p: dict[str, Any], priority: str) -> Message:
    kind = SLA_KIND_LABELS.get(p.get("kind", ""), "prazo")
    return _build(
        priority,
        f"Chamado {_ticket_ref(p)}: prazo de {kind} vencido",
        [f"{p.get('title', '')}", f"O prazo de {kind} venceu em {p.get('due_local', '-')} (SLA violado)."],
        p,
    )


def backup_failed(p: dict[str, Any], priority: str) -> Message:
    err = p.get("error") or "motivo não informado"
    return Message(
        title="Falha no backup do banco de dados",
        body_text=f"O backup automático falhou: {err}\nVerifique o espaço em disco e o utilitário pg_dump.",
        body_html=_html_card("Falha no backup do banco de dados", [f"O backup automático falhou: {err}"], link=False),
        priority=priority,
        entity_type="backup",
    )


def backup_completed(p: dict[str, Any], priority: str) -> Message:
    name = p.get("filename") or "backup"
    return Message(
        title="Backup concluído",
        body_text=f"Backup gerado: {name}",
        body_html=_html_card("Backup concluído", [f"Arquivo gerado: {name}"], link=False),
        priority=priority,
        entity_type="backup",
    )


def channel_degraded(p: dict[str, Any], priority: str) -> Message:
    channel = p.get("channel") or "canal"
    return Message(
        title=f"Canal {channel} degradado",
        body_text=f"O canal {channel} falhou repetidamente e foi pausado por alguns minutos. Último erro: {p.get('error', '-')}",
        body_html=_html_card(
            f"Canal {channel} degradado",
            [f"O canal {channel} falhou repetidamente e foi pausado por alguns minutos.", f"Último erro: {p.get('error', '-')}"],
            link=False,
        ),
        priority=priority,
        entity_type="channel",
    )


def _digest(title: str, lines: list[str], extra: int, link: str, entity_type: str, priority: str) -> Message:
    if extra > 0:
        lines = [*lines, f"... e mais {extra}."]
    return Message(
        title=title,
        body_text="\n".join(lines),
        body_html=_html_card(title, lines),
        link=link,
        priority=priority,
        entity_type=entity_type,
    )


def identity_critical_changed(p: dict[str, Any], priority: str) -> Message:
    granted = p.get("action") == "granted"
    label = p.get("permission_label") or p.get("permission") or "permissão crítica"
    who = p.get("target_email") or "um usuário"
    title = f"Permissão crítica {'concedida' if granted else 'revogada'}: {label}"
    via = {"setup": "assistente de instalação", "cli": "comando no servidor", "migration": "atualização do sistema"}
    lines = [f"Usuário: {who}", f"Origem: {via.get(p.get('via'), 'tela de usuários')}"]
    return Message(
        title=title,
        body_text="\n".join([title, *lines]),
        body_html=_html_card(title, lines, link=False),
        priority=priority,
        entity_type="user",
    )


def audit_integrity_failed(p: dict[str, Any], priority: str) -> Message:
    labels = {"security": "segurança", "operational": "operacional"}
    lines = [f"Trilha de {labels.get(i.get('category'), i.get('category'))}: {i.get('problem')}" for i in p.get("problems", [])]
    lines.append("Alguém alterou ou apagou registros fora do sistema. Preserve o servidor e os backups e investigue.")
    title = "Auditoria: a cadeia de integridade não confere"
    return Message(
        title=title,
        body_text="\n".join([title, *lines]),
        body_html=_html_card(title, lines, link=False),
        priority=priority,
        entity_type="audit_chain",
    )


def stock_below_minimum(p: dict[str, Any], priority: str) -> Message:
    items = p.get("items") or []
    total = int(p.get("total") or len(items))
    lines = [f"{i.get('name', '?')}: {i.get('quantity', 0)} em estoque (mínimo {i.get('min_quantity', 0)})" for i in items]
    title = "1 item com estoque baixo" if total == 1 else f"{total} itens com estoque baixo"
    return _digest(title, lines, total - len(items), "/stock", "stock", priority)


def asset_warranty_expiring(p: dict[str, Any], priority: str) -> Message:
    items = p.get("items") or []
    total = int(p.get("total") or len(items))

    def when(days: int) -> str:
        return "vence hoje" if days <= 0 else ("vence amanhã" if days == 1 else f"vence em {days} dias")

    lines = [f"{i.get('tag', '?')} - {i.get('name', '')}: garantia {when(int(i.get('days_left', 0)))}" for i in items]
    title = "1 garantia perto de vencer" if total == 1 else f"{total} garantias perto de vencer"
    return _digest(title, lines, total - len(items), "/assets", "asset", priority)


def _asset_label(p: dict[str, Any]) -> str:
    tag, name = p.get("asset_tag") or "", p.get("asset_name") or ""
    return f"{tag} - {name}" if tag and name else (tag or name or "equipamento")


def ticket_asset_delivered(p: dict[str, Any], priority: str) -> Message:
    return _build(
        priority,
        f"Chamado {_ticket_ref(p)}: equipamento entregue",
        [f"{_asset_label(p)} foi entregue a você.", "O Termo de Responsabilidade está no chamado."],
        p,
    )


def ticket_asset_returned(p: dict[str, Any], priority: str) -> Message:
    return _build(
        priority,
        f"Chamado {_ticket_ref(p)}: equipamento devolvido",
        [f"{_asset_label(p)} foi devolvido e aguarda inspeção técnica.", f"{p.get('title', '')}"],
        p,
    )


JOB_LABELS = {
    "retention.cleanup": "limpeza de dados antigos",
    "stock.low_check": "verificação de estoque",
    "assets.warranty_check": "verificação de garantias",
    "whatsapp.health_check": "checagem dos canais",
    "audit.retention": "retenção da auditoria",
    "audit.seal": "selagem da auditoria",
    "audit.verify": "verificação da auditoria",
    "sla.check": "verificação de SLA",
    "messages.schedules": "agendamentos de mensagens",
}


def job_failed(p: dict[str, Any], priority: str) -> Message:
    job = p.get("job") or "?"
    status = {"timeout": "passou do tempo máximo", "interrupted": "foi interrompida"}.get(p.get("status"), "falhou")
    title = f"Rotina automática com falha: {JOB_LABELS.get(job, job)}"
    lines = [
        f"A rotina {job} {status} nas {p.get('attempts', '?')} tentativas e volta à agenda normal.",
        *([f"Erro: {p['error']}"] if p.get("error") else []),
        "Detalhes em Notificações - administração > Agenda. Novo aviso só depois que ela voltar a funcionar.",
    ]
    return Message(
        title=title,
        body_text="\n".join([title, *lines]),
        body_html=_html_card(title, lines, link=False),
        priority=priority,
        entity_type="job",
    )


def generic(p: dict[str, Any], priority: str) -> Message:
    title = str(p.get("title") or "Notificação do sistema")
    return Message(title=title, body_text=str(p.get("message") or title), priority=priority)


TEMPLATES: dict[str, Callable[[dict[str, Any], str], Message]] = {
    "ticket.created.staff": ticket_created_staff,
    "ticket.created.requester": ticket_created_requester,
    "ticket.assigned": ticket_assigned,
    "ticket.status_changed": ticket_status_changed,
    "ticket.interaction_added": ticket_interaction_added,
    "ticket.sla_warning": ticket_sla_warning,
    "ticket.sla_breached": ticket_sla_breached,
    "backup.failed": backup_failed,
    "backup.completed": backup_completed,
    "channel.degraded": channel_degraded,
    "identity.critical_changed": identity_critical_changed,
    "audit.integrity_failed": audit_integrity_failed,
    "stock.below_minimum": stock_below_minimum,
    "asset.warranty_expiring": asset_warranty_expiring,
    "ticket.asset_delivered": ticket_asset_delivered,
    "ticket.asset_returned": ticket_asset_returned,
    "job.failed": job_failed,
}


def render(template_code: str, payload: dict[str, Any], priority: str) -> Message:
    return TEMPLATES.get(template_code, generic)(payload, priority)
