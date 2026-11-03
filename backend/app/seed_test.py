"""
Módulo de Carga para Base de Testes e Homologação (QA / Staging) — seed_test.py

Gera uma base de testes realista, isolada e com cenários de borda para homologação:
- 1 Empresa de Teste ("Empresa de Homologação & Testes S.A.")
- 2 Unidades (Matriz e Filial)
- 6 Setores (TI, Suporte N1, Almoxarifado, RH, Comercial, Operações)
- 7 Usuários e Colaboradores com perfis distintos (Superadmin, N1, N2, Almoxarife, Gestão, Solicitantes)
- Senha unificada para homologação: Teste@2026
- Ativos em múltiplos estados (IN_USE, IN_STOCK, MAINTENANCE, DECOMMISSIONED)
- Insumos de estoque com cenários de alerta (Estoque Normal, Baixo e Crítico/Zerado)
- Chamados em diversos estados (OPENED, IN_PROGRESS, RESOLVED, com SLA estourado e com ativo vinculado)
- Movimentações patrimoniais e materiais consumidos

Pode ser executado com a flag --reset para recriar os dados com segurança.
"""

import argparse
import asyncio
from datetime import date, datetime, timedelta, timezone
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.assets.models import Asset, AssetCategory, AssetStatus
from app.audit.models import AuditLog
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


TEST_PASSWORD = "Teste@2026"



async def clean_test_database(session: AsyncSession) -> None:
    """Limpa tabelas de teste e transações de forma controlada."""
    print("--> [QA/Test] Limpando dados de teste existentes...")

    from app.notifications.models import ConversationSession, Delivery, DeliveryAttempt, DomainEvent, InboundMessage

    for model in (DeliveryAttempt, Delivery, DomainEvent, InboundMessage, ConversationSession):
        await session.execute(delete(model))
    await session.execute(delete(Notification))
    await session.execute(delete(AuditLog))
    await session.execute(delete(Attachment))
    await session.execute(delete(InventoryAuditItem))
    await session.execute(delete(InventoryAudit))

    await session.execute(delete(ticket_assets))
    await session.execute(delete(TicketInteraction))
    await session.execute(delete(TicketMaterial))
    await session.execute(delete(Ticket))
    await session.execute(delete(TicketCategory))

    await session.execute(delete(AssetMovement))
    await session.execute(delete(Asset))
    await session.execute(delete(AssetCategory))

    await session.execute(delete(StockMovement))
    await session.execute(delete(StockItem))
    await session.execute(delete(StockCategory))

    await session.execute(delete(user_role_association))
    await session.execute(delete(UserAccount))
    await session.execute(delete(Employee))

    await session.execute(delete(Sector))
    await session.execute(delete(Unit))
    await session.execute(delete(Company))

    await session.flush()
    print("--> [QA/Test] Limpeza concluída com sucesso!")


async def sync_roles_and_permissions(session: AsyncSession) -> dict[str, Role]:
    """Garante todas as permissões e perfis estruturados."""
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

    atendente_codes = solicitante_codes + [
        "service_desk.tickets.manage",
        "service_desk.interactions.internal",
        "assets.read",
        "stock.read",
    ]
    atendente_role = await _sync_role(
        "Atendente",
        "Atendimento e triagem de chamados do seu setor/unidade, notas técnicas internas e consulta a estoque/ativos.",
        atendente_codes,
    )

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

    admin_role = await _sync_role(
        "Administrador",
        "Acesso total irrestrito ao sistema, configurações globais e infraestrutura.",
        None,
    )

    return {
        "Administrador": admin_role,
        "Gestão": gestao_role,
        "Atendente": atendente_role,
        "Solicitante": solicitante_role,
    }


async def seed_test(reset: bool = False) -> None:
    """Executa a carga da base de testes e homologação."""
    print("=================================================================")
    print("  CARGA DA BASE DE TESTES E HOMOLOGAÇÃO (QA / STAGING)")
    print("=================================================================")

    async with AsyncSessionLocal() as session:
        if reset:
            await clean_test_database(session)

        # 1. Permissões e Perfis
        roles = await sync_roles_and_permissions(session)
        print("--> 1. Permissões e perfis sincronizados.")

        # 2. Empresa de Teste
        stmt = select(Company).where(Company.cnpj == "11.222.333/0001-44")
        company = (await session.execute(stmt)).scalar_one_or_none()
        if not company:
            company = Company(
                name="Empresa de Homologação & Testes S.A.",
                cnpj="11.222.333/0001-44",
                is_demo=False,
            )
            session.add(company)
            await session.flush()
            print(f"--> 2. Empresa criada: {company.name}")
        else:
            print(f"--> 2. Empresa já existente: {company.name}")

        # 3. Unidades
        async def _get_or_create_unit(code: str, name: str, utype: str) -> Unit:
            stmt = select(Unit).where(Unit.code == code)
            u = (await session.execute(stmt)).scalar_one_or_none()
            if not u:
                u = Unit(company_id=company.id, code=code, name=name, type=utype, is_demo=False)
                session.add(u)
                await session.flush()
            return u

        unit_matriz = await _get_or_create_unit("HOM-MATRIZ", "Matriz - Centro de Testes", "MATRIZ")
        unit_filial = await _get_or_create_unit("HOM-FILIAL", "Filial Regional - Homologação", "FILIAL")
        print("--> 3. Unidades operacionais sincronizadas.")

        # 4. Setores
        async def _get_or_create_sector(unit: Unit, code: str, name: str) -> Sector:
            stmt = select(Sector).where(Sector.code == code)
            s = (await session.execute(stmt)).scalar_one_or_none()
            if not s:
                s = Sector(unit_id=unit.id, code=code, name=name, is_demo=False)
                session.add(s)
                await session.flush()
            return s

        sec_ti = await _get_or_create_sector(unit_matriz, "HOM-TI", "Tecnologia da Informação")
        sec_sup = await _get_or_create_sector(unit_matriz, "HOM-SUP", "Suporte Técnico N1")
        sec_alm = await _get_or_create_sector(unit_matriz, "HOM-ALM", "Almoxarifado & Estoque")
        sec_rh = await _get_or_create_sector(unit_matriz, "HOM-RH", "Recursos Humanos")
        sec_com = await _get_or_create_sector(unit_filial, "HOM-COM", "Comercial & Vendas")
        sec_ops = await _get_or_create_sector(unit_filial, "HOM-OPS", "Operações & Logística")
        print("--> 4. Setores departamentais sincronizados.")

        # 5. Colaboradores e Contas de Usuário (Cenários de Teste)
        pwd_hash = hash_password(TEST_PASSWORD)

        users_specs = [
            {
                "email": "admin@teste.local",
                "name": "Administrador de Testes",
                "reg": "TEST-001",
                "position": "Superadmin de TI",
                "unit": unit_matriz,
                "sector": sec_ti,
                "role": roles["Administrador"],
                "is_admin": True,
            },
            {
                "email": "tecnico.n1@teste.local",
                "name": "Carlos Suporte N1",
                "reg": "TEST-002",
                "position": "Técnico de Suporte N1",
                "unit": unit_matriz,
                "sector": sec_sup,
                "role": roles["Atendente"],
                "is_admin": False,
            },
            {
                "email": "tecnico.n2@teste.local",
                "name": "Juliana Especialista N2",
                "reg": "TEST-003",
                "position": "Analista de Infraestrutura N2",
                "unit": unit_matriz,
                "sector": sec_ti,
                "role": roles["Administrador"],
                "is_admin": False,
            },
            {
                "email": "almoxarife@teste.local",
                "name": "Roberto Almoxarife",
                "reg": "TEST-004",
                "position": "Encarregado de Estoque",
                "unit": unit_matriz,
                "sector": sec_alm,
                "role": roles["Administrador"],
                "is_admin": False,
            },
            {
                "email": "gestor@teste.local",
                "name": "Mariana Gestora",
                "reg": "TEST-005",
                "position": "Gerente de Operações",
                "unit": unit_filial,
                "sector": sec_ops,
                "role": roles["Gestão"],
                "is_admin": False,
            },
            {
                "email": "solicitante@teste.local",
                "name": "Lucas Solicitante",
                "reg": "TEST-006",
                "position": "Executivo de Vendas",
                "unit": unit_filial,
                "sector": sec_com,
                "role": roles["Solicitante"],
                "is_admin": False,
            },
            {
                "email": "solicitante.rh@teste.local",
                "name": "Fernanda Recursos Humanos",
                "reg": "TEST-007",
                "position": "Analista de RH",
                "unit": unit_matriz,
                "sector": sec_rh,
                "role": roles["Solicitante"],
                "is_admin": False,
            },
        ]

        created_employees: dict[str, Employee] = {}
        created_users: dict[str, UserAccount] = {}

        for idx, us in enumerate(users_specs, 1):
            phone_num = f"+558499999{idx:04d}"
            stmt_e = select(Employee).where(Employee.registration_number == us["reg"])
            emp = (await session.execute(stmt_e)).scalar_one_or_none()
            if not emp:
                emp = Employee(
                    name=us["name"],
                    registration_number=us["reg"],
                    position=us["position"],
                    phone=phone_num,
                    unit_id=us["unit"].id,
                    sector_id=us["sector"].id,
                    status="ATIVO",
                    is_demo=False,
                )
                session.add(emp)
                await session.flush()
            else:
                emp.phone = phone_num
            created_employees[us["email"]] = emp

            stmt_u = select(UserAccount).options(selectinload(UserAccount.roles)).where(UserAccount.email == us["email"])
            usr = (await session.execute(stmt_u)).scalar_one_or_none()
            if not usr:
                usr = UserAccount(
                    employee_id=emp.id,
                    email=us["email"],
                    hashed_password=pwd_hash,
                    must_change_password=False,
                    is_admin=us["is_admin"],
                    is_demo=False,
                )
                usr.roles = [us["role"]]
                session.add(usr)
                await session.flush()
            created_users[us["email"]] = usr

        print(f"--> 5. Contas de usuário criadas/sincronizadas: {len(created_users)} perfis (Senha: {TEST_PASSWORD}).")

        # 6. Categorias de Ativos
        asset_cat_specs = [
            ("Notebooks & Laptops", "Notebooks corporativos e computadores portáteis"),
            ("Desktops & Workstations", "Estações de trabalho e computadores fixos"),
            ("Monitores & Telas", "Monitores e displays profissionais"),
            ("Equipamentos de Rede", "Switches, roteadores e access points"),
            ("Smartphones & Tablets", "Dispositivos móveis e celulares funcionais"),
        ]
        created_asset_cats: dict[str, AssetCategory] = {}
        for cname, cdesc in asset_cat_specs:
            stmt_ac = select(AssetCategory).where(AssetCategory.name == cname)
            acat = (await session.execute(stmt_ac)).scalar_one_or_none()
            if not acat:
                acat = AssetCategory(name=cname, description=cdesc, spec_schema={})
                session.add(acat)
                await session.flush()
            created_asset_cats[cname] = acat

        # 7. Ativos Patrimoniais com Vários Estados
        emp_lucas = created_employees["solicitante@teste.local"]
        emp_carlos = created_employees["tecnico.n1@teste.local"]

        assets_specs = [
            {
                "tag": "NOTE-TEST-001",
                "name": "Dell Latitude 5420 i7 16GB",
                "cat": "Notebooks & Laptops",
                "status": AssetStatus.IN_USE.value,
                "unit": unit_matriz,
                "emp": emp_lucas,
                "notes": "Equipamento principal de trabalho alocado.",
            },
            {
                "tag": "NOTE-TEST-002",
                "name": "Lenovo ThinkPad T14 AMD 16GB",
                "cat": "Notebooks & Laptops",
                "status": AssetStatus.IN_STOCK.value,
                "unit": unit_matriz,
                "emp": None,
                "notes": "Equipamento reserva pronto no estoque de TI.",
            },
            {
                "tag": "NOTE-TEST-003",
                "name": "Apple MacBook Pro 14 M2 16GB",
                "cat": "Notebooks & Laptops",
                "status": AssetStatus.MAINTENANCE.value,
                "unit": unit_matriz,
                "emp": None,
                "notes": "Enviado para reparo de tela na assistência autorizada.",
            },
            {
                "tag": "NOTE-TEST-004",
                "name": "Dell Inspiron 15 Antigo",
                "cat": "Notebooks & Laptops",
                "status": AssetStatus.DECOMMISSIONED.value,
                "unit": unit_matriz,
                "emp": None,
                "notes": "Baixado por obsolescência técnica.",
            },
            {
                "tag": "SW-TEST-001",
                "name": "Switch Cisco SG350-28 Gigabit",
                "cat": "Equipamentos de Rede",
                "status": AssetStatus.IN_USE.value,
                "unit": unit_matriz,
                "emp": None,
                "notes": "Switch core do rack principal da Matriz.",
            },
            {
                "tag": "MON-TEST-001",
                "name": "Monitor Dell 27 4K U2723QE",
                "cat": "Monitores & Telas",
                "status": AssetStatus.IN_USE.value,
                "unit": unit_matriz,
                "emp": emp_carlos,
                "notes": "Monitor alocado na bancada de atendimento.",
            },
            {
                "tag": "CEL-TEST-001",
                "name": "Samsung Galaxy S23 128GB",
                "cat": "Smartphones & Tablets",
                "status": AssetStatus.IN_USE.value,
                "unit": unit_filial,
                "emp": emp_lucas,
                "notes": "Aparelho celular corporativo para vendas externas.",
            },
        ]

        created_assets: dict[str, Asset] = {}
        for aspec in assets_specs:
            stmt_a = select(Asset).where(Asset.tag == aspec["tag"])
            ast = (await session.execute(stmt_a)).scalar_one_or_none()
            if not ast:
                ast = Asset(
                    tag=aspec["tag"],
                    name=aspec["name"],
                    category_id=created_asset_cats[aspec["cat"]].id,
                    status=aspec["status"],
                    unit_id=aspec["unit"].id,
                    employee_id=aspec["emp"].id if aspec["emp"] else None,
                    purchase_date=date.today() - timedelta(days=180),
                    warranty_expires=date.today() + timedelta(days=185),
                    notes=aspec["notes"],
                    technical_specs={},
                    is_demo=False,
                )
                session.add(ast)
                await session.flush()
            created_assets[aspec["tag"]] = ast
        print(f"--> 6. Ativos patrimoniais criados: {len(created_assets)} equipamentos com estados diversos.")

        # 8. Categorias de Estoque e Itens com Cenários de Alerta
        stk_cat_specs = [
            ("Periféricos & Acessórios", "Mouses, teclados e headsets"),
            ("Cabos & Adaptadores", "Cabos de rede, HDMI e adaptadores"),
            ("Toners & Cartuchos", "Suprimentos para impressoras"),
            ("Componentes & Peças", "SSDs, memórias e placas"),
        ]
        created_stk_cats: dict[str, StockCategory] = {}
        for sname, sdesc in stk_cat_specs:
            stmt_sc = select(StockCategory).where(StockCategory.name == sname)
            scat = (await session.execute(stmt_sc)).scalar_one_or_none()
            if not scat:
                scat = StockCategory(name=sname, description=sdesc, spec_schema={})
                session.add(scat)
                await session.flush()
            created_stk_cats[sname] = scat

        stock_specs = [
            ("Mouse USB Óptico Dell MS116", "Periféricos & Acessórios", 15, 5),   # Normal
            ("Teclado USB ABNT2", "Periféricos & Acessórios", 8, 5),             # Normal
            ("Cabo HDMI 2.0 Blindado 2m", "Cabos & Adaptadores", 2, 10),         # Baixo / Alerta
            ("Toner HP Neverstop Laser W1105A", "Toners & Cartuchos", 0, 3),      # Crítico / Zerado
            ("SSD NVMe Kingston 500GB", "Componentes & Peças", 5, 2),            # Normal
        ]
        created_stock_items: dict[str, StockItem] = {}
        for iname, icat, iqtd, imin in stock_specs:
            stmt_si = select(StockItem).where(StockItem.name == iname)
            sitem = (await session.execute(stmt_si)).scalar_one_or_none()
            if not sitem:
                sitem = StockItem(
                    name=iname,
                    category_id=created_stk_cats[icat].id,
                    unit_id=unit_matriz.id,
                    quantity=iqtd,
                    min_quantity=imin,
                    technical_specs={},
                    is_demo=False,
                )
                session.add(sitem)
                await session.flush()
            created_stock_items[iname] = sitem
        print(f"--> 7. Insumos de estoque criados: {len(created_stock_items)} itens com alertas simulados.")

        # 9. Categorias de Chamados
        ticket_cat_specs = [
            ("Falha em Hardware / Equipamento", "Problemas físicos em notebooks, monitores e periféricos"),
            ("Acesso a Sistemas & Credenciais", "Solicitação de login, permissões e resets de senha"),
            ("Suporte Geral & Dúvidas", "Dúvidas de utilização e pequenos ajustes de software"),
            ("Solicitação de Suprimentos & Periféricos", "Pedidos de mouses, cabos, toners e adaptadores"),
        ]
        created_ticket_cats: dict[str, TicketCategory] = {}
        for tcname, tcdesc in ticket_cat_specs:
            stmt_tc = select(TicketCategory).where(TicketCategory.name == tcname)
            tcat = (await session.execute(stmt_tc)).scalar_one_or_none()
            if not tcat:
                tcat = TicketCategory(
                    name=tcname,
                    description=tcdesc,
                    is_active=True,
                    default_sector_id=sec_ti.id,
                    form_schema=[
                        {"id": "descricao_detalhada", "label": "Descreva o problema ocorrido", "type": "textarea", "required": True},
                        {"id": "urgencia_operacional", "label": "Impacto na operação", "type": "select", "options": ["Baixo", "Médio", "Crítico"], "required": False},
                    ],
                )
                session.add(tcat)
                await session.flush()
            created_ticket_cats[tcname] = tcat

        # 10. Chamados de Teste (Cenários de Borda e Validação)
        user_carlos = created_users["tecnico.n1@teste.local"]
        user_juliana = created_users["tecnico.n2@teste.local"]
        emp_fernanda = created_employees["solicitante.rh@teste.local"]
        emp_mariana = created_employees["gestor@teste.local"]

        # Chamado 1: Em Atendimento + Ativo Vinculado (NOTE-TEST-001)
        stmt_t1 = select(Ticket).where(Ticket.title == "Notebook reiniciando sozinho em tela azul")
        t1 = (await session.execute(stmt_t1)).scalar_one_or_none()
        if not t1:
            t1 = Ticket(
                title="Notebook reiniciando sozinho em tela azul",
                description="O notebook apresenta tela azul após cerca de 20 minutos de uso contínuo da planilha.",
                priority="HIGH",
                status="IN_PROGRESS",
                category_id=created_ticket_cats["Falha em Hardware / Equipamento"].id,
                requester_id=emp_lucas.id,
                assignee_id=user_carlos.id,
                origin_unit_id=unit_filial.id,
                origin_sector_id=sec_com.id,
                responsible_sector_id=sec_ti.id,
                custom_fields={"urgencia_operacional": "Médio"},
                is_demo=False,
            )
            # Vincula o ativo NOTE-TEST-001
            t1.assets.append(created_assets["NOTE-TEST-001"])
            session.add(t1)
            await session.flush()

            # Adiciona interações
            it1 = TicketInteraction(
                ticket_id=t1.id,
                author_id=created_users["solicitante@teste.local"].id,
                message="O erro começou a ocorrer ontem à tarde durante reunião com cliente.",
                is_internal=False,
            )
            it2 = TicketInteraction(
                ticket_id=t1.id,
                author_id=user_carlos.id,
                message="Identificado erro de despejo de memória (kernel dump). Realizaremos teste de estresse da RAM.",
                is_internal=True,
            )
            session.add_all([it1, it2])
            await session.flush()

        # Chamado 2: Aberto / Não Atribuído
        stmt_t2 = select(Ticket).where(Ticket.title == "Liberação de acesso ao ERP Financeiro")
        t2 = (await session.execute(stmt_t2)).scalar_one_or_none()
        if not t2:
            t2 = Ticket(
                title="Liberação de acesso ao ERP Financeiro",
                description="Colaboradora recém-admitida no RH precisa de acesso ao módulo de folha de pagamento.",
                priority="MEDIUM",
                status="OPENED",
                category_id=created_ticket_cats["Acesso a Sistemas & Credenciais"].id,
                requester_id=emp_fernanda.id,
                assignee_id=None,
                origin_unit_id=unit_matriz.id,
                origin_sector_id=sec_rh.id,
                responsible_sector_id=sec_ti.id,
                custom_fields={},
                is_demo=False,
            )
            session.add(t2)
            await session.flush()

        # Chamado 3: Cenário de SLA Estourado (Criado há 5 dias)
        stmt_t3 = select(Ticket).where(Ticket.title == "Lentidão generalizada e oscilação de link na filial")
        t3 = (await session.execute(stmt_t3)).scalar_one_or_none()
        if not t3:
            t3 = Ticket(
                title="Lentidão generalizada e oscilação de link na filial",
                description="Link de contingência não assumiu após queda da fibra óptica principal na filial.",
                priority="CRITICAL",
                status="IN_PROGRESS",
                category_id=created_ticket_cats["Suporte Geral & Dúvidas"].id,
                requester_id=emp_mariana.id,
                assignee_id=user_juliana.id,
                origin_unit_id=unit_filial.id,
                origin_sector_id=sec_ops.id,
                responsible_sector_id=sec_ti.id,
                custom_fields={"urgencia_operacional": "Crítico"},
                is_demo=False,
            )
            session.add(t3)
            await session.flush()

        # Chamado 4: Resolvido com Material Consumido
        stmt_t4 = select(Ticket).where(Ticket.title == "Substituição de mouse com falha de duplo clique")
        t4 = (await session.execute(stmt_t4)).scalar_one_or_none()
        if not t4:
            t4 = Ticket(
                title="Substituição de mouse com falha de duplo clique",
                description="Mouse óptico antigo apresenta falha intermitente no botão esquerdo.",
                priority="LOW",
                status="RESOLVED",
                category_id=created_ticket_cats["Solicitação de Suprimentos & Periféricos"].id,
                requester_id=emp_lucas.id,
                assignee_id=user_carlos.id,
                origin_unit_id=unit_filial.id,
                origin_sector_id=sec_com.id,
                responsible_sector_id=sec_ti.id,
                custom_fields={},
                is_demo=False,
            )
            session.add(t4)
            await session.flush()

            mat = TicketMaterial(
                ticket_id=t4.id,
                stock_item_id=created_stock_items["Mouse USB Óptico Dell MS116"].id,
                quantity=1,
                author_id=user_carlos.id,
            )
            session.add(mat)
            await session.flush()

        print("--> 8. Chamados com múltiplos estados, ativos vinculados e materiais sincronizados.")

        # 11. Movimentações Patrimoniais
        user_admin = created_users["admin@teste.local"]
        stmt_m1 = select(AssetMovement).where(AssetMovement.asset_id == created_assets["NOTE-TEST-001"].id)
        if not (await session.execute(stmt_m1)).first():
            m1 = AssetMovement(
                asset_id=created_assets["NOTE-TEST-001"].id,
                movement_type=MovementType.ASSIGNMENT.value,
                from_unit_id=unit_matriz.id,
                to_unit_id=unit_filial.id,
                to_employee_id=emp_lucas.id,
                status_from=AssetStatus.IN_STOCK.value,
                status_to=AssetStatus.IN_USE.value,
                author_id=user_admin.id,
                notes="Entrega formal do notebook com termo de responsabilidade assinado.",
            )
            session.add(m1)

        stmt_m2 = select(AssetMovement).where(AssetMovement.asset_id == created_assets["NOTE-TEST-003"].id)
        if not (await session.execute(stmt_m2)).first():
            m2 = AssetMovement(
                asset_id=created_assets["NOTE-TEST-003"].id,
                movement_type=MovementType.MAINTENANCE.value,
                from_unit_id=unit_matriz.id,
                to_unit_id=unit_matriz.id,
                status_from=AssetStatus.IN_STOCK.value,
                status_to=AssetStatus.MAINTENANCE.value,
                author_id=user_admin.id,
                notes="Envio para reparo físico na assistência autorizada.",
            )
            session.add(m2)

        # 10. Auditoria Periódica de Inventário
        from app.inventory_audit.models import InventoryAudit
        from app.inventory_audit.repository import InventoryAuditRepository
        from app.inventory_audit.service import InventoryAuditService
        from app.inventory_audit.schemas import InventoryAuditCreate

        audit_name = "Auditoria Periódica de Homologação - Matriz"
        stmt_aud = select(InventoryAudit).where(InventoryAudit.name == audit_name)
        existing_audit = (await session.execute(stmt_aud)).scalar_one_or_none()
        if not existing_audit:
            audit_repo = InventoryAuditRepository(session)
            audit_service = InventoryAuditService(audit_repo)
            created_audit = await audit_service.create_audit(
                InventoryAuditCreate(
                    name=audit_name,
                    unit_id=unit_matriz.id,
                    auditor_id=user_admin.id,
                )
            )
            print(f"--> 10. Auditoria de Inventário criada com {len(created_audit.items)} itens conferidos.")

        await session.commit()
        print("=================================================================")
        print("  BASE DE TESTES E HOMOLOGAÇÃO INICIALIZADA COM SUCESSO!")
        print("=================================================================")
        print(f"  Usuário Admin:        admin@teste.local       (Senha: {TEST_PASSWORD})")
        print(f"  Técnico N1:           tecnico.n1@teste.local  (Senha: {TEST_PASSWORD})")
        print(f"  Especialista N2:      tecnico.n2@teste.local  (Senha: {TEST_PASSWORD})")
        print(f"  Almoxarife:           almoxarife@teste.local  (Senha: {TEST_PASSWORD})")
        print(f"  Gestor de Operações:  gestor@teste.local      (Senha: {TEST_PASSWORD})")
        print(f"  Solicitante Comercial:solicitante@teste.local (Senha: {TEST_PASSWORD})")
        print("=================================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inicializa a base de testes e homologação (QA/Staging)")
    parser.add_argument("--reset", action="store_true", help="Limpa os dados anteriores antes de semear")
    args = parser.parse_args()

    asyncio.run(seed_test(reset=args.reset))
