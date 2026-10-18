"""Slack no hub (ADR-013, Fase E): assinatura + replay, mensagens diretas, vínculo, envio, config."""
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.notifications import slack_webhook
from app.notifications.channel_store import load_channel, save_channel
from app.notifications.channels.base import AdapterContext, Message, Recipient
from app.notifications.channels.slack import SlackAdapter, classify, render_text
from app.notifications.dispatcher import Dispatcher
from app.notifications.fanout import plan_event
from app.notifications.linking import create_link_code
from app.notifications.models import ChannelConfig, Delivery, DomainEvent, NotificationRule, UserChannelAddress
from app.notifications.rules_seed import seed_notification_rules
from app.notifications.telegram_poller import SenderRateLimiter
from tests.factories import headers_for, make_employee, make_org, make_user

pytestmark = pytest.mark.asyncio

EVENTS = "/api/v1/integrations/slack/events"
BASE = "/api/v1/notifications"
SIGNING = "slack-signing-secret"
SessionFactory: async_sessionmaker = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _bind(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    global SessionFactory
    SessionFactory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.notifications.fanout.quiet_until", lambda *a, **k: None)
    monkeypatch.setattr(slack_webhook, "_limiter", SenderRateLimiter(limit=1000))


class FakeSlack:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, str]] = []
        self.post_responses: list[httpx.Response] = []
        self.auth_test: dict = {"ok": True, "user": "gti_bot", "team": "Empresa"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        self.calls.append((method, json.loads(request.content or b"{}"), request.headers.get("authorization", "")))
        if method == "auth.test":
            return httpx.Response(200, json=self.auth_test)
        if self.post_responses:
            return self.post_responses.pop(0)
        return httpx.Response(200, json={"ok": True, "ts": "1760000000.000100"})

    def sent(self) -> list[dict]:
        return [p for m, p, _ in self.calls if m == "chat.postMessage"]


@pytest.fixture
def slack(monkeypatch: pytest.MonkeyPatch) -> FakeSlack:
    fake = FakeSlack()
    monkeypatch.setattr(
        "app.notifications.channels.slack.http_client",
        lambda timeout=15.0: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)),
    )
    return fake


@dataclass
class World:
    requester: object
    attendant: object
    admin: object


async def _configure(db: AsyncSession, enabled: bool = True) -> None:
    await save_channel(
        db, "slack", enabled, {"bot_name": "gti_bot", "app_base_url": "http://sys"},
        {"bot_token": "xoxb-TOKEN", "signing_secret": SIGNING},
    )
    await db.commit()


@pytest.fixture
async def world(db_session: AsyncSession) -> World:
    org = await make_org(db_session)
    requester = await make_user(db_session, await make_employee(db_session, org))
    attendant = await make_user(db_session, await make_employee(db_session, org))
    admin = await make_user(db_session, is_admin=True)
    await seed_notification_rules(db_session)
    await _configure(db_session)
    return World(requester, attendant, admin)


def sign(raw: bytes, ts: int | None = None, secret: str = SIGNING) -> dict:
    stamp = str(ts if ts is not None else int(time.time()))
    digest = hmac.new(secret.encode(), b"v0:" + stamp.encode() + b":" + raw, hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-Slack-Request-Timestamp": stamp, "X-Slack-Signature": f"v0={digest}"}


def dm(text: str, user="U111", ts: str | None = None, **extra) -> dict:
    event = {"type": "message", "channel_type": "im", "channel": "D1", "user": user, "text": text, "ts": ts or f"{time.time():.6f}"}
    return {"type": "event_callback", "event_id": f"Ev{uuid.uuid4().hex[:8]}", "event": {**event, **extra}}


async def post(client: AsyncClient, payload: dict, **sign_kwargs):
    raw = json.dumps(payload).encode()
    return await client.post(EVENTS, content=raw, headers=sign(raw, **sign_kwargs))


async def replies(db: AsyncSession) -> list[Delivery]:
    rows = await db.execute(select(Delivery).where(Delivery.channel == "slack").order_by(Delivery.created_at))
    return list(rows.scalars())


# --- Assinatura e replay --------------------------------------------------------------------------


async def test_unsigned_or_wrongly_signed_requests_are_rejected(client: AsyncClient, db_session: AsyncSession, world: World):
    raw = json.dumps(dm("menu")).encode()
    assert (await client.post(EVENTS, content=raw)).status_code == 401
    assert (await client.post(EVENTS, content=raw, headers=sign(raw, secret="outro"))).status_code == 401
    assert await replies(db_session) == []


async def test_replayed_request_older_than_five_minutes_is_rejected(client: AsyncClient, db_session: AsyncSession, world: World):
    resp = await post(client, dm("menu"), ts=int(time.time()) - 301)
    assert resp.status_code == 401
    assert (await post(client, dm("menu"), ts=int(time.time()) - 200)).status_code == 200


async def test_signature_helper_edges():
    raw = b"{}"
    good = sign(raw)
    now = time.time()
    assert slack_webhook.signature_valid(SIGNING, good["X-Slack-Request-Timestamp"], good["X-Slack-Signature"], raw, now)
    assert not slack_webhook.signature_valid(None, good["X-Slack-Request-Timestamp"], good["X-Slack-Signature"], raw, now)
    assert not slack_webhook.signature_valid(SIGNING, "abc", good["X-Slack-Signature"], raw, now)
    assert not slack_webhook.signature_valid(SIGNING, good["X-Slack-Request-Timestamp"], "sha256=zz", raw, now)
    assert not slack_webhook.signature_valid(SIGNING, good["X-Slack-Request-Timestamp"], good["X-Slack-Signature"], b"{ }", now)


async def test_disabled_channel_does_not_answer(client: AsyncClient, db_session: AsyncSession, world: World):
    await db_session.execute(update(ChannelConfig).values(enabled=False))
    await db_session.commit()
    assert (await post(client, dm("menu"))).status_code == 404


async def test_url_verification_echoes_the_challenge_only_when_signed(client: AsyncClient, world: World):
    payload = {"type": "url_verification", "challenge": "abc123"}
    resp = await post(client, payload)
    assert resp.status_code == 200 and resp.text == "abc123"
    raw = json.dumps(payload).encode()
    assert (await client.post(EVENTS, content=raw, headers=sign(raw, secret="errado"))).status_code == 401


# --- Mensagens ------------------------------------------------------------------------------------


async def test_unlinked_sender_gets_instructions_and_is_deduplicated(client: AsyncClient, db_session: AsyncSession, world: World):
    payload = dm("oi", ts="1760000000.000200")
    assert (await post(client, payload)).status_code == 200
    assert (await post(client, payload)).status_code == 200  # reentrega do Slack
    [reply] = await replies(db_session)
    assert reply.address == "U111" and "vincular" in reply.message["body_text"].lower()


@pytest.mark.parametrize("extra", [{"bot_id": "B1"}, {"subtype": "message_changed"}, {"channel_type": "channel"}])
async def test_bot_edits_and_channel_chatter_are_ignored(client: AsyncClient, db_session: AsyncSession, world: World, extra):
    assert (await post(client, dm("menu", **extra))).status_code == 200
    assert await replies(db_session) == []


async def test_non_message_events_are_acknowledged_and_ignored(client: AsyncClient, db_session: AsyncSession, world: World):
    assert (await post(client, {"type": "event_callback", "event": {"type": "reaction_added"}})).status_code == 200
    assert (await db_session.execute(select(func.count()).select_from(Delivery))).scalar_one() == 0


async def test_per_sender_flood_is_dropped(client: AsyncClient, db_session: AsyncSession, world: World, monkeypatch):
    monkeypatch.setattr(slack_webhook, "_limiter", SenderRateLimiter(limit=2))
    for _ in range(5):
        await post(client, dm("menu", user="U999"))
    assert len(await replies(db_session)) == 2


async def test_link_flow_and_notification_reach_the_linked_user(client: AsyncClient, db_session: AsyncSession, world: World):
    code, _ = await create_link_code(db_session, world.attendant.id, "slack")
    await db_session.commit()
    assert (await post(client, dm(f"vincular {code}", user="U777"))).status_code == 200
    address = (await db_session.execute(select(UserChannelAddress).where(UserChannelAddress.channel == "slack"))).scalar_one()
    assert (address.user_id, address.address) == (world.attendant.id, "U777") and address.verified_at

    event = DomainEvent(
        id=uuid.uuid4(), event_type="ticket.assigned", entity_type="ticket", priority="normal",
        payload={"ticket_id": str(uuid.uuid4()), "title": "Sem rede", "requester_employee_id": None,
                 "assignee_id": str(world.attendant.id), "priority": "HIGH"},
    )
    rules = list((await db_session.execute(select(NotificationRule).where(NotificationRule.enabled.is_(True)))).scalars())
    plans = await plan_event(db_session, event, rules, {"in_app", "email", "slack"}, datetime.now(timezone.utc))
    assert [(p.user_id, p.address) for p in plans if p.channel == "slack"] == [(world.attendant.id, "U777")]


# --- Adapter --------------------------------------------------------------------------------------


async def test_reply_goes_out_through_chat_post_message(client: AsyncClient, db_session: AsyncSession, world: World, slack: FakeSlack):
    await post(client, dm("oi", user="U555"))
    await Dispatcher(SessionFactory).run_once()

    [sent] = slack.sent()
    assert sent["channel"] == "U555" and "vincular" in sent["text"].lower()
    assert slack.calls[0][2] == "Bearer xoxb-TOKEN"
    [delivery] = await replies(db_session)
    await db_session.refresh(delivery)
    assert delivery.status == "SENT" and delivery.provider_message_id == "1760000000.000100"


async def test_classify_maps_slack_errors_to_retry_policy():
    assert classify(200, {"ok": True, "ts": "1.2"}).outcome == "ok"
    limited = classify(429, {"retry_after": "30"})
    assert (limited.outcome, limited.retry_after_seconds) == ("retryable", 30)
    assert classify(200, {"ok": False, "error": "ratelimited"}).outcome == "retryable"
    assert classify(200, {"ok": False, "error": "token_revoked"}).outcome == "retryable"
    assert classify(200, {"ok": False, "error": "user_not_found"}).outcome == "permanent"
    assert classify(200, {"ok": False, "error": "is_archived"}).outcome == "permanent"
    assert classify(500, {"error": "boom"}).outcome == "retryable"
    assert classify(0, {"error": "ConnectError"}).outcome == "retryable"


async def test_render_text_uses_slack_link_syntax_and_truncates():
    text = render_text(Message(title="Aviso", body_text="corpo", link="/tickets/1"), "http://sys/")
    assert text == "*Aviso*\n\ncorpo\n\n<http://sys/tickets/1|Abrir no sistema>"
    assert len(render_text(Message(title="", body_text="x" * 9000), None)) <= 3500


async def test_adapter_without_config_fails_permanently(db_session: AsyncSession, slack: FakeSlack):
    result = await SlackAdapter(AdapterContext(session_factory=SessionFactory)).send(Recipient(address="U1"), Message(title="t", body_text="b"))
    assert result.outcome == "permanent" and slack.calls == []


async def test_adapter_health_reports_bot_and_workspace(db_session: AsyncSession, world: World, slack: FakeSlack):
    health = await SlackAdapter(AdapterContext(session_factory=SessionFactory)).health()
    assert health.ok and "gti_bot" in health.detail
    slack.auth_test = {"ok": False, "error": "invalid_auth"}
    assert not (await SlackAdapter(AdapterContext(session_factory=SessionFactory)).health()).ok


# --- Configuração e vínculo (API) -----------------------------------------------------------------


async def test_config_requires_permission_and_never_returns_secrets(client: AsyncClient, world: World):
    assert (await client.get(f"{BASE}/slack/config", headers=headers_for(world.requester))).status_code == 403
    body = (await client.get(f"{BASE}/slack/config", headers=headers_for(world.admin))).json()
    assert body["bot_token"] == "********" and body["signing_secret"] == "********"
    assert "xoxb-TOKEN" not in json.dumps(body) and SIGNING not in json.dumps(body)


async def test_new_token_is_validated_and_masked_values_keep_the_old_secrets(client: AsyncClient, db_session: AsyncSession, world: World, slack: FakeSlack):
    admin = headers_for(world.admin)
    resp = await client.put(
        f"{BASE}/slack/config",
        json={"enabled": True, "bot_token": "xoxb-NEW", "signing_secret": "********", "app_base_url": "http://x"},
        headers=admin,
    )
    assert resp.status_code == 200 and resp.json()["bot_name"] == "gti_bot" and resp.json()["team_name"] == "Empresa"
    stored = await load_channel(db_session, "slack")
    assert stored.secrets == {"bot_token": "xoxb-NEW", "signing_secret": SIGNING}

    calls_before = len(slack.calls)
    again = await client.put(
        f"{BASE}/slack/config", json={"enabled": True, "bot_token": "********", "signing_secret": "", "app_base_url": "http://y"}, headers=admin
    )
    assert again.status_code == 200 and len(slack.calls) == calls_before  # token inalterado: sem nova chamada


async def test_rejected_token_and_missing_secrets_are_refused(client: AsyncClient, db_session: AsyncSession, world: World, slack: FakeSlack):
    admin = headers_for(world.admin)
    slack.auth_test = {"ok": False, "error": "invalid_auth"}
    bad = await client.put(f"{BASE}/slack/config", json={"enabled": True, "bot_token": "xoxb-BAD", "signing_secret": "s"}, headers=admin)
    assert bad.status_code >= 400 and "invalid_auth" in bad.text
    await db_session.execute(delete(ChannelConfig))
    await db_session.commit()
    incomplete = await client.put(f"{BASE}/slack/config", json={"enabled": True, "bot_token": "", "signing_secret": ""}, headers=admin)
    assert incomplete.status_code >= 400


async def test_link_code_api_and_prefs_support_slack(client: AsyncClient, world: World):
    channels = (await client.get(f"{BASE}/channels", headers=headers_for(world.requester))).json()["channels"]
    entry = next(c for c in channels if c["channel"] == "slack")
    assert (entry["available"], entry["linked"], entry["bot_name"]) == (True, False, "gti_bot")

    issued = (await client.post(f"{BASE}/channels/slack/link-code", headers=headers_for(world.requester))).json()
    assert issued["command"] == f"vincular {issued['code']}"

    prefs = await client.put(f"{BASE}/prefs", json={"channels_disabled": ["slack"]}, headers=headers_for(world.requester))
    assert prefs.status_code == 200 and prefs.json()["channels_disabled"] == ["slack"]
