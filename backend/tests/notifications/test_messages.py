"""Central de Mensagens (ADR-025 M3): formatação, variáveis, alcance por setor, prévia, envio idempotente, tetos,
teste, histórico, cancelamento e modelos."""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.notifications import messages as svc
from app.notifications.channel_store import save_channel
from app.notifications.dispatcher import Dispatcher
from app.notifications.models import Delivery, Notification, OutboundMessage, UserChannelAddress
from tests.factories import headers_for, make_employee, make_org, make_user

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/notifications/messages"
SEND = "notifications.messages.send"


@pytest.fixture
async def world(db_session: AsyncSession) -> SimpleNamespace:
    org = await make_org(db_session)
    other_org = await make_org(db_session)
    sender = await make_user(db_session, await make_employee(db_session, org))
    colleague = await make_user(db_session, await make_employee(db_session, org))
    linked = await make_user(db_session, await make_employee(db_session, org))
    stranger = await make_user(db_session, await make_employee(db_session, other_org))
    manager = await make_user(db_session, is_admin=True)
    db_session.add(UserChannelAddress(user_id=linked.id, channel="telegram", address="777", verified_at=datetime.now(timezone.utc)))
    db_session.add(UserChannelAddress(user_id=sender.id, channel="telegram", address="111", verified_at=None))  # não verificado
    await save_channel(db_session, "telegram", True, {"bot_username": "bot", "app_base_url": "http://sys"}, {"bot_token": "t"})
    await save_channel(db_session, "email", True, {}, {})
    await db_session.commit()
    return SimpleNamespace(sender=sender, colleague=colleague, linked=linked, stranger=stranger, manager=manager)


def as_sender(world, *extra: str) -> dict:
    return headers_for(world.sender, SEND, *extra)


def draft(channel="in_app", recipients=(), **overrides) -> dict:
    return {"channel": channel, "subject": "Aviso", "body": "Olá {{nome}}, **manutenção** hoje.",
            "recipient_ids": [str(r.id) for r in recipients], **overrides}


async def _send(client, world, headers=None, key=None, **kwargs):
    return await client.post(
        BASE, json=draft(**kwargs), headers={**(headers or as_sender(world)), "Idempotency-Key": key or uuid.uuid4().hex}
    )


# --- Formatação e variáveis -----------------------------------------------------------------------


async def test_neutral_markup_becomes_each_channel_format_and_html_is_escaped():
    body = "**Atenção** <script>x</script>\n- item 1\n- item 2\nVeja https://exemplo.com/a?b=1&c=2"
    assert svc.to_text(body, "whatsapp").startswith("*Atenção* <script>")
    assert svc.to_text(body, "slack").startswith("*Atenção*")
    assert svc.to_text(body, "plain").startswith("Atenção <script>")
    html = svc.to_html(body)
    assert "<strong>Atenção</strong>" in html and "&lt;script&gt;" in html and "<script>" not in html
    assert "<ul><li>item 1</li><li>item 2</li></ul>" in html
    assert '<a href="https://exemplo.com/a?b=1&amp;c=2">' in html


async def test_placeholders_are_filled_case_insensitively_and_unknown_ones_stay():
    assert svc.placeholders("Oi {{ Nome }}", "{{setor}} {{nome}}") == {"nome", "setor"}
    assert svc.fill("Oi {{ NOME }}, {{x}}", {"nome": "Ana"}) == "Oi Ana, {{x}}"


# --- Permissão e alcance --------------------------------------------------------------------------


async def test_routes_need_a_message_permission(client: AsyncClient, world):
    assert (await client.get(BASE, headers=headers_for(world.colleague))).status_code == 403
    assert (await client.get(f"{BASE}/recipients", headers=headers_for(world.colleague, "notifications.messages.read"))).status_code == 403
    assert (await client.get(BASE, headers=as_sender(world))).status_code == 200


async def test_sender_reaches_only_the_own_sector_and_manager_reaches_everyone(client: AsyncClient, world):
    mine = (await client.get(f"{BASE}/recipients", headers=as_sender(world))).json()
    emails = {r["email"] for r in mine["items"]}
    assert mine["reaches_everyone"] is False
    assert {world.sender.email, world.colleague.email, world.linked.email} <= emails and world.stranger.email not in emails
    linked = next(r for r in mine["items"] if r["email"] == world.linked.email)
    assert linked["channels"] == ["email", "in_app", "telegram"] and all(set(i) == {"user_id", "name", "email", "channels"} for i in mine["items"])  # canais sim, endereços não
    sender = next(r for r in mine["items"] if r["email"] == world.sender.email)
    assert "telegram" not in sender["channels"]  # vínculo não verificado não conta

    everyone = (await client.get(f"{BASE}/recipients", headers=headers_for(world.manager, "notifications.manage"))).json()
    assert everyone["reaches_everyone"] is True and world.stranger.email in {r["email"] for r in everyone["items"]}
    found = (await client.get(f"{BASE}/recipients", params={"q": world.linked.email}, headers=as_sender(world))).json()["items"]
    assert [r["email"] for r in found] == [world.linked.email]


async def test_preview_explains_who_is_left_out_and_shows_the_channel_text(client: AsyncClient, db_session: AsyncSession, world):
    world.colleague.is_active = False
    await db_session.commit()
    body = draft("telegram", [world.linked, world.sender, world.stranger, world.colleague])
    body["recipient_ids"].append(str(uuid.uuid4()))
    resp = await client.post(f"{BASE}/preview", json=body, headers=as_sender(world))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    outcomes = {r["email"] or "?": r["outcome"] for r in data["recipients"]}
    assert outcomes == {
        world.linked.email: "queued", world.sender.email: "no_address", world.stranger.email: "out_of_scope",
        world.colleague.email: "inactive", "?": "unknown",
    }
    assert data["queued"] == 1 and data["skipped"] == 4
    linked = next(r for r in data["recipients"] if r["outcome"] == "queued")
    assert linked["rendered"]["text"].startswith("Aviso\n\nOlá ")  # o render_text do próprio adapter do Telegram
    assert "manutenção hoje" in linked["rendered"]["text"] and "**" not in linked["rendered"]["text"]
    assert data["capabilities"]["formatting"] == "plain"
    assert await db_session.scalar(select(func.count()).select_from(OutboundMessage)) == 0  # prévia não grava


async def test_email_preview_is_the_html_the_adapter_sends(client: AsyncClient, world):
    data = (await client.post(f"{BASE}/preview", json=draft("email", [world.colleague]), headers=as_sender(world))).json()
    rendered = data["recipients"][0]["rendered"]
    assert rendered["subject"] == "Aviso" and "<strong>manutenção</strong>" in rendered["html"]
    assert "{{link}}" not in rendered["html"]  # sem botão "Abrir no sistema" numa mensagem manual


async def test_draft_validation(client: AsyncClient, db_session: AsyncSession, world):
    h = as_sender(world)
    missing = await client.post(f"{BASE}/preview", json=draft(body="Oi {{setor}}"), headers=h)
    assert missing.status_code == 422 and "setor" in missing.text
    filled = await client.post(f"{BASE}/preview", json=draft(body="Oi {{setor}}", variables={"setor": "TI"}), headers=h)
    assert filled.status_code == 200
    assert (await client.post(f"{BASE}/preview", json=draft("slack"), headers=h)).status_code == 400  # canal desligado
    assert (await client.post(f"{BASE}/preview", json=draft("pombo"), headers=h)).status_code == 422
    assert (await client.post(f"{BASE}/preview", json=draft(body="   "), headers=h)).status_code == 422
    too_long = await client.post(f"{BASE}/preview", json=draft("telegram", body="x" * 3999), headers=h)
    assert too_long.status_code == 422 and "limite" in too_long.text


# --- Envio ----------------------------------------------------------------------------------------


async def test_send_queues_one_delivery_per_reachable_recipient_and_is_idempotent(client: AsyncClient, db_session: AsyncSession, world):
    key = uuid.uuid4().hex
    first = await _send(client, world, key=key, channel="telegram", recipients=[world.linked, world.sender])
    assert first.status_code == 201, first.text
    data = first.json()
    assert data["queued_count"] == 1 and data["skipped_count"] == 1 and data["kind"] == "manual"

    again = await _send(client, world, key=key, channel="telegram", recipients=[world.linked, world.sender])
    assert again.status_code == 200 and again.json()["id"] == data["id"]
    deliveries = list((await db_session.execute(select(Delivery))).scalars())
    assert len(deliveries) == 1
    [delivery] = deliveries
    assert delivery.address == "777" and str(delivery.message_id) == data["id"] and delivery.status == "PENDING"
    assert delivery.message["body_text"].startswith("Olá ") and "**" not in delivery.message["body_text"]
    audit = (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "notifications.message_sent"))).scalar_one()
    assert audit.data["queued"] == 1

    no_key = await client.post(BASE, json=draft(recipients=[world.colleague]), headers=as_sender(world))
    assert no_key.status_code == 422
    nobody = await _send(client, world, channel="telegram", recipients=[world.sender])
    assert nobody.status_code == 400 and "Nenhum destinatário" in nobody.text


async def test_send_respects_the_caps(client: AsyncClient, db_session: AsyncSession, world, monkeypatch):
    monkeypatch.setattr(svc, "get_settings", lambda: SimpleNamespace(MESSAGES_MAX_RECIPIENTS=2, MESSAGES_MAX_PER_HOUR=2))
    too_many = await _send(client, world, recipients=[world.sender, world.colleague, world.linked])
    assert too_many.status_code == 400 and "No máximo 2" in too_many.text
    assert (await _send(client, world, recipients=[world.colleague])).status_code == 201
    assert (await _send(client, world, recipients=[world.colleague])).status_code == 201
    capped = await _send(client, world, recipients=[world.colleague])
    assert capped.status_code == 400 and "por hora" in capped.text
    # uma hora depois, volta a valer
    await db_session.execute(update(OutboundMessage).values(created_at=datetime.now(timezone.utc) - timedelta(hours=2)))
    await db_session.commit()
    assert (await _send(client, world, recipients=[world.colleague])).status_code == 201


async def test_worker_delivers_a_message_like_any_other(client: AsyncClient, db_session: AsyncSession, world):
    resp = await _send(client, world, recipients=[world.colleague])
    await Dispatcher(async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)).run_once()
    note = (await db_session.execute(select(Notification).where(Notification.user_id == world.colleague.id))).scalar_one()
    assert note.title == "Aviso" and note.message.startswith(f"Olá {(await _name(db_session, world.colleague))}")
    admin = headers_for(world.manager, "notifications.manage")
    items = (await client.get("/api/v1/notifications/admin/deliveries?origin=message", headers=admin)).json()["items"]
    assert len(items) == 1 and items[0]["origin"] == "message" and items[0]["status"] == "SENT"
    detail = (await client.get(f"{BASE}/{resp.json()['id']}", headers=as_sender(world))).json()
    assert detail["deliveries"] == {"SENT": 1} and detail["recipients"][0]["delivery"]["status"] == "SENT"


async def _name(db: AsyncSession, user) -> str:
    from app.organization.models import Employee

    return (await db.execute(select(Employee.name).where(Employee.id == user.employee_id))).scalar_one()


async def test_test_send_goes_only_to_the_tester(client: AsyncClient, db_session: AsyncSession, world, monkeypatch):
    ok = await client.post(f"{BASE}/test", json=draft(recipients=[world.stranger]), headers=as_sender(world))
    assert ok.status_code == 201 and ok.json()["kind"] == "test"
    [delivery] = (await db_session.execute(select(Delivery))).scalars()
    assert delivery.recipient_user_id == world.sender.id
    unlinked = await client.post(f"{BASE}/test", json=draft("telegram"), headers=as_sender(world))
    assert unlinked.status_code == 400 and "Vincule" in unlinked.text

    monkeypatch.setattr(svc, "TEST_MAX_PER_HOUR", 1)
    capped = await client.post(f"{BASE}/test", json=draft(), headers=as_sender(world))
    assert capped.status_code == 400 and "testes por hora" in capped.text
    assert (await _send(client, world, recipients=[world.colleague])).status_code == 201  # teste não gasta o teto de envios


# --- Histórico e cancelamento ---------------------------------------------------------------------


async def test_history_shows_own_sends_unless_allowed_to_read_all(client: AsyncClient, db_session: AsyncSession, world):
    mine = (await _send(client, world, recipients=[world.colleague])).json()
    theirs = (await _send(client, world, headers=headers_for(world.colleague, SEND), recipients=[world.sender])).json()

    listed = (await client.get(BASE, headers=as_sender(world))).json()
    assert [m["id"] for m in listed["items"]] == [mine["id"]]
    assert (await client.get(f"{BASE}/{theirs['id']}", headers=as_sender(world))).status_code == 404
    reader = (await client.get(BASE, headers=as_sender(world, "notifications.messages.read"))).json()
    assert {m["id"] for m in reader["items"]} == {mine["id"], theirs["id"]}
    assert (await client.get(f"{BASE}?kind=test", headers=as_sender(world, "notifications.messages.read"))).json()["total"] == 0


async def test_cancel_stops_only_what_has_not_left(client: AsyncClient, db_session: AsyncSession, world):
    sent = (await _send(client, world, recipients=[world.colleague, world.linked])).json()
    first = (await db_session.execute(select(Delivery).where(Delivery.recipient_user_id == world.colleague.id))).scalar_one()
    first.status = "SENT"
    await db_session.commit()

    other = await client.post(f"{BASE}/{sent['id']}/cancel", headers=headers_for(world.colleague, SEND, "notifications.messages.read"))
    assert other.status_code == 403  # vê, mas não é o autor nem administra

    resp = await client.post(f"{BASE}/{sent['id']}/cancel", headers=as_sender(world))
    assert resp.status_code == 200 and resp.json()["cancelled"] == 1 and resp.json()["status"] == "CANCELLED"
    statuses = {d.recipient_user_id: d.status for d in (await db_session.execute(select(Delivery))).scalars()}
    assert statuses == {world.colleague.id: "SENT", world.linked.id: "CANCELLED"}
    assert (await client.post(f"{BASE}/{sent['id']}/cancel", headers=as_sender(world))).status_code == 400
    assert await db_session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.event_type == "notifications.message_cancelled")
    ) == 1


# --- Modelos --------------------------------------------------------------------------------------


async def test_templates_are_managed_by_admins_and_used_by_senders(client: AsyncClient, db_session: AsyncSession, world):
    admin = headers_for(world.manager, "notifications.manage")
    template = {"code": "manutencao", "name": "Manutenção", "channels": ["email"], "subject": "Manutenção {{data}}",
                "body": "Olá {{nome}}, parada às {{hora_parada}}."}
    assert (await client.post(f"{BASE}/templates", json=template, headers=as_sender(world))).status_code == 403
    created = await client.post(f"{BASE}/templates", json=template, headers=admin)
    assert created.status_code == 201 and created.json()["variables"] == ["data", "hora_parada", "nome"]
    assert (await client.post(f"{BASE}/templates", json=template, headers=admin)).status_code == 400  # código repetido
    assert (await client.post(f"{BASE}/templates", json={**template, "code": "Com Espaço"}, headers=admin)).status_code == 422
    template_id = created.json()["id"]

    wrong_channel = await client.post(f"{BASE}/preview", json=draft("in_app", template_id=template_id), headers=as_sender(world))
    assert wrong_channel.status_code == 400 and "não é para este canal" in wrong_channel.text
    sent = await _send(client, world, channel="email", template_id=template_id, recipients=[world.colleague],
                       subject=template["subject"], body=template["body"], variables={"hora_parada": "18h"})
    assert sent.status_code == 201
    stored = (await db_session.execute(select(OutboundMessage))).scalar_one()
    assert str(stored.template_id) == template_id

    await client.put(f"{BASE}/templates/{template_id}", json={**template, "is_active": False}, headers=admin)
    assert (await client.get(f"{BASE}/templates", headers=as_sender(world))).json()["items"] == []
    assert len((await client.get(f"{BASE}/templates", headers=admin)).json()["items"]) == 1
    inactive = await client.post(f"{BASE}/preview", json=draft("email", template_id=template_id), headers=as_sender(world))
    assert inactive.status_code == 400

    assert (await client.delete(f"{BASE}/templates/{template_id}", headers=admin)).status_code == 204
    await db_session.refresh(stored)
    assert stored.template_id is None and stored.body == template["body"]  # o envio guarda o texto usado
