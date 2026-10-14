"""
Script de seed para a Plataforma de Gestão de TI.
Cria a empresa padrão, permissões e o perfil de administrador.

O primeiro usuário administrador NÃO é criado aqui: ele é definido por quem
instala o sistema, na tela de configuração inicial (primeiro acesso).
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
import app.main  # Import all modules to avoid SQLAlchemy mapper errors
from app.identity.models import Permission, Role
from app.organization.models import Company, Unit


# Import all models to ensure SQLAlchemy registers them before creating relationships
import app.stock.models
import app.assets.models
import app.movements.models
import app.service_desk.models


async def seed() -> None:
    print("Iniciando seed...")
    async with AsyncSessionLocal() as session:
        # 1. Criar Empresa
        stmt = select(Company).where(Company.name == "Empresa Padrão")
        result = await session.execute(stmt)
        company = result.scalar_one_or_none()
        
        if not company:
            company = Company(name="Empresa Padrão", cnpj="00.000.000/0001-00")
            session.add(company)
            await session.flush()
            print(f"Empresa '{company.name}' criada.")
        else:
            print(f"Empresa '{company.name}' já existe.")

        # 2. Criar Unidade Matriz
        stmt = select(Unit).where(Unit.company_id == company.id, Unit.type == "MATRIZ")
        result = await session.execute(stmt)
        matriz = result.scalar_one_or_none()
        
        if not matriz:
            matriz = Unit(company_id=company.id, name="Matriz", code="MAT-01", type="MATRIZ")
            session.add(matriz)
            await session.flush()
            print(f"Unidade '{matriz.name}' criada.")

        # 3. Criar Permissões Iniciais
        permissions_data = [
            # Organization
            {"code": "organization.company.read", "description": "Ler dados da empresa"},
            {"code": "organization.company.create", "description": "Inicializar a empresa"},
            {"code": "organization.company.update", "description": "Editar dados da empresa"},
            {"code": "organization.units.read", "description": "Ler unidades"},
            {"code": "organization.units.create", "description": "Criar unidades"},
            {"code": "organization.units.update", "description": "Editar unidades"},
            {"code": "organization.sectors.read", "description": "Ler setores"},
            {"code": "organization.sectors.create", "description": "Criar setores"},
            {"code": "organization.sectors.update", "description": "Editar setores"},
            {"code": "organization.employees.read", "description": "Ler colaboradores"},
            {"code": "organization.employees.create", "description": "Criar colaboradores"},
            {"code": "organization.employees.update", "description": "Editar colaboradores"},
            
            # Identity
            {"code": "identity.users.read", "description": "Ler usuários"},
            {"code": "identity.users.create", "description": "Criar usuários"},
            {"code": "identity.users.update", "description": "Editar usuários"},
            {"code": "identity.roles.read", "description": "Ler perfis"},
            {"code": "identity.roles.create", "description": "Criar perfis"},
            {"code": "identity.roles.update", "description": "Editar perfis"},

            # Assets
            {"code": "assets.read", "description": "Ler patrimônio e ativos"},
            {"code": "assets.write", "description": "Criar/editar ativos e movimentações"},

            # Stock
            {"code": "stock.read", "description": "Ler estoque e insumos"},
            {"code": "stock.write", "description": "Criar/editar insumos e movimentações de estoque"},

            # Inventory
            {"code": "inventory.read", "description": "Ler inventários periódicos"},
            {"code": "inventory.write", "description": "Criar e conduzir inventários periódicos"},

            # Service Desk
            {"code": "service_desk.tickets.manage", "description": "Atender e gerenciar chamados (técnico)"},
            {"code": "service_desk.tickets.create", "description": "Abrir novos chamados de suporte"},
            {"code": "service_desk.tickets.read", "description": "Visualizar próprios chamados"},
            {"code": "service_desk.tickets.read_all", "description": "Visualizar todos os chamados da organização (Gestão)"},
            {"code": "service_desk.reports.read", "description": "Acessar relatórios e métricas de desempenho/SLA"},
            {"code": "service_desk.interactions.internal", "description": "Registrar e visualizar notas internas no chamado"},

            # Sistema, Dados e Backups
            {"code": "system.data.export", "description": "Exportar dados do sistema em formato CSV"},
            {"code": "system.data.import", "description": "Importar dados no sistema via CSV"},
            {"code": "system.backup.manage", "description": "Gerenciar e gerar backups do banco de dados"},
            {"code": "system.backup.download", "description": "Baixar arquivos de backup do banco de dados"},

            # Integrações
            {"code": "integrations.whatsapp.manage", "description": "Configurar e gerenciar bot do WhatsApp"},
        ]
        
        for p_data in permissions_data:
            stmt = select(Permission).where(Permission.code == p_data["code"])
            result = await session.execute(stmt)
            if not result.scalar_one_or_none():
                permission = Permission(**p_data)
                session.add(permission)
        await session.flush()
        print("Permissões sincronizadas.")

        # 4. Criar Admin Role (e mantê-lo com todas as permissões a cada execução)
        stmt_all_perms = select(Permission)
        all_perms = list((await session.execute(stmt_all_perms)).scalars().all())

        stmt = select(Role).options(selectinload(Role.permissions)).where(Role.name == "Administrador")
        result = await session.execute(stmt)
        admin_role = result.scalar_one_or_none()
        
        if not admin_role:
            admin_role = Role(name="Administrador", description="Acesso total ao sistema.")
            admin_role.permissions = all_perms
            session.add(admin_role)
            await session.flush()
            print(f"Perfil '{admin_role.name}' criado com {len(all_perms)} permissões.")
        else:
            admin_role.permissions = all_perms
            await session.flush()
            print(f"Perfil '{admin_role.name}' sincronizado com {len(all_perms)} permissões.")

        # Helper para sincronizar perfil
        async def sync_role(name: str, desc: str, perm_codes: list[str]) -> Role:
            stmt_p = select(Permission).where(Permission.code.in_(perm_codes))
            perms = list((await session.execute(stmt_p)).scalars().all())
            stmt_r = select(Role).options(selectinload(Role.permissions)).where(Role.name == name)
            role = (await session.execute(stmt_r)).scalar_one_or_none()
            if not role:
                role = Role(name=name, description=desc)
                role.permissions = perms
                session.add(role)
                await session.flush()
                print(f"Perfil '{role.name}' criado com {len(perms)} permissões.")
            else:
                role.description = desc
                role.permissions = perms
                await session.flush()
                print(f"Perfil '{role.name}' sincronizado com {len(perms)} permissões.")
            return role

        # 5. Perfis Operacionais: Gestão, Atendente e Solicitante
        gestao_codes = [
            "service_desk.tickets.read_all",
            "service_desk.tickets.read",
            "service_desk.tickets.create",
            "service_desk.reports.read",
            "service_desk.interactions.internal",
            "organization.company.read",
            "organization.units.read",
            "organization.sectors.read",
            "organization.employees.read",
            "assets.read",
            "stock.read",
            "inventory.read",
            "system.data.export",
        ]
        await sync_role(
            name="Gestão",
            desc="Visualização gerencial, relatórios, SLAs, indicadores e exportação de dados.",
            perm_codes=gestao_codes,
        )

        atendente_codes = [
            "service_desk.tickets.manage",
            "service_desk.tickets.read_all",
            "service_desk.tickets.read",
            "service_desk.tickets.create",
            "service_desk.interactions.internal",
            "assets.read",
            "stock.read",
        ]
        await sync_role(
            name="Atendente",
            desc="Atendimento operacional de chamados, encaminhamento, notas técnicas e consumo de estoque.",
            perm_codes=atendente_codes,
        )

        solicitante_codes = [
            "service_desk.tickets.create",
            "service_desk.tickets.read",
        ]
        await sync_role(
            name="Solicitante",
            desc="Perfil restrito para abertura e acompanhamento dos próprios chamados.",
            perm_codes=solicitante_codes,
        )

        # 6. Criar Categorias Iniciais de Estoque
        stock_categories_data = [
            {
                "name": "Periféricos & Acessórios",
                "description": "Mouses, teclados, fones, webcams e adaptadores USB.",
                "spec_schema": {
                    "tipo": {"label": "Tipo de Periférico", "required": True},
                    "marca": {"label": "Marca / Fabricante", "required": False},
                    "conexao": {"label": "Tipo de Conexão (USB-A, USB-C, Wireless, Bluetooth)", "required": False},
                    "cor": {"label": "Cor / Acabamento", "required": False},
                },
            },
            {
                "name": "Cabos & Conectores",
                "description": "Cabos de rede, vídeo, força e conversores.",
                "spec_schema": {
                    "tipo_cabo": {"label": "Tipo de Cabo (HDMI, DisplayPort, RJ45, USB-C)", "required": True},
                    "comprimento": {"label": "Comprimento (metros)", "required": False},
                    "blindagem": {"label": "Blindagem / Padrão (ex: Cat6, 4K 60Hz)", "required": False},
                },
            },
            {
                "name": "Toners & Suprimentos",
                "description": "Cartuchos de toner, tintas e cilindros fotocondutores.",
                "spec_schema": {
                    "modelo": {"label": "Modelo do Toner/Cartucho", "required": True},
                    "compatibilidade": {"label": "Impressoras Compatíveis", "required": True},
                    "cor": {"label": "Cor da Tinta/Toner (Preto, Ciano, Magenta, Amarelo)", "required": False},
                    "rendimento": {"label": "Rendimento Estimado (páginas)", "required": False},
                },
            },
            {
                "name": "Componentes & Peças",
                "description": "Memórias RAM, unidades SSD/HD, coolers e fontes de alimentação.",
                "spec_schema": {
                    "tipo_peca": {"label": "Tipo de Componente (RAM, SSD, Fonte, etc.)", "required": True},
                    "capacidade": {"label": "Capacidade / Frequência", "required": False},
                    "interface": {"label": "Interface / Fator de Forma (ex: NVMe M.2, DDR4, SATA)", "required": False},
                    "marca": {"label": "Marca / Fabricante", "required": False},
                },
            },
        ]

        from app.stock.models import StockCategory
        for sc_data in stock_categories_data:
            stmt = select(StockCategory).where(StockCategory.name == sc_data["name"])
            res = await session.execute(stmt)
            if not res.scalar_one_or_none():
                cat = StockCategory(**sc_data)
                session.add(cat)
        await session.flush()
        print("Categorias de estoque sincronizadas.")

        # 7. Usuário administrador: criado no primeiro acesso (tela de setup).
        print("Primeiro administrador: acesse o sistema para concluir a configuração inicial.")

        await session.commit()
        print("Seed finalizado com sucesso!")


if __name__ == "__main__":
    asyncio.run(seed())
