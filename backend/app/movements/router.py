import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.repository import AssetRepository
from app.core.dependencies import get_current_user_id, require_permission
from app.database import get_db
from app.movements.repository import AssetMovementRepository
from app.movements.schemas import AssetMovementCreate, AssetMovementResponse
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
    dependencies=[Depends(require_permission("assets.write"))],
)
async def create_movement(
    data: AssetMovementCreate,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    service: AssetMovementService = Depends(get_movement_service),
):
    """Registra uma nova movimentação para um ativo e atualiza seu status/alocação."""
    return await service.create_movement(data, current_user_id)
