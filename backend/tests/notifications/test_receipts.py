"""Confirmações do provedor separadas de SENT (ADR-025 M1): regra de avanço, webhooks da Evolution e da Meta e os
filtros novos do painel de entregas."""
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.channel_store import save_channel
from app.notifications.channels import whatsapp_evolution as evo
from app.notifications.models import Delivery, DomainEvent
from app.notifications.receipts import Receipt, advances, apply_receipts
from app.notifications.whatsapp_webhook import extract_receipts
from tests.factories import headers_for, make_user

pytestmark = pytest.mark.asyncio

EVOLUTION_HOOK = "/api/v1/integrations/whatsapp/evolution/webhook"
META_HOOK = "/api/v1/integrations/whatsapp/webhook"
SECRET = "hook-secret-0123456789"
APP_SECRET = "meta-app-secret"
PHONE_ID = "1234567890"
ADMIN_BASE = "/api/v1/notifications/admin"


async def _delivery(db: AsyncSession, *, channel="whatsapp", provider_message_id=None, event_type="ticket.created",
                    rule=False, address="5585900001111", title="Olá", body="corpo", **fields) -> Delivery:
    event = DomainEvent(event_type=event_type, entity_type="ticket", payload={}, fanned_out_at=datetime.now(timezone.utc))
    db.add(event)
    await db.flush()
    if rule:
        from app.notifications.models import NotificationRule

        rule_row = NotificationRule(name="r", event_type=event_type, audience=["admins"], channels=[channel], template_code="generic")
        db.add(rule_row)
        await db.flush()
        fields["rule_id"] = rule_row.id
    delivery = Delivery(
        event_id=event.id, channel=channel, address=address, status="SENT", sent_at=datetime.now(timezone.utc),
        message={"title": title, "body_text": body}, provider_message_id=provider_message_id,
        idempotency_key=uuid.uuid4().hex + uuid.uuid4().hex, **fields,
    )
    db.add(delivery)
    await db.commit()
    return delivery


async def _status(db: AsyncSession, delivery: Delivery) -> str | None:
    await db.refresh(delivery)
    return delivery.provider_status


# --- Regra de avanço ------------------------------------------------------------------------------


async def test_status_only_moves_forward_and_failed_never_undoes_a_delivery():
    assert advances(None, "accepted") and advances("accepted", "delivered") and advances("delivered", "read")
    assert not advances("read", "delivered") and not advances("delivered", "accepted") and not advances("read", "read")
    assert advances(None, "failed") and advances("accepted", "failed")
    assert not advances("delivered", "failed") and not advances("read", "failed")
    assert advances("failed", "delivered")  # erro informado e depois entregue: vale o que chegou depois


async def test_apply_receipts_matches_channel_and_message_id_only(db_session: AsyncSession):
    whatsapp = await _delivery(db_session, provider_message_id="BAE5OUT1")
    other_channel = await _delivery(db_session, channel="telegram", provider_message_id="BAE5OUT1")
    changed = await apply_receipts(db_session, "whatsapp", [
        Receipt("BAE5OUT1", "delivered"), Receipt("DESCONHECIDO", "read"), Receipt("BAE5OUT1", "inventado"),
    ])
    await db_session.commit()
    assert changed == 1
    assert await _status(db_session, whatsapp) == "delivered" and whatsapp.provider_status_at is not None
    assert await _status(db_session, other_channel) is None
    assert whatsapp.status == "SENT"  # a fila não muda: SENT continua "aceito pelo gateway"

    await apply_receipts(db_session, "whatsapp", [Receipt("BAE5OUT1", "accepted"), Receipt("BAE5OUT1", "failed")])
    await db_session.commit()
    assert await _status(db_session, whatsapp) == "delivered"


# --- Evolution ------------------------------------------------------------------------------------


def _update(status: str, key_id: str = "BAE5OUT1", from_me: bool = True, instance: str = "gestao-ti") -> dict:
    return {
        "event": "messages.update", "instance": instance,
        "data": {"keyId": key_id, "remoteJid": "5585900001111@s.whatsapp.net", "fromMe": from_me, "status": status},
    }


async def test_evolution_receipts_parser_keeps_only_our_messages_in_this_instance():
    assert evo.parse_receipts(_update("DELIVERY_ACK"), "gestao-ti") == [Receipt("BAE5OUT1", "delivered")]
    assert evo.parse_receipts(_update("PLAYED"), "gestao-ti") == [Receipt("BAE5OUT1", "read")]
    assert evo.parse_receipts(_update("SERVER_ACK"), "gestao-ti") == [Receipt("BAE5OUT1", "accepted")]
    assert evo.parse_receipts(_update("ERROR"), "gestao-ti") == [Receipt("BAE5OUT1", "failed")]
    for ignored in (_update("READ", from_me=False), _update("READ", instance="outra"), _update("PENDING"),
                    _update("DELETED"), {**_update("READ"), "event": "messages.upsert"}, {"event": "messages.update"}):
        assert evo.parse_receipts(ignored, "gestao-ti") == [], ignored
    listed = {**_update("READ"), "data": [{"key": {"id": "A1", "fromMe": True}, "status": "READ"}]}
    assert evo.parse_receipts(listed, "gestao-ti") == [Receipt("A1", "read")]


async def test_evolution_webhook_records_delivered_then_read_and_requires_the_secret(client: AsyncClient, db_session: AsyncSession):
    await save_channel(db_session, "whatsapp", True, {"provider": "evolution", "instance_name": "gestao-ti"}, {"webhook_secret": SECRET})
    await db_session.commit()
    delivery = await _delivery(db_session, provider_message_id="BAE5OUT1")

    assert (await client.post(EVOLUTION_HOOK, json=_update("READ"))).status_code == 401
    assert await _status(db_session, delivery) is None

    ok = await client.post(EVOLUTION_HOOK, json=_update("DELIVERY_ACK"), headers={"X-Webhook-Secret": SECRET})
    assert ok.status_code == 200
    assert await _status(db_session, delivery) == "delivered"
    await client.post(EVOLUTION_HOOK, json=_update("READ"), headers={"X-Webhook-Secret": SECRET})
    assert await _status(db_session, delivery) == "read"


# --- Meta -----------------------------------------------------------------------------------------


def _statuses(*items: tuple[str, str], phone_id: str = PHONE_ID) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp", "metadata": {"phone_number_id": phone_id},
            "statuses": [{"id": wamid, "status": status, "timestamp": "1760000000", "recipient_id": "5585"} for wamid, status in items],
        }}]}],
    }


async def test_meta_receipts_parser_maps_statuses_and_filters_other_numbers():
    found = extract_receipts(_statuses(("wamid.1", "sent"), ("wamid.2", "read"), ("wamid.3", "deleted")), PHONE_ID)
    assert [(r.provider_message_id, r.status) for r in found] == [("wamid.1", "accepted"), ("wamid.2", "read")]
    assert found[0].at == datetime.fromtimestamp(1760000000, tz=timezone.utc)
    assert extract_receipts(_statuses(("wamid.1", "read"), phone_id="outro"), PHONE_ID) == []


async def test_meta_webhook_records_receipts_only_with_a_valid_signature(client: AsyncClient, db_session: AsyncSession):
    await save_channel(db_session, "whatsapp", True, {"phone_number_id": PHONE_ID}, {"app_secret": APP_SECRET, "access_token": "t"})
    await db_session.commit()
    delivery = await _delivery(db_session, provider_message_id="wamid.ABC")
    raw = json.dumps(_statuses(("wamid.ABC", "delivered"))).encode()

    bad = await client.post(META_HOOK, content=raw, headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=00"})
    assert bad.status_code == 401 and await _status(db_session, delivery) is None

    signature = "sha256=" + hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    ok = await client.post(META_HOOK, content=raw, headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature})
    assert ok.status_code == 200 and await _status(db_session, delivery) == "delivered"


# --- Painel ---------------------------------------------------------------------------------------


async def test_deliveries_listing_filters_by_origin_confirmation_address_and_text(client: AsyncClient, db_session: AsyncSession):
    admin = await make_user(db_session, is_admin=True)
    h = headers_for(admin, "notifications.manage")
    by_rule = await _delivery(db_session, rule=True, title="Novo chamado #1", provider_status="read", address="5585911112222")
    direct = await _delivery(db_session, event_type="ticket.direct_message", body="Abra o AnyDesk", address="5585933334444")
    reply = await _delivery(db_session, event_type="conversation.reply", body="Menu do robô", address="chat-77")
    system = await _delivery(db_session, event_type="channel.test", body="Teste 100%_ok", channel="email", address="a@b.c")

    async def ids(**params) -> set[str]:
        body = (await client.get(f"{ADMIN_BASE}/deliveries", params=params, headers=h)).json()
        return {item["id"] for item in body["items"]}

    assert await ids(origin="rule") == {str(by_rule.id)}
    assert await ids(origin="direct") == {str(direct.id)}
    assert await ids(origin="conversation") == {str(reply.id)}
    assert await ids(origin="system") == {str(system.id)}
    assert await ids(provider_status="read") == {str(by_rule.id)}
    assert await ids(provider_status="none") == {str(direct.id), str(reply.id), str(system.id)}
    assert await ids(address="3333") == {str(direct.id)}
    assert await ids(q="anydesk") == {str(direct.id)}
    assert await ids(q="chamado #1") == {str(by_rule.id)}
    assert await ids(q="100%_") == {str(system.id)}  # % e _ digitados são texto, não curinga
    assert await ids(q="%") == {str(system.id)}
    assert await ids(q="   ") == {str(d.id) for d in (by_rule, direct, reply, system)}

    item = next(i for i in (await client.get(f"{ADMIN_BASE}/deliveries", params={"origin": "rule"}, headers=h)).json()["items"])
    assert item["origin"] == "rule" and item["provider_status"] == "read"
    assert (await client.get(f"{ADMIN_BASE}/deliveries", params={"origin": "x"}, headers=h)).status_code == 422
    assert (await client.get(f"{ADMIN_BASE}/deliveries", params={"provider_status": "x"}, headers=h)).status_code == 422
