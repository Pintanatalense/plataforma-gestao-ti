"""Modelos de atendimento (ADR-026, PR 4). Ler os ativos: qualquer usuário (a tela de abertura usa). Gerenciar:
``service_desk.templates.manage``."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessContext
from app.core.dependencies import get_access_context, get_db, require_permission
from app.core.exceptions import ForbiddenException
from app.service_desk.schemas import TicketTemplateIn, TicketTemplateOut
from app.service_desk.templates import TicketTemplateService

TEMPLATES_MANAGE = "service_desk.templates.manage"

router = APIRouter()
can_manage = [Depends(require_permission(TEMPLATES_MANAGE))]


async def _loaded(session: AsyncSession, template) -> TicketTemplateOut:
    await session.refresh(template)
    return TicketTemplateOut.model_validate(template)


@router.get("", response_model=list[TicketTemplateOut], summary="Lista os modelos de atendimento")
async def list_templates(
    include_inactive: bool = Query(False, description="Inclui os desativados (exige Gerenciar modelos)"),
    ctx: AccessContext = Depends(get_access_context),
    session: AsyncSession = Depends(get_db),
) -> list[TicketTemplateOut]:
    if include_inactive and not ctx.has(TEMPLATES_MANAGE):
        raise ForbiddenException("Ver modelos desativados exige a permissão Gerenciar modelos de atendimento.")
    return await TicketTemplateService(session).list(include_inactive)


@router.get("/{template_id}", response_model=TicketTemplateOut, summary="Busca um modelo de atendimento")
async def get_template(
    template_id: uuid.UUID,
    ctx: AccessContext = Depends(get_access_context),
    session: AsyncSession = Depends(get_db),
) -> TicketTemplateOut:
    return await TicketTemplateService(session).get(template_id, include_inactive=ctx.has(TEMPLATES_MANAGE))


@router.post(
    "", response_model=TicketTemplateOut, status_code=status.HTTP_201_CREATED, dependencies=can_manage,
    summary="Cria um modelo de atendimento",
)
async def create_template(
    body: TicketTemplateIn,
    ctx: AccessContext = Depends(get_access_context),
    session: AsyncSession = Depends(get_db),
) -> TicketTemplateOut:
    template = await TicketTemplateService(session).create(body, ctx.user_id)
    await session.commit()
    return await _loaded(session, template)


@router.put(
    "/{template_id}", response_model=TicketTemplateOut, dependencies=can_manage,
    summary="Substitui um modelo de atendimento (nome, descrição, situação e itens)",
)
async def update_template(
    template_id: uuid.UUID,
    body: TicketTemplateIn,
    ctx: AccessContext = Depends(get_access_context),
    session: AsyncSession = Depends(get_db),
) -> TicketTemplateOut:
    template = await TicketTemplateService(session).update(template_id, body, ctx.user_id)
    await session.commit()
    return await _loaded(session, template)


@router.delete(
    "/{template_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=can_manage,
    summary="Desativa um modelo de atendimento (nada é apagado)",
)
async def deactivate_template(
    template_id: uuid.UUID,
    ctx: AccessContext = Depends(get_access_context),
    session: AsyncSession = Depends(get_db),
) -> None:
    await TicketTemplateService(session).deactivate(template_id, ctx.user_id)
    await session.commit()
