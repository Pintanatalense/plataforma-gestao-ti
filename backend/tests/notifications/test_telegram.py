"""Telegram + camada conversacional + vínculo por código (ADR-013, Fase C)."""
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
from app.notifications.channel_store import load_channel, save_channel
from app.notifications.channels.base import AdapterContext, Message, Recipient
from app.notifications.channels.telegram import TelegramAdapter, classify, render_text
from app.notifications.conversation.engine import UNLINKED_REPLY, ConversationEngine
from app.notifications.conversation.inbound import process_inbound
from app.notifications.dispatcher import Dispatcher
from app.notifications.fanout import fan_out_batch, plan_event
from app.notifications.linking import (
    MAX_CODES_PER_HOUR,
    create_link_code,
    hash_code,
    load_addresses,
    normalize_code,
)
from app.notifications.models import (
    ChannelLinkCode,
    Delivery,
    DomainEvent,
    InboundMessage,
    NotificationRule,
    UserChannelAddress,
    UserNotificationPref,
)
from app.notifications.rules_seed import seed_notification_rules
from app.notifications.telegram_poller import SenderRateLimiter, handle_update, last_update_id, parse_update, poll_once
from app.service_desk.models import Ticket, TicketInteraction
from tests.factories import headers_for, make_employee, make_org, make_ticket_category, make_user

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/notifications"
SessionFactory: async_sessionmaker = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _bind(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    global SessionFactory
    SessionFactory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.notifications.fanout.quiet_until", lambda *a, **k: None)


class FakeTelegram:
    """Substitui a Bot API: registra chamadas e devolve respostas roteirizadas por método."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.responses: dict[str, tuple[int, dict]] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        payload = json.loads(request.content or b"{}")
        self.calls.append((method, payload))
        status, body = self.responses.get(method, (200, {"ok": True, "result": {"message_id": 77, "username": "gti_bot"}}))
        return httpx.Response(status, json=body)

    def sent(self) -> list[dict]:
        return [p for m, p in self.calls if m == "sendMessage"]


@pytest.fixture
def tg(monkeypatch: pytest.MonkeyPatch) -> FakeTelegram:
    fake = FakeTelegram()
    monkeypatch.setattr(
        "app.notifications.channels.telegram.http_client",
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
    other_emp: object
    attendant: object
    admin: object


async def _grant(db: AsyncSession, user, role_name: str, code: str | None) -> None:
    role = Role(name=role_name)
    db.add(role)
    await db.flush()
    if code:
        perm = (await db.execute(select(Permission).where(Permission.code == code))).scalar_one_or_none()
        if perm is None:
            perm = Permission(code=code)
            db.add(perm)
            await db.flush()
        await db.execute(role_permission_association.insert().values(role_id=role.id, permission_id=perm.id))
    await db.execute(user_role_association.insert().values(user_id=user.id, role_id=role.id))
    await db.commit()


@pytest.fixture
async def world(db_session: AsyncSession) -> World:
    org = await make_org(db_session)
    category = await make_ticket_category(db_session, org.sector)
    requester_emp = await make_employee(db_session, org)
    other_emp = await make_employee(db_session, org)
    attendant_emp = await make_employee(db_session, org)
    requester = await make_user(db_session, requester_emp)
    other = await make_user(db_session, other_emp)
    attendant = await make_user(db_session, attendant_emp)
    admin = await make_user(db_session, is_admin=True)
    await _grant(db_session, attendant, "Atendente", "service_desk.tickets.manage")
    await save_channel(db_session, "telegram", True, {"bot_username": "gti_bot", "app_base_url": "http://sys"}, {"bot_token": "1:TOKEN"})
    await seed_notification_rules(db_session)
    await db_session.commit()
    return World(org, category.id, requester, requester_emp, other, other_emp, attendant, admin)


async def _link(db: AsyncSession, user, chat: str) -> None:
    """Vincula via fluxo real: código + mensagem do chat."""
    code, _ = await create_link_code(db, user.id, "telegram")
    await db.commit()
    replies, user_id = await ConversationEngine(db).handle("telegram", chat, f"/vincular {code}")
    await db.commit()
    assert user_id == user.id, replies


async def say(db: AsyncSession, chat: str, text: str) -> str:
    replies, _ = await ConversationEngine(db).handle("telegram", chat, text)
    await db.commit()
    return "\n".join(replies)


# --- Vínculo por código ---------------------------------------------------------------------------


async def test_link_code_is_stored_hashed_and_single_use(db_session: AsyncSession, world: World):
    code, expires = await create_link_code(db_session, world.requester.id, "telegram")
    await db_session.commit()
    row = (await db_session.execute(select(ChannelLinkCode))).scalar_one()
    assert len(code) == 6 and code not in row.code_hash and row.code_hash == hash_code("telegram", code)
    assert timedelta(minutes=9) < expires - datetime.now(timezone.utc) <= timedelta(minutes=10)
    assert normalize_code(" ab-c 23 ") == "ABC23"

    first = await say(db_session, "111", f"/vincular {code}")
    assert "vinculado" in first
    again = await say(db_session, "222", f"/vincular {code.lower()}")
    assert "inválido" in again  # já usado


async def test_new_code_invalidates_the_previous_one_and_is_rate_limited(db_session: AsyncSession, world: World):
    old, _ = await create_link_code(db_session, world.requester.id, "telegram")
    new, _ = await create_link_code(db_session, world.requester.id, "telegram")
    await db_session.commit()
    assert "inválido" in await say(db_session, "111", f"/vincular {old}")
    assert "vinculado" in await say(db_session, "111", f"/vincular {new}")

    for _ in range(MAX_CODES_PER_HOUR):
        try:
            await create_link_code(db_session, world.other.id, "telegram")
        except Exception:
            break
    with pytest.raises(Exception, match="Muitos códigos"):
        await create_link_code(db_session, world.other.id, "telegram")


async def test_expired_code_is_refused(db_session: AsyncSession, world: World):
    code, _ = await create_link_code(db_session, world.requester.id, "telegram")
    await db_session.execute(update(ChannelLinkCode).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    await db_session.commit()
    assert "inválido" in await say(db_session, "111", f"/vincular {code}")
    assert (await db_session.execute(select(func.count()).select_from(UserChannelAddress))).scalar_one() == 0


async def test_five_wrong_codes_lock_the_sender_even_for_the_right_code(db_session: AsyncSession, world: World):
    code, _ = await create_link_code(db_session, world.requester.id, "telegram")
    await db_session.commit()
    for _ in range(5):
        assert "inválido" in await say(db_session, "666", "/vincular ZZZZZZ")
    assert "Muitas tentativas" in await say(db_session, "666", f"/vincular {code}")
    # outro chat não é afetado pelo bloqueio
    assert "vinculado" in await say(db_session, "111", f"/vincular {code}")


async def test_deep_link_start_payload_links_too(db_session: AsyncSession, world: World):
    code, _ = await create_link_code(db_session, world.requester.id, "telegram")
    await db_session.commit()
    assert "vinculado" in await say(db_session, "111", f"/start {code}")


async def test_chat_linked_to_another_account_cannot_be_taken(db_session: AsyncSession, world: World):
    await _link(db_session, world.requester, "111")
    code, _ = await create_link_code(db_session, world.other.id, "telegram")
    await db_session.commit()
    reply = await say(db_session, "111", f"/vincular {code}")
    assert "outra conta" in reply
    owner = (await db_session.execute(select(UserChannelAddress).where(UserChannelAddress.address == "111"))).scalar_one()
    assert owner.user_id == world.requester.id


async def test_relinking_replaces_the_old_chat(db_session: AsyncSession, world: World):
    await _link(db_session, world.requester, "111")
    await _link(db_session, world.requester, "999")
    rows = (await db_session.execute(select(UserChannelAddress))).scalars().all()
    assert [r.address for r in rows] == ["999"]


# --- Remetente não vinculado ----------------------------------------------------------------------


async def test_unlinked_sender_learns_nothing(db_session: AsyncSession, world: World):
    await say(db_session, "111", "/start")  # cria sessão
    replies = [await say(db_session, "555", t) for t in ("1", "2", "3", "menu", "oi", "/desvincular", "qual o meu chamado?")]
    assert set(replies) == {UNLINKED_REPLY}
    assert world.requester_emp.name not in UNLINKED_REPLY


async def test_deactivated_user_loses_chat_access_immediately(db_session: AsyncSession, world: World):
    await _link(db_session, world.requester, "111")
    assert "Abrir novo chamado" in await say(db_session, "111", "menu")
    world.requester.is_active = False
    await db_session.commit()
    assert await say(db_session, "111", "2") == UNLINKED_REPLY


# --- Fluxos como o usuário vinculado --------------------------------------------------------------


async def _open_ticket(db: AsyncSession, chat: str, title="Impressora parada") -> str:
    await say(db, chat, "1")
    await say(db, chat, "1")  # primeira categoria
    await say(db, chat, title)
    return await say(db, chat, "Não imprime desde ontem")


async def test_requester_opens_ticket_by_chat_and_attendants_are_notified(db_session: AsyncSession, world: World):
    await _link(db_session, world.requester, "111")
    reply = await _open_ticket(db_session, "111")
    assert "Chamado criado" in reply

    ticket = (await db_session.execute(select(Ticket))).scalar_one()
    assert (ticket.requester_id, ticket.title, ticket.status) == (world.requester_emp.id, "Impressora parada", "OPENED")
    assert ticket.description.startswith("[Aberto via chat]")

    event = (await db_session.execute(select(DomainEvent).where(DomainEvent.event_type == "ticket.created"))).scalar_one()
    assert event.actor_user_id == world.requester.id  # age como o usuário vinculado


async def test_category_with_required_fields_fails_gracefully(db_session: AsyncSession, world: World):
    from app.service_desk.models import TicketCategory

    cat = (await db_session.execute(select(TicketCategory))).scalars().first()
    cat.form_schema = [{"id": "urgencia", "label": "Urgência", "type": "text", "required": True}]
    await db_session.commit()
    await _link(db_session, world.requester, "111")
    reply = await _open_ticket(db_session, "111")
    assert "Não foi possível concluir" in reply and "Urgência" in reply
    assert (await db_session.execute(select(func.count()).select_from(Ticket))).scalar_one() == 0
    assert "Abrir novo chamado" in reply  # volta ao menu, sem ficar preso no estado


async def test_listing_shows_only_tickets_the_user_may_see(db_session: AsyncSession, world: World):
    await _link(db_session, world.requester, "111")
    await _link(db_session, world.other, "222")
    await _open_ticket(db_session, "111", "Do solicitante")
    await _open_ticket(db_session, "222", "Do outro")

    mine = await say(db_session, "111", "2")
    assert "Do solicitante" in mine and "Do outro" not in mine
    theirs = await say(db_session, "222", "2")
    assert "Do outro" in theirs and "Do solicitante" not in theirs


async def test_reply_goes_to_ticket_and_cannot_target_someone_elses(db_session: AsyncSession, world: World):
    await _link(db_session, world.requester, "111")
    await _link(db_session, world.other, "222")
    await _open_ticket(db_session, "111", "Chamado A")
    ticket = (await db_session.execute(select(Ticket))).scalar_one()
    prefix = str(ticket.id)[:8]

    await say(db_session, "222", "3")
    assert "não encontrado" in await say(db_session, "222", prefix)
    await say(db_session, "222", "0")

    await say(db_session, "111", "3")
    assert "Chamado: Chamado A" in await say(db_session, "111", prefix)
    assert "Mensagem registrada" in await say(db_session, "111", "Ainda sem impressão")
    interaction = (await db_session.execute(select(TicketInteraction))).scalar_one()
    assert interaction.message == "[Via chat] Ainda sem impressão"
    assert interaction.is_internal is False and interaction.author_id == world.requester.id


async def test_short_or_ambiguous_ticket_prefix_is_not_accepted(db_session: AsyncSession, world: World):
    await _link(db_session, world.requester, "111")
    await _open_ticket(db_session, "111")
    await say(db_session, "111", "3")
    assert "pelo menos 4" in await say(db_session, "111", "ab")


async def test_attendant_sees_sector_tickets_and_chat_never_writes_internal_notes(db_session: AsyncSession, world: World):
    await _link(db_session, world.requester, "111")
    await _link(db_session, world.attendant, "333")
    await _open_ticket(db_session, "111", "Pedido do setor")
    ticket = (await db_session.execute(select(Ticket))).scalar_one()

    assert "Pedido do setor" in await say(db_session, "333", "2")
    await say(db_session, "333", "3")
    await say(db_session, "333", str(ticket.id)[:8])
    await say(db_session, "333", "Vou verificar")
    note = (await db_session.execute(select(TicketInteraction))).scalar_one()
    assert note.is_internal is False  # técnico no chat responde ao solicitante, nunca grava nota interna


async def test_unlink_command_and_endpoint(client: AsyncClient, db_session: AsyncSession, world: World):
    await _link(db_session, world.requester, "111")
    assert "desvinculado" in await say(db_session, "111", "/desvincular")
    assert await say(db_session, "111", "menu") == UNLINKED_REPLY
    assert (await db_session.execute(select(func.count()).select_from(UserChannelAddress))).scalar_one() == 0

    await _link(db_session, world.other, "222")
    assert (await client.delete(f"{BASE}/channels/telegram", headers=headers_for(world.other))).status_code == 204
    assert (await db_session.execute(select(func.count()).select_from(UserChannelAddress))).scalar_one() == 0


# --- Entrada: deduplicação, resposta como entrega -------------------------------------------------


async def test_redelivered_message_runs_once(db_session: AsyncSession, world: World):
    await _link(db_session, world.requester, "111")
    for _ in range(3):
        await process_inbound(db_session, "telegram", "5001", "111", "1")
        await db_session.commit()
    replies = (await db_session.execute(select(Delivery).where(Delivery.channel == "telegram"))).scalars().all()
    assert len(replies) == 1
    assert (await db_session.execute(select(func.count()).select_from(InboundMessage))).scalar_one() == 1


async def test_reply_is_a_high_priority_delivery_sent_by_the_dispatcher(db_session: AsyncSession, world: World, tg: FakeTelegram):
    await _link(db_session, world.requester, "111")
    await process_inbound(db_session, "telegram", "6001", "111", "menu")
    await db_session.commit()

    delivery = (await db_session.execute(select(Delivery).where(Delivery.channel == "telegram"))).scalar_one()
    assert (delivery.address, delivery.priority, delivery.status) == ("111", "high", "PENDING")
    event = (await db_session.execute(select(DomainEvent).where(DomainEvent.id == delivery.event_id))).scalar_one()
    assert event.event_type == "conversation.reply" and "Abrir novo chamado" not in json.dumps(event.payload)

    await Dispatcher(SessionFactory).run_once()
    assert tg.sent()[-1]["chat_id"] == "111" and "Abrir novo chamado" in tg.sent()[-1]["text"]
    await db_session.refresh(delivery)
    assert delivery.status == "SENT" and delivery.provider_message_id == "77"


# --- Adapter --------------------------------------------------------------------------------------


async def test_classify_maps_api_answers_to_retry_policy():
    ok = classify(200, {"ok": True, "result": {"message_id": 9}})
    assert (ok.outcome, ok.provider_message_id) == ("ok", "9")
    limited = classify(429, {"description": "Too Many Requests", "parameters": {"retry_after": 17}})
    assert (limited.outcome, limited.retry_after_seconds) == ("retryable", 17)
    assert classify(403, {"description": "bot was blocked by the user"}).outcome == "permanent"
    assert classify(400, {"description": "chat not found"}).outcome == "permanent"
    assert classify(401, {"description": "Unauthorized"}).outcome == "retryable"
    assert classify(502, {}).outcome == "retryable"
    assert classify(0, {"description": "ConnectError"}).outcome == "retryable"


async def test_render_text_adds_link_and_truncates():
    msg = Message(title="Título", body_text="Corpo", link="/service-desk/1")
    assert render_text(msg, "http://sys/") == "Título\n\nCorpo\n\nAbrir no sistema: http://sys/service-desk/1"
    assert "Abrir no sistema" not in render_text(msg, None)
    assert len(render_text(Message(title="t", body_text="x" * 9000), None)) <= 4000


async def test_adapter_refuses_when_disabled_and_checks_health(db_session: AsyncSession, tg: FakeTelegram):
    adapter = TelegramAdapter(AdapterContext(session_factory=SessionFactory))
    result = await adapter.send(Recipient(address="1"), Message(title="t", body_text="b"))
    assert result.outcome == "permanent" and "desabilitado" in result.error
    assert (await adapter.health()).ok is False

    await save_channel(db_session, "telegram", True, {}, {"bot_token": "1:T"})
    await db_session.commit()
    health = await adapter.health()
    assert health.ok is True and health.detail == "@gti_bot"
    sent = await adapter.send(Recipient(address="42"), Message(title="t", body_text="b"))
    assert sent.outcome == "ok" and tg.sent()[-1]["chat_id"] == "42"

    tg.responses["sendMessage"] = (403, {"ok": False, "description": "Forbidden: bot was blocked"})
    assert (await adapter.send(Recipient(address="42"), Message(title="t", body_text="b"))).outcome == "permanent"


# --- Canal "preferred" no fan-out -----------------------------------------------------------------


async def _created_event(db: AsyncSession, world: World, actor=None) -> DomainEvent:
    event = DomainEvent(
        id=uuid.uuid4(), event_type="ticket.assigned", entity_type="ticket", priority="normal", actor_user_id=actor,
        payload={"ticket_id": str(uuid.uuid4()), "title": "Sem rede", "requester_employee_id": str(world.requester_emp.id),
                 "assignee_id": str(world.attendant.id), "responsible_sector_id": str(world.org.sector.id), "priority": "HIGH"},
    )
    return event


async def _plan(db: AsyncSession, event: DomainEvent, channels_on=("in_app", "email", "telegram")):
    rules = list((await db.execute(select(NotificationRule).where(NotificationRule.enabled.is_(True)))).scalars())
    return await plan_event(db, event, rules, set(channels_on), datetime.now(timezone.utc))


async def test_preferred_delivers_on_telegram_only_to_verified_linked_users(db_session: AsyncSession, world: World):
    await _link(db_session, world.attendant, "333")
    event = await _created_event(db_session, world)
    plans = await _plan(db_session, event)

    telegram = [(p.user_id, p.address) for p in plans if p.channel == "telegram"]
    assert telegram == [(world.attendant.id, "333")]  # o solicitante não vinculou: só in-app
    assert any(p.channel == "in_app" and p.user_id == world.requester.id for p in plans)
    assert not any(p.channel == "telegram" and p.user_id == world.requester.id for p in plans)


async def test_unverified_address_and_disabled_channel_and_prefs_block_telegram(db_session: AsyncSession, world: World):
    db_session.add(UserChannelAddress(user_id=world.attendant.id, channel="telegram", address="333", verified_at=None))
    await db_session.commit()
    event = await _created_event(db_session, world)
    assert not [p for p in await _plan(db_session, event) if p.channel == "telegram"]
    assert await load_addresses(db_session, {world.attendant.id}) == {}

    await db_session.execute(update(UserChannelAddress).values(verified_at=datetime.now(timezone.utc)))
    await db_session.commit()
    assert [p for p in await _plan(db_session, event) if p.channel == "telegram"]
    assert not [p for p in await _plan(db_session, event, channels_on=("in_app", "email")) if p.channel == "telegram"]

    db_session.add(UserNotificationPref(user_id=world.attendant.id, channels_disabled=["telegram"]))
    await db_session.commit()
    plans = await _plan(db_session, event)
    assert not [p for p in plans if p.channel == "telegram"]
    assert any(p.channel == "in_app" and p.user_id == world.attendant.id for p in plans)  # piso intacto


async def test_ticket_event_reaches_telegram_end_to_end(client: AsyncClient, db_session: AsyncSession, world: World, tg: FakeTelegram):
    await _link(db_session, world.attendant, "333")
    resp = await client.post(
        "/api/v1/tickets",
        json={"title": "VPN caiu", "description": "d", "priority": "HIGH", "category_id": str(world.category_id)},
        headers=headers_for(world.requester),
    )
    assert resp.status_code == 201
    async with SessionFactory() as s:
        await fan_out_batch(s)
        await s.commit()
    await Dispatcher(SessionFactory).run_once(limit=50)

    assert [m["chat_id"] for m in tg.sent()] == ["333"]
    assert "VPN caiu" in tg.sent()[0]["text"] and "http://sys/service-desk/" in tg.sent()[0]["text"]


# --- Poller ---------------------------------------------------------------------------------------


def _update(update_id: int, chat_id: int, text: str | None = "oi", chat_type="private") -> dict:
    message: dict = {"chat": {"id": chat_id, "type": chat_type}, "from": {"id": chat_id}}
    if text is not None:
        message["text"] = text
    return {"update_id": update_id, "message": message}


async def test_parse_update_accepts_only_private_text():
    assert parse_update(_update(1, 10, "olá")) == ("1", "10", "olá")
    assert parse_update(_update(2, -100, "olá", chat_type="group")) is None
    assert parse_update(_update(3, 10, None)) is None
    assert parse_update({"update_id": 4, "edited_message": {}}) is None


async def test_rate_limiter_per_sender():
    limiter = SenderRateLimiter(limit=3, window=60)
    assert [limiter.allow("a", now=t) for t in (0, 1, 2, 3)] == [True, True, True, False]
    assert limiter.allow("b", now=3) is True
    assert limiter.allow("a", now=61) is True


async def test_poll_once_processes_updates_in_order_and_advances_offset(db_session: AsyncSession, world: World, tg: FakeTelegram):
    await _link(db_session, world.requester, "111")
    tg.responses["getUpdates"] = (200, {"ok": True, "result": [_update(10, 111, "menu"), _update(11, 111, "2"), _update(12, -5, "x", "group")]})
    offset, status = await poll_once(SessionFactory, "1:TOKEN", None, SenderRateLimiter())
    assert (offset, status) == (13, 200)
    assert (await db_session.execute(select(func.count()).select_from(Delivery).where(Delivery.channel == "telegram"))).scalar_one() == 2
    assert await last_update_id(SessionFactory) == 11
    # offset enviado nas chamadas seguintes e allowed_updates restrito a mensagens
    await poll_once(SessionFactory, "1:TOKEN", 13, SenderRateLimiter())
    method, payload = tg.calls[-1]
    assert method == "getUpdates" and payload["offset"] == 13 and payload["allowed_updates"] == ["message"]


async def test_poll_once_survives_api_errors_and_poison_updates(db_session: AsyncSession, world: World, tg: FakeTelegram, monkeypatch):
    tg.responses["getUpdates"] = (502, {"description": "Bad Gateway"})
    assert await poll_once(SessionFactory, "1:T", 5, SenderRateLimiter()) == (5, 502)

    async def boom(*a, **k):
        raise RuntimeError("quebrou")

    monkeypatch.setattr("app.notifications.telegram_poller.handle_update", boom)
    tg.responses["getUpdates"] = (200, {"ok": True, "result": [_update(20, 1), _update(21, 1)]})
    offset, status = await poll_once(SessionFactory, "1:T", None, SenderRateLimiter())
    assert (offset, status) == (22, 200)  # não trava na mensagem ruim


async def test_replayed_update_after_restart_is_ignored(db_session: AsyncSession, world: World):
    limiter = SenderRateLimiter()
    assert await handle_update(SessionFactory, _update(30, 111, "oi"), limiter) is True
    assert await handle_update(SessionFactory, _update(30, 111, "oi"), limiter) is False


# --- Configuração do canal (administração) --------------------------------------------------------


async def test_config_validates_token_encrypts_it_and_never_returns_it(client: AsyncClient, db_session: AsyncSession, world: World, tg: FakeTelegram):
    h = headers_for(world.admin)
    await save_channel(db_session, "telegram", False, {}, {})
    await db_session.commit()

    saved = await client.put(f"{BASE}/telegram/config", json={"enabled": True, "bot_token": "999:SECRET-TOKEN", "app_base_url": "http://x"}, headers=h)
    assert saved.status_code == 200
    body = saved.json()
    assert body["bot_token"] == "********" and body["bot_username"] == "gti_bot" and "SECRET-TOKEN" not in json.dumps(body)
    assert tg.calls[-1][0] == "getMe"

    row = await load_channel(db_session, "telegram")
    assert row.secrets["bot_token"] == "999:SECRET-TOKEN" and row.config["app_base_url"] == "http://x"
    raw = (await db_session.execute(select(func_secret()))).scalar_one()
    assert "SECRET-TOKEN" not in raw

    # reenviar mascarado preserva; sem chamada nova ao getMe
    calls = len(tg.calls)
    kept = await client.put(f"{BASE}/telegram/config", json={"enabled": True, "bot_token": "********", "app_base_url": "http://y"}, headers=h)
    assert kept.status_code == 200 and len(tg.calls) == calls
    assert (await load_channel(db_session, "telegram")).secrets["bot_token"] == "999:SECRET-TOKEN"


def func_secret():
    from app.notifications.models import ChannelConfig

    return ChannelConfig.secrets_encrypted


async def test_config_rejects_bad_token_and_enabling_without_one(client: AsyncClient, db_session: AsyncSession, world: World, tg: FakeTelegram):
    h = headers_for(world.admin)
    tg.responses["getMe"] = (401, {"ok": False, "description": "Unauthorized"})
    bad = await client.put(f"{BASE}/telegram/config", json={"enabled": True, "bot_token": "1:BAD"}, headers=h)
    assert bad.status_code >= 400 and "recusou" in bad.text
    assert (await load_channel(db_session, "telegram")).secrets["bot_token"] == "1:TOKEN"  # nada foi gravado

    from app.notifications.models import ChannelConfig

    await db_session.execute(ChannelConfig.__table__.delete())
    await db_session.commit()
    none = await client.put(f"{BASE}/telegram/config", json={"enabled": True, "bot_token": ""}, headers=h)
    assert none.status_code >= 400 and "token" in none.text.lower()


async def test_config_requires_manage_permission(client: AsyncClient, world: World):
    assert (await client.get(f"{BASE}/telegram/config", headers=headers_for(world.requester))).status_code == 403
    assert (await client.get(f"{BASE}/telegram/config", headers=headers_for(world.requester, "notifications.manage"))).status_code == 200


# --- API do usuário -------------------------------------------------------------------------------


async def test_channels_api_reports_availability_and_issues_codes(client: AsyncClient, db_session: AsyncSession, world: World):
    h = headers_for(world.requester)
    channels = (await client.get(f"{BASE}/channels", headers=h)).json()["channels"][0]
    assert (channels["channel"], channels["available"], channels["linked"], channels["bot_username"]) == ("telegram", True, False, "gti_bot")

    issued = (await client.post(f"{BASE}/channels/telegram/link-code", headers=h)).json()
    assert issued["command"] == f"/vincular {issued['code']}" and issued["deep_link"] == f"https://t.me/gti_bot?start={issued['code']}"
    assert "vinculado" in await say(db_session, "111", issued["command"])
    assert (await client.get(f"{BASE}/channels", headers=h)).json()["channels"][0]["linked"] is True


async def test_link_code_requires_enabled_channel_and_known_channel(client: AsyncClient, db_session: AsyncSession, world: World):
    h = headers_for(world.requester)
    assert (await client.post(f"{BASE}/channels/whatsapp/link-code", headers=h)).status_code >= 400
    from app.notifications.models import ChannelConfig

    await db_session.execute(ChannelConfig.__table__.update().values(enabled=False))
    await db_session.commit()
    disabled = await client.post(f"{BASE}/channels/telegram/link-code", headers=h)
    assert disabled.status_code >= 400 and "habilitado" in disabled.text
    assert not (await client.get(f"{BASE}/channels", headers=h)).json()["channels"][0]["available"]


async def test_channels_api_requires_login(client: AsyncClient):
    assert (await client.get(f"{BASE}/channels")).status_code in (401, 403)
    assert (await client.post(f"{BASE}/channels/telegram/link-code")).status_code in (401, 403)


async def test_prefs_accept_telegram_as_configurable_channel(client: AsyncClient, world: World):
    h = headers_for(world.requester)
    ok = await client.put(f"{BASE}/prefs", json={"channels_disabled": ["telegram"]}, headers=h)
    assert ok.status_code == 200 and ok.json()["channels_disabled"] == ["telegram"]


async def test_rules_accept_the_preferred_pseudo_channel(client: AsyncClient, world: World):
    rule = {"name": "Teste", "event_type": "ticket.created", "audience": ["requester"], "channels": ["in_app", "preferred"]}
    created = await client.post(f"{BASE}/admin/rules", json=rule, headers=headers_for(world.admin))
    assert created.status_code == 201
    options = (await client.get(f"{BASE}/admin/rules", headers=headers_for(world.admin))).json()["options"]
    assert "preferred" in options["channels"] and "telegram" in options["channels"]


async def test_bot_token_never_reaches_the_logs(db_session: AsyncSession, world: World, tg: FakeTelegram, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    adapter = TelegramAdapter(AdapterContext(session_factory=SessionFactory))
    await adapter.send(Recipient(address="42"), Message(title="t", body_text="b"))
    await adapter.health()
    assert "1:TOKEN" not in caplog.text
    assert logging.getLogger("httpx").level >= logging.WARNING
