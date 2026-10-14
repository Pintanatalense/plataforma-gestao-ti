"""
Teste E2E de Ciclo de Vida Completo da Plataforma de Gestão de TI:
- Setup da Empresa, Unidade e Setor
- Cadastro de Colaborador e Técnico de TI
- Cadastro e Movimentação de Ativo (Patrimônio)
- Cadastro de Insumo em Estoque
- Abertura de Chamado vinculando o Ativo pelo Colaborador
- Atendimento do Técnico (Notas Internas e Mensagens Públicas)
- Consumo de Insumo do Estoque no Chamado
- Verificação da Baixa Automática do Estoque
- Encerramento do Chamado
"""

import io
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import make_auth_headers

from app.core.security import hash_password
from app.organization.models import Company, Unit, Sector, Employee
from app.identity.models import UserAccount, Role, Permission
from app.assets.models import AssetCategory, Asset, AssetStatus
from app.stock.models import StockItem
from app.service_desk.models import Ticket, TicketCategory
from app.notifications.models import Notification

pytestmark = pytest.mark.asyncio


async def test_full_platform_lifecycle_e2e(client: AsyncClient, db_session: AsyncSession):
    # -------------------------------------------------------------------------
    # 1. SETUP ORGANIZACIONAL (Admin)
    # -------------------------------------------------------------------------
    company = Company(name="TechCorp Soluções", cnpj="12.345.678/0001-90")
    db_session.add(company)
    await db_session.flush()

    unit = Unit(name="Matriz SP", code="SP01", company_id=company.id)
    db_session.add(unit)
    await db_session.flush()

    sector_ti = Sector(name="Tecnologia da Informação", code="TI", unit_id=unit.id)
    sector_rh = Sector(name="Recursos Humanos", code="RH", unit_id=unit.id)
    db_session.add_all([sector_ti, sector_rh])
    await db_session.flush()

    # Colaborador solicitante (RH)
    emp_colaborador = Employee(
        name="Ana Silva",
        registration_number="RH001",
        position="Analista de RH",
        unit_id=unit.id,
        sector_id=sector_rh.id,
    )
    # Técnico de suporte (TI)
    emp_tecnico = Employee(
        name="Carlos Técnico",
        registration_number="TI002",
        position="Suporte N2",
        unit_id=unit.id,
        sector_id=sector_ti.id,
    )
    db_session.add_all([emp_colaborador, emp_tecnico])
    await db_session.flush()

    # Usuários no sistema
    user_colab = UserAccount(
        email="ana.silva@techcorp.com",
        hashed_password=hash_password("senha123"),
        employee_id=emp_colaborador.id,
        is_admin=False,
    )
    user_tec = UserAccount(
        email="carlos.ti@techcorp.com",
        hashed_password=hash_password("senha123"),
        employee_id=emp_tecnico.id,
        is_admin=True,  # Privilégios técnicos / admin
    )
    db_session.add_all([user_colab, user_tec])
    await db_session.flush()

    # Categoria de chamado
    cat_hardware = TicketCategory(name="Falha de Hardware", default_sector_id=sector_ti.id)
    db_session.add(cat_hardware)
    await db_session.flush()

    # -------------------------------------------------------------------------
    # 2. GESTÃO DE ATIVOS (Cadastrar Notebook e Atribuir à Ana)
    # -------------------------------------------------------------------------
    asset_cat = AssetCategory(
        name="Notebooks",
        spec_schema={"ram": "string", "storage": "string"}
    )
    db_session.add(asset_cat)
    await db_session.flush()

    notebook = Asset(
        tag="PAT-NOTE-001",
        name="Dell Latitude 5420",
        category_id=asset_cat.id,
        unit_id=unit.id,
        employee_id=emp_colaborador.id,
        status=AssetStatus.IN_USE.value,
        technical_specs={"ram": "16GB", "storage": "512GB SSD"}
    )
    db_session.add(notebook)
    await db_session.flush()

    # -------------------------------------------------------------------------
    # 3. GESTÃO DE ESTOQUE (Cadastrar Cabo de Rede com 10 unidades)
    # -------------------------------------------------------------------------
    stock_cabo = StockItem(
        name="Patch Cord Cat6 2m",
        description="Cabo de rede azul",
        unit_id=unit.id,
        quantity=10,
        min_quantity=3
    )
    db_session.add(stock_cabo)
    await db_session.commit()

    headers_colab = make_auth_headers(user_id=str(user_colab.id), is_admin=False)
    headers_tec = make_auth_headers(user_id=str(user_tec.id), is_admin=True)

    # -------------------------------------------------------------------------
    # 4. COLABORADORA ABRE CHAMADO VINCULANDO SEU NOTEBOOK
    # -------------------------------------------------------------------------
    ticket_payload = {
        "title": "Notebook não conecta à rede da sala 104",
        "description": "Ao ligar o cabo no notebook, não há sinal de conexão de rede.",
        "priority": "HIGH",
        "category_id": str(cat_hardware.id),
        "asset_ids": [str(notebook.id)],
    }
    resp_ticket = await client.post("/api/v1/tickets", json=ticket_payload, headers=headers_colab)
    assert resp_ticket.status_code == 201
    ticket_data = resp_ticket.json()
    ticket_id = ticket_data["id"]
    assert ticket_data["status"] == "OPENED"
    assert ticket_data["priority"] == "HIGH"

    # -------------------------------------------------------------------------
    # 5. TÉCNICO INICIA ATENDIMENTO E INTERAGE (Mensagem Pública + Nota Interna)
    # -------------------------------------------------------------------------
    # Atualiza status para IN_PROGRESS
    resp_patch = await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "IN_PROGRESS"},
        headers=headers_tec
    )
    assert resp_patch.status_code == 200
    assert resp_patch.json()["status"] == "IN_PROGRESS"

    # Nota interna confidencial do técnico
    resp_note = await client.post(
        f"/api/v1/tickets/{ticket_id}/interactions",
        json={"message": "Verifiquei que a trava do cabo do ponto RJ45 quebrou.", "is_internal": True},
        headers=headers_tec
    )
    assert resp_note.status_code == 201
    assert resp_note.json()["is_internal"] is True

    # Mensagem pública para a solicitante
    resp_pub = await client.post(
        f"/api/v1/tickets/{ticket_id}/interactions",
        json={"message": "Olá Ana, estou a caminho com um novo cabo de rede.", "is_internal": False},
        headers=headers_tec
    )
    assert resp_pub.status_code == 201
    assert resp_pub.json()["is_internal"] is False

    # Validação de segurança: Colaboradora NÃO pode ver a nota interna
    resp_view_colab = await client.get(f"/api/v1/tickets/{ticket_id}", headers=headers_colab)
    assert resp_view_colab.status_code == 200
    interactions_colab = resp_view_colab.json()["interactions"]
    for inter in interactions_colab:
        assert inter["is_internal"] is False, "Vazamento de nota interna para o solicitante!"

    # -------------------------------------------------------------------------
    # 6. ANEXO DE EVIDÊNCIA NO CHAMADO (Técnico anexa foto/laudo)
    # -------------------------------------------------------------------------
    file_content = b"Evidencia do cabo rompido na sala 104"
    files = {"file": ("cabo_defeituoso.txt", io.BytesIO(file_content), "text/plain")}
    data = {"entity_type": "TICKET", "entity_id": str(ticket_id)}
    resp_attach = await client.post("/api/v1/attachments", files=files, data=data, headers=headers_tec)
    assert resp_attach.status_code == 201
    attach_id = resp_attach.json()["id"]

    # Download do anexo pelo técnico
    resp_dl = await client.get(f"/api/v1/attachments/{attach_id}/download", headers=headers_tec)
    assert resp_dl.status_code == 200
    assert resp_dl.content == file_content

    # -------------------------------------------------------------------------
    # 7. TÉCNICO REGISTRA CONSUMO DE MATERIAL NO CHAMADO (Baixa de Estoque)
    # -------------------------------------------------------------------------
    material_payload = {
        "stock_item_id": str(stock_cabo.id),
        "quantity": 1
    }
    resp_material = await client.post(
        f"/api/v1/tickets/{ticket_id}/materials",
        json=material_payload,
        headers=headers_tec
    )
    assert resp_material.status_code == 201
    assert resp_material.json()["quantity"] == 1

    # Verifica se o saldo do estoque baixou de 10 para 9
    resp_stock = await client.get(f"/api/v1/stock/items/{stock_cabo.id}", headers=headers_tec)
    assert resp_stock.status_code == 200
    assert resp_stock.json()["quantity"] == 9, "Estoque não foi decrementado com o material do chamado!"

    # -------------------------------------------------------------------------
    # 8. ENCERRAMENTO DO CHAMADO E NOTIFICAÇÃO
    # -------------------------------------------------------------------------
    resp_close = await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "CLOSED"},
        headers=headers_tec
    )
    assert resp_close.status_code == 200
    assert resp_close.json()["status"] == "CLOSED"

    # Confere dados consolidados do chamado
    resp_final = await client.get(f"/api/v1/tickets/{ticket_id}", headers=headers_tec)
    assert resp_final.status_code == 200
    final_data = resp_final.json()
    assert len(final_data["interactions"]) == 2
    assert len(final_data["materials"]) == 1

    # Notificação do solicitante
    notif = Notification(
        user_id=user_colab.id,
        title="Chamado Concluído",
        message=f"Seu chamado #{ticket_id} foi atendido e finalizado.",
        type="INFO",
        is_read=False,
    )
    db_session.add(notif)
    await db_session.commit()

    resp_notif = await client.get("/api/v1/notifications", headers=headers_colab)
    assert resp_notif.status_code == 200
    notifs = resp_notif.json()
    assert any(n["id"] == str(notif.id) for n in notifs)

    # Marca notificação como lida
    resp_read = await client.post(f"/api/v1/notifications/{notif.id}/read", headers=headers_colab)
    assert resp_read.status_code == 200
    assert resp_read.json()["is_read"] is True

    # -------------------------------------------------------------------------
    # 9. BARREIRA RBAC E AUDITORIA
    # -------------------------------------------------------------------------
    # Colaboradora sem privilégios de auditoria é bloqueada (403)
    resp_audit_colab = await client.get("/api/v1/audit", headers=headers_colab)
    assert resp_audit_colab.status_code == 403

    # Admin tem acesso à trilha de auditoria
    resp_audit_admin = await client.get("/api/v1/audit", headers=headers_tec)
    assert resp_audit_admin.status_code == 200
    assert isinstance(resp_audit_admin.json(), list)


async def test_multi_profile_rbac_matrix_e2e(client: AsyncClient, db_session: AsyncSession):
    """
    Validação da Matriz de Perfis (RBAC) para os 4 perfis fundamentais:
    - Admin (Superusuário com acesso irrestrito)
    - Gestor (Acesso a relatórios, organização e ativos da sua unidade)
    - Técnico (Acesso a chamados, estoque e execução operacional)
    - Colaborador (Acesso restrito a autoatendimento / próprios chamados)
    """
    # 1. Setup básico
    company = Company(name="Corp Matriz", cnpj="99.888.777/0001-11")
    db_session.add(company)
    await db_session.flush()

    unit = Unit(name="Unidade Rio", code="RJ01", company_id=company.id)
    db_session.add(unit)
    await db_session.flush()

    sector = Sector(name="Operações", code="OPS", unit_id=unit.id)
    db_session.add(sector)
    await db_session.flush()

    emp_gestor = Employee(name="Gestora Maria", registration_number="GEST01", unit_id=unit.id, sector_id=sector.id)
    emp_tecnico = Employee(name="Tecnico Joao", registration_number="TEC01", unit_id=unit.id, sector_id=sector.id)
    emp_colab = Employee(name="Colaborador Pedro", registration_number="COL01", unit_id=unit.id, sector_id=sector.id)
    emp_solicitante = Employee(name="Solicitante Lucas", registration_number="SOL01", unit_id=unit.id, sector_id=sector.id)
    db_session.add_all([emp_gestor, emp_tecnico, emp_colab, emp_solicitante])
    await db_session.flush()

    # Contas com perfis distintos
    u_admin = UserAccount(email="adm@corp.com", hashed_password=hash_password("123"), is_admin=True)
    u_gestor = UserAccount(email="gestor@corp.com", hashed_password=hash_password("123"), is_admin=False, employee_id=emp_gestor.id)
    u_tecnico = UserAccount(email="tecnico@corp.com", hashed_password=hash_password("123"), is_admin=False, employee_id=emp_tecnico.id)
    u_colab = UserAccount(email="colab@corp.com", hashed_password=hash_password("123"), is_admin=False, employee_id=emp_colab.id)
    u_solicitante = UserAccount(email="solicitante@corp.com", hashed_password=hash_password("123"), is_admin=False, employee_id=emp_solicitante.id)
    db_session.add_all([u_admin, u_gestor, u_tecnico, u_colab, u_solicitante])
    await db_session.commit()

    # Headers JWT com as permissões atribuídas a cada perfil
    h_admin = make_auth_headers(user_id=str(u_admin.id), is_admin=True)
    h_gestor = make_auth_headers(
        user_id=str(u_gestor.id),
        is_admin=False,
        permissions=["organization.units.read", "organization.employees.read", "assets.read"]
    )
    h_tecnico = make_auth_headers(
        user_id=str(u_tecnico.id),
        is_admin=False,
        permissions=["tickets.read", "tickets.update", "stock.read", "stock.update"]
    )
    h_colab = make_auth_headers(user_id=str(u_colab.id), is_admin=False, permissions=[])
    h_solicitante = make_auth_headers(
        user_id=str(u_solicitante.id),
        is_admin=False,
        permissions=["service_desk.tickets.create", "service_desk.tickets.read"]
    )

    # MATRIZ RBAC:

    # A) Auditoria (/api/v1/audit) -> APENAS Admin
    assert (await client.get("/api/v1/audit", headers=h_admin)).status_code == 200
    assert (await client.get("/api/v1/audit", headers=h_gestor)).status_code == 403
    assert (await client.get("/api/v1/audit", headers=h_tecnico)).status_code == 403
    assert (await client.get("/api/v1/audit", headers=h_colab)).status_code == 403
    assert (await client.get("/api/v1/audit", headers=h_solicitante)).status_code == 403

    # B) Gestão de Usuários (/api/v1/identity/users) -> APENAS Admin (ou role específica)
    assert (await client.get("/api/v1/identity/users", headers=h_admin)).status_code == 200
    assert (await client.get("/api/v1/identity/users", headers=h_gestor)).status_code == 403
    assert (await client.get("/api/v1/identity/users", headers=h_tecnico)).status_code == 403
    assert (await client.get("/api/v1/identity/users", headers=h_colab)).status_code == 403
    assert (await client.get("/api/v1/identity/users", headers=h_solicitante)).status_code == 403

    # C) Visualização da Estrutura Organizacional (/api/v1/organization/units) -> Admin e Gestor
    assert (await client.get("/api/v1/organization/units", headers=h_admin)).status_code == 200
    assert (await client.get("/api/v1/organization/units", headers=h_gestor)).status_code == 200
    assert (await client.get("/api/v1/organization/units", headers=h_tecnico)).status_code == 403
    assert (await client.get("/api/v1/organization/units", headers=h_colab)).status_code == 403
    assert (await client.get("/api/v1/organization/units", headers=h_solicitante)).status_code == 403

    # D) Gestão de Estoque (/api/v1/stock/items) -> Admin e Técnico
    assert (await client.get("/api/v1/stock/items", headers=h_admin)).status_code == 200
    assert (await client.get("/api/v1/stock/items", headers=h_tecnico)).status_code == 200
    assert (await client.get("/api/v1/stock/items", headers=h_solicitante)).status_code == 403

    # E) Notificações (/api/v1/notifications) -> Todos os perfis têm acesso às suas próprias notificações
    assert (await client.get("/api/v1/notifications", headers=h_admin)).status_code == 200
    assert (await client.get("/api/v1/notifications", headers=h_gestor)).status_code == 200
    assert (await client.get("/api/v1/notifications", headers=h_tecnico)).status_code == 200
    assert (await client.get("/api/v1/notifications", headers=h_colab)).status_code == 200
    assert (await client.get("/api/v1/notifications", headers=h_solicitante)).status_code == 200
