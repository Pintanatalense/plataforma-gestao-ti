"""Indicadores de SLA dos chamados vinculados (ADR-026, PR 2c): por tipo, por setor e os dois sinais de atraso."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.sla.report import sla_report
from tests.factories import headers_for, make_employee, make_sector, make_ticket_category, make_user
from tests.sla.support import utc

pytestmark = pytest.mark.asyncio

API = "/api/v1/tickets"
MANAGE = "service_desk.tickets.manage"


async def _sector_b(db: AsyncSession, w, *, with_policy: bool = True):
    sector = await make_sector(db, w.org.unit)
    cat = await make_ticket_category(db, sector)
    if with_policy:
        cat.sla_policy_id = w.policy.id
    emp = await make_employee(db, w.org)
    emp.sector_id = sector.id
    await db.commit()
    return sector, cat, await make_user(db, emp)


async def _open(client: AsyncClient, w, category, children: list[dict]) -> str:
    body = {"title": "P", "description": "d", "priority": "HIGH", "category_id": str(category.id), "children": children}
    resp = await client.post(API, json=body, headers=w.h_req)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _resolve(client: AsyncClient, ticket_id: str, headers) -> None:
    resp = await client.patch(f"{API}/{ticket_id}", json={"status": "RESOLVED"}, headers=headers)
    assert resp.status_code == 200, resp.text


async def _overview(client: AsyncClient, w, parent_id: str) -> dict:
    return (await client.get(f"{API}/{parent_id}/children", headers=w.h_req)).json()


async def test_report_splits_standalone_parent_and_child_and_departments(
    client: AsyncClient, db_session: AsyncSession, world, clock
):
    w = world
    sector_b, cat_b, att_b = await _sector_b(db_session, w)
    h_att = headers_for(w.attendant, MANAGE)
    standalone = await _open(client, w, w.category, [])
    parent = await _open(client, w, w.category, [{"category_id": str(cat_b.id), "title": "E", "description": "d"}])
    [child] = (await _overview(client, w, parent))["children"]

    clock.set(utc(26, 11, 30))  # dentro da primeira resposta (60 min) e da resolução
    await _resolve(client, child["id"], headers_for(att_b, MANAGE))
    await _resolve(client, standalone, h_att)
    await _resolve(client, parent, h_att)

    report = await sla_report(db_session)
    kinds = {g.key: g for g in report.by_kind}
    assert set(kinds) == {"standalone", "parent", "child"}
    assert all(g.met == 1 and g.breached == 0 for g in kinds.values())
    assert [g.label for g in report.child_by_sector] == [sector_b.name]
    assert report.total.met == 3


async def test_parent_carries_two_separate_overdue_signals(
    client: AsyncClient, db_session: AsyncSession, world, clock
):
    w = world
    _, cat_b, _ = await _sector_b(db_session, w)
    parent = await _open(client, w, w.category, [{"category_id": str(cat_b.id), "title": "E", "description": "d"}])

    clock.set(utc(28, 12))  # quarta: os dois prazos de resolução (8 h úteis desde segunda 11h) venceram
    report = await sla_report(db_session)
    assert report.processes.open == 1
    assert report.processes.process_overdue == 1
    assert report.processes.steps_overdue == 1
    progress = (await _overview(client, w, parent))["progress"]
    assert progress["steps_overdue"] == 1 and progress["process_overdue"] is True


async def test_signals_stay_apart_without_parent_policy_or_required_step(
    client: AsyncClient, db_session: AsyncSession, world, clock
):
    w = world
    _, cat_b, _ = await _sector_b(db_session, w)
    no_policy = await make_ticket_category(db_session, w.org.sector)
    parent = await _open(
        client, w, no_policy, [{"category_id": str(cat_b.id), "title": "E", "description": "d", "is_required": False}]
    )

    clock.set(utc(28, 12))
    report = await sla_report(db_session)
    # O filho está atrasado, mas não é obrigatório; o principal não tem relógio.
    assert report.overdue == 1
    assert report.processes.open == 1
    assert report.processes.process_overdue == 0
    assert report.processes.steps_overdue == 0
    progress = (await _overview(client, w, parent))["progress"]
    assert progress["overdue"] == 1 and progress["steps_overdue"] == 0 and progress["process_overdue"] is False
