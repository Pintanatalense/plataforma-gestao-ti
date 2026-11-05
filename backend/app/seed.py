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
from app.identity.permission_catalog import sync_permission_catalog
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
        # Single tenant: se já existe uma empresa (mesmo renomeada no setup), não cria outra.
        stmt = select(Company).order_by(Company.created_at).limit(1)
        company = (await session.execute(stmt)).scalars().first()
        
        if not company:
            company = Company(name="Empresa Padrão", cnpj="00.000.000/0001-00")
            session.add(company)
            await session.flush()
            print(f"Empresa '{company.name}' criada.")
        else:
            print(f"Empresa '{company.name}' já existe.")

        # 2. Criar Unidade Matriz
        stmt = select(Unit).where(Unit.code == "MAT-01")
        result = await session.execute(stmt)
        matriz = result.scalar_one_or_none()
        
        if not matriz:
            matriz = Unit(company_id=company.id, name="Matriz", code="MAT-01", type="MATRIZ")
            session.add(matriz)
            await session.flush()
            print(f"Unidade '{matriz.name}' criada.")

        # 3. Permissões: catálogo único (app/identity/permission_catalog.py). Também tira críticas de perfis.
        await sync_permission_catalog(session)
        print("Permissões sincronizadas com o catálogo.")

        # 4. Perfil Administrador: todas as permissões comuns. Críticas nunca vão em perfil (S5): só por concessão
        # individual (assistente de instalação, tela de usuários ou `python -m app.cli grant-critical`).
        stmt_all_perms = select(Permission).where(Permission.is_critical.is_(False))
        all_perms = list((await session.execute(stmt_all_perms)).scalars().all())

        stmt = select(Role).options(selectinload(Role.permissions)).where(Role.name == "Administrador")
        result = await session.execute(stmt)
        admin_role = result.scalar_one_or_none()
        
        if not admin_role:
            admin_role = Role(name="Administrador", description="Acesso total ao sistema e funções de infraestrutura/backups.")
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
            stmt_p = select(Permission).where(Permission.code.in_(perm_codes), Permission.is_critical.is_(False))
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
                # Perfis existentes não são sobrescritos: personalizações feitas na tela de perfis
                # sobrevivem a reinícios. Permissões novas devem ser concedidas por migration ou pela UI.
                print(f"Perfil '{role.name}' já existe; permissões preservadas.")
            return role

        # 5. Hierarquia Acumulativa de Menor Privilégio:
        # Tier 1 - Solicitante: abre chamado e vê seus itens (notebook, celular)
        solicitante_codes = [
            "service_desk.tickets.create",
            "service_desk.tickets.read",
            "assets.read_own",
        ]
        await sync_role(
            name="Solicitante",
            desc="Abre chamados, acompanha suas solicitações e consulta seus equipamentos vinculados.",
            perm_codes=solicitante_codes,
        )

        # Tier 2 - Atendente: Solicitante + atendimento de chamados do seu setor/unidade
        atendente_codes = solicitante_codes + [
            "service_desk.tickets.manage",
        "service_desk.categories.manage",
            "service_desk.interactions.internal",
            "assets.read",
            "stock.read",
        ]
        await sync_role(
            name="Atendente",
            desc="Atendimento e triagem de chamados do seu setor/unidade, notas técnicas internas e consulta a estoque/ativos.",
            perm_codes=atendente_codes,
        )

        # Tier 3 - Gestão / Gestor: Atendente + relatórios de chamados, inventário periódico e auditoria
        gestao_codes = atendente_codes + [
            "service_desk.tickets.read_all",
            "service_desk.reports.read",
            "inventory.read",
            "inventory.write",
            "audit.read",
            "organization.company.read",
            "organization.units.read",
            "organization.sectors.read",
            "organization.employees.read",
            "system.data.export",
        ]
        await sync_role(
            name="Gestão",
            desc="Visão gerencial ampla de chamados, relatórios e SLAs, inventários periódicos e trilha de auditoria.",
            perm_codes=gestao_codes,
        )

        # Tier 4 - Admin: Gestão + cadastro de inventário e ativos completo + usuários e estoque
        admin_local_codes = gestao_codes + [
            "assets.write",
        "assets.categories.manage",
        "assets.movements.write",
        "assets.import",
            "stock.write",
            "organization.company.update",
            "organization.units.create",
            "organization.units.update",
            "organization.sectors.create",
            "organization.sectors.update",
            "organization.employees.create",
            "organization.employees.update",
            "identity.users.read",
            "identity.users.create",
            "identity.users.update",
            "identity.roles.read",
            "identity.roles.create",
            "identity.roles.update",
            "service_desk.sla.manage",
        ]
        await sync_role(
            name="Admin",
            desc="Administração operacional com gestão completa de ativos, patrimônio, estoque, organização e usuários.",
            perm_codes=admin_local_codes,
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

        # 7. Criar Templates Padrão do WhatsApp
        from app.whatsapp.models import WhatsAppTemplate
        whatsapp_templates_data = [
            {
                "code": "TICKET_OPENED",
                "name": "Abertura de Chamado Confirmada",
                "category": "SERVICE_DESK",
                "content": "👋 Olá, {{solicitante}}! Seu chamado *#{{protocolo}}* (_{{titulo}}_) foi aberto com sucesso na TI *{{empresa}}*.\nNossa equipe já foi notificada e iniciará o atendimento em breve.\n\nPara acompanhar, responda [2] no menu.",
                "is_active": True,
            },
            {
                "code": "TICKET_IN_PROGRESS",
                "name": "Chamado em Atendimento",
                "category": "SERVICE_DESK",
                "content": "🛠️ Olá, {{solicitante}}! O seu chamado *#{{protocolo}}* está agora *Em Atendimento* com o técnico *{{atendente}}*.\nEm caso de dúvidas, você pode responder diretamente por este canal.",
                "is_active": True,
            },
            {
                "code": "AWAITING_USER",
                "name": "Aguardando Informações do Solicitante",
                "category": "SERVICE_DESK",
                "content": "❓ Olá, {{solicitante}}! Precisamos de informações adicionais para dar continuidade ao seu chamado *#{{protocolo}}*:\n\n_{{observacao}}_\n\nPor favor, responda esta mensagem informando o que foi solicitado.",
                "is_active": True,
            },
            {
                "code": "REMOTE_ACCESS",
                "name": "Acesso Remoto Solicitado",
                "category": "SERVICE_DESK",
                "content": "💻 Olá, {{solicitante}}! Para solucionar seu chamado *#{{protocolo}}*, o técnico *{{atendente}}* precisa realizar um acesso remoto.\nPor favor, abra o software de suporte (AnyDesk ou TeamViewer) e nos envie o código de conexão aqui pelo WhatsApp.",
                "is_active": True,
            },
            {
                "code": "ASSET_READY",
                "name": "Equipamento Pronto para Retirada",
                "category": "ATENDIMENTO",
                "content": "📦 Olá, {{solicitante}}! Seu equipamento referente ao chamado *#{{protocolo}}* foi configurado com sucesso e já está disponível para retirada na sala da TI da unidade *{{unidade}}*.",
                "is_active": True,
            },
            {
                "code": "TICKET_RESOLVED",
                "name": "Chamado Concluído / Resolvido",
                "category": "SERVICE_DESK",
                "content": "✅ Olá, {{solicitante}}! Seu chamado *#{{protocolo}}* (_{{titulo}}_) foi resolvido pelo técnico *{{atendente}}*.\n\n*Solução aplicada:*\n_{{observacao}}_\n\nSe ainda precisar de suporte sobre este caso, basta responder aqui em até 48 horas.",
                "is_active": True,
            },
            {
                "code": "MAINTENANCE_ALERT",
                "name": "Aviso de Manutenção de Infraestrutura",
                "category": "MANUTENCAO",
                "content": "⚠️ *Aviso de Manutenção Programada de TI*\nInformamos que realizaremos uma intervenção preventiva na infraestrutura da unidade *{{unidade}}*.\nHorário: {{hora}} de {{data}}.\nPoderá haver instabilidade temporária. Agradecemos a compreensão de todos.",
                "is_active": True,
            },
        ]

        for wt_data in whatsapp_templates_data:
            stmt_wt = select(WhatsAppTemplate).where(WhatsAppTemplate.code == wt_data["code"])
            res_wt = await session.execute(stmt_wt)
            if not res_wt.scalar_one_or_none():
                tpl = WhatsAppTemplate(**wt_data)
                session.add(tpl)
        await session.flush()
        print("Templates de WhatsApp sincronizados.")

        # 7b. Regras de notificação e agenda do worker (criadas só se ausentes; edições são preservadas).
        from app.notifications.jobs import ensure_default_jobs
        from app.notifications.rules_seed import seed_notification_rules

        rules_created = await seed_notification_rules(session)
        jobs_created = await ensure_default_jobs(session)
        print(f"Notificações: {rules_created} regra(s) e {jobs_created} job(s) criados.")

        # 8. Usuário administrador: criado no primeiro acesso (tela de setup).
        print("Primeiro administrador: acesse o sistema para concluir a configuração inicial.")


        await session.commit()
        print("Seed finalizado com sucesso!")


if __name__ == "__main__":
    asyncio.run(seed())
