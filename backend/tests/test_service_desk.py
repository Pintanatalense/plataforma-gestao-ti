import pytest
from uuid import uuid4
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.organization.models import Employee, Company, Unit, Sector
from app.identity.models import UserAccount, Role, Permission
from app.service_desk.models import TicketCategory
from app.core.security import hash_password
from tests.conftest import make_auth_headers

pytestmark = pytest.mark.asyncio


async def setup_test_data(db_session: AsyncSession):
    company = Company(name="Test Company", cnpj="123")
    db_session.add(company)
    await db_session.commit()

    unit = Unit(name="HQ", code="HQ1", company_id=company.id)
    db_session.add(unit)
    await db_session.commit()

    dept = Sector(name="IT", code="IT1", unit_id=unit.id)
    db_session.add(dept)
    await db_session.commit()

    employee = Employee(name="Test User", registration_number="123", unit_id=unit.id, sector_id=dept.id)
    db_session.add(employee)
    await db_session.commit()

    user = UserAccount(email="test@test.com", hashed_password=hash_password("123"), employee_id=employee.id)
    db_session.add(user)
    await db_session.commit()
    
    technician_employee = Employee(name="Tech User", registration_number="456", unit_id=unit.id, sector_id=dept.id)
    db_session.add(technician_employee)
    await db_session.commit()

    tech_user = UserAccount(email="tech@test.com", hashed_password=hash_password("123"), employee_id=technician_employee.id, is_admin=True)
    db_session.add(tech_user)
    await db_session.commit()

    category = TicketCategory(name="Hardware", default_sector_id=dept.id)
    db_session.add(category)
    await db_session.commit()

    return {
        "company": company,
        "unit": unit,
        "dept": dept,
        "employee": employee,
        "user": user,
        "technician_employee": technician_employee,
        "tech_user": tech_user,
        "category": category,
    }


async def test_list_categories(client: AsyncClient, db_session: AsyncSession):
    await setup_test_data(db_session)
    response = await client.get("/api/v1/tickets/categories")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Hardware"


async def test_create_ticket(client: AsyncClient, db_session: AsyncSession):
    data = await setup_test_data(db_session)
    user = data["user"]
    category = data["category"]

    headers = make_auth_headers(user_id=str(user.id), is_admin=False)
    
    payload = {
        "title": "Mouse quebrado",
        "description": "O botão esquerdo não funciona.",
        "priority": "LOW",
        "category_id": str(category.id)
    }

    response = await client.post("/api/v1/tickets", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    resp_data = response.json()
    assert resp_data["title"] == "Mouse quebrado"
    assert resp_data["status"] == "OPENED"
    assert resp_data["requester_id"] == str(user.employee_id)


async def test_ticket_interactions(client: AsyncClient, db_session: AsyncSession):
    data = await setup_test_data(db_session)
    user = data["user"]
    tech = data["tech_user"]
    category = data["category"]

    user_headers = make_auth_headers(user_id=str(user.id), is_admin=False)
    tech_headers = make_auth_headers(user_id=str(tech.id), is_admin=True)
    
    # 1. Create ticket as user
    payload = {
        "title": "Teclado não digita A",
        "description": "Ao apertar A, não sai nada.",
        "priority": "MEDIUM",
        "category_id": str(category.id)
    }
    resp = await client.post("/api/v1/tickets", json=payload, headers=user_headers)
    assert resp.status_code == 201, resp.text
    ticket_id = resp.json()["id"]

    # 2. Add public interaction as tech
    inter_payload = {
        "message": "Vamos trocar o teclado hoje à tarde.",
        "is_internal": False
    }
    resp = await client.post(f"/api/v1/tickets/{ticket_id}/interactions", json=inter_payload, headers=tech_headers)
    assert resp.status_code == 201

    # 3. Add internal interaction as tech
    internal_payload = {
        "message": "O usuário provavelmente derrubou café.",
        "is_internal": True
    }
    resp = await client.post(f"/api/v1/tickets/{ticket_id}/interactions", json=internal_payload, headers=tech_headers)
    assert resp.status_code == 201

    # 4. View ticket as user (should see 1 interaction)
    resp = await client.get(f"/api/v1/tickets/{ticket_id}", headers=user_headers)
    assert resp.status_code == 200
    interactions = resp.json()["interactions"]
    assert len(interactions) == 1
    assert interactions[0]["message"] == "Vamos trocar o teclado hoje à tarde."

    # 5. View ticket as tech (should see 2 interactions)
    resp = await client.get(f"/api/v1/tickets/{ticket_id}", headers=tech_headers)
    assert resp.status_code == 200
    interactions = resp.json()["interactions"]
    assert len(interactions) == 2


async def test_category_form_builder_and_ticket_prerequisites_validation(client: AsyncClient, db_session: AsyncSession):
    """
    Valida a criação de categoria com form_schema (pré-requisitos)
    e a obrigatoriedade estrita de preenchimento de todos os pré-requisitos para abertura do chamado.
    """
    data = await setup_test_data(db_session)
    user = data["user"]
    tech = data["tech_user"]
    dept = data["dept"]

    tech_headers = make_auth_headers(user_id=str(tech.id), is_admin=True)
    user_headers = make_auth_headers(user_id=str(user.id), is_admin=False)

    # 1. Técnico cria categoria com schema de formulário / pré-requisitos
    cat_payload = {
        "name": "Substituição de Notebook",
        "description": "Exige preenchimento de patrimônio anterior e motivo",
        "default_sector_id": str(dept.id),
        "form_schema": [
            {
                "id": "patrimonio_anterior",
                "label": "Patrimônio Anterior",
                "type": "text",
                "required": True,
                "placeholder": "Ex: PAT-1234"
            },
            {
                "id": "motivo_troca",
                "label": "Motivo da Troca",
                "type": "select",
                "required": True,
                "options": ["Defeito Físico", "Lentidão Excessiva", "Upgrade de Cargo"]
            },
            {
                "id": "termo_concordancia",
                "label": "Declaro estar ciente da devolução do antigo",
                "type": "checkbox",
                "required": True
            },
            {
                "id": "observacoes",
                "label": "Observações Opcionais",
                "type": "textarea",
                "required": False
            }
        ]
    }
    cat_resp = await client.post("/api/v1/tickets/categories", json=cat_payload, headers=tech_headers)
    assert cat_resp.status_code == 201, cat_resp.text
    category_id = cat_resp.json()["id"]
    assert len(cat_resp.json()["form_schema"]) == 4

    # 2. Usuário tenta abrir chamado SEM preencher os pré-requisitos obrigatórios -> Deve falhar (400)
    ticket_payload_empty = {
        "title": "Preciso trocar de notebook",
        "description": "Meu computador atual queimou a placa mãe.",
        "priority": "HIGH",
        "category_id": category_id,
        "custom_fields": {}
    }
    resp_empty = await client.post("/api/v1/tickets", json=ticket_payload_empty, headers=user_headers)
    assert resp_empty.status_code == 400
    msg_empty = str(resp_empty.json().get("detail") or resp_empty.json().get("error", {}).get("message", ""))
    assert "Patrimônio Anterior" in msg_empty

    # 3. Usuário preenche patrimônio anterior, mas não o motivo da troca -> Deve falhar (400)
    ticket_payload_partial = {
        "title": "Preciso trocar de notebook",
        "description": "Meu computador atual queimou a placa mãe.",
        "priority": "HIGH",
        "category_id": category_id,
        "custom_fields": {
            "patrimonio_anterior": "PAT-9876"
        }
    }
    resp_partial = await client.post("/api/v1/tickets", json=ticket_payload_partial, headers=user_headers)
    assert resp_partial.status_code == 400
    msg_partial = str(resp_partial.json().get("detail") or resp_partial.json().get("error", {}).get("message", ""))
    assert "Motivo da Troca" in msg_partial

    # 4. Usuário fornece opção inválida no select -> Deve falhar (400)
    ticket_payload_invalid_opt = {
        "title": "Preciso trocar de notebook",
        "description": "Meu computador atual queimou a placa mãe.",
        "priority": "HIGH",
        "category_id": category_id,
        "custom_fields": {
            "patrimonio_anterior": "PAT-9876",
            "motivo_troca": "Opção Inválida Qualquer",
            "termo_concordancia": True
        }
    }
    resp_inv = await client.post("/api/v1/tickets", json=ticket_payload_invalid_opt, headers=user_headers)
    assert resp_inv.status_code == 400
    msg_inv = str(resp_inv.json().get("detail") or resp_inv.json().get("error", {}).get("message", "")).lower()
    assert "inválida" in msg_inv

    # 5. Usuário cumpre TODOS os pré-requisitos -> Sucesso (201)
    ticket_payload_valid = {
        "title": "Preciso trocar de notebook",
        "description": "Meu computador atual queimou a placa mãe.",
        "priority": "HIGH",
        "category_id": category_id,
        "custom_fields": {
            "patrimonio_anterior": "PAT-9876",
            "motivo_troca": "Defeito Físico",
            "termo_concordancia": True,
            "observacoes": "Equipamento já entregue na bancada da TI."
        }
    }
    resp_valid = await client.post("/api/v1/tickets", json=ticket_payload_valid, headers=user_headers)
    assert resp_valid.status_code == 201, resp_valid.text
    created_ticket = resp_valid.json()
    assert created_ticket["custom_fields"]["patrimonio_anterior"] == "PAT-9876"
    assert created_ticket["custom_fields"]["motivo_troca"] == "Defeito Físico"
    assert created_ticket["custom_fields"]["termo_concordancia"] is True

    # 6. Consultando o chamado individual -> custom_fields preservados
    ticket_id = created_ticket["id"]
    get_resp = await client.get(f"/api/v1/tickets/{ticket_id}", headers=user_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["custom_fields"]["patrimonio_anterior"] == "PAT-9876"


async def test_solicitante_profile_rbac_isolation(client: AsyncClient, db_session: AsyncSession):
    """
    Validação de segurança do perfil 'Solicitante' (só abrir chamado):
    - Consegue listar seus próprios chamados
    - Consegue abrir novos chamados
    - É BLOQUEADO de gerenciar categorias de chamados
    - É BLOQUEADO de acessar ativos patrimoniais
    - É BLOQUEADO de acessar estoque e movimentações
    """
    data = await setup_test_data(db_session)
    user = data["user"]
    category = data["category"]

    # Usuário com permissões estritas de Solicitante
    solicitante_headers = make_auth_headers(
        user_id=str(user.id),
        is_admin=False,
        permissions=["service_desk.tickets.create", "service_desk.tickets.read"]
    )

    # 1. Consegue abrir chamado
    ticket_resp = await client.post("/api/v1/tickets", json={
        "title": "Chamado aberto por Solicitante",
        "description": "Teclado com teclas travando.",
        "priority": "LOW",
        "category_id": str(category.id)
    }, headers=solicitante_headers)
    assert ticket_resp.status_code == 201

    # 2. Consegue listar seus chamados
    list_resp = await client.get("/api/v1/tickets", headers=solicitante_headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 1

    # 3. Bloqueado de criar/gerenciar categorias de chamados (exige service_desk.tickets.manage)
    cat_block_resp = await client.post("/api/v1/tickets/categories", json={
        "name": "Tentativa Invasiva"
    }, headers=solicitante_headers)
    assert cat_block_resp.status_code == 403

    # 4. Bloqueado de acessar ativos patrimoniais
    assets_block_resp = await client.get("/api/v1/assets", headers=solicitante_headers)
    assert assets_block_resp.status_code == 403

    # 5. Bloqueado de acessar estoque
    stock_block_resp = await client.get("/api/v1/stock/items", headers=solicitante_headers)
    assert stock_block_resp.status_code == 403


async def test_ticket_lifecycle_history_and_requester_closing(client: AsyncClient, db_session: AsyncSession):
    """
    Testa o ciclo de vida completo do chamado:
    1. Abertura do chamado pelo solicitante.
    2. Técnico atende e altera status para IN_PROGRESS com evento no histórico.
    3. Solicitante e técnico trocam interações no chamado.
    4. Solicitante finaliza seu próprio chamado com nota de resolução (CLOSED).
    5. Histórico completo de eventos é consultado e preservado.
    """
    data = await setup_test_data(db_session)
    user = data["user"]
    tech = data["tech_user"]
    category = data["category"]

    user_headers = make_auth_headers(user_id=str(user.id), is_admin=False)
    tech_headers = make_auth_headers(user_id=str(tech.id), is_admin=True)

    # 1. Solicitante abre chamado
    open_resp = await client.post("/api/v1/tickets", json={
        "title": "Problema no monitor",
        "description": "Tela piscando e com linhas verticais.",
        "priority": "MEDIUM",
        "category_id": str(category.id)
    }, headers=user_headers)
    assert open_resp.status_code == 201
    ticket_id = open_resp.json()["id"]

    # 2. Técnico assume e coloca em atendimento
    patch_resp = await client.patch(f"/api/v1/tickets/{ticket_id}", json={
        "status": "IN_PROGRESS"
    }, headers=tech_headers)
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "IN_PROGRESS"

    # 3. Solicitante envia mensagem ao técnico
    msg_resp = await client.post(f"/api/v1/tickets/{ticket_id}/interactions", json={
        "message": "Começou a piscar depois da chuva de ontem.",
        "is_internal": False
    }, headers=user_headers)
    assert msg_resp.status_code == 201

    # 4. Solicitante confirma resolução e finaliza seu próprio chamado
    close_resp = await client.patch(f"/api/v1/tickets/{ticket_id}", json={
        "status": "CLOSED",
        "notes": "O cabo HDMI foi trocado e funcionou perfeitamente. Obrigado!"
    }, headers=user_headers)
    assert close_resp.status_code == 200
    assert close_resp.json()["status"] == "CLOSED"

    # 5. Consulta histórico de vida do chamado
    history_resp = await client.get(f"/api/v1/tickets/{ticket_id}/history", headers=user_headers)
    assert history_resp.status_code == 200
    history = history_resp.json()
    assert len(history) >= 2
    actions = [h["action"] for h in history]
    assert "Abertura de Chamado" in actions
    assert any("Status" in a or "Finalização" in a for a in actions)


@pytest.mark.asyncio
async def test_tripartite_rbac_gestao_atendente_solicitante(client: AsyncClient, db_session: AsyncSession):
    """
    Testa a matriz de autorização tripartite no Service Desk:
    - Gestão: Leitura global de chamados, relatórios (/reports/summary), notas internas; BLOQUEADO para alterações operacionais.
    - Atendente: Atendimento, alteração de status/prioridade/responsável, notas internas.
    - Solicitante: Apenas seus próprios chamados, sem acesso a relatórios gerenciais ou notas internas.
    """
    from app.core.security import hash_password
    from sqlalchemy import select
    from app.organization.models import Company, Unit, Sector, Employee
    from app.identity.models import UserAccount, Role, Permission
    from app.service_desk.models import TicketCategory

    # 1. Setup da estrutura organizacional
    company = Company(name="RBAC Tripartite Corp", cnpj="99.888.777/0001-99")
    db_session.add(company)
    await db_session.flush()

    unit = Unit(company_id=company.id, name="Matriz Central", code="MC-01", type="MATRIZ")
    db_session.add(unit)
    await db_session.flush()

    sector = Sector(unit_id=unit.id, name="Tecnologia", code="TEC-01")
    db_session.add(sector)
    await db_session.flush()

    # 2. Criar colaboradores
    emp_solic1 = Employee(unit_id=unit.id, sector_id=sector.id, name="Solicitante Um", registration_number="SOL-001")
    emp_solic2 = Employee(unit_id=unit.id, sector_id=sector.id, name="Solicitante Dois", registration_number="SOL-002")
    emp_atend = Employee(unit_id=unit.id, sector_id=sector.id, name="Técnico Atendente", registration_number="ATD-001")
    emp_gestor = Employee(unit_id=unit.id, sector_id=sector.id, name="Gerente Gestão", registration_number="GES-001")
    db_session.add_all([emp_solic1, emp_solic2, emp_atend, emp_gestor])
    await db_session.flush()

    # 3. Criar permissões necessárias
    needed_codes = [
        "service_desk.tickets.create",
        "service_desk.tickets.read",
        "service_desk.tickets.manage",
        "service_desk.tickets.read_all",
        "service_desk.reports.read",
        "service_desk.interactions.internal"
    ]
    perms_dict = {}
    for code in needed_codes:
        res = await db_session.execute(select(Permission).where(Permission.code == code))
        p = res.scalar_one_or_none()
        if not p:
            p = Permission(code=code, description=code)
            db_session.add(p)
            await db_session.flush()
        perms_dict[code] = p

    # 4. Criar Roles
    role_solic = Role(name="Role_Solicitante_Test", description="Test Solicitante")
    role_solic.permissions = [perms_dict["service_desk.tickets.create"], perms_dict["service_desk.tickets.read"]]

    role_atend = Role(name="Role_Atendente_Test", description="Test Atendente")
    role_atend.permissions = [
        perms_dict["service_desk.tickets.create"],
        perms_dict["service_desk.tickets.read"],
        perms_dict["service_desk.tickets.read_all"],
        perms_dict["service_desk.tickets.manage"],
        perms_dict["service_desk.interactions.internal"]
    ]

    role_gestao = Role(name="Role_Gestao_Test", description="Test Gestão")
    role_gestao.permissions = [
        perms_dict["service_desk.tickets.create"],
        perms_dict["service_desk.tickets.read"],
        perms_dict["service_desk.tickets.read_all"],
        perms_dict["service_desk.reports.read"],
        perms_dict["service_desk.interactions.internal"]
    ]
    db_session.add_all([role_solic, role_atend, role_gestao])
    await db_session.flush()

    # 5. Criar Contas de Usuário
    u_solic1 = UserAccount(email="solic1@rbac.com", hashed_password=hash_password("Senha123!"), employee_id=emp_solic1.id)
    u_solic1.roles = [role_solic]

    u_solic2 = UserAccount(email="solic2@rbac.com", hashed_password=hash_password("Senha123!"), employee_id=emp_solic2.id)
    u_solic2.roles = [role_solic]

    u_atend = UserAccount(email="atend@rbac.com", hashed_password=hash_password("Senha123!"), employee_id=emp_atend.id)
    u_atend.roles = [role_atend]

    u_gestor = UserAccount(email="gestor@rbac.com", hashed_password=hash_password("Senha123!"), employee_id=emp_gestor.id)
    u_gestor.roles = [role_gestao]

    cat = TicketCategory(name="Suporte Técnico RBAC", default_sector_id=sector.id)
    db_session.add_all([u_solic1, u_solic2, u_atend, u_gestor, cat])
    await db_session.commit()

    # Helpers de autenticação
    async def get_auth(email: str) -> dict:
        r = await client.post("/api/v1/identity/login", data={"username": email, "password": "Senha123!"})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    headers_solic1 = await get_auth("solic1@rbac.com")
    headers_solic2 = await get_auth("solic2@rbac.com")
    headers_atend = await get_auth("atend@rbac.com")
    headers_gestor = await get_auth("gestor@rbac.com")

    # 6. Solicitante 1 cria um chamado
    create_r = await client.post("/api/v1/tickets", json={
        "title": "Problema no servidor de arquivos",
        "description": "Pasta de rede não acessível",
        "priority": "HIGH",
        "category_id": str(cat.id)
    }, headers=headers_solic1)
    assert create_r.status_code == 201
    ticket_id = create_r.json()["id"]

    # 7. Solicitante 2 tenta ver o chamado de Solicitante 1 -> Bloqueado 403
    r_solic2 = await client.get(f"/api/v1/tickets/{ticket_id}", headers=headers_solic2)
    assert r_solic2.status_code == 403

    # 8. Atendente vê o chamado -> Permitido 200
    r_atend = await client.get(f"/api/v1/tickets/{ticket_id}", headers=headers_atend)
    assert r_atend.status_code == 200

    # 9. Gestão vê o chamado (leitura global) -> Permitido 200
    r_gestor = await client.get(f"/api/v1/tickets/{ticket_id}", headers=headers_gestor)
    assert r_gestor.status_code == 200

    # 10. Gestão tenta alterar status operacional -> Bloqueado 403 (Gestão não é técnico)
    patch_gestor = await client.patch(f"/api/v1/tickets/{ticket_id}", json={
        "status": "IN_PROGRESS"
    }, headers=headers_gestor)
    assert patch_gestor.status_code == 403

    # 11. Atendente altera status operacional -> Permitido 200
    patch_atend = await client.patch(f"/api/v1/tickets/{ticket_id}", json={
        "status": "IN_PROGRESS"
    }, headers=headers_atend)
    assert patch_atend.status_code == 200
    assert patch_atend.json()["status"] == "IN_PROGRESS"

    # 12. Atendente adiciona nota técnica interna -> Permitido 201
    int_resp = await client.post(f"/api/v1/tickets/{ticket_id}/interactions", json={
        "message": "Nota interna confidencial sobre reinicialização de switch",
        "is_internal": True
    }, headers=headers_atend)
    assert int_resp.status_code == 201

    # 13. Solicitante 1 consulta chamado -> Não vê a nota interna
    ticket_solic1 = await client.get(f"/api/v1/tickets/{ticket_id}", headers=headers_solic1)
    assert ticket_solic1.status_code == 200
    interactions_solic = ticket_solic1.json()["interactions"]
    assert not any(i["is_internal"] for i in interactions_solic)

    # 14. Gestão consulta chamado -> Vê a nota interna
    ticket_gestao = await client.get(f"/api/v1/tickets/{ticket_id}", headers=headers_gestor)
    assert ticket_gestao.status_code == 200
    interactions_gestao = ticket_gestao.json()["interactions"]
    assert any(i["is_internal"] for i in interactions_gestao)

    # 15. Solicitante 1 tenta criar nota interna -> Bloqueado 403
    int_solic_block = await client.post(f"/api/v1/tickets/{ticket_id}/interactions", json={
        "message": "Tentativa indevida de nota interna",
        "is_internal": True
    }, headers=headers_solic1)
    assert int_solic_block.status_code == 403

    # 16. Gestão acessa resumo de métricas (/reports/summary) -> Permitido 200
    rep_gestao = await client.get("/api/v1/tickets/reports/summary", headers=headers_gestor)
    assert rep_gestao.status_code == 200
    rep_data = rep_gestao.json()
    assert rep_data["total_tickets"] >= 1
    assert "by_status" in rep_data
    assert "resolution_rate_percent" in rep_data

    # 17. Solicitante 1 tenta acessar resumo de métricas -> Bloqueado 403
    rep_solic = await client.get("/api/v1/tickets/reports/summary", headers=headers_solic1)
    assert rep_solic.status_code == 403


