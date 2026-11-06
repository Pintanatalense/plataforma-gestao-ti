"""
Seed de desenvolvimento para popular backend/dev.db com dados realistas
para teste do Módulo 1 (Ciclo de Vida de Ativos e Integração com Chamados).
"""

import asyncio
import os
import uuid

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///backend/dev.db"

from app.database import Base, engine, AsyncSessionLocal
from app.core.security import hash_password
import app.main

from app.organization.models import Company, Unit, Sector, Employee
from app.identity.models import UserAccount, Role, Permission
from app.assets.models import AssetCategory, Asset, AssetStatus
from app.movements.models import AssetMovement, MovementType
from app.stock.models import StockItem
from app.service_desk.models import Ticket, TicketCategory

async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        res = await session.execute(select(Company))
        if res.scalar_one_or_none():
            print("Database already contains data.")
            return

        print("Seeding database...")

        # 1. Empresa
        company = Company(
            id=uuid.uuid4(),
            name="Empresa Demonstração TI S.A.",
            cnpj="12.345.678/0001-90"
        )
        session.add(company)

        # 2. Unidade
        unit_sp = Unit(
            id=uuid.uuid4(),
            company_id=company.id,
            name="Matriz São Paulo",
            code="SP-01",
            type="MATRIZ"
        )
        unit_rn = Unit(
            id=uuid.uuid4(),
            company_id=company.id,
            name="Filial Natal",
            code="RN-01",
            type="FILIAL"
        )
        session.add_all([unit_sp, unit_rn])

        # 3. Setores
        sector_ti = Sector(id=uuid.uuid4(), unit_id=unit_sp.id, name="Tecnologia da Informação", code="TI")
        sector_rh = Sector(id=uuid.uuid4(), unit_id=unit_sp.id, name="Recursos Humanos", code="RH")
        sector_fin = Sector(id=uuid.uuid4(), unit_id=unit_sp.id, name="Financeiro", code="FIN")
        session.add_all([sector_ti, sector_rh, sector_fin])

        # 4. Colaboradores
        emp_admin = Employee(
            id=uuid.uuid4(),
            name="Eduardo Administrador",
            registration_number="ADM-001",
            position="Gerente de TI",
            unit_id=unit_sp.id,
            sector_id=sector_ti.id,
        )
        emp_tec = Employee(
            id=uuid.uuid4(),
            name="Carlos Técnico Suporte",
            registration_number="TEC-002",
            position="Analista de Suporte",
            unit_id=unit_sp.id,
            sector_id=sector_ti.id,
        )
        emp_solicitante = Employee(
            id=uuid.uuid4(),
            name="Ana Paula Silva",
            registration_number="RH-101",
            position="Coordenadora de RH",
            unit_id=unit_sp.id,
            sector_id=sector_rh.id,
        )
        session.add_all([emp_admin, emp_tec, emp_solicitante])

        # 5. Permissões e Perfis
        all_perms_codes = [
            "service_desk.tickets.manage",
            "service_desk.tickets.read_all",
            "service_desk.interactions.internal",
            "assets.create", "assets.update", "assets.read",
            "movements.create", "movements.read",
            "stock.read", "stock.write"
        ]
        perms_objects = []
        for pcode in all_perms_codes:
            perm = Permission(id=uuid.uuid4(), code=pcode, description=pcode)
            session.add(perm)
            perms_objects.append(perm)

        role_tec = Role(id=uuid.uuid4(), name="Técnico de TI", description="Operação de chamados e ativos")
        role_tec.permissions = perms_objects
        session.add(role_tec)

        # 6. Usuários (senha padrão: admin123)
        user_admin = UserAccount(
            id=uuid.uuid4(),
            email="admin@gestao.ti",
            hashed_password=hash_password("admin123"),
            employee_id=emp_admin.id,
            is_admin=True,
            is_active=True,
            must_change_password=False,
        )
        user_tec = UserAccount(
            id=uuid.uuid4(),
            email="tecnico@gestao.ti",
            hashed_password=hash_password("admin123"),
            employee_id=emp_tec.id,
            is_admin=False,
            is_active=True,
            must_change_password=False,
        )
        user_tec.roles = [role_tec]

        user_solicitante = UserAccount(
            id=uuid.uuid4(),
            email="solicitante@gestao.ti",
            hashed_password=hash_password("admin123"),
            employee_id=emp_solicitante.id,
            is_admin=False,
            is_active=True,
            must_change_password=False,
        )
        session.add_all([user_admin, user_tec, user_solicitante])

        # 7. Categorias de Ativos
        cat_note = AssetCategory(
            id=uuid.uuid4(),
            name="Notebooks Corporativos",
            description="Notebooks portáteis para colaboradores",
            spec_schema={"ram": "string", "storage": "string", "processador": "string"}
        )
        cat_desktop = AssetCategory(
            id=uuid.uuid4(),
            name="Desktops & Workstations",
            description="Computadores fixos de escritório",
            spec_schema={"ram": "string", "gpu": "string"}
        )
        cat_monitor = AssetCategory(
            id=uuid.uuid4(),
            name="Monitores",
            description="Telas e monitores auxiliares",
            spec_schema={"polegadas": "string", "resolucao": "string"}
        )
        session.add_all([cat_note, cat_desktop, cat_monitor])

        # 8. Equipamentos com Diferentes Status da Máquina de Estados
        asset_stock = Asset(
            id=uuid.uuid4(),
            tag="PAT-00101",
            name="Dell Latitude 5430 i7 16GB",
            category_id=cat_note.id,
            unit_id=unit_sp.id,
            status=AssetStatus.IN_STOCK.value,
            technical_specs={"ram": "16GB", "storage": "512GB NVMe", "processador": "Intel Core i7 12th"}
        )
        asset_inuse = Asset(
            id=uuid.uuid4(),
            tag="PAT-00102",
            name="Lenovo ThinkPad T14 AMD Ryzen 7",
            category_id=cat_note.id,
            unit_id=unit_sp.id,
            employee_id=emp_solicitante.id,
            status=AssetStatus.IN_USE.value,
            technical_specs={"ram": "32GB", "storage": "1TB SSD", "processador": "AMD Ryzen 7 PRO"}
        )
        asset_reserved = Asset(
            id=uuid.uuid4(),
            tag="PAT-00103",
            name="Dell UltraSharp 27 4K U2723QE",
            category_id=cat_monitor.id,
            unit_id=unit_sp.id,
            employee_id=emp_solicitante.id,
            status=AssetStatus.RESERVED.value,
            technical_specs={"polegadas": "27", "resolucao": "3840x2160 4K"}
        )
        asset_inspection = Asset(
            id=uuid.uuid4(),
            tag="PAT-00104",
            name="MacBook Pro M2 16GB",
            category_id=cat_note.id,
            unit_id=unit_sp.id,
            status=AssetStatus.PENDING_INSPECTION.value,
            technical_specs={"ram": "16GB", "storage": "512GB SSD", "processador": "Apple M2"}
        )
        session.add_all([asset_stock, asset_inuse, asset_reserved, asset_inspection])

        # 9. Movimentações iniciais
        mov_note = AssetMovement(
            id=uuid.uuid4(),
            asset_id=asset_inuse.id,
            movement_type=MovementType.ASSIGNMENT.value,
            status_from=AssetStatus.IN_STOCK.value,
            status_to=AssetStatus.IN_USE.value,
            to_employee_id=emp_solicitante.id,
            author_id=user_admin.id,
            notes="Entrega de equipamento para admissão no RH"
        )
        mov_inspect = AssetMovement(
            id=uuid.uuid4(),
            asset_id=asset_inspection.id,
            movement_type=MovementType.RETURN.value,
            status_from=AssetStatus.IN_USE.value,
            status_to=AssetStatus.PENDING_INSPECTION.value,
            author_id=user_tec.id,
            notes="Devolução física pós-desligamento. Equipamento em quarentena aguardando conferência técnica."
        )
        session.add_all([mov_note, mov_inspect])

        # 10. Insumos em Estoque
        stock_mouse = StockItem(
            id=uuid.uuid4(),
            name="Mouse Sem Fio Logitech M170",
            description="Mouse óptico wireless USB",
            unit_id=unit_sp.id,
            quantity=15,
            min_quantity=5
        )
        stock_teclado = StockItem(
            id=uuid.uuid4(),
            name="Teclado ABNT2 USB Dell KB216",
            description="Teclado padrão corporativo",
            unit_id=unit_sp.id,
            quantity=8,
            min_quantity=3
        )
        session.add_all([stock_mouse, stock_teclado])

        # 11. Categorias de Chamados com formulário
        cat_chamado_equip = TicketCategory(
            id=uuid.uuid4(),
            name="Entrega & Devolução de Equipamento",
            description="Solicitações de notebooks, monitores e periféricos para colaboradores",
            default_sector_id=sector_ti.id,
            is_active=True,
            form_schema=[
                {"id": "motivo", "label": "Motivo da Solicitação", "type": "select", "required": True, "options": ["Admissão de Colaborador", "Troca / Upgrade", "Equipamento Danificado", "Devolução por Desligamento"]},
                {"id": "modelo_preferencial", "label": "Modelo Solicitado", "type": "text", "required": False}
            ]
        )
        cat_chamado_suporte = TicketCategory(
            id=uuid.uuid4(),
            name="Falha de Hardware / Suporte Técnico",
            description="Relato de defeitos ou problemas físicos em computadores",
            default_sector_id=sector_ti.id,
            is_active=True
        )
        session.add_all([cat_chamado_equip, cat_chamado_suporte])

        # 12. Chamado demonstrativo com Ativos Vinculados
        ticket_demonstracao = Ticket(
            id=uuid.uuid4(),
            title="Admissão: Disponibilização de Notebook e Monitor para RH",
            description="Novo colaborador ingressando no time de RH na próxima segunda-feira. Necessita de notebook corporativo preparado e monitor secundário.",
            priority="HIGH",
            status="IN_PROGRESS",
            category_id=cat_chamado_equip.id,
            requester_id=emp_solicitante.id,
            created_by_user_id=user_solicitante.id,
            assignee_id=emp_tec.id,
            origin_unit_id=unit_sp.id,
            origin_sector_id=sector_rh.id,
            responsible_sector_id=sector_ti.id,
            custom_fields={"motivo": "Admissão de Colaborador", "modelo_preferencial": "Dell Latitude"}
        )
        ticket_demonstracao.assets = [asset_stock, asset_reserved]
        session.add(ticket_demonstracao)

        await session.commit()
        print("SEED COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(seed())
