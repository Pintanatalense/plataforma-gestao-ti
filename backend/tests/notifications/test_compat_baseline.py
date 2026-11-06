"""Caracterização do hub antes da Central de Mensagens (ADR-025, etapa M0).

Congela o que as próximas etapas não podem mudar sem decisão explícita: para cada regra semeada, quem recebe e por
qual canal; e os campos das respostas do painel de entregas e de regras. Se um destes testes falhar numa etapa
seguinte, a mudança alterou comportamento existente: corrija o código ou registre a decisão no ADR antes de
atualizar o valor esperado.
"""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import Permission, Role, role_permission_association, user_role_association
from app.notifications.fanout import plan_event
from app.notifications.models import (
    Delivery,
    DeliveryAttempt,
    DomainEvent,
    NotificationRule,
    UserChannelAddress,
)
from app.notifications.rules_seed import seed_notification_rules
from tests.factories import headers_for, make_employee, make_org, make_user

pytestmark = pytest.mark.asyncio

ADMIN_BASE = "/api/v1/notifications/admin"
CHANNELS_ON = {"in_app", "email", "telegram"}


async def _grant(db: AsyncSession, user, role_name: str, permission_code: str | None = None) -> None:
    role = (await db.execute(select(Role).where(Role.name == role_name))).scalar_one_or_none()
    if role is None:
        role = Role(name=role_name)
        db.add(role)
        await db.flush()
        if permission_code:
            perm = (await db.execute(select(Permission).where(Permission.code == permission_code))).scalar_one_or_none()
            if perm is None:
                perm = Permission(code=permission_code)
                db.add(perm)
                await db.flush()
            await db.execute(role_permission_association.insert().values(role_id=role.id, permission_id=perm.id))
    await db.execute(user_role_association.insert().values(user_id=user.id, role_id=role.id))
    await db.commit()


@pytest.fixture
async def people(db_session: AsyncSession) -> dict:
    """Solicitante, dois atendentes do setor (um deles será o responsável), gestão e um superadministrador.
    Todos com Telegram vinculado, para exercitar o pseudo-canal `preferred`."""
    org = await make_org(db_session)
    found = {
        "requester": await make_user(db_session, await make_employee(db_session, org)),
        "attendant": await make_user(db_session, await make_employee(db_session, org)),
        "assignee": await make_user(db_session, await make_employee(db_session, org)),
        "manager": await make_user(db_session),
        "admin": await make_user(db_session, is_admin=True),
    }
    await _grant(db_session, found["attendant"], "Atendente", "service_desk.tickets.manage")
    await _grant(db_session, found["assignee"], "Atendente")
    await _grant(db_session, found["manager"], "Gestão")
    now = datetime.now(timezone.utc)
    for n, user in enumerate(found.values()):
        db_session.add(UserChannelAddress(user_id=user.id, channel="telegram", address=f"9000{n}", verified_at=now))
    await seed_notification_rules(db_session)
    await db_session.commit()
    found["sector_id"] = org.sector.id
    return found


def _ticket_payload(people: dict, assigned: bool = True, **extra) -> dict:
    return {
        "ticket_id": str(uuid.uuid4()),
        "title": "Sem rede",
        "priority": "HIGH",
        "status": "OPENED",
        "requester_employee_id": str(people["requester"].employee_id),
        "assignee_id": str(people["assignee"].id) if assigned else None,
        "assigned": assigned,  # só os eventos de SLA trazem este campo; nenhuma regra de chamado o lê
        "responsible_sector_id": str(people["sector_id"]),
        **extra,
    }


async def _routing(db: AsyncSession, people: dict, event_type: str, payload: dict, actor: str | None) -> set:
    rules = list((await db.execute(select(NotificationRule).where(NotificationRule.enabled.is_(True)))).scalars())
    event = DomainEvent(
        event_type=event_type, entity_type=event_type.split(".")[0], payload=payload,
        actor_user_id=people[actor].id if actor else None, priority="high",
    )
    db.add(event)
    await db.flush()
    label = {people[k].id: k for k in ("requester", "attendant", "assignee", "manager", "admin")}
    plans = await plan_event(db, event, rules, CHANNELS_ON, datetime.now(timezone.utc))
    return {(p.rule.code, label[p.user_id], p.channel) for p in plans}


def _each(code: str, who: str, channels: str) -> set:
    return {(code, who, channel) for channel in channels.split()}


async def test_seeded_rules_route_each_event_to_the_same_people_and_channels(db_session: AsyncSession, people):
    async def routing(event_type, payload, actor=None):
        return await _routing(db_session, people, event_type, payload, actor)

    assert await routing("ticket.created", _ticket_payload(people, assigned=False), actor="requester") == (
        _each("ticket.created.staff", "attendant", "in_app email telegram")
        | _each("ticket.created.staff", "assignee", "in_app email telegram")
        | _each("ticket.created.requester", "requester", "in_app email telegram")
    )
    assert await routing("ticket.assigned", _ticket_payload(people), actor="attendant") == (
        _each("ticket.assigned.assignee", "assignee", "in_app email telegram")
        | _each("ticket.assigned.requester", "requester", "in_app telegram")
    )
    assert await routing("ticket.status_changed", _ticket_payload(people), actor="assignee") == (
        _each("ticket.status_changed", "requester", "in_app telegram")
    )
    public = _ticket_payload(people, is_internal=False)
    assert await routing("ticket.interaction_added", public, actor="assignee") == (
        _each("ticket.interaction_added", "requester", "in_app email telegram")
    )
    assert await routing("ticket.interaction_added", public, actor="requester") == (
        _each("ticket.interaction_added", "assignee", "in_app email telegram")
    )
    internal = _ticket_payload(people, is_internal=True)
    assert await routing("ticket.interaction_added", internal, actor="attendant") == (
        _each("ticket.interaction_added", "assignee", "in_app email telegram")
    )

    assert await routing("ticket.sla_warning", _ticket_payload(people, assigned=True)) == (
        _each("ticket.sla_warning.assignee", "assignee", "in_app telegram")
    )
    assert await routing("ticket.sla_warning", _ticket_payload(people, assigned=False)) == (
        _each("ticket.sla_warning.sector", "attendant", "in_app telegram")
        | _each("ticket.sla_warning.sector", "assignee", "in_app telegram")
    )
    assert await routing("ticket.sla_breached", _ticket_payload(people, assigned=True)) == (
        _each("ticket.sla_breached", "assignee", "in_app email telegram")
        | _each("ticket.sla_breached", "attendant", "in_app email telegram")
        | _each("ticket.sla_breached", "manager", "in_app email telegram")
    )

    assert await routing("backup.failed", {"error": "x"}) == _each("backup.failed", "admin", "in_app email telegram")
    assert await routing("backup.completed", {}) == set()  # regra semeada desligada
    assert await routing("stock.below_minimum", {"items": []}) == (
        _each("stock.below_minimum", "admin", "in_app email telegram")
        | _each("stock.below_minimum", "manager", "in_app email telegram")
    )
    assert await routing("asset.warranty_expiring", {"items": []}) == (
        _each("asset.warranty_expiring", "admin", "in_app email telegram")
        | _each("asset.warranty_expiring", "manager", "in_app email telegram")
    )
    assert await routing("identity.critical_changed", {}, actor="admin") == (
        _each("identity.critical_changed", "admin", "in_app email")
    )
    assert await routing("audit.integrity_failed", {}) == _each("audit.integrity_failed", "admin", "in_app email")
    assert await routing("channel.degraded", {"channel": "email"}) == _each("channel.degraded", "admin", "in_app email")

    # Ganharam regra semeada no M5 do ADR-025 (antes não iam a ninguém).
    assert await routing("ticket.asset_delivered", _ticket_payload(people), actor="attendant") == (
        _each("ticket.asset_delivered.requester", "requester", "in_app email telegram")
    )
    assert await routing("ticket.asset_returned", _ticket_payload(people), actor="assignee") == (
        _each("ticket.asset_returned.sector", "attendant", "in_app")
    )
    assert await routing("job.failed", {"job": "sla.check"}) == _each("job.failed", "admin", "in_app email")


async def test_unverified_address_and_disabled_channel_never_receive(db_session: AsyncSession, people):
    address = (
        await db_session.execute(select(UserChannelAddress).where(UserChannelAddress.user_id == people["admin"].id))
    ).scalar_one()
    address.verified_at = None
    await db_session.commit()
    routed = await _routing(db_session, people, "backup.failed", {"error": "x"}, None)
    assert routed == _each("backup.failed", "admin", "in_app email")

    rules = list((await db_session.execute(select(NotificationRule).where(NotificationRule.enabled.is_(True)))).scalars())
    event = DomainEvent(event_type="backup.failed", entity_type="backup", payload={}, priority="high")
    db_session.add(event)
    await db_session.flush()
    only_in_app = await plan_event(db_session, event, rules, {"in_app"}, datetime.now(timezone.utc))
    assert {p.channel for p in only_in_app} == {"in_app"}


# --- Forma das respostas usadas pelas telas ------------------------------------------------------

DELIVERY_FIELDS = {
    "id", "event_id", "event_type", "channel", "status", "priority", "recipient_email", "address", "title",
    "attempts", "max_attempts", "last_error", "next_attempt_at", "created_at", "sent_at",
    # M1: campos acrescentados (nenhum removido ou renomeado)
    "provider_status", "provider_status_at", "origin",
}


async def test_deliveries_listing_and_detail_keep_their_fields(client: AsyncClient, db_session: AsyncSession, people):
    admin = people["admin"]
    event = DomainEvent(event_type="ticket.created", entity_type="ticket", payload={"a": 1},
                        fanned_out_at=datetime.now(timezone.utc))
    db_session.add(event)
    await db_session.flush()
    delivery = Delivery(
        event_id=event.id, recipient_user_id=admin.id, channel="email", address=admin.email, status="DEAD",
        message={"title": "Olá", "body_text": "b"}, idempotency_key=uuid.uuid4().hex, attempts=1, last_error="boom",
    )
    db_session.add(delivery)
    await db_session.flush()
    db_session.add(DeliveryAttempt(delivery_id=delivery.id, attempt_no=1, started_at=datetime.now(timezone.utc),
                                   finished_at=datetime.now(timezone.utc), outcome="permanent", error="boom"))
    await db_session.commit()
    h = headers_for(admin, "notifications.manage")

    listing = (await client.get(f"{ADMIN_BASE}/deliveries", headers=h)).json()
    assert set(listing) == {"total", "items"}
    assert set(listing["items"][0]) == DELIVERY_FIELDS

    detail = (await client.get(f"{ADMIN_BASE}/deliveries/{delivery.id}", headers=h)).json()
    assert set(detail) == DELIVERY_FIELDS | {"attempt_log", "event_payload"}
    assert set(detail["attempt_log"][0]) == {"attempt_no", "started_at", "finished_at", "outcome", "error"}


async def test_rules_listing_keeps_its_fields(client: AsyncClient, people):
    listing = (await client.get(f"{ADMIN_BASE}/rules", headers=headers_for(people["admin"], "notifications.manage"))).json()
    assert {"items", "options"} <= set(listing)
    assert set(listing["items"][0]) == {
        "id", "code", "is_system", "name", "enabled", "event_type", "condition", "audience", "channels", "template_code",
        "escalation", "fallback_channel", "in_catalog",  # acrescentados no M5 (ADR-025)
    }
    assert {"channels"} <= set(listing["options"])
