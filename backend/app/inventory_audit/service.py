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

    async def create_audit(self, data: InventoryAuditCreate, fallback_user_id: Optional[uuid.UUID] = None) -> InventoryAudit:
        from app.identity.models import UserAccount
        from sqlalchemy import select

        # Resolver auditor_id: caso tenha vindo o employee_id selecionado no frontend
        stmt_user = select(UserAccount).where(
            (UserAccount.id == data.auditor_id) | (UserAccount.employee_id == data.auditor_id)
        )
        user_res = await self.repo.session.execute(stmt_user)
        user = user_res.scalars().first()
        if user:
            data.auditor_id = user.id
        elif fallback_user_id:
            data.auditor_id = fallback_user_id

        audit = await self.repo.create(data)
        await self.populate_audit_items(audit.id)
        return await self.get_audit(audit.id)

    async def populate_audit_items(self, audit_id: uuid.UUID) -> InventoryAudit:
        from sqlalchemy import select
        from app.assets.models import Asset
        from app.stock.models import StockItem

        audit = await self.get_audit(audit_id)
        if audit.status in ["CLOSED", "CANCELLED"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Não é possível sincronizar itens de um inventário fechado ou cancelado"
            )

        existing_asset_ids = {item.asset_id for item in audit.items if item.asset_id}
        existing_stock_ids = {item.stock_item_id for item in audit.items if item.stock_item_id}

        # 1. Ativos pertencentes à unidade do inventário
        stmt_assets = select(Asset).where(
            Asset.unit_id == audit.unit_id,
            Asset.deleted_at.is_(None)
        )
        assets_res = await self.repo.session.execute(stmt_assets)
        assets = assets_res.scalars().all()

        for a in assets:
            if a.id not in existing_asset_ids:
                new_item = InventoryAuditItem(
                    audit_id=audit.id,
                    asset_id=a.id,
                    item_type="ASSET",
                    expected_status=a.status,
                    actual_status=None,
                    notes=None
                )
                self.repo.session.add(new_item)

        # 2. Itens de estoque pertencentes à unidade do inventário
        stmt_stock = select(StockItem).where(
            StockItem.unit_id == audit.unit_id
        )
        stock_res = await self.repo.session.execute(stmt_stock)
        stock_items = stock_res.scalars().all()

        for s in stock_items:
            if s.id not in existing_stock_ids:
                new_item = InventoryAuditItem(
                    audit_id=audit.id,
                    stock_item_id=s.id,
                    item_type="STOCK",
                    expected_quantity=s.quantity,
                    actual_quantity=None,
                    notes=None
                )
                self.repo.session.add(new_item)

        await self.repo.session.flush()
        await self.repo.session.refresh(audit, ["items"])
        return audit

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
