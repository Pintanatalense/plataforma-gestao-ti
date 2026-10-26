"""
MOD-15 — WhatsApp (Router)

Respostas rápidas (templates) e envio a partir de um chamado. O canal em si — Meta Cloud API, webhook,
vínculo por código, fila e retentativa — vive no hub de notificações (`app.notifications`, ADR-013).
"""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import require_any_permission, require_permission
from app.database import get_db
from app.identity.models import UserAccount
from app.notifications.channel_store import load_channel
from app.notifications.channels.whatsapp import WHATSAPP_CHANNEL
from app.notifications.channels_router import is_ready
from app.notifications.direct import enqueue_direct_message
from app.notifications.linking import load_addresses
from app.organization.models import Company
from app.service_desk.models import Ticket, TicketInteraction
from app.core.access import AccessContext
from app.core.dependencies import get_access_context
from app.service_desk.services import ServiceDeskService
from app.whatsapp.models import WhatsAppTemplate
from app.whatsapp.schemas import (
    WhatsAppPreviewTemplateRequest,
    WhatsAppPreviewTemplateResponse,
    WhatsAppSendTicketRequest,
    WhatsAppTemplateCreate,
    WhatsAppTemplateResponse,
    WhatsAppTemplateUpdate,
)
from app.whatsapp.template_service import render_template

router = APIRouter(prefix="/integrations/whatsapp", tags=["Integração WhatsApp"])

PRIORITY_BY_NUMBER = {1: "high", 2: "normal", 3: "low"}
MANAGE_OR_ATTEND = require_any_permission("integrations.whatsapp.manage", "service_desk.tickets.manage")


# ==============================================================================
# Templates & Mensagens Pré-definidas
# ==============================================================================

@router.get(
    "/templates",
    response_model=list[WhatsAppTemplateResponse],
    summary="Lista todos os templates pré-definidos de mensagens",
    dependencies=[Depends(MANAGE_OR_ATTEND)],
)
async def list_templates(
    session: Annotated[AsyncSession, Depends(get_db)],
    category: str | None = Query(None, description="Filtrar por categoria"),
    active_only: bool = Query(False, description="Apenas templates ativos"),
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
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))],
)
async def create_template(body: WhatsAppTemplateCreate, session: Annotated[AsyncSession, Depends(get_db)]):
    existing = (await session.execute(select(WhatsAppTemplate).where(WhatsAppTemplate.code == body.code))).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Já existe um template cadastrado com o código '{body.code}'.",
        )

    template = WhatsAppTemplate(
        name=body.name, code=body.code, category=body.category, content=body.content, is_active=body.is_active
    )
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return WhatsAppTemplateResponse.model_validate(template)


async def _get_template(session: AsyncSession, template_id: uuid.UUID) -> WhatsAppTemplate:
    template = (await session.execute(select(WhatsAppTemplate).where(WhatsAppTemplate.id == template_id))).scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template não encontrado.")
    return template


@router.put(
    "/templates/{template_id}",
    response_model=WhatsAppTemplateResponse,
    summary="Atualiza um template existente",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))],
)
async def update_template(
    template_id: uuid.UUID, body: WhatsAppTemplateUpdate, session: Annotated[AsyncSession, Depends(get_db)]
):
    template = await _get_template(session, template_id)
    for field in ("name", "category", "content", "is_active"):
        value = getattr(body, field)
        if value is not None:
            setattr(template, field, value)
    await session.commit()
    await session.refresh(template)
    return WhatsAppTemplateResponse.model_validate(template)


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove um template de mensagem",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))],
)
async def delete_template(template_id: uuid.UUID, session: Annotated[AsyncSession, Depends(get_db)]):
    await session.delete(await _get_template(session, template_id))
    await session.commit()


async def _company_name(session: AsyncSession) -> str:
    company = (await session.execute(select(Company).limit(1))).scalar_one_or_none()
    return company.name if company else "Gestão de TI"


@router.post(
    "/templates/{template_id}/preview",
    response_model=WhatsAppPreviewTemplateResponse,
    summary="Gera pré-visualização interpolada do template com dados do chamado",
    dependencies=[Depends(MANAGE_OR_ATTEND)],
)
async def preview_template(
    template_id: uuid.UUID, body: WhatsAppPreviewTemplateRequest, session: Annotated[AsyncSession, Depends(get_db)]
):
    template = await _get_template(session, template_id)
    content = body.template_content or template.content

    ticket = None
    if body.ticket_id:
        ticket = (
            await session.execute(
                select(Ticket)
                .options(selectinload(Ticket.requester), selectinload(Ticket.assignee))
                .where(Ticket.id == body.ticket_id)
            )
        ).scalar_one_or_none()

    rendered = render_template(
        template_content=content, ticket=ticket, company_name=await _company_name(session), observacao=body.observacao or ""
    )
    variables = sorted({v.strip().lower() for v in re.findall(r"\{\{([^}]+)\}\}", content)})
    return WhatsAppPreviewTemplateResponse(rendered_message=rendered, variables_detected=variables)


# ==============================================================================
# Envio a partir do chamado (pelo hub)
# ==============================================================================

@router.post(
    "/tickets/{ticket_id}/send",
    summary="Envia mensagem ou template pré-definido ao solicitante do chamado via WhatsApp",
    dependencies=[Depends(MANAGE_OR_ATTEND)],
)
async def send_whatsapp_ticket_message(
    ticket_id: uuid.UUID,
    body: WhatsAppSendTicketRequest,
    ctx: Annotated[AccessContext, Depends(get_access_context)],
    session: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Envia pelo canal WhatsApp do hub à pessoa solicitante, se ela VINCULOU o próprio WhatsApp por código.
    Telefone digitado no cadastro do colaborador não é endereço verificado e não recebe mensagens.
    """
    # Mesma regra de visibilidade da API de chamados (setor responsável / atribuído / gestão).
    ticket = await ServiceDeskService(session).get_ticket_for_user(
        ticket_id=ticket_id,
        user_employee_id=ctx.employee_id,
        is_technician=ctx.is_technician,
        can_read_all=ctx.can_read_all,
        user_id=ctx.user_id,
        sector_id=ctx.sector_id,
    )

    if not is_ready(WHATSAPP_CHANNEL, await load_channel(session, WHATSAPP_CHANNEL)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O canal WhatsApp não está habilitado pela administração.")

    requester_user = (
        await session.execute(
            select(UserAccount).where(UserAccount.employee_id == ticket.requester_id, UserAccount.is_active.is_(True))
        )
    ).scalar_one_or_none()
    address = (await load_addresses(session, {requester_user.id})).get(requester_user.id, {}).get(WHATSAPP_CHANNEL) if requester_user else None
    if not requester_user or not address:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "O solicitante ainda não vinculou o WhatsApp. Peça a ele para gerar o código em Notificações > Minhas "
            "preferências e enviá-lo ao número da empresa.",
        )

    template = None
    if body.template_id:
        template = await _get_template(session, body.template_id)
        final_message = render_template(
            template_content=template.content,
            ticket=ticket,
            company_name=await _company_name(session),
            observacao=body.observacao or "",
        )
    elif body.custom_message and body.custom_message.strip():
        final_message = body.custom_message.strip()
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Informe um template pré-definido ou digite uma mensagem personalizada.")

    delivery = await enqueue_direct_message(
        session,
        channel=WHATSAPP_CHANNEL,
        address=address,
        recipient_user_id=requester_user.id,
        text=final_message,
        actor_user_id=ctx.user_id,
        entity_type="ticket",
        entity_id=ticket.id,
        priority=PRIORITY_BY_NUMBER[body.priority],
    )
    # Fica registrado no histórico do chamado para a equipe.
    session.add(
        TicketInteraction(
            ticket_id=ticket.id,
            author_id=ctx.user_id,
            message=f"📱 [WhatsApp enviado]\n\n{final_message}",
            is_internal=False,
        )
    )
    await session.commit()
    return {
        "status": "queued",
        "delivery_id": delivery.id,
        "message": "Mensagem enfileirada; acompanhe o envio em Notificações > Entregas.",
    }
