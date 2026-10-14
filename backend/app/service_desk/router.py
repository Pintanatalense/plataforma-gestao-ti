"""
MOD-04 — Service Desk (Router)
"""

import uuid
from typing import Sequence

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_token_payload, get_db
from app.identity.repository import IdentityRepository
from app.organization.models import Employee
from app.service_desk.schemas import (
    TicketCategoryResponse,
    TicketCategoryCreate,
    TicketCategoryUpdate,
    TicketCreate,
    TicketInteractionCreate,
    TicketInteractionResponse,
    TicketMaterialCreate,
    TicketMaterialResponse,
    TicketResponse,
    TicketUpdate,
    TicketHistoryItem,
)
from app.service_desk.services import ServiceDeskService

router = APIRouter()


async def get_user_context(
    payload: dict = Depends(get_token_payload),
    session: AsyncSession = Depends(get_db)
) -> dict:
    user_id = uuid.UUID(payload["sub"])
    is_technician = payload.get("is_admin", False) or "service_desk.tickets.manage" in payload.get("permissions", [])
    
    # precisamos do employee_id do usuário logado
    repo = IdentityRepository(session)
    user = await repo.get_user(user_id)
    employee_id = user.employee_id if user else None
    
    employee_unit_id = None
    employee_sector_id = None
    if employee_id:
        from sqlalchemy import select
        stmt = select(Employee).where(Employee.id == employee_id)
        result = await session.execute(stmt)
        emp = result.scalar_one_or_none()
        if emp:
            employee_unit_id = emp.unit_id
            employee_sector_id = emp.sector_id

    return {
        "user_id": user_id,
        "employee_id": employee_id,
        "unit_id": employee_unit_id,
        "sector_id": employee_sector_id,
        "is_technician": is_technician
    }


@router.get(
    "/categories",
    response_model=list[TicketCategoryResponse],
    summary="Lista categorias de chamados"
)
async def list_categories(
    session: AsyncSession = Depends(get_db)
) -> Sequence[TicketCategoryResponse]:
    service = ServiceDeskService(session)
    return await service.list_categories()

@router.post(
    "/categories",
    response_model=TicketCategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cria uma nova categoria de chamado"
)
async def create_category(
    schema: TicketCategoryCreate,
    ctx: dict = Depends(get_user_context),
    session: AsyncSession = Depends(get_db)
) -> TicketCategoryResponse:
    if not ctx["is_technician"]:
        from app.core.exceptions import ForbiddenException
        raise ForbiddenException("Apenas técnicos ou gestores podem criar categorias.")
    service = ServiceDeskService(session)
    cat = await service.create_category(schema)
    await session.commit()
    return cat

@router.patch(
    "/categories/{category_id}",
    response_model=TicketCategoryResponse,
    summary="Atualiza uma categoria existente"
)
async def update_category(
    category_id: uuid.UUID,
    schema: TicketCategoryUpdate,
    ctx: dict = Depends(get_user_context),
    session: AsyncSession = Depends(get_db)
) -> TicketCategoryResponse:
    if not ctx["is_technician"]:
        from app.core.exceptions import ForbiddenException
        raise ForbiddenException("Apenas técnicos ou gestores podem atualizar categorias.")
    service = ServiceDeskService(session)
    cat = await service.update_category(category_id, schema)
    await session.commit()
    return cat


@router.get(
    "",
    response_model=list[TicketResponse],
    summary="Lista chamados do usuário ou todos (se técnico)"
)
async def list_tickets(
    ctx: dict = Depends(get_user_context),
    session: AsyncSession = Depends(get_db)
) -> Sequence[TicketResponse]:
    service = ServiceDeskService(session)
    tickets = await service.list_tickets_for_user(
        user_employee_id=ctx["employee_id"],
        is_technician=ctx["is_technician"]
    )
    
    responses = []
    for t in tickets:
        resp = TicketResponse.model_validate(t)
        if not ctx["is_technician"]:
            resp.interactions = [i for i in resp.interactions if not i.is_internal]
        responses.append(resp)
        
    return responses


@router.get(
    "/{ticket_id}",
    response_model=TicketResponse,
    summary="Busca detalhes de um chamado específico"
)
async def get_ticket(
    ticket_id: uuid.UUID,
    ctx: dict = Depends(get_user_context),
    session: AsyncSession = Depends(get_db)
) -> TicketResponse:
    service = ServiceDeskService(session)
    ticket = await service.get_ticket_for_user(
        ticket_id=ticket_id,
        user_employee_id=ctx["employee_id"],
        is_technician=ctx["is_technician"]
    )
    
    resp = TicketResponse.model_validate(ticket)
    if not ctx["is_technician"]:
        resp.interactions = [i for i in resp.interactions if not i.is_internal]
        
    return resp


@router.post(
    "",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Abre um novo chamado"
)
async def create_ticket(
    schema: TicketCreate,
    ctx: dict = Depends(get_user_context),
    session: AsyncSession = Depends(get_db)
) -> TicketResponse:
    # Mesmo quem não é tecnico pode abrir (o usuario atual é o requester se tiver employee_id)
    # Requisito minimo é ter employee_id
    if not ctx["employee_id"]:
        from app.core.exceptions import ForbiddenException
        raise ForbiddenException("Apenas colaboradores vinculados a um Employee podem abrir chamados.")

    service = ServiceDeskService(session)
    ticket = await service.create_ticket(
        schema, 
        requester_id=ctx["employee_id"], 
        origin_unit_id=ctx["unit_id"], 
        origin_sector_id=ctx["sector_id"],
        user_id=ctx["user_id"]
    )
    await session.commit()
    return ticket


@router.patch(
    "/{ticket_id}",
    response_model=TicketResponse,
    summary="Atualiza status, prioridade, responsável ou categoria"
)
async def update_ticket(
    ticket_id: uuid.UUID,
    schema: TicketUpdate,
    ctx: dict = Depends(get_user_context),
    session: AsyncSession = Depends(get_db)
) -> TicketResponse:
    service = ServiceDeskService(session)
    ticket = await service.update_ticket(
        ticket_id=ticket_id,
        schema=schema,
        is_technician=ctx["is_technician"],
        user_employee_id=ctx["employee_id"],
        user_id=ctx["user_id"]
    )
    await session.commit()
    return ticket


@router.get(
    "/{ticket_id}/history",
    response_model=list[TicketHistoryItem],
    summary="Recupera o histórico e linha do tempo de eventos do chamado"
)
async def get_ticket_history(
    ticket_id: uuid.UUID,
    ctx: dict = Depends(get_user_context),
    session: AsyncSession = Depends(get_db)
) -> list[TicketHistoryItem]:
    service = ServiceDeskService(session)
    history = await service.get_ticket_history(
        ticket_id=ticket_id,
        user_employee_id=ctx["employee_id"],
        is_technician=ctx["is_technician"]
    )
    return [TicketHistoryItem.model_validate(h) for h in history]


@router.post(
    "/{ticket_id}/interactions",
    response_model=TicketInteractionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Adiciona uma nova interação ao chamado"
)
async def add_interaction(
    ticket_id: uuid.UUID,
    schema: TicketInteractionCreate,
    ctx: dict = Depends(get_user_context),
    session: AsyncSession = Depends(get_db)
) -> TicketInteractionResponse:
    service = ServiceDeskService(session)
    interaction = await service.add_interaction(
        ticket_id=ticket_id,
        schema=schema,
        author_id=ctx["user_id"],
        user_employee_id=ctx["employee_id"],
        is_technician=ctx["is_technician"]
    )
    await session.commit()
    return interaction


@router.post(
    "/{ticket_id}/materials",
    response_model=TicketMaterialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Adiciona um material (item de estoque) consumido pelo chamado"
)
async def add_material(
    ticket_id: uuid.UUID,
    schema: TicketMaterialCreate,
    ctx: dict = Depends(get_user_context),
    session: AsyncSession = Depends(get_db)
) -> TicketMaterialResponse:
    from app.stock.repository import StockRepository
    from app.stock.services import StockService
    
    stock_service = StockService(StockRepository(session))
    service = ServiceDeskService(session, stock_service)
    
    material = await service.add_material_to_ticket(
        ticket_id=ticket_id,
        schema=schema,
        author_id=ctx["user_id"],
        user_employee_id=ctx["employee_id"],
        is_technician=ctx["is_technician"]
    )
    await session.commit()
    return material
