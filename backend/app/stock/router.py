import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import get_current_user_id, require_permission
from app.stock.schemas import (
    StockCategoryCreate,
    StockCategoryResponse,
    StockCategoryUpdate,
    StockItemCreate,
    StockItemResponse,
    StockItemUpdate,
    StockMovementCreate,
    StockMovementResponse,
)
from app.stock.repository import StockRepository
from app.stock.services import StockService

router = APIRouter(tags=["stock"])


def get_stock_service(db: AsyncSession = Depends(get_db)) -> StockService:
    repo = StockRepository(db)
    return StockService(repo)


# ============================================================================
# Categorias de Estoque
# ============================================================================

@router.get(
    "/categories",
    response_model=List[StockCategoryResponse],
    dependencies=[Depends(require_permission("stock.read"))],
)
async def list_categories(
    service: StockService = Depends(get_stock_service),
):
    return await service.list_categories()


@router.post(
    "/categories",
    response_model=StockCategoryResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("stock.write"))],
)
async def create_category(
    schema: StockCategoryCreate,
    service: StockService = Depends(get_stock_service),
    session: AsyncSession = Depends(get_db),
):
    category = await service.create_category(schema)
    await session.commit()
    return category


@router.get(
    "/categories/{category_id}",
    response_model=StockCategoryResponse,
    dependencies=[Depends(require_permission("stock.read"))],
)
async def get_category(
    category_id: uuid.UUID,
    service: StockService = Depends(get_stock_service),
):
    return await service.get_category(category_id)


@router.put(
    "/categories/{category_id}",
    response_model=StockCategoryResponse,
    dependencies=[Depends(require_permission("stock.write"))],
)
async def update_category(
    category_id: uuid.UUID,
    schema: StockCategoryUpdate,
    service: StockService = Depends(get_stock_service),
    session: AsyncSession = Depends(get_db),
):
    category = await service.update_category(category_id, schema)
    await session.commit()
    return category


@router.delete(
    "/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("stock.write"))],
)
async def delete_category(
    category_id: uuid.UUID,
    service: StockService = Depends(get_stock_service),
    session: AsyncSession = Depends(get_db),
):
    await service.delete_category(category_id)
    await session.commit()


# ============================================================================
# Itens de Estoque
# ============================================================================

@router.get(
    "/items",
    response_model=List[StockItemResponse],
    dependencies=[Depends(require_permission("stock.read"))],
)
async def list_items(
    unit_id: Optional[uuid.UUID] = None,
    service: StockService = Depends(get_stock_service),
):
    return await service.list_items(unit_id)


@router.post(
    "/items",
    response_model=StockItemResponse,
    dependencies=[Depends(require_permission("stock.write"))],
)
async def create_item(
    schema: StockItemCreate,
    service: StockService = Depends(get_stock_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
):
    item = await service.create_item(schema, current_user_id)
    await session.commit()
    return item


@router.get(
    "/items/{item_id}",
    response_model=StockItemResponse,
    dependencies=[Depends(require_permission("stock.read"))],
)
async def get_item(
    item_id: uuid.UUID,
    service: StockService = Depends(get_stock_service),
):
    return await service.get_item(item_id)


@router.put(
    "/items/{item_id}",
    response_model=StockItemResponse,
    dependencies=[Depends(require_permission("stock.write"))],
)
async def update_item(
    item_id: uuid.UUID,
    schema: StockItemUpdate,
    service: StockService = Depends(get_stock_service),
    session: AsyncSession = Depends(get_db),
):
    item = await service.update_item(item_id, schema)
    await session.commit()
    return item


# ============================================================================
# Movimentações
# ============================================================================

@router.post(
    "/movements",
    response_model=StockMovementResponse,
    dependencies=[Depends(require_permission("stock.write"))],
)
async def create_movement(
    schema: StockMovementCreate,
    service: StockService = Depends(get_stock_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
):
    mov = await service.add_movement(schema, current_user_id)
    await session.commit()
    return mov


@router.get(
    "/movements/item/{item_id}",
    response_model=List[StockMovementResponse],
    dependencies=[Depends(require_permission("stock.read"))],
)
async def list_movements(
    item_id: uuid.UUID,
    service: StockService = Depends(get_stock_service),
):
    return await service.list_movements(item_id)
