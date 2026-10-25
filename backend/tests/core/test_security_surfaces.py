"""
Regressões da auditoria de segurança: carga de QA desligada por padrão e teste de SMTP
que não entrega a senha guardada a outro servidor.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.config import get_settings
from app.notifications import email_service
from app.notifications.email_service import EmailService, SmtpConfigSchema
from tests.factories import headers_for, make_user

pytestmark = pytest.mark.asyncio

SEED_TEST = "/api/v1/system/demo/seed-test"
EMAIL_TEST = "/api/v1/notifications/email/test"
EMAIL_CONFIG = "/api/v1/notifications/email/config"

SAVED = dict(host="smtp.empresa.local", port=587, security="STARTTLS", username="svc", password="segredo-guardado")


async def _manager(db: AsyncSession):
    user = await make_user(db)
    return user, headers_for(user, "system.backup.manage", "system.demo.manage")


async def _save_smtp(db: AsyncSession) -> None:
    await EmailService(db).update_config(SmtpConfigSchema(is_enabled=True, **SAVED))


@pytest.fixture
def captured(monkeypatch):
    calls: list[SmtpConfigSchema] = []

    def fake_send(config, to, subject, html, text):
        calls.append(config)
        return "ok", "enviado"

    monkeypatch.setattr(email_service, "send_smtp_raw", fake_send)
    return calls


async def test_qa_seed_is_disabled_by_default(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    called = []

    async def fake_seed(reset=False):
        called.append(reset)

    monkeypatch.setattr("app.seed_test.seed_test", fake_seed)
    _, headers = await _manager(db_session)

    assert get_settings().ENABLE_QA_SEED is False
    resp = await client.post(SEED_TEST, headers=headers)

    assert resp.status_code == 403
    assert "ENABLE_QA_SEED" in resp.json()["error"]["message"]
    assert called == []


async def test_qa_seed_runs_only_when_explicitly_enabled(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    called = []

    async def fake_seed(reset=False):
        called.append(reset)

    monkeypatch.setattr("app.seed_test.seed_test", fake_seed)
    monkeypatch.setattr(get_settings(), "ENABLE_QA_SEED", True)
    _, headers = await _manager(db_session)

    resp = await client.post(SEED_TEST, headers=headers)

    assert resp.status_code == 201
    assert called == [False]


async def test_qa_seed_still_requires_permission(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr(get_settings(), "ENABLE_QA_SEED", True)
    user = await make_user(db_session)
    resp = await client.post(SEED_TEST, headers=headers_for(user, "tickets.read"))
    assert resp.status_code == 403


async def test_smtp_test_refuses_stored_password_for_another_host(
    client: AsyncClient, db_session: AsyncSession, captured
):
    await _save_smtp(db_session)
    _, headers = await _manager(db_session)

    resp = await client.post(
        EMAIL_TEST,
        json={"target_email": "a@b.com", "host": "capturador.exemplo.net", "password": "********"},
        headers=headers,
    )

    assert resp.status_code == 400
    assert captured == []  # nada foi enviado, logo a senha guardada não saiu


@pytest.mark.parametrize("override", [{"port": 2525}, {"username": "outro"}])
async def test_smtp_test_refuses_stored_password_for_other_port_or_user(
    client: AsyncClient, db_session: AsyncSession, captured, override
):
    await _save_smtp(db_session)
    _, headers = await _manager(db_session)

    resp = await client.post(EMAIL_TEST, json={"target_email": "a@b.com", **override}, headers=headers)

    assert resp.status_code == 400
    assert captured == []


async def test_smtp_test_uses_typed_password_for_another_host(client: AsyncClient, db_session: AsyncSession, captured):
    await _save_smtp(db_session)
    _, headers = await _manager(db_session)

    resp = await client.post(
        EMAIL_TEST,
        json={"target_email": "a@b.com", "host": "novo.exemplo.net", "password": "digitada"},
        headers=headers,
    )

    assert resp.status_code == 200
    assert captured[0].host == "novo.exemplo.net" and captured[0].password == "digitada"


async def test_smtp_test_with_saved_endpoint_reuses_stored_password(
    client: AsyncClient, db_session: AsyncSession, captured
):
    await _save_smtp(db_session)
    _, headers = await _manager(db_session)

    resp = await client.post(
        EMAIL_TEST,
        json={
            "target_email": "a@b.com",
            "host": "SMTP.Empresa.Local",
            "port": 587,
            "username": "svc",
            "password": "********",
        },
        headers=headers,
    )

    assert resp.status_code == 200
    assert captured[0].password == "segredo-guardado"


async def test_smtp_config_change_and_test_are_audited_without_secrets(
    client: AsyncClient, db_session: AsyncSession, captured
):
    user, headers = await _manager(db_session)
    body = {**SAVED, "is_enabled": True, "password": "segredo-novo"}

    assert (await client.put(EMAIL_CONFIG, json=body, headers=headers)).status_code == 200
    assert (await client.post(EMAIL_TEST, json={"target_email": "a@b.com"}, headers=headers)).status_code == 200

    stmt = select(AuditLog).where(AuditLog.event_type.like("notifications.email_%"))
    logs = (await db_session.execute(stmt)).scalars().all()
    assert {log.event_type for log in logs} == {"notifications.email_configured", "notifications.email_tested"}
    assert all(log.user_id == user.id for log in logs)
    assert "segredo" not in str([log.data for log in logs])


async def test_api_docs_are_off_by_default_and_can_be_turned_on(monkeypatch):
    from app.config import Settings
    from app.main import create_app

    assert Settings.model_fields["ENABLE_API_DOCS"].default is False
    monkeypatch.setattr(get_settings(), "ENABLE_API_DOCS", False)
    app = create_app()
    assert app.docs_url is None and app.redoc_url is None and app.openapi_url is None
    monkeypatch.setattr(get_settings(), "ENABLE_API_DOCS", True)
    assert create_app().openapi_url is not None
