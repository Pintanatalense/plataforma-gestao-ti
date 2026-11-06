"""Regras e automações (ADR-025 M5): escalonamento conferido no envio, canal alternativo quando a entrega falha de vez,
`job.failed` uma vez por queda, catálogo de eventos e validação das regras."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.identity.models import Permission, Role, role_permission_association, user_role_association
from app.notifications.dispatcher import Dispatcher
from app.notifications.email_service import EmailService, SmtpConfigSchema
from app.notifications.fanout import fan_out_batch
from app.notifications.job_runner import MAX_ATTEMPTS
from app.notifications.jobs import run_due_jobs
from app.notifications.models import Delivery, DomainEvent, Notification, NotificationRule, ScheduledJob
from app.notifications.rules_seed import seed_notification_rules
from tests.factories import headers_for, make_employee, make_org, make_ticket_category, make_user

pytestmark = pytest.mark.asyncio

ADMIN = "/api/v1/notifications/admin"


@pytest.fixture
def factory(db_session: AsyncSession) -> async_sessionmaker:
    return async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _no_quiet_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.notifications.fanout.quiet_until", lambda *args, **kwargs: None)


async def _grant(db: AsyncSession, user, code: str) -> None:
    role = Role(name=f"r-{uuid.uuid4().hex[:8]}")
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


@pytest.fixture
async def world(db_session: AsyncSession, factory):
    org = await make_org(db_session)
    category = await make_ticket_category(db_session, org.sector)
    requester = await make_user(db_session, await make_employee(db_session, org))
    attendant = await make_user(db_session, await make_employee(db_session, org))
    admin = await make_user(db_session, is_admin=True)
    await _grant(db_session, attendant, "service_desk.tickets.manage")
    async with factory() as s:
        await seed_notification_rules(s)
        await s.commit()
    return {"requester": requester, "attendant": attendant, "admin": admin, "category": category}


def h_admin(world) -> dict:
    return headers_for(world["admin"], "notifications.manage")


def h_attendant(world) -> dict:
    return headers_for(world["attendant"], "service_desk.tickets.manage")


async def _ticket(client: AsyncClient, world) -> str:
    resp = await client.post(
        "/api/v1/tickets",
        json={"title": "Sem rede", "description": "d", "priority": "HIGH", "category_id": str(world["category"].id)},
        headers=headers_for(world["requester"]),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _fan_out(factory) -> None:
    async with factory() as s:
        await fan_out_batch(s)
        await s.commit()


async def _deliveries(factory, **filters) -> list[Delivery]:
    async with factory() as s:
        stmt = select(Delivery)
        for key, value in filters.items():
            stmt = stmt.where(getattr(Delivery, key) == value)
        return list((await s.execute(stmt)).scalars())


async def _escalation_rule(client, world, until="first_response") -> dict:
    resp = await client.post(f"{ADMIN}/rules", json={
        "name": "Chamado sem resposta → administradores", "event_type": "ticket.created",
        "audience": ["sector_attendants"], "channels": ["in_app"], "template_code": "ticket.created.staff",
        "escalation": {"after_minutes": 30, "until": until, "audience": ["admins"], "channels": ["in_app"]},
    }, headers=h_admin(world))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _make_escalation_due(factory) -> None:
    async with factory() as s:
        await s.execute(
            update(Delivery).where(Delivery.escalation_condition.is_not(None))
            .values(next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
        await s.commit()


# --- Escalonamento --------------------------------------------------------------------------------


async def test_escalation_waits_and_goes_out_when_nobody_answered(client, world, factory):
    await _escalation_rule(client, world)
    await _ticket(client, world)
    await _fan_out(factory)
    [escalation] = await _deliveries(factory, escalation_condition="first_response")
    due = escalation.next_attempt_at if escalation.next_attempt_at.tzinfo else escalation.next_attempt_at.replace(tzinfo=timezone.utc)
    assert escalation.recipient_user_id == world["admin"].id and due > datetime.now(timezone.utc) + timedelta(minutes=29)

    await Dispatcher(factory).run_once(limit=200)
    assert (await _deliveries(factory, id=escalation.id))[0].status == "PENDING"  # ainda não é hora

    await _make_escalation_due(factory)
    await Dispatcher(factory).run_once(limit=200)
    assert (await _deliveries(factory, id=escalation.id))[0].status == "SENT"
    async with factory() as s:
        titles = [n.title for n in (await s.execute(select(Notification).where(Notification.user_id == world["admin"].id))).scalars()]
    assert any(t.startswith("Escalonado (sem resposta há 30 min)") for t in titles)


async def test_escalation_is_skipped_when_the_team_already_answered(client, world, factory):
    await _escalation_rule(client, world)
    ticket_id = await _ticket(client, world)
    await _fan_out(factory)
    internal = await client.post(
        f"/api/v1/tickets/{ticket_id}/interactions", json={"message": "nota", "is_internal": True}, headers=h_attendant(world)
    )
    assert internal.status_code in (200, 201)
    await _make_escalation_due(factory)
    await Dispatcher(factory).run_once(limit=200)
    assert (await _deliveries(factory, escalation_condition="first_response"))[0].status == "SENT"  # nota interna não conta

    await _ticket(client, world)  # segundo chamado, agora respondido em público
    await _fan_out(factory)
    second = [d for d in await _deliveries(factory, escalation_condition="first_response") if d.status == "PENDING"]
    tickets = (await client.get("/api/v1/tickets", headers=h_attendant(world))).json()
    newest = tickets["items"][0]["id"] if isinstance(tickets, dict) else tickets[0]["id"]
    public = await client.post(
        f"/api/v1/tickets/{newest}/interactions", json={"message": "Verificando", "is_internal": False}, headers=h_attendant(world)
    )
    assert public.status_code in (200, 201)
    await _make_escalation_due(factory)
    await Dispatcher(factory).run_once(limit=200)
    skipped = (await _deliveries(factory, id=second[0].id))[0]
    assert skipped.status == "SKIPPED" and "dispensado" in skipped.last_error


async def test_escalation_until_resolved_is_skipped_after_resolution(client, world, factory):
    await _escalation_rule(client, world, until="resolved")
    ticket_id = await _ticket(client, world)
    await _fan_out(factory)
    resolved = await client.patch(
        f"/api/v1/tickets/{ticket_id}", json={"status": "RESOLVED", "notes": "Resolvido"}, headers=h_attendant(world)
    )
    assert resolved.status_code == 200, resolved.text
    await _make_escalation_due(factory)
    await Dispatcher(factory).run_once(limit=200)
    assert (await _deliveries(factory, escalation_condition="resolved"))[0].status == "SKIPPED"


# --- Canal alternativo ----------------------------------------------------------------------------


async def test_dead_delivery_is_redone_once_by_the_fallback_channel(client, world, factory, db_session):
    await EmailService(db_session).update_config(
        SmtpConfigSchema(is_enabled=True, host="smtp.test", username="u", password="s3cret", app_base_url="http://sys")
    )
    await db_session.execute(update(NotificationRule).values(enabled=False))  # só a regra deste teste
    await db_session.commit()
    rule = await client.post(f"{ADMIN}/rules", json={
        "name": "Confirmação por e-mail", "event_type": "ticket.created", "condition": {"exclude_actor": False},
        "audience": ["requester"], "channels": ["email"], "template_code": "ticket.created.requester",
        "fallback_channel": "in_app",
    }, headers=h_admin(world))
    assert rule.status_code == 201, rule.text and rule.json()["fallback_channel"] == "in_app"

    await _ticket(client, world)
    await _fan_out(factory)
    with patch("app.notifications.channels.email.send_smtp_raw", return_value=("permanent", "550 no such user")):
        await Dispatcher(factory).run_once(limit=200)
    [dead] = await _deliveries(factory, channel="email")
    [fallback] = await _deliveries(factory, channel="in_app")
    assert dead.status == "DEAD" and fallback.fallback_of_id == dead.id and fallback.status == "PENDING"

    await Dispatcher(factory).run_once(limit=200)
    async with factory() as s:
        notes = list((await s.execute(select(Notification).where(Notification.user_id == world["requester"].id))).scalars())
    assert len(notes) == 1 and "registrado" in notes[0].title


# --- job.failed -----------------------------------------------------------------------------------


async def _last_attempt_due(factory, name: str) -> None:
    async with factory() as s:
        job = await s.get(ScheduledJob, name)
        if job is None:
            s.add(ScheduledJob(name=name, schedule="every:60", next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                               retry_attempt=MAX_ATTEMPTS - 1))
        else:
            job.next_run_at, job.retry_attempt = datetime.now(timezone.utc) - timedelta(minutes=1), MAX_ATTEMPTS - 1
        await s.commit()


async def _job_failed_events(factory) -> list[DomainEvent]:
    async with factory() as s:
        return list((await s.execute(select(DomainEvent).where(DomainEvent.event_type == "job.failed"))).scalars())


async def test_final_job_failure_is_announced_once_until_it_works_again(world, factory):
    state = {"fail": True}

    async def flaky(_factory):
        if state["fail"]:
            raise RuntimeError("disco cheio")

    async def broken_backup(_factory):
        raise RuntimeError("pg_dump ausente")

    with patch.dict("app.notifications.jobs.JOBS", {"t.flaky": flaky, "backup.daily": broken_backup}):
        await _last_attempt_due(factory, "t.flaky")
        await _last_attempt_due(factory, "backup.daily")
        await run_due_jobs(factory)
        events = await _job_failed_events(factory)
        assert [e.payload["job"] for e in events] == ["t.flaky"]  # o backup tem o próprio aviso
        assert events[0].priority == "high" and "disco cheio" in events[0].payload["error"]

        await _last_attempt_due(factory, "t.flaky")
        await run_due_jobs(factory)
        assert len(await _job_failed_events(factory)) == 1  # mesma queda: sem repetir

        state["fail"] = False
        await _last_attempt_due(factory, "t.flaky")
        await run_due_jobs(factory)
        state["fail"] = True
        await _last_attempt_due(factory, "t.flaky")
        await run_due_jobs(factory)
        assert len(await _job_failed_events(factory)) == 2  # voltou a funcionar e caiu de novo: novo aviso


# --- Catálogo e validação -------------------------------------------------------------------------


async def test_rules_listing_offers_the_event_catalog(client, world):
    listing = (await client.get(f"{ADMIN}/rules", headers=h_admin(world))).json()
    events = {e["code"]: e for e in listing["options"]["events"]}
    assert events["ticket.created"]["escalation"] is True and events["job.failed"]["escalation"] is False
    assert "first_response" in listing["options"]["escalation_until"]
    assert all(r["in_catalog"] for r in listing["items"])


async def test_escalation_and_fallback_are_validated(client, world):
    base = {"name": "x", "event_type": "ticket.created", "audience": ["requester"], "channels": ["in_app"]}
    h = h_admin(world)
    cases = [
        {**base, "event_type": "backup.failed", "escalation": {"after_minutes": 30, "audience": ["admins"]}},
        {**base, "escalation": {"after_minutes": 1, "audience": ["admins"]}},
        {**base, "escalation": {"after_minutes": 30, "audience": []}},
        {**base, "escalation": {"after_minutes": 30, "audience": ["admins"], "until": "sempre"}},
        {**base, "escalation": {"after_minutes": 30, "audience": ["admins"], "extra": 1}},
        {**base, "fallback_channel": "pombo"},
    ]
    for body in cases:
        assert (await client.post(f"{ADMIN}/rules", json=body, headers=h)).status_code == 422, body
    ok = await client.post(f"{ADMIN}/rules", json={**base, "escalation": {"after_minutes": 60, "audience": ["admins"]}}, headers=h)
    assert ok.status_code == 201 and ok.json()["escalation"]["until"] == "first_response"


async def test_simulator_shows_the_escalation(client, world):
    await _escalation_rule(client, world)
    sim = await client.post(f"{ADMIN}/rules/simulate", json={
        "event_type": "ticket.created", "payload": {"ticket_id": str(uuid.uuid4()), "title": "t"},
    }, headers=h_admin(world))
    assert sim.status_code == 200
    assert any(d["escalation_until"] == "first_response" for d in sim.json()["deliveries"])
