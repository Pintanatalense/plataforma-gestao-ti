import uuid
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import HTTPException, status

from app.inventory_audit.models import InventoryAudit, InventoryAuditItem
from app.inventory_audit.schemas import (
    InventoryAuditCreate, 
    InventoryAuditUpdate, 
    InventoryAuditItemCreate, 
    InventoryAuditItemUpdate
)
from app.inventory_audit.repository import InventoryAuditRepository


class InventoryAuditService:
    def __init__(self, repo: InventoryAuditRepository):
        self.repo = repo

    async def get_audit(self, audit_id: uuid.UUID) -> InventoryAudit:
        audit = await self.repo.get_by_id(audit_id)
        if not audit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Inventário não encontrado"
            )
        return audit

    async def list_audits(self, unit_id: Optional[uuid.UUID] = None) -> List[InventoryAudit]:
        return await self.repo.list_all(unit_id)

    async def create_audit(self, data: InventoryAuditCreate) -> InventoryAudit:
        return await self.repo.create(data)

    async def update_audit(self, audit_id: uuid.UUID, data: InventoryAuditUpdate) -> InventoryAudit:
        audit = await self.get_audit(audit_id)
        
        # Se estivermos fechando o inventário, gravar end_date se não foi passado
        if data.status == "CLOSED" and not data.end_date and not audit.end_date:
            data.end_date = datetime.now(timezone.utc)
            
        # Se mudar para IN_PROGRESS, gravar start_date se não existir
        if data.status == "IN_PROGRESS" and not data.start_date and not audit.start_date:
            data.start_date = datetime.now(timezone.utc)
            
        return await self.repo.update(audit, data)

    async def add_item_to_audit(self, audit_id: uuid.UUID, data: InventoryAuditItemCreate) -> InventoryAuditItem:
        audit = await self.get_audit(audit_id)
        if audit.status in ["CLOSED", "CANCELLED"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Não é possível adicionar itens a um inventário fechado ou cancelado"
            )
            
        if data.audit_id != audit_id:
            data.audit_id = audit_id
            
        return await self.repo.add_item(data)

    async def update_audit_item(
        self, audit_id: uuid.UUID, item_id: uuid.UUID, data: InventoryAuditItemUpdate
    ) -> InventoryAuditItem:
        audit = await self.get_audit(audit_id)
        if audit.status in ["CLOSED", "CANCELLED"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Não é possível alterar itens em um inventário fechado ou cancelado"
            )
            
        item = await self.repo.get_item_by_id(item_id)
        if not item or item.audit_id != audit_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Item de inventário não encontrado"
            )
            
        return await self.repo.update_item(item, data)
