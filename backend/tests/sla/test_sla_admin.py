"""Administração de SLA (ADR-017, P4-S4): calendários, políticas, SLA da categoria e permissão Gerenciar SLA."""

import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from tests.factories import headers_for, make_ticket_category, make_user
from tests.sla.support import WEEKLY, Clock, World, open_ticket, sla_of, utc

pytestmark = pytest.mark.asyncio

SLA = "/api/v1/sla"
MANAGE = "service_desk.sla.manage"
CATEGORIES = "service_desk.categories.manage"


@pytest.fixture
async def manager(db_session: AsyncSession) -> dict:
    return headers_for(await make_user(db_session), MANAGE)


async def _calendar(client: AsyncClient, h: dict, name: str = "Comercial", **extra) -> dict:
    body = {"name": name, "timezone": "America/Sao_Paulo", "weekly_hours": WEEKLY, **extra}
    resp = await client.post(f"{SLA}/calendars", json=body, headers=h)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _targets(**minutes) -> list[dict]:
    return [{"priority": p, "first_response_minutes": f, "resolution_minutes": r} for p, (f, r) in minutes.items()]


async def _policy(client: AsyncClient, h: dict, calendar_id: str, name: str = "Ouro", **extra) -> dict:
    body = {"name": name, "calendar_id": calendar_id, "targets": _targets(HIGH=(30, 240)), **extra}
    resp = await client.post(f"{SLA}/policies", json=body, headers=h)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_only_sla_managers_change_and_category_managers_can_read(client: AsyncClient, db_session: AsyncSession, manager: dict):
    nobody = headers_for(await make_user(db_session))
    categories = headers_for(await make_user(db_session), CATEGORIES)
    body = {"name": "X", "weekly_hours": WEEKLY}
    assert (await client.post(f"{SLA}/calendars", json=body, headers=nobody)).status_code == 403
    assert (await client.post(f"{SLA}/calendars", json=body, headers=categories)).status_code == 403
    assert (await client.get(f"{SLA}/policies", headers=nobody)).status_code == 403
    assert (await client.get(f"{SLA}/policies", headers=categories)).status_code == 200
    assert (await client.get(f"{SLA}/calendars", headers=manager)).status_code == 200


async def test_calendar_is_validated_like_the_clock(client: AsyncClient, manager: dict):
    bad = [
        {"weekly_hours": {"0": [["18:00", "08:00"]]}},  # invertido
        {"weekly_hours": {"0": [["08:00", "12:00"], ["11:00", "18:00"]]}},  # sobreposto
        {"weekly_hours": {}},  # sem expediente
        {"weekly_hours": {"7": [["08:00", "18:00"]]}},  # dia inexistente
        {"weekly_hours": WEEKLY, "timezone": "Marte/Olympus"},
        {"weekly_hours": WEEKLY, "holidays": [{"day": "2026-12-25", "name": "Natal"}, {"day": "2026-12-25", "name": "De novo"}]},
    ]
    for extra in bad:
        resp = await client.post(f"{SLA}/calendars", json={"name": "Errado", **extra}, headers=manager)
        assert resp.status_code == 422, (extra, resp.text)


async def test_calendar_create_edit_holidays_and_delete(client: AsyncClient, db_session: AsyncSession, manager: dict):
    cal = await _calendar(client, manager, holidays=[{"day": "2026-12-25", "name": "Natal"}])
    assert cal["holidays"] == [{"day": "2026-12-25", "name": "Natal"}] and cal["policy_names"] == []
    assert (await client.post(f"{SLA}/calendars", json={"name": "comercial", "weekly_hours": WEEKLY}, headers=manager)).status_code == 409

    resp = await client.patch(f"{SLA}/calendars/{cal['id']}", json={"holidays": [{"day": "2026-12-25", "name": "Natal"}, {"day": "2027-01-01", "name": "Ano novo"}]}, headers=manager)
    assert resp.status_code == 200 and [h["day"] for h in resp.json()["holidays"]] == ["2026-12-25", "2027-01-01"]
    resp = await client.patch(f"{SLA}/calendars/{cal['id']}", json={"weekly_hours": {"5": [["08:00", "12:00"]]}}, headers=manager)
    assert resp.json()["weekly_hours"] == {"5": [["08:00", "12:00"]]} and len(resp.json()["holidays"]) == 2

    policy = await _policy(client, manager, cal["id"])
    in_use = await client.delete(f"{SLA}/calendars/{cal['id']}", headers=manager)
    assert in_use.status_code == 409 and "Ouro" in in_use.text
    assert (await client.delete(f"{SLA}/policies/{policy['id']}", headers=manager)).status_code == 204
    assert (await client.delete(f"{SLA}/calendars/{cal['id']}", headers=manager)).status_code == 204
    events = set((await db_session.execute(select(AuditLog.event_type).where(AuditLog.entity_id == uuid.UUID(cal["id"])))).scalars())
    assert events == {"sla.calendar_created", "sla.calendar_updated", "sla.calendar_deleted"}


async def test_policy_targets_are_validated_and_replaced(client: AsyncClient, manager: dict):
    cal = await _calendar(client, manager)
    for targets in (_targets(HIGH=(30, 240)) * 2, _targets(HIGH=(300, 240)), _targets(HIGH=(0, 240))):
        resp = await client.post(f"{SLA}/policies", json={"name": "Errada", "calendar_id": cal["id"], "targets": targets}, headers=manager)
        assert resp.status_code == 422, (targets, resp.text)
    for extra in ({"pause_statuses": ["OPENED"]}, {"alert_percent": 100}, {"reopen_rule": "NUNCA"}):
        resp = await client.post(f"{SLA}/policies", json={"name": "Errada", "calendar_id": cal["id"], **extra}, headers=manager)
        assert resp.status_code == 422, extra
    missing = await client.post(f"{SLA}/policies", json={"name": "Sem calendário", "calendar_id": str(uuid.uuid4())}, headers=manager)
    assert missing.status_code == 404

    policy = await _policy(client, manager, cal["id"])
    assert (policy["is_active"], policy["calendar_name"], policy["alert_percent"]) == (False, "Comercial", 80)
    resp = await client.patch(
        f"{SLA}/policies/{policy['id']}",
        json={"is_active": True, "targets": _targets(LOW=(480, 2880), CRITICAL=(15, 120)), "pause_statuses": ["IN_PROGRESS", "PENDING"]},
        headers=manager,
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["is_active"] is True and out["pause_statuses"] == ["IN_PROGRESS", "PENDING"]
    assert [t["priority"] for t in out["targets"]] == ["CRITICAL", "LOW"]


async def test_category_sla_needs_the_sla_permission_and_starts_the_clock_on_new_tickets(
    client: AsyncClient, db_session: AsyncSession, world: World, manager: dict
):
    cal = await _calendar(client, manager)
    policy = await _policy(client, manager, cal["id"], is_active=True)
    category = await make_ticket_category(db_session, world.org.sector)
    url = f"/api/v1/tickets/categories/{category.id}"

    only_categories = headers_for(await make_user(db_session), CATEGORIES)
    assert (await client.patch(url, json={"sla_policy_id": policy["id"]}, headers=only_categories)).status_code == 403
    assert (await client.patch(url, json={"name": "Rede"}, headers=only_categories)).status_code == 200  # o resto continua

    both = headers_for(await make_user(db_session), CATEGORIES, MANAGE)
    assert (await client.patch(url, json={"sla_policy_id": str(uuid.uuid4())}, headers=both)).status_code == 422
    resp = await client.patch(url, json={"sla_policy_id": policy["id"]}, headers=both)
    assert resp.status_code == 200 and resp.json()["sla_policy_id"] == policy["id"]
    listed = (await client.get(f"{SLA}/policies", headers=manager)).json()
    assert {p["name"]: p["category_names"] for p in listed}["Ouro"] == ["Rede"]
    assert (await client.delete(f"{SLA}/policies/{policy['id']}", headers=manager)).status_code == 409

    ticket = await open_ticket(client, world, category=category)
    sla = await sla_of(client, world, ticket)
    assert sla["state"] == "RUNNING" and sla["policy_name"] == "Ouro"

    resp = await client.patch(url, json={"sla_policy_id": None}, headers=both)
    assert resp.status_code == 200 and resp.json()["sla_policy_id"] is None
    assert (await sla_of(client, world, await open_ticket(client, world, category=category)))["state"] == "NOT_APPLICABLE"
    audit = (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "ticket_category.sla_changed"))).scalars().all()
    assert len(audit) == 2


async def test_creating_a_category_with_sla_also_needs_the_permission(client: AsyncClient, db_session: AsyncSession, manager: dict):
    cal = await _calendar(client, manager)
    policy = await _policy(client, manager, cal["id"])
    body = {"name": "Impressoras", "sla_policy_id": policy["id"]}
    only_categories = headers_for(await make_user(db_session), CATEGORIES)
    assert (await client.post("/api/v1/tickets/categories", json=body, headers=only_categories)).status_code == 403
    both = headers_for(await make_user(db_session), CATEGORIES, MANAGE)
    resp = await client.post("/api/v1/tickets/categories", json=body, headers=both)
    assert resp.status_code == 201 and resp.json()["sla_policy_id"] == policy["id"]


async def test_sla_managers_can_reopen_after_the_window(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    ticket = await open_ticket(client, world)
    await client.patch(f"/api/v1/tickets/{ticket}", json={"status": "RESOLVED", "notes": "ok"}, headers=world.h_att)
    clock.set(utc(26, 11) + timedelta(days=10))
    late = await client.patch(f"/api/v1/tickets/{ticket}", json={"status": "OPENED"}, headers=world.h_att)
    assert late.status_code == 422
    manager = headers_for(world.attendant, "service_desk.tickets.manage", MANAGE)
    assert (await client.patch(f"/api/v1/tickets/{ticket}", json={"status": "OPENED"}, headers=manager)).status_code == 200
