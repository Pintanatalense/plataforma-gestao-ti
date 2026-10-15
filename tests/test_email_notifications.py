"""
Teste automatizado para o Módulo de E-mail & Notificações (MOD-11):
1. Configuração e mascaramento de credenciais SMTP.
2. Endpoint de teste de conectividade.
3. Validação estrita da regra de privacidade DEC-012:
   - Respostas públicas notificam o solicitante.
   - Notas internas NUNCA notificam o solicitante.
"""

import asyncio
import uuid
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from app.database import AsyncSessionLocal
from app.notifications.email_service import EmailService, SmtpConfigSchema, SmtpTestEmailRequest
from app.identity.models import UserAccount
from app.organization.models import Employee
from app.service_desk.models import Ticket, TicketInteraction


async def run_email_tests():
    print("--- INICIANDO TESTES DO MÓDULO DE E-MAIL & NOTIFICAÇÕES ---")

    # 1. Testes via HTTP API
    client = httpx.AsyncClient(base_url="http://localhost", timeout=20.0)

    # Login Admin
    r_login = await client.post("/api/v1/identity/login", data={"username": "admin@empresa.com.br", "password": "Demo@2026"})
    assert r_login.status_code == 200, f"Falha no login: {r_login.text}"
    token = r_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Atualizar Configuração SMTP
    smtp_payload = {
        "is_enabled": True,
        "host": "smtp.exemplo.com.br",
        "port": 587,
        "security": "STARTTLS",
        "username": "smtp_user@exemplo.com.br",
        "password": "SecretPassword123!",
        "from_email": "chamados@empresa.com.br",
        "from_name": "Service Desk Central",
        "app_base_url": "http://localhost"
    }
    r_put = await client.put("/api/v1/notifications/email/config", json=smtp_payload, headers=headers)
    assert r_put.status_code == 200, f"Falha ao salvar config SMTP: {r_put.text}"
    saved_cfg = r_put.json()
    assert saved_cfg["password"] == "********", "Senha deveria estar mascarada na resposta do PUT"
    print("1. PUT /notifications/email/config: OK (Senha mascarada: '********')")

    # Obter Configuração SMTP
    r_get = await client.get("/api/v1/notifications/email/config", headers=headers)
    assert r_get.status_code == 200
    cfg = r_get.json()
    assert cfg["host"] == "smtp.exemplo.com.br"
    assert cfg["password"] == "********", "Senha deve estar mascarada no GET"
    assert cfg["is_enabled"] is True
    print("2. GET /notifications/email/config: OK (Credenciais protegidas fora do frontend)")

    # 2. Testes de Regra de Negócio e Privacidade DEC-012
    async with AsyncSessionLocal() as session:
        service = EmailService(session)

        # Mock dos objetos de domínio
        solicitante_user = UserAccount(
            id=uuid.uuid4(),
            email="solicitante.real@cliente.com.br",
            is_active=True
        )
        solicitante_emp = Employee(
            id=uuid.uuid4(),
            name="João Solicitante",
            registration_number="FUNC-9999",
            unit_id=uuid.uuid4(),
            sector_id=uuid.uuid4()
        )
        solicitante_emp.user_account = solicitante_user

        tecnico_user = UserAccount(
            id=uuid.uuid4(),
            email="tecnico.ti@empresa.com.br",
            is_active=True
        )

        ticket = Ticket(
            id=uuid.uuid4(),
            title="Falha de conexão com VPN",
            description="Não consigo autenticar na VPN corporativa.",
            priority="HIGH",
            status="IN_PROGRESS",
            requester_id=solicitante_emp.id,
            assignee_id=tecnico_user.id
        )
        ticket.requester = solicitante_emp
        ticket.assignee = tecnico_user

        # Cenário A: Técnico adiciona NOTA INTERNA (is_internal=True)
        # REGRA DEC-012: O solicitante NUNCA deve receber essa mensagem!
        nota_interna = TicketInteraction(
            id=uuid.uuid4(),
            ticket_id=ticket.id,
            author_id=tecnico_user.id,
            message="Diagnóstico interno: O usuário está com a conta bloqueada no Active Directory.",
            is_internal=True
        )

        with patch.object(service, "send_email", new_callable=AsyncMock) as mock_send:
            await service.notify_ticket_interaction(ticket, nota_interna, author=tecnico_user)
            # Como o autor é o próprio técnico, e é nota interna, NENHUM e-mail vai para o solicitante!
            for call in mock_send.call_args_list:
                to_addr = call.kwargs.get("to_email")
                assert to_addr != solicitante_user.email, f"VIOLAÇÃO CRÍTICA DEC-012: Solicitante {to_addr} recebeu nota interna!"
            assert mock_send.call_count == 0
            print("3. DEC-012 (Nota Interna): 100% SEGURO — Solicitante JAMAIS notificado de nota interna.")

        # Cenário B: Técnico adiciona RESPOSTA PÚBLICA (is_internal=False)
        resposta_publica = TicketInteraction(
            id=uuid.uuid4(),
            ticket_id=ticket.id,
            author_id=tecnico_user.id,
            message="Olá João, realizamos o reset da sua credencial de VPN. Por favor, tente novamente.",
            is_internal=False
        )

        with patch.object(service, "send_email", new_callable=AsyncMock) as mock_send:
            await service.notify_ticket_interaction(ticket, resposta_publica, author=tecnico_user)
            assert mock_send.call_count == 1
            call_kwargs = mock_send.call_args.kwargs
            assert call_kwargs["to_email"] == "solicitante.real@cliente.com.br"
            assert "Falha de conexão com VPN" in call_kwargs["subject"]
            assert "Olá João, realizamos o reset" in call_kwargs["html_body"]
            print("4. Resposta Pública do Técnico -> Solicitante notificado por e-mail com sucesso.")

        # Cenário C: Solicitante responde publicamente no chamado
        resposta_solicitante = TicketInteraction(
            id=uuid.uuid4(),
            ticket_id=ticket.id,
            author_id=solicitante_user.id,
            message="Funcionou perfeitamente, muito obrigado!",
            is_internal=False
        )

        with patch.object(service, "send_email", new_callable=AsyncMock) as mock_send:
            await service.notify_ticket_interaction(ticket, resposta_solicitante, author=solicitante_user)
            assert mock_send.call_count == 1
            call_kwargs = mock_send.call_args.kwargs
            assert call_kwargs["to_email"] == "tecnico.ti@empresa.com.br"
            print("5. Resposta Pública do Solicitante -> Técnico responsável notificado por e-mail com sucesso.")

    print("\n>>> ALL 5 EMAIL & PRIVACY (DEC-012) TESTS PASSED SUCCESSFULLY! <<<")


if __name__ == "__main__":
    asyncio.run(run_email_tests())
