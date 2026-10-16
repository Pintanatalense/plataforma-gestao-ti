import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends

from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db

from app.core.dependencies import get_current_user_id, require_permission

from app.inventory_audit.schemas import (
    InventoryAuditCreate,
    InventoryAuditUpdate,
    InventoryAuditOut,
    InventoryAuditWithItemsOut,
    InventoryAuditItemCreate,
    InventoryAuditItemUpdate,
    InventoryAuditItemOut
)
from app.inventory_audit.repository import InventoryAuditRepository
from app.inventory_audit.service import InventoryAuditService

router = APIRouter(tags=["Inventory Audit"])

def get_inventory_audit_service(db: AsyncSession = Depends(get_db)) -> InventoryAuditService:
    repo = InventoryAuditRepository(db)
    return InventoryAuditService(repo)


@router.post("", response_model=InventoryAuditWithItemsOut, dependencies=[Depends(require_permission("inventory.write"))])
async def create_audit(
    data: InventoryAuditCreate,
    service: InventoryAuditService = Depends(get_inventory_audit_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id)
):
    return await service.create_audit(data, fallback_user_id=current_user_id)


@router.post("/{audit_id}/populate", response_model=InventoryAuditWithItemsOut, dependencies=[Depends(require_permission("inventory.write"))])
async def populate_audit_items(
    audit_id: uuid.UUID,
    service: InventoryAuditService = Depends(get_inventory_audit_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id)
):
    return await service.populate_audit_items(audit_id)


@router.get("", response_model=List[InventoryAuditOut], dependencies=[Depends(require_permission("inventory.read"))])
async def list_audits(
    unit_id: Optional[uuid.UUID] = None,
    service: InventoryAuditService = Depends(get_inventory_audit_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id)
):
    return await service.list_audits(unit_id)


@router.get("/{audit_id}", response_model=InventoryAuditWithItemsOut, dependencies=[Depends(require_permission("inventory.read"))])
async def get_audit(
    audit_id: uuid.UUID,
    service: InventoryAuditService = Depends(get_inventory_audit_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id)
):
    return await service.get_audit(audit_id)


@router.patch("/{audit_id}", response_model=InventoryAuditOut, dependencies=[Depends(require_permission("inventory.write"))])
async def update_audit(
    audit_id: uuid.UUID,
    data: InventoryAuditUpdate,
    service: InventoryAuditService = Depends(get_inventory_audit_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id)
):
    return await service.update_audit(audit_id, data)


@router.post("/{audit_id}/items", response_model=InventoryAuditItemOut, dependencies=[Depends(require_permission("inventory.write"))])
async def add_item_to_audit(
    audit_id: uuid.UUID,
    data: InventoryAuditItemCreate,
    service: InventoryAuditService = Depends(get_inventory_audit_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id)
):
    return await service.add_item_to_audit(audit_id, data)


@router.patch("/{audit_id}/items/{item_id}", response_model=InventoryAuditItemOut, dependencies=[Depends(require_permission("inventory.write"))])
async def update_audit_item(
    audit_id: uuid.UUID,
    item_id: uuid.UUID,
    data: InventoryAuditItemUpdate,
    service: InventoryAuditService = Depends(get_inventory_audit_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id)
):
    return await service.update_audit_item(audit_id, item_id, data)
