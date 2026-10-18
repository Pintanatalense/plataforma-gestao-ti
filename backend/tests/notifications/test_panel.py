"""Painel de notificações (ADR-013, Fase B): API do usuário, administração e preferências."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.core.security import create_access_token
from app.notifications.fanout import plan_event
from app.notifications.models import (
    Delivery,
    DeliveryAttempt,
    DomainEvent,
    Notification,
    NotificationRule,
    ScheduledJob,
    UserNotificationPref,
    WorkerHeartbeat,
)
from app.notifications.prefs import Prefs, allows, category_of, quiet_until
from app.notifications.rules_seed import seed_notification_rules
from tests.factories import headers_for, make_employee, make_org, make_user

pytestmark = pytest.mark.asyncio

ADMIN_BASE = "/api/v1/notifications/admin"


@pytest.fixture
async def users(db_session: AsyncSession):
    org = await make_org(db_session)
    manager = await make_user(db_session, await make_employee(db_session, org))
    plain = await make_user(db_session, await make_employee(db_session, org))
    return org, manager, plain


def manage(user):
    return headers_for(user, "notifications.manage")


async def _delivery(db: AsyncSession, user=None, **overrides) -> Delivery:
    event = DomainEvent(event_type=overrides.pop("event_type", "ticket.created"), entity_type="ticket", payload={"a": 1},
                        fanned_out_at=datetime.now(timezone.utc))
    db.add(event)
    await db.flush()
    fields = {
        "event_id": event.id,
        "recipient_user_id": user.id if user else None,
        "channel": "email",
        "address": user.email if user else "x@y.z",
        "message": {"title": "Olá", "body_text": "b"},
        "idempotency_key": uuid.uuid4().hex + uuid.uuid4().hex,
        **overrides,
    }
    delivery = Delivery(**fields)
    db.add(delivery)
    await db.commit()
    return delivery


# --- Permissão ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/deliveries"),
        ("get", "/rules"),
        ("get", "/channels"),
        ("get", "/jobs"),
        ("post", "/rules/simulate"),
    ],
)
async def test_admin_endpoints_require_notifications_manage(client: AsyncClient, users, method, path):
    _, manager, plain = users
    kwargs = {"json": {"event_type": "ticket.created"}} if method == "post" else {}
    assert (await getattr(client, method)(ADMIN_BASE + path, headers=headers_for(plain), **kwargs)).status_code == 403
    assert (await getattr(client, method)(ADMIN_BASE + path, headers=manage(manager), **kwargs)).status_code == 200
    assert (await getattr(client, method)(ADMIN_BASE + path, **kwargs)).status_code in (401, 403)


async def test_smtp_config_accepts_notifications_manage(client: AsyncClient, users):
    _, manager, _ = users
    assert (await client.get("/api/v1/notifications/email/config", headers=manage(manager))).status_code == 200


# --- Entregas -------------------------------------------------------------------------------------


async def test_deliveries_listing_filters_and_detail(client: AsyncClient, db_session: AsyncSession, users):
    _, manager, plain = users
    sent = await _delivery(db_session, plain, status="SENT", sent_at=datetime.now(timezone.utc))
    dead = await _delivery(db_session, manager, status="DEAD", channel="in_app", last_error="boom", attempts=2)
    db_session.add(DeliveryAttempt(delivery_id=dead.id, attempt_no=1, started_at=datetime.now(timezone.utc),
                                   finished_at=datetime.now(timezone.utc), outcome="retryable", error="boom"))
    await db_session.commit()
    h = manage(manager)

    everything = (await client.get(f"{ADMIN_BASE}/deliveries", headers=h)).json()
    assert everything["total"] == 2 and {i["status"] for i in everything["items"]} == {"SENT", "DEAD"}
    only_dead = (await client.get(f"{ADMIN_BASE}/deliveries?status=DEAD", headers=h)).json()
    assert [i["id"] for i in only_dead["items"]] == [str(dead.id)]
    by_channel = (await client.get(f"{ADMIN_BASE}/deliveries?channel=email", headers=h)).json()
    assert [i["id"] for i in by_channel["items"]] == [str(sent.id)]
    by_user = (await client.get(f"{ADMIN_BASE}/deliveries?recipient={plain.email[:8]}", headers=h)).json()
    assert by_user["total"] == 1 and by_user["items"][0]["recipient_email"] == plain.email
    assert (await client.get(f"{ADMIN_BASE}/deliveries?limit=1", headers=h)).json()["items"].__len__() == 1

    detail = (await client.get(f"{ADMIN_BASE}/deliveries/{dead.id}", headers=h)).json()
    assert detail["last_error"] == "boom" and detail["attempt_log"][0]["outcome"] == "retryable"
    assert detail["event_payload"] == {"a": 1}
    assert (await client.get(f"{ADMIN_BASE}/deliveries/{uuid.uuid4()}", headers=h)).status_code == 404


async def test_resend_creates_new_delivery_for_dead_only_and_is_audited(client: AsyncClient, db_session: AsyncSession, users):
    _, manager, plain = users
    dead = await _delivery(db_session, plain, status="DEAD", attempts=5)
    sent = await _delivery(db_session, plain, status="SENT")
    h = manage(manager)

    refused = await client.post(f"{ADMIN_BASE}/deliveries/{sent.id}/resend", headers=h)
    assert refused.status_code >= 400

    ok = await client.post(f"{ADMIN_BASE}/deliveries/{dead.id}/resend", headers=h)
    assert ok.status_code == 201
    new = (await db_session.execute(select(Delivery).where(Delivery.id == uuid.UUID(ok.json()["id"])))).scalar_one()
    assert (new.status, new.attempts, new.event_id, new.address) == ("PENDING", 0, dead.event_id, dead.address)
    assert new.idempotency_key != dead.idempotency_key
    await db_session.refresh(dead)
    assert dead.status == "DEAD"  # histórico preservado
    logs = (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "notifications.delivery_resent"))).scalars().all()
    assert len(logs) == 1 and logs[0].data["from_delivery"] == str(dead.id) and logs[0].user_id == manager.id


async def test_cancel_only_pending(client: AsyncClient, db_session: AsyncSession, users):
    _, manager, plain = users
    pending = await _delivery(db_session, plain, status="PENDING")
    sent = await _delivery(db_session, plain, status="SENT")
    h = manage(manager)
    assert (await client.post(f"{ADMIN_BASE}/deliveries/{pending.id}/cancel", headers=h)).json()["status"] == "CANCELLED"
    assert (await client.post(f"{ADMIN_BASE}/deliveries/{sent.id}/cancel", headers=h)).status_code >= 400
    assert (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "notifications.delivery_cancelled"))).scalars().all()


# --- Regras ---------------------------------------------------------------------------------------


RULE = {
    "name": "Estoque baixo",
    "event_type": "stock.below_minimum",
    "audience": ["role:Gestão", "admins"],
    "channels": ["in_app", "email"],
    "template_code": "generic",
    "condition": {"min_priority": "normal"},
}


async def test_rule_crud_validation_and_system_rules(client: AsyncClient, db_session: AsyncSession, users):
    _, manager, _ = users
    h = manage(manager)
    await seed_notification_rules(db_session)
    await db_session.commit()

    created = await client.post(f"{ADMIN_BASE}/rules", json=RULE, headers=h)
    assert created.status_code == 201 and created.json()["is_system"] is False
    rule_id = created.json()["id"]

    updated = await client.put(f"{ADMIN_BASE}/rules/{rule_id}", json={**RULE, "enabled": False}, headers=h)
    assert updated.json()["enabled"] is False

    listing = (await client.get(f"{ADMIN_BASE}/rules", headers=h)).json()
    assert any(r["id"] == rule_id for r in listing["items"])
    assert {"in_app", "email"} <= set(listing["options"]["channels"])

    for bad in (
        {**RULE, "channels": ["pombo_correio"]},
        {**RULE, "audience": ["todo_mundo"]},
        {**RULE, "audience": ["user:não-é-uuid"]},
        {**RULE, "event_type": "Estoque Baixo"},
        {**RULE, "template_code": "inexistente"},
        {**RULE, "condition": {"sql": "1=1"}},
        {**RULE, "channels": []},
    ):
        assert (await client.post(f"{ADMIN_BASE}/rules", json=bad, headers=h)).status_code == 422, bad

    system_rule = next(r for r in listing["items"] if r["is_system"])
    assert (await client.delete(f"{ADMIN_BASE}/rules/{system_rule['id']}", headers=h)).status_code >= 400
    assert (await client.put(f"{ADMIN_BASE}/rules/{system_rule['id']}", json={**RULE, "enabled": False}, headers=h)).status_code == 200
    assert (await client.delete(f"{ADMIN_BASE}/rules/{rule_id}", headers=h)).status_code == 204
    kinds = {l.event_type for l in (await db_session.execute(select(AuditLog))).scalars()}
    assert {"notifications.rule_created", "notifications.rule_updated", "notifications.rule_deleted"} <= kinds


async def test_simulation_shows_recipients_without_persisting(client: AsyncClient, db_session: AsyncSession, users):
    _, manager, plain = users
    await seed_notification_rules(db_session)
    await db_session.commit()
    body = {"event_type": "backup.failed", "priority": "critical", "payload": {"error": "disco cheio"}}
    admin = await make_user(db_session, is_admin=True)

    result = (await client.post(f"{ADMIN_BASE}/rules/simulate", json=body, headers=manage(manager))).json()
    recipients = {(d["recipient_email"], d["channel"]) for d in result["deliveries"]}
    assert (admin.email, "in_app") in recipients
    assert plain.email not in {r[0] for r in recipients}
    assert all("backup" in d["title"].lower() for d in result["deliveries"])
    assert (await db_session.execute(select(Delivery))).scalars().all() == []
    assert (await db_session.execute(select(DomainEvent))).scalars().all() == []


# --- Saúde dos canais e agenda --------------------------------------------------------------------


async def test_channel_health_reports_counts_worker_and_circuit(client: AsyncClient, db_session: AsyncSession, users):
    _, manager, plain = users
    await _delivery(db_session, plain, status="PENDING", channel="email")
    dead = await _delivery(db_session, plain, status="DEAD", channel="email", last_error="smtp down")
    db_session.add(DeliveryAttempt(delivery_id=dead.id, attempt_no=1, started_at=datetime.now(timezone.utc),
                                   finished_at=datetime.now(timezone.utc), outcome="retryable", error="smtp down"))
    db_session.add(DomainEvent(event_type="x.y", entity_type="x", payload={}))
    db_session.add(WorkerHeartbeat(name="notifier", beat_at=datetime.now(timezone.utc),
                                   info={"open_circuits": ["email"], "deliveries": 3}))
    await db_session.commit()

    data = (await client.get(f"{ADMIN_BASE}/channels", headers=manage(manager))).json()
    email = next(c for c in data["channels"] if c["channel"] == "email")
    in_app = next(c for c in data["channels"] if c["channel"] == "in_app")
    assert data["worker"]["status"] == "healthy" and data["events_waiting"]["count"] == 1
    assert (email["pending"], email["dead"], email["circuit_open"], email["enabled"]) == (1, 1, True, False)
    assert email["last_error"] == "smtp down" and email["failures_last_hour"] == 1
    assert in_app["enabled"] is True and in_app["circuit_open"] is False


async def test_worker_status_stale_and_stopped(client: AsyncClient, db_session: AsyncSession, users):
    _, manager, _ = users
    h = manage(manager)
    assert (await client.get(f"{ADMIN_BASE}/channels", headers=h)).json()["worker"]["status"] == "stopped"
    db_session.add(WorkerHeartbeat(name="notifier", beat_at=datetime.now(timezone.utc) - timedelta(minutes=5), info={}))
    await db_session.commit()
    assert (await client.get(f"{ADMIN_BASE}/channels", headers=h)).json()["worker"]["status"] == "stale"


async def test_channel_test_uses_adapter_health(client: AsyncClient, users):
    _, manager, _ = users
    h = manage(manager)
    ok = (await client.post(f"{ADMIN_BASE}/channels/in_app/test", headers=h)).json()
    assert ok["ok"] is True
    assert (await client.post(f"{ADMIN_BASE}/channels/pombo/test", headers=h)).status_code == 404


async def test_jobs_listing_toggle_and_run_now(client: AsyncClient, db_session: AsyncSession, users):
    _, manager, _ = users
    h = manage(manager)
    future = datetime.now(timezone.utc) + timedelta(hours=5)
    db_session.add(ScheduledJob(name="backup.daily", schedule="daily:02:00", next_run_at=future))
    await db_session.commit()

    assert (await client.get(f"{ADMIN_BASE}/jobs", headers=h)).json()["items"][0]["name"] == "backup.daily"
    assert (await client.patch(f"{ADMIN_BASE}/jobs/backup.daily", json={"enabled": False}, headers=h)).json()["enabled"] is False
    assert (await client.post(f"{ADMIN_BASE}/jobs/backup.daily/run", headers=h)).status_code >= 400  # desativado
    await client.patch(f"{ADMIN_BASE}/jobs/backup.daily", json={"enabled": True}, headers=h)
    assert (await client.post(f"{ADMIN_BASE}/jobs/backup.daily/run", headers=h)).status_code == 200
    job = (await db_session.execute(select(ScheduledJob))).scalar_one()
    await db_session.refresh(job)
    assert job.next_run_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)
    assert (await client.patch(f"{ADMIN_BASE}/jobs/nao.existe", json={"enabled": True}, headers=h)).status_code == 404


# --- Caixa de entrada -----------------------------------------------------------------------------


async def test_inbox_filters_unread_count_and_isolation(client: AsyncClient, db_session: AsyncSession, users):
    _, manager, plain = users
    now = datetime.now(timezone.utc)
    db_session.add_all([
        Notification(user_id=plain.id, title="a", message="m", type="info", is_read=False),
        Notification(user_id=plain.id, title="b", message="m", type="error", is_read=True),
        Notification(user_id=plain.id, title="c", message="m", type="info", is_read=False),
        Notification(user_id=manager.id, title="alheia", message="m", type="info"),
    ])
    await db_session.commit()
    h = headers_for(plain)

    assert (await client.get("/api/v1/notifications/unread-count", headers=h)).json() == {"count": 2}
    assert len((await client.get("/api/v1/notifications", headers=h)).json()) == 3
    unread = (await client.get("/api/v1/notifications?is_read=false", headers=h)).json()
    assert {n["title"] for n in unread} == {"a", "c"}
    assert [n["title"] for n in (await client.get("/api/v1/notifications?type=error", headers=h)).json()] == ["b"]
    today = now.date().isoformat()
    assert len((await client.get(f"/api/v1/notifications?date_from={today}&date_to={today}", headers=h)).json()) == 3
    assert (await client.get("/api/v1/notifications?date_to=2000-01-01", headers=h)).json() == []


# --- Preferências ---------------------------------------------------------------------------------


async def test_prefs_default_roundtrip_and_validation(client: AsyncClient, db_session: AsyncSession, users):
    _, _, plain = users
    h = headers_for(plain)
    default = (await client.get("/api/v1/notifications/prefs", headers=h)).json()
    assert (default["quiet_enabled"], default["quiet_start"], default["quiet_end"], default["critical_bypass"]) == (
        True, "20:00", "07:00", True)
    assert default["timezone"] == "America/Fortaleza" and default["channels_disabled"] == []

    body = {"channels_disabled": ["email"], "categories_disabled": ["stock"], "quiet_enabled": False,
            "quiet_start": "22:30", "quiet_end": "06:15", "critical_bypass": False}
    assert (await client.put("/api/v1/notifications/prefs", json=body, headers=h)).status_code == 200
    saved = (await client.get("/api/v1/notifications/prefs", headers=h)).json()
    assert saved["channels_disabled"] == ["email"] and saved["quiet_start"] == "22:30" and saved["critical_bypass"] is False

    for bad in ({"channels_disabled": ["in_app"]}, {"categories_disabled": ["x"]}, {"quiet_start": "25:00"}, {"quiet_end": "7h"}):
        assert (await client.put("/api/v1/notifications/prefs", json=bad, headers=h)).status_code == 422, bad
    rows = (await db_session.execute(select(UserNotificationPref))).scalars().all()
    assert len(rows) == 1 and rows[0].user_id == plain.id


def _at(hour: int, minute: int = 0) -> datetime:
    """Horário local de Fortaleza (UTC-3) convertido para UTC, em 2026-10-16."""
    return datetime(2026, 10, 16, hour, minute, tzinfo=timezone(timedelta(hours=-3))).astimezone(timezone.utc)


async def test_quiet_hours_window_and_critical_bypass():
    prefs = Prefs()  # 20:00 -> 07:00
    assert quiet_until(prefs, _at(12), "normal") is None
    assert quiet_until(prefs, _at(19, 59), "normal") is None
    assert quiet_until(prefs, _at(21), "normal") == _at(7).replace(day=17)
    assert quiet_until(prefs, _at(3), "normal") == _at(7)
    assert quiet_until(prefs, _at(7), "normal") is None
    assert quiet_until(prefs, _at(23), "critical") is None
    assert quiet_until(Prefs(critical_bypass=False), _at(23), "critical") is not None
    assert quiet_until(Prefs(quiet_enabled=False), _at(23), "normal") is None
    day_window = Prefs(quiet_start="12:00", quiet_end="13:00")
    assert quiet_until(day_window, _at(12, 30), "normal") == _at(13)
    assert quiet_until(day_window, _at(15), "normal") is None


async def test_allows_keeps_in_app_as_floor():
    prefs = Prefs(channels_disabled=["email"], categories_disabled=["ticket"])
    assert allows(prefs, "in_app", "ticket.created") is True
    assert allows(prefs, "email", "backup.failed") is False
    assert allows(Prefs(categories_disabled=["ticket"]), "email", "ticket.created") is False
    assert allows(Prefs(categories_disabled=["ticket"]), "email", "backup.failed") is True
    assert (category_of("ticket.sla_breached"), category_of("inventory.divergence_found"), category_of("channel.degraded")) == (
        "ticket", "stock", "system")


async def _plan_for(db: AsyncSession, user, event_type="backup.failed", priority="normal", now=None, channels=("in_app", "email")):
    db.add(NotificationRule(name="r", event_type=event_type, audience=[f"user:{user.id}"], channels=list(channels),
                            template_code="generic", condition={}))
    await db.commit()
    event = DomainEvent(id=uuid.uuid4(), event_type=event_type, entity_type="x", payload={"title": "t"}, priority=priority)
    rules = list((await db.execute(select(NotificationRule))).scalars())
    return await plan_event(db, event, rules, {"in_app", "email"}, now or _at(12))


async def test_fanout_honors_prefs_and_quiet_hours(db_session: AsyncSession, users):
    _, _, plain = users
    by_channel = lambda plans: {p.channel: p for p in plans}

    daytime = by_channel(await _plan_for(db_session, plain, now=_at(12)))
    assert set(daytime) == {"in_app", "email"} and daytime["email"].next_attempt_at == _at(12)

    night = by_channel(await _plan_for(db_session, plain, now=_at(22)))
    assert night["in_app"].next_attempt_at == _at(22)  # caixa de entrada nunca espera
    assert night["email"].next_attempt_at == _at(7).replace(day=17)

    critical = by_channel(await _plan_for(db_session, plain, priority="critical", now=_at(22)))
    assert critical["email"].next_attempt_at == _at(22)

    db_session.add(UserNotificationPref(user_id=plain.id, channels_disabled=["email"]))
    await db_session.commit()
    assert set(by_channel(await _plan_for(db_session, plain, now=_at(12)))) == {"in_app"}

    pref = (await db_session.execute(select(UserNotificationPref))).scalar_one()
    pref.channels_disabled, pref.categories_disabled = [], ["system"]
    await db_session.commit()
    assert set(by_channel(await _plan_for(db_session, plain, now=_at(12)))) == {"in_app"}


# --- WebSocket ------------------------------------------------------------------------------------


async def test_ws_ticket_is_short_lived_and_useless_as_access_token(client: AsyncClient, users):
    from app.core.security import decode_access_token

    _, _, plain = users
    ticket = (await client.post("/api/v1/notifications/ws-ticket", headers=headers_for(plain))).json()["ticket"]
    payload = decode_access_token(ticket)
    assert payload["typ"] == "ws" and payload["sub"] == str(plain.id)
    assert datetime.fromtimestamp(payload["exp"], timezone.utc) - datetime.now(timezone.utc) <= timedelta(seconds=61)

    reused = await client.get("/api/v1/notifications", headers={"Authorization": f"Bearer {ticket}"})
    assert reused.status_code == 401
    assert (await client.post("/api/v1/notifications/ws-ticket")).status_code in (401, 403)
    # um token de acesso comum não vira ticket
    access = create_access_token({"sub": str(plain.id)})
    assert decode_access_token(access).get("typ") != "ws"
