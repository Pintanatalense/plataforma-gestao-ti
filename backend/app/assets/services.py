import uuid

from app.assets.models import Asset, AssetCategory
from app.assets.repository import AssetRepository
from app.assets.schemas import AssetCategoryCreate, AssetCategoryUpdate, AssetCreate, AssetUpdate
from app.core.exceptions import NotFoundException, ValidationException
from app.movements.models import AssetMovement
from app.movements.repository import AssetMovementRepository


class AssetService:
    def __init__(self, repo: AssetRepository, movement_repo: AssetMovementRepository):
        self.repo = repo
        self.movement_repo = movement_repo

    async def list_categories(self) -> list[AssetCategory]:
        return list(await self.repo.list_categories())

    async def get_category(self, category_id: uuid.UUID) -> AssetCategory:
        category = await self.repo.get_category(category_id)
        if not category:
            raise NotFoundException("Categoria não encontrada.")
        return category

    async def create_category(self, schema: AssetCategoryCreate) -> AssetCategory:
        category = AssetCategory(**schema.model_dump())
        return await self.repo.create_category(category)

    async def update_category(self, category_id: uuid.UUID, schema: AssetCategoryUpdate) -> AssetCategory:
        category = await self.get_category(category_id)
        for key, value in schema.model_dump(exclude_unset=True).items():
            setattr(category, key, value)
        return await self.repo.update_category(category)

    async def list_assets(self, unit_id: uuid.UUID | None = None, employee_id: uuid.UUID | None = None) -> list[Asset]:
        return list(await self.repo.list_assets(unit_id=unit_id, employee_id=employee_id))

    async def get_asset(self, asset_id: uuid.UUID) -> Asset:
        asset = await self.repo.get_asset(asset_id)
        if not asset:
            raise NotFoundException("Ativo não encontrado.")
        return asset

    async def create_asset(self, schema: AssetCreate, author_id: uuid.UUID) -> Asset:
        existing = await self.repo.get_asset_by_tag(schema.tag)
        if existing:
            raise ValidationException(f"Ativo com patrimônio {schema.tag} já existe.")

        asset = Asset(**schema.model_dump())
        asset = await self.repo.create_asset(asset)

        movement_type = "ASSIGNMENT" if asset.employee_id else "INITIAL_STOCK"
        
        movement = AssetMovement(
            asset_id=asset.id,
            movement_type=movement_type,
            to_unit_id=asset.unit_id,
            to_employee_id=asset.employee_id,
            status_to=asset.status,
            notes="Cadastro inicial do ativo.",
            author_id=author_id
        )
        await self.movement_repo.create_movement(movement)
        
        # Reload to get category relation populated
        return await self.get_asset(asset.id)

    async def update_asset(self, asset_id: uuid.UUID, schema: AssetUpdate, author_id: uuid.UUID) -> Asset:
        asset = await self.get_asset(asset_id)

        from_unit_id = asset.unit_id
        from_employee_id = asset.employee_id
        status_from = asset.status

        update_data = schema.model_dump(exclude_unset=True)
        
        # Check if tag is being changed and is unique
        if "tag" in update_data and update_data["tag"] != asset.tag:
            existing = await self.repo.get_asset_by_tag(update_data["tag"])
            if existing:
                raise ValidationException(f"Ativo com patrimônio {update_data['tag']} já existe.")

        for key, value in update_data.items():
            setattr(asset, key, value)

        asset = await self.repo.update_asset(asset)

        # Record movement if location, assignment or status changed
        if (from_unit_id != asset.unit_id or 
            from_employee_id != asset.employee_id or 
            status_from != asset.status):
            
            movement_type = "TRANSFER"
            if not from_employee_id and asset.employee_id:
                movement_type = "ASSIGNMENT"
            elif from_employee_id and not asset.employee_id:
                movement_type = "RETURN"
            
            if asset.status == "MAINTENANCE":
                movement_type = "MAINTENANCE"
            elif asset.status == "DECOMMISSIONED":
                movement_type = "DECOMMISSION"

            movement = AssetMovement(
                asset_id=asset.id,
                movement_type=movement_type,
                from_unit_id=from_unit_id,
                to_unit_id=asset.unit_id,
                from_employee_id=from_employee_id,
                to_employee_id=asset.employee_id,
                status_from=status_from,
                status_to=asset.status,
                notes="Atualização de alocação ou status.",
                author_id=author_id
            )
            await self.movement_repo.create_movement(movement)

        return asset
