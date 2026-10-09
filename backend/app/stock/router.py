import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import get_current_user_id, require_permission
from app.stock.schemas import StockItemResponse, StockItemCreate, StockItemUpdate, StockMovementResponse, StockMovementCreate
from app.stock.repository import StockRepository
from app.stock.services import StockService

router = APIRouter(tags=["stock"])

def get_stock_service(db: AsyncSession = Depends(get_db)) -> StockService:
    repo = StockRepository(db)
    return StockService(repo)

@router.get("/items", response_model=List[StockItemResponse], dependencies=[Depends(require_permission("stock.read"))])
async def list_items(
    unit_id: Optional[uuid.UUID] = None,
    service: StockService = Depends(get_stock_service),
):
    return await service.list_items(unit_id)

@router.post("/items", response_model=StockItemResponse, dependencies=[Depends(require_permission("stock.write"))])
async def create_item(
    schema: StockItemCreate,
    service: StockService = Depends(get_stock_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db)
):
    item = await service.create_item(schema, current_user_id)
    await session.commit()
    return item

@router.get("/items/{item_id}", response_model=StockItemResponse, dependencies=[Depends(require_permission("stock.read"))])
async def get_item(
    item_id: uuid.UUID,
    service: StockService = Depends(get_stock_service),
):
    return await service.get_item(item_id)

@router.put("/items/{item_id}", response_model=StockItemResponse, dependencies=[Depends(require_permission("stock.write"))])
async def update_item(
    item_id: uuid.UUID,
    schema: StockItemUpdate,
    service: StockService = Depends(get_stock_service),
    session: AsyncSession = Depends(get_db)
):
    item = await service.update_item(item_id, schema)
    await session.commit()
    return item

@router.post("/movements", response_model=StockMovementResponse, dependencies=[Depends(require_permission("stock.write"))])
async def create_movement(
    schema: StockMovementCreate,
    service: StockService = Depends(get_stock_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db)
):
    mov = await service.add_movement(schema, current_user_id)
    await session.commit()
    return mov

@router.get("/movements/item/{item_id}", response_model=List[StockMovementResponse], dependencies=[Depends(require_permission("stock.read"))])
async def list_movements(
    item_id: uuid.UUID,
    service: StockService = Depends(get_stock_service),
):
    return await service.list_movements(item_id)
