import uuid

from app.assets.models import Asset, AssetCategory, AssetStatus
from app.assets.repository import AssetRepository
from app.assets.schemas import AssetCategoryCreate, AssetCategoryUpdate, AssetCreate, AssetUpdate
from app.core.exceptions import (
    BusinessRuleException,
    NotFoundException,
    ValidationException,
)
from app.movements.models import AssetMovement, MovementType
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
            raise NotFoundException("Categoria", category_id)
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
            raise NotFoundException("Ativo", asset_id)
        return asset

    async def create_asset(self, schema: AssetCreate, author_id: uuid.UUID) -> Asset:
        existing = await self.repo.get_asset_by_tag(schema.tag)
        if existing:
            raise ValidationException(f"Ativo com patrimônio {schema.tag} já existe.")

        asset_data = schema.model_dump()
        status_val = asset_data.get("status", AssetStatus.IN_STOCK)
        if isinstance(status_val, AssetStatus):
            status_val = status_val.value
            asset_data["status"] = status_val

        # Validações de consistência de estado inicial
        if status_val == AssetStatus.IN_STOCK.value and asset_data.get("employee_id"):
            raise ValidationException("Ativo em estoque (IN_STOCK) não pode possuir colaborador atribuído.")
        if status_val == AssetStatus.IN_USE.value and not asset_data.get("employee_id"):
            raise ValidationException("Ativo em uso (IN_USE) deve possuir um colaborador atribuído.")

        asset = Asset(**asset_data)
        asset = await self.repo.create_asset(asset)

        movement_type = (
            MovementType.ASSIGNMENT.value if asset.employee_id else MovementType.INITIAL_STOCK.value
        )

        movement = AssetMovement(
            asset_id=asset.id,
            movement_type=movement_type,
            to_unit_id=asset.unit_id,
            to_employee_id=asset.employee_id,
            status_to=asset.status,
            notes="Cadastro inicial do ativo.",
            author_id=author_id,
        )
        await self.movement_repo.create_movement(movement)

        # Reload to get category relation populated
        return await self.get_asset(asset.id)

    async def update_asset(self, asset_id: uuid.UUID, schema: AssetUpdate, author_id: uuid.UUID) -> Asset:
        asset = await self.get_asset(asset_id)

        if asset.status == AssetStatus.DECOMMISSIONED.value:
            raise BusinessRuleException("Ativo já baixado não pode ser modificado.")

        from_unit_id = asset.unit_id
        from_employee_id = asset.employee_id
        status_from = asset.status

        update_data = schema.model_dump(exclude_unset=True)

        # Check if tag is being changed and is unique
        if "tag" in update_data and update_data["tag"] != asset.tag:
            existing = await self.repo.get_asset_by_tag(update_data["tag"])
            if existing:
                raise ValidationException(f"Ativo com patrimônio {update_data['tag']} já existe.")

        new_status = update_data.get("status", asset.status)
        if isinstance(new_status, AssetStatus):
            new_status = new_status.value
            update_data["status"] = new_status

        target_employee = update_data.get("employee_id", asset.employee_id)
        if new_status == AssetStatus.IN_STOCK.value and target_employee is not None:
            raise ValidationException("Ativo em estoque (IN_STOCK) não pode possuir colaborador atribuído.")
        if new_status == AssetStatus.DECOMMISSIONED.value and target_employee is not None:
            raise ValidationException("Ativo baixado (DECOMMISSIONED) não pode possuir colaborador atribuído.")

        for key, value in update_data.items():
            setattr(asset, key, value)

        asset = await self.repo.update_asset(asset)

        # Record movement if location, assignment or status changed
        if (
            from_unit_id != asset.unit_id
            or from_employee_id != asset.employee_id
            or status_from != asset.status
        ):
            movement_type = MovementType.TRANSFER.value
            if not from_employee_id and asset.employee_id:
                movement_type = MovementType.ASSIGNMENT.value
            elif from_employee_id and not asset.employee_id:
                movement_type = MovementType.RETURN.value

            if asset.status == AssetStatus.MAINTENANCE.value:
                movement_type = MovementType.MAINTENANCE.value
            elif asset.status == AssetStatus.DECOMMISSIONED.value:
                movement_type = MovementType.DECOMMISSION.value

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
                author_id=author_id,
            )
            await self.movement_repo.create_movement(movement)

        return asset
