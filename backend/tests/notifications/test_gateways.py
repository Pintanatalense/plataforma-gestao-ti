"""Gateways (ADR-025 M2): capacidades declaradas, limite ajustável só para baixo e checagem periódica de todos os
canais habilitados."""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.notifications.channel_store import load_channel, save_channel
from app.notifications.channels import ADAPTERS
from app.notifications.channels.base import ChannelHealth
from app.notifications.channels.telegram import TelegramAdapter
from app.notifications.dispatcher import Dispatcher, effective_rate
from app.notifications.jobs import job_whatsapp_health
from app.notifications.models import AutomationMark, Delivery, DomainEvent, WorkerHeartbeat
from tests.factories import headers_for, make_user

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/notifications/admin/gateways"


@pytest.fixture
def factory(db_session: AsyncSession) -> async_sessionmaker:
    return async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)


async def _admin_headers(db: AsyncSession) -> dict:
    return headers_for(await make_user(db, is_admin=True), "notifications.manage")


# --- Capacidades ----------------------------------------------------------------------------------


async def test_capabilities_describe_only_what_our_integration_does():
    caps = {name: adapter.capabilities for name, adapter in ADAPTERS.items()}
    assert caps["whatsapp"].delivery_receipts and caps["whatsapp"].read_receipts
    assert caps["whatsapp"].formatting == "whatsapp" and caps["email"].formatting == "html"
    assert caps["slack"].formatting == "slack" and caps["telegram"].formatting == "plain"
    # nenhum canal envia anexo nem "digitando" ainda (M6); confirmação só o WhatsApp lê (M1)
    assert not any(c.attachments or c.typing for c in caps.values())
    assert [n for n, c in caps.items() if c.delivery_receipts] == ["whatsapp"]


async def test_effective_rate_never_goes_above_the_channel_ceiling():
    assert effective_rate(2.0, None) == 2.0
    assert effective_rate(2.0, 0.5) == 0.5
    assert effective_rate(2.0, 9.0) == 2.0
    assert effective_rate(None, None) is None and effective_rate(None, 3.0) == 3.0


# --- API ------------------------------------------------------------------------------------------


async def test_gateways_listing_shows_capabilities_limits_and_needs_permission(client: AsyncClient, db_session: AsyncSession):
    plain = await make_user(db_session)
    assert (await client.get(BASE, headers=headers_for(plain))).status_code == 403

    await save_channel(db_session, "whatsapp", True, {"provider": "evolution", "max_per_hour": 4}, {"webhook_secret": "s"})
    await db_session.commit()
    items = {g["channel"]: g for g in (await client.get(BASE, headers=await _admin_headers(db_session))).json()["items"]}
    assert set(items) == set(ADAPTERS)
    assert items["in_app"]["enabled"] is True and items["in_app"]["configured"] is True
    assert items["telegram"]["configured"] is False and items["telegram"]["enabled"] is False
    whatsapp = items["whatsapp"]
    assert whatsapp["provider"] == "evolution" and whatsapp["capabilities"]["read_receipts"] is True
    assert whatsapp["limits"]["max_per_hour_per_person"] == 4 and whatsapp["limits"]["send_interval_seconds"] == 4
    assert whatsapp["limits"]["effective_rate_per_second"] == ADAPTERS["whatsapp"].capabilities.rate_per_second
    assert "webhook_secret" not in str(items)  # segredos nunca saem por aqui


async def test_limit_can_only_go_down_survives_channel_edits_and_is_audited(client: AsyncClient, db_session: AsyncSession):
    h = await _admin_headers(db_session)
    url = f"{BASE}/telegram/limits"
    assert (await client.put(url, json={"rate_per_second": 1}, headers=h)).status_code == 400  # canal sem configuração
    await save_channel(db_session, "telegram", True, {"bot_username": "bot"}, {"bot_token": "t"})
    await db_session.commit()

    too_high = await client.put(url, json={"rate_per_second": 50}, headers=h)
    assert too_high.status_code == 400 and "reduzido" in too_high.text
    assert (await client.put(url, json={"rate_per_second": 0}, headers=h)).status_code == 422
    assert (await client.put(f"{BASE}/in_app/limits", json={"rate_per_second": 1}, headers=h)).status_code == 400
    assert (await client.put(f"{BASE}/pombo/limits", json={"rate_per_second": 1}, headers=h)).status_code == 404

    ok = await client.put(url, json={"rate_per_second": 0.5}, headers=h)
    assert ok.status_code == 200 and ok.json()["limits"]["effective_rate_per_second"] == 0.5

    # a aba do Telegram grava o config do zero: o limite continua
    stored = await load_channel(db_session, "telegram")
    await save_channel(db_session, "telegram", True, {"bot_username": "outro"}, dict(stored.secrets))
    await db_session.commit()
    after = await load_channel(db_session, "telegram")
    assert after.config["bot_username"] == "outro" and after.config["limits"] == {"rate_per_second": 0.5}
    assert after.secrets == {"bot_token": "t"}

    cleared = await client.put(url, json={"rate_per_second": None}, headers=h)
    assert cleared.json()["limits"]["rate_per_second"] is None
    assert cleared.json()["limits"]["effective_rate_per_second"] == ADAPTERS["telegram"].capabilities.rate_per_second
    events = [a.event_type for a in (await db_session.execute(select(AuditLog))).scalars()]
    assert events.count("notifications.gateway_limits_updated") == 2


async def test_dispatcher_applies_the_lowered_limit(db_session: AsyncSession, factory, monkeypatch: pytest.MonkeyPatch):
    await save_channel(db_session, "email", False, {"limits": {"rate_per_second": 0.25}}, {})
    event = DomainEvent(event_type="x.y", entity_type="x", payload={}, fanned_out_at=datetime.now(timezone.utc))
    db_session.add(event)
    await db_session.flush()
    db_session.add(Delivery(event_id=event.id, channel="email", address="a@b.c", message={"title": "t", "body_text": "b"},
                            idempotency_key=uuid.uuid4().hex))
    await db_session.commit()

    rates: list = []

    async def record(self, channel, rate):
        rates.append((channel, rate))

    monkeypatch.setattr(Dispatcher, "_throttle", record)
    assert await Dispatcher(factory).run_once() == 1
    assert rates == [("email", 0.25)]


# --- Checagem periódica ---------------------------------------------------------------------------


async def _degraded(db: AsyncSession) -> list[dict]:
    rows = await db.execute(select(DomainEvent).where(DomainEvent.event_type == "channel.degraded"))
    return [e.payload for e in rows.scalars()]


async def test_periodic_check_warns_once_per_outage_for_other_channels(db_session: AsyncSession, factory, monkeypatch):
    await save_channel(db_session, "telegram", True, {"bot_username": "bot"}, {"bot_token": "t"})
    await db_session.commit()
    state = {"ok": False}

    async def health(self):
        return ChannelHealth(ok=state["ok"], detail="401 token inválido" if not state["ok"] else "@bot")

    monkeypatch.setattr(TelegramAdapter, "health", health)

    await job_whatsapp_health(factory)  # WhatsApp nem configurado: os outros canais são checados mesmo assim
    assert await _degraded(db_session) == []  # primeira falha só marca (debounce)
    await job_whatsapp_health(factory)
    [payload] = await _degraded(db_session)
    assert payload["channel"] == "telegram" and "401 token inválido" in payload["error"]
    await job_whatsapp_health(factory)
    assert len(await _degraded(db_session)) == 1  # um aviso por queda

    state["ok"] = True
    await job_whatsapp_health(factory)
    keys = set((await db_session.execute(select(AutomationMark.key))).scalars())
    assert not any(k.startswith("telegram.down") for k in keys)  # rearmado


async def test_periodic_check_stays_quiet_when_the_circuit_already_warned(db_session: AsyncSession, factory, monkeypatch):
    await save_channel(db_session, "telegram", True, {}, {"bot_token": "t"})
    db_session.add(WorkerHeartbeat(name="notifier", beat_at=datetime.now(timezone.utc), info={"open_circuits": ["telegram"]}))
    await db_session.commit()

    async def health(self):
        return ChannelHealth(ok=False, detail="fora")

    monkeypatch.setattr(TelegramAdapter, "health", health)
    for _ in range(3):
        await job_whatsapp_health(factory)
    assert await _degraded(db_session) == []


async def test_periodic_check_ignores_disabled_channels_and_survives_an_adapter_error(db_session: AsyncSession, factory, monkeypatch):
    await save_channel(db_session, "telegram", True, {}, {"bot_token": "t"})
    await save_channel(db_session, "slack", False, {}, {"bot_token": "t"})
    await db_session.commit()

    async def boom(self):
        raise RuntimeError("rede caiu")

    monkeypatch.setattr(TelegramAdapter, "health", boom)
    await job_whatsapp_health(factory)
    await job_whatsapp_health(factory)
    assert [p["channel"] for p in await _degraded(db_session)] == ["telegram"]
