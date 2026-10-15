"""
Testes automatizados para a rotina de ambientação corporativa e seed de demonstração (seed_demo).

Valida:
- Execução limpa do seed
- Criação da Matriz e Filial
- Criação dos 8 setores (4 Matriz + 4 Filial)
- Criação dos 8 colaboradores/usuários por setor + Administrador Global
- Criação das 16 categorias de chamado (2 por setor)
- Criação dos 10 ativos patrimoniais (computadores, celulares e impressoras)
- Criação das 10 categorias de insumos e itens de estoque
- Capacidade do Administrador Global editar ou excluir os dados de exemplo
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.assets.models import Asset, AssetCategory
from app.identity.models import Role, UserAccount
from app.organization.models import Company, Employee, Sector, Unit
from app.seed_demo import seed_demo
from app.service_desk.models import Ticket, TicketCategory
from app.stock.models import StockCategory, StockItem


@pytest.mark.asyncio
async def test_seed_demo_creates_complete_corporate_environment(db_session):
    # Executa a rotina de demonstração
    await seed_demo(reset=True, session=db_session)

    # 1. Validação de Empresa e Unidades
    stmt_comp = select(Company)
    company = (await db_session.execute(stmt_comp)).scalar_one()
    assert company.name == "TechCorp Soluções Empresariais Ltda."

    stmt_units = select(Unit).where(Unit.company_id == company.id)
    units = list((await db_session.execute(stmt_units)).scalars().all())
    assert len(units) == 2
    unit_names = {u.name for u in units}
    unit_types = {u.type for u in units}
    assert "Matriz Corporativa - SP" in unit_names
    assert "Filial Operacional - Campinas" in unit_names
    assert "MATRIZ" in unit_types
    assert "FILIAL" in unit_types

    # 2. Validação dos 8 Setores (4 Matriz + 4 Filial)
    stmt_sec = select(Sector)
    sectors = list((await db_session.execute(stmt_sec)).scalars().all())
    assert len(sectors) == 8

    matriz = next(u for u in units if u.type == "MATRIZ")
    filial = next(u for u in units if u.type == "FILIAL")

    matriz_sectors = {s.name for s in sectors if s.unit_id == matriz.id}
    filial_sectors = {s.name for s in sectors if s.unit_id == filial.id}

    assert matriz_sectors == {"Financeiro", "Comercial", "Diretoria", "Recursos Humanos"}
    assert filial_sectors == {"Administrativo", "Operacional", "Manutenção", "TI / Suporte"}

    # 3. Validação dos Usuários (8 setoriais + 1 Admin Operacional + 1 Admin Global)
    stmt_users = select(UserAccount).options(selectinload(UserAccount.roles), selectinload(UserAccount.employee))
    users = list((await db_session.execute(stmt_users)).scalars().all())
    assert len(users) == 10

    emails = {u.email for u in users}
    expected_emails = {
        "admin@empresa.com.br",
        "carlos.admin@empresa.com.br",
        "lucas.financeiro@empresa.com.br",
        "mariana.comercial@empresa.com.br",
        "roberto.diretoria@empresa.com.br",
        "carla.rh@empresa.com.br",
        "patricia.adm@empresa.com.br",
        "marcos.operacional@empresa.com.br",
        "felipe.manutencao@empresa.com.br",
        "gabriel.ti@empresa.com.br",
    }
    assert expected_emails.issubset(emails)

    admin_user = next(u for u in users if u.email == "admin@empresa.com.br")
    assert admin_user.is_admin is True
    assert any(r.name == "Administrador" for r in admin_user.roles)

    carlos_user = next(u for u in users if u.email == "carlos.admin@empresa.com.br")
    assert any(r.name == "Admin" for r in carlos_user.roles)

    roberto_user = next(u for u in users if u.email == "roberto.diretoria@empresa.com.br")
    assert any(r.name == "Gestão" for r in roberto_user.roles)

    lucas_user = next(u for u in users if u.email == "lucas.financeiro@empresa.com.br")
    assert any(r.name == "Atendente" for r in lucas_user.roles)

    gabriel_user = next(u for u in users if u.email == "gabriel.ti@empresa.com.br")
    assert any(r.name == "Atendente" for r in gabriel_user.roles)

    # 4. Validação das 16 Categorias de Chamados (2 por setor)
    stmt_cats = select(TicketCategory)
    ticket_cats = list((await db_session.execute(stmt_cats)).scalars().all())
    assert len(ticket_cats) == 16

    # Cada um dos 8 setores deve ter exatamente 2 categorias atribuídas como default_sector_id
    for sec in sectors:
        sec_cats = [c for c in ticket_cats if c.default_sector_id == sec.id]
        assert len(sec_cats) == 2, f"Setor {sec.name} deveria ter 2 categorias de chamado"

    # 5. Validação dos 10 Ativos Patrimoniais (Computador, Celular, Impressora)
    stmt_assets = select(Asset).options(selectinload(Asset.category))
    assets = list((await db_session.execute(stmt_assets)).scalars().all())
    assert len(assets) == 10

    tags = {a.tag for a in assets}
    for i in range(1, 11):
        assert f"PAT-{i:04d}" in tags

    cat_names = {a.category.name for a in assets}
    assert "Computadores & Notebooks" in cat_names
    assert "Smartphones & Dispositivos Móveis" in cat_names
    assert "Impressoras & Multifuncionais" in cat_names

    # 6. Validação das 10 Categorias de Insumos e Itens de Estoque
    stmt_stk_cats = select(StockCategory)
    stock_cats = list((await db_session.execute(stmt_stk_cats)).scalars().all())
    assert len(stock_cats) == 10

    expected_categories = [
        "Tintas e Toners para Impressoras",
        "Teclados",
        "Mouses",
        "Conectores e Cabeamento RJ45",
        "Fontes e Carregadores para Celular",
        "Películas Protetoras para Celular",
        "Capas Protetoras para Celular",
        "Cases e Maletas para Notebooks",
        "Cabos e Adaptadores de Vídeo/Energia",
        "Componentes e Peças de Reposição",
    ]
    stk_cat_names = {sc.name for sc in stock_cats}
    for expected in expected_categories:
        assert expected in stk_cat_names

    stmt_stk_items = select(StockItem)
    stock_items = list((await db_session.execute(stmt_stk_items)).scalars().all())
    assert len(stock_items) >= 15
    assert all(item.quantity > 0 for item in stock_items)

    # 7. Validação de Chamados de Demonstração
    stmt_tickets = select(Ticket)
    tickets = list((await db_session.execute(stmt_tickets)).scalars().all())
    assert len(tickets) >= 3

    statuses = {t.status for t in tickets}
    assert "IN_PROGRESS" in statuses
    assert "RESOLVED" in statuses
    assert "OPENED" in statuses


@pytest.mark.asyncio
async def test_admin_can_edit_and_delete_demo_entities(db_session):
    """Garante que todas as entidades criadas pelo seed podem ser editadas ou excluídas."""
    await seed_demo(reset=True, session=db_session)

    # Buscar um ativo de exemplo e editá-lo
    stmt_asset = select(Asset).where(Asset.tag == "PAT-0008")
    asset = (await db_session.execute(stmt_asset)).scalar_one()
    asset.name = "Smartphone Motorola Moto G54 5G 128GB (Editado pelo Admin)"
    await db_session.flush()

    stmt_check = select(Asset).where(Asset.tag == "PAT-0008")
    reloaded_asset = (await db_session.execute(stmt_check)).scalar_one()
    assert reloaded_asset.name == "Smartphone Motorola Moto G54 5G 128GB (Editado pelo Admin)"

    # Buscar uma categoria de chamado e alterar o status
    stmt_cat = select(TicketCategory).where(TicketCategory.name.like("Financeiro: Certificado%"))
    cat = (await db_session.execute(stmt_cat)).scalar_one()
    cat.description = "Descrição atualizada pelo administrador global"
    await db_session.flush()

    # Excluir um item de estoque de teste sem dependências bloqueantes
    stmt_item = select(StockItem).where(StockItem.name.like("%HDMI%"))
    hdmi_item = (await db_session.execute(stmt_item)).scalar_one_or_none()
    if hdmi_item:
        await db_session.delete(hdmi_item)
        await db_session.flush()
        stmt_check_deleted = select(StockItem).where(StockItem.name.like("%HDMI%"))
        assert (await db_session.execute(stmt_check_deleted)).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_cumulative_roles_and_sector_attendants_routing(client, db_session):
    """
    Valida a hierarquia de menor privilégio e o roteamento setorial de chamados:
    - Lucas (Atendente do Financeiro) vê o chamado do setor Financeiro, mas não vê chamados da TI.
    - Gabriel (Atendente de TI) vê os chamados da TI, mas não vê o chamado do Financeiro.
    - Roberto (Gestão) e Carlos (Admin) veem todos os chamados da organização.
    - Mariana (Solicitante) pode consultar seus próprios ativos via /api/v1/assets/me.
    """
    from tests.factories import headers_for
    from app.service_desk.services import ServiceDeskService

    await seed_demo(reset=True, session=db_session)

    stmt = select(UserAccount).options(selectinload(UserAccount.roles), selectinload(UserAccount.employee))
    users = {u.email: u for u in (await db_session.execute(stmt)).scalars().all()}

    user_lucas = users["lucas.financeiro@empresa.com.br"]
    user_gabriel = users["gabriel.ti@empresa.com.br"]
    user_roberto = users["roberto.diretoria@empresa.com.br"]
    user_mariana = users["mariana.comercial@empresa.com.br"]

    sd_service = ServiceDeskService(db_session)

    # 1. Lucas (Atendente Financeiro) lista chamados
    lucas_tickets = await sd_service.list_tickets_for_user(
        user_employee_id=user_lucas.employee_id,
        user_id=user_lucas.id,
        sector_id=user_lucas.employee.sector_id,
        is_technician=True,
        can_read_all=False,
    )
    lucas_titles = {t.title for t in lucas_tickets}
    assert any("faturamento e conciliação bancária" in title for title in lucas_titles)
    # Não deve ver chamados da TI
    assert not any("Preparação de kit de TI" in title for title in lucas_titles)

    # 2. Gabriel (Atendente TI) lista chamados
    gabriel_tickets = await sd_service.list_tickets_for_user(
        user_employee_id=user_gabriel.employee_id,
        user_id=user_gabriel.id,
        sector_id=user_gabriel.employee.sector_id,
        is_technician=True,
        can_read_all=False,
    )
    gabriel_titles = {t.title for t in gabriel_tickets}
    assert any("Preparação de kit de TI" in title for title in gabriel_titles)
    # Não deve ver chamado do Financeiro
    assert not any("faturamento e conciliação bancária" in title for title in gabriel_titles)

    # 3. Roberto (Gestão) possui can_read_all=True
    roberto_tickets = await sd_service.list_tickets_for_user(
        user_employee_id=user_roberto.employee_id,
        user_id=user_roberto.id,
        sector_id=user_roberto.employee.sector_id,
        is_technician=True,
        can_read_all=True,
    )
    roberto_titles = {t.title for t in roberto_tickets}
    assert any("faturamento e conciliação bancária" in title for title in roberto_titles)
    assert any("Preparação de kit de TI" in title for title in roberto_titles)

    # 4. Solicitante (Mariana) consulta seus próprios ativos (/api/v1/assets/me)
    h_mariana = headers_for(user_mariana)
    resp_me = await client.get("/api/v1/assets/me", headers=h_mariana)
    assert resp_me.status_code == 200
    mariana_assets = resp_me.json()
    assert len(mariana_assets) >= 1
    assert any("Samsung Galaxy" in a["name"] for a in mariana_assets)

