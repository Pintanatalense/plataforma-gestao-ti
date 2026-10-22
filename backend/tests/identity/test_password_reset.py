"""
ADR-018: recuperação de senha por e-mail. Desligada por padrão; token de uso único com hash; sem enumeração de contas;
limites por e-mail e por IP; a confirmação derruba as sessões abertas.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.core.security import hash_password
from app.identity import password_reset as pr
from app.identity.models import PasswordResetRequest, UserAccount
from app.notifications.email_service import EmailService, SmtpConfigSchema
from tests.factories import headers_for, make_user

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/identity"
OLD = "senha-antiga-1"
NEW = "senha-nova-forte-2"
ADMIN_PERMS = ("system.backup.manage",)


@pytest.fixture
def sent(monkeypatch):
    """Captura os e-mails em vez de falar com um servidor SMTP."""
    box: list[dict] = []

    def fake(config, to_email, subject, html, text=None):
        box.append({"to": to_email, "subject": subject, "html": html, "text": text or ""})
        return "ok", "ok"

    monkeypatch.setattr(pr, "send_smtp_raw", fake)
    return box


async def _smtp(db: AsyncSession, *, enabled=True, security="STARTTLS", homologated=True) -> None:
    service = EmailService(db)
    cfg = SmtpConfigSchema(
        is_enabled=enabled, host="smtp.test", port=587, security=security, username="u", password="p",
        from_email="ti@test.com", app_base_url="https://ti.test",
    )
    await service.update_config(cfg)
    if homologated:
        await service._mark_homologated(await service.get_config())


async def _enable(db: AsyncSession) -> None:
    await pr.PasswordResetService(db).set_enabled(True, None)


async def _user(db: AsyncSession, email: str = "maria@test.com") -> UserAccount:
    user = UserAccount(email=email, hashed_password=hash_password(OLD))
    db.add(user)
    await db.commit()
    return user


def _token_from(mail: dict) -> str:
    match = re.search(r"token=([A-Za-z0-9_\-]+)", mail["text"])
    assert match, mail["text"]
    return match.group(1)


async def _ready(db: AsyncSession) -> None:
    await _smtp(db)
    await _enable(db)


async def test_disabled_by_default_everything_is_404(client: AsyncClient, db_session: AsyncSession, sent):
    assert (await client.get(f"{BASE}/password-reset/status")).json() == {"enabled": False}
    assert (await client.post(f"{BASE}/password-reset/request", json={"email": "a@b.com"})).status_code == 404
    assert (
        await client.post(f"{BASE}/password-reset/confirm", json={"token": "x" * 30, "new_password": NEW})
    ).status_code == 404
    assert sent == []


async def test_cannot_enable_without_a_homologated_tls_smtp(client: AsyncClient, db_session: AsyncSession):
    admin = await make_user(db_session, is_admin=True)
    h = headers_for(admin, *ADMIN_PERMS)

    async def put(enabled=True):
        return await client.put("/api/v1/notifications/email/password-reset", json={"enabled": enabled}, headers=h)

    await _smtp(db_session, enabled=False, homologated=False)
    assert (await put()).status_code == 400  # SMTP desligado
    await _smtp(db_session, homologated=False)
    assert (await put()).status_code == 400  # nunca testado
    await _smtp(db_session, security="NONE")
    assert (await put()).status_code == 400  # sem TLS
    await _smtp(db_session)
    ok = await put()
    assert ok.status_code == 200 and ok.json() == {"enabled": True, "smtp_ready": True}
    assert (await client.get(f"{BASE}/password-reset/status")).json() == {"enabled": True}


async def test_changing_the_smtp_server_drops_the_homologation(client: AsyncClient, db_session: AsyncSession):
    await _ready(db_session)
    service = EmailService(db_session)
    cfg = await service.get_config()
    cfg.host = "outro.smtp.test"
    await service.update_config(cfg)
    # a flag continua ligada, mas o SMTP já não está homologado: a recuperação some
    assert (await client.get(f"{BASE}/password-reset/status")).json() == {"enabled": False}


async def test_full_flow_resets_password_and_ends_sessions(client: AsyncClient, db_session: AsyncSession, sent):
    await _ready(db_session)
    user = await _user(db_session)
    old_session = (await client.post(f"{BASE}/login", data={"username": user.email, "password": OLD})).json()
    old_headers = {"Authorization": f"Bearer {old_session['access_token']}"}
    assert (await client.get(f"{BASE}/me", headers=old_headers)).status_code == 200
    user.must_change_password = True
    user.failed_login_count = 4
    await db_session.commit()

    resp = await client.post(f"{BASE}/password-reset/request", json={"email": " Maria@Test.com "})
    assert resp.status_code == 202
    assert len(sent) == 1 and sent[0]["to"] == "maria@test.com"
    assert "https://ti.test/reset-password?token=" in sent[0]["text"]
    token = _token_from(sent[0])

    done = await client.post(f"{BASE}/password-reset/confirm", json={"token": token, "new_password": NEW})
    assert done.status_code == 204

    assert (await client.post(f"{BASE}/login", data={"username": user.email, "password": OLD})).status_code == 401
    login = await client.post(f"{BASE}/login", data={"username": user.email, "password": NEW})
    assert login.status_code == 200
    await db_session.refresh(user)
    assert user.must_change_password is False and user.failed_login_count == 0
    # a sessão aberta com a senha antiga caiu
    assert (await client.get(f"{BASE}/me", headers=old_headers)).status_code == 401


async def test_token_is_single_use_and_stored_only_as_hash(client: AsyncClient, db_session: AsyncSession, sent):
    await _ready(db_session)
    await _user(db_session)
    await client.post(f"{BASE}/password-reset/request", json={"email": "maria@test.com"})
    token = _token_from(sent[0])

    stored = (await db_session.execute(select(PasswordResetRequest.token_hash))).scalars().all()
    assert token not in stored and pr.hash_secret(token) in stored

    assert (await client.post(f"{BASE}/password-reset/confirm", json={"token": token, "new_password": NEW})).status_code == 204
    again = await client.post(f"{BASE}/password-reset/confirm", json={"token": token, "new_password": "outra-senha-3"})
    assert again.status_code == 422 and pr.INVALID_LINK in again.text


async def test_expired_forged_and_superseded_tokens_are_refused_with_the_same_message(
    client: AsyncClient, db_session: AsyncSession, sent
):
    await _ready(db_session)
    await _user(db_session)
    await client.post(f"{BASE}/password-reset/request", json={"email": "maria@test.com"})
    first = _token_from(sent[0])
    await client.post(f"{BASE}/password-reset/request", json={"email": "maria@test.com"})
    second = _token_from(sent[1])

    forged = "f" * 43
    for bad in (first, forged):  # o primeiro foi invalidado pelo segundo pedido
        resp = await client.post(f"{BASE}/password-reset/confirm", json={"token": bad, "new_password": NEW})
        assert resp.status_code == 422 and pr.INVALID_LINK in resp.text

    row = (
        await db_session.execute(select(PasswordResetRequest).where(PasswordResetRequest.token_hash == pr.hash_secret(second)))
    ).scalar_one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()
    expired = await client.post(f"{BASE}/password-reset/confirm", json={"token": second, "new_password": NEW})
    assert expired.status_code == 422 and pr.INVALID_LINK in expired.text


async def test_unknown_account_gets_the_same_answer_and_no_email(client: AsyncClient, db_session: AsyncSession, sent):
    await _ready(db_session)
    await _user(db_session)
    known = await client.post(f"{BASE}/password-reset/request", json={"email": "maria@test.com"})
    unknown = await client.post(f"{BASE}/password-reset/request", json={"email": "ninguem@test.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(sent) == 1  # nada foi enviado para quem não existe


async def test_inactive_account_is_treated_as_unknown(client: AsyncClient, db_session: AsyncSession, sent):
    await _ready(db_session)
    user = await _user(db_session)
    user.is_active = False
    await db_session.commit()
    assert (await client.post(f"{BASE}/password-reset/request", json={"email": user.email})).status_code == 202
    assert sent == []


async def test_per_email_limit_is_silent(client: AsyncClient, db_session: AsyncSession, sent):
    await _ready(db_session)
    await _user(db_session)
    statuses = [
        (await client.post(f"{BASE}/password-reset/request", json={"email": "maria@test.com"})).status_code
        for _ in range(5)
    ]
    assert statuses == [202] * 5
    assert len(sent) == pr.LIMIT_PER_EMAIL  # do 4º pedido em diante: 202, sem token e sem e-mail


async def test_per_ip_limit_counts_unknown_addresses_too(client: AsyncClient, db_session: AsyncSession, sent):
    await _ready(db_session)
    await _user(db_session)
    headers = {"X-Forwarded-For": "203.0.113.9"}
    for i in range(pr.LIMIT_PER_IP):
        await client.post(f"{BASE}/password-reset/request", json={"email": f"x{i}@test.com"}, headers=headers)
    resp = await client.post(f"{BASE}/password-reset/request", json={"email": "maria@test.com"}, headers=headers)
    assert resp.status_code == 202
    assert sent == []  # o IP estourou o limite: nem a conta real recebeu


async def test_smtp_failure_still_answers_202_and_never_logs_the_token(
    client: AsyncClient, db_session: AsyncSession, monkeypatch, caplog
):
    await _ready(db_session)
    await _user(db_session)
    seen: list[str] = []

    def failing(config, to_email, subject, html, text=None):
        seen.append(text or "")
        return "retryable", "conexão recusada"

    monkeypatch.setattr(pr, "send_smtp_raw", failing)

    monkeypatch.setattr(pr, "AsyncSessionLocal", lambda: (_ for _ in ()).throw(RuntimeError("sem banco")))
    with caplog.at_level(logging.DEBUG, logger="app"):
        resp = await client.post(f"{BASE}/password-reset/request", json={"email": "maria@test.com"})
    assert resp.status_code == 202
    token = _token_from({"text": seen[0]})
    app_logs = " ".join(r.getMessage() for r in caplog.records if r.name.startswith("app"))
    assert token not in app_logs and "maria@test.com" not in app_logs
    assert "Falha ao enviar e-mail de recuperação de senha" in app_logs


async def test_audit_trail_has_no_token_or_password(client: AsyncClient, db_session: AsyncSession, sent):
    await _ready(db_session)
    await _user(db_session)
    await client.post(f"{BASE}/password-reset/request", json={"email": "maria@test.com"})
    token = _token_from(sent[0])
    await client.post(f"{BASE}/password-reset/confirm", json={"token": token, "new_password": NEW})

    logs = (await db_session.execute(select(AuditLog).where(AuditLog.event_type.like("identity.password_reset_%")))).scalars().all()
    kinds = {log.event_type for log in logs}
    assert {"identity.password_reset_configured", "identity.password_reset_requested", "identity.password_reset_completed"} <= kinds
    dump = " ".join(str(log.data) for log in logs)
    assert token not in dump and NEW not in dump and "maria@test.com" not in dump


async def test_new_password_must_have_at_least_8_characters(client: AsyncClient, db_session: AsyncSession, sent):
    await _ready(db_session)
    await _user(db_session)
    await client.post(f"{BASE}/password-reset/request", json={"email": "maria@test.com"})
    resp = await client.post(f"{BASE}/password-reset/confirm", json={"token": _token_from(sent[0]), "new_password": "curta"})
    assert resp.status_code == 422


async def test_admin_config_requires_permission(client: AsyncClient, db_session: AsyncSession):
    user = await make_user(db_session)
    resp = await client.put(
        "/api/v1/notifications/email/password-reset", json={"enabled": True}, headers=headers_for(user)
    )
    assert resp.status_code == 403
