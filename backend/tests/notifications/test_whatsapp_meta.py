"""WhatsApp pela Meta Cloud API no hub (ADR-013, Fase D): webhook, janela de 24 h, config, vínculo, envio do chamado."""
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.identity.models import Permission, Role, role_permission_association, user_role_association
from app.notifications import whatsapp_webhook
from app.notifications.channel_store import load_channel, save_channel
from app.notifications.channels.base import AdapterContext, Message, Recipient
from app.notifications.channels.whatsapp import WhatsAppAdapter, classify, template_text
from app.notifications.conversation.engine import ConversationEngine
from app.notifications.dispatcher import Dispatcher
from app.notifications.fanout import plan_event
from app.notifications.linking import create_link_code
from app.notifications.models import (
    ChannelConfig,
    ConversationSession,
    Delivery,
    DomainEvent,
    InboundMessage,
    NotificationRule,
    UserChannelAddress,
)
from app.notifications.rules_seed import seed_notification_rules
from app.notifications.telegram_poller import SenderRateLimiter
from app.service_desk.models import Ticket, TicketInteraction
from app.whatsapp.models import WhatsAppTemplate
from tests.factories import headers_for, make_employee, make_org, make_ticket_category, make_user

pytestmark = pytest.mark.asyncio

WEBHOOK = "/api/v1/integrations/whatsapp/webhook"
BASE = "/api/v1/notifications"
APP_SECRET = "meta-app-secret"
VERIFY = "verify-me"
PHONE_ID = "1055550000"
SessionFactory: async_sessionmaker = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _bind(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    global SessionFactory
    SessionFactory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.notifications.fanout.quiet_until", lambda *a, **k: None)
    monkeypatch.setattr(whatsapp_webhook, "_limiter", SenderRateLimiter(limit=1000))


class FakeGraph:
    """Substitui a Graph API: registra chamadas e devolve respostas roteirizadas."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.send_responses: list[tuple[int, dict]] = []  # consumidas em ordem; vazio = sucesso
        self.details: tuple[int, dict] = (200, {"display_phone_number": "+55 85 99999-0000", "verified_name": "TI Empresa"})

    def handler(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else {}
        self.calls.append((request.method, request.url.path, payload))
        if request.url.path.endswith("/messages"):
            status, body = self.send_responses.pop(0) if self.send_responses else (200, {"messages": [{"id": "wamid.OUT1"}]})
            return httpx.Response(status, json=body)
        return httpx.Response(self.details[0], json=self.details[1])

    def sent(self) -> list[dict]:
        return [p for m, path, p in self.calls if path.endswith("/messages")]


@pytest.fixture
def graph(monkeypatch: pytest.MonkeyPatch) -> FakeGraph:
    fake = FakeGraph()
    monkeypatch.setattr(
        "app.notifications.channels.whatsapp.http_client",
        lambda timeout=15.0: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)),
    )
    return fake


@dataclass
class World:
    org: object
    category_id: uuid.UUID
    requester: object
    requester_emp: object
    other: object
    attendant: object
    admin: object


async def _grant(db: AsyncSession, user, role_name: str, code: str) -> None:
    role = Role(name=role_name)
    db.add(role)
    await db.flush()
    perm = (await db.execute(select(Permission).where(Permission.code == code))).scalar_one_or_none()
    if perm is None:
        perm = Permission(code=code)
        db.add(perm)
        await db.flush()
    await db.execute(role_permission_association.insert().values(role_id=role.id, permission_id=perm.id))
    await db.execute(user_role_association.insert().values(user_id=user.id, role_id=role.id))
    await db.commit()


async def _configure(db: AsyncSession, enabled=True, template: str | None = None, **overrides) -> None:
    config = {
        "phone_number_id": PHONE_ID, "graph_version": "v21.0", "template_name": template or "",
        "template_language": "pt_BR", "display_phone": "+55 85 99999-0000", "app_base_url": "http://sys",
        **overrides,
    }
    await save_channel(
        db, "whatsapp", enabled, config,
        {"access_token": "EAAG-TOKEN", "app_secret": APP_SECRET, "verify_token": VERIFY},
    )
    await db.commit()


@pytest.fixture
async def world(db_session: AsyncSession) -> World:
    org = await make_org(db_session)
    category = await make_ticket_category(db_session, org.sector)
    requester_emp = await make_employee(db_session, org)
    requester = await make_user(db_session, requester_emp)
    other = await make_user(db_session, await make_employee(db_session, org))
    attendant = await make_user(db_session, await make_employee(db_session, org))
    admin = await make_user(db_session, is_admin=True)
    await _grant(db_session, attendant, "Atendente", "service_desk.tickets.manage")
    await seed_notification_rules(db_session)
    await _configure(db_session)
    return World(org, category.id, requester, requester_emp, other, attendant, admin)


def sign(body: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def inbound(text: str, sender="5585999991111", wamid=None, phone_id=PHONE_ID, kind="text") -> dict:
    message = {"from": sender, "id": wamid or f"wamid.{uuid.uuid4().hex}", "timestamp": "1760000000", "type": kind}
    if kind == "text":
        message["text"] = {"body": text}
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp", "metadata": {"phone_number_id": phone_id, "display_phone_number": "558599990000"},
            "contacts": [{"wa_id": sender}], "messages": [message]}}]}],
    }


async def post_webhook(client: AsyncClient, payload: dict, secret: str = APP_SECRET, header: str | None = None):
    raw = json.dumps(payload).encode()
    return await client.post(
        WEBHOOK, content=raw, headers={"Content-Type": "application/json", "X-Hub-Signature-256": header or sign(raw, secret)}
    )


async def replies(db: AsyncSession) -> list[Delivery]:
    rows = await db.execute(select(Delivery).where(Delivery.channel == "whatsapp").order_by(Delivery.created_at))
    return list(rows.scalars())


async def link(client: AsyncClient, db: AsyncSession, user, phone: str) -> None:
    code, _ = await create_link_code(db, user.id, "whatsapp")
    await db.commit()
    resp = await post_webhook(client, inbound(f"vincular {code}", sender=phone))
    assert resp.status_code == 200
    assert (await db.execute(select(UserChannelAddress).where(UserChannelAddress.address == phone))).scalar_one_or_none()


# --- Handshake e assinatura -----------------------------------------------------------------------


async def test_handshake_returns_challenge_only_for_the_right_token(client: AsyncClient, world: World):
    ok = await client.get(WEBHOOK, params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "12345"})
    assert (ok.status_code, ok.text) == (200, "12345")
    for params in (
        {"hub.mode": "subscribe", "hub.verify_token": "errado", "hub.challenge": "1"},
        {"hub.mode": "unsubscribe", "hub.verify_token": VERIFY, "hub.challenge": "1"},
        {"hub.mode": "subscribe", "hub.verify_token": VERIFY},
        {},
    ):
        assert (await client.get(WEBHOOK, params=params)).status_code == 403, params


async def test_handshake_without_configuration_is_refused(client: AsyncClient):
    resp = await client.get(WEBHOOK, params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "1"})
    assert resp.status_code == 403


async def test_unsigned_or_wrongly_signed_bodies_are_rejected_and_ignored(client: AsyncClient, db_session: AsyncSession, world: World):
    body = json.dumps(inbound("1")).encode()
    cases = {
        "sem cabeçalho": {},
        "segredo errado": {"X-Hub-Signature-256": sign(body, "outro")},
        "sem prefixo": {"X-Hub-Signature-256": sign(body).removeprefix("sha256=")},
        "assinatura de outro corpo": {"X-Hub-Signature-256": sign(b"{}")},
    }
    for name, headers in cases.items():
        resp = await client.post(WEBHOOK, content=body, headers={"Content-Type": "application/json", **headers})
        assert resp.status_code == 401 and resp.content == b"", name
    assert (await db_session.execute(select(func.count()).select_from(InboundMessage))).scalar_one() == 0


async def test_body_tampered_after_signing_is_rejected(client: AsyncClient, world: World):
    original = json.dumps(inbound("menu")).encode()
    resp = await client.post(WEBHOOK, content=original.replace(b"menu", b"MENU"), headers={"X-Hub-Signature-256": sign(original)})
    assert resp.status_code == 401


async def test_disabled_channel_and_bad_json_and_missing_secret(client: AsyncClient, db_session: AsyncSession, world: World):
    raw = b"{nao-e-json"
    assert (await client.post(WEBHOOK, content=raw, headers={"X-Hub-Signature-256": sign(raw)})).status_code == 400

    await db_session.execute(update(ChannelConfig).values(enabled=False))
    await db_session.commit()
    assert (await post_webhook(client, inbound("menu"))).status_code == 404

    await _configure(db_session)
    await save_channel(db_session, "whatsapp", True, {"phone_number_id": PHONE_ID}, {"access_token": "t", "verify_token": VERIFY})
    await db_session.commit()
    assert (await post_webhook(client, inbound("menu"))).status_code == 401  # sem App Secret nada é aceito


# --- Processamento de mensagens -------------------------------------------------------------------


async def test_unlinked_sender_gets_only_instructions_as_a_queued_delivery(client: AsyncClient, db_session: AsyncSession, world: World):
    resp = await post_webhook(client, inbound("oi, quais são meus chamados?", sender="5585988880000"))
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}  # a resposta do bot não vai no corpo
    [delivery] = await replies(db_session)
    assert (delivery.address, delivery.priority) == ("5585988880000", "high")
    assert "vincular" in delivery.message["body_text"].lower()
    assert world.requester_emp.name not in delivery.message["body_text"]


async def test_link_then_open_ticket_by_whatsapp(client: AsyncClient, db_session: AsyncSession, world: World):
    phone = "5585977770000"
    await link(client, db_session, world.requester, phone)
    for text in ("1", "1", "VPN fora", "Não conecto desde cedo"):
        await post_webhook(client, inbound(text, sender=phone))
    ticket = (await db_session.execute(select(Ticket))).scalar_one()
    assert (ticket.title, ticket.requester_id) == ("VPN fora", world.requester_emp.id)
    assert ticket.description.startswith("[Aberto via chat]")


async def test_ticket_title_starting_with_vincular_is_not_a_link_attempt(client: AsyncClient, db_session: AsyncSession, world: World):
    phone = "5585966660000"
    await link(client, db_session, world.requester, phone)
    for text in ("1", "1", "vincular impressora nova", "Preciso instalar a impressora"):
        await post_webhook(client, inbound(text, sender=phone))
    assert (await db_session.execute(select(Ticket.title))).scalar_one() == "vincular impressora nova"


async def test_redelivered_wamid_runs_once_and_foreign_numbers_statuses_and_media_are_ignored(client: AsyncClient, db_session: AsyncSession, world: World):
    payload = inbound("menu", wamid="wamid.SAME")
    for _ in range(3):
        assert (await post_webhook(client, payload)).status_code == 200
    assert len(await replies(db_session)) == 1

    await post_webhook(client, inbound("menu", phone_id="OUTRO-NUMERO"))
    await post_webhook(client, inbound("", kind="image"))
    statuses = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "metadata": {"phone_number_id": PHONE_ID}, "statuses": [{"id": "wamid.X", "status": "read"}]}}]}]}
    assert (await post_webhook(client, statuses)).status_code == 200
    assert len(await replies(db_session)) == 1


async def test_per_sender_flood_is_dropped(client: AsyncClient, db_session: AsyncSession, world: World, monkeypatch):
    monkeypatch.setattr(whatsapp_webhook, "_limiter", SenderRateLimiter(limit=2))
    for _ in range(5):
        await post_webhook(client, inbound("menu", sender="5585955550000"))
    assert len(await replies(db_session)) == 2


async def test_reply_is_sent_as_free_text_because_the_window_just_opened(client: AsyncClient, db_session: AsyncSession, world: World, graph: FakeGraph):
    await post_webhook(client, inbound("oi", sender="5585944440000"))
    await Dispatcher(SessionFactory).run_once()

    [sent] = graph.sent()
    assert sent["type"] == "text" and sent["to"] == "5585944440000" and "vincular" in sent["text"]["body"].lower()
    [delivery] = await replies(db_session)
    await db_session.refresh(delivery)
    assert delivery.status == "SENT" and delivery.provider_message_id == "wamid.OUT1"
    method, path, _ = graph.calls[0]
    assert (method, path) == ("POST", f"/v21.0/{PHONE_ID}/messages")


# --- Adapter: janela de 24 h e classificação ------------------------------------------------------


async def _send(db: AsyncSession, phone="5585933330000", text="Chamado atualizado"):
    adapter = WhatsAppAdapter(AdapterContext(session_factory=SessionFactory))
    return await adapter.send(Recipient(address=phone), Message(title="Título", body_text=text, link="/service-desk/1"))


async def _touch_window(db: AsyncSession, phone: str, ago: timedelta) -> None:
    db.add(ConversationSession(channel="whatsapp", external_id=phone, last_interaction_at=datetime.now(timezone.utc) - ago))
    await db.commit()


async def test_open_window_sends_free_text_with_link(db_session: AsyncSession, world: World, graph: FakeGraph):
    await _touch_window(db_session, "5585933330000", timedelta(hours=3))
    assert (await _send(db_session)).outcome == "ok"
    [sent] = graph.sent()
    assert sent["type"] == "text" and sent["text"]["body"] == "Título\n\nChamado atualizado\n\nAbrir no sistema: http://sys/service-desk/1"
    assert sent["text"]["preview_url"] is False


async def test_closed_window_uses_the_template_with_a_flat_parameter(db_session: AsyncSession, world: World, graph: FakeGraph):
    await _configure(db_session, template="aviso_ti")
    await _touch_window(db_session, "5585933330000", timedelta(hours=25))
    assert (await _send(db_session, text="linha 1\nlinha 2\t\tfim")).outcome == "ok"
    [sent] = graph.sent()
    assert sent["type"] == "template" and sent["template"]["name"] == "aviso_ti"
    assert sent["template"]["language"] == {"code": "pt_BR"}
    param = sent["template"]["components"][0]["parameters"][0]["text"]
    assert "\n" not in param and "\t" not in param and "linha 1 | linha 2 | fim" in param


async def test_person_who_never_wrote_is_outside_the_window(db_session: AsyncSession, world: World, graph: FakeGraph):
    await _configure(db_session, template="aviso_ti")
    assert (await _send(db_session, phone="5585900000001")).outcome == "ok"
    assert graph.sent()[0]["type"] == "template"


async def test_closed_window_without_template_fails_permanently_and_explains(db_session: AsyncSession, world: World, graph: FakeGraph):
    result = await _send(db_session, phone="5585900000002")
    assert result.outcome == "permanent" and "24 h" in result.error and "template" in result.error
    assert graph.sent() == []  # nem tenta: não adianta bater na API


async def test_window_closing_midway_falls_back_to_the_template(db_session: AsyncSession, world: World, graph: FakeGraph):
    await _configure(db_session, template="aviso_ti")
    await _touch_window(db_session, "5585933330000", timedelta(hours=23, minutes=59))
    graph.send_responses = [(400, {"error": {"code": 131047, "message": "Re-engagement message"}})]
    assert (await _send(db_session)).outcome == "ok"
    assert [p["type"] for p in graph.sent()] == ["text", "template"]


async def test_adapter_refuses_when_disabled_or_unconfigured(db_session: AsyncSession, world: World, graph: FakeGraph):
    await db_session.execute(update(ChannelConfig).values(enabled=False))
    await db_session.commit()
    result = await _send(db_session)
    assert result.outcome == "permanent" and "desabilitado" in result.error and graph.calls == []
    health = await WhatsAppAdapter(AdapterContext(session_factory=SessionFactory)).health()
    assert health.ok is False


async def test_health_calls_graph_with_the_phone_number(db_session: AsyncSession, world: World, graph: FakeGraph):
    health = await WhatsAppAdapter(AdapterContext(session_factory=SessionFactory)).health()
    assert health.ok is True and "TI Empresa" in health.detail
    assert graph.calls[0][:2] == ("GET", f"/v21.0/{PHONE_ID}")
    graph.details = (401, {"error": {"code": 190, "message": "Invalid OAuth access token"}})
    assert (await WhatsAppAdapter(AdapterContext(session_factory=SessionFactory)).health()).ok is False


async def test_classify_maps_cloud_api_errors_to_retry_policy():
    ok = classify(200, {"messages": [{"id": "wamid.9"}]})
    assert (ok.outcome, ok.provider_message_id) == ("ok", "wamid.9")
    assert classify(401, {"error": {"code": 190, "message": "expired"}}).outcome == "retryable"
    throttled = classify(429, {"error": {"code": 130429, "message": "rate"}})
    assert (throttled.outcome, throttled.retry_after_seconds) == ("retryable", 60)
    assert classify(400, {"error": {"code": 80007, "message": "limit"}}).outcome == "retryable"
    assert classify(400, {"error": {"code": 131026, "message": "Message undeliverable"}}).outcome == "permanent"
    assert classify(400, {"error": {"code": 131030, "message": "not in allowed list"}}).outcome == "permanent"
    assert classify(503, {}).outcome == "retryable"
    assert classify(0, {"error": {"message": "ConnectError"}}).outcome == "retryable"


async def test_template_text_flattens_whitespace():
    assert template_text("a\n\nb") == "a | b"
    assert template_text("a    b") == "a b"
    assert template_text("  x  ") == "x"
    assert len(template_text("y" * 5000)) == 1000


async def test_token_never_reaches_the_logs(db_session: AsyncSession, world: World, graph: FakeGraph, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    await _touch_window(db_session, "5585933330000", timedelta(hours=1))
    await _send(db_session)
    assert "EAAG-TOKEN" not in caplog.text


# --- Configuração (administração) -----------------------------------------------------------------


CONFIG = {"enabled": True, "access_token": "EAAG-NEW", "app_secret": "novo-secret", "phone_number_id": PHONE_ID,
          "graph_version": "v21.0", "template_name": "aviso_ti", "template_language": "pt_BR", "app_base_url": "http://x"}


async def test_config_validates_with_graph_encrypts_secrets_and_masks_them(client: AsyncClient, db_session: AsyncSession, world: World, graph: FakeGraph):
    h = headers_for(world.admin)
    await db_session.execute(ChannelConfig.__table__.delete())
    await db_session.commit()

    saved = await client.put(f"{BASE}/whatsapp/config", json=CONFIG, headers=h)
    assert saved.status_code == 200
    body = saved.json()
    assert body["access_token"] == "********" and body["app_secret"] == "********"
    assert body["display_phone"] == "+55 85 99999-0000" and body["verified_name"] == "TI Empresa"
    assert body["verify_token"] and body["webhook_path"] == "/api/v1/integrations/whatsapp/webhook"
    assert "EAAG-NEW" not in saved.text and "novo-secret" not in saved.text

    stored = await load_channel(db_session, "whatsapp")
    assert stored.secrets["access_token"] == "EAAG-NEW" and stored.config["template_name"] == "aviso_ti"
    raw = (await db_session.execute(select(ChannelConfig.secrets_encrypted))).scalar_one()
    assert "EAAG-NEW" not in raw and "novo-secret" not in raw

    token = body["verify_token"]
    calls = len(graph.calls)
    again = await client.put(f"{BASE}/whatsapp/config", json={**CONFIG, "access_token": "********", "app_secret": "********", "app_base_url": "http://y"}, headers=h)
    assert again.status_code == 200 and again.json()["verify_token"] == token
    assert len(graph.calls) == calls  # token e número iguais: não valida de novo
    assert (await load_channel(db_session, "whatsapp")).secrets["access_token"] == "EAAG-NEW"


async def test_config_rejects_bad_credentials_missing_secret_and_bad_version(client: AsyncClient, db_session: AsyncSession, world: World, graph: FakeGraph):
    h = headers_for(world.admin)
    graph.details = (400, {"error": {"code": 190, "message": "Invalid OAuth access token"}})
    bad = await client.put(f"{BASE}/whatsapp/config", json={**CONFIG, "access_token": "EAAG-RUIM"}, headers=h)
    assert bad.status_code >= 400 and "recusou" in bad.text
    assert (await load_channel(db_session, "whatsapp")).secrets["access_token"] == "EAAG-TOKEN"  # nada foi gravado

    # campo em branco = manter o segredo atual (não é erro)...
    graph.details = (200, {"display_phone_number": "+55 85 99999-0000", "verified_name": "TI"})
    keep = await client.put(f"{BASE}/whatsapp/config", json={**CONFIG, "app_secret": "", "access_token": ""}, headers=h)
    assert keep.status_code == 200
    assert (await load_channel(db_session, "whatsapp")).secrets["app_secret"] == APP_SECRET
    # ...mas habilitar sem nunca ter informado o App Secret é recusado
    await db_session.execute(ChannelConfig.__table__.delete())
    await db_session.commit()
    incomplete = await client.put(f"{BASE}/whatsapp/config", json={**CONFIG, "app_secret": ""}, headers=h)
    assert incomplete.status_code >= 400 and "App Secret" in incomplete.text
    assert await load_channel(db_session, "whatsapp") is None
    assert (await client.put(f"{BASE}/whatsapp/config", json={**CONFIG, "graph_version": "latest"}, headers=h)).status_code == 422
    assert (await client.put(f"{BASE}/whatsapp/config", json={**CONFIG, "template_name": "Nome Com Espaço"}, headers=h)).status_code == 422


async def test_config_requires_manage_permission(client: AsyncClient, world: World):
    assert (await client.get(f"{BASE}/whatsapp/config", headers=headers_for(world.requester))).status_code == 403
    assert (await client.put(f"{BASE}/whatsapp/config", json=CONFIG, headers=headers_for(world.requester))).status_code == 403
    assert (await client.get(f"{BASE}/whatsapp/config", headers=headers_for(world.requester, "notifications.manage"))).status_code == 200


# --- Vínculo e notificações -----------------------------------------------------------------------


async def test_link_code_api_gives_command_and_wa_me_link(client: AsyncClient, world: World):
    channels = (await client.get(f"{BASE}/channels", headers=headers_for(world.requester))).json()["channels"]
    wa = next(c for c in channels if c["channel"] == "whatsapp")
    assert (wa["available"], wa["linked"], wa["display_phone"]) == (True, False, "+55 85 99999-0000")

    issued = (await client.post(f"{BASE}/channels/whatsapp/link-code", headers=headers_for(world.requester))).json()
    assert issued["command"] == f"vincular {issued['code']}"
    assert issued["deep_link"] == f"https://wa.me/5585999990000?text=vincular%20{issued['code']}"


async def test_link_code_refused_while_channel_is_not_ready(client: AsyncClient, db_session: AsyncSession, world: World):
    await db_session.execute(update(ChannelConfig).values(enabled=False))
    await db_session.commit()
    resp = await client.post(f"{BASE}/channels/whatsapp/link-code", headers=headers_for(world.requester))
    assert resp.status_code >= 400 and "habilitado" in resp.text


async def test_whatsapp_phone_in_employee_registry_does_not_link_anything(client: AsyncClient, db_session: AsyncSession, world: World):
    world.requester_emp.phone = "5585911112222"
    await db_session.commit()
    await post_webhook(client, inbound("1", sender="5585911112222"))
    assert (await db_session.execute(select(func.count()).select_from(UserChannelAddress))).scalar_one() == 0
    assert (await db_session.execute(select(func.count()).select_from(Ticket))).scalar_one() == 0


async def test_ticket_notifications_reach_linked_whatsapp_only(client: AsyncClient, db_session: AsyncSession, world: World):
    await link(client, db_session, world.attendant, "5585922220000")
    event = DomainEvent(
        id=uuid.uuid4(), event_type="ticket.assigned", entity_type="ticket", priority="normal",
        payload={"ticket_id": str(uuid.uuid4()), "title": "Sem rede", "requester_employee_id": str(world.requester_emp.id),
                 "assignee_id": str(world.attendant.id), "responsible_sector_id": str(world.org.sector.id), "priority": "HIGH"},
    )
    rules = list((await db_session.execute(select(NotificationRule).where(NotificationRule.enabled.is_(True)))).scalars())
    plans = await plan_event(db_session, event, rules, {"in_app", "email", "whatsapp"}, datetime.now(timezone.utc))
    assert [(p.user_id, p.address) for p in plans if p.channel == "whatsapp"] == [(world.attendant.id, "5585922220000")]


# --- Envio a partir do chamado --------------------------------------------------------------------


async def _make_ticket(client: AsyncClient, world: World) -> str:
    resp = await client.post(
        "/api/v1/tickets",
        json={"title": "Monitor piscando", "description": "d", "priority": "LOW", "category_id": str(world.category_id)},
        headers=headers_for(world.requester),
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def attend(world: World):
    return headers_for(world.attendant, "service_desk.tickets.manage")


async def test_send_from_ticket_requires_the_requester_to_have_linked_whatsapp(client: AsyncClient, db_session: AsyncSession, world: World):
    ticket_id = await _make_ticket(client, world)
    resp = await client.post(f"/api/v1/integrations/whatsapp/tickets/{ticket_id}/send", json={"custom_message": "Olá"}, headers=attend(world))
    assert resp.status_code == 400 and "vinculou" in resp.text
    assert await replies(db_session) == []


async def test_send_from_ticket_queues_a_delivery_and_records_history(client: AsyncClient, db_session: AsyncSession, world: World):
    await link(client, db_session, world.requester, "5585900001111")
    ticket_id = await _make_ticket(client, world)
    db_session.add(WhatsAppTemplate(name="Acesso remoto", code="acesso", category="SERVICE_DESK", content="Olá {{solicitante}}, chamado #{{protocolo}}: {{observacao}}"))
    await db_session.commit()
    template = (await db_session.execute(select(WhatsAppTemplate))).scalar_one()

    resp = await client.post(
        f"/api/v1/integrations/whatsapp/tickets/{ticket_id}/send",
        json={"template_id": str(template.id), "observacao": "abra o AnyDesk", "priority": 1}, headers=attend(world),
    )
    assert resp.status_code == 200 and resp.json()["status"] == "queued"
    delivery = (await replies(db_session))[-1]
    assert delivery.address == "5585900001111" and delivery.priority == "high" and delivery.recipient_user_id == world.requester.id
    assert delivery.message["body_text"] == f"Olá {world.requester_emp.name}, chamado #{ticket_id[:8]}: abra o AnyDesk"
    history = (await db_session.execute(select(TicketInteraction).where(TicketInteraction.message.like("%WhatsApp enviado%")))).scalar_one()
    assert history.is_internal is False and history.author_id == world.attendant.id


async def test_send_from_ticket_validations_and_access_scope(client: AsyncClient, db_session: AsyncSession, world: World):
    await link(client, db_session, world.requester, "5585900001111")
    ticket_id = await _make_ticket(client, world)
    url = f"/api/v1/integrations/whatsapp/tickets/{ticket_id}/send"

    assert (await client.post(url, json={}, headers=attend(world))).status_code == 400  # nem modelo nem texto
    assert (await client.post(url, json={"custom_message": "x"}, headers=headers_for(world.other))).status_code == 403

    # técnico de OUTRO setor não enxerga o chamado: sem acesso, sem envio
    other_org = await make_org(db_session)
    stranger = await make_user(db_session, await make_employee(db_session, other_org))
    denied = await client.post(url, json={"custom_message": "x"}, headers=headers_for(stranger, "service_desk.tickets.manage"))
    assert denied.status_code in (403, 404)

    await db_session.execute(update(ChannelConfig).values(enabled=False))
    await db_session.commit()
    off = await client.post(url, json={"custom_message": "x"}, headers=attend(world))
    assert off.status_code == 400 and "habilitado" in off.text


# --- Respostas rápidas (templates) e remoção do bot antigo ----------------------------------------


async def test_quick_reply_templates_crud_and_preview(client: AsyncClient, db_session: AsyncSession, world: World):
    base = "/api/v1/integrations/whatsapp/templates"
    h = headers_for(world.admin)
    body = {"name": "Aviso", "code": "aviso", "category": "SERVICE_DESK", "content": "Chamado #{{protocolo}} {{status}}"}
    created = await client.post(base, json=body, headers=h)
    assert created.status_code == 201
    assert (await client.post(base, json=body, headers=h)).status_code == 400  # código repetido
    tid = created.json()["id"]

    assert (await client.put(f"{base}/{tid}", json={"is_active": False}, headers=h)).json()["is_active"] is False
    assert [t["code"] for t in (await client.get(f"{base}?active_only=true", headers=h)).json()] == []
    assert len((await client.get(base, headers=h)).json()) == 1

    ticket_id = await _make_ticket(client, world)
    preview = (await client.post(f"{base}/{tid}/preview", json={"ticket_id": ticket_id}, headers=h)).json()
    assert preview["rendered_message"] == f"Chamado #{ticket_id[:8]} Aberto"
    assert preview["variables_detected"] == ["protocolo", "status"]

    assert (await client.post(base, json={**body, "code": "x2"}, headers=headers_for(world.attendant, "service_desk.tickets.manage"))).status_code == 403
    assert (await client.delete(f"{base}/{tid}", headers=h)).status_code == 204
    assert (await client.delete(f"{base}/{tid}", headers=h)).status_code == 404


async def test_legacy_bot_endpoints_are_gone(client: AsyncClient, world: World):
    h = headers_for(world.admin)
    for method, path in (
        ("get", "/config"), ("get", "/status"), ("get", "/qrcode"), ("get", "/outbox"), ("get", "/outbox/stats"),
        ("post", "/outbox/process"), ("post", "/emergency-pause"), ("post", "/test-send"),
    ):
        resp = await getattr(client, method)(f"/api/v1/integrations/whatsapp{path}", headers=h)
        assert resp.status_code in (404, 405), path


async def test_old_unauthenticated_webhook_contract_is_gone(client: AsyncClient, world: World):
    """O webhook antigo aceitava {phone, message} com X-Webhook-Secret e devolvia a resposta do bot no corpo."""
    resp = await client.post(WEBHOOK, json={"phone": "5585999990000", "message": "1"}, headers={"X-Webhook-Secret": "qualquer"})
    assert resp.status_code == 401 and resp.content == b""


async def test_prefs_accept_whatsapp_as_configurable_channel(client: AsyncClient, world: World):
    resp = await client.put(f"{BASE}/prefs", json={"channels_disabled": ["whatsapp", "telegram"]}, headers=headers_for(world.requester))
    assert resp.status_code == 200 and resp.json()["channels_disabled"] == ["telegram", "whatsapp"]


async def test_engine_treats_whatsapp_like_any_channel(db_session: AsyncSession, world: World):
    code, _ = await create_link_code(db_session, world.requester.id, "whatsapp")
    await db_session.commit()
    replies_, user_id = await ConversationEngine(db_session).handle("whatsapp", "5585912345678", f"Vincular {code.lower()}")
    assert user_id == world.requester.id and "vinculado" in replies_[0]
