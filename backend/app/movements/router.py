import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.repository import AssetRepository
from app.core.dependencies import get_current_user_id, require_permission
from app.database import get_db
from app.movements.repository import AssetMovementRepository
from app.movements.schemas import (
    AssetDeliveryRequest,
    AssetInspectionRequest,
    AssetMovementCreate,
    AssetMovementResponse,
    AssetReserveRequest,
    AssetReturnRequest,
)
from app.movements.services import AssetMovementService

router = APIRouter()


def get_movement_service(db: AsyncSession = Depends(get_db)) -> AssetMovementService:
    return AssetMovementService(AssetMovementRepository(db), AssetRepository(db))


@router.get(
    "/asset/{asset_id}",
    response_model=list[AssetMovementResponse],
    dependencies=[Depends(require_permission("assets.read"))],
)
async def list_movements_by_asset(
    asset_id: uuid.UUID,
    service: AssetMovementService = Depends(get_movement_service),
):
    """Retorna o histórico de movimentações de um ativo específico."""
    return await service.list_movements_by_asset(asset_id)


@router.post(
    "/",
    response_model=AssetMovementResponse,
    dependencies=[Depends(require_permission("assets.movements.write"))],
)
async def create_movement(
    data: AssetMovementCreate,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    service: AssetMovementService = Depends(get_movement_service),
):
    """Registra uma nova movimentação para um ativo e atualiza seu status/alocação."""
    return await service.create_movement(data, current_user_id)


@router.post(
    "/{asset_id}/reserve",
    response_model=AssetMovementResponse,
    dependencies=[Depends(require_permission("assets.movements.write"))],
)
async def reserve_asset(
    asset_id: uuid.UUID,
    data: AssetReserveRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    service: AssetMovementService = Depends(get_movement_service),
):
    """Reserva um ativo em estoque para um colaborador ou chamado."""
    return await service.reserve_asset(
        asset_id=asset_id,
        author_id=current_user_id,
        employee_id=data.employee_id,
        ticket_id=data.ticket_id,
        notes=data.notes,
    )


@router.post(
    "/{asset_id}/cancel-reservation",
    response_model=AssetMovementResponse,
    dependencies=[Depends(require_permission("assets.movements.write"))],
)
async def cancel_reservation(
    asset_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    service: AssetMovementService = Depends(get_movement_service),
):
    """Cancela a reserva de um ativo, retornando-o para disponível em estoque."""
    return await service.cancel_reservation(asset_id=asset_id, author_id=current_user_id)


@router.post(
    "/{asset_id}/deliver",
    response_model=AssetMovementResponse,
    dependencies=[Depends(require_permission("assets.movements.write"))],
)
async def deliver_asset(
    asset_id: uuid.UUID,
    data: AssetDeliveryRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    service: AssetMovementService = Depends(get_movement_service),
):
    """Efetiva a entrega do equipamento ao colaborador responsável."""
    return await service.deliver_asset(
        asset_id=asset_id,
        author_id=current_user_id,
        employee_id=data.employee_id,
        ticket_id=data.ticket_id,
        notes=data.notes,
    )


@router.post(
    "/{asset_id}/return",
    response_model=AssetMovementResponse,
    dependencies=[Depends(require_permission("assets.movements.write"))],
)
async def return_asset(
    asset_id: uuid.UUID,
    data: AssetReturnRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    service: AssetMovementService = Depends(get_movement_service),
):
    """Registra a devolução física do equipamento, colocando-o em conferência/inspeção."""
    return await service.return_asset(
        asset_id=asset_id,
        author_id=current_user_id,
        ticket_id=data.ticket_id,
        notes=data.notes,
    )


@router.post(
    "/{asset_id}/inspect",
    response_model=AssetMovementResponse,
    dependencies=[Depends(require_permission("assets.movements.write"))],
)
async def inspect_asset(
    asset_id: uuid.UUID,
    data: AssetInspectionRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    service: AssetMovementService = Depends(get_movement_service),
):
    """Conclui a inspeção técnica do ativo devolvido, liberando para estoque ou encaminhando para manutenção."""
    return await service.inspect_asset(
        asset_id=asset_id,
        author_id=current_user_id,
        approved=data.approved,
        notes=data.notes,
        send_to_maintenance=data.send_to_maintenance,
    )
