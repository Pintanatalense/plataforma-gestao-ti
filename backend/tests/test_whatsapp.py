"""
Testes automatizados para MOD-15 — WhatsApp Integration & Bot
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.security import hash_password
from app.organization.models import Company, Unit, Sector, Employee
from app.identity.models import UserAccount, Role, Permission
from app.service_desk.models import Ticket, TicketCategory, TicketInteraction
from app.whatsapp.models import WhatsAppConfig, WhatsAppSession
from app.whatsapp.adapter import default_mock_adapter
from tests.conftest import make_auth_headers

pytestmark = pytest.mark.asyncio


WEBHOOK_SECRET = "segredo-de-teste-do-webhook"


async def wa(client: AsyncClient, payload: dict):
    """Chama o webhook autenticado; a resposta do bot é lida no adapter mock."""
    return await client.post(
        "/api/v1/integrations/whatsapp/webhook", json=payload, headers={"X-Webhook-Secret": WEBHOOK_SECRET}
    )


def last_reply() -> str:
    return default_mock_adapter.sent_messages[-1]["text"]



async def setup_whatsapp_fixtures(db_session: AsyncSession):
    company = Company(name="WhatsApp Corp", cnpj="55.666.777/0001-88")
    db_session.add(company)
    await db_session.flush()

    unit = Unit(company_id=company.id, name="Matriz Rio", code="RIO-01", type="MATRIZ")
    db_session.add(unit)
    await db_session.flush()

    sector = Sector(unit_id=unit.id, name="Infraestrutura", code="INF-01")
    db_session.add(sector)
    await db_session.flush()

    # Colaborador com telefone já cadastrado
    emp_linked = Employee(
        unit_id=unit.id, sector_id=sector.id, name="Carlos Mendes", registration_number="CM-100", phone="5521988887777"
    )
    # Colaborador sem telefone para testar fluxo de vinculação
    emp_unlinked = Employee(
        unit_id=unit.id, sector_id=sector.id, name="Fernanda Lima", registration_number="FL-200"
    )
    db_session.add_all([emp_linked, emp_unlinked])
    await db_session.flush()

    user_linked = UserAccount(email="carlos@empresa.com", hashed_password=hash_password("123"), employee_id=emp_linked.id)
    db_session.add(user_linked)
    await db_session.flush()

    # Permissões administrativas de WhatsApp
    perm_wa = Permission(code="integrations.whatsapp.manage", description="Gerenciar WhatsApp")
    db_session.add(perm_wa)
    await db_session.flush()

    role_admin = Role(name="WAAdminRole", description="Admin WhatsApp")
    role_admin.permissions = [perm_wa]
    db_session.add(role_admin)
    await db_session.flush()

    emp_admin = Employee(unit_id=unit.id, sector_id=sector.id, name="Admin WA", registration_number="ADM-999")
    db_session.add(emp_admin)
    await db_session.flush()

    user_admin = UserAccount(email="admin_wa@empresa.com", hashed_password=hash_password("123"), employee_id=emp_admin.id)
    user_admin.roles = [role_admin]
    db_session.add(user_admin)
    await db_session.flush()

    cat1 = TicketCategory(name="Problemas de Conexão", description="Internet / VPN", default_sector_id=sector.id)
    cat2 = TicketCategory(name="Sistemas Corporativos", description="ERP / E-mail", default_sector_id=sector.id)
    db_session.add_all([cat1, cat2])
    await db_session.flush()

    # Configuração de WhatsApp garantida no banco
    cfg = WhatsAppConfig(provider="MOCK", is_enabled=True, webhook_secret=WEBHOOK_SECRET)
    db_session.add(cfg)
    await db_session.commit()

    default_mock_adapter.clear()

    return {
        "admin_headers": make_auth_headers(str(user_admin.id), is_admin=False, permissions=["integrations.whatsapp.manage", "service_desk.tickets.manage"]),
        "regular_headers": make_auth_headers(str(user_linked.id), is_admin=False, permissions=[]),
        "emp_linked": emp_linked,
        "emp_unlinked": emp_unlinked,
        "cat1": cat1,
    }


async def test_unlinked_number_gets_generic_reply_and_is_never_linked(client: AsyncClient, db_session: AsyncSession):
    """Número desconhecido não é vinculado por matrícula e não recebe dados de ninguém."""
    await setup_whatsapp_fixtures(db_session)
    phone = "5521999990000"

    r1 = await wa(client, {"phone": phone, "message": "Oi"})
    assert r1.status_code == 200
    assert "não está vinculado" in last_reply()

    # Digitar uma matrícula válida NÃO vincula o número
    r2 = await wa(client, {"phone": phone, "message": "FL-200"})
    assert r2.status_code == 200
    assert "não está vinculado" in last_reply()
    stmt = select(Employee).where(Employee.registration_number == "FL-200")
    emp = (await db_session.execute(stmt)).scalar_one()
    assert emp.phone is None


async def test_webhook_requires_shared_secret_and_never_echoes_reply(client: AsyncClient, db_session: AsyncSession):
    fixtures = await setup_whatsapp_fixtures(db_session)
    payload = {"phone": fixtures["emp_linked"].phone, "message": "2"}
    url = "/api/v1/integrations/whatsapp/webhook"

    assert (await client.post(url, json=payload)).status_code == 401
    assert (await client.post(url, json=payload, headers={"X-Webhook-Secret": "errado"})).status_code == 401
    assert default_mock_adapter.sent_messages == []

    ok = await client.post(url, json=payload, headers={"X-Webhook-Secret": WEBHOOK_SECRET})
    assert ok.status_code == 200
    assert ok.json() == {"status": "accepted"}
    assert default_mock_adapter.sent_messages  # resposta segue pelo provedor, não pelo corpo HTTP


async def test_webhook_rejected_when_secret_not_configured(client: AsyncClient, db_session: AsyncSession):
    fixtures = await setup_whatsapp_fixtures(db_session)
    cfg = (await db_session.execute(select(WhatsAppConfig))).scalars().one()
    cfg.webhook_secret = None
    await db_session.commit()
    r = await client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json={"phone": fixtures["emp_linked"].phone, "message": "2"},
        headers={"X-Webhook-Secret": ""},
    )
    assert r.status_code == 401


async def test_templates_and_ticket_send_require_permissions(client: AsyncClient, db_session: AsyncSession):
    fixtures = await setup_whatsapp_fixtures(db_session)
    base = "/api/v1/integrations/whatsapp"
    assert (await client.get(f"{base}/templates")).status_code == 401
    assert (await client.get(f"{base}/templates", headers=fixtures["regular_headers"])).status_code == 403
    assert (await client.get(f"{base}/templates", headers=fixtures["admin_headers"])).status_code == 200
    r = await client.post(
        f"{base}/tickets/{uuid.uuid4()}/send", json={"custom_message": "x"}, headers=fixtures["regular_headers"]
    )
    assert r.status_code == 403


async def test_whatsapp_create_ticket_full_flow(client: AsyncClient, db_session: AsyncSession):
    """Testa o fluxo conversacional de ponta a ponta para abertura de chamado via WhatsApp."""
    fixtures = await setup_whatsapp_fixtures(db_session)
    phone = fixtures["emp_linked"].phone

    # 1. Inicia fluxo enviando [1]
    r1 = await wa(client, {"phone": phone, "message": "1"})
    assert r1.status_code == 200
    assert "Selecione a categoria" in last_reply()

    # 2. Seleciona categoria [1]
    r2 = await wa(client, {"phone": phone, "message": "1"})
    assert r2.status_code == 200
    assert "Título Resumido" in last_reply()

    # 3. Informa título
    r3 = await wa(client, {"phone": phone, "message": "VPN desconectando a cada 5 minutos"})
    assert r3.status_code == 200
    assert "descreva detalhadamente" in last_reply().lower()

    # 4. Informa descrição
    r4 = await wa(client, {
        "phone": phone,
        "message": "Estou em home office e a conexão cai no meio de reuniões."
    })
    assert r4.status_code == 200
    reply4 = last_reply()
    assert "criado com sucesso" in reply4.lower()

    # 5. Valida que o chamado foi persistido no banco
    stmt = select(Ticket).where(Ticket.requester_id == fixtures["emp_linked"].id).order_by(Ticket.created_at.desc())
    ticket_db = (await db_session.execute(stmt)).scalars().first()
    assert ticket_db is not None
    assert ticket_db.title == "VPN desconectando a cada 5 minutos"
    assert "home office" in ticket_db.description
    assert ticket_db.status == "OPENED"


async def test_whatsapp_list_tickets(client: AsyncClient, db_session: AsyncSession):
    """Testa a consulta de chamados existentes via WhatsApp."""
    fixtures = await setup_whatsapp_fixtures(db_session)
    phone = fixtures["emp_linked"].phone

    # Cria um chamado para o colaborador
    t = Ticket(
        title="Monitor não liga",
        description="Fica com tela preta",
        priority="LOW",
        status="IN_PROGRESS",
        requester_id=fixtures["emp_linked"].id,
        origin_unit_id=fixtures["emp_linked"].unit_id,
        origin_sector_id=fixtures["emp_linked"].sector_id,
        responsible_sector_id=fixtures["emp_linked"].sector_id,
    )
    db_session.add(t)
    await db_session.commit()

    # Usuário digita '2' para consultar
    r = await wa(client, {"phone": phone, "message": "2"})
    assert r.status_code == 200
    reply = last_reply()
    assert "Monitor não liga" in reply
    assert "Em Atendimento" in reply


async def test_whatsapp_interaction_on_ticket(client: AsyncClient, db_session: AsyncSession):
    """Testa o envio de interação/resposta para um chamado aberto via WhatsApp."""
    fixtures = await setup_whatsapp_fixtures(db_session)
    phone = fixtures["emp_linked"].phone

    # Cria chamado prévio
    t = Ticket(
        title="Impressora travando papel",
        description="Erro recorrente",
        priority="MEDIUM",
        status="IN_PROGRESS",
        requester_id=fixtures["emp_linked"].id,
        origin_unit_id=fixtures["emp_linked"].unit_id,
        origin_sector_id=fixtures["emp_linked"].sector_id,
        responsible_sector_id=fixtures["emp_linked"].sector_id,
    )
    db_session.add(t)
    await db_session.commit()

    # 1. Digita [3] para responder
    r1 = await wa(client, {"phone": phone, "message": "3"})
    assert r1.status_code == 200
    assert "digite os primeiros dígitos" in last_reply().lower()

    # 2. Digita primeiros dígitos do ID do chamado
    short_id = str(t.id)[:6]
    r2 = await wa(client, {"phone": phone, "message": short_id})
    assert r2.status_code == 200
    assert "Impressora travando papel" in last_reply()

    # 3. Digita a resposta
    r3 = await wa(client, {
        "phone": phone,
        "message": "Consegui destravar reiniciando, mas o ruído continua."
    })
    assert r3.status_code == 200
    assert "enviada com sucesso" in last_reply().lower()

    # Verifica interação no banco
    stmt = select(TicketInteraction).where(TicketInteraction.ticket_id == t.id)
    interactions = (await db_session.execute(stmt)).scalars().all()
    assert len(interactions) >= 1
    assert any("ruído continua" in i.message for i in interactions)


async def test_whatsapp_admin_configuration(client: AsyncClient, db_session: AsyncSession):
    """Testa endpoints de configuração e teste de envio de mensagem."""
    fixtures = await setup_whatsapp_fixtures(db_session)
    admin_headers = fixtures["admin_headers"]
    reg_headers = fixtures["regular_headers"]

    # 1. Usuário comum bloqueado
    r_block = await client.get("/api/v1/integrations/whatsapp/config", headers=reg_headers)
    assert r_block.status_code == 403

    # 2. Admin obtém configuração
    r_cfg = await client.get("/api/v1/integrations/whatsapp/config", headers=admin_headers)
    assert r_cfg.status_code == 200
    assert r_cfg.json()["provider"] in ("MOCK", "EVOLUTION_API")

    # 3. Admin dispara teste de envio com Mock (sucesso 200)
    r_test = await client.post("/api/v1/integrations/whatsapp/test-send", json={
        "to_phone": "5511999998888",
        "message": "Teste automatizado com Mock"
    }, headers=admin_headers)
    assert r_test.status_code == 200
    assert r_test.json()["to_phone"] == "5511999998888"

    # 4. Admin atualiza configuração para provedor externo (Evolution API)
    r_patch = await client.patch("/api/v1/integrations/whatsapp/config", json={
        "provider": "EVOLUTION_API",
        "api_url": "http://evolution-api:8080",
        "instance_name": "gestao_ti_prod"
    }, headers=admin_headers)
    assert r_patch.status_code == 200
    assert r_patch.json()["instance_name"] == "gestao_ti_prod"

    # 5. Admin testa envio para Evolution API offline -> Deve tratar graciosamente com 502
    r_test_offline = await client.post("/api/v1/integrations/whatsapp/test-send", json={
        "to_phone": "5511999998888",
        "message": "Teste com servidor externo offline"
    }, headers=admin_headers)
    assert r_test_offline.status_code == 502


async def test_whatsapp_antiban_and_emergency_pause(client: AsyncClient, db_session: AsyncSession):
    """Testa parâmetros de segurança anti-ban e o botão kill switch de emergência."""
    fixtures = await setup_whatsapp_fixtures(db_session)
    admin_headers = fixtures["admin_headers"]

    # 1. Configura parâmetros anti-ban avançados
    r_patch = await client.patch("/api/v1/integrations/whatsapp/config", json={
        "anti_ban_enabled": True,
        "min_delay_seconds": 3,
        "max_delay_seconds": 7,
        "simulate_typing": True,
        "typing_duration_seconds": 2,
        "max_messages_per_minute": 10,
        "cooldown_per_recipient_seconds": 15
    }, headers=admin_headers)
    assert r_patch.status_code == 200
    data = r_patch.json()
    assert data["anti_ban_enabled"] is True
    assert data["min_delay_seconds"] == 3
    assert data["max_delay_seconds"] == 7
    assert data["max_messages_per_minute"] == 10

    # 2. Ativa Kill Switch (Emergency Pause)
    r_pause = await client.post("/api/v1/integrations/whatsapp/emergency-pause", headers=admin_headers)
    assert r_pause.status_code == 200
    assert r_pause.json()["emergency_pause"] is True

    # 3. Tenta processar a fila com Kill Switch ativo -> deve abortar
    r_proc = await client.post("/api/v1/integrations/whatsapp/outbox/process", headers=admin_headers)
    assert r_proc.status_code == 200
    assert r_proc.json()["status"] == "paused"

    # 4. Desativa Kill Switch
    r_unpause = await client.post("/api/v1/integrations/whatsapp/emergency-pause", headers=admin_headers)
    assert r_unpause.status_code == 200
    assert r_unpause.json()["emergency_pause"] is False


async def test_whatsapp_templates_crud_and_preview(client: AsyncClient, db_session: AsyncSession):
    """Testa criação, listagem, preview interpolado e exclusão de templates pré-definidos."""
    fixtures = await setup_whatsapp_fixtures(db_session)
    admin_headers = fixtures["admin_headers"]

    # 1. Cria template pré-definido
    r_create = await client.post("/api/v1/integrations/whatsapp/templates", json={
        "code": "TEST_TPL",
        "name": "Template de Teste Automatizado",
        "category": "SERVICE_DESK",
        "content": "Olá {{solicitante}}! Seu chamado #{{protocolo}} está com status {{status}}. Obs: {{observacao}}"
    }, headers=admin_headers)
    assert r_create.status_code == 201
    tpl_id = r_create.json()["id"]

    # 2. Listagem de templates
    r_list = await client.get("/api/v1/integrations/whatsapp/templates?category=SERVICE_DESK", headers=admin_headers)
    assert r_list.status_code == 200
    assert any(t["code"] == "TEST_TPL" for t in r_list.json())

    # 3. Cria chamado para testar interpolação
    t = Ticket(
        title="Teclado quebrado",
        description="Falta tecla espaço",
        priority="LOW",
        status="IN_PROGRESS",
        requester_id=fixtures["emp_linked"].id,
        origin_unit_id=fixtures["emp_linked"].unit_id,
        origin_sector_id=fixtures["emp_linked"].sector_id,
        responsible_sector_id=fixtures["emp_linked"].sector_id,
    )
    db_session.add(t)
    await db_session.commit()

    # 4. Pré-visualização com dados do chamado
    r_prev = await client.post(f"/api/v1/integrations/whatsapp/templates/{tpl_id}/preview", json={
        "ticket_id": str(t.id),
        "observacao": "Peça de reposição solicitada."
    }, headers=admin_headers)
    assert r_prev.status_code == 200
    rendered = r_prev.json()["rendered_message"]
    assert "Carlos Mendes" in rendered
    assert str(t.id)[:8] in rendered
    assert "Em Atendimento" in rendered
    assert "Peça de reposição solicitada." in rendered

    # 5. Exclusão do template
    r_del = await client.delete(f"/api/v1/integrations/whatsapp/templates/{tpl_id}", headers=admin_headers)
    assert r_del.status_code == 204


async def test_whatsapp_send_ticket_message_and_outbox(client: AsyncClient, db_session: AsyncSession):
    """Testa envio de mensagem a partir do chamado para a fila com Anti-Ban e registro no chat."""
    fixtures = await setup_whatsapp_fixtures(db_session)
    admin_headers = fixtures["admin_headers"]
    phone = fixtures["emp_linked"].phone

    # Cria template
    r_create = await client.post("/api/v1/integrations/whatsapp/templates", json={
        "code": "TICKET_NOTIFY",
        "name": "Notificação Rápida",
        "category": "SERVICE_DESK",
        "content": "Prezado {{solicitante}}, seu chamado #{{protocolo}} foi atualizado: {{observacao}}"
    }, headers=admin_headers)
    tpl_id = r_create.json()["id"]

    # Cria chamado com o solicitante vinculado
    t = Ticket(
        title="Problema no Áudio",
        description="Microfone mudo",
        priority="MEDIUM",
        status="IN_PROGRESS",
        requester_id=fixtures["emp_linked"].id,
        origin_unit_id=fixtures["emp_linked"].unit_id,
        origin_sector_id=fixtures["emp_linked"].sector_id,
        responsible_sector_id=fixtures["emp_linked"].sector_id,
    )
    db_session.add(t)
    await db_session.commit()

    # Envia WhatsApp pelo endpoint do chamado
    r_send = await client.post(f"/api/v1/integrations/whatsapp/tickets/{t.id}/send", json={
        "template_id": tpl_id,
        "observacao": "Testamos a saída e o problema é o conector P3.",
        "priority": 1
    }, headers=admin_headers)
    assert r_send.status_code == 200
    assert r_send.json()["status"] == "queued"
    outbox_id = r_send.json()["outbox_id"]

    # Valida presença do registro na fila outbox
    r_outbox = await client.get("/api/v1/integrations/whatsapp/outbox", headers=admin_headers)
    assert r_outbox.status_code == 200
    assert any(item["id"] == outbox_id for item in r_outbox.json())

    # Valida métricas do Outbox Stats
    r_stats = await client.get("/api/v1/integrations/whatsapp/outbox/stats", headers=admin_headers)
    assert r_stats.status_code == 200
    assert r_stats.json()["anti_ban_enabled"] is True

    # Valida que interação pública foi gravada no chamado
    stmt_inter = select(TicketInteraction).where(TicketInteraction.ticket_id == t.id)
    interactions = (await db_session.execute(stmt_inter)).scalars().all()
    assert len(interactions) >= 1
    assert any("[WhatsApp Enviado]" in inter.message for inter in interactions)

