"""WhatsApp pelo provedor Evolution (ADR-019, C2): envio, classificação, estado da conexão e rotas de administração."""
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.notifications.channel_store import StoredChannel, load_channel, save_channel
from app.notifications.channels import whatsapp_evolution as evo
from app.notifications.channels.base import AdapterContext, Message, Recipient
from app.notifications.channels.whatsapp import WhatsAppAdapter, provider_of
from app.notifications.dispatcher import Dispatcher
from app.notifications.jobs import DEFAULT_JOBS, job_whatsapp_health
from app.notifications import whatsapp_evolution_webhook
from app.notifications.linking import create_link_code
from app.notifications.models import AutomationMark, Delivery, DomainEvent, InboundMessage, NotificationRule, UserChannelAddress
from app.notifications.telegram_poller import SenderRateLimiter
from app.notifications.rules_seed import seed_notification_rules
from tests.factories import headers_for, make_employee, make_org, make_user

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/notifications"
API_KEY = "evo-global-key-0123456789"
HOOK_URL = "http://backend:8000/api/v1/integrations/whatsapp/evolution/webhook"
SessionFactory: async_sessionmaker = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _bind(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    global SessionFactory
    SessionFactory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(evo, "get_settings", lambda: SimpleNamespace(EVOLUTION_BASE_URL="http://evolution:8080", EVOLUTION_API_KEY=API_KEY, EVOLUTION_WEBHOOK_URL=HOOK_URL))


class FakeEvolution:
    """Substitui a Evolution: registra chamadas e devolve respostas roteirizadas por rota."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, str | None]] = []
        self.created = True  # padrão: instância pronta e conectada (a maioria dos testes só quer enviar)
        self.state = "open"
        self.send_responses: list[tuple[int, object]] = []
        self.owner = "5585999990000@s.whatsapp.net"
        self.logout_response: tuple[int, object] = (200, {"status": "SUCCESS"})

    def handler(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else {}
        path = request.url.path
        self.calls.append((request.method, path, payload, request.headers.get("apikey")))
        if path.startswith("/message/sendText/"):
            status, body = self.send_responses.pop(0) if self.send_responses else (201, {"key": {"id": "BAE5OUT1"}})
            return httpx.Response(status, json=body)
        if path.startswith("/instance/connectionState/"):
            if not self.created:
                return httpx.Response(404, json={"status": 404, "error": "Not Found", "response": {"message": ["The instance does not exist"]}})
            return httpx.Response(200, json={"instance": {"instanceName": "gestao-ti", "state": self.state}})
        if path == "/instance/create":
            self.created = True
            return httpx.Response(201, json={"instance": {"instanceName": payload["instanceName"]}})
        if path.startswith("/instance/connect/"):
            if self.state == "open":
                return httpx.Response(200, json={"instance": {"instanceName": "gestao-ti", "state": "open"}})
            return httpx.Response(200, json={"pairingCode": None, "code": "2@abc", "base64": "data:image/png;base64,QR", "count": 1})
        if path.startswith("/webhook/set/"):
            return httpx.Response(201, json={"enabled": True})
        if path == "/instance/fetchInstances":
            return httpx.Response(200, json=[{"name": "gestao-ti", "ownerJid": self.owner}])
        if path.startswith("/instance/logout/"):
            return httpx.Response(*self.logout_response[:1], json=self.logout_response[1])
        return httpx.Response(404, json={})

    def sent(self) -> list[dict]:
        return [p for m, path, p, _ in self.calls if path.startswith("/message/sendText/")]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeEvolution:
    fake = FakeEvolution()
    monkeypatch.setattr(evo, "http_client", lambda timeout=15.0: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    return fake


async def _configure(db: AsyncSession, enabled: bool = True, **overrides) -> None:
    config = {"provider": "evolution", "instance_name": "gestao-ti", "app_base_url": "http://sys", **overrides}
    await save_channel(db, "whatsapp", enabled, config, {})
    await db.commit()


async def _send(phone: str = "5585933330000", title: str = "Garantia vencendo", body: str = "3 ativos vencem em 7 dias"):
    adapter = WhatsAppAdapter(AdapterContext(session_factory=SessionFactory))
    return await adapter.send(Recipient(address=phone), Message(title=title, body_text=body, link="/assets"))


# --- Envio ----------------------------------------------------------------------------------------


async def test_sends_free_text_with_api_key_and_no_window_or_template(db_session: AsyncSession, fake: FakeEvolution):
    await _configure(db_session)
    result = await _send()

    assert (result.outcome, result.provider_message_id) == ("ok", "BAE5OUT1")
    method, path, payload, key = fake.calls[-1]  # antes do envio, o adapter confere o estado da sessão
    assert fake.calls[0][:2] == ("GET", "/instance/connectionState/gestao-ti")
    assert (method, path, key) == ("POST", "/message/sendText/gestao-ti", API_KEY)
    assert payload["number"] == "5585933330000" and payload["linkPreview"] is False
    assert payload["text"] == "*Garantia vencendo*\n\n3 ativos vencem em 7 dias\n\nAbrir no sistema: http://sys/assets"


async def test_disabled_channel_and_missing_server_key_do_not_call_the_api(db_session: AsyncSession, fake: FakeEvolution, monkeypatch):
    await _configure(db_session, enabled=False)
    off = await _send()
    assert off.outcome == "permanent" and "desabilitado" in off.error

    await _configure(db_session)
    monkeypatch.setattr(evo, "get_settings", lambda: SimpleNamespace(EVOLUTION_BASE_URL="http://evolution:8080", EVOLUTION_API_KEY="", EVOLUTION_WEBHOOK_URL=HOOK_URL))
    no_key = await _send()
    assert no_key.outcome == "retryable" and "EVOLUTION_API_KEY" in no_key.error
    assert fake.calls == []


async def test_classify_maps_evolution_errors_to_retry_policy():
    assert evo.classify(201, {"key": {"id": "X"}}).outcome == "ok"
    # número sem WhatsApp: não adianta tentar de novo
    not_on_whatsapp = evo.classify(400, {"status": 400, "error": "Bad Request", "response": {"message": [{"exists": False, "number": "5585"}]}})
    assert not_on_whatsapp.outcome == "permanent"
    # sessão caída ou instância ausente: volta a funcionar ao reconectar
    assert evo.classify(500, {"message": "Connection Closed"}).outcome == "retryable"
    assert evo.classify(400, {"message": "Connection Closed"}).outcome == "retryable"
    assert evo.classify(404, {"response": {"message": ["The instance does not exist"]}}).outcome == "retryable"
    refused = evo.classify(401, {"message": "Unauthorized"})
    assert refused.outcome == "retryable" and "EVOLUTION_API_KEY" in refused.error
    throttled = evo.classify(429, {})
    assert (throttled.outcome, throttled.retry_after_seconds) == ("retryable", 60)
    assert evo.classify(0, {"message": "ConnectError"}).outcome == "retryable"
    assert evo.classify(201, {}).outcome == "permanent"  # 2xx sem id de mensagem não vale como entrega


async def test_failed_send_is_classified_through_the_adapter(db_session: AsyncSession, fake: FakeEvolution):
    await _configure(db_session)
    fake.send_responses = [(400, {"response": {"message": [{"exists": False}]}}), (500, {"message": "boom"})]
    assert (await _send()).outcome == "permanent"
    assert (await _send()).outcome == "retryable"


async def test_api_key_never_reaches_the_logs(db_session: AsyncSession, fake: FakeEvolution, caplog):
    caplog.set_level(logging.DEBUG)
    await _configure(db_session)
    await _send()
    assert API_KEY not in caplog.text


async def test_render_text_truncates_and_omits_empty_parts():
    text = evo.render_text(Message(title="", body_text="x" * 5000), None)
    assert len(text) == evo.MAX_TEXT and text.endswith("…")
    assert evo.render_text(Message(title="T", body_text="c"), "http://sys") == "*T*\n\nc"


# --- Provedor e saúde -----------------------------------------------------------------------------


async def test_old_configs_without_provider_are_meta():
    assert provider_of(None) == "meta"
    assert provider_of(StoredChannel("whatsapp", True, {"phone_number_id": "1"}, {})) == "meta"
    assert provider_of(StoredChannel("whatsapp", True, {"provider": "evolution"}, {})) == "evolution"
    assert provider_of(StoredChannel("whatsapp", True, {"provider": "outro"}, {})) == "meta"


async def test_health_follows_the_connection_state(db_session: AsyncSession, fake: FakeEvolution):
    adapter = WhatsAppAdapter(AdapterContext(session_factory=SessionFactory))
    await _configure(db_session, display_phone="+55 85 99999-0000")
    fake.created = False
    assert (await adapter.health()).ok is False  # instância ainda não criada

    fake.created, fake.state = True, "connecting"
    assert (await adapter.health()).ok is False
    fake.state = "open"
    health = await adapter.health()
    assert health.ok is True and "99999-0000" in health.detail


# --- Administração: configuração ------------------------------------------------------------------


async def _admin(db: AsyncSession):
    return await make_user(db, is_admin=True)


async def test_config_saves_evolution_without_secrets_and_keeps_the_meta_ones(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution):
    admin = await _admin(db_session)
    h = headers_for(admin)
    await save_channel(db_session, "whatsapp", False, {"phone_number_id": "1055550000"}, {"access_token": "EAAG-OLD", "app_secret": "s", "verify_token": "v"})
    await db_session.commit()

    saved = await client.put(f"{BASE}/whatsapp/config", json={"enabled": True, "provider": "evolution", "instance_name": "ti-matriz", "app_base_url": "http://x"}, headers=h)
    assert saved.status_code == 200
    body = saved.json()
    assert (body["provider"], body["instance_name"], body["evolution_ready"], body["enabled"]) == ("evolution", "ti-matriz", True, True)
    assert API_KEY not in saved.text

    stored = await load_channel(db_session, "whatsapp")
    assert stored.config["provider"] == "evolution" and stored.config["phone_number_id"] == "1055550000"
    assert stored.secrets["access_token"] == "EAAG-OLD"  # voltar à Meta não exige digitar tudo de novo
    assert fake.calls == []  # salvar não chama a Evolution


async def test_enabling_evolution_without_the_server_key_is_refused(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr(evo, "get_settings", lambda: SimpleNamespace(EVOLUTION_BASE_URL="http://evolution:8080", EVOLUTION_API_KEY="", EVOLUTION_WEBHOOK_URL=HOOK_URL))
    h = headers_for(await _admin(db_session))
    refused = await client.put(f"{BASE}/whatsapp/config", json={"enabled": True, "provider": "evolution"}, headers=h)
    assert refused.status_code >= 400 and "EVOLUTION_API_KEY" in refused.text
    assert await load_channel(db_session, "whatsapp") is None
    # desabilitado pode ser salvo (só escolher o provedor)
    assert (await client.put(f"{BASE}/whatsapp/config", json={"enabled": False, "provider": "evolution"}, headers=h)).status_code == 200


async def test_config_validates_provider_and_instance_name(client: AsyncClient, db_session: AsyncSession):
    h = headers_for(await _admin(db_session))
    assert (await client.put(f"{BASE}/whatsapp/config", json={"provider": "baileys"}, headers=h)).status_code == 422
    for bad in ("com espaço", "../x", "a" * 41, ""):
        assert (await client.put(f"{BASE}/whatsapp/config", json={"provider": "evolution", "instance_name": bad}, headers=h)).status_code == 422, bad


async def test_changing_the_instance_forgets_the_displayed_phone(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution):
    h = headers_for(await _admin(db_session))
    await _configure(db_session, display_phone="5585999990000")
    resp = await client.put(f"{BASE}/whatsapp/config", json={"enabled": True, "provider": "evolution", "instance_name": "outra"}, headers=h)
    assert resp.status_code == 200 and resp.json()["display_phone"] is None


async def test_link_code_available_for_evolution_when_server_is_configured(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution):
    user = await make_user(db_session, await make_employee(db_session, await make_org(db_session)))
    await _configure(db_session, display_phone="5585999990000")
    channels = (await client.get(f"{BASE}/channels", headers=headers_for(user))).json()["channels"]
    assert next(c for c in channels if c["channel"] == "whatsapp")["available"] is True
    issued = (await client.post(f"{BASE}/channels/whatsapp/link-code", headers=headers_for(user))).json()
    assert issued["deep_link"].startswith("https://wa.me/5585999990000?text=vincular")


# --- Administração: conexão (QR code) -------------------------------------------------------------


async def test_status_connect_and_disconnect_flow(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution):
    h = headers_for(await _admin(db_session))
    await _configure(db_session)
    fake.created, fake.state = False, "close"

    status = (await client.get(f"{BASE}/whatsapp/status", headers=h)).json()
    assert (status["provider"], status["state"]) == ("evolution", "close")  # instância ainda não existe

    connect = (await client.post(f"{BASE}/whatsapp/connect", headers=h)).json()
    assert connect["state"] == "connecting" and connect["qr_base64"] == "data:image/png;base64,QR" and connect["count"] == 1
    assert fake.created is True
    assert any(path == "/instance/create" and payload["integration"] == "WHATSAPP-BAILEYS" for _, path, payload, _ in fake.calls)

    fake.state = "open"
    status = (await client.get(f"{BASE}/whatsapp/status", headers=h)).json()
    assert (status["state"], status["display_phone"]) == ("open", "5585999990000")  # descoberto e guardado
    assert (await load_channel(db_session, "whatsapp")).config["display_phone"] == "5585999990000"

    fake.calls.clear()
    again = (await client.post(f"{BASE}/whatsapp/connect", headers=h)).json()
    assert again["state"] == "open" and again["qr_base64"] is None
    assert not any(path == "/instance/create" for _, path, _, _ in fake.calls)  # não recria

    off = await client.post(f"{BASE}/whatsapp/disconnect", headers=h)
    assert off.status_code == 200 and off.json()["state"] == "close"
    assert "display_phone" not in (await load_channel(db_session, "whatsapp")).config

    events = set((await db_session.execute(select(AuditLog.event_type))).scalars())
    assert {"notifications.whatsapp_connect_requested", "notifications.whatsapp_disconnected"} <= events


async def test_connect_and_disconnect_only_apply_to_the_evolution_provider(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution):
    h = headers_for(await _admin(db_session))
    await save_channel(db_session, "whatsapp", True, {"phone_number_id": "1"}, {"access_token": "t"})
    await db_session.commit()
    assert (await client.get(f"{BASE}/whatsapp/status", headers=h)).json()["state"] == "not_applicable"
    for action in ("connect", "disconnect"):
        resp = await client.post(f"{BASE}/whatsapp/{action}", headers=h)
        assert resp.status_code >= 400 and "Evolution" in resp.text
    assert fake.calls == []


async def test_connection_errors_are_reported_not_hidden(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution, monkeypatch):
    h = headers_for(await _admin(db_session))
    await _configure(db_session)
    monkeypatch.setattr(evo, "get_settings", lambda: SimpleNamespace(EVOLUTION_BASE_URL="http://evolution:8080", EVOLUTION_API_KEY="", EVOLUTION_WEBHOOK_URL=HOOK_URL))
    status = (await client.get(f"{BASE}/whatsapp/status", headers=h)).json()
    assert status["state"] == "unconfigured" and "EVOLUTION_API_KEY" in status["detail"]
    connect = (await client.post(f"{BASE}/whatsapp/connect", headers=h)).json()
    assert connect["state"] == "error" and "EVOLUTION_API_KEY" in connect["detail"]

    monkeypatch.setattr(evo, "get_settings", lambda: SimpleNamespace(EVOLUTION_BASE_URL="http://evolution:8080", EVOLUTION_API_KEY=API_KEY, EVOLUTION_WEBHOOK_URL=HOOK_URL))
    fake.logout_response = (500, {"message": "falhou"})
    resp = await client.post(f"{BASE}/whatsapp/disconnect", headers=h)
    assert resp.status_code >= 400 and "não conseguiu desconectar" in resp.text


async def test_connection_routes_require_manage_permission(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution):
    user = await make_user(db_session, await make_employee(db_session, await make_org(db_session)))
    await _configure(db_session)
    for method, path in (("get", "status"), ("post", "connect"), ("post", "disconnect")):
        assert (await getattr(client, method)(f"{BASE}/whatsapp/{path}", headers=headers_for(user))).status_code == 403
    assert (await client.get(f"{BASE}/whatsapp/status", headers=headers_for(user, "notifications.manage"))).status_code == 200
    assert fake.calls and all(path.startswith(("/instance/connectionState", "/instance/fetchInstances")) for _, path, _, _ in fake.calls)


async def test_instance_name_is_url_encoded_in_paths():
    assert evo.instance_path("message/sendText", "a b/c") == "message/sendText/a%20b%2Fc"


# --- Revisão do PR: troca de provedor, auditoria do QR e mensagens de erro -------------------------


async def test_switching_provider_forgets_the_displayed_phone_both_ways(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution):
    h = headers_for(await _admin(db_session))
    await save_channel(db_session, "whatsapp", False, {"phone_number_id": "1", "display_phone": "+55 85 1111-1111", "verified_name": "Meta"}, {"access_token": "t"})
    await db_session.commit()

    to_evo = await client.put(f"{BASE}/whatsapp/config", json={"enabled": False, "provider": "evolution"}, headers=h)
    assert to_evo.status_code == 200 and to_evo.json()["display_phone"] is None  # o wa.me não pode apontar para o número da Meta

    await save_channel(db_session, "whatsapp", False, {"provider": "evolution", "instance_name": "gestao-ti", "display_phone": "5585999990000"}, {"access_token": "t"})
    await db_session.commit()
    to_meta = await client.put(f"{BASE}/whatsapp/config", json={"enabled": False, "provider": "meta"}, headers=h)
    assert to_meta.status_code == 200
    body = to_meta.json()
    assert body["provider"] == "meta" and body["display_phone"] is None and body["verified_name"] is None


async def test_instance_name_is_optional_and_kept_when_omitted(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution):
    h = headers_for(await _admin(db_session))
    await _configure(db_session, instance_name="ti-matriz")
    saved = await client.put(f"{BASE}/whatsapp/config", json={"enabled": False, "provider": "evolution"}, headers=h)
    assert saved.status_code == 200 and saved.json()["instance_name"] == "ti-matriz"
    # a Meta não precisa mandar o nome da instância
    assert (await client.put(f"{BASE}/whatsapp/config", json={"enabled": False, "provider": "meta"}, headers=h)).status_code == 200


async def test_qr_refresh_is_not_audited_but_the_first_request_is(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution):
    h = headers_for(await _admin(db_session))
    await _configure(db_session)

    async def audited() -> int:
        rows = await db_session.execute(select(AuditLog.event_type).where(AuditLog.event_type == "notifications.whatsapp_connect_requested"))
        return len(list(rows.scalars()))

    await client.post(f"{BASE}/whatsapp/connect", headers=h)
    assert await audited() == 1
    for _ in range(3):
        assert (await client.post(f"{BASE}/whatsapp/connect?refresh=true", headers=h)).status_code == 200
    assert await audited() == 1


async def test_error_messages_are_specific():
    no_whatsapp = evo.classify(400, {"status": 400, "message": [{"jid": "5585@s.whatsapp.net", "exists": False, "number": "5585"}]})
    assert no_whatsapp.outcome == "permanent" and "sem WhatsApp" in no_whatsapp.error
    assert evo.classify(400, {"message": "Timed Out"}).outcome == "retryable"


async def test_connect_surfaces_an_error_body_returned_with_200(db_session: AsyncSession, fake: FakeEvolution, monkeypatch):
    fake.created = True

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/instance/connect/"):
            return httpx.Response(200, json={"error": True, "message": "Error: boom"})
        return fake.handler(request)

    monkeypatch.setattr(evo, "http_client", lambda timeout=15.0: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result = await evo.connect("gestao-ti")
    assert result["state"] == "error" and "boom" in result["detail"]


# --- C3: ritmo contra banimento, entrega adiada, teste, saúde e regra de backup --------------------


async def test_pacer_books_the_next_slot_with_a_random_gap_and_can_be_disabled():
    clock = [100.0]
    pacer = evo.Pacer(clock=lambda: clock[0], rng=lambda low, high: high)  # sempre o maior intervalo (interval * 1.75)
    assert pacer.reserve(4) == 0.0
    assert pacer.reserve(4) == pytest.approx(7.0)
    clock[0] += 3
    assert pacer.reserve(4) == pytest.approx(4.0)
    clock[0] += 4
    assert pacer.reserve(4) == 0.0
    assert evo.Pacer().reserve(0) == 0.0  # intervalo 0 = sem ritmo


async def test_second_message_inside_the_interval_is_deferred_without_calling_the_api(db_session: AsyncSession, fake: FakeEvolution):
    await _configure(db_session, send_interval_seconds=30)
    adapter = WhatsAppAdapter(AdapterContext(session_factory=SessionFactory))
    message = Message(title="T", body_text="b")
    assert (await adapter.send(Recipient(address="5585911110000"), message)).outcome == "ok"
    second = await adapter.send(Recipient(address="5585922220000"), message)
    assert second.deferred is True and second.retry_after_seconds >= 30
    assert len(fake.sent()) == 1  # a segunda nem chegou à Evolution


async def test_interval_zero_sends_back_to_back(db_session: AsyncSession, fake: FakeEvolution):
    await _configure(db_session, send_interval_seconds=0)
    adapter = WhatsAppAdapter(AdapterContext(session_factory=SessionFactory))
    for phone in ("5585911110000", "5585922220000", "5585933330000"):
        assert (await adapter.send(Recipient(address=phone), Message(title="T", body_text="b"))).outcome == "ok"
    assert len(fake.sent()) == 3


async def _sent_deliveries(db: AsyncSession, address: str, count: int, ago: timedelta = timedelta(minutes=5)) -> None:
    event = DomainEvent(event_type="t.e", entity_type="t", payload={}, fanned_out_at=datetime.now(timezone.utc))
    db.add(event)
    await db.flush()
    for _ in range(count):
        db.add(Delivery(
            event_id=event.id, channel="whatsapp", address=address, status="SENT", message={"title": "t", "body_text": "b"},
            idempotency_key=uuid.uuid4().hex + uuid.uuid4().hex, sent_at=datetime.now(timezone.utc) - ago,
        ))
    await db.commit()


async def test_hourly_limit_per_recipient_defers_and_only_counts_the_last_hour(db_session: AsyncSession, fake: FakeEvolution):
    await _configure(db_session, send_interval_seconds=0, max_per_hour=3)
    await _sent_deliveries(db_session, "5585911110000", 3)
    await _sent_deliveries(db_session, "5585922220000", 3, ago=timedelta(hours=2))  # fora da janela

    adapter = WhatsAppAdapter(AdapterContext(session_factory=SessionFactory))
    capped = await adapter.send(Recipient(address="5585911110000"), Message(title="T", body_text="b"))
    assert capped.deferred is True and "3 mensagens por hora" in capped.error
    assert (await adapter.send(Recipient(address="5585922220000"), Message(title="T", body_text="b"))).outcome == "ok"
    assert len(fake.sent()) == 1


async def test_dispatcher_keeps_a_deferred_delivery_pending_without_spending_attempts_or_the_circuit(db_session: AsyncSession, fake: FakeEvolution):
    await _configure(db_session, send_interval_seconds=60)
    event = DomainEvent(event_type="t.e", entity_type="t", payload={}, fanned_out_at=datetime.now(timezone.utc))
    db_session.add(event)
    await db_session.flush()
    for phone in ("5585911110000", "5585922220000"):
        db_session.add(Delivery(
            event_id=event.id, channel="whatsapp", address=phone, message={"title": "T", "body_text": "b"},
            idempotency_key=uuid.uuid4().hex + uuid.uuid4().hex,
        ))
    await db_session.commit()

    dispatcher = Dispatcher(SessionFactory)
    assert await dispatcher.run_once() == 2
    rows = list((await db_session.execute(select(Delivery).order_by(Delivery.status))).scalars())
    await db_session.commit()
    by_status = {r.status: r for r in rows}
    assert set(by_status) == {"PENDING", "SENT"}
    waiting = by_status["PENDING"]
    await db_session.refresh(waiting)
    assert waiting.attempts == 0 and waiting.locked_at is None  # não gastou tentativa
    assert waiting.next_attempt_at > datetime.now(timezone.utc).replace(tzinfo=waiting.next_attempt_at.tzinfo) + timedelta(seconds=30)
    assert dispatcher.circuit.open_channels(datetime.now(timezone.utc)) == set()
    assert await dispatcher.run_once() == 0  # só volta quando chegar a hora


async def test_config_stores_the_pacing_and_keeps_it_when_omitted(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution):
    h = headers_for(await _admin(db_session))
    saved = await client.put(f"{BASE}/whatsapp/config", json={"enabled": True, "provider": "evolution", "send_interval_seconds": 8, "max_per_hour": 5}, headers=h)
    assert (saved.json()["send_interval_seconds"], saved.json()["max_per_hour"]) == (8, 5)
    again = await client.put(f"{BASE}/whatsapp/config", json={"enabled": True, "provider": "evolution"}, headers=h)
    assert (again.json()["send_interval_seconds"], again.json()["max_per_hour"]) == (8, 5)
    default = (await client.get(f"{BASE}/whatsapp/config", headers=h)).json()
    assert default["send_interval_seconds"] == 8
    assert (await client.put(f"{BASE}/whatsapp/config", json={"provider": "evolution", "send_interval_seconds": 61}, headers=h)).status_code == 422
    assert (await client.put(f"{BASE}/whatsapp/config", json={"provider": "evolution", "max_per_hour": -1}, headers=h)).status_code == 422


# --- Enviar teste ---------------------------------------------------------------------------------


async def test_send_test_goes_straight_to_the_number_and_audits_only_the_last_digits(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution):
    h = headers_for(await _admin(db_session))
    await _configure(db_session)
    resp = await client.post(f"{BASE}/whatsapp/test", json={"to": "+55 (85) 99999-1234"}, headers=h)
    assert resp.status_code == 200 and resp.json()["ok"] is True and "1234" in resp.json()["detail"]
    [sent] = fake.sent()
    assert sent["number"] == "5585999991234" and "Teste do canal" in sent["text"]

    audit = (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "notifications.whatsapp_test_sent"))).scalar_one()
    assert audit.data == {"outcome": "ok", "to_last4": "1234"}
    assert "5585999991234" not in json.dumps(audit.data)


async def test_send_test_reports_failures_and_validates_input(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution):
    h = headers_for(await _admin(db_session))
    await _configure(db_session)
    fake.send_responses = [(400, {"message": [{"exists": False}]})]
    failed = (await client.post(f"{BASE}/whatsapp/test", json={"to": "5585999991234"}, headers=h)).json()
    assert failed["ok"] is False and "sem WhatsApp" in failed["detail"]

    for bad in ("123", "abc", "5" * 16, ""):
        resp = await client.post(f"{BASE}/whatsapp/test", json={"to": bad}, headers=h)
        assert resp.status_code >= 400, bad
    assert len(fake.sent()) == 1


async def test_send_test_needs_an_enabled_channel_permission_and_is_rate_limited(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution, monkeypatch):
    from app.notifications import channels_router
    from app.notifications.telegram_poller import SenderRateLimiter

    monkeypatch.setattr(channels_router, "_test_limiter", SenderRateLimiter(limit=2, window=3600.0))
    admin, user = await _admin(db_session), await make_user(db_session, await make_employee(db_session, await make_org(db_session)))
    h = headers_for(admin)
    off = await client.post(f"{BASE}/whatsapp/test", json={"to": "5585999991234"}, headers=h)
    assert off.status_code >= 400 and "Habilite" in off.text

    await _configure(db_session)
    assert (await client.post(f"{BASE}/whatsapp/test", json={"to": "5585999991234"}, headers=headers_for(user))).status_code == 403
    for _ in range(2):
        assert (await client.post(f"{BASE}/whatsapp/test", json={"to": "5585999991234"}, headers=h)).status_code == 200
    limited = await client.post(f"{BASE}/whatsapp/test", json={"to": "5585999991234"}, headers=h)
    assert limited.status_code >= 400 and "Limite" in limited.text


# --- Sessão caída: aviso aos administradores -------------------------------------------------------


async def _degraded_events(db: AsyncSession) -> list[DomainEvent]:
    rows = await db.execute(select(DomainEvent).where(DomainEvent.event_type == "channel.degraded"))
    return list(rows.scalars())


async def test_health_job_alerts_once_per_outage_after_one_debounce_check(db_session: AsyncSession, fake: FakeEvolution):
    await _configure(db_session)
    fake.created, fake.state = True, "close"

    await job_whatsapp_health(SessionFactory)  # 1ª checagem: só anota (pode ser um tropeço)
    assert await _degraded_events(db_session) == []
    await job_whatsapp_health(SessionFactory)  # 2ª: avisa
    [event] = await _degraded_events(db_session)
    assert event.payload["channel"] == "whatsapp" and "QR code" in event.payload["error"]
    await job_whatsapp_health(SessionFactory)
    await job_whatsapp_health(SessionFactory)
    assert len(await _degraded_events(db_session)) == 1  # um aviso por queda

    fake.state = "open"  # reconectou: rearma
    await job_whatsapp_health(SessionFactory)
    assert (await db_session.execute(select(AutomationMark))).scalars().all() == []
    fake.state = "close"
    await job_whatsapp_health(SessionFactory)
    await job_whatsapp_health(SessionFactory)
    assert len(await _degraded_events(db_session)) == 2


async def test_health_job_ignores_meta_and_disabled_channels_and_clears_old_marks(db_session: AsyncSession, fake: FakeEvolution):
    db_session.add(AutomationMark(key="whatsapp.down.seen"))
    await db_session.commit()
    await save_channel(db_session, "whatsapp", True, {"phone_number_id": "1"}, {"access_token": "t"})  # Meta
    await db_session.commit()
    await job_whatsapp_health(SessionFactory)
    await _configure(db_session, enabled=False)
    await job_whatsapp_health(SessionFactory)
    assert fake.calls == [] and await _degraded_events(db_session) == []
    assert (await db_session.execute(select(AutomationMark))).scalars().all() == []


async def test_health_job_is_a_default_scheduled_job():
    assert DEFAULT_JOBS["whatsapp.health_check"] == "every:5"


async def test_backup_failed_rule_reaches_the_linked_whatsapp_of_admins(db_session: AsyncSession):
    await seed_notification_rules(db_session)
    await db_session.commit()
    rule = (await db_session.execute(select(NotificationRule).where(NotificationRule.code == "backup.failed"))).scalar_one()
    assert rule.channels == ["in_app", "email", "preferred"]
    # o aviso de sessão caída NÃO vai pelo próprio WhatsApp
    degraded = (await db_session.execute(select(NotificationRule).where(NotificationRule.code == "channel.degraded"))).scalar_one()
    assert "preferred" not in degraded.channels and "whatsapp" not in degraded.channels


# --- C4: entrada de mensagens (vínculo pelo WhatsApp sem URL pública) -------------------------------

HOOK = "/api/v1/integrations/whatsapp/evolution/webhook"
SECRET = "hook-secret-0123456789"


def upsert(text: str = "menu", jid: str = "5585977770000@s.whatsapp.net", msg_id: str | None = None, from_me: bool = False,
           event: str = "messages.upsert", instance: str = "gestao-ti", extended: bool = False) -> dict:
    message = {"extendedTextMessage": {"text": text}} if extended else {"conversation": text}
    return {
        "event": event, "instance": instance, "apikey": "ignorada",
        "data": {"key": {"remoteJid": jid, "fromMe": from_me, "id": msg_id or f"MSG{uuid.uuid4().hex[:12]}"}, "pushName": "Fulano", "message": message, "messageType": "conversation"},
    }


async def _hooked(db: AsyncSession, **cfg) -> None:
    await save_channel(db, "whatsapp", True, {"provider": "evolution", "instance_name": "gestao-ti", **cfg}, {"webhook_secret": SECRET})
    await db.commit()


def hook_headers(secret: str | None = SECRET) -> dict:
    return {"X-Webhook-Secret": secret} if secret else {}


@pytest.fixture(autouse=True)
def _fresh_hook_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(whatsapp_evolution_webhook, "_limiter", SenderRateLimiter(limit=1000))


async def _replies(db: AsyncSession) -> list[Delivery]:
    rows = await db.execute(select(Delivery).where(Delivery.channel == "whatsapp").order_by(Delivery.created_at))
    return list(rows.scalars())


async def test_hook_refuses_wrong_or_missing_secret_and_other_providers(client: AsyncClient, db_session: AsyncSession):
    await _hooked(db_session)
    body = upsert()
    for headers in ({}, {"X-Webhook-Secret": "errado"}, {"X-Webhook-Secret": SECRET + "x"}):
        resp = await client.post(HOOK, json=body, headers=headers)
        assert resp.status_code == 401 and resp.content == b""
    assert (await db_session.execute(select(InboundMessage))).scalars().all() == []

    # chave da API da Evolution no corpo não vale como autenticação
    assert (await client.post(HOOK, json={**body, "apikey": API_KEY})).status_code == 401

    await save_channel(db_session, "whatsapp", True, {"provider": "evolution"}, {})  # sem segredo gerado: nada é aceito
    await db_session.commit()
    assert (await client.post(HOOK, json=body, headers=hook_headers())).status_code == 401

    await save_channel(db_session, "whatsapp", True, {"phone_number_id": "1"}, {"webhook_secret": SECRET})  # provedor Meta
    await db_session.commit()
    assert (await client.post(HOOK, json=body, headers=hook_headers())).status_code == 404
    await save_channel(db_session, "whatsapp", False, {"provider": "evolution"}, {"webhook_secret": SECRET})  # desabilitado
    await db_session.commit()
    assert (await client.post(HOOK, json=body, headers=hook_headers())).status_code == 404


async def test_hook_rejects_bad_json(client: AsyncClient, db_session: AsyncSession):
    await _hooked(db_session)
    resp = await client.post(HOOK, content=b"{nao-e-json", headers={**hook_headers(), "Content-Type": "application/json"})
    assert resp.status_code == 400


async def test_link_code_sent_to_the_company_number_links_the_phone_and_queues_the_reply(client: AsyncClient, db_session: AsyncSession):
    await _hooked(db_session)
    user = await make_user(db_session, await make_employee(db_session, await make_org(db_session)))
    code, _ = await create_link_code(db_session, user.id, "whatsapp")
    await db_session.commit()

    resp = await client.post(HOOK, json=upsert(f"vincular {code}"), headers=hook_headers())
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}
    address = (await db_session.execute(select(UserChannelAddress).where(UserChannelAddress.user_id == user.id))).scalar_one()
    assert (address.channel, address.address) == ("whatsapp", "5585977770000") and address.verified_at
    [reply] = await _replies(db_session)
    assert reply.address == "5585977770000" and "vinculado" in reply.message["body_text"]


async def test_unlinked_sender_only_gets_instructions(client: AsyncClient, db_session: AsyncSession):
    await _hooked(db_session)
    await client.post(HOOK, json=upsert("quais são meus chamados?"), headers=hook_headers())
    [reply] = await _replies(db_session)
    assert "vincular" in reply.message["body_text"].lower()
    assert (await db_session.execute(select(UserChannelAddress))).scalars().all() == []


async def test_only_private_text_from_other_people_on_the_right_instance_is_processed(client: AsyncClient, db_session: AsyncSession):
    await _hooked(db_session)
    ignored = [
        upsert(from_me=True),  # eco do que nós mesmos enviamos
        upsert(jid="120363012345678901@g.us"),  # grupo
        upsert(jid="987654321098765@lid"),  # só o identificador interno: sem telefone não há vínculo seguro
        upsert(jid="status@broadcast"),
        upsert(instance="outra-instancia"),
        upsert(event="connection.update"),
        upsert(text="   "),
        {"event": "messages.upsert", "instance": "gestao-ti", "data": {"key": {"remoteJid": "5585911110000@s.whatsapp.net", "fromMe": False, "id": "IMG1"}, "message": {"imageMessage": {}}}},
        {"event": "messages.upsert", "instance": "gestao-ti", "data": "lixo"},
        {"event": "messages.upsert", "instance": "gestao-ti"},
    ]
    for body in ignored:
        assert (await client.post(HOOK, json=body, headers=hook_headers())).status_code == 200
    assert await _replies(db_session) == []
    assert (await db_session.execute(select(InboundMessage))).scalars().all() == []

    # formatos aceitos: texto estendido, nome do evento em maiúsculas, lista de mensagens
    await client.post(HOOK, json=upsert("menu", extended=True, jid="5585911110000@s.whatsapp.net"), headers=hook_headers())
    await client.post(HOOK, json=upsert("menu", event="MESSAGES_UPSERT", jid="5585922220000@s.whatsapp.net"), headers=hook_headers())
    listed = upsert("menu", jid="5585933330000@s.whatsapp.net")
    listed["data"] = [listed["data"]]
    await client.post(HOOK, json=listed, headers=hook_headers())
    assert sorted(r.address for r in await _replies(db_session)) == ["5585911110000", "5585922220000", "5585933330000"]


async def test_redelivered_message_runs_once(client: AsyncClient, db_session: AsyncSession):
    await _hooked(db_session)
    body = upsert("menu", msg_id="SAME1")
    for _ in range(3):
        assert (await client.post(HOOK, json=body, headers=hook_headers())).status_code == 200
    assert len(await _replies(db_session)) == 1


async def test_per_sender_flood_is_dropped(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr(whatsapp_evolution_webhook, "_limiter", SenderRateLimiter(limit=2))
    await _hooked(db_session)
    for _ in range(5):
        await client.post(HOOK, json=upsert("menu"), headers=hook_headers())
    assert len(await _replies(db_session)) == 2


async def test_parse_inbound_is_strict_about_the_phone_format():
    good = upsert(jid="5585977770000@s.whatsapp.net")
    assert evo.parse_inbound(good, "gestao-ti")[0][1] == "5585977770000"
    for jid in ("123@s.whatsapp.net", "5585977770000@lid", "5585977770000", "abc@s.whatsapp.net", "5585977770000:12@s.whatsapp.net"):
        assert evo.parse_inbound(upsert(jid=jid), "gestao-ti") == [], jid
    assert evo.parse_inbound(None, "gestao-ti") == [] and evo.parse_inbound([], "gestao-ti") == []


async def test_connect_registers_the_webhook_once_with_secret_and_the_qr_refresh_does_not(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution):
    h = headers_for(await _admin(db_session))
    await client.put(f"{BASE}/whatsapp/config", json={"enabled": True, "provider": "evolution"}, headers=h)
    secret = (await load_channel(db_session, "whatsapp")).secrets["webhook_secret"]
    assert len(secret) >= 32

    await client.post(f"{BASE}/whatsapp/connect", headers=h)
    [(method, path, payload, key)] = [c for c in fake.calls if c[1].startswith("/webhook/set/")]
    assert (method, path, key) == ("POST", "/webhook/set/gestao-ti", API_KEY)
    hook = payload["webhook"]
    assert hook["url"].endswith("/api/v1/integrations/whatsapp/evolution/webhook") and hook["enabled"] is True
    assert hook["headers"] == {"X-Webhook-Secret": secret} and hook["events"] == ["MESSAGES_UPSERT"]

    fake.calls.clear()
    await client.post(f"{BASE}/whatsapp/connect?refresh=true", headers=h)
    assert not any(c[1].startswith("/webhook/set/") for c in fake.calls)

    await client.put(f"{BASE}/whatsapp/config", json={"enabled": True, "provider": "evolution", "instance_name": "gestao-ti"}, headers=h)
    assert (await load_channel(db_session, "whatsapp")).secrets["webhook_secret"] == secret  # salvar de novo não troca o segredo
    config = (await client.get(f"{BASE}/whatsapp/config", headers=h)).text
    assert secret not in config


async def test_saving_the_meta_provider_keeps_the_evolution_webhook_secret(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution):
    h = headers_for(await _admin(db_session))
    await client.put(f"{BASE}/whatsapp/config", json={"enabled": False, "provider": "evolution"}, headers=h)
    secret = (await load_channel(db_session, "whatsapp")).secrets["webhook_secret"]
    await client.put(f"{BASE}/whatsapp/config", json={"enabled": False, "provider": "meta"}, headers=h)
    await client.put(f"{BASE}/whatsapp/config", json={"enabled": False, "provider": "evolution"}, headers=h)
    assert (await load_channel(db_session, "whatsapp")).secrets["webhook_secret"] == secret  # continua o que a Evolution tem registrado


async def test_old_configs_without_a_webhook_secret_get_one_on_connect(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution):
    h = headers_for(await _admin(db_session))
    await _configure(db_session)  # salva sem segredo, como antes do C4
    await client.post(f"{BASE}/whatsapp/connect", headers=h)
    secret = (await load_channel(db_session, "whatsapp")).secrets["webhook_secret"]
    [(_, _, payload, _)] = [c for c in fake.calls if c[1].startswith("/webhook/set/")]
    assert payload["webhook"]["headers"]["X-Webhook-Secret"] == secret


async def test_connect_reports_when_the_webhook_cannot_be_registered(db_session: AsyncSession, fake: FakeEvolution, monkeypatch):
    fake.created = True

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/webhook/set/"):
            return httpx.Response(400, json={"message": "invalid url"})
        return fake.handler(request)

    monkeypatch.setattr(evo, "http_client", lambda timeout=15.0: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result = await evo.connect("gestao-ti", "segredo")
    assert result["state"] == "error" and "entrada de mensagens" in result["detail"]


async def test_nginx_hides_the_inbound_path_from_the_internet():
    from pathlib import Path

    conf = (Path(__file__).resolve().parents[3] / "nginx" / "app-locations.conf").read_text(encoding="utf-8")
    block = conf.index("location /api/v1/integrations/whatsapp/evolution/ {")
    assert "return 404;" in conf[block: conf.index("}", block)]
    assert block < conf.index("location /api/ {")  # a regra específica vem antes do proxy geral


async def test_send_while_disconnected_fails_fast_without_calling_send_text(db_session: AsyncSession, fake: FakeEvolution):
    """Homologação real (C5): sem sessão a Evolution não responde ao envio e a chamada pendura por 15 s."""
    await _configure(db_session)
    for created, state, expected in ((True, "close", "close"), (True, "connecting", "connecting"), (False, "close", "instância não criada")):
        fake.created, fake.state = created, state
        result = await _send()
        assert result.outcome == "retryable" and "desconectado" in result.error and expected in result.error, (state, result.error)
    assert fake.sent() == []


async def test_network_timeout_message_is_not_empty(monkeypatch):
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("")

    monkeypatch.setattr(evo, "http_client", lambda timeout=15.0: httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    result = await evo.send_text("gestao-ti", "5585999990000", "oi")
    assert result.outcome == "retryable" and "ReadTimeout" in result.error and "sem resposta" in result.error
