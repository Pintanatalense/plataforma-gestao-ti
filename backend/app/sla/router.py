"""Rotas de administração de SLA (ADR-017, P4-S4): `/sla/calendars` e `/sla/policies`.

Ler é permitido a quem administra SLA ou categorias (o formulário de categoria lista as políticas); alterar exige
`service_desk.sla.manage`.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user_id, get_db, require_any_permission, require_permission
from app.sla.admin import SlaAdminService
from app.sla.schemas import CalendarIn, CalendarOut, CalendarUpdate, PolicyIn, PolicyOut, PolicyUpdate

SLA_MANAGE = "service_desk.sla.manage"

router = APIRouter(prefix="/sla", tags=["SLA"])
can_read = Depends(require_any_permission(SLA_MANAGE, "service_desk.categories.manage"))
can_manage = Depends(require_permission(SLA_MANAGE))


def _service(session: AsyncSession = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)) -> SlaAdminService:
    return SlaAdminService(session, user_id)


@router.get("/calendars", response_model=list[CalendarOut], dependencies=[can_read], summary="Lista os calendários de SLA")
async def list_calendars(service: SlaAdminService = Depends(_service)):
    return await service.list_calendars()


@router.post("/calendars", response_model=CalendarOut, status_code=status.HTTP_201_CREATED, dependencies=[can_manage],
             summary="Cria um calendário (expediente e feriados)")
async def create_calendar(data: CalendarIn, service: SlaAdminService = Depends(_service)):
    out = await service.create_calendar(data)
    await service.session.commit()
    return out


@router.patch("/calendars/{calendar_id}", response_model=CalendarOut, dependencies=[can_manage],
              summary="Edita um calendário (vale para chamados novos)")
async def update_calendar(calendar_id: uuid.UUID, data: CalendarUpdate, service: SlaAdminService = Depends(_service)):
    out = await service.update_calendar(calendar_id, data)
    await service.session.commit()
    return out


@router.delete("/calendars/{calendar_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[can_manage],
               summary="Exclui um calendário que nenhuma política usa")
async def delete_calendar(calendar_id: uuid.UUID, service: SlaAdminService = Depends(_service)):
    await service.delete_calendar(calendar_id)
    await service.session.commit()


@router.get("/policies", response_model=list[PolicyOut], dependencies=[can_read], summary="Lista as políticas de SLA")
async def list_policies(service: SlaAdminService = Depends(_service)):
    return await service.list_policies()


@router.post("/policies", response_model=PolicyOut, status_code=status.HTTP_201_CREATED, dependencies=[can_manage],
             summary="Cria uma política de SLA (alvos por prioridade)")
async def create_policy(data: PolicyIn, service: SlaAdminService = Depends(_service)):
    out = await service.create_policy(data)
    await service.session.commit()
    return out


@router.patch("/policies/{policy_id}", response_model=PolicyOut, dependencies=[can_manage],
              summary="Edita, ativa ou desativa uma política (vale para chamados novos)")
async def update_policy(policy_id: uuid.UUID, data: PolicyUpdate, service: SlaAdminService = Depends(_service)):
    out = await service.update_policy(policy_id, data)
    await service.session.commit()
    return out


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[can_manage],
               summary="Exclui uma política que nenhuma categoria usa")
async def delete_policy(policy_id: uuid.UUID, service: SlaAdminService = Depends(_service)):
    await service.delete_policy(policy_id)
    await service.session.commit()
