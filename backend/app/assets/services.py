import uuid

from app.assets.models import Asset, AssetCategory, AssetStatus
from app.assets.repository import AssetRepository
from app.assets.schemas import AssetCategoryCreate, AssetCategoryUpdate, AssetCreate, AssetUpdate
from app.assets.statement_template import DEFAULT_TEMPLATE, StatementData, render_document, validate_template
from app.core.exceptions import (
    BusinessRuleException,
    NotFoundException,
    ValidationException,
)
from app.movements.models import AssetMovement, MovementType
from app.movements.repository import AssetMovementRepository


STATEMENT_TEMPLATE_KEY = "asset_statement_template"


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

    async def delete_category(self, category_id: uuid.UUID) -> None:
        category = await self.get_category(category_id)
        category.is_active = False
        await self.repo.update_category(category)

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
        if status_val in (AssetStatus.IN_STOCK.value, AssetStatus.PENDING_INSPECTION.value, AssetStatus.DECOMMISSIONED.value) and asset_data.get("employee_id"):
            raise ValidationException(f"Ativo com status {status_val} não pode possuir colaborador atribuído.")
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
        if new_status in (AssetStatus.IN_STOCK.value, AssetStatus.PENDING_INSPECTION.value, AssetStatus.DECOMMISSIONED.value) and target_employee is not None:
            raise ValidationException(f"Ativo com status {new_status} não pode possuir colaborador atribuído.")

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

            if asset.status == AssetStatus.RESERVED.value:
                movement_type = MovementType.RESERVATION.value
            elif asset.status == AssetStatus.MAINTENANCE.value:
                movement_type = MovementType.MAINTENANCE.value
            elif asset.status == AssetStatus.DECOMMISSIONED.value:
                movement_type = MovementType.DECOMMISSION.value
            elif asset.status == AssetStatus.IN_STOCK.value and status_from == AssetStatus.PENDING_INSPECTION.value:
                movement_type = MovementType.INSPECTION_RELEASE.value

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

    # --- Termo de Responsabilidade (modelo editável, ver statement_template.py) ---

    async def get_statement_template(self) -> tuple[str, bool]:
        """Texto do modelo em uso e se é o padrão do sistema (nenhum modelo próprio salvo)."""
        from app.core.settings_model import SystemSetting

        row = await self.repo.session.get(SystemSetting, STATEMENT_TEMPLATE_KEY)
        if row and row.value and row.value.strip():
            return row.value, False
        return DEFAULT_TEMPLATE, True

    async def save_statement_template(self, template: str) -> str:
        from app.core.settings_model import SystemSetting

        try:
            text = validate_template(template)
        except ValueError as err:
            raise ValidationException(str(err)) from err
        row = await self.repo.session.get(SystemSetting, STATEMENT_TEMPLATE_KEY)
        if row:
            row.value = text
        else:
            self.repo.session.add(SystemSetting(key=STATEMENT_TEMPLATE_KEY, value=text))
        await self.repo.session.commit()
        return text

    async def reset_statement_template(self) -> None:
        from app.core.settings_model import SystemSetting

        row = await self.repo.session.get(SystemSetting, STATEMENT_TEMPLATE_KEY)
        if row:
            await self.repo.session.delete(row)
            await self.repo.session.commit()

    async def _company_name(self) -> str:
        from app.organization.repository import OrganizationRepository

        company = await OrganizationRepository(self.repo.session).get_company()
        return company.name if company else ""

    @staticmethod
    def _now_text() -> str:
        from datetime import datetime

        return datetime.now().strftime("%d/%m/%Y às %H:%M")

    async def render_statement_preview(self, template: str) -> str:
        """Mostra o modelo com dados de exemplo (sem tocar em nenhum ativo real)."""
        try:
            text = validate_template(template)
        except ValueError as err:
            raise ValidationException(str(err)) from err
        data = StatementData(
            colaborador="Maria da Silva", matricula="12345", cargo="Analista Administrativo", setor="Financeiro",
            unidade="Matriz", patrimonio="PAT-0001", categoria="Notebook", equipamento="Dell Latitude 5420",
            empresa=await self._company_name(), data=self._now_text(), asset_id="00000000-0000-0000-0000-000000000000",
            specs={"processador": "Core i7", "memoria_ram": "16 GB", "armazenamento": "512 GB SSD"},
        )
        return render_document(text, data)

    async def generate_responsibility_statement(self, asset_id: uuid.UUID) -> str:
        asset = await self.get_asset(asset_id)
        data = StatementData(
            patrimonio=asset.tag,
            equipamento=asset.name,
            categoria=asset.category.name if asset.category else "Equipamento de TI",
            specs=asset.technical_specs or {},
            empresa=await self._company_name(),
            data=self._now_text(),
            asset_id=str(asset.id),
        )

        if asset.employee_id:
            from app.organization.models import Employee, Sector

            emp = await self.repo.session.get(Employee, asset.employee_id)
            if emp:
                data.colaborador = emp.name
                data.matricula = emp.registration_number
                data.cargo = emp.position or "Colaborador"
                if emp.sector_id:
                    sector = await self.repo.session.get(Sector, emp.sector_id)
                    if sector:
                        data.setor = sector.name

        if asset.unit_id:
            from app.organization.models import Unit

            unit = await self.repo.session.get(Unit, asset.unit_id)
            if unit:
                data.unidade = unit.name

        template, _ = await self.get_statement_template()
        return render_document(template, data)
