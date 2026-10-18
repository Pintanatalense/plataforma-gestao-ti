"""Canal Navegador / Web Push (ADR-013, Fase G): chaves VAPID, inscrição, SSRF, envio e limpeza de inscrições mortas."""
import base64
import json
import os
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.notifications.channel_store import load_channel
from app.notifications.channels import webpush
from app.notifications.channels.base import AdapterContext, Message, Recipient
from app.notifications.channels.webpush import WebPushAdapter, address_for, build_payload, endpoint_allowed, generate_vapid
from app.notifications.dispatcher import Dispatcher
from app.notifications.fanout import plan_event
from app.notifications.models import Delivery, DomainEvent, NotificationRule, PushSubscription, UserChannelAddress
from app.notifications.rules_seed import seed_notification_rules
from tests.factories import headers_for, make_employee, make_org, make_user

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/notifications"
FCM = "https://fcm.googleapis.com/fcm/send/abc123"
MOZ = "https://updates.push.services.mozilla.com/wpush/v2/xyz"
SessionFactory: async_sessionmaker = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _bind(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    global SessionFactory
    SessionFactory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.notifications.fanout.quiet_until", lambda *a, **k: None)


def browser_keys() -> dict:
    """Chaves que um navegador de verdade enviaria: ponto P-256 não comprimido e segredo de autenticação de 16 bytes."""
    key = ec.generate_private_key(ec.SECP256R1())
    point = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
    return {"p256dh": b64(point), "auth": b64(os.urandom(16))}


def sub_body(endpoint: str = FCM) -> dict:
    return {"endpoint": endpoint, "keys": browser_keys()}


class FakePush:
    """Substitui `send_push`: devolve (status, detalhe) roteirizados por endpoint e guarda o que foi enviado."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict, str]] = []
        self.statuses: dict[str, int] = {}

    def __call__(self, subscription, payload, private_pem, subject, urgency):
        self.sent.append((subscription["endpoint"], payload, urgency))
        return self.statuses.get(subscription["endpoint"], 201), ""


@pytest.fixture
def fake_push(monkeypatch: pytest.MonkeyPatch) -> FakePush:
    fake = FakePush()
    monkeypatch.setattr(webpush, "send_push", fake)
    return fake


@pytest.fixture
async def users(db_session: AsyncSession):
    org = await make_org(db_session)
    first = await make_user(db_session, await make_employee(db_session, org))
    second = await make_user(db_session, await make_employee(db_session, org))
    admin = await make_user(db_session, is_admin=True)
    return first, second, admin


async def _subscribe(client: AsyncClient, user, endpoint: str = FCM):
    return await client.post(f"{BASE}/push/subscribe", json=sub_body(endpoint), headers=headers_for(user))


# --- Chaves e SSRF --------------------------------------------------------------------------------


async def test_generated_vapid_pair_is_usable_by_the_push_library():
    from py_vapid import Vapid02

    private_pem, public_key = generate_vapid()
    point = base64.urlsafe_b64decode(public_key + "=" * (-len(public_key) % 4))
    assert len(point) == 65 and point[0] == 4  # ponto não comprimido, formato de applicationServerKey
    vapid = Vapid02.from_pem(private_pem.encode())
    assert vapid.sign({"aud": "https://fcm.googleapis.com", "sub": "mailto:a@b.com", "exp": 9999999999})["Authorization"].startswith("vapid ")


@pytest.mark.parametrize("endpoint,expected", [
    (FCM, True), (MOZ, True),
    ("https://wns2-par02p.notify.windows.com/w/?token=x", True),
    ("https://web.push.apple.com/abc", True),
    ("http://fcm.googleapis.com/fcm/send/x", False),  # sem TLS
    ("https://169.254.169.254/latest/meta-data", False),  # metadados de nuvem
    ("https://localhost:8000/api", False),
    ("https://fcm.googleapis.com.evil.com/x", False),  # sufixo enganoso
    ("https://fcm.googleapis.com@evil.com/x", False),  # credencial na URL
    ("https://evilfcm.googleapis.com.attacker.io/x", False),
    ("ftp://fcm.googleapis.com/x", False),
])
async def test_only_known_push_services_are_accepted(endpoint, expected):
    assert endpoint_allowed(endpoint) is expected


# --- API ------------------------------------------------------------------------------------------


async def test_endpoints_require_authentication(client: AsyncClient):
    assert (await client.get(f"{BASE}/push/public-key")).status_code == 401
    assert (await client.post(f"{BASE}/push/subscribe", json=sub_body())).status_code == 401
    assert (await client.post(f"{BASE}/push/test")).status_code == 401


async def test_public_key_is_generated_once_and_the_private_key_stays_encrypted(client: AsyncClient, db_session: AsyncSession, users):
    first, _, admin = users
    key1 = (await client.get(f"{BASE}/push/public-key", headers=headers_for(first))).json()["public_key"]
    key2 = (await client.get(f"{BASE}/push/public-key", headers=headers_for(first))).json()["public_key"]
    assert key1 == key2 and len(key1) == 87

    stored = await load_channel(db_session, "webpush")
    assert stored.enabled and stored.config["public_key"] == key1
    assert stored.config["subject"] == f"mailto:{admin.email}"
    assert "private_key" in stored.secrets and "private_key" not in stored.config


async def test_subscribe_creates_device_and_verified_address(client: AsyncClient, db_session: AsyncSession, users):
    first, *_ = users
    resp = await _subscribe(client, first)
    assert resp.status_code == 201 and resp.json() == {"devices": 1}
    address = (await db_session.execute(select(UserChannelAddress).where(UserChannelAddress.channel == "webpush"))).scalar_one()
    assert (address.user_id, address.address) == (first.id, address_for(first.id)) and address.verified_at

    assert (await _subscribe(client, first, MOZ)).json() == {"devices": 2}
    assert (await client.get(f"{BASE}/push/status", headers=headers_for(first))).json() == {"devices": 2}
    again = await client.post(f"{BASE}/push/subscribe", json={"endpoint": FCM, "keys": browser_keys()}, headers=headers_for(first))
    assert again.json() == {"devices": 2}  # mesmo aparelho renovando as chaves não duplica
    assert (await db_session.execute(select(func.count()).select_from(UserChannelAddress))).scalar_one() == 1


@pytest.mark.parametrize("endpoint", ["https://169.254.169.254/x", "http://fcm.googleapis.com/x", "https://fcm.googleapis.com@evil.com/x"])
async def test_subscribe_refuses_unknown_hosts(client: AsyncClient, db_session: AsyncSession, users, endpoint):
    resp = await _subscribe(client, users[0], endpoint)
    assert resp.status_code >= 400 and "não suportado" in resp.text
    assert (await db_session.execute(select(func.count()).select_from(PushSubscription))).scalar_one() == 0


async def test_device_limit_per_account(client: AsyncClient, users):
    first, *_ = users
    for n in range(10):
        assert (await _subscribe(client, first, f"https://fcm.googleapis.com/fcm/send/dev{n}")).status_code == 201
    over = await _subscribe(client, first, "https://fcm.googleapis.com/fcm/send/dev-extra")
    assert over.status_code >= 400 and "Limite" in over.text


async def test_unsubscribe_removes_device_and_address_only_for_the_owner(client: AsyncClient, db_session: AsyncSession, users):
    first, second, _ = users
    await _subscribe(client, first, FCM)
    await _subscribe(client, first, MOZ)

    intruder = await client.post(f"{BASE}/push/unsubscribe", json={"endpoint": FCM}, headers=headers_for(second))
    assert intruder.json() == {"devices": 0}
    assert (await client.get(f"{BASE}/push/status", headers=headers_for(first))).json() == {"devices": 2}  # nada foi removido

    assert (await client.post(f"{BASE}/push/unsubscribe", json={"endpoint": FCM}, headers=headers_for(first))).json() == {"devices": 1}
    assert (await db_session.execute(select(func.count()).select_from(UserChannelAddress))).scalar_one() == 1
    assert (await client.post(f"{BASE}/push/unsubscribe", json={"endpoint": MOZ}, headers=headers_for(first))).json() == {"devices": 0}
    assert (await db_session.execute(select(func.count()).select_from(UserChannelAddress))).scalar_one() == 0


async def test_browser_shared_between_accounts_moves_to_the_latest_user(client: AsyncClient, db_session: AsyncSession, users):
    first, second, _ = users
    await _subscribe(client, first, FCM)
    await _subscribe(client, second, FCM)  # outra conta entrou no mesmo navegador
    assert (await client.get(f"{BASE}/push/status", headers=headers_for(first))).json() == {"devices": 0}
    assert (await client.get(f"{BASE}/push/status", headers=headers_for(second))).json() == {"devices": 1}
    owners = set((await db_session.execute(select(UserChannelAddress.user_id).where(UserChannelAddress.channel == "webpush"))).scalars())
    assert owners == {second.id}  # a conta anterior deixa de receber pop-ups naquele navegador


async def test_prefs_can_turn_the_browser_channel_off(client: AsyncClient, users):
    resp = await client.put(f"{BASE}/prefs", json={"channels_disabled": ["webpush"]}, headers=headers_for(users[0]))
    assert resp.status_code == 200 and resp.json()["channels_disabled"] == ["webpush"]


# --- Envio ----------------------------------------------------------------------------------------


async def _provisioned(client: AsyncClient, user):
    await client.get(f"{BASE}/push/public-key", headers=headers_for(user))


def adapter() -> WebPushAdapter:
    return WebPushAdapter(AdapterContext(session_factory=SessionFactory))


async def test_send_reaches_every_device_with_a_short_payload(client: AsyncClient, users, fake_push: FakePush):
    first, *_ = users
    await _provisioned(client, first)
    await _subscribe(client, first, FCM)
    await _subscribe(client, first, MOZ)

    message = Message(title="Chamado #12 atualizado", body_text="Ana respondeu:\n" + "x" * 400, link="/service-desk/12", priority="high")
    result = await adapter().send(Recipient(address=address_for(first.id), user_id=str(first.id)), message)

    assert result.outcome == "ok"
    assert {url for url, _, _ in fake_push.sent} == {FCM, MOZ}
    _, payload, urgency = fake_push.sent[0]
    assert urgency == "high" and payload["url"] == "/service-desk/12" and payload["title"] == "Chamado #12 atualizado"
    assert len(payload["body"]) <= 180 and "\n" not in payload["body"]


async def test_expired_subscription_is_deleted_and_the_address_goes_with_the_last_device(client: AsyncClient, db_session: AsyncSession, users, fake_push: FakePush):
    first, *_ = users
    await _provisioned(client, first)
    await _subscribe(client, first, FCM)
    await _subscribe(client, first, MOZ)
    fake_push.statuses[FCM] = 410

    mixed = await adapter().send(Recipient(address="x", user_id=str(first.id)), Message(title="t", body_text="b"))
    assert mixed.outcome == "ok"  # um aparelho recebeu
    left = list((await db_session.execute(select(PushSubscription.endpoint))).scalars())
    assert left == [MOZ]

    fake_push.statuses[MOZ] = 404
    dead = await adapter().send(Recipient(address="x", user_id=str(first.id)), Message(title="t", body_text="b"))
    assert dead.outcome == "permanent"
    assert (await db_session.execute(select(func.count()).select_from(PushSubscription))).scalar_one() == 0
    assert (await db_session.execute(select(func.count()).select_from(UserChannelAddress))).scalar_one() == 0


@pytest.mark.parametrize("status,outcome", [(500, "retryable"), (429, "retryable"), (0, "retryable"), (400, "permanent"), (403, "permanent")])
async def test_failure_classification(client: AsyncClient, db_session: AsyncSession, users, fake_push: FakePush, status, outcome):
    first, *_ = users
    await _provisioned(client, first)
    await _subscribe(client, first, FCM)
    fake_push.statuses[FCM] = status
    result = await adapter().send(Recipient(address="x", user_id=str(first.id)), Message(title="t", body_text="b"))
    assert result.outcome == outcome
    assert (await db_session.execute(select(func.count()).select_from(PushSubscription))).scalar_one() == 1  # só 404/410 apagam


async def test_send_without_devices_or_channel_fails_permanently(client: AsyncClient, users, fake_push: FakePush):
    first, *_ = users
    no_channel = await adapter().send(Recipient(address="x", user_id=str(first.id)), Message(title="t", body_text="b"))
    assert no_channel.outcome == "permanent"
    await _provisioned(client, first)
    no_device = await adapter().send(Recipient(address="x", user_id=str(first.id)), Message(title="t", body_text="b"))
    assert no_device.outcome == "permanent" and "Nenhum navegador" in no_device.error and fake_push.sent == []


async def test_real_encryption_and_vapid_header_without_network(monkeypatch: pytest.MonkeyPatch):
    """Exercita pywebpush de verdade (criptografia aes128gcm + assinatura VAPID); só o HTTP é falso."""
    seen = {}

    class Resp:
        status_code = 201
        text = ""
        reason = "Created"
        headers: dict = {}

    def fake_post(url, data=None, headers=None, timeout=None, **kw):
        seen.update(url=url, headers=headers, size=len(data or b""))
        return Resp()

    monkeypatch.setattr("pywebpush.requests.post", fake_post)
    private_pem, _ = generate_vapid()
    status, detail = webpush.send_push(
        {"endpoint": FCM, "keys": browser_keys()}, {"title": "oi", "body": "teste", "url": "/"}, private_pem, "mailto:ti@empresa.com", "normal"
    )
    assert (status, detail) == (201, "")
    assert seen["url"] == FCM and seen["size"] > 20
    assert seen["headers"]["content-encoding"] == "aes128gcm" and seen["headers"]["authorization"].startswith("vapid t=")
    assert seen["headers"]["urgency"] == "normal"


async def test_payload_builder_defaults():
    assert build_payload(Message(title="", body_text="a\nb"))["title"] == "Plataforma de Gestão de TI"
    assert build_payload(Message(title="t", body_text="a\nb"))["body"] == "a b"


# --- Integração com o hub -------------------------------------------------------------------------


async def test_default_rules_deliver_to_the_browser_channel_of_a_subscribed_user(client: AsyncClient, db_session: AsyncSession, users):
    first, *_ = users
    await seed_notification_rules(db_session)
    await db_session.commit()
    await _provisioned(client, first)
    await _subscribe(client, first, FCM)

    event = DomainEvent(
        id=__import__("uuid").uuid4(), event_type="ticket.assigned", entity_type="ticket", priority="normal",
        payload={"ticket_id": str(__import__("uuid").uuid4()), "title": "Sem rede", "assignee_id": str(first.id), "priority": "HIGH"},
    )
    rules = list((await db_session.execute(select(NotificationRule).where(NotificationRule.enabled.is_(True)))).scalars())
    plans = await plan_event(db_session, event, rules, {"in_app", "email", "webpush"}, datetime.now(timezone.utc))
    assert [(p.user_id, p.address) for p in plans if p.channel == "webpush"] == [(first.id, address_for(first.id))]


async def test_test_button_goes_through_the_worker(client: AsyncClient, db_session: AsyncSession, users, fake_push: FakePush):
    first, *_ = users
    refused = await client.post(f"{BASE}/push/test", headers=headers_for(first))
    assert refused.status_code >= 400 and "Ative" in refused.text

    await _provisioned(client, first)
    await _subscribe(client, first, FCM)
    assert (await client.post(f"{BASE}/push/test", headers=headers_for(first))).status_code == 202
    await Dispatcher(SessionFactory).run_once()

    delivery = (await db_session.execute(select(Delivery).where(Delivery.channel == "webpush"))).scalar_one()
    await db_session.refresh(delivery)
    assert delivery.status == "SENT" and len(fake_push.sent) == 1
    assert "funcionando" in json.dumps(fake_push.sent[0][1], ensure_ascii=False)
