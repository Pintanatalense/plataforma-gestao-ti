import uuid
from app.core.exceptions import NotFoundException, BusinessRuleException, ConflictException
from app.stock.repository import StockRepository
from app.stock.schemas import (
    StockCategoryCreate,
    StockCategoryUpdate,
    StockItemCreate,
    StockItemUpdate,
    StockMovementCreate,
)
from app.stock.models import StockCategory, StockItem, StockMovement


class StockService:
    def __init__(self, repo: StockRepository):
        self.repo = repo

    # --- Categories ---
    async def list_categories(self):
        return await self.repo.get_categories()

    async def get_category(self, category_id: uuid.UUID):
        cat = await self.repo.get_category(category_id)
        if not cat:
            raise NotFoundException("Categoria de Estoque", category_id)
        return cat

    async def create_category(self, schema: StockCategoryCreate):
        existing = await self.repo.get_category_by_name(schema.name)
        if existing:
            raise ConflictException(f"Já existe uma categoria de estoque com o nome '{schema.name}'.")

        category = StockCategory(
            name=schema.name,
            description=schema.description,
            spec_schema=schema.spec_schema,
        )
        return await self.repo.create_category(category)

    async def update_category(self, category_id: uuid.UUID, schema: StockCategoryUpdate):
        category = await self.get_category(category_id)

        if schema.name != category.name:
            existing = await self.repo.get_category_by_name(schema.name)
            if existing and existing.id != category_id:
                raise ConflictException(f"Já existe uma categoria de estoque com o nome '{schema.name}'.")

        category.name = schema.name
        category.description = schema.description
        category.spec_schema = schema.spec_schema

        return await self.repo.update_category(category)

    async def delete_category(self, category_id: uuid.UUID):
        category = await self.get_category(category_id)
        await self.repo.delete_category(category)

    # --- Items ---
    async def list_items(self, unit_id: uuid.UUID = None):
        return await self.repo.get_items(unit_id)

    async def get_item(self, item_id: uuid.UUID):
        item = await self.repo.get_item(item_id)
        if not item:
            raise NotFoundException("Item de Estoque", item_id)
        return item

    async def create_item(self, schema: StockItemCreate, author_id: uuid.UUID):
        if schema.category_id:
            cat = await self.repo.get_category(schema.category_id)
            if not cat:
                raise NotFoundException("Categoria de Estoque", schema.category_id)

        item = StockItem(
            name=schema.name,
            description=schema.description,
            unit_id=schema.unit_id,
            quantity=schema.initial_quantity,
            min_quantity=schema.min_quantity,
            category_id=schema.category_id,
            technical_specs=schema.technical_specs or {},
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
        if schema.category_id is not None:
            if schema.category_id:
                cat = await self.repo.get_category(schema.category_id)
                if not cat:
                    raise NotFoundException("Categoria de Estoque", schema.category_id)
            item.category_id = schema.category_id
        if schema.technical_specs is not None:
            item.technical_specs = schema.technical_specs
        
        return await self.repo.update_item(item)

    async def add_movement(self, schema: StockMovementCreate, author_id: uuid.UUID):
        item = await self.repo.get_item_for_update(schema.item_id)
        if not item:
            raise NotFoundException("Item de Estoque", schema.item_id)
        
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
        await self.repo.update_item(item)
        
        return mov

    async def list_movements(self, item_id: uuid.UUID):
        return await self.repo.get_movements_by_item(item_id)
