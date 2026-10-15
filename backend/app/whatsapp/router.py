"""
MOD-15 — WhatsApp Integration (Router)

Endpoints REST para:
- Webhook do bot e autoatendimento
- Configuração administrativa e proteção Anti-Ban (delays, jitter, typing, kill switch)
- Gestão de Templates pré-definidos (Respostas Rápidas)
- Fila de Envios (Outbox Monitor, reprocessamento e cancelamento)
- Disparo de WhatsApp vinculado a chamados do Service Desk
"""

import re
from typing import Annotated, Sequence
import uuid
from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.core.dependencies import require_permission, get_current_user_id
from app.identity.models import UserAccount

from app.organization.models import Company
from app.service_desk.models import Ticket, TicketInteraction
from app.whatsapp.models import WhatsAppConfig, WhatsAppTemplate, WhatsAppOutbox
from app.whatsapp.schemas import (
    WhatsAppWebhookPayload,
    WhatsAppConfigResponse,
    WhatsAppConfigUpdate,
    WhatsAppTestMessageRequest,
    WhatsAppTemplateCreate,
    WhatsAppTemplateUpdate,
    WhatsAppTemplateResponse,
    WhatsAppPreviewTemplateRequest,
    WhatsAppPreviewTemplateResponse,
    WhatsAppOutboxResponse,
    WhatsAppOutboxStatsResponse,
    WhatsAppSendTicketRequest,
)
from app.whatsapp.conversation_service import WhatsAppConversationService
from app.whatsapp.queue_service import WhatsAppQueueService
from app.whatsapp.template_service import render_template
from app.whatsapp.adapter import get_whatsapp_adapter

router = APIRouter(prefix="/integrations/whatsapp", tags=["Integração WhatsApp"])


# ==============================================================================
# Webhook & Recepção
# ==============================================================================

@router.post(
    "/webhook",
    summary="Webhook para recepção e processamento de mensagens do WhatsApp",
)
async def whatsapp_webhook(
    payload: WhatsAppWebhookPayload,
    session: Annotated[AsyncSession, Depends(get_db)]
):
    phone = payload.phone
    message_text = payload.message

    # Parser para payloads do Evolution API (ex: key.remoteJid e message.conversation)
    if not phone and payload.data:
        data = payload.data
        key = data.get("key", {})
        remote_jid = key.get("remoteJid", "")
        if "@" in remote_jid:
            phone = remote_jid.split("@")[0]

        msg_obj = data.get("message", {})
        message_text = msg_obj.get("conversation") or msg_obj.get("extendedTextMessage", {}).get("text")

    if not phone or not message_text:
        return {"status": "ignored", "reason": "No valid phone or message content identified"}

    service = WhatsAppConversationService(session)
    reply = await service.process_incoming_message(from_phone=phone, text=message_text)
    return {"status": "processed", "reply": reply}


# ==============================================================================
# Configurações & Proteção Anti-Ban
# ==============================================================================

@router.get(
    "/config",
    response_model=WhatsAppConfigResponse,
    summary="Recupera as configurações e status da integração com WhatsApp",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))]
)
async def get_whatsapp_config(
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = WhatsAppConversationService(session)
    config = await service.get_config()
    return WhatsAppConfigResponse.model_validate(config)


@router.get(
    "/status",
    summary="Obtém o estado detalhado da integração (NOT_CONFIGURED, CONNECTED, DISCONNECTED, FAILED)",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))]
)
async def get_whatsapp_integration_status(
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = WhatsAppConversationService(session)
    config = await service.get_config()
    if not config or not config.is_enabled:
        return {
            "status": "NOT_CONFIGURED",
            "provider": config.provider if config else "NONE",
            "instance_name": config.instance_name if config else "",
            "message": "Integração desativada ou não configurada"
        }

    adapter = get_whatsapp_adapter(config)
    state_res = await adapter.check_connection_state()
    state = state_res.get("state", "unknown")

    if state in ("open", "connected"):
        final_status = "CONNECTED"
        msg = f"Conectado com sucesso ao WhatsApp via {config.provider}"
    elif state in ("close", "connecting", "not_found"):
        final_status = "DISCONNECTED"
        msg = f"Instância aguardando conexão/pareamento via QR Code ({state})"
    elif state in ("unreachable", "error"):
        final_status = "FAILED"
        msg = f"Falha de comunicação com o serviço: {state_res.get('error', state_res.get('message', 'Erro'))}"
    else:
        final_status = "CONFIGURED"
        msg = f"Configurado (estado do provedor: {state})"

    return {
        "status": final_status,
        "provider": config.provider,
        "instance_name": config.instance_name,
        "api_url": config.api_url,
        "message": msg,
        "details": state_res
    }


@router.get(
    "/qrcode",
    summary="Obtém o QR Code para pareamento com WhatsApp via Evolution API",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))]
)
async def get_whatsapp_qrcode(
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = WhatsAppConversationService(session)
    config = await service.get_config()
    if not config or not config.is_enabled:
        raise HTTPException(status_code=400, detail="Integração do WhatsApp está desativada.")

    adapter = get_whatsapp_adapter(config)
    return await adapter.get_qr_code()


@router.patch(
    "/config",
    response_model=WhatsAppConfigResponse,
    summary="Atualiza provedor, tokens e parâmetros anti-ban do WhatsApp",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))]
)
async def update_whatsapp_config(
    body: WhatsAppConfigUpdate,
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = WhatsAppConversationService(session)
    config = await service.get_config()

    if body.provider is not None:
        config.provider = body.provider
    if body.is_enabled is not None:
        config.is_enabled = body.is_enabled
    if body.api_url is not None:
        config.api_url = body.api_url
    if body.api_key is not None:
        config.api_key = body.api_key
    if body.instance_name is not None:
        config.instance_name = body.instance_name
    if body.webhook_secret is not None:
        config.webhook_secret = body.webhook_secret
    if body.welcome_message is not None:
        config.welcome_message = body.welcome_message

    # Anti-ban fields
    if body.anti_ban_enabled is not None:
        config.anti_ban_enabled = body.anti_ban_enabled
    if body.min_delay_seconds is not None:
        config.min_delay_seconds = body.min_delay_seconds
    if body.max_delay_seconds is not None:
        config.max_delay_seconds = body.max_delay_seconds
    if body.simulate_typing is not None:
        config.simulate_typing = body.simulate_typing
    if body.typing_duration_seconds is not None:
        config.typing_duration_seconds = body.typing_duration_seconds
    if body.max_messages_per_minute is not None:
        config.max_messages_per_minute = body.max_messages_per_minute
    if body.cooldown_per_recipient_seconds is not None:
        config.cooldown_per_recipient_seconds = body.cooldown_per_recipient_seconds
    if body.emergency_pause is not None:
        config.emergency_pause = body.emergency_pause

    await session.commit()
    return WhatsAppConfigResponse.model_validate(config)


@router.post(
    "/emergency-pause",
    summary="Kill Switch: Alterna a pausa de emergência imediata de todos os disparos da fila",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))]
)
async def toggle_emergency_pause(
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = WhatsAppConversationService(session)
    config = await service.get_config()
    config.emergency_pause = not config.emergency_pause
    await session.commit()
    return {
        "emergency_pause": config.emergency_pause,
        "message": "Pausa de emergência ATIVADA. Nenhum disparo será efetuado." if config.emergency_pause else "Pausa de emergência DESATIVADA. Disparos liberados."
    }


@router.post(
    "/test-send",
    summary="Dispara mensagem de teste para validação de conectividade com o provedor",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))]
)
async def test_send_message(
    body: WhatsAppTestMessageRequest,
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = WhatsAppConversationService(session)
    config = await service.get_config()
    adapter = get_whatsapp_adapter(config)

    success = await adapter.send_message(body.to_phone, body.message)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível enviar a mensagem através do provedor configurado."
        )

    return {"message": "Mensagem de teste enviada com sucesso!", "to_phone": body.to_phone}


# ==============================================================================
# Templates & Mensagens Pré-definidas
# ==============================================================================

@router.get(
    "/templates",
    response_model=list[WhatsAppTemplateResponse],
    summary="Lista todos os templates pré-definidos de mensagens",
)
async def list_templates(
    session: Annotated[AsyncSession, Depends(get_db)],
    category: str | None = Query(None, description="Filtrar por categoria"),
    active_only: bool = Query(False, description="Apenas templates ativos")
):
    query = select(WhatsAppTemplate)
    conditions = []
    if category:
        conditions.append(WhatsAppTemplate.category == category)
    if active_only:
        conditions.append(WhatsAppTemplate.is_active.is_(True))

    if conditions:
        query = query.where(and_(*conditions))

    query = query.order_by(WhatsAppTemplate.category.asc(), WhatsAppTemplate.name.asc())
    templates = (await session.execute(query)).scalars().all()
    return [WhatsAppTemplateResponse.model_validate(t) for t in templates]


@router.post(
    "/templates",
    response_model=WhatsAppTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastra um novo template de resposta rápida",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))]
)
async def create_template(
    body: WhatsAppTemplateCreate,
    session: Annotated[AsyncSession, Depends(get_db)]
):
    # Verifica duplicidade de código
    stmt = select(WhatsAppTemplate).where(WhatsAppTemplate.code == body.code)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Já existe um template cadastrado com o código '{body.code}'."
        )

    template = WhatsAppTemplate(
        name=body.name,
        code=body.code,
        category=body.category,
        content=body.content,
        is_active=body.is_active
    )
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return WhatsAppTemplateResponse.model_validate(template)


@router.put(
    "/templates/{template_id}",
    response_model=WhatsAppTemplateResponse,
    summary="Atualiza um template existente",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))]
)
async def update_template(
    template_id: uuid.UUID,
    body: WhatsAppTemplateUpdate,
    session: Annotated[AsyncSession, Depends(get_db)]
):
    stmt = select(WhatsAppTemplate).where(WhatsAppTemplate.id == template_id)
    template = (await session.execute(stmt)).scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template não encontrado.")

    if body.name is not None:
        template.name = body.name
    if body.category is not None:
        template.category = body.category
    if body.content is not None:
        template.content = body.content
    if body.is_active is not None:
        template.is_active = body.is_active

    await session.commit()
    await session.refresh(template)
    return WhatsAppTemplateResponse.model_validate(template)


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove um template de mensagem",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))]
)
async def delete_template(
    template_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)]
):
    stmt = select(WhatsAppTemplate).where(WhatsAppTemplate.id == template_id)
    template = (await session.execute(stmt)).scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template não encontrado.")

    await session.delete(template)
    await session.commit()
    return None


@router.post(
    "/templates/{template_id}/preview",
    response_model=WhatsAppPreviewTemplateResponse,
    summary="Gera pré-visualização interpolada do template com dados do chamado"
)
async def preview_template(
    template_id: uuid.UUID,
    body: WhatsAppPreviewTemplateRequest,
    session: Annotated[AsyncSession, Depends(get_db)]
):
    stmt = select(WhatsAppTemplate).where(WhatsAppTemplate.id == template_id)
    template = (await session.execute(stmt)).scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template não encontrado.")

    content = body.template_content or template.content

    ticket = None
    if body.ticket_id:
        stmt_t = (
            select(Ticket)
            .options(
                selectinload(Ticket.requester),
                selectinload(Ticket.assignee),
            )
            .where(Ticket.id == body.ticket_id)
        )

        ticket = (await session.execute(stmt_t)).scalar_one_or_none()

    # Busca nome da empresa
    stmt_comp = select(Company).limit(1)
    company = (await session.execute(stmt_comp)).scalar_one_or_none()
    comp_name = company.name if company else "Gestão de TI"

    rendered = render_template(
        template_content=content,
        ticket=ticket,
        company_name=comp_name,
        observacao=body.observacao or ""
    )

    detected = re.findall(r"\{\{([^}]+)\}\}", content)
    unique_vars = sorted(list(set(v.strip().lower() for v in detected)))

    return WhatsAppPreviewTemplateResponse(
        rendered_message=rendered,
        variables_detected=unique_vars
    )


# ==============================================================================
# Fila de Envios (Outbox Monitor & Controle)
# ==============================================================================

@router.get(
    "/outbox",
    response_model=list[WhatsAppOutboxResponse],
    summary="Lista as mensagens na fila de saída do WhatsApp com status e filtros",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))]
)
async def list_outbox(
    session: Annotated[AsyncSession, Depends(get_db)],
    status_filter: str | None = Query(None, description="Filtrar por status: PENDING, SENT, FAILED, CANCELLED"),
    limit: int = Query(50, ge=1, le=200)
):
    query = select(WhatsAppOutbox)
    if status_filter:
        query = query.where(WhatsAppOutbox.status == status_filter)

    query = query.order_by(WhatsAppOutbox.created_at.desc()).limit(limit)
    items = (await session.execute(query)).scalars().all()
    return [WhatsAppOutboxResponse.model_validate(it) for it in items]


@router.get(
    "/outbox/stats",
    response_model=WhatsAppOutboxStatsResponse,
    summary="Recupera métricas e contadores da fila de saída e proteção anti-ban",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))]
)
async def get_outbox_stats(
    session: Annotated[AsyncSession, Depends(get_db)]
):
    queue_service = WhatsAppQueueService(session)
    stats = await queue_service.get_stats()
    return WhatsAppOutboxStatsResponse.model_validate(stats)


@router.post(
    "/outbox/process",
    summary="Força a execução imediata de um lote da fila de saída respeitando anti-ban",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))]
)
async def process_outbox_now(
    session: Annotated[AsyncSession, Depends(get_db)],
    max_batch: int = Query(10, ge=1, le=50)
):
    queue_service = WhatsAppQueueService(session)
    res = await queue_service.process_outbox(max_batch=max_batch, skip_sleep=True)
    return res


@router.post(
    "/outbox/{item_id}/cancel",
    summary="Cancela o envio de uma mensagem pendente na fila",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))]
)
async def cancel_outbox_message(
    item_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)]
):
    queue_service = WhatsAppQueueService(session)
    success = await queue_service.cancel_item(item_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Item não encontrado ou não está mais com status PENDENTE."
        )
    return {"message": "Envio cancelado com sucesso."}


@router.post(
    "/outbox/{item_id}/retry",
    summary="Reagenda para reenvio uma mensagem que falhou",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))]
)
async def retry_outbox_message(
    item_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)]
):
    queue_service = WhatsAppQueueService(session)
    success = await queue_service.retry_item(item_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item não encontrado."
        )
    return {"message": "Item reagendado para novo envio."}


# ==============================================================================
# Disparo Direto de Template a partir do Chamado (Service Desk)
# ==============================================================================

@router.post(
    "/tickets/{ticket_id}/send",
    summary="Dispara mensagem ou template pré-definido para o solicitante do chamado via WhatsApp",
    dependencies=[Depends(get_current_user_id)]
)
async def send_whatsapp_ticket_message(
    ticket_id: uuid.UUID,
    body: WhatsAppSendTicketRequest,
    current_user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    session: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Envia uma mensagem segura para o WhatsApp do solicitante do chamado:
    1. Valida se o solicitante possui telefone cadastrado.
    2. Interpola o template selecionado com as variáveis do chamado.
    3. Enfileira na fila com proteção Anti-Ban e controle de taxa.
    4. Registra automaticamente no chat/interações do chamado.
    """
    stmt_t = (
        select(Ticket)
        .options(
            selectinload(Ticket.requester),
            selectinload(Ticket.assignee),
        )
        .where(Ticket.id == ticket_id)
    )
    ticket = (await session.execute(stmt_t)).scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chamado não encontrado.")

    if not ticket.requester or not ticket.requester.phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O colaborador solicitante não possui número de WhatsApp cadastrado em seu perfil funcional."
        )

    # Determina o texto final a enviar
    final_message = ""
    template = None
    if body.template_id:
        stmt_tpl = select(WhatsAppTemplate).where(WhatsAppTemplate.id == body.template_id)
        template = (await session.execute(stmt_tpl)).scalar_one_or_none()
        if not template:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template não encontrado.")

        # Busca nome da empresa
        stmt_comp = select(Company).limit(1)
        company = (await session.execute(stmt_comp)).scalar_one_or_none()
        comp_name = company.name if company else "Gestão de TI"

        final_message = render_template(
            template_content=template.content,
            ticket=ticket,
            company_name=comp_name,
            observacao=body.observacao or ""
        )
    elif body.custom_message and body.custom_message.strip():
        final_message = body.custom_message.strip()
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Informe um template pré-definido ou digite uma mensagem personalizada."
        )

    # 1. Enfileira na fila outbox segura (com Anti-Ban)
    queue_service = WhatsAppQueueService(session)
    outbox_item = await queue_service.enqueue_message(
        to_phone=ticket.requester.phone,
        message=final_message,
        priority=body.priority,
        ticket_id=ticket.id,
        template_id=template.id if template else None,
        metadata={"author_id": str(current_user_id), "template_code": template.code if template else None}
    )

    # 2. Registra como interação pública no chamado para constar no histórico da equipe
    author_id = current_user_id
    interaction_msg = f"📱 *[WhatsApp Enviado]*\n\n{final_message}"
    interaction = TicketInteraction(
        ticket_id=ticket.id,
        author_id=author_id,
        message=interaction_msg,
        is_internal=False
    )

    session.add(interaction)
    await session.commit()

    # 3. Dispara processamento em background (sem aguardar delays para responder a UI)
    try:
        await queue_service.process_outbox(max_batch=5, skip_sleep=True)
    except Exception:
        pass

    return {
        "status": "queued",
        "outbox_id": outbox_item.id,
        "to_phone": ticket.requester.phone,
        "message": "Mensagem enfileirada e enviada para processamento com proteção Anti-Ban!"
    }
