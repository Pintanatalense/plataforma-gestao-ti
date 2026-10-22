import pytest
from uuid import uuid4
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.organization.models import Employee, Company, Unit, Sector
from app.identity.models import UserAccount
from app.assets.models import AssetCategory
from app.service_desk.models import TicketCategory
from app.core.security import hash_password
from tests.conftest import make_auth_headers

pytestmark = pytest.mark.asyncio


async def setup_test_data(db_session: AsyncSession):
    company = Company(name="Lifecycle Test Co", cnpj=f"123_{uuid4().hex[:6]}")
    db_session.add(company)
    await db_session.commit()

    unit = Unit(name="HQ", code=f"HQ_{uuid4().hex[:4]}", company_id=company.id)
    db_session.add(unit)
    await db_session.commit()

    dept = Sector(name="IT Support", code=f"IT_{uuid4().hex[:4]}", unit_id=unit.id)
    db_session.add(dept)
    await db_session.commit()

    employee = Employee(
        name="Carlos Solicitante",
        registration_number=f"REG_{uuid4().hex[:6]}",
        unit_id=unit.id,
        sector_id=dept.id,
    )
    db_session.add(employee)
    await db_session.commit()

    admin_user = UserAccount(
        email=f"admin_{uuid4().hex[:6]}@test.com",
        hashed_password=hash_password("admin123"),
        employee_id=employee.id,
        is_admin=True,
    )
    db_session.add(admin_user)
    await db_session.commit()

    category = AssetCategory(name=f"Laptop_{uuid4().hex[:4]}", spec_schema={})
    db_session.add(category)

    ticket_cat = TicketCategory(name=f"Suporte_{uuid4().hex[:4]}", default_sector_id=dept.id)
    db_session.add(ticket_cat)
    await db_session.commit()

    return {
        "company": company,
        "unit": unit,
        "dept": dept,
        "employee": employee,
        "admin": admin_user,
        "category": category,
        "ticket_cat": ticket_cat,
    }


async def test_asset_lifecycle_full_cycle(client: AsyncClient, db_session: AsyncSession):
    data = await setup_test_data(db_session)
    headers = make_auth_headers(user_id=str(data["admin"].id), is_admin=True)

    # 1. Cria ativo em estoque (IN_STOCK)
    tag = f"PAT-{uuid4().hex[:6].upper()}"
    create_res = await client.post(
        "/api/v1/assets",
        json={
            "tag": tag,
            "name": "Notebook Dell Latitude",
            "category_id": str(data["category"].id),
            "status": "IN_STOCK",
            "unit_id": str(data["unit"].id),
        },
        headers=headers,
    )
    assert create_res.status_code == 200
    asset_id = create_res.json()["id"]

    # 2. Reserva o ativo para o colaborador
    reserve_res = await client.post(
        f"/api/v1/movements/{asset_id}/reserve",
        json={"employee_id": str(data["employee"].id), "notes": "Reservado para admissão"},
        headers=headers,
    )
    assert reserve_res.status_code == 200
    assert reserve_res.json()["movement_type"] == "RESERVATION"
    assert reserve_res.json()["status_to"] == "RESERVED"

    # Verifica status atual do ativo
    asset = (await client.get(f"/api/v1/assets/{asset_id}", headers=headers)).json()
    assert asset["status"] == "RESERVED"

    # 3. Efetiva a entrega (ASSIGNMENT -> IN_USE)
    deliver_res = await client.post(
        f"/api/v1/movements/{asset_id}/deliver",
        json={"employee_id": str(data["employee"].id), "notes": "Entregue com termo de cautela"},
        headers=headers,
    )
    assert deliver_res.status_code == 200
    assert deliver_res.json()["movement_type"] == "ASSIGNMENT"
    assert deliver_res.json()["status_to"] == "IN_USE"

    asset = (await client.get(f"/api/v1/assets/{asset_id}", headers=headers)).json()
    assert asset["status"] == "IN_USE"
    assert asset["employee_id"] == str(data["employee"].id)

    # 4. Registra devolução física (RETURN -> PENDING_INSPECTION)
    # REGRA FUNDAMENTAL: A devolução física NÃO libera imediatamente para estoque!
    return_res = await client.post(
        f"/api/v1/movements/{asset_id}/return",
        json={"notes": "Equipamento devolvido fisicamente pelo colaborador"},
        headers=headers,
    )
    assert return_res.status_code == 200
    assert return_res.json()["movement_type"] == "RETURN"
    assert return_res.json()["status_to"] == "PENDING_INSPECTION"

    asset = (await client.get(f"/api/v1/assets/{asset_id}", headers=headers)).json()
    assert asset["status"] == "PENDING_INSPECTION"
    assert asset["employee_id"] is None

    # 5. Tentativa de entrega ou reserva enquanto aguarda inspeção DEVE ser bloqueada!
    blocked_delivery = await client.post(
        f"/api/v1/movements/{asset_id}/deliver",
        json={"employee_id": str(data["employee"].id)},
        headers=headers,
    )
    assert blocked_delivery.status_code == 400
    err_msg = blocked_delivery.json().get("error", {}).get("message", "") or blocked_delivery.json().get("detail", "")
    assert "inspeção" in err_msg.lower()

    blocked_reserve = await client.post(
        f"/api/v1/movements/{asset_id}/reserve",
        json={"employee_id": str(data["employee"].id)},
        headers=headers,
    )
    assert blocked_reserve.status_code == 400

    # 6. Realiza a inspeção técnica com aprovação (INSPECTION_RELEASE -> IN_STOCK)
    inspect_res = await client.post(
        f"/api/v1/movements/{asset_id}/inspect",
        json={"approved": True, "notes": "Equipamento revisado, sem avarias. Pronto para uso."},
        headers=headers,
    )
    assert inspect_res.status_code == 200
    assert inspect_res.json()["movement_type"] == "INSPECTION_RELEASE"
    assert inspect_res.json()["status_to"] == "IN_STOCK"

    # Agora sim o ativo está em estoque e liberado para novo ciclo
    asset = (await client.get(f"/api/v1/assets/{asset_id}", headers=headers)).json()
    assert asset["status"] == "IN_STOCK"


async def test_asset_reservation_cancellation(client: AsyncClient, db_session: AsyncSession):
    data = await setup_test_data(db_session)
    headers = make_auth_headers(user_id=str(data["admin"].id), is_admin=True)

    tag = f"PAT-{uuid4().hex[:6].upper()}"
    create_res = await client.post(
        "/api/v1/assets",
        json={
            "tag": tag,
            "name": "Monitor LG 27",
            "category_id": str(data["category"].id),
            "status": "IN_STOCK",
            "unit_id": str(data["unit"].id),
        },
        headers=headers,
    )
    asset_id = create_res.json()["id"]

    # Reserva
    await client.post(
        f"/api/v1/movements/{asset_id}/reserve",
        json={"employee_id": str(data["employee"].id)},
        headers=headers,
    )
    asset = (await client.get(f"/api/v1/assets/{asset_id}", headers=headers)).json()
    assert asset["status"] == "RESERVED"

    # Cancela reserva
    cancel_res = await client.post(
        f"/api/v1/movements/{asset_id}/cancel-reservation",
        headers=headers,
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status_to"] == "IN_STOCK"

    asset = (await client.get(f"/api/v1/assets/{asset_id}", headers=headers)).json()
    assert asset["status"] == "IN_STOCK"


async def test_asset_double_reservation_conflict(client: AsyncClient, db_session: AsyncSession):
    data = await setup_test_data(db_session)
    headers = make_auth_headers(user_id=str(data["admin"].id), is_admin=True)

    tag = f"PAT-{uuid4().hex[:6].upper()}"
    create_res = await client.post(
        "/api/v1/assets",
        json={
            "tag": tag,
            "name": "Teclado Mecanico",
            "category_id": str(data["category"].id),
            "status": "IN_STOCK",
            "unit_id": str(data["unit"].id),
        },
        headers=headers,
    )
    asset_id = create_res.json()["id"]

    # Primeira reserva
    res1 = await client.post(
        f"/api/v1/movements/{asset_id}/reserve",
        json={"employee_id": str(data["employee"].id)},
        headers=headers,
    )
    assert res1.status_code == 200

    # Segunda reserva simultânea / concorrente deve ser rejeitada com 409 Conflict
    res2 = await client.post(
        f"/api/v1/movements/{asset_id}/reserve",
        json={"employee_id": str(data["employee"].id)},
        headers=headers,
    )
    assert res2.status_code == 409


async def test_ticket_asset_lifecycle_integration(client: AsyncClient, db_session: AsyncSession):
    data = await setup_test_data(db_session)
    headers = make_auth_headers(user_id=str(data["admin"].id), is_admin=True)

    # 1. Cria ativo em estoque
    tag = f"PAT-{uuid4().hex[:6].upper()}"
    create_asset_res = await client.post(
        "/api/v1/assets",
        json={
            "tag": tag,
            "name": "MacBook Pro",
            "category_id": str(data["category"].id),
            "status": "IN_STOCK",
            "unit_id": str(data["unit"].id),
        },
        headers=headers,
    )
    asset_id = create_asset_res.json()["id"]

    # 2. Cria chamado vinculando o ativo
    ticket_res = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Solicitação de Equipamento de Trabalho",
            "description": "Necessito de notebook para desenvolvimento.",
            "priority": "HIGH",
            "category_id": str(data["ticket_cat"].id),
            "asset_ids": [asset_id],
        },
        headers=headers,
    )
    assert ticket_res.status_code == 201
    ticket = ticket_res.json()
    ticket_id = ticket["id"]
    assert len(ticket["assets"]) == 1
    assert ticket["assets"][0]["id"] == asset_id

    # 3. Técnico reserva o ativo diretamente pelo chamado
    reserve_call = await client.post(
        f"/api/v1/tickets/{ticket_id}/assets/{asset_id}/reserve",
        json={"notes": "Ativo reservado para atender este chamado"},
        headers=headers,
    )
    assert reserve_call.status_code == 200

    # Verifica que o ativo está RESERVED
    asset_check = (await client.get(f"/api/v1/assets/{asset_id}", headers=headers)).json()
    assert asset_check["status"] == "RESERVED"

    # 4. Técnico entrega o ativo ao solicitante via chamado
    deliver_call = await client.post(
        f"/api/v1/tickets/{ticket_id}/assets/{asset_id}/deliver",
        json={"notes": "Equipamento entregue em mãos com termo assinado"},
        headers=headers,
    )
    assert deliver_call.status_code == 200

    asset_check = (await client.get(f"/api/v1/assets/{asset_id}", headers=headers)).json()
    assert asset_check["status"] == "IN_USE"
    assert asset_check["employee_id"] == str(data["employee"].id)

    # 5. Mais tarde, registra devolução física via chamado
    return_call = await client.post(
        f"/api/v1/tickets/{ticket_id}/assets/{asset_id}/return",
        json={"notes": "Devolvido no encerramento das atividades"},
        headers=headers,
    )
    assert return_call.status_code == 200
    asset_check = (await client.get(f"/api/v1/assets/{asset_id}", headers=headers)).json()
    assert asset_check["status"] == "PENDING_INSPECTION"

    # 6. Técnico faz conferência e libera o ativo
    inspect_call = await client.post(
        f"/api/v1/tickets/{ticket_id}/assets/{asset_id}/inspect",
        json={"approved": True, "notes": "Conferido: tudo em perfeito estado"},
        headers=headers,
    )
    assert inspect_call.status_code == 200
    asset_check = (await client.get(f"/api/v1/assets/{asset_id}", headers=headers)).json()
    assert asset_check["status"] == "IN_STOCK"

    # 7. Verifica histórico do chamado: deve conter todos os eventos do ciclo do ativo!
    history_res = await client.get(f"/api/v1/tickets/{ticket_id}/history", headers=headers)
    assert history_res.status_code == 200
    history = history_res.json()
    event_types = [h["event_type"] for h in history]
    assert "ticket.asset_reserved" in event_types
    assert "ticket.asset_delivered" in event_types
    assert "ticket.asset_returned" in event_types
    assert "ticket.asset_inspected" in event_types

    # 8. Verifica que os movimentos do ativo contêm o ticket_id
    movs = (await client.get(f"/api/v1/movements/asset/{asset_id}", headers=headers)).json()
    ticket_movs = [m for m in movs if m.get("ticket_id") == ticket_id]
    assert len(ticket_movs) >= 4


async def test_inspection_failure_sends_to_maintenance(client: AsyncClient, db_session: AsyncSession):
    data = await setup_test_data(db_session)
    headers = make_auth_headers(user_id=str(data["admin"].id), is_admin=True)

    tag = f"PAT-{uuid4().hex[:6].upper()}"
    create_res = await client.post(
        "/api/v1/assets",
        json={
            "tag": tag,
            "name": "Desktop Dell OptiPlex",
            "category_id": str(data["category"].id),
            "status": "IN_STOCK",
            "unit_id": str(data["unit"].id),
        },
        headers=headers,
    )
    asset_id = create_res.json()["id"]

    # Entrega -> Devolução
    await client.post(
        f"/api/v1/movements/{asset_id}/deliver",
        json={"employee_id": str(data["employee"].id)},
        headers=headers,
    )
    await client.post(
        f"/api/v1/movements/{asset_id}/return",
        headers=headers,
    )

    # Inspeção reprovada: encaminha para manutenção
    inspect_res = await client.post(
        f"/api/v1/movements/{asset_id}/inspect",
        json={"approved": False, "send_to_maintenance": True, "notes": "Fonte queimada"},
        headers=headers,
    )
    assert inspect_res.status_code == 200
    assert inspect_res.json()["status_to"] == "MAINTENANCE"

    asset = (await client.get(f"/api/v1/assets/{asset_id}", headers=headers)).json()
    assert asset["status"] == "MAINTENANCE"

    # Libera da manutenção pós-conserto
    release_res = await client.post(
        f"/api/v1/movements/{asset_id}/inspect",
        json={"approved": True, "notes": "Fonte substituída e testada com sucesso"},
        headers=headers,
    )
    assert release_res.status_code == 200
    assert release_res.json()["status_to"] == "IN_STOCK"

    asset = (await client.get(f"/api/v1/assets/{asset_id}", headers=headers)).json()
    assert asset["status"] == "IN_STOCK"


async def test_link_and_unlink_asset_to_ticket(client: AsyncClient, db_session: AsyncSession):
    data = await setup_test_data(db_session)
    headers = make_auth_headers(
        str(data["admin"].id),
        is_admin=True,
        permissions=["assets.read", "assets.write", "service_desk.tickets.read", "service_desk.tickets.write"],
    )

    # 1. Cria ativo
    create_res = await client.post(
        "/api/v1/assets",
        json={
            "tag": f"LNK-{uuid4().hex[:6].upper()}",
            "name": "Monitor Samsung 27",
            "category_id": str(data["category"].id),
            "status": "IN_STOCK",
            "unit_id": str(data["unit"].id),
        },
        headers=headers,
    )
    asset_id = create_res.json()["id"]

    # 2. Cria chamado sem ativos
    ticket_res = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Configuração de monitor secundário",
            "description": "Colaborador solicitou tela adicional",
            "priority": "LOW",
            "category_id": str(data["ticket_cat"].id),
            "asset_ids": [],
        },
        headers=headers,
    )
    ticket_id = ticket_res.json()["id"]
    assert len(ticket_res.json()["assets"]) == 0

    # 3. Vincula o ativo ao chamado existente
    link_res = await client.post(
        f"/api/v1/tickets/{ticket_id}/assets/{asset_id}",
        headers=headers,
    )
    assert link_res.status_code == 200

    # Verifica no chamado
    get_ticket_res = await client.get(f"/api/v1/tickets/{ticket_id}", headers=headers)
    assert get_ticket_res.status_code == 200
    assets = get_ticket_res.json()["assets"]
    assert len(assets) == 1
    assert assets[0]["id"] == asset_id

    # 4. Verifica na listagem de chamados do ativo
    asset_tickets_res = await client.get(f"/api/v1/assets/{asset_id}/tickets", headers=headers)
    assert asset_tickets_res.status_code == 200
    asset_tickets = asset_tickets_res.json()
    assert len(asset_tickets) == 1
    assert asset_tickets[0]["id"] == ticket_id

    # 5. Verifica linha do tempo / histórico
    history_res = await client.get(f"/api/v1/tickets/{ticket_id}/history", headers=headers)
    assert history_res.status_code == 200
    history = history_res.json()
    assert any(h["event_type"] == "ticket.asset_linked" for h in history)

    # 6. Desvincula o ativo do chamado
    unlink_res = await client.delete(
        f"/api/v1/tickets/{ticket_id}/assets/{asset_id}",
        headers=headers,
    )
    assert unlink_res.status_code == 200

    # Verifica que foi removido
    get_ticket_after = await client.get(f"/api/v1/tickets/{ticket_id}", headers=headers)
    assert len(get_ticket_after.json()["assets"]) == 0

