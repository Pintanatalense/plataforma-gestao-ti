"""Enviar teste para a própria conta no Telegram e no Slack (rota /notifications/channels/{canal}/test-send)."""
import json
from datetime import datetime, timezone

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.notifications import channels_router
from app.notifications.channel_store import save_channel
from app.notifications.models import UserChannelAddress
from app.notifications.telegram_poller import SenderRateLimiter
from tests.factories import headers_for, make_employee, make_org, make_user

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/notifications"


class Fake:
    """Substitui a API do Telegram e a do Slack: registra as chamadas de envio e responde como o provedor."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.telegram_response: tuple[int, dict] = (200, {"ok": True, "result": {"message_id": 5}})
        self.slack_response: tuple[int, dict] = (200, {"ok": True, "ts": "1760000000.000100"})

    def handler(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content or b"{}")
        path = request.url.path
        if path.endswith("/sendMessage"):
            self.sent.append(("telegram", payload))
            return httpx.Response(self.telegram_response[0], json=self.telegram_response[1])
        if "chat.postMessage" in path:
            self.sent.append(("slack", payload))
            return httpx.Response(self.slack_response[0], json=self.slack_response[1])
        return httpx.Response(200, json={"ok": True, "result": {"username": "gti_bot"}})


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Fake:
    fake = Fake()
    for module in ("telegram", "slack"):
        monkeypatch.setattr(
            f"app.notifications.channels.{module}.http_client",
            lambda timeout=15.0: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)),
        )
    monkeypatch.setattr(channels_router, "_self_test_limiter", SenderRateLimiter(limit=5, window=3600.0))
    return fake


async def _enable(db: AsyncSession) -> None:
    await save_channel(db, "telegram", True, {"bot_username": "gti_bot"}, {"bot_token": "123:ABC"})
    await save_channel(db, "slack", True, {"bot_name": "gti"}, {"bot_token": "xoxb-1", "signing_secret": "s"})
    await db.commit()


async def _link(db: AsyncSession, user, channel: str, address: str) -> None:
    db.add(UserChannelAddress(user_id=user.id, channel=channel, address=address, verified_at=datetime.now(timezone.utc)))
    await db.commit()


async def _admin(db: AsyncSession):
    return await make_user(db, is_admin=True)


@pytest.mark.parametrize("channel,address,key", [("telegram", "987654321", "chat_id"), ("slack", "U0123ABCD", "channel")])
async def test_sends_to_the_admins_own_linked_account(client: AsyncClient, db_session: AsyncSession, fake: Fake, channel, address, key):
    admin = await _admin(db_session)
    await _enable(db_session)
    await _link(db_session, admin, channel, address)

    resp = await client.post(f"{BASE}/channels/{channel}/test-send", headers=headers_for(admin))
    assert resp.status_code == 200 and resp.json()["ok"] is True
    [(provider, payload)] = fake.sent
    assert provider == channel and payload[key] == address and "Teste do canal" in json.dumps(payload)

    audit = (await db_session.execute(select(AuditLog).where(AuditLog.event_type == f"notifications.{channel}_test_sent"))).scalar_one()
    assert audit.data == {"outcome": "ok"}


async def test_without_a_linked_account_it_explains_how_to_link_and_sends_nothing(client: AsyncClient, db_session: AsyncSession, fake: Fake):
    admin = await _admin(db_session)
    await _enable(db_session)
    resp = await client.post(f"{BASE}/channels/telegram/test-send", headers=headers_for(admin))
    assert resp.status_code >= 400 and "Minhas preferências" in resp.text
    assert fake.sent == []


async def test_does_not_use_another_persons_link_nor_an_unverified_one(client: AsyncClient, db_session: AsyncSession, fake: Fake):
    admin = await _admin(db_session)
    other = await make_user(db_session, await make_employee(db_session, await make_org(db_session)))
    await _enable(db_session)
    await _link(db_session, other, "telegram", "111")
    db_session.add(UserChannelAddress(user_id=admin.id, channel="telegram", address="222", verified_at=None))
    await db_session.commit()
    resp = await client.post(f"{BASE}/channels/telegram/test-send", headers=headers_for(admin))
    assert resp.status_code >= 400 and fake.sent == []


async def test_reports_the_provider_refusal(client: AsyncClient, db_session: AsyncSession, fake: Fake):
    admin = await _admin(db_session)
    await _enable(db_session)
    await _link(db_session, admin, "telegram", "987654321")
    fake.telegram_response = (403, {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"})
    body = (await client.post(f"{BASE}/channels/telegram/test-send", headers=headers_for(admin))).json()
    assert body["ok"] is False and body["detail"]


async def test_requires_an_enabled_channel_a_supported_channel_and_the_permission(client: AsyncClient, db_session: AsyncSession, fake: Fake):
    admin = await _admin(db_session)
    user = await make_user(db_session, await make_employee(db_session, await make_org(db_session)))
    off = await client.post(f"{BASE}/channels/telegram/test-send", headers=headers_for(admin))
    assert off.status_code >= 400 and "Habilite" in off.text

    await _enable(db_session)
    await _link(db_session, user, "telegram", "333")
    assert (await client.post(f"{BASE}/channels/telegram/test-send", headers=headers_for(user))).status_code == 403
    for other_channel in ("whatsapp", "email", "inexistente"):
        resp = await client.post(f"{BASE}/channels/{other_channel}/test-send", headers=headers_for(admin))
        assert resp.status_code >= 400 and "Telegram e Slack" in resp.text, other_channel
    assert fake.sent == []


async def test_is_rate_limited_per_admin_and_channel(client: AsyncClient, db_session: AsyncSession, fake: Fake, monkeypatch):
    monkeypatch.setattr(channels_router, "_self_test_limiter", SenderRateLimiter(limit=2, window=3600.0))
    admin = await _admin(db_session)
    await _enable(db_session)
    await _link(db_session, admin, "telegram", "987654321")
    await _link(db_session, admin, "slack", "U0123ABCD")
    h = headers_for(admin)
    for _ in range(2):
        assert (await client.post(f"{BASE}/channels/telegram/test-send", headers=h)).status_code == 200
    limited = await client.post(f"{BASE}/channels/telegram/test-send", headers=h)
    assert limited.status_code >= 400 and "Limite" in limited.text
    assert (await client.post(f"{BASE}/channels/slack/test-send", headers=h)).status_code == 200  # outro canal, outra cota
