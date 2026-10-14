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
        # Usa lock transacional para impedir concorrência em operações de movimentação
        asset = await self.asset_repo.get_asset_for_update(data.asset_id)
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
        ticket_id = data.ticket_id

        # Regras da Máquina de Estados por tipo de movimentação
        if movement_type_str == MovementType.RESERVATION.value:
            # Reserva: apenas ativos disponíveis em estoque podem ser reservados
            if asset.status == AssetStatus.RESERVED.value:
                raise ConflictException("Ativo já se encontra reservado.")
            if asset.status == AssetStatus.IN_USE.value or asset.employee_id is not None:
                raise ConflictException("Ativo já está em uso / atribuído a um colaborador.")
            if asset.status == AssetStatus.PENDING_INSPECTION.value:
                raise BusinessRuleException("Ativo aguarda conferência/inspeção técnica pós-devolução e não pode ser reservado.")
            if asset.status == AssetStatus.MAINTENANCE.value:
                raise BusinessRuleException("Ativo em manutenção não pode ser reservado.")

            to_employee_id = data.to_employee_id
            status_to = AssetStatus.RESERVED.value

        elif movement_type_str == MovementType.RESERVATION_CANCEL.value:
            # Cancelamento de reserva: retorna ao estoque
            if asset.status != AssetStatus.RESERVED.value:
                raise BusinessRuleException(f"Não é possível cancelar reserva: ativo está com status {asset.status}.")

            to_employee_id = None
            status_to = AssetStatus.IN_STOCK.value

        elif movement_type_str == MovementType.ASSIGNMENT.value:
            # Prevenção de conflito: entrega duplicada em ativo em uso
            if asset.status == AssetStatus.IN_USE.value or (asset.employee_id is not None and asset.status != AssetStatus.RESERVED.value):
                raise ConflictException("Ativo já está em uso / atribuído a um colaborador.")
            if asset.status == AssetStatus.PENDING_INSPECTION.value:
                raise BusinessRuleException("Ativo aguarda conferência/inspeção técnica pós-devolução antes de ser entregue.")
            if asset.status == AssetStatus.MAINTENANCE.value:
                raise BusinessRuleException("Ativo em manutenção não pode ser entregue.")
            if not data.to_employee_id:
                raise ValidationException("Atribuição de ativo exige o colaborador responsável (to_employee_id).")

            to_employee_id = data.to_employee_id
            status_to = (
                data.status_to.value if isinstance(data.status_to, AssetStatus) else data.status_to
            ) or AssetStatus.IN_USE.value

        elif movement_type_str == MovementType.RETURN.value:
            # Devolução física: transiciona por padrão para PENDING_INSPECTION (aguardando conferência)
            # A devolução não deve significar liberação automática para nova entrega.
            if asset.status not in (AssetStatus.IN_USE.value, AssetStatus.RESERVED.value):
                if not data.status_to:
                    raise BusinessRuleException(f"Não é possível registrar devolução para ativo com status {asset.status}.")

            to_employee_id = None
            status_to = (
                data.status_to.value if isinstance(data.status_to, AssetStatus) else data.status_to
            ) or AssetStatus.PENDING_INSPECTION.value

        elif movement_type_str == MovementType.INSPECTION_RELEASE.value:
            # Liberação pós-inspeção: equipamento conferido com sucesso e liberado para estoque
            if asset.status not in (AssetStatus.PENDING_INSPECTION.value, AssetStatus.MAINTENANCE.value):
                raise BusinessRuleException(
                    f"Apenas ativos aguardando inspeção ou em manutenção podem ser liberados para estoque (status atual: {asset.status})."
                )

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

        # Cria registro de movimentação com auditoria e vínculo de ticket
        movement = AssetMovement(
            asset_id=asset.id,
            movement_type=movement_type_str,
            from_unit_id=from_unit_id,
            to_unit_id=to_unit_id,
            from_employee_id=from_employee_id,
            to_employee_id=to_employee_id,
            status_from=status_from,
            status_to=status_to,
            ticket_id=ticket_id,
            notes=data.notes,
            author_id=author_id,
        )
        movement = await self.repo.create_movement(movement)

        # Atualiza o ativo atomicamente
        asset.unit_id = to_unit_id
        asset.employee_id = to_employee_id
        asset.status = status_to

        await self.asset_repo.update_asset(asset)

        return movement

    async def reserve_asset(
        self,
        asset_id: uuid.UUID,
        author_id: uuid.UUID,
        employee_id: uuid.UUID | None = None,
        ticket_id: uuid.UUID | None = None,
        notes: str | None = None,
    ) -> AssetMovement:
        data = AssetMovementCreate(
            asset_id=asset_id,
            movement_type=MovementType.RESERVATION,
            to_employee_id=employee_id,
            ticket_id=ticket_id,
            notes=notes or "Reserva de equipamento efetuada.",
        )
        return await self.create_movement(data, author_id)

    async def cancel_reservation(
        self,
        asset_id: uuid.UUID,
        author_id: uuid.UUID,
        notes: str | None = None,
    ) -> AssetMovement:
        data = AssetMovementCreate(
            asset_id=asset_id,
            movement_type=MovementType.RESERVATION_CANCEL,
            notes=notes or "Cancelamento de reserva.",
        )
        return await self.create_movement(data, author_id)

    async def deliver_asset(
        self,
        asset_id: uuid.UUID,
        author_id: uuid.UUID,
        employee_id: uuid.UUID,
        ticket_id: uuid.UUID | None = None,
        notes: str | None = None,
    ) -> AssetMovement:
        data = AssetMovementCreate(
            asset_id=asset_id,
            movement_type=MovementType.ASSIGNMENT,
            to_employee_id=employee_id,
            ticket_id=ticket_id,
            notes=notes or "Entrega efetiva de equipamento ao colaborador.",
        )
        return await self.create_movement(data, author_id)

    async def return_asset(
        self,
        asset_id: uuid.UUID,
        author_id: uuid.UUID,
        ticket_id: uuid.UUID | None = None,
        notes: str | None = None,
    ) -> AssetMovement:
        data = AssetMovementCreate(
            asset_id=asset_id,
            movement_type=MovementType.RETURN,
            ticket_id=ticket_id,
            notes=notes or "Devolução física do equipamento registrada (aguarda inspeção técnica).",
        )
        return await self.create_movement(data, author_id)

    async def inspect_asset(
        self,
        asset_id: uuid.UUID,
        author_id: uuid.UUID,
        approved: bool,
        ticket_id: uuid.UUID | None = None,
        notes: str | None = None,
        send_to_maintenance: bool = False,
    ) -> AssetMovement:
        if approved:
            data = AssetMovementCreate(
                asset_id=asset_id,
                movement_type=MovementType.INSPECTION_RELEASE,
                ticket_id=ticket_id,
                notes=notes or "Conferência técnica aprovada. Equipamento liberado para estoque.",
            )
        elif send_to_maintenance:
            data = AssetMovementCreate(
                asset_id=asset_id,
                movement_type=MovementType.MAINTENANCE,
                ticket_id=ticket_id,
                notes=notes or "Conferência técnica identificou defeitos. Equipamento encaminhado para manutenção.",
            )
        else:
            raise ValidationException("Se a conferência não foi aprovada, informe 'send_to_maintenance=True'.")

        return await self.create_movement(data, author_id)
