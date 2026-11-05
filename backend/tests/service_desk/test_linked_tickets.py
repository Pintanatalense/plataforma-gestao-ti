"""
Chamados vinculados (ADR-026): principal e subchamados para qualquer categoria e setor.

Mundo de teste: o principal é do setor P (atendente `att_p`); os filhos vão para os setores B e C (atendentes `att_b` e
`att_c`); `outsider` atende um quarto setor sem vínculo. Categorias e setores vêm das fábricas, sem nomes de processo.
A concorrência entre incluir filhos e encerrar o principal é testada no PostgreSQL, com duas sessões reais.
"""

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.notifications.models import DomainEvent
from app.service_desk.models import Ticket, TicketCategory
from tests.factories import (
    headers_for,
    make_employee,
    make_org,
    make_sector,
    make_ticket_category,
    make_user,
)

pytestmark = pytest.mark.asyncio

API = "/api/v1/tickets"
MANAGE = "service_desk.tickets.manage"
ON_BEHALF = "service_desk.tickets.create_on_behalf"
REASON = "Motivo registrado para a etapa"


@dataclass
class World:
    org: object
    sector_b: object
    sector_c: object
    cat_parent: TicketCategory
    cat_b: TicketCategory
    cat_c: TicketCategory
    requester: object
    requester_emp: object
    att_p: object
    att_b: object
    att_c: object
    outsider: object


async def _attendant(db: AsyncSession, org, sector):
    emp = await make_employee(db, org)
    emp.sector_id = sector.id
    await db.commit()
    return await make_user(db, emp)


async def _world(db: AsyncSession) -> World:
    org = await make_org(db)
    sector_b = await make_sector(db, org.unit)
    sector_c = await make_sector(db, org.unit)
    sector_d = await make_sector(db, org.unit)
    requester_emp = await make_employee(db, org)
    requester = await make_user(db, requester_emp)
    return World(
        org=org, sector_b=sector_b, sector_c=sector_c,
        cat_parent=await make_ticket_category(db, org.sector),
        cat_b=await make_ticket_category(db, sector_b),
        cat_c=await make_ticket_category(db, sector_c),
        requester=requester, requester_emp=requester_emp,
        att_p=await _attendant(db, org, org.sector),
        att_b=await _attendant(db, org, sector_b),
        att_c=await _attendant(db, org, sector_c),
        outsider=await _attendant(db, org, sector_d),
    )


def _child(cat, title="Etapa", **extra) -> dict:
    return {"category_id": str(cat.id), "title": title, "description": "d", **extra}


def _h(user, *perms):
    return headers_for(user, *perms)


def _att(user):
    return headers_for(user, MANAGE)


async def _open(client: AsyncClient, w: World, children: list[dict], headers=None, **extra) -> dict:
    body = {"title": "Processo", "description": "d", "category_id": str(w.cat_parent.id), "children": children, **extra}
    resp = await client.post(API, json=body, headers=headers or _h(w.requester))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _children(db: AsyncSession, parent_id: str) -> list[Ticket]:
    rows = await db.execute(
        select(Ticket).where(Ticket.parent_ticket_id == uuid.UUID(parent_id)).order_by(Ticket.created_at, Ticket.id)
    )
    return list(rows.scalars().all())


async def _child_of(db: AsyncSession, parent_id: str, sector) -> Ticket:
    return next(c for c in await _children(db, parent_id) if c.responsible_sector_id == sector.id)


async def _audits(db: AsyncSession, ticket_id, event_type: str) -> list[AuditLog]:
    rows = await db.execute(
        select(AuditLog).where(AuditLog.entity_id == uuid.UUID(str(ticket_id)), AuditLog.event_type == event_type)
    )
    return list(rows.scalars().all())


async def _events(db: AsyncSession, event_type: str, entity_id=None) -> list[DomainEvent]:
    stmt = select(DomainEvent).where(DomainEvent.event_type == event_type)
    if entity_id is not None:
        stmt = stmt.where(DomainEvent.entity_id == uuid.UUID(str(entity_id)))
    return list((await db.execute(stmt)).scalars().all())


async def _resolve(client: AsyncClient, ticket_id, headers) -> int:
    return (await client.patch(f"{API}/{ticket_id}", json={"status": "RESOLVED"}, headers=headers)).status_code


# --- 1. Abertura e visibilidade ------------------------------------------------------------------------------


async def test_open_with_children_inherits_requester_and_routes_each_child(
    client: AsyncClient, db_session: AsyncSession
):
    w = await _world(db_session)
    parent = await _open(client, w, [_child(w.cat_b), _child(w.cat_c, is_required=False)])
    children = await _children(db_session, parent["id"])
    assert {c.responsible_sector_id for c in children} == {w.sector_b.id, w.sector_c.id}
    for child in children:
        assert child.requester_id == w.requester_emp.id
        assert child.created_by_user_id == w.requester.id
        assert child.origin_sector_id == w.org.sector.id
    assert {c.is_required for c in children} == {True, False}

    [added] = await _audits(db_session, parent["id"], "ticket.children_added")
    assert len(added.data["children"]) == 2
    [created] = await _audits(db_session, children[0].id, "ticket.created")
    assert created.data["parent_ticket_id"] == parent["id"]


async def test_invalid_child_creates_nothing(client: AsyncClient, db_session: AsyncSession):
    w = await _world(db_session)
    inactive = await make_ticket_category(db_session, w.sector_b, active=False)
    before = (await db_session.execute(select(func.count(Ticket.id)))).scalar_one()
    body = {
        "title": "Processo", "description": "d", "category_id": str(w.cat_parent.id),
        "children": [_child(w.cat_b), _child(inactive)],
    }
    resp = await client.post(API, json=body, headers=_h(w.requester))
    assert resp.status_code == 400
    await db_session.rollback()
    assert (await db_session.execute(select(func.count(Ticket.id)))).scalar_one() == before


async def test_each_department_sees_only_its_child(client: AsyncClient, db_session: AsyncSession):
    w = await _world(db_session)
    parent = await _open(client, w, [_child(w.cat_b), _child(w.cat_c)])
    child_b = await _child_of(db_session, parent["id"], w.sector_b)
    child_c = await _child_of(db_session, parent["id"], w.sector_c)

    note = await client.post(
        f"{API}/{child_b.id}/interactions", json={"message": "nota do setor", "is_internal": True},
        headers=_att(w.att_b),
    )
    assert note.status_code == 201, note.text
    db_session.expire(child_b, ["interactions"])  # o cliente de teste divide a sessão: relê as interações

    # Solicitante: resumo e detalhe de todos os filhos, sem nota interna.
    h = _h(w.requester)
    overview = (await client.get(f"{API}/{parent['id']}/children", headers=h)).json()
    assert {c["id"] for c in overview["children"]} == {str(child_b.id), str(child_c.id)}
    detail = (await client.get(f"{API}/{child_b.id}", headers=h)).json()
    assert detail["interactions"] == []
    assert detail["parent_ticket_id"] == parent["id"]

    # Atendente de B: só o próprio filho; não vê o principal, então o vínculo não aparece para ele.
    hb = _att(w.att_b)
    own = await client.get(f"{API}/{child_b.id}", headers=hb)
    assert own.status_code == 200
    assert own.json()["parent_ticket_id"] is None
    assert len(own.json()["interactions"]) == 1
    assert (await client.get(f"{API}/{child_c.id}", headers=hb)).status_code == 403
    assert (await client.get(f"{API}/{parent['id']}/children", headers=hb)).status_code == 403

    # Atendente do principal: acompanha pelo resumo, mas não abre o detalhe de filhos de outros setores.
    hp = _att(w.att_p)
    assert (await client.get(f"{API}/{parent['id']}/children", headers=hp)).status_code == 200
    assert (await client.get(f"{API}/{child_b.id}", headers=hp)).status_code == 403

    # Quarto setor sem vínculo: nada.
    ho = _att(w.outsider)
    for path in (f"{API}/{parent['id']}", f"{API}/{parent['id']}/children", f"{API}/{child_b.id}"):
        assert (await client.get(path, headers=ho)).status_code == 403


async def test_progress_appears_in_parent_detail(client: AsyncClient, db_session: AsyncSession):
    w = await _world(db_session)
    parent = await _open(client, w, [_child(w.cat_b), _child(w.cat_c, is_required=False)])
    progress = (await client.get(f"{API}/{parent['id']}", headers=_h(w.requester))).json()["children_progress"]
    assert progress == {"total": 2, "done": 0, "canceled": 0, "required_pending": 1, "overdue": 0}


# --- 2. Criador diferente do solicitante ---------------------------------------------------------------------


async def test_creator_on_behalf_follows_and_comments_on_every_child(client: AsyncClient, db_session: AsyncSession):
    w = await _world(db_session)
    opener = await make_user(db_session, await make_employee(db_session, w.org))
    parent = await _open(
        client, w, [_child(w.cat_b), _child(w.cat_c)], headers=_h(opener, ON_BEHALF),
        requester_id=str(w.requester_emp.id),
    )
    for child in await _children(db_session, parent["id"]):
        assert child.requester_id == w.requester_emp.id
        for user in (opener, w.requester):
            h = _h(user)
            assert (await client.get(f"{API}/{child.id}", headers=h)).status_code == 200
            public = await client.post(f"{API}/{child.id}/interactions", json={"message": "oi"}, headers=h)
            assert public.status_code == 201, public.text
            internal = await client.post(
                f"{API}/{child.id}/interactions", json={"message": "x", "is_internal": True}, headers=h
            )
            assert internal.status_code == 403
            # Acompanha, mas não atende: não muda status de um filho.
            assert (await _resolve(client, child.id, h)) == 403


async def test_creator_of_one_child_sees_only_that_child(client: AsyncClient, db_session: AsyncSession):
    w = await _world(db_session)
    parent = await _open(client, w, [_child(w.cat_b)])
    resp = await client.post(
        f"{API}/{parent['id']}/children", json={"children": [_child(w.cat_c)]}, headers=_att(w.att_p)
    )
    assert resp.status_code == 201, resp.text
    child_c = await _child_of(db_session, parent["id"], w.sector_c)
    child_b = await _child_of(db_session, parent["id"], w.sector_b)
    assert child_c.created_by_user_id == w.att_p.id
    hp = _att(w.att_p)
    assert (await client.get(f"{API}/{child_c.id}", headers=hp)).status_code == 200
    comment = await client.post(f"{API}/{child_c.id}/interactions", json={"message": "oi"}, headers=hp)
    assert comment.status_code == 201
    # Criou o filho de C, mas não é do setor dele: nota interna e alteração continuam do setor C.
    note = await client.post(f"{API}/{child_c.id}/interactions", json={"message": "x", "is_internal": True}, headers=hp)
    assert note.status_code == 403
    assert (await client.get(f"{API}/{child_b.id}", headers=hp)).status_code == 403


# --- 3 e 4. Inclusão depois da abertura ----------------------------------------------------------------------


async def test_add_children_later_updates_progress_audit_and_notifies_once(
    client: AsyncClient, db_session: AsyncSession
):
    w = await _world(db_session)
    parent = await _open(client, w, [])
    assert (await client.get(f"{API}/{parent['id']}", headers=_h(w.requester))).json()["children_progress"] is None
    resp = await client.post(
        f"{API}/{parent['id']}/children", json={"children": [_child(w.cat_b), _child(w.cat_c)]},
        headers=_att(w.att_p),
    )
    assert resp.status_code == 201, resp.text
    overview = (await client.get(f"{API}/{parent['id']}/children", headers=_h(w.requester))).json()
    assert overview["progress"]["total"] == 2
    assert len(await _audits(db_session, parent["id"], "ticket.children_added")) == 1
    [batch] = await _events(db_session, "ticket.children_created", parent["id"])
    assert len(batch.payload["children"]) == 2
    assert batch.payload["created_by_user_id"] == str(w.requester.id)


async def test_only_parent_people_add_children(client: AsyncClient, db_session: AsyncSession):
    w = await _world(db_session)
    parent = await _open(client, w, [])
    body = {"children": [_child(w.cat_b)]}
    assert (await client.post(f"{API}/{parent['id']}/children", json=body, headers=_att(w.outsider))).status_code == 403
    assert (await client.post(f"{API}/{parent['id']}/children", json=body, headers=_h(w.requester))).status_code == 201


async def test_add_children_after_parent_resolved_is_conflict(client: AsyncClient, db_session: AsyncSession):
    w = await _world(db_session)
    parent = await _open(client, w, [])
    assert await _resolve(client, parent["id"], _att(w.att_p)) == 200
    resp = await client.post(
        f"{API}/{parent['id']}/children", json={"children": [_child(w.cat_b)]}, headers=_att(w.att_p)
    )
    assert resp.status_code == 409


async def test_one_level_only(client: AsyncClient, db_session: AsyncSession):
    w = await _world(db_session)
    parent = await _open(client, w, [_child(w.cat_b)])
    child_b = await _child_of(db_session, parent["id"], w.sector_b)
    resp = await client.post(
        f"{API}/{child_b.id}/children", json={"children": [_child(w.cat_c)]}, headers=_att(w.att_b)
    )
    assert resp.status_code == 400


async def test_child_routing_follows_category_unless_permitted(client: AsyncClient, db_session: AsyncSession):
    w = await _world(db_session)
    rerouted = _child(w.cat_b, responsible_sector_id=str(w.sector_c.id))
    body = {"title": "P", "description": "d", "category_id": str(w.cat_parent.id), "children": [rerouted]}
    assert (await client.post(API, json=body, headers=_h(w.requester))).status_code == 403
    allowed = await client.post(API, json=body, headers=_h(w.requester, "service_desk.tickets.route_any_sector"))
    assert allowed.status_code == 201, allowed.text
    [child] = await _children(db_session, allowed.json()["id"])
    assert child.responsible_sector_id == w.sector_c.id


# --- 6. Encerramento do principal ----------------------------------------------------------------------------


async def test_parent_waits_for_required_children(client: AsyncClient, db_session: AsyncSession):
    w = await _world(db_session)
    parent = await _open(client, w, [_child(w.cat_b), _child(w.cat_c, is_required=False)])
    child_b = await _child_of(db_session, parent["id"], w.sector_b)
    hp = _att(w.att_p)

    refused = await client.patch(f"{API}/{parent['id']}", json={"status": "RESOLVED"}, headers=hp)
    assert refused.status_code == 400
    assert str(child_b.id)[:8] in refused.json()["error"]["message"]
    # O solicitante também não encerra por fora.
    assert (await client.patch(f"{API}/{parent['id']}", json={"status": "CLOSED"}, headers=_h(w.requester))).status_code == 400

    assert await _resolve(client, child_b.id, _att(w.att_b)) == 200
    [done] = await _events(db_session, "ticket.child_completed", parent["id"])
    assert done.payload["all_required_done"] is True
    assert len(await _audits(db_session, parent["id"], "ticket.child_completed")) == 1
    # O filho não obrigatório ainda aberto não trava.
    assert await _resolve(client, parent["id"], hp) == 200


# --- 7. Cancelamento e substituição --------------------------------------------------------------------------


async def test_cancel_requires_reason_and_keeps_parent_blocked(client: AsyncClient, db_session: AsyncSession):
    w = await _world(db_session)
    parent = await _open(client, w, [_child(w.cat_b)])
    child_b = await _child_of(db_session, parent["id"], w.sector_b)
    path = f"{API}/{child_b.id}/cancel"

    assert (await client.post(path, json={}, headers=_att(w.att_p))).status_code == 422
    assert (await client.post(path, json={"reason": "curto"}, headers=_att(w.att_p))).status_code == 422
    for who in (_h(w.requester), _att(w.outsider), _att(w.att_c)):
        assert (await client.post(path, json={"reason": REASON}, headers=who)).status_code == 403

    # O setor do principal cancela uma etapa de outro setor (decisão do ADR-026), com motivo e auditoria.
    resp = await client.post(path, json={"reason": REASON}, headers=_att(w.att_p))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "CANCELED"
    assert any(REASON in i["message"] for i in resp.json()["interactions"])
    [own] = await _audits(db_session, child_b.id, "ticket.canceled")
    assert own.data["reason"] == REASON
    assert own.data["canceled_by_sector_id"] == str(w.org.sector.id)
    [on_parent] = await _audits(db_session, parent["id"], "ticket.child_canceled")
    assert on_parent.data["is_required"] is True
    assert len(await _events(db_session, "ticket.canceled", child_b.id)) == 1
    assert len(await _events(db_session, "ticket.child_canceled", parent["id"])) == 1

    # Cancelado não é concluído: o principal continua travado.
    progress = (await client.get(f"{API}/{parent['id']}/children", headers=_h(w.requester))).json()["progress"]
    assert progress["canceled"] == 1 and progress["required_pending"] == 1 and progress["done"] == 0
    assert await _resolve(client, parent["id"], _att(w.att_p)) == 400
    # E não se cancela duas vezes nem se reabre.
    assert (await client.post(path, json={"reason": REASON}, headers=_att(w.att_b))).status_code == 409
    assert (await client.patch(f"{API}/{child_b.id}", json={"status": "OPENED"}, headers=_att(w.att_b))).status_code == 400


async def test_child_sector_may_cancel_its_own_step(client: AsyncClient, db_session: AsyncSession):
    w = await _world(db_session)
    parent = await _open(client, w, [_child(w.cat_b)])
    child_b = await _child_of(db_session, parent["id"], w.sector_b)
    resp = await client.post(f"{API}/{child_b.id}/cancel", json={"reason": REASON}, headers=_att(w.att_b))
    assert resp.status_code == 200


async def test_replace_canceled_step_keeps_history(client: AsyncClient, db_session: AsyncSession):
    w = await _world(db_session)
    parent = await _open(client, w, [_child(w.cat_b)])
    child_b = await _child_of(db_session, parent["id"], w.sector_b)
    hp = _att(w.att_p)
    body = {"reason": REASON, "child": _child(w.cat_c, title="Nova etapa")}

    assert (await client.post(f"{API}/{child_b.id}/replace", json=body, headers=hp)).status_code == 409  # não cancelado
    assert (await client.post(f"{API}/{child_b.id}/cancel", json={"reason": REASON}, headers=hp)).status_code == 200
    for who in (_h(w.requester), _att(w.att_b)):
        assert (await client.post(f"{API}/{child_b.id}/replace", json=body, headers=who)).status_code == 403

    resp = await client.post(f"{API}/{child_b.id}/replace", json=body, headers=hp)
    assert resp.status_code == 201, resp.text
    new = resp.json()
    assert new["replaces_ticket_id"] == str(child_b.id)
    assert new["is_required"] is True
    assert new["responsible_sector_id"] == str(w.sector_c.id)
    assert (await client.post(f"{API}/{child_b.id}/replace", json=body, headers=hp)).status_code == 409  # já substituído

    old = (await client.get(f"{API}/{child_b.id}", headers=_att(w.att_b))).json()
    assert old["status"] == "CANCELED" and old["is_required"] is False
    assert any(REASON in i["message"] for i in old["interactions"])
    assert len(await _audits(db_session, parent["id"], "ticket.child_replaced")) == 1
    assert len(await _audits(db_session, child_b.id, "ticket.requirement_changed")) == 1
    overview = (await client.get(f"{API}/{parent['id']}/children", headers=_h(w.requester))).json()
    by_id = {c["id"]: c for c in overview["children"]}
    assert by_id[str(child_b.id)]["replaced_by_ticket_id"] == new["id"]

    # O principal só destrava quando a etapa nova conclui.
    assert await _resolve(client, parent["id"], hp) == 400
    assert await _resolve(client, new["id"], _att(w.att_c)) == 200
    assert await _resolve(client, parent["id"], hp) == 200


# --- 8. Obrigatoriedade --------------------------------------------------------------------------------------


async def test_dispensing_a_step_unblocks_parent_without_erasing_it(client: AsyncClient, db_session: AsyncSession):
    w = await _world(db_session)
    parent = await _open(client, w, [_child(w.cat_b)])
    child_b = await _child_of(db_session, parent["id"], w.sector_b)
    await client.post(f"{API}/{child_b.id}/interactions", json={"message": "andamento"}, headers=_att(w.att_b))
    path = f"{API}/{child_b.id}/requirement"
    body = {"is_required": False, "reason": REASON}

    assert (await client.patch(path, json=body, headers=_att(w.att_b))).status_code == 403
    assert (await client.patch(path, json={"is_required": False, "reason": "x"}, headers=_att(w.att_p))).status_code == 422
    resp = await client.patch(path, json=body, headers=_att(w.att_p))
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_required"] is False
    assert len(await _audits(db_session, child_b.id, "ticket.requirement_changed")) == 1
    assert len(await _audits(db_session, parent["id"], "ticket.requirement_changed")) == 1

    assert await _resolve(client, parent["id"], _att(w.att_p)) == 200
    still = (await client.get(f"{API}/{child_b.id}", headers=_att(w.att_b))).json()
    assert still["status"] == "OPENED" and len(still["interactions"]) == 1


async def test_canceled_step_cannot_become_required_again(client: AsyncClient, db_session: AsyncSession):
    w = await _world(db_session)
    parent = await _open(client, w, [_child(w.cat_b, is_required=False)])
    child_b = await _child_of(db_session, parent["id"], w.sector_b)
    await client.post(f"{API}/{child_b.id}/cancel", json={"reason": REASON}, headers=_att(w.att_p))
    resp = await client.patch(
        f"{API}/{child_b.id}/requirement", json={"is_required": True, "reason": REASON}, headers=_att(w.att_p)
    )
    assert resp.status_code == 409


# --- 10. Notificações consolidadas ---------------------------------------------------------------------------


async def test_requester_and_creator_get_one_batch_notice_not_one_per_child(db_session: AsyncSession, client):
    from app.notifications.audience import resolve_audience
    from app.notifications.fanout import rule_matches_event
    from app.notifications.models import NotificationRule
    from app.notifications.rules_seed import seed_notification_rules

    w = await _world(db_session)
    await seed_notification_rules(db_session)
    await db_session.commit()
    opener = await make_user(db_session, await make_employee(db_session, w.org))
    parent = await _open(
        client, w, [_child(w.cat_b), _child(w.cat_c)], headers=_h(opener, ON_BEHALF),
        requester_id=str(w.requester_emp.id),
    )
    rules = {r.code: r for r in (await db_session.execute(select(NotificationRule))).scalars()}

    created = await _events(db_session, "ticket.created")
    parent_event = next(e for e in created if str(e.entity_id) == parent["id"])
    child_events = [e for e in created if e.payload.get("parent_ticket_id") == parent["id"]]
    assert len(child_events) == 2
    # Cada filho avisa o próprio setor, mas não confirma ao solicitante um a um.
    assert rule_matches_event(rules["ticket.created.requester"], parent_event)
    for event in child_events:
        assert not rule_matches_event(rules["ticket.created.requester"], event)
        assert rule_matches_event(rules["ticket.created.staff"], event)

    # O aviso consolidado vai ao solicitante; quem abriu é o autor do lote (o motor não avisa o autor).
    [batch] = await _events(db_session, "ticket.children_created", parent["id"])
    rule = rules["ticket.children_created"]
    assert rule_matches_event(rule, batch)
    audience = {m.user_id for m in await resolve_audience(db_session, batch, rule.audience)}
    assert audience == {w.requester.id}
    everyone = {m.user_id for m in await resolve_audience(db_session, batch, rule.audience, exclude_actor=False)}
    assert everyone == {w.requester.id, opener.id}


async def test_child_events_reach_requester_and_creator_of_the_parent(client: AsyncClient, db_session: AsyncSession):
    from app.notifications.audience import resolve_audience
    from app.notifications.rules_seed import DEFAULT_RULES

    w = await _world(db_session)
    opener = await make_user(db_session, await make_employee(db_session, w.org))
    parent = await _open(
        client, w, [_child(w.cat_b), _child(w.cat_c)], headers=_h(opener, ON_BEHALF),
        requester_id=str(w.requester_emp.id),
    )
    child_b = await _child_of(db_session, parent["id"], w.sector_b)
    child_c = await _child_of(db_session, parent["id"], w.sector_c)
    assert await _resolve(client, child_b.id, _att(w.att_b)) == 200
    assert (await client.post(f"{API}/{child_c.id}/cancel", json={"reason": REASON}, headers=_att(w.att_c))).status_code == 200

    audiences = {spec["code"]: spec["audience"] for spec in DEFAULT_RULES}
    for event_type in ("ticket.child_completed", "ticket.child_canceled"):
        [event] = await _events(db_session, event_type, parent["id"])
        members = {m.user_id for m in await resolve_audience(db_session, event, audiences[event_type])}
        assert {w.requester.id, opener.id} <= members
    [canceled] = await _events(db_session, "ticket.canceled", child_c.id)
    members = {m.user_id for m in await resolve_audience(db_session, canceled, audiences["ticket.canceled"])}
    assert members == set()  # o único atendente do setor C foi quem cancelou (o motor não avisa o autor)


# --- 13. SLA do filho cancelado ------------------------------------------------------------------------------


async def test_canceled_child_cycle_leaves_the_indicators(client: AsyncClient, db_session: AsyncSession):
    from app.sla.models import TicketSlaCycle
    from app.sla.report import sla_report
    from tests.sla.support import make_policy

    w = await _world(db_session)
    policy = await make_policy(db_session)
    w.cat_b.sla_policy_id = policy.id
    await db_session.commit()
    parent = await _open(client, w, [_child(w.cat_b)])
    child_b = await _child_of(db_session, parent["id"], w.sector_b)
    resp = await client.post(f"{API}/{child_b.id}/cancel", json={"reason": REASON}, headers=_att(w.att_b))
    assert resp.json()["sla"]["state"] == "CANCELED"
    cycle = (await db_session.execute(select(TicketSlaCycle).where(TicketSlaCycle.ticket_id == child_b.id))).scalar_one()
    assert cycle.state == "CANCELED"
    report = await sla_report(db_session)
    assert report.total.met == 0 and report.total.breached == 0 and report.open == 0


# --- 5. Concorrência real: incluir filhos x encerrar o principal ---------------------------------------------


@pytest.mark.pg
async def test_adding_children_and_closing_parent_are_serialized():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.access import AccessContext
    from app.core.exceptions import AppException
    from app.database import Base
    from app.service_desk.schemas import ChildTicketSpec, TicketCreate, TicketUpdate
    from app.service_desk.services import ServiceDeskService

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as db:
            w = await _world(db)
            ctx = AccessContext(
                user_id=w.att_p.id, is_admin=False, permissions=frozenset({MANAGE}),
                employee_id=w.att_p.employee_id, sector_id=w.org.sector.id,
            )

        async def new_parent() -> uuid.UUID:
            async with maker() as db:
                parent = await ServiceDeskService(db).create_ticket(
                    TicketCreate(title="P", description="d", category_id=w.cat_parent.id),
                    requester_id=w.requester_emp.id, origin_unit_id=w.org.unit.id,
                    origin_sector_id=w.org.sector.id, user_id=w.requester.id,
                )
                await db.commit()
                return parent.id

        async def close(parent_id: uuid.UUID, gate: asyncio.Event | None = None) -> str:
            async with maker() as db:
                try:
                    await ServiceDeskService(db).update_ticket(
                        parent_id, TicketUpdate(status="RESOLVED"), is_technician=True,
                        user_employee_id=ctx.employee_id, user_id=ctx.user_id, sector_id=ctx.sector_id,
                    )
                    if gate is not None:
                        await gate.wait()  # segura a trava até o outro lado tentar
                    await db.commit()
                    return "ok"
                except AppException as exc:
                    await db.rollback()
                    return str(exc.status_code)

        async def add(parent_id: uuid.UUID, gate: asyncio.Event | None = None) -> str:
            async with maker() as db:
                try:
                    await ServiceDeskService(db).add_children(
                        parent_id, [ChildTicketSpec(category_id=w.cat_b.id, title="E", description="d")], ctx
                    )
                    if gate is not None:
                        await gate.wait()
                    await db.commit()
                    return "ok"
                except AppException as exc:
                    await db.rollback()
                    return str(exc.status_code)

        async def race(first, second, parent_id: uuid.UUID) -> tuple[str, str]:
            gate = asyncio.Event()
            holder = asyncio.create_task(first(parent_id, gate))
            await asyncio.sleep(0.3)  # o primeiro já travou a linha do principal
            waiter = asyncio.create_task(second(parent_id))
            await asyncio.sleep(0.3)
            assert not waiter.done(), "o segundo devia esperar a trava do principal"
            gate.set()
            return await holder, await waiter

        # Inclusão primeiro: o encerramento espera e depois vê a etapa nova pendente.
        parent_id = await new_parent()
        assert await race(add, close, parent_id) == ("ok", "400")
        # Encerramento primeiro: a inclusão espera e depois vê o principal resolvido.
        parent_id = await new_parent()
        assert await race(close, add, parent_id) == ("ok", "409")

        async with maker() as db:
            pending = await db.execute(
                select(func.count(Ticket.id)).where(
                    Ticket.parent_ticket_id == parent_id,
                )
            )
            assert pending.scalar_one() == 0
    finally:
        await engine.dispose()


# --- Migration -----------------------------------------------------------------------------------------------


@pytest.mark.pg
@pytest.mark.migrations
async def test_migration_adds_link_columns_and_only_touches_the_unedited_rule():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    url = os.environ["TEST_DATABASE_URL"]
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    backend = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    os.environ["DATABASE_URL"] = url
    loop = asyncio.get_running_loop()

    async def move(action, rev: str) -> None:
        await loop.run_in_executor(None, action, cfg, rev)

    async def condition() -> dict:
        async with engine.connect() as conn:
            value = (await conn.execute(text(
                "SELECT condition FROM notification_rules WHERE code = 'ticket.created.requester'"
            ))).scalar_one()
            return value if isinstance(value, dict) else json.loads(value)

    async def columns() -> set[str]:
        async with engine.connect() as conn:
            rows = await conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'sd_ticket'"
            ))
            return set(rows.scalars())

    try:
        await move(command.upgrade, "f7a8b9c0d1e2f")
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO notification_rules (id, code, name, event_type, condition, audience, channels, "
                "template_code) VALUES (gen_random_uuid(), 'ticket.created.requester', 'r', 'ticket.created', "
                "'{\"exclude_actor\": false}'::jsonb, '[\"requester\"]'::jsonb, '[\"in_app\"]'::jsonb, 't')"
            ))

        await move(command.upgrade, "a9b0c1d2e3f4a")
        assert {"parent_ticket_id", "is_required", "replaces_ticket_id"} <= await columns()
        assert await condition() == {"exclude_actor": False, "payload_equals": {"parent_ticket_id": None}}

        await move(command.downgrade, "f7a8b9c0d1e2f")
        assert not {"parent_ticket_id", "is_required", "replaces_ticket_id"} & await columns()
        assert await condition() == {"exclude_actor": False}

        # Regra editada pelo administrador: a migration não mexe.
        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE notification_rules SET condition = '{\"min_priority\": \"HIGH\"}'::jsonb "
                "WHERE code = 'ticket.created.requester'"
            ))
        await move(command.upgrade, "a9b0c1d2e3f4a")
        assert await condition() == {"min_priority": "HIGH"}
    finally:
        await engine.dispose()