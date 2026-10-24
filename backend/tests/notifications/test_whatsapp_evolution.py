"""WhatsApp pelo provedor Evolution (ADR-019, C2): envio, classificação, estado da conexão e rotas de administração."""
import json
import logging
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
from tests.factories import headers_for, make_employee, make_org, make_user

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/notifications"
API_KEY = "evo-global-key-0123456789"
SessionFactory: async_sessionmaker = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _bind(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    global SessionFactory
    SessionFactory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(evo, "get_settings", lambda: SimpleNamespace(EVOLUTION_BASE_URL="http://evolution:8080", EVOLUTION_API_KEY=API_KEY))


class FakeEvolution:
    """Substitui a Evolution: registra chamadas e devolve respostas roteirizadas por rota."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, str | None]] = []
        self.created = False
        self.state = "close"  # estado da instância depois de criada
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
    [(method, path, payload, key)] = fake.calls
    assert (method, path, key) == ("POST", "/message/sendText/gestao-ti", API_KEY)
    assert payload["number"] == "5585933330000" and payload["linkPreview"] is False
    assert payload["text"] == "*Garantia vencendo*\n\n3 ativos vencem em 7 dias\n\nAbrir no sistema: http://sys/assets"


async def test_disabled_channel_and_missing_server_key_do_not_call_the_api(db_session: AsyncSession, fake: FakeEvolution, monkeypatch):
    await _configure(db_session, enabled=False)
    off = await _send()
    assert off.outcome == "permanent" and "desabilitado" in off.error

    await _configure(db_session)
    monkeypatch.setattr(evo, "get_settings", lambda: SimpleNamespace(EVOLUTION_BASE_URL="http://evolution:8080", EVOLUTION_API_KEY=""))
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
    monkeypatch.setattr(evo, "get_settings", lambda: SimpleNamespace(EVOLUTION_BASE_URL="http://evolution:8080", EVOLUTION_API_KEY=""))
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
    monkeypatch.setattr(evo, "get_settings", lambda: SimpleNamespace(EVOLUTION_BASE_URL="http://evolution:8080", EVOLUTION_API_KEY=""))
    status = (await client.get(f"{BASE}/whatsapp/status", headers=h)).json()
    assert status["state"] == "unconfigured" and "EVOLUTION_API_KEY" in status["detail"]
    connect = (await client.post(f"{BASE}/whatsapp/connect", headers=h)).json()
    assert connect["state"] == "error" and "EVOLUTION_API_KEY" in connect["detail"]

    monkeypatch.setattr(evo, "get_settings", lambda: SimpleNamespace(EVOLUTION_BASE_URL="http://evolution:8080", EVOLUTION_API_KEY=API_KEY))
    fake.logout_response = (500, {"message": "falhou"})
    resp = await client.post(f"{BASE}/whatsapp/disconnect", headers=h)
    assert resp.status_code >= 400 and "não conseguiu desconectar" in resp.text


async def test_connection_routes_require_manage_permission(client: AsyncClient, db_session: AsyncSession, fake: FakeEvolution):
    user = await make_user(db_session, await make_employee(db_session, await make_org(db_session)))
    await _configure(db_session)
    for method, path in (("get", "status"), ("post", "connect"), ("post", "disconnect")):
        assert (await getattr(client, method)(f"{BASE}/whatsapp/{path}", headers=headers_for(user))).status_code == 403
    assert (await client.get(f"{BASE}/whatsapp/status", headers=headers_for(user, "notifications.manage"))).status_code == 200
    assert fake.calls and all(path.startswith("/instance/connectionState") for _, path, _, _ in fake.calls)


async def test_instance_name_is_url_encoded_in_paths():
    assert evo.instance_path("message/sendText", "a b/c") == "message/sendText/a%20b%2Fc"
