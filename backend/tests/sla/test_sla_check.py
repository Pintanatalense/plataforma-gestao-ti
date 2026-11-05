"""Job `sla.check` (ADR-017, P4-S3): violação de quem ninguém tocou, alerta de proximidade e aviso de violação.

Política de teste: HIGH = 60 min de primeira resposta e 480 min de resolução, alerta em 80%. Chamado aberto segunda
11:00 (São Paulo): primeira resposta vence 12:00, alerta a partir de 11:48.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import Permission, Role, user_role_association
from app.identity.permission_catalog import sync_permission_catalog
from app.notifications.fanout import plan_event
from app.notifications.jobs import DEFAULT_JOBS, JOBS, job_sla_check
from app.notifications.models import DomainEvent, NotificationRule
from app.notifications.rules_seed import seed_notification_rules
from app.service_desk.models import Ticket
from app.sla.checker import check_sla
from app.sla.models import SlaBreach, TicketSlaCycle
from tests.sla.support import Clock, World, open_ticket, patch, utc

pytestmark = pytest.mark.asyncio


async def events(db: AsyncSession, event_type: str) -> list[DomainEvent]:
    rows = await db.execute(select(DomainEvent).where(DomainEvent.event_type == event_type).order_by(DomainEvent.created_at))
    return list(rows.scalars())


async def check(db: AsyncSession, at: datetime):
    result = await check_sla(db, at)
    await db.commit()
    return result


async def breaches(db: AsyncSession, ticket_id: str) -> list[SlaBreach]:
    rows = await db.execute(
        select(SlaBreach).join(TicketSlaCycle).where(TicketSlaCycle.ticket_id == uuid.UUID(ticket_id)).order_by(SlaBreach.kind)
    )
    return list(rows.scalars())


def as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


async def test_job_is_registered_every_five_minutes():
    assert DEFAULT_JOBS["sla.check"] == "every:5" and JOBS["sla.check"] is job_sla_check


async def test_untouched_ticket_gets_the_breach_and_one_notice(client: AsyncClient, db_session: AsyncSession, world: World):
    ticket = await open_ticket(client, world)

    assert (await check(db_session, utc(26, 12))).breaches == 0  # exatamente no vencimento ainda não violou
    result = await check(db_session, utc(26, 12, 1))
    assert (result.breaches, result.breach_notices) == (1, 1)
    [breach] = await breaches(db_session, ticket)
    assert breach.kind == "FIRST_RESPONSE" and as_utc(breach.due_at) == utc(26, 12)
    assert as_utc(breach.notified_at) == utc(26, 12, 1)
    [event] = await events(db_session, "ticket.sla_breached")
    assert event.payload["ticket_id"] == ticket and event.payload["kind"] == "FIRST_RESPONSE"
    assert event.payload["due_local"] == "26/10 12:00" and event.priority == "high"

    again = await check(db_session, utc(26, 12, 6))  # a próxima execução não repete nada
    assert (again.breaches, again.warnings, again.breach_notices) == (0, 0, 0)
    assert len(await events(db_session, "ticket.sla_breached")) == 1


async def test_resolution_breach_is_also_detected_and_the_cycle_keeps_running(client: AsyncClient, db_session: AsyncSession, world: World):
    ticket = await open_ticket(client, world)
    await check(db_session, utc(27, 11, 1))  # 480 min úteis depois: terça 11:00
    assert [b.kind for b in await breaches(db_session, ticket)] == ["FIRST_RESPONSE", "RESOLUTION"]
    cycle = (await db_session.execute(select(TicketSlaCycle).where(TicketSlaCycle.ticket_id == uuid.UUID(ticket)))).scalar_one()
    assert cycle.state == "RUNNING"  # o resultado final só sai na resolução
    assert len(await events(db_session, "ticket.sla_breached")) == 2


async def test_warning_fires_once_at_the_alert_percent(client: AsyncClient, db_session: AsyncSession, world: World):
    await open_ticket(client, world)
    assert (await check(db_session, utc(26, 11, 47))).warnings == 0  # 47 de 60 min: 78%
    assert (await check(db_session, utc(26, 11, 48))).warnings == 1  # 48 de 60 min: 80%
    [event] = await events(db_session, "ticket.sla_warning")
    assert event.payload["kind"] == "FIRST_RESPONSE" and event.payload["due_local"] == "26/10 12:00"
    assert event.payload["assigned"] is False
    assert (await check(db_session, utc(26, 11, 55))).warnings == 0
    assert len(await events(db_session, "ticket.sla_warning")) == 1


async def test_answered_or_paused_tickets_are_left_alone(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    answered = await open_ticket(client, world)
    await patch(client, world, answered, status="IN_PROGRESS", notes="Assumi")
    paused = await open_ticket(client, world)
    await patch(client, world, paused, status="PENDING")  # pausa sem nota: não é resposta

    result = await check(db_session, utc(26, 17))
    assert result.breaches == 0
    assert await breaches(db_session, answered) == [] and await breaches(db_session, paused) == []
    warned = {e.payload["ticket_id"] for e in await events(db_session, "ticket.sla_warning")}
    assert paused not in warned and warned <= {answered}  # o respondido só pode ser alertado da resolução
    assert all(e.payload["kind"] == "RESOLUTION" for e in await events(db_session, "ticket.sla_warning"))


async def test_breach_registered_by_a_transition_is_announced_once(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    ticket = await open_ticket(client, world)
    clock.set(utc(26, 12, 30))
    url = f"/api/v1/tickets/{ticket}/interactions"
    assert (await client.post(url, json={"message": "Atrasado", "is_internal": False}, headers=world.h_att)).status_code == 201
    [breach] = await breaches(db_session, ticket)
    assert breach.notified_at is None

    assert (await check(db_session, utc(26, 12, 31))).breach_notices == 1
    assert (await check(db_session, utc(26, 12, 36))).breach_notices == 0
    assert len(await events(db_session, "ticket.sla_breached")) == 1


async def test_priority_change_rearms_the_warning(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    ticket = await open_ticket(client, world, priority="LOW")  # 480 min de primeira resposta
    await patch(client, world, ticket, priority="HIGH")
    assert (await check(db_session, utc(26, 11, 48))).warnings == 1
    clock.set(utc(26, 11, 50))
    await patch(client, world, ticket, priority="CRITICAL")  # 30 min: já estourou, violação na hora
    await patch(client, world, ticket, priority="HIGH")  # 60 min de novo: vence 12:00, alerta rearmado
    assert (await check(db_session, utc(26, 11, 51))).warnings == 1
    assert len(await events(db_session, "ticket.sla_warning")) == 2


async def test_continue_reopen_rearms_the_resolution_warning(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    world.policy.reopen_rule = "CONTINUE"
    await db_session.commit()
    ticket = await open_ticket(client, world)  # HIGH: resolução 480 min, vence terça 09:00; alerta a partir de seg 17:24
    await client.post(f"/api/v1/tickets/{ticket}/interactions", json={"message": "Vendo", "is_internal": False}, headers=world.h_att)
    assert (await check(db_session, utc(26, 17, 30))).warnings == 1
    clock.set(utc(26, 17, 40))
    await patch(client, world, ticket, status="RESOLVED")
    clock.set(utc(27, 8, 30))
    await patch(client, world, ticket, status="IN_PROGRESS")  # continua: faltavam 80 min, vence terça 09:50
    result = await check(db_session, utc(27, 8, 35))
    assert (result.warnings, result.breaches) == (1, 0)
    assert [e.payload["kind"] for e in await events(db_session, "ticket.sla_warning")] == ["RESOLUTION", "RESOLUTION"]


async def test_inactive_policy_does_not_stop_open_cycles(client: AsyncClient, db_session: AsyncSession, world: World):
    ticket = await open_ticket(client, world)
    world.policy.is_active = False
    await db_session.commit()
    assert (await check(db_session, utc(26, 12, 1))).breaches == 1
    assert len(await breaches(db_session, ticket)) == 1


async def _attendant_role(db: AsyncSession, *users) -> None:
    await sync_permission_catalog(db)
    perm = (await db.execute(select(Permission).where(Permission.code == "service_desk.tickets.manage"))).scalar_one()
    role = Role(name="Atendimento SLA", permissions=[perm])
    db.add(role)
    await db.flush()
    for user in users:
        await db.execute(user_role_association.insert().values(user_id=user.id, role_id=role.id))
    await db.commit()


async def _audience(db: AsyncSession, event: DomainEvent) -> set[uuid.UUID]:
    rules = list((await db.execute(select(NotificationRule).where(NotificationRule.event_type == event.event_type))).scalars())
    plans = await plan_event(db, event, rules, {"in_app"}, datetime.now(timezone.utc))
    return {p.user_id for p in plans}


async def test_warning_goes_to_the_assignee_or_to_the_sector_when_unassigned(client: AsyncClient, db_session: AsyncSession, world: World):
    await seed_notification_rules(db_session)
    await _attendant_role(db_session, world.attendant)
    unassigned = await open_ticket(client, world)
    assigned = await open_ticket(client, world)
    row = await db_session.get(Ticket, uuid.UUID(assigned))
    row.assignee_id = world.admin.id
    await db_session.commit()

    await check(db_session, utc(26, 11, 50))
    by_ticket = {e.payload["ticket_id"]: e for e in await events(db_session, "ticket.sla_warning")}
    assert await _audience(db_session, by_ticket[unassigned]) == {world.attendant.id}
    assert await _audience(db_session, by_ticket[assigned]) == {world.admin.id}


async def test_breach_notice_reaches_the_team(client: AsyncClient, db_session: AsyncSession, world: World):
    await seed_notification_rules(db_session)
    await _attendant_role(db_session, world.attendant)
    await open_ticket(client, world)
    await check(db_session, utc(26, 12, 1))
    [event] = await events(db_session, "ticket.sla_breached")
    assert world.attendant.id in await _audience(db_session, event)
