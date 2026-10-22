import uuid
from html import escape

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

    async def generate_responsibility_statement(self, asset_id: uuid.UUID) -> str:
        asset = await self.get_asset(asset_id)
        
        emp_name = "Não atribuído (Em Estoque)"
        emp_reg = "N/A"
        emp_role = "N/A"
        emp_sector = "N/A"
        unit_name = "N/A"
        
        if asset.employee_id:
            from app.organization.models import Employee, Sector
            emp = await self.repo.session.get(Employee, asset.employee_id)
            if emp:
                emp_name = emp.name
                emp_reg = emp.registration_number
                emp_role = emp.position or "Colaborador"
                if emp.sector_id:
                    sector = await self.repo.session.get(Sector, emp.sector_id)
                    if sector:
                        emp_sector = sector.name
        
        if asset.unit_id:
            from app.organization.models import Unit
            unit = await self.repo.session.get(Unit, asset.unit_id)
            if unit:
                unit_name = unit.name

        category_name = asset.category.name if asset.category else "Equipamento de TI"
        e = escape  # todo valor interpolado no HTML do termo vem do banco/usuário
        specs_rows = "".join([
            f"<tr><td style='padding:6px 12px;font-weight:600;border:1px solid #cbd5e1;background:#f8fafc;width:35%;'>{e(str(k).upper())}</td><td style='padding:6px 12px;border:1px solid #cbd5e1;'>{e(str(v))}</td></tr>" 
            for k, v in (asset.technical_specs or {}).items()
        ])
        if not specs_rows:
            specs_rows = "<tr><td colspan='2' style='padding:8px 12px;border:1px solid #cbd5e1;color:#64748b;'>Sem especificações registradas</td></tr>"

        from datetime import datetime
        now_str = datetime.now().strftime("%d/%m/%Y às %H:%M")

        return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Termo de Responsabilidade - Patrimônio {e(asset.tag)}</title>
    <style>
        body {{
            font-family: Arial, Helvetica, sans-serif;
            color: #1e293b;
            margin: 40px;
            font-size: 13px;
            line-height: 1.5;
        }}
        .header {{
            text-align: center;
            border-bottom: 2px solid #0f172a;
            padding-bottom: 12px;
            margin-bottom: 24px;
        }}
        .header h1 {{
            font-size: 18px;
            text-transform: uppercase;
            margin: 0;
            letter-spacing: 0.5px;
        }}
        .header p {{
            margin: 4px 0 0;
            color: #64748b;
            font-size: 11px;
        }}
        .section-title {{
            font-size: 13px;
            font-weight: bold;
            text-transform: uppercase;
            color: #0f172a;
            background: #e2e8f0;
            padding: 6px 10px;
            margin-top: 18px;
            margin-bottom: 8px;
            border-left: 4px solid #2563eb;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 12px;
        }}
        .info-grid td {{
            padding: 6px 10px;
            border: 1px solid #cbd5e1;
        }}
        .label {{
            font-weight: bold;
            background-color: #f8fafc;
            width: 25%;
        }}
        .terms {{
            margin-top: 16px;
            text-align: justify;
            font-size: 12px;
        }}
        .terms ol {{
            padding-left: 20px;
            margin: 6px 0;
        }}
        .terms li {{
            margin-bottom: 6px;
        }}
        .signatures {{
            margin-top: 50px;
            display: flex;
            justify-content: space-between;
        }}
        .sig-block {{
            width: 45%;
            text-align: center;
        }}
        .sig-line {{
            border-top: 1px solid #334155;
            margin-bottom: 6px;
        }}
        .footer {{
            margin-top: 35px;
            text-align: center;
            font-size: 10px;
            color: #94a3b8;
            border-top: 1px solid #e2e8f0;
            padding-top: 8px;
        }}
        .no-print {{
            position: fixed;
            top: 20px;
            right: 20px;
            background: #2563eb;
            color: white;
            border: none;
            padding: 10px 18px;
            font-size: 14px;
            font-weight: bold;
            border-radius: 6px;
            cursor: pointer;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
        }}
        @media print {{
            .no-print {{
                display: none;
            }}
            body {{
                margin: 20px;
            }}
        }}
    </style>
</head>
<body>
    <button class="no-print" onclick="window.print()">🖨️ Imprimir / Salvar PDF</button>

    <div class="header">
        <h1>Termo de Responsabilidade e Cautela de Equipamento de TI</h1>
        <p>Departamento de Tecnologia da Informação — Gestão Patrimonial</p>
    </div>

    <div class="section-title">1. Dados do Colaborador (Responsável)</div>
    <table class="info-grid">
        <tr>
            <td class="label">Colaborador:</td>
            <td><strong>{e(emp_name)}</strong></td>
            <td class="label">Matrícula:</td>
            <td>{e(emp_reg)}</td>
        </tr>
        <tr>
            <td class="label">Cargo / Função:</td>
            <td>{e(emp_role)}</td>
            <td class="label">Setor / Departamento:</td>
            <td>{e(emp_sector)}</td>
        </tr>
        <tr>
            <td class="label">Unidade / Localidade:</td>
            <td colspan="3">{e(unit_name)}</td>
        </tr>
    </table>

    <div class="section-title">2. Identificação do Equipamento (Patrimônio)</div>
    <table class="info-grid">
        <tr>
            <td class="label">Número de Patrimônio:</td>
            <td><strong style="font-size:14px;color:#2563eb;">{e(asset.tag)}</strong></td>
            <td class="label">Categoria:</td>
            <td>{e(category_name)}</td>
        </tr>
        <tr>
            <td class="label">Equipamento / Modelo:</td>
            <td colspan="3">{e(asset.name)}</td>
        </tr>
    </table>

    <div class="section-title">3. Especificações Técnicas</div>
    <table>
        {specs_rows}
    </table>

    <div class="section-title">4. Declaração e Termos de Uso</div>
    <div class="terms">
        <ol>
            <li>O colaborador declara haver recebido nesta data o equipamento de TI acima especificado em perfeito estado de conservação, limpeza e pleno funcionamento.</li>
            <li>O equipamento destina-se <strong>exclusivamente</strong> ao desempenho das atividades profissionais relativas à sua função na empresa.</li>
            <li>O colaborador compromete-se a guardar e zelar pela conservação do equipamento, responsabilizando-se pelo seu uso adequado e pela observância da Política de Segurança da Informação.</li>
            <li>É terminantemente vedada a instalação de softwares não autorizados ou licenciados pela equipe de Tecnologia da Informação.</li>
            <li>Qualquer anomalia, quebra, dano, perda ou furto/roubo deve ser imediatamente comunicado à equipe de TI e às autoridades competentes (com respectivo Boletim de Ocorrência).</li>
            <li>Em caso de desligamento, transferência de setor ou solicitação da TI, o equipamento deverá ser devolvido imediatamente no mesmo estado em que foi entregue, ressalvado o desgaste natural.</li>
        </ol>
    </div>

    <div class="signatures">
        <div class="sig-block">
            <div class="sig-line"></div>
            <strong>{e(emp_name)}</strong><br>
            Colaborador Responsável<br>
            Data: ____ / ____ / ________
        </div>
        <div class="sig-block">
            <div class="sig-line"></div>
            <strong>Responsável de TI</strong><br>
            Departamento de Tecnologia<br>
            Data: ____ / ____ / ________
        </div>
    </div>

    <div class="footer">
        Documento gerado eletronicamente em {now_str} pela Plataforma de Gestão de TI • ID Ativo: {e(str(asset.id))}
    </div>
</body>
</html>"""

