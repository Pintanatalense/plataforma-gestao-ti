"""
Modelos de atendimento (ADR-026, PR 4): listas reutilizáveis de subchamados.

O modelo só pré-preenche a tela. A abertura recebe a lista explícita e cada item passa pelas regras de sempre
(direcionamento por categoria, formulário, SLA): um item com setor fora do padrão da categoria é recusado na abertura
para quem não tem ``route_any_sector``, mesmo que o modelo o traga. Desativar um modelo não apaga nada; os chamados
abertos com ele guardam o ``template_id``.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.repository import AuditRepository
from app.core.exceptions import BusinessRuleException, ConflictException, NotFoundException
from app.organization.models import Sector
from app.service_desk.models import TicketCategory, TicketTemplate, TicketTemplateItem
from app.service_desk.schemas import TicketTemplateIn


class TicketTemplateService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, include_inactive: bool = False) -> list[TicketTemplate]:
        stmt = select(TicketTemplate).order_by(TicketTemplate.name)
        if not include_inactive:
            stmt = stmt.where(TicketTemplate.is_active.is_(True))
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, template_id: uuid.UUID, include_inactive: bool = False) -> TicketTemplate:
        template = await self.session.get(TicketTemplate, template_id)
        if template is None or (not template.is_active and not include_inactive):
            raise NotFoundException("Modelo de atendimento", template_id)
        return template

    async def ensure_usable(self, template_id: uuid.UUID) -> None:
        """Abertura com ``template_id``: o modelo precisa existir ativo."""
        template = await self.session.get(TicketTemplate, template_id)
        if template is None or not template.is_active:
            raise BusinessRuleException("Modelo de atendimento inválido ou inativo.")

    async def _check_items(self, data: TicketTemplateIn) -> None:
        for item in data.items:
            category = await self.session.get(TicketCategory, item.category_id)
            if category is None or not category.is_active:
                raise BusinessRuleException(f"Categoria inválida ou inativa no item '{item.title}'.")
            if item.responsible_sector_id is not None:
                sector = await self.session.get(Sector, item.responsible_sector_id)
                if sector is None or not sector.is_active or sector.deleted_at is not None:
                    raise BusinessRuleException(f"Setor inválido ou inativo no item '{item.title}'.")

    def _fill(self, template: TicketTemplate, data: TicketTemplateIn) -> None:
        template.name = data.name.strip()
        template.description = data.description
        template.is_active = data.is_active
        template.items = [
            TicketTemplateItem(
                category_id=item.category_id, responsible_sector_id=item.responsible_sector_id, title=item.title,
                description=item.description, default_custom_fields=item.default_custom_fields,
                is_required=item.is_required, sort=position,
            )
            for position, item in enumerate(data.items)
        ]

    async def _ensure_unique_name(self, name: str, own_id: uuid.UUID | None) -> None:
        stmt = select(TicketTemplate.id).where(func.lower(TicketTemplate.name) == name.strip().lower())
        if own_id is not None:
            stmt = stmt.where(TicketTemplate.id != own_id)
        if (await self.session.execute(stmt)).first() is not None:
            raise ConflictException("Já existe um modelo de atendimento com esse nome.")

    async def _audit(self, event: str, template: TicketTemplate, user_id: uuid.UUID) -> None:
        await AuditRepository(self.session).create(
            event, "ticket_template", template.id,
            {"name": template.name, "is_active": template.is_active, "items": len(template.items)},
            user_id=user_id,
        )

    async def create(self, data: TicketTemplateIn, user_id: uuid.UUID) -> TicketTemplate:
        await self._check_items(data)
        await self._ensure_unique_name(data.name, None)
        template = TicketTemplate()
        self._fill(template, data)
        self.session.add(template)
        await self.session.flush()
        await self._audit("ticket_template.created", template, user_id)
        return template

    async def update(self, template_id: uuid.UUID, data: TicketTemplateIn, user_id: uuid.UUID) -> TicketTemplate:
        template = await self.get(template_id, include_inactive=True)
        await self._check_items(data)
        await self._ensure_unique_name(data.name, template.id)
        self._fill(template, data)
        await self.session.flush()
        await self._audit("ticket_template.updated", template, user_id)
        return template

    async def deactivate(self, template_id: uuid.UUID, user_id: uuid.UUID) -> None:
        template = await self.get(template_id, include_inactive=True)
        template.is_active = False
        await self.session.flush()
        await self._audit("ticket_template.deactivated", template, user_id)
