"""
Script de ambientação e carga de dados de demonstração (seed_demo).

Cria um ambiente corporativo modelo completo, profissional e personalizável:
- 1 Empresa ("TechCorp Soluções Empresariais Ltda.")
- 2 Unidades (Matriz SP e Filial Campinas)
- 8 Setores (Matriz: Financeiro, Comercial, Diretoria, RH | Filial: Administrativo, Operacional, Manutenção, TI)
- 8 Colaboradores e 8 Usuários (1 por setor) + 1 Administrador Global
- 16 Categorias de Chamados (2 por setor, com formulários dinâmicos de triagem)
- 10 Ativos patrimoniais categorizados (computadores, celulares, impressoras)
- 10 Categorias de Insumos com itens de estoque cadastrados e saldo inicial
- Movimentações de implantação patrimonial e estoque inicial
- Chamados de exemplo ilustrativos para visualização imediata no Kanban

Pode ser executado com flag --reset para limpar dados de teste anteriores com segurança.
"""

import argparse
import asyncio
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.assets.models import Asset, AssetCategory, AssetStatus
from app.attachments.models import Attachment
from app.core.security import hash_password
from app.database import AsyncSessionLocal
from app.identity.models import Permission, Role, UserAccount, user_role_association
from app.identity.permission_catalog import sync_permission_catalog
from app.inventory_audit.models import InventoryAudit, InventoryAuditItem
from app.movements.models import AssetMovement, MovementType
from app.notifications.models import Notification
from app.organization.models import Company, Employee, Sector, Unit
from app.service_desk.models import Ticket, TicketCategory, TicketInteraction, TicketMaterial, ticket_assets
from app.stock.models import StockCategory, StockItem, StockMovement
from app.whatsapp.models import WhatsAppTemplate


DEMO_PASSWORD = "Demo@2026"


WHATSAPP_TEMPLATES = [
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


async def clean_database(session: AsyncSession) -> None:
    """Limpa tabelas de negócio e transações de teste, mantendo estrutura do sistema."""
    print("--> Limpando dados de teste e tabelas transacionais...")

    # 1. Hub de notificações: entregas, eventos e conversas de teste
    from app.notifications.models import ConversationSession, Delivery, DeliveryAttempt, DomainEvent, InboundMessage

    for model in (DeliveryAttempt, Delivery, DomainEvent, InboundMessage, ConversationSession):
        await session.execute(delete(model))

    # 2. Notificações. A auditoria NÃO é apagada: é só de inserção e sai apenas pela retenção (ADR-023)
    await session.execute(delete(Notification))

    # 3. Anexos
    await session.execute(delete(Attachment))

    # 4. Auditorias de inventário
    await session.execute(delete(InventoryAuditItem))
    await session.execute(delete(InventoryAudit))

    # 5. Service desk (chamados, interações, materiais, ativos vinculados)
    await session.execute(delete(ticket_assets))
    await session.execute(delete(TicketInteraction))
    await session.execute(delete(TicketMaterial))
    await session.execute(delete(Ticket))
    await session.execute(delete(TicketCategory))

    # 6. Movimentações e ativos
    await session.execute(delete(AssetMovement))
    await session.execute(delete(Asset))
    await session.execute(delete(AssetCategory))

    # 7. Estoque e insumos
    await session.execute(delete(StockMovement))
    await session.execute(delete(StockItem))
    await session.execute(delete(StockCategory))

    # 8. Usuários e colaboradores
    await session.execute(delete(user_role_association))
    await session.execute(delete(UserAccount))
    await session.execute(delete(Employee))

    # 9. Setores, unidades e empresas
    await session.execute(delete(Sector))
    await session.execute(delete(Unit))
    await session.execute(delete(Company))

    await session.flush()
    print("--> Banco de dados limpo com sucesso!")


async def sync_roles_and_permissions(session: AsyncSession) -> dict[str, Role]:
    """Garante a existência de todas as permissões e perfis do sistema."""
    # Catálogo único; críticas nunca entram em perfil, nem no Administrador da demonstração/QA (S5).
    await sync_permission_catalog(session)

    stmt_all = select(Permission).where(Permission.is_critical.is_(False))
    all_perms = list((await session.execute(stmt_all)).scalars().all())

    async def _sync_role(name: str, desc: str, perm_codes: list[str] | None = None) -> Role:
        if perm_codes is None:
            perms = all_perms
        else:
            stmt_p = select(Permission).where(Permission.code.in_(perm_codes), Permission.is_critical.is_(False))
            perms = list((await session.execute(stmt_p)).scalars().all())

        stmt_r = select(Role).options(selectinload(Role.permissions)).where(Role.name == name)
        role = (await session.execute(stmt_r)).scalar_one_or_none()
        if not role:
            role = Role(name=name, description=desc)
            role.permissions = perms
            session.add(role)
        else:
            role.description = desc
            role.permissions = perms
        await session.flush()
        return role

    # Hierarquia Acumulativa de Menor Privilégio:
    # 1. Solicitante: abre chamado e vê seus itens (notebook, celular)
    solicitante_codes = [
        "service_desk.tickets.create",
        "service_desk.tickets.read",
        "assets.read_own",
    ]
    solicitante_role = await _sync_role(
        "Solicitante",
        "Abre chamados, acompanha suas solicitações e consulta seus equipamentos vinculados.",
        solicitante_codes,
    )

    # 2. Atendente: Solicitante + atendimento de chamados do seu setor/unidade
    atendente_codes = solicitante_codes + [
        "service_desk.tickets.manage",
    "service_desk.categories.manage",
        "service_desk.interactions.internal",
        "assets.read",
        "stock.read",
    ]
    atendente_role = await _sync_role(
        "Atendente",
        "Atendimento e triagem de chamados do seu setor/unidade, notas técnicas internas e consulta a estoque/ativos.",
        atendente_codes,
    )

    # 3. Gestão / Gestor: Atendente + relatórios de chamados, inventário periódico e auditoria
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
    gestao_role = await _sync_role(
        "Gestão",
        "Visão gerencial ampla de chamados, relatórios e SLAs, inventários periódicos e trilha de auditoria.",
        gestao_codes,
    )

    # 4. Admin: Gestão + cadastro de inventário e ativos completo + usuários e estoque
    admin_codes = gestao_codes + [
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
    ]
    admin_role = await _sync_role(
        "Admin",
        "Administração operacional com gestão completa de ativos, patrimônio, estoque, organização e usuários.",
        admin_codes,
    )

    # 5. Administrador Global: instalador com todas as opções, backups e integrações
    global_admin_role = await _sync_role(
        "Administrador",
        "Acesso total irrestrito ao sistema e funções de infraestrutura, backups e mensageria.",
        None,
    )

    for wt_data in WHATSAPP_TEMPLATES:
        stmt_wt = select(WhatsAppTemplate).where(WhatsAppTemplate.code == wt_data["code"])
        res_wt = await session.execute(stmt_wt)
        if not res_wt.scalar_one_or_none():
            session.add(WhatsAppTemplate(**wt_data))
    await session.flush()

    return {
        "Administrador": global_admin_role,
        "Admin": admin_role,
        "Gestão": gestao_role,
        "Atendente": atendente_role,
        "Solicitante": solicitante_role,
    }


async def _seed_demo_impl(session: AsyncSession) -> None:
    roles = await sync_roles_and_permissions(session)
    hashed_pwd = hash_password(DEMO_PASSWORD)

    # 1. Empresa
    # o sistema tem uma única empresa: sobre uma base já inicializada (make seed-demo sem reset) reaproveita a existente
    company = (await session.execute(select(Company).order_by(Company.created_at, Company.id).limit(1))).scalars().first()
    if company is None:
        company = Company(
            name="TechCorp Soluções Empresariais Ltda.",
            cnpj="12.345.678/0001-90",
            logo_url=None,
        )
        session.add(company)
        await session.flush()
        print(f"Empresa '{company.name}' cadastrada.")
    else:
        print(f"Empresa '{company.name}' já existe: reaproveitada.")

    # 2. Unidades (Matriz e Filial)
    matriz = Unit(
        company_id=company.id,
        name="Matriz Corporativa - SP",
        code="MAT-01",
        type="MATRIZ",
        address="Av. Paulista, 1000, 14º andar - Bela Vista, São Paulo - SP",
    )
    filial = Unit(
        company_id=company.id,
        name="Filial Operacional - Campinas",
        code="FIL-01",
        type="FILIAL",
        address="Av. Eng. Carlos Stevenson, 450 - Nova Campinas, Campinas - SP",
    )
    session.add_all([matriz, filial])
    await session.flush()
    print("Unidades Matriz e Filial cadastradas.")

    # 3. Setores (4 na Matriz + 4 na Filial)
    # Matriz
    sec_financeiro = Sector(unit_id=matriz.id, name="Financeiro", code="MAT-FIN")
    sec_comercial = Sector(unit_id=matriz.id, name="Comercial", code="MAT-COM")
    sec_diretoria = Sector(unit_id=matriz.id, name="Diretoria", code="MAT-DIR")
    sec_rh = Sector(unit_id=matriz.id, name="Recursos Humanos", code="MAT-RH")

    # Filial
    sec_adm = Sector(unit_id=filial.id, name="Administrativo", code="FIL-ADM")
    sec_operacional = Sector(unit_id=filial.id, name="Operacional", code="FIL-OPE")
    sec_manutencao = Sector(unit_id=filial.id, name="Manutenção", code="FIL-MAN")
    sec_ti = Sector(unit_id=filial.id, name="TI / Suporte", code="FIL-TI")

    sectors = [
        sec_financeiro,
        sec_comercial,
        sec_diretoria,
        sec_rh,
        sec_adm,
        sec_operacional,
        sec_manutencao,
        sec_ti,
    ]
    session.add_all(sectors)
    await session.flush()
    print("8 Setores cadastrados (4 Matriz, 4 Filial).")

    # 4. Colaboradores e Usuários (1 por setor + 1 Admin Operacional + 1 Administrador Global)
    users_specs = [
        {
            "unit": matriz,
            "sector": sec_financeiro,
            "name": "Lucas Mendes",
            "registration": "EMP-1001",
            "position": "Analista Financeiro",
            "phone": "+55 11 98111-2001",
            "email": "lucas.financeiro@empresa.com.br",
            "role": roles["Atendente"],  # Atendente do Setor Financeiro
            "is_admin": False,
        },
        {
            "unit": matriz,
            "sector": sec_comercial,
            "name": "Mariana Costa",
            "registration": "EMP-1002",
            "position": "Executiva de Contas",
            "phone": "+55 11 98111-2002",
            "email": "mariana.comercial@empresa.com.br",
            "role": roles["Solicitante"],  # Solicitante Comercial
            "is_admin": False,
        },
        {
            "unit": matriz,
            "sector": sec_diretoria,
            "name": "Roberto Silveira",
            "registration": "EMP-1003",
            "position": "Diretor Executivo",
            "phone": "+55 11 98111-2003",
            "email": "roberto.diretoria@empresa.com.br",
            "role": roles["Gestão"],  # Perfil Gestão / Gestor (Visão ampla, SLA e relatórios)
            "is_admin": False,
        },
        {
            "unit": matriz,
            "sector": sec_rh,
            "name": "Carla Albuquerque",
            "registration": "EMP-1004",
            "position": "Coordenadora de RH",
            "phone": "+55 11 98111-2004",
            "email": "carla.rh@empresa.com.br",
            "role": roles["Atendente"],  # Atendente do Setor RH
            "is_admin": False,
        },
        {
            "unit": matriz,
            "sector": sec_diretoria,
            "name": "Carlos Drummond",
            "registration": "EMP-1005",
            "position": "Administrador de Sistemas & TI",
            "phone": "+55 11 98111-2005",
            "email": "carlos.admin@empresa.com.br",
            "role": roles["Admin"],  # Perfil Admin (Gestão completa de ativos, estoque e usuários)
            "is_admin": False,
        },
        {
            "unit": filial,
            "sector": sec_adm,
            "name": "Patrícia Lima",
            "registration": "EMP-2001",
            "position": "Assistente Administrativo",
            "phone": "+55 19 98222-3001",
            "email": "patricia.adm@empresa.com.br",
            "role": roles["Solicitante"],  # Solicitante Administrativo
            "is_admin": False,
        },
        {
            "unit": filial,
            "sector": sec_operacional,
            "name": "Marcos Rocha",
            "registration": "EMP-2002",
            "position": "Supervisor Operacional",
            "phone": "+55 19 98222-3002",
            "email": "marcos.operacional@empresa.com.br",
            "role": roles["Solicitante"],  # Solicitante Operacional
            "is_admin": False,
        },
        {
            "unit": filial,
            "sector": sec_manutencao,
            "name": "Felipe Santos",
            "registration": "EMP-2003",
            "position": "Líder de Manutenção Predial",
            "phone": "+55 19 98222-3003",
            "email": "felipe.manutencao@empresa.com.br",
            "role": roles["Atendente"],  # Atendente do Setor Manutenção
            "is_admin": False,
        },
        {
            "unit": filial,
            "sector": sec_ti,
            "name": "Gabriel Oliveira",
            "registration": "EMP-2004",
            "position": "Analista de Suporte de TI",
            "phone": "+55 19 98222-3004",
            "email": "gabriel.ti@empresa.com.br",
            "role": roles["Atendente"],  # Atendente do Setor TI
            "is_admin": False,
        },
    ]

    employee_map: dict[str, Employee] = {}
    user_map: dict[str, UserAccount] = {}

    for u in users_specs:
        emp = Employee(
            unit_id=u["unit"].id,
            sector_id=u["sector"].id,
            name=u["name"],
            registration_number=u["registration"],
            position=u["position"],
            phone=u["phone"],
            status="ATIVO",
        )
        session.add(emp)
        await session.flush()
        employee_map[u["name"]] = emp

        user = UserAccount(
            employee_id=emp.id,
            email=u["email"],
            hashed_password=hashed_pwd,
            must_change_password=False,
            is_admin=u["is_admin"],
            last_login_at=datetime.now(timezone.utc),
        )
        user.roles = [u["role"]]
        session.add(user)
        await session.flush()
        user_map[u["email"]] = user

    # Administrador Global (Acesso Total com colaborador e perfil Administrador)
    admin_emp = Employee(
        unit_id=matriz.id,
        sector_id=sec_diretoria.id,
        name="Administrador do Sistema",
        registration_number="EMP-0001",
        position="Gestor Global de TI & Infraestrutura",
        phone="+55 11 99999-0000",
        status="ATIVO",
    )
    session.add(admin_emp)
    await session.flush()
    employee_map["Administrador do Sistema"] = admin_emp

    admin_user = UserAccount(
        employee_id=admin_emp.id,
        email="admin@empresa.com.br",
        hashed_password=hashed_pwd,
        must_change_password=False,
        is_admin=True,
        last_login_at=datetime.now(timezone.utc),
    )
    admin_user.roles = [roles["Administrador"]]
    session.add(admin_user)
    await session.flush()
    user_map["admin@empresa.com.br"] = admin_user
    print(f"10 Usuários criados com sucesso (8 de setor + 1 Admin Operacional + 1 Administrador Global). Senha padrão: {DEMO_PASSWORD}")

    # 5. Categorias de Chamados (2 por setor = 16 categorias)
    ticket_categories_data = [
        # Financeiro
        {
            "name": "Financeiro: Liberação de Acesso Bancário e ERP",
            "desc": "Solicitação de novo usuário, alteração de alçadas ou liberação de módulos no sistema financeiro.",
            "sector": sec_financeiro,
            "schema": [
                {"name": "sistema", "label": "Sistema ou Banco", "type": "text", "required": True},
                {"name": "perfil", "label": "Perfil / Alçada Solicitada", "type": "text", "required": True},
                {"name": "centro_custo", "label": "Centro de Custo", "type": "text", "required": False},
            ],
        },
        {
            "name": "Financeiro: Certificado Digital (A1 / A3 / e-CNPJ)",
            "desc": "Instalação, renovação, emissão ou desbloqueio de mídias de certificado digital da empresa.",
            "sector": sec_financeiro,
            "schema": [
                {"name": "tipo_certificado", "label": "Tipo (A1 Arquivo, A3 Token/Cartão)", "type": "text", "required": True},
                {"name": "cnpj", "label": "CNPJ do Certificado", "type": "text", "required": True},
            ],
        },
        # Comercial
        {
            "name": "Comercial: Licença e Permissões no CRM de Vendas",
            "desc": "Criação de novos acessos de vendedores, ajuste de carteiras e funis de vendas no CRM.",
            "sector": sec_comercial,
            "schema": [
                {"name": "nome_crm", "label": "Ferramenta CRM", "type": "text", "required": True},
                {"name": "regiao", "label": "Região Comercial / Equipe", "type": "text", "required": True},
            ],
        },
        {
            "name": "Comercial: Configuração de E-mail e Apps Móveis",
            "desc": "Sincronização de e-mail corporativo, assinatura padrão e aplicativos de vendas em celulares corporativos.",
            "sector": sec_comercial,
            "schema": [
                {"name": "modelo_aparelho", "label": "Modelo do Celular / Tablet", "type": "text", "required": True},
                {"name": "sistema_operacional", "label": "Sistema Operacional (Android/iOS)", "type": "text", "required": True},
            ],
        },
        # Diretoria
        {
            "name": "Diretoria: Suporte Técnico a Videoconferência e Reuniões",
            "desc": "Preparação e apoio técnico presencial/remoto para reuniões estratégicas, salas de diretoria e transmissões.",
            "sector": sec_diretoria,
            "schema": [
                {"name": "data_hora", "label": "Data e Hora da Reunião", "type": "text", "required": True},
                {"name": "sala", "label": "Sala / Local", "type": "text", "required": True},
                {"name": "plataforma", "label": "Plataforma (Teams, Meet, Zoom)", "type": "text", "required": True},
            ],
        },
        {
            "name": "Diretoria: Substituição / Upgrade de Equipamento Executivo",
            "desc": "Atendimento preferencial para troca, manutenção emergencial ou upgrade de notebooks e celulares executivos.",
            "sector": sec_diretoria,
            "schema": [
                {"name": "equipamento_atual", "label": "Equipamento Atual", "type": "text", "required": True},
                {"name": "motivo", "label": "Motivo da Solicitação", "type": "textarea", "required": True},
            ],
        },
        # RH
        {
            "name": "RH: Onboarding de Novo Colaborador (Kit de TI)",
            "desc": "Provisionamento de máquina, e-mail, acessos a pastas de rede e kit de boas-vindas para novo contratado.",
            "sector": sec_rh,
            "schema": [
                {"name": "nome_colaborador", "label": "Nome do Colaborador", "type": "text", "required": True},
                {"name": "cargo", "label": "Cargo / Função", "type": "text", "required": True},
                {"name": "setor_destino", "label": "Setor de Destino", "type": "text", "required": True},
                {"name": "data_admissao", "label": "Data de Início", "type": "date", "required": True},
            ],
        },
        {
            "name": "RH: Offboarding (Desligamento e Recolhimento de Ativos)",
            "desc": "Revogação imediata de credenciais de acesso, arquivamento de e-mail e conferência de devolução de patrimônio.",
            "sector": sec_rh,
            "schema": [
                {"name": "nome_colaborador", "label": "Colaborador Desligado", "type": "text", "required": True},
                {"name": "data_desligamento", "label": "Data de Desligamento", "type": "date", "required": True},
                {"name": "ativos_recolhidos", "label": "Equipamentos a Recolher", "type": "textarea", "required": True},
            ],
        },
        # Administrativo
        {
            "name": "Administrativo: Pastas em Rede e Mapeamento de Impressoras",
            "desc": "Ajuste de permissões em pastas compartilhadas na rede interna e mapeamento de impressoras departamentais.",
            "sector": sec_adm,
            "schema": [
                {"name": "caminho_pasta", "label": "Caminho da Pasta / Impressora", "type": "text", "required": True},
                {"name": "tipo_permissao", "label": "Permissão (Leitura / Completa)", "type": "text", "required": True},
            ],
        },
        {
            "name": "Administrativo: Suporte a Relógio de Ponto e Catracas",
            "desc": "Manutenção, sincronização de dados ou falhas de leitura biométrica e cartões de acesso predial.",
            "sector": sec_adm,
            "schema": [
                {"name": "equipamento", "label": "Dispositivo (Catraca / Relógio)", "type": "text", "required": True},
                {"name": "localizacao", "label": "Localização Física", "type": "text", "required": True},
            ],
        },
        # Operacional
        {
            "name": "Operacional: Falha de Conexão em Terminais de Expedição",
            "desc": "Interrupção de internet, instabilidade de rede ou travamento de terminal de bipagem e faturamento na expedição.",
            "sector": sec_operacional,
            "schema": [
                {"name": "identificacao_terminal", "label": "Número / Nome do Terminal", "type": "text", "required": True},
                {"name": "descricao_falha", "label": "Sintoma Observado", "type": "textarea", "required": True},
            ],
        },
        {
            "name": "Operacional: Substituição de Leitores de Código de Barras",
            "desc": "Troca de leitor laser/óptico com defeito, quebra de cabo USB ou suporte a leitor sem fio.",
            "sector": sec_operacional,
            "schema": [
                {"name": "modelo_leitor", "label": "Tipo / Modelo do Leitor", "type": "text", "required": True},
                {"name": "defeito", "label": "Defeito Apresentado", "type": "text", "required": True},
            ],
        },
        # Manutenção
        {
            "name": "Manutenção: Vistoria Preventiva de Racks e Cabeamento",
            "desc": "Acompanhamento técnico em salas elétricas, nobreaks centrais, ar-condicionado de TI e cabeamento estruturado.",
            "sector": sec_manutencao,
            "schema": [
                {"name": "rack_sala", "label": "Sala / Rack Envolvido", "type": "text", "required": True},
                {"name": "tipo_vistoria", "label": "Escopo da Vistoria", "type": "text", "required": True},
            ],
        },
        {
            "name": "Manutenção: Reparo e Troca de Tomadas e Conectores RJ45",
            "desc": "Substituição de tomadas fêmea de rede, crimpagem de conectores danificados ou passagem de cabos.",
            "sector": sec_manutencao,
            "schema": [
                {"name": "ponto_rede", "label": "Identificação do Ponto / Tomada", "type": "text", "required": True},
                {"name": "ambiente", "label": "Setor / Mesa", "type": "text", "required": True},
            ],
        },
        # TI
        {
            "name": "TI: Atendimento Geral de Helpdesk (Hardware e Software)",
            "desc": "Chamado geral para resolução de problemas em computadores, lentidão, formatação, reinstalação de Windows e Office.",
            "sector": sec_ti,
            "schema": [
                {"name": "patrimonio", "label": "Tag de Patrimônio (se houver)", "type": "text", "required": False},
                {"name": "mensagem_erro", "label": "Mensagem de Erro Apresentada", "type": "textarea", "required": False},
            ],
        },
        {
            "name": "TI: Restauração de Arquivos e Recuperação de Backups",
            "desc": "Recuperação emergencial de planilhas, arquivos de banco de dados ou pastas corrompidas/excluídas por engano.",
            "sector": sec_ti,
            "schema": [
                {"name": "nome_arquivo", "label": "Nome do Arquivo / Pasta", "type": "text", "required": True},
                {"name": "data_aproximada", "label": "Data do Ponto de Restauração", "type": "text", "required": True},
            ],
        },
    ]

    ticket_cat_map: dict[str, TicketCategory] = {}
    for tc_data in ticket_categories_data:
        cat = TicketCategory(
            name=tc_data["name"],
            description=tc_data["desc"],
            is_active=True,
            default_sector_id=tc_data["sector"].id,
            form_schema=tc_data["schema"],
        )
        session.add(cat)
        await session.flush()
        ticket_cat_map[tc_data["name"]] = cat
    print("16 Categorias de Chamados criadas (2 por setor com formulários dinâmicos).")

    # 6. Categorias de Ativos e 10 Ativos Patrimoniais
    cat_pc = AssetCategory(
        name="Computadores & Notebooks",
        description="Laptops corporativos, estações de trabalho e desktops.",
        spec_schema={
            "cpu": {"label": "Processador", "required": True},
            "ram": {"label": "Memória RAM", "required": True},
            "storage": {"label": "Armazenamento", "required": True},
            "os": {"label": "Sistema Operacional", "required": True},
        },
    )
    cat_mobile = AssetCategory(
        name="Smartphones & Dispositivos Móveis",
        description="Smartphones corporativos e tablets para equipe comercial e externa.",
        spec_schema={
            "tela": {"label": "Tamanho da Tela", "required": True},
            "armazenamento": {"label": "Armazenamento Interno", "required": True},
            "ram": {"label": "Memória RAM", "required": True},
            "imei": {"label": "Número IMEI", "required": False},
        },
    )
    cat_print = AssetCategory(
        name="Impressoras & Multifuncionais",
        description="Impressoras laser departamentais, térmicas e multifuncionais de rede.",
        spec_schema={
            "tipo": {"label": "Tecnologia de Impressão", "required": True},
            "conexao": {"label": "Interfaces de Conexão", "required": True},
            "resolucao": {"label": "Resolução Máxima", "required": False},
        },
    )
    session.add_all([cat_pc, cat_mobile, cat_print])
    await session.flush()

    assets_data = [
        # Notebooks / Desktops
        {
            "tag": "PAT-0001",
            "name": "Notebook Dell Latitude 3420 i7 16GB",
            "category": cat_pc,
            "status": AssetStatus.IN_USE.value,
            "specs": {"cpu": "Core i7-1165G7", "ram": "16GB DDR4", "storage": "512GB NVMe SSD", "os": "Windows 11 Pro"},
            "unit": matriz,
            "employee": employee_map["Roberto Silveira"],
            "purchase_date": date(2024, 3, 10),
            "warranty_expires": date(2027, 3, 10),
            "notes": "Equipamento executivo da Diretoria Geral. Inclui bolsa de transporte e carregador USB-C 65W.",
        },
        {
            "tag": "PAT-0002",
            "name": "Notebook Lenovo ThinkPad E14 i5 16GB",
            "category": cat_pc,
            "status": AssetStatus.IN_USE.value,
            "specs": {"cpu": "Core i5-1135G7", "ram": "16GB DDR4", "storage": "256GB NVMe SSD", "os": "Windows 11 Pro"},
            "unit": matriz,
            "employee": employee_map["Lucas Mendes"],
            "purchase_date": date(2024, 5, 15),
            "warranty_expires": date(2027, 5, 15),
            "notes": "Utilizado no setor Financeiro para emissão fiscal, faturamento e planilhas orçamentárias.",
        },
        {
            "tag": "PAT-0003",
            "name": "Notebook Dell Vostro 3520 i5 8GB",
            "category": cat_pc,
            "status": AssetStatus.IN_USE.value,
            "specs": {"cpu": "Core i5-1235U", "ram": "8GB DDR4", "storage": "256GB SSD", "os": "Windows 11 Home"},
            "unit": matriz,
            "employee": employee_map["Carla Albuquerque"],
            "purchase_date": date(2024, 6, 20),
            "warranty_expires": date(2026, 6, 20),
            "notes": "Alocado no Recursos Humanos para processos seletivos e admissão de colaboradores.",
        },
        {
            "tag": "PAT-0004",
            "name": "Desktop HP ProDesk 400 G6 i5 16GB",
            "category": cat_pc,
            "status": AssetStatus.IN_USE.value,
            "specs": {"cpu": "Core i5-10500", "ram": "16GB DDR4", "storage": "512GB SSD", "os": "Windows 11 Pro"},
            "unit": filial,
            "employee": employee_map["Gabriel Oliveira"],
            "purchase_date": date(2023, 11, 5),
            "warranty_expires": date(2026, 11, 5),
            "notes": "Bancada técnica do setor de TI da filial de Campinas com dual monitor.",
        },
        {
            "tag": "PAT-0005",
            "name": "Desktop Dell OptiPlex 3080 i3 8GB",
            "category": cat_pc,
            "status": AssetStatus.IN_USE.value,
            "specs": {"cpu": "Core i3-10100", "ram": "8GB DDR4", "storage": "256GB SSD", "os": "Windows 10 Pro"},
            "unit": filial,
            "employee": employee_map["Marcos Rocha"],
            "purchase_date": date(2023, 8, 12),
            "warranty_expires": date(2025, 8, 12),
            "notes": "Terminal operacional no galpão de expedição da filial.",
        },
        # Celulares
        {
            "tag": "PAT-0006",
            "name": "Smartphone Samsung Galaxy A54 5G 128GB",
            "category": cat_mobile,
            "status": AssetStatus.IN_USE.value,
            "specs": {"tela": "6.4 Super AMOLED", "armazenamento": "128GB", "ram": "8GB", "imei": "358941092847102"},
            "unit": matriz,
            "employee": employee_map["Mariana Costa"],
            "purchase_date": date(2024, 2, 18),
            "warranty_expires": date(2025, 2, 18),
            "notes": "Aparelho funcional com plano corporativo para prospecção externa de vendas.",
        },
        {
            "tag": "PAT-0007",
            "name": "Smartphone Samsung Galaxy A15 128GB",
            "category": cat_mobile,
            "status": AssetStatus.IN_USE.value,
            "specs": {"tela": "6.5 FHD+", "armazenamento": "128GB", "ram": "4GB", "imei": "358941092847551"},
            "unit": filial,
            "employee": employee_map["Felipe Santos"],
            "purchase_date": date(2024, 7, 10),
            "warranty_expires": date(2025, 7, 10),
            "notes": "Utilizado pela equipe de manutenção predial para chamados em trânsito pela planta.",
        },
        {
            "tag": "PAT-0008",
            "name": "Smartphone Motorola Moto G54 5G 128GB",
            "category": cat_mobile,
            "status": AssetStatus.IN_STOCK.value,
            "specs": {"tela": "6.5 120Hz", "armazenamento": "128GB", "ram": "8GB", "imei": "358941092849923"},
            "unit": filial,
            "employee": None,
            "purchase_date": date(2024, 8, 1),
            "warranty_expires": date(2025, 8, 1),
            "notes": "Reserva técnica disponível na TI para substituição emergencial.",
        },
        # Impressoras
        {
            "tag": "PAT-0009",
            "name": "Impressora Multifuncional Brother DCP-L2540DW",
            "category": cat_print,
            "status": AssetStatus.IN_USE.value,
            "specs": {"tipo": "Laser Monocromática", "conexao": "Wi-Fi / Ethernet", "resolucao": "2400x600 dpi"},
            "unit": matriz,
            "employee": None,
            "purchase_date": date(2023, 9, 14),
            "warranty_expires": date(2025, 9, 14),
            "notes": "Instalada no setor Financeiro da Matriz para impressão de relatórios e faturas.",
        },
        {
            "tag": "PAT-0010",
            "name": "Impressora Multifuncional HP LaserJet Pro M428fdw",
            "category": cat_print,
            "status": AssetStatus.IN_USE.value,
            "specs": {"tipo": "Laser Multifuncional ADF", "conexao": "Ethernet / Wi-Fi", "velocidade": "38 ppm"},
            "unit": filial,
            "employee": None,
            "purchase_date": date(2023, 10, 22),
            "warranty_expires": date(2025, 10, 22),
            "notes": "Instalada no setor Administrativo da Filial para digitalização e notas de remessa.",
        },
    ]

    assets_created: list[Asset] = []
    for a_data in assets_data:
        ast = Asset(
            tag=a_data["tag"],
            name=a_data["name"],
            category_id=a_data["category"].id,
            status=a_data["status"],
            technical_specs=a_data["specs"],
            purchase_date=a_data["purchase_date"],
            warranty_expires=a_data["warranty_expires"],
            notes=a_data["notes"],
            unit_id=a_data["unit"].id,
            employee_id=a_data["employee"].id if a_data["employee"] else None,
        )
        session.add(ast)
        await session.flush()
        assets_created.append(ast)

        # Histórico de movimentação patrimonial inicial
        mov = AssetMovement(
            asset_id=ast.id,
            movement_type=MovementType.ASSIGNMENT.value if ast.employee_id else MovementType.INITIAL_STOCK.value,
            from_unit_id=None,
            to_unit_id=ast.unit_id,
            from_employee_id=None,
            to_employee_id=ast.employee_id,
            status_from=None,
            status_to=ast.status,
            notes=f"Cadastro inicial patrimonial do ativo {ast.tag}.",
            author_id=admin_user.id,
        )
        session.add(mov)

    print("10 Ativos Patrimoniais criados (computadores, celulares e impressoras com rastreabilidade).")

    # 7. Categorias de Insumos (10 Categorias Solicitadas) e Estoque Inicial
    stock_categories_specs = [
        {
            "name": "Tintas e Toners para Impressoras",
            "description": "Cartuchos de toner laser, garrafas de tinta para refil e fotocondutores.",
            "schema": {
                "modelo": {"label": "Modelo do Toner/Tinta", "required": True},
                "compatibilidade": {"label": "Impressoras Compatíveis", "required": True},
                "cor": {"label": "Cor do Suprimento", "required": False},
            },
            "items": [
                {
                    "name": "Toner Brother TN-2370 Preto Original",
                    "desc": "Toner para impressora Brother DCP-L2540DW (Rendimento aproximado de 2.600 páginas).",
                    "unit": matriz,
                    "qty": 6,
                    "min_qty": 2,
                    "specs": {"modelo": "TN-2370", "compatibilidade": "Brother DCP-L2540DW / HL-L2360DW", "cor": "Preto"},
                },
                {
                    "name": "Toner HP CF258A 58A Preto",
                    "desc": "Toner para multifuncional HP LaserJet Pro M428fdw (Rendimento até 3.000 páginas).",
                    "unit": filial,
                    "qty": 4,
                    "min_qty": 2,
                    "specs": {"modelo": "CF258A 58A", "compatibilidade": "HP LaserJet Pro M428fdw / M404n", "cor": "Preto"},
                },
            ],
        },
        {
            "name": "Teclados",
            "description": "Teclados com fio USB, teclados sem fio e kits multimídia padrão ABNT2.",
            "schema": {
                "conexao": {"label": "Tipo de Conexão (USB / Wireless)", "required": True},
                "padrao": {"label": "Padrão de Teclas (ABNT2)", "required": True},
            },
            "items": [
                {
                    "name": "Teclado USB Logitech K120 ABNT2 Preto",
                    "desc": "Teclado com fio resistente a respingos com conexão USB.",
                    "unit": matriz,
                    "qty": 15,
                    "min_qty": 5,
                    "specs": {"conexao": "USB", "padrao": "ABNT2", "garantia": "36 meses"},
                },
                {
                    "name": "Teclado Sem Fio Dell Pro KM5221W ABNT2",
                    "desc": "Teclado sem fio de alta durabilidade com receptor USB 2.4GHz.",
                    "unit": filial,
                    "qty": 8,
                    "min_qty": 3,
                    "specs": {"conexao": "Wireless 2.4GHz", "padrao": "ABNT2", "bateria": "Pilha AAA"},
                },
            ],
        },
        {
            "name": "Mouses",
            "description": "Mouses ópticos com fio USB e sem fio de precisão para estações de trabalho.",
            "schema": {
                "dpi": {"label": "Resolução DPI", "required": False},
                "conexao": {"label": "Conexão (USB / Wireless)", "required": True},
            },
            "items": [
                {
                    "name": "Mouse Óptico USB Logitech M90 Preto",
                    "desc": "Mouse ambidestro simples com fio USB de 1000 DPI.",
                    "unit": matriz,
                    "qty": 20,
                    "min_qty": 5,
                    "specs": {"dpi": "1000 DPI", "conexao": "USB", "formato": "Ambidestro"},
                },
                {
                    "name": "Mouse Sem Fio Logitech M170 Cinza",
                    "desc": "Mouse compacto sem fio com receptor nano USB.",
                    "unit": filial,
                    "qty": 10,
                    "min_qty": 4,
                    "specs": {"dpi": "1000 DPI", "conexao": "Wireless 2.4GHz", "bateria": "1x Pilha AA"},
                },
            ],
        },
        {
            "name": "Conectores e Cabeamento RJ45",
            "description": "Conectores RJ45 Cat6, cabos de rede montados (patch cords) e bobinas UTP.",
            "schema": {
                "categoria": {"label": "Categoria de Rede (Cat5e / Cat6)", "required": True},
                "comprimento": {"label": "Comprimento ou Embalagem", "required": False},
            },
            "items": [
                {
                    "name": "Conector RJ45 Cat6 Macho (Pacote com 100 un)",
                    "desc": "Conectores com guias internos e pinos folheados a ouro para conectorização Cat6.",
                    "unit": filial,
                    "qty": 3,
                    "min_qty": 1,
                    "specs": {"categoria": "Cat6", "tipo": "Macho 8P8C", "quantidade_embalagem": "100 unidades"},
                },
                {
                    "name": "Cabo de Rede Patch Cord Cat6 2.5m Azul Furukawa",
                    "desc": "Patch cord conectorizado de fábrica com capas protetoras injetadas.",
                    "unit": matriz,
                    "qty": 25,
                    "min_qty": 10,
                    "specs": {"categoria": "Cat6", "comprimento": "2.5 metros", "cor": "Azul"},
                },
            ],
        },
        {
            "name": "Fontes e Carregadores para Celular",
            "description": "Carregadores de tomada bivolt rápidos, cabos USB-C e Lightning.",
            "schema": {
                "potencia": {"label": "Potência (W)", "required": True},
                "padrao": {"label": "Padrão de Conexão", "required": True},
            },
            "items": [
                {
                    "name": "Carregador Rápido de Tomada USB-C 25W Samsung",
                    "desc": "Adaptador de energia bivolt com carregamento super rápido compatível com linha Galaxy.",
                    "unit": matriz,
                    "qty": 8,
                    "min_qty": 3,
                    "specs": {"potencia": "25W", "padrao": "USB-C Power Delivery", "voltagem": "Bivolt 110/220V"},
                },
                {
                    "name": "Cabo USB-C para USB-C 1.0m Blindado",
                    "desc": "Cabo de sincronização e carga rápida reforçado em nylon trançado.",
                    "unit": filial,
                    "qty": 12,
                    "min_qty": 4,
                    "specs": {"potencia": "Até 60W", "padrao": "USB-C para USB-C", "comprimento": "1.0 metro"},
                },
            ],
        },
        {
            "name": "Películas Protetoras para Celular",
            "description": "Películas de vidro temperado 3D e cerâmica para conservação das telas corporativas.",
            "schema": {
                "modelo_compativel": {"label": "Modelo Compatível", "required": True},
                "material": {"label": "Material (Vidro 3D / Cerâmica)", "required": True},
            },
            "items": [
                {
                    "name": "Película Protetora de Vidro 3D Galaxy A54",
                    "desc": "Película com bordas pretas curvas e cobertura integral da tela do Galaxy A54.",
                    "unit": matriz,
                    "qty": 10,
                    "min_qty": 3,
                    "specs": {"modelo_compativel": "Samsung Galaxy A54 5G", "material": "Vidro Temperado 9H"},
                },
                {
                    "name": "Película Protetora Cerâmica Fosca Moto G54",
                    "desc": "Película flexível antirreflexo resistente a impactos para Moto G54.",
                    "unit": filial,
                    "qty": 10,
                    "min_qty": 3,
                    "specs": {"modelo_compativel": "Motorola Moto G54 5G", "material": "Cerâmica Fosca"},
                },
            ],
        },
        {
            "name": "Capas Protetoras para Celular",
            "description": "Capas em silicone anti-queda e cases rígidos com cantos reforçados.",
            "schema": {
                "modelo_compativel": {"label": "Modelo Compatível", "required": True},
                "tipo_capa": {"label": "Tipo de Proteção", "required": True},
            },
            "items": [
                {
                    "name": "Capa Silicone Anti-impacto Transparente Galaxy A54",
                    "desc": "Capa com cantos elevados com absorção de choque (Air Cushion) para Galaxy A54.",
                    "unit": matriz,
                    "qty": 10,
                    "min_qty": 3,
                    "specs": {"modelo_compativel": "Samsung Galaxy A54 5G", "tipo_capa": "Silicone TPU Transparente"},
                },
                {
                    "name": "Capa Rígida Protetora Militar Moto G54",
                    "desc": "Capa robusta com textura antiderrapante e proteção contra quedas para operação.",
                    "unit": filial,
                    "qty": 8,
                    "min_qty": 2,
                    "specs": {"modelo_compativel": "Motorola Moto G54 5G", "tipo_capa": "Híbrida Policarbonato + TPU"},
                },
            ],
        },
        {
            "name": "Cases e Maletas para Notebooks",
            "description": "Cases acolchoados em neoprene, capas impermeáveis e mochilas para laptops.",
            "schema": {
                "polegadas": {"label": "Tamanho Máximo (Polegadas)", "required": True},
                "compartimentos": {"label": "Compartimentos", "required": False},
            },
            "items": [
                {
                    "name": "Case Neoprene Protetor 14 Polegadas Preto",
                    "desc": "Case impermeável com zíper duplo e forro aveludado interno para ThinkPad e Dell 14'.",
                    "unit": matriz,
                    "qty": 12,
                    "min_qty": 4,
                    "specs": {"polegadas": "14.0 pol", "material": "Neoprene 4mm impermeável", "cor": "Preto"},
                },
                {
                    "name": "Mochila Executiva Acolchoada para Notebook 15.6",
                    "desc": "Mochila antifurto com compartimento acolchoado para notebook de até 15.6 polegadas.",
                    "unit": filial,
                    "qty": 6,
                    "min_qty": 2,
                    "specs": {"polegadas": "15.6 pol", "compartimentos": "3 bolsos externos + divisória interna"},
                },
            ],
        },
        {
            "name": "Cabos e Adaptadores de Vídeo/Energia",
            "description": "Cabos HDMI 4K, adaptadores USB-C multiportas e extensores de vídeo.",
            "schema": {
                "tipo": {"label": "Tipo de Conexão", "required": True},
                "comprimento": {"label": "Comprimento / Padrão", "required": False},
            },
            "items": [
                {
                    "name": "Cabo HDMI 2.0 4K 2 Metros Blindado",
                    "desc": "Cabo HDMI de alta velocidade compatível com resolução 4K a 60Hz para monitores.",
                    "unit": matriz,
                    "qty": 14,
                    "min_qty": 5,
                    "specs": {"tipo": "HDMI 2.0", "comprimento": "2.0 metros", "resolucao": "4K 60Hz"},
                },
            ],
        },
        {
            "name": "Componentes e Peças de Reposição",
            "description": "Unidades SSD NVMe, módulos de memória RAM DDR4 e fontes de alimentação.",
            "schema": {
                "tipo_peca": {"label": "Tipo de Peça", "required": True},
                "capacidade": {"label": "Capacidade / Frequência", "required": True},
            },
            "items": [
                {
                    "name": "SSD Kingston NV2 500GB M.2 NVMe PCIe 4.0",
                    "desc": "Unidade SSD de alta velocidade para upgrade de inicialização de desktops e notebooks.",
                    "unit": filial,
                    "qty": 5,
                    "min_qty": 2,
                    "specs": {"tipo_peca": "SSD NVMe M.2 2280", "capacidade": "500GB", "velocidade": "Leitura até 3500MB/s"},
                },
            ],
        },
    ]

    stock_items_created: list[StockItem] = []
    for sc_spec in stock_categories_specs:
        scat = StockCategory(
            name=sc_spec["name"],
            description=sc_spec["description"],
            spec_schema=sc_spec["schema"],
        )
        session.add(scat)
        await session.flush()

        for it in sc_spec["items"]:
            stk_item = StockItem(
                name=it["name"],
                description=it["desc"],
                unit_id=it["unit"].id,
                quantity=it["qty"],
                min_quantity=it["min_qty"],
                category_id=scat.id,
                technical_specs=it["specs"],
            )
            session.add(stk_item)
            await session.flush()
            stock_items_created.append(stk_item)

            # Movimentação inicial de entrada no estoque
            sm = StockMovement(
                item_id=stk_item.id,
                movement_type="IN",
                quantity=it["qty"],
                author_id=admin_user.id,
                notes="Carga de implantação de estoque e ambientação inicial.",
            )
            session.add(sm)

    print(f"10 Categorias de Insumos cadastradas com {len(stock_items_created)} itens em estoque e movimentações de entrada.")

    # 8. Chamados de Demonstração (Exemplos vivos para o Kanban)
    cat_onboarding = ticket_cat_map["RH: Onboarding de Novo Colaborador (Kit de TI)"]
    cat_helpdesk = ticket_cat_map["TI: Atendimento Geral de Helpdesk (Hardware e Software)"]
    cat_pastas = ticket_cat_map["Administrativo: Pastas em Rede e Mapeamento de Impressoras"]

    # Chamado 1: Em Atendimento (Com Gabriel da TI)
    ticket_1 = Ticket(
        title="Preparação de kit de TI para novo Analista Comercial",
        description="Novo colaborador inicia na próxima segunda-feira. Solicito liberação de notebook com pacote Office, e-mail corporativo configurado e case de transporte.",
        priority="HIGH",
        status="IN_PROGRESS",
        custom_fields={
            "nome_colaborador": "Rodrigo Silva",
            "cargo": "Consultor de Vendas Sênior",
            "setor_destino": "Comercial",
            "data_admissao": (date.today() + timedelta(days=5)).isoformat(),
        },
        requester_id=employee_map["Carla Albuquerque"].id,
        created_by_user_id=admin_user.id,  # aberto pela carga de demonstração
        assignee_id=user_map["gabriel.ti@empresa.com.br"].id,
        origin_unit_id=matriz.id,
        origin_sector_id=sec_rh.id,
        responsible_sector_id=sec_ti.id,
        category_id=cat_onboarding.id,
    )
    session.add(ticket_1)
    await session.flush()

    # Interação do chamado 1
    interac_1 = TicketInteraction(
        ticket_id=ticket_1.id,
        author_id=user_map["gabriel.ti@empresa.com.br"].id,
        message="Notebook já reservado no estoque e sistema operacional atualizado com os padrões da empresa. Concluirei a instalação dos aplicativos hoje à tarde.",
        is_internal=False,
    )
    session.add(interac_1)

    # Chamado 2: Resolvido com Consumo de Material de Estoque
    ticket_2 = Ticket(
        title="Substituição de teclado com defeito na recepção da filial",
        description="As teclas de pontuação e a barra de espaço do teclado da recepção pararam de responder após queda acidental.",
        priority="LOW",
        status="RESOLVED",
        custom_fields={
            "patrimonio": "PAT-0005",
            "mensagem_erro": "Teclas de espaço e interrogação sem resposta mecânica",
        },
        requester_id=employee_map["Patrícia Lima"].id,
        created_by_user_id=admin_user.id,  # aberto pela carga de demonstração
        assignee_id=user_map["gabriel.ti@empresa.com.br"].id,
        origin_unit_id=filial.id,
        origin_sector_id=sec_adm.id,
        responsible_sector_id=sec_ti.id,
        category_id=cat_helpdesk.id,
    )
    session.add(ticket_2)
    await session.flush()

    interac_2 = TicketInteraction(
        ticket_id=ticket_2.id,
        author_id=user_map["gabriel.ti@empresa.com.br"].id,
        message="Teclado substituído com sucesso por um novo modelo Logitech com garantia. Testado e operando normalmente.",
        is_internal=False,
    )
    session.add(interac_2)

    # Baixa de 1 teclado como material utilizado no chamado 2
    teclado_item = next(item for item in stock_items_created if "Teclado" in item.name and item.unit_id == filial.id)
    mat_used = TicketMaterial(
        ticket_id=ticket_2.id,
        stock_item_id=teclado_item.id,
        quantity=1,
        author_id=user_map["gabriel.ti@empresa.com.br"].id,
    )
    session.add(mat_used)

    # Chamado 3: Aberto / Aguardando Triagem
    ticket_3 = Ticket(
        title="Mapeamento da pasta de remessas e expedição da filial",
        description="Novo terminal da balança precisa acessar a pasta compartilhada \\\\server-campinas\\expedicao para envio automático de arquivos CSV.",
        priority="MEDIUM",
        status="OPENED",
        custom_fields={
            "caminho_pasta": "\\\\server-campinas\\expedicao",
            "tipo_permissao": "Leitura e Gravação",
        },
        requester_id=employee_map["Marcos Rocha"].id,
        created_by_user_id=admin_user.id,  # aberto pela carga de demonstração
        assignee_id=None,
        origin_unit_id=filial.id,
        origin_sector_id=sec_operacional.id,
        responsible_sector_id=sec_ti.id,
        category_id=cat_pastas.id,
    )
    session.add(ticket_3)

    # Chamado 4: Em Aberto no Setor Financeiro (Para Lucas Mendes atender)
    cat_erp = ticket_cat_map["Financeiro: Liberação de Acesso Bancário e ERP"]
    ticket_4 = Ticket(
        title="Liberação de alçada de faturamento e conciliação bancária no ERP",
        description="Cliente corporativo fechou contrato de grande porte. Necessário liberar acesso ao módulo de faturamento e conciliação bancária no ERP para emissão de notas fiscais.",
        priority="HIGH",
        status="OPENED",
        custom_fields={
            "sistema": "TOTVS Protheus / Bradesco Net Empresa",
            "perfil": "Faturamento Comercial Nível 2",
            "centro_custo": "CC-201 (Comercial Matriz)",
        },
        requester_id=employee_map["Mariana Costa"].id,
        created_by_user_id=admin_user.id,  # aberto pela carga de demonstração
        assignee_id=None,
        origin_unit_id=matriz.id,
        origin_sector_id=sec_comercial.id,
        responsible_sector_id=sec_financeiro.id,
        category_id=cat_erp.id,
    )
    session.add(ticket_4)

    # Chamado 5: Em Atendimento no Setor de Manutenção (Para Felipe Santos atender)
    cat_tomadas = ticket_cat_map["Manutenção: Reparo e Troca de Tomadas e Conectores RJ45"]
    ticket_5 = Ticket(
        title="Reparo de ponto de rede com conector danificado no galpão",
        description="A trava do conector RJ45 quebrou e o cabo de rede está soltando da tomada da parede no posto de conferência.",
        priority="MEDIUM",
        status="IN_PROGRESS",
        custom_fields={
            "ponto_rede": "PONTO-RJ45-OPE-03",
            "ambiente": "Bancada de Triagem e Expedição",
        },
        requester_id=employee_map["Marcos Rocha"].id,
        created_by_user_id=admin_user.id,  # aberto pela carga de demonstração
        assignee_id=user_map["felipe.manutencao@empresa.com.br"].id,
        origin_unit_id=filial.id,
        origin_sector_id=sec_operacional.id,
        responsible_sector_id=sec_manutencao.id,
        category_id=cat_tomadas.id,
    )
    session.add(ticket_5)
    await session.flush()

    interac_5 = TicketInteraction(
        ticket_id=ticket_5.id,
        author_id=user_map["felipe.manutencao@empresa.com.br"].id,
        message="Vistoria técnica realizada no ponto de rede. Conector macho RJ45 substituído e recrimpado com sucesso. Ponto retestado e operando a 1Gbps.",
        is_internal=False,
    )
    session.add(interac_5)

    await session.commit()
    print("\n==================================================================")
    print("*** AMBIENTACAO CONCLUIDA COM SUCESSO! ***")
    print("==================================================================")
    print("Empresa: TechCorp Soluções Empresariais Ltda.")
    print("Unidades: Matriz Corporativa - SP | Filial Operacional - Campinas")
    print("Setores: 8 setores (Financeiro, Comercial, Diretoria, RH, Administrativo, Operacional, Manutenção, TI)")
    print(f"Senha de acesso para todos os usuários: {DEMO_PASSWORD}")
    print("\nUsuários e Perfis configurados (Hierarquia de Menor Privilégio):")
    print("  [Tier 5 - Administrador Global]")
    print("  - admin@empresa.com.br        -> Acesso irrestrito + backups de banco e bot WhatsApp")
    print("  [Tier 4 - Admin Operacional]")
    print("  - carlos.admin@empresa.com.br -> Gestão completa de inventário, ativos, estoque e usuários")
    print("  [Tier 3 - Gestão]")
    print("  - roberto.diretoria@empresa.com.br -> Visão ampla de chamados, relatórios/SLAs e auditoria")
    print("  [Tier 2 - Atendentes Setoriais]")
    print("  - lucas.financeiro@empresa.com.br   -> Atendente do Setor Financeiro")
    print("  - carla.rh@empresa.com.br           -> Atendente do Setor RH")
    print("  - felipe.manutencao@empresa.com.br  -> Atendente do Setor Manutenção")
    print("  - gabriel.ti@empresa.com.br         -> Atendente do Setor TI")
    print("  [Tier 1 - Solicitantes]")
    print("  - mariana.comercial@empresa.com.br  -> Abertura e acompanhamento + visualização dos próprios itens")
    print("  - patricia.adm@empresa.com.br       -> Abertura e acompanhamento + visualização dos próprios itens")
    print("  - marcos.operacional@empresa.com.br -> Abertura e acompanhamento + visualização dos próprios itens")
    print("==================================================================")


async def seed_demo(reset: bool = True, session: AsyncSession | None = None) -> None:
    """Popula o ambiente com a ambientação corporativa de demonstração."""
    if session is not None:
        if reset:
            await clean_database(session)
        await _seed_demo_impl(session)
    else:
        async with AsyncSessionLocal() as sess:
            if reset:
                await clean_database(sess)
            await _seed_demo_impl(sess)


def main():
    parser = argparse.ArgumentParser(description="Script de ambientação de demonstração para Gestão de TI.")
    parser.add_argument(
        "--reset",
        action="store_true",
        default=True,
        help="Limpa tabelas de teste e transações prévias antes de inserir os dados de demonstração (padrão: True).",
    )
    parser.add_argument(
        "--no-reset",
        action="store_false",
        dest="reset",
        help="Não remove os dados existentes, apenas adiciona os dados que faltarem.",
    )
    args = parser.parse_args()
    asyncio.run(seed_demo(reset=args.reset))


if __name__ == "__main__":
    main()
