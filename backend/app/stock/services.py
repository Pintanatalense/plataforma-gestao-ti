import uuid
from app.core.exceptions import NotFoundException, BusinessRuleException
from app.stock.repository import StockRepository
from app.stock.schemas import StockItemCreate, StockItemUpdate, StockMovementCreate
from app.stock.models import StockItem, StockMovement

class StockService:
    def __init__(self, repo: StockRepository):
        self.repo = repo

    async def list_items(self, unit_id: uuid.UUID = None):
        return await self.repo.get_items(unit_id)

    async def get_item(self, item_id: uuid.UUID):
        item = await self.repo.get_item(item_id)
        if not item:
            raise NotFoundException("Item de Estoque", item_id)
        return item

    async def create_item(self, schema: StockItemCreate, author_id: uuid.UUID):
        item = StockItem(
            name=schema.name,
            description=schema.description,
            unit_id=schema.unit_id,
            quantity=schema.initial_quantity,
            min_quantity=schema.min_quantity
        )
        item = await self.repo.create_item(item)
        
        if schema.initial_quantity > 0:
            mov = StockMovement(
                item_id=item.id,
                movement_type="IN",
                quantity=schema.initial_quantity,
                author_id=author_id,
                notes="Estoque inicial"
            )
            await self.repo.create_movement(mov)

        return item

    async def update_item(self, item_id: uuid.UUID, schema: StockItemUpdate):
        item = await self.get_item(item_id)
        if schema.name is not None:
            item.name = schema.name
        if schema.description is not None:
            item.description = schema.description
        if schema.min_quantity is not None:
            item.min_quantity = schema.min_quantity
        
        return await self.repo.update_item(item)

    async def add_movement(self, schema: StockMovementCreate, author_id: uuid.UUID):
        item = await self.get_item(schema.item_id)
        
        if schema.movement_type == "OUT" and item.quantity < schema.quantity:
            raise BusinessRuleException("Estoque insuficiente para esta saída.")

        if schema.movement_type == "IN":
            item.quantity += schema.quantity
        elif schema.movement_type == "OUT":
            item.quantity -= schema.quantity
        elif schema.movement_type == "ADJUST":
            item.quantity += schema.quantity
        else:
            raise BusinessRuleException("Tipo de movimentação inválido.")

        mov = StockMovement(
            item_id=item.id,
            movement_type=schema.movement_type,
            quantity=schema.quantity,
            author_id=author_id,
            notes=schema.notes
        )
        
        await self.repo.create_movement(mov)
        # item is automatically saved/committed since they share session or update_item is called
        await self.repo.update_item(item)
        
        return mov

    async def list_movements(self, item_id: uuid.UUID):
        return await self.repo.get_movements_by_item(item_id)
