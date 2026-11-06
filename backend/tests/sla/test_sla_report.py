"""Indicadores de SLA (ADR-017, P4-S5): relatório com período e situação de cada chamado na lista.

Política de teste: HIGH = 60 min de primeira resposta e 480 min de resolução, alerta em 80%; expediente 08:00-18:00.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import headers_for, make_ticket_category, make_user
from tests.sla.support import Clock, World, open_ticket, patch, sla_of, utc

pytestmark = pytest.mark.asyncio
REPORT = "/api/v1/tickets/reports/summary"


async def report(client: AsyncClient, w: World, **params) -> dict:
    resp = await client.get(REPORT, params=params, headers=w.h_admin)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def answer(client: AsyncClient, w: World, ticket_id: str) -> None:
    resp = await client.post(f"/api/v1/tickets/{ticket_id}/interactions", json={"message": "Vendo", "is_internal": False}, headers=w.h_att)
    assert resp.status_code == 201, resp.text


async def test_compliance_and_average_business_times(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    met = await open_ticket(client, world)  # segunda 11:00
    late = await open_ticket(client, world)
    clock.set(utc(26, 11, 30))
    await answer(client, world, met)  # primeira resposta em 30 min
    clock.set(utc(26, 13))
    await patch(client, world, met, status="RESOLVED")  # 120 min: cumprido
    clock.set(utc(26, 14))
    await patch(client, world, late, status="RESOLVED")  # sem resposta em 60 min: violado
    no_sla = await make_ticket_category(db_session, world.org.sector)
    await open_ticket(client, world, category=no_sla)  # categoria sem política: fora dos indicadores

    sla = (await report(client, world))["sla"]
    total = sla["total"]
    assert (total["met"], total["breached"], total["compliance_percent"]) == (1, 1, 50.0)
    assert total["avg_first_response_minutes"] == 30  # só quem respondeu entra na média
    assert total["avg_resolution_minutes"] == 150  # (120 + 180) / 2
    assert [(g["key"], g["met"], g["breached"]) for g in sla["by_priority"]] == [("HIGH", 1, 1)]
    assert [(g["label"], g["met"] + g["breached"]) for g in sla["by_category"]] == [(world.category.name, 2)]
    assert sla["open"] == 0 and sla["attention"] == []


async def test_period_uses_the_resolution_day(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    ticket = await open_ticket(client, world)
    clock.set(utc(26, 12, 30))
    await patch(client, world, ticket, status="RESOLVED", notes="Resolvido")

    same_day = await report(client, world, start="2026-10-26", end="2026-10-26")
    assert same_day["start"] == "2026-10-26" and same_day["sla"]["total"]["breached"] == 1
    next_day = (await report(client, world, start="2026-10-27", end="2026-10-31"))["sla"]["total"]
    assert (next_day["met"], next_day["breached"], next_day["compliance_percent"]) == (0, 0, None)
    assert next_day["avg_resolution_minutes"] is None


async def test_open_tickets_at_risk_and_overdue(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    clock.set(utc(26, 10, 30))
    overdue = await open_ticket(client, world)  # primeira resposta vence 11:30
    clock.set(utc(26, 11))
    risky = await open_ticket(client, world)  # vence 12:00; alerta a partir de 11:48
    calm = await open_ticket(client, world, priority="LOW")  # 480 min
    paused = await open_ticket(client, world)
    await patch(client, world, paused, status="PENDING")
    clock.set(utc(26, 11, 50))

    sla = (await report(client, world))["sla"]
    assert (sla["open"], sla["overdue"], sla["at_risk"]) == (4, 1, 1)
    assert [(a["ticket_id"], a["overdue"], a["kind"]) for a in sla["attention"]] == [
        (overdue, True, "FIRST_RESPONSE"), (risky, False, "FIRST_RESPONSE"),
    ]

    by_id = {t["id"]: t["sla"] for t in (await client.get("/api/v1/tickets", headers=world.h_att)).json()}
    assert (by_id[overdue]["overdue"], by_id[overdue]["at_risk"]) == (True, False)
    assert (by_id[risky]["overdue"], by_id[risky]["at_risk"]) == (False, True)
    assert (by_id[calm]["overdue"], by_id[calm]["at_risk"]) == (False, False)
    assert (by_id[paused]["overdue"], by_id[paused]["at_risk"]) == (False, False)  # pausado não tem prazo
    assert (await sla_of(client, world, risky))["at_risk"] is True


async def test_disabled_alert_never_marks_risk(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    world.policy.alert_percent = 0
    await db_session.commit()
    ticket = await open_ticket(client, world)
    clock.set(utc(26, 11, 59))
    assert (await sla_of(client, world, ticket))["at_risk"] is False


async def test_report_validation_and_permission(client: AsyncClient, db_session: AsyncSession, world: World):
    resp = await client.get(REPORT, params={"start": "2026-10-27", "end": "2026-10-26"}, headers=world.h_admin)
    assert resp.status_code == 422
    manager = await make_user(db_session)
    allowed = await client.get(REPORT, headers=headers_for(manager, "service_desk.reports.read"))
    assert allowed.status_code == 200 and "sla" in allowed.json()
    assert (await client.get(REPORT, headers=world.h_att)).status_code == 403
