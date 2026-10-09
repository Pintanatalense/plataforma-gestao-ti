"""
MOD-04 — Service Desk (Services)

Implementa as regras de negócio de visualização e transição de chamados.
"""

import uuid
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BusinessRuleException,
    ForbiddenException,
    NotFoundException,
    StateTransitionException,
)
from app.service_desk.models import Ticket, TicketCategory, TicketInteraction, TicketMaterial
from app.service_desk.repository import ServiceDeskRepository
from app.service_desk.schemas import (
    TicketCreate,
    TicketInteractionCreate,
    TicketUpdate,
    TicketCategoryCreate,
    TicketCategoryUpdate,
    TicketMaterialCreate,
)


class ServiceDeskService:
    def __init__(self, session: AsyncSession, stock_service=None) -> None:
        self.repo = ServiceDeskRepository(session)
        self.stock_service = stock_service

    # ==========================================================================
    # Categories
    # ==========================================================================
    
    async def list_categories(self) -> Sequence[TicketCategory]:
        return await self.repo.list_categories()

    async def create_category(self, schema: TicketCategoryCreate) -> TicketCategory:
        cat = TicketCategory(
            name=schema.name,
            description=schema.description,
            is_active=schema.is_active,
            default_sector_id=schema.default_sector_id
        )
        return await self.repo.create_category(cat)

    async def update_category(self, category_id: uuid.UUID, schema: TicketCategoryUpdate) -> TicketCategory:
        cat = await self.repo.get_category(category_id)
        if not cat:
            raise NotFoundException("TicketCategory", category_id)

        if schema.name is not None:
            cat.name = schema.name
        if schema.description is not None:
            cat.description = schema.description
        if schema.is_active is not None:
            cat.is_active = schema.is_active
        if schema.default_sector_id is not None:
            cat.default_sector_id = schema.default_sector_id

        return await self.repo.update_category(cat)

    # ==========================================================================
    # Tickets
    # ==========================================================================

    async def get_ticket_for_user(
        self, ticket_id: uuid.UUID, user_employee_id: uuid.UUID | None, is_technician: bool
    ) -> Ticket:
        """
        Busca um ticket e garante as regras de visualização:
        - Técnicos (is_technician=True) veem tudo.
        - Colaboradores (is_technician=False) só veem seus próprios chamados.
        """
        ticket = await self.repo.get_ticket(ticket_id)
        if not ticket:
            raise NotFoundException("Chamado", ticket_id)

        if not is_technician:
            if not user_employee_id or ticket.requester_id != user_employee_id:
                raise ForbiddenException("Você não tem acesso a este chamado.")

        return ticket

    async def list_tickets_for_user(
        self, user_employee_id: uuid.UUID | None, is_technician: bool
    ) -> Sequence[Ticket]:
        if is_technician:
            return await self.repo.list_tickets()
        else:
            if not user_employee_id:
                return []
            return await self.repo.list_tickets(requester_id=user_employee_id)

    async def create_ticket(
        self, 
        schema: TicketCreate, 
        requester_id: uuid.UUID,
        origin_unit_id: uuid.UUID,
        origin_sector_id: uuid.UUID
    ) -> Ticket:
        responsible_sector_id = schema.responsible_sector_id
        
        if schema.category_id:
            cat = await self.repo.get_category(schema.category_id)
            if not cat or not cat.is_active:
                raise BusinessRuleException("Categoria inválida ou inativa.")
            if not responsible_sector_id:
                responsible_sector_id = cat.default_sector_id
        
        if not responsible_sector_id:
            raise BusinessRuleException("Setor responsável não definido. Informe-o manualmente ou selecione uma categoria com roteamento automático.")

        ticket = Ticket(
            title=schema.title,
            description=schema.description,
            priority=schema.priority,
            category_id=schema.category_id,
            requester_id=requester_id,
            origin_unit_id=origin_unit_id,
            origin_sector_id=origin_sector_id,
            responsible_sector_id=responsible_sector_id,
            status="OPENED"
        )
        
        if schema.asset_ids:
            assets = await self.repo.get_assets_by_ids(schema.asset_ids)
            ticket.assets = list(assets)
            
        ticket = await self.repo.create_ticket(ticket)
        return await self.repo.get_ticket(ticket.id)

    async def update_ticket(
        self, ticket_id: uuid.UUID, schema: TicketUpdate, is_technician: bool
    ) -> Ticket:
        # Apenas técnicos alteram status/prioridade/responsável (em teoria)
        if not is_technician:
            raise ForbiddenException("Apenas técnicos podem gerenciar chamados.")

        ticket = await self.repo.get_ticket(ticket_id)
        if not ticket:
            raise NotFoundException("Chamado", ticket_id)

        if schema.category_id is not None:
            cat = await self.repo.get_category(schema.category_id)
            if not cat or not cat.is_active:
                raise BusinessRuleException("Categoria inválida ou inativa.")
            ticket.category_id = schema.category_id

        if schema.assignee_id is not None:
            # TODO: Ideal seria checar via IdentityService se assignee_id é um técnico válido
            ticket.assignee_id = schema.assignee_id

        if schema.priority is not None:
            ticket.priority = schema.priority

        if schema.status is not None:
            # Regras de máquina de estados simples:
            if ticket.status == "CLOSED" and schema.status != "CLOSED":
                raise StateTransitionException("Chamado", ticket.status, schema.status)
            ticket.status = schema.status

        if schema.asset_ids is not None:
            assets = await self.repo.get_assets_by_ids(schema.asset_ids)
            ticket.assets = list(assets)

        return await self.repo.update_ticket(ticket)

    # ==========================================================================
    # Interactions (Comentários)
    # ==========================================================================

    async def add_interaction(
        self, 
        ticket_id: uuid.UUID, 
        schema: TicketInteractionCreate, 
        author_id: uuid.UUID,
        user_employee_id: uuid.UUID | None,
        is_technician: bool
    ) -> TicketInteraction:
        
        # O get_ticket_for_user já valida a permissão de visualização do ticket
        ticket = await self.get_ticket_for_user(ticket_id, user_employee_id, is_technician)

        if ticket.status == "CLOSED":
            raise BusinessRuleException("Não é possível adicionar interações a um chamado fechado.")

        if schema.is_internal and not is_technician:
            raise ForbiddenException("Apenas técnicos podem criar notas internas.")

        interaction = TicketInteraction(
            ticket_id=ticket.id,
            author_id=author_id,
            message=schema.message,
            is_internal=schema.is_internal
        )
        return await self.repo.create_interaction(interaction)

    # ==========================================================================
    # Materials (Consumo de Estoque)
    # ==========================================================================

    async def add_material_to_ticket(
        self,
        ticket_id: uuid.UUID,
        schema: TicketMaterialCreate,
        author_id: uuid.UUID,
        user_employee_id: uuid.UUID | None,
        is_technician: bool
    ) -> TicketMaterial:
        
        # Apenas técnicos podem adicionar materiais do estoque a um chamado
        if not is_technician:
            raise ForbiddenException("Apenas técnicos podem gerenciar materiais e estoque.")

        ticket = await self.get_ticket_for_user(ticket_id, user_employee_id, is_technician)

        if ticket.status == "CLOSED":
            raise BusinessRuleException("Não é possível adicionar materiais a um chamado fechado.")

        if not self.stock_service:
            raise BusinessRuleException("Serviço de estoque não está disponível no contexto.")

        # Deduzir do estoque (lança HTTPException caso falhe)
        from app.stock.schemas import StockMovementCreate
        mov_schema = StockMovementCreate(
            item_id=schema.stock_item_id,
            movement_type="OUT",
            quantity=schema.quantity,
            notes=f"Consumo via chamado {ticket.id}"
        )
        await self.stock_service.add_movement(mov_schema, author_id)

        # Adicionar o registro no ticket
        material = TicketMaterial(
            ticket_id=ticket.id,
            stock_item_id=schema.stock_item_id,
            quantity=schema.quantity,
            author_id=author_id
        )
        
        return await self.repo.create_material(material)
