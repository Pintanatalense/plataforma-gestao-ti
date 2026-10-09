import uuid
from fastapi import HTTPException

from app.movements.models import AssetMovement
from app.movements.repository import AssetMovementRepository
from app.movements.schemas import AssetMovementCreate
from app.assets.repository import AssetRepository


class AssetMovementService:
    def __init__(self, repo: AssetMovementRepository, asset_repo: AssetRepository):
        self.repo = repo
        self.asset_repo = asset_repo

    async def list_movements_by_asset(self, asset_id: uuid.UUID) -> list[AssetMovement]:
        return list(await self.repo.list_movements_by_asset(asset_id))

    async def create_movement(self, data: AssetMovementCreate, author_id: uuid.UUID) -> AssetMovement:
        asset = await self.asset_repo.get_asset(data.asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        # Create movement record
        movement = AssetMovement(
            asset_id=asset.id,
            movement_type=data.movement_type,
            from_unit_id=asset.unit_id,
            to_unit_id=data.to_unit_id or asset.unit_id,
            from_employee_id=asset.employee_id,
            to_employee_id=data.to_employee_id,
            status_from=asset.status,
            status_to=data.status_to or asset.status,
            notes=data.notes,
            author_id=author_id,
        )

        movement = await self.repo.create_movement(movement)

        # Update Asset
        if data.to_unit_id:
            asset.unit_id = data.to_unit_id
        
        # When assigning or returning, employee_id can change
        # A return or un-assignment sets it to None
        asset.employee_id = data.to_employee_id
        
        if data.status_to:
            asset.status = data.status_to

        await self.asset_repo.update_asset(asset)

        return movement
