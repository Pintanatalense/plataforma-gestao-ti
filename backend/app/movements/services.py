import uuid

from app.assets.models import AssetStatus
from app.assets.repository import AssetRepository
from app.core.exceptions import (
    BusinessRuleException,
    ConflictException,
    NotFoundException,
    ValidationException,
)
from app.movements.models import AssetMovement, MovementType
from app.movements.repository import AssetMovementRepository
from app.movements.schemas import AssetMovementCreate


class AssetMovementService:
    def __init__(self, repo: AssetMovementRepository, asset_repo: AssetRepository):
        self.repo = repo
        self.asset_repo = asset_repo

    async def list_movements_by_asset(self, asset_id: uuid.UUID) -> list[AssetMovement]:
        return list(await self.repo.list_movements_by_asset(asset_id))

    async def create_movement(self, data: AssetMovementCreate, author_id: uuid.UUID) -> AssetMovement:
        asset = await self.asset_repo.get_asset(data.asset_id)
        if not asset:
            raise NotFoundException("Ativo", data.asset_id)

        if asset.status == AssetStatus.DECOMMISSIONED.value:
            raise BusinessRuleException("Ativo baixado não pode sofrer novas movimentações.")

        movement_type = data.movement_type
        movement_type_str = movement_type.value if isinstance(movement_type, MovementType) else str(movement_type)

        from_unit_id = asset.unit_id
        to_unit_id = data.to_unit_id or asset.unit_id
        from_employee_id = asset.employee_id
        status_from = asset.status

        # Regras por tipo de movimentação
        if movement_type_str == MovementType.ASSIGNMENT.value:
            # Prevenção de conflito: entrega duplicada em ativo em uso
            if asset.status == AssetStatus.IN_USE.value or asset.employee_id is not None:
                raise ConflictException("Ativo já está em uso / atribuído a um colaborador.")
            if not data.to_employee_id:
                raise ValidationException("Atribuição de ativo exige o colaborador responsável (to_employee_id).")

            to_employee_id = data.to_employee_id
            status_to = (
                data.status_to.value if isinstance(data.status_to, AssetStatus) else data.status_to
            ) or AssetStatus.IN_USE.value

        elif movement_type_str == MovementType.RETURN.value:
            to_employee_id = None
            status_to = (
                data.status_to.value if isinstance(data.status_to, AssetStatus) else data.status_to
            ) or AssetStatus.IN_STOCK.value

        elif movement_type_str == MovementType.TRANSFER.value:
            to_employee_id = data.to_employee_id if data.to_employee_id is not None else asset.employee_id
            status_to = (
                data.status_to.value if isinstance(data.status_to, AssetStatus) else data.status_to
            ) or asset.status

        elif movement_type_str == MovementType.MAINTENANCE.value:
            # Preserva a posse se to_employee_id não for informado explicitamente
            to_employee_id = data.to_employee_id if data.to_employee_id is not None else asset.employee_id
            status_to = (
                data.status_to.value if isinstance(data.status_to, AssetStatus) else data.status_to
            ) or AssetStatus.MAINTENANCE.value

        elif movement_type_str == MovementType.DECOMMISSION.value:
            to_employee_id = None
            status_to = AssetStatus.DECOMMISSIONED.value

        elif movement_type_str == MovementType.INITIAL_STOCK.value:
            to_employee_id = None
            status_to = AssetStatus.IN_STOCK.value

        else:
            raise ValidationException(f"Tipo de movimentação inválido: {movement_type_str}")

        # Cria registro de movimentação
        movement = AssetMovement(
            asset_id=asset.id,
            movement_type=movement_type_str,
            from_unit_id=from_unit_id,
            to_unit_id=to_unit_id,
            from_employee_id=from_employee_id,
            to_employee_id=to_employee_id,
            status_from=status_from,
            status_to=status_to,
            notes=data.notes,
            author_id=author_id,
        )
        movement = await self.repo.create_movement(movement)

        # Atualiza o ativo
        asset.unit_id = to_unit_id
        asset.employee_id = to_employee_id
        asset.status = status_to

        await self.asset_repo.update_asset(asset)

        return movement
