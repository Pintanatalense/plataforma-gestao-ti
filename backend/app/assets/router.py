import uuid

from fastapi import APIRouter, Depends, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.repository import AssetRepository
from app.assets.schemas import AssetCategoryCreate, AssetCategoryResponse, AssetCategoryUpdate, AssetCreate, AssetResponse, AssetUpdate
from app.assets.services import AssetService
from app.core.dependencies import require_permission, get_current_user_id
from app.database import get_db
from app.movements.repository import AssetMovementRepository


router = APIRouter()


def get_asset_service(db: AsyncSession = Depends(get_db)) -> AssetService:
    return AssetService(AssetRepository(db), AssetMovementRepository(db))


@router.get("/categories", response_model=list[AssetCategoryResponse], dependencies=[Depends(require_permission("assets.read"))])
async def list_categories(
    service: AssetService = Depends(get_asset_service),
):
    return await service.list_categories()


@router.post("/categories", response_model=AssetCategoryResponse, dependencies=[Depends(require_permission("assets.write"))])
async def create_category(
    schema: AssetCategoryCreate,
    service: AssetService = Depends(get_asset_service),
):
    return await service.create_category(schema)


@router.put("/categories/{category_id}", response_model=AssetCategoryResponse, dependencies=[Depends(require_permission("assets.write"))])
async def update_category(
    category_id: uuid.UUID,
    schema: AssetCategoryUpdate,
    service: AssetService = Depends(get_asset_service),
):
    return await service.update_category(category_id, schema)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("assets.write"))])
async def delete_category(
    category_id: uuid.UUID,
    service: AssetService = Depends(get_asset_service),
):
    await service.delete_category(category_id)


@router.get("", response_model=list[AssetResponse], dependencies=[Depends(require_permission("assets.read"))])
async def list_assets(
    unit_id: uuid.UUID | None = None,
    employee_id: uuid.UUID | None = None,
    service: AssetService = Depends(get_asset_service),
):
    return await service.list_assets(unit_id=unit_id, employee_id=employee_id)


@router.get("/{asset_id}", response_model=AssetResponse, dependencies=[Depends(require_permission("assets.read"))])
async def get_asset(
    asset_id: uuid.UUID,
    service: AssetService = Depends(get_asset_service),
):
    return await service.get_asset(asset_id)


@router.post("", response_model=AssetResponse, dependencies=[Depends(require_permission("assets.write"))])
async def create_asset(
    schema: AssetCreate,
    service: AssetService = Depends(get_asset_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    return await service.create_asset(schema, current_user_id)


@router.put("/{asset_id}", response_model=AssetResponse, dependencies=[Depends(require_permission("assets.write"))])
async def update_asset(
    asset_id: uuid.UUID,
    schema: AssetUpdate,
    service: AssetService = Depends(get_asset_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    return await service.update_asset(asset_id, schema, current_user_id)


@router.get(
    "/{asset_id}/responsibility-statement",
    response_class=HTMLResponse,
    summary="Gera Termo de Responsabilidade e Cautela pronto para impressão/PDF",
    dependencies=[Depends(require_permission("assets.read"))]
)
async def get_responsibility_statement(
    asset_id: uuid.UUID,
    service: AssetService = Depends(get_asset_service),
):
    html_content = await service.generate_responsibility_statement(asset_id)
    return HTMLResponse(content=html_content)
