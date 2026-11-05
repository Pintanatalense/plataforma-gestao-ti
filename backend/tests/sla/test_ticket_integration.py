"""SLA ligado aos chamados (ADR-017, P4-S2): ciclo na criação, primeira resposta, pausa, resolução, reabertura,
prioridade, categoria e janela de reabertura. O relógio é controlado (`clock`), sempre numa segunda-feira de manhã.

Calendário: segunda a sexta, 08:00-18:00 em America/Sao_Paulo (UTC-3).
"""

from datetime import datetime, timedelta, timezone

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.service_desk.models import Ticket
from app.sla.models import SlaBreach, SlaPolicyTarget, TicketSlaCycle
from app.sla.service import SlaService
from tests.factories import make_ticket_category
from tests.sla.support import MONDAY_11H, Clock, World, as_utc, make_policy, open_ticket, patch, same, sla_of, utc

pytestmark = pytest.mark.asyncio


# --- Início ---------------------------------------------------------------------------------------


async def test_category_without_policy_or_with_inactive_policy_has_no_clock(client: AsyncClient, db_session: AsyncSession, world: World):
    plain = await make_ticket_category(db_session, world.org.sector)
    ticket = await open_ticket(client, world, category=plain)
    assert (await sla_of(client, world, ticket))["state"] == "NOT_APPLICABLE"

    world.policy.is_active = False
    await db_session.commit()
    ticket = await open_ticket(client, world)
    sla = await sla_of(client, world, ticket)
    assert sla["state"] == "NOT_APPLICABLE" and sla["first_response_due_at"] is None
    assert (await db_session.execute(select(TicketSlaCycle))).scalars().all() == []


async def test_ticket_opens_a_running_cycle_with_business_deadlines(client: AsyncClient, world: World):
    ticket = await open_ticket(client, world)
    sla = await sla_of(client, world, ticket)
    assert (sla["state"], sla["cycle"], sla["priority"], sla["policy_name"]) == ("RUNNING", 1, "HIGH", "Padrão")
    assert same(sla["first_response_due_at"], utc(26, 12))  # 11:00 + 60 min
    assert same(sla["resolution_due_at"], utc(27, 9))  # 11:00 + 8 h úteis: segunda 7 h + terça 1 h
    listed = (await client.get("/api/v1/tickets", headers=world.h_att)).json()
    assert listed[0]["sla"]["state"] == "RUNNING"


async def test_policy_that_does_not_cover_the_priority_gives_no_clock(client: AsyncClient, db_session: AsyncSession, world: World):
    narrow = await make_policy(db_session, name="So alta", targets={"HIGH": (60, 480)})
    world.category.sla_policy_id = narrow.id
    await db_session.commit()
    ticket = await open_ticket(client, world, priority="LOW")
    assert (await sla_of(client, world, ticket))["state"] == "NOT_APPLICABLE"


async def test_editing_the_policy_afterwards_does_not_change_the_open_cycle(client: AsyncClient, db_session: AsyncSession, world: World):
    ticket = await open_ticket(client, world)
    await db_session.execute(update(SlaPolicyTarget).values(resolution_minutes=1))
    world.policy.is_active = False
    await db_session.commit()
    sla = await sla_of(client, world, ticket)
    assert same(sla["resolution_due_at"], utc(27, 9)) and sla["state"] == "RUNNING"


# --- Primeira resposta ----------------------------------------------------------------------------


async def test_only_a_public_reply_from_someone_else_is_the_first_response(client: AsyncClient, world: World):
    ticket = await open_ticket(client, world)
    url = f"/api/v1/tickets/{ticket}/interactions"
    clock_note = await client.post(url, json={"message": "nota", "is_internal": True}, headers=world.h_att)
    assert clock_note.status_code == 201
    assert (await sla_of(client, world, ticket))["first_response_at"] is None  # nota interna não conta

    assert (await client.post(url, json={"message": "ainda sem rede", "is_internal": False}, headers=world.h_req)).status_code == 201
    assert (await sla_of(client, world, ticket))["first_response_at"] is None  # o solicitante falando sozinho não conta

    assert (await client.post(url, json={"message": "Olá, já olhando", "is_internal": False}, headers=world.h_att)).status_code == 201
    sla = await sla_of(client, world, ticket)
    assert same(sla["first_response_at"], MONDAY_11H) and sla["breaches"] == []


async def test_a_late_first_response_registers_the_breach_but_keeps_the_cycle_running(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    ticket = await open_ticket(client, world)
    clock.set(utc(26, 12, 1))  # 1 minuto depois do prazo de 12:00
    await client.post(f"/api/v1/tickets/{ticket}/interactions", json={"message": "oi", "is_internal": False}, headers=world.h_att)
    sla = await sla_of(client, world, ticket)
    assert sla["state"] == "RUNNING" and sla["breaches"] == ["FIRST_RESPONSE"]
    breach = (await db_session.execute(select(SlaBreach))).scalar_one()
    assert breach.kind == "FIRST_RESPONSE" and as_utc(breach.due_at) == utc(26, 12)


async def test_first_response_exactly_at_the_deadline_is_on_time(client: AsyncClient, world: World, clock: Clock):
    ticket = await open_ticket(client, world)
    clock.set(utc(26, 12))
    await client.post(f"/api/v1/tickets/{ticket}/interactions", json={"message": "oi", "is_internal": False}, headers=world.h_att)
    assert (await sla_of(client, world, ticket))["breaches"] == []


async def test_status_note_from_the_attendant_counts_as_first_response(client: AsyncClient, world: World):
    ticket = await open_ticket(client, world)
    sla = await patch(client, world, ticket, status="IN_PROGRESS", notes="Assumi o chamado")
    assert same(sla["first_response_at"], MONDAY_11H)


# --- Pausa e retomada -----------------------------------------------------------------------------


async def test_pause_stops_the_clock_and_resume_pushes_the_deadlines(client: AsyncClient, world: World, clock: Clock):
    ticket = await open_ticket(client, world)
    clock.set(utc(26, 11, 30))
    sla = await patch(client, world, ticket, status="PENDING")
    assert sla["state"] == "PAUSED" and sla["paused"] is True
    assert sla["first_response_due_at"] is None and sla["resolution_due_at"] is None  # sem vencimento enquanto pausado

    clock.set(utc(26, 13, 30))  # 2 h úteis depois
    sla = await patch(client, world, ticket, status="IN_PROGRESS")
    assert sla["state"] == "RUNNING"
    assert same(sla["first_response_due_at"], utc(26, 14))  # faltavam 30 min
    assert same(sla["resolution_due_at"], utc(27, 11))  # 09:00 de terça + as 2 h paradas


async def test_pause_over_the_weekend_only_counts_business_time(client: AsyncClient, world: World, clock: Clock):
    ticket = await open_ticket(client, world)
    clock.set(utc(26, 17))  # segunda 17:00 (6 h consumidas, faltam 2 h)
    await patch(client, world, ticket, status="PENDING")
    clock.set(utc(30, 8))  # sexta... mas vamos retomar na segunda seguinte 08:00
    clock.set(utc(11 + 20, 8)) if False else None
    clock.set(datetime(2026, 11, 2, 8, 0, tzinfo=timezone(timedelta(hours=-3))).astimezone(timezone.utc))
    sla = await patch(client, world, ticket, status="IN_PROGRESS")
    assert same(sla["resolution_due_at"], datetime(2026, 11, 2, 10, 0, tzinfo=timezone(timedelta(hours=-3))).astimezone(timezone.utc))


async def test_opened_status_never_pauses_and_non_pause_changes_keep_running(client: AsyncClient, world: World):
    ticket = await open_ticket(client, world)
    sla = await patch(client, world, ticket, status="IN_PROGRESS")
    assert sla["state"] == "RUNNING" and same(sla["resolution_due_at"], utc(27, 9))


async def test_policy_can_pause_on_in_progress_too(client: AsyncClient, db_session: AsyncSession, world: World):
    both = await make_policy(db_session, name="Pausa dupla", pause=["PENDING", "IN_PROGRESS"])
    world.category.sla_policy_id = both.id
    await db_session.commit()
    ticket = await open_ticket(client, world)
    assert (await patch(client, world, ticket, status="IN_PROGRESS"))["state"] == "PAUSED"
    assert (await patch(client, world, ticket, status="OPENED"))["state"] == "RUNNING"


# --- Resolução ------------------------------------------------------------------------------------


async def test_resolving_on_time_is_met_and_exactly_at_the_deadline_still_is(client: AsyncClient, world: World, clock: Clock):
    first = await open_ticket(client, world)
    clock.set(utc(26, 15))
    sla = await patch(client, world, first, status="RESOLVED")
    assert sla["state"] == "BREACHED" or sla["state"] == "MET"  # só a primeira resposta estava vencida (12:00)
    assert "RESOLUTION" not in sla["breaches"]

    second = await open_ticket(client, world)
    clock.set(utc(27, 9))  # prazo de resolução cravado
    await client.post(f"/api/v1/tickets/{second}/interactions", json={"message": "ok", "is_internal": False}, headers=world.h_att)
    sla = await patch(client, world, second, status="RESOLVED")
    assert sla["state"] == "BREACHED" and sla["breaches"] == ["FIRST_RESPONSE"]  # resposta às 09:00 de terça passou das 12:00 de segunda


async def test_resolution_exactly_at_the_deadline_with_a_timely_response_is_met(client: AsyncClient, world: World, clock: Clock):
    ticket = await open_ticket(client, world)
    await client.post(f"/api/v1/tickets/{ticket}/interactions", json={"message": "ok", "is_internal": False}, headers=world.h_att)
    clock.set(utc(27, 9))
    sla = await patch(client, world, ticket, status="RESOLVED")
    assert sla["state"] == "MET" and sla["breaches"] == [] and same(sla["resolved_at"], utc(27, 9))


async def test_resolving_one_minute_late_is_breached(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    ticket = await open_ticket(client, world)
    await client.post(f"/api/v1/tickets/{ticket}/interactions", json={"message": "ok", "is_internal": False}, headers=world.h_att)
    clock.set(utc(27, 9, 1))
    sla = await patch(client, world, ticket, status="RESOLVED")
    assert sla["state"] == "BREACHED" and sla["breaches"] == ["RESOLUTION"]
    breach = (await db_session.execute(select(SlaBreach))).scalar_one()
    assert as_utc(breach.due_at) == utc(27, 9) and as_utc(breach.detected_at) == utc(27, 9, 1)


async def test_resolved_while_paused_is_not_a_breach_however_long_the_pause(client: AsyncClient, world: World, clock: Clock):
    ticket = await open_ticket(client, world)
    await client.post(f"/api/v1/tickets/{ticket}/interactions", json={"message": "ok", "is_internal": False}, headers=world.h_att)
    clock.set(utc(26, 12))
    await patch(client, world, ticket, status="PENDING")
    clock.set(datetime(2026, 11, 9, 14, 0, tzinfo=timezone.utc))  # duas semanas depois
    sla = await patch(client, world, ticket, status="RESOLVED")
    assert sla["state"] == "MET" and sla["breaches"] == []


async def test_closing_a_resolved_ticket_keeps_the_final_result(client: AsyncClient, world: World, clock: Clock):
    ticket = await open_ticket(client, world)
    await client.post(f"/api/v1/tickets/{ticket}/interactions", json={"message": "ok", "is_internal": False}, headers=world.h_att)
    clock.set(utc(26, 15))
    first = await patch(client, world, ticket, status="RESOLVED")
    clock.set(utc(28, 15))
    closed = await patch(client, world, ticket, status="CLOSED")
    assert (closed["state"], closed["resolved_at"]) == (first["state"], first["resolved_at"])


async def test_closing_directly_without_resolving_ends_the_cycle(client: AsyncClient, world: World, clock: Clock):
    ticket = await open_ticket(client, world)
    await client.post(f"/api/v1/tickets/{ticket}/interactions", json={"message": "ok", "is_internal": False}, headers=world.h_att)
    clock.set(utc(26, 15))
    assert (await patch(client, world, ticket, status="CLOSED"))["state"] == "MET"


# --- Reabertura -----------------------------------------------------------------------------------


async def _resolved(client: AsyncClient, w: World, clock: Clock, at: datetime):
    ticket = await open_ticket(client, w)
    await client.post(f"/api/v1/tickets/{ticket}/interactions", json={"message": "ok", "is_internal": False}, headers=w.h_att)
    clock.set(at)
    await patch(client, w, ticket, status="RESOLVED")
    return ticket


async def test_reopen_restart_opens_a_new_resolution_only_cycle(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    ticket = await _resolved(client, world, clock, utc(26, 15))
    clock.set(utc(27, 10))
    sla = await patch(client, world, ticket, status="OPENED")
    assert (sla["state"], sla["cycle"]) == ("RUNNING", 2)
    assert sla["first_response_due_at"] is None and sla["first_response_at"] is not None  # a primeira resposta não se reaplica
    assert same(sla["resolution_due_at"], utc(27, 18))  # 8 h úteis a partir de terça 10:00 -> 18:00
    cycles = list((await db_session.execute(select(TicketSlaCycle).order_by(TicketSlaCycle.cycle))).scalars())
    assert [c.state for c in cycles] == ["MET", "RUNNING"]
    events = (await db_session.execute(select(AuditLog.event_type).where(AuditLog.event_type == "ticket.sla_reopened"))).scalars().all()
    assert len(events) == 1


async def test_reopen_continue_resumes_the_same_cycle_with_the_remaining_time(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    cont = await make_policy(db_session, name="Continua", reopen="CONTINUE")
    world.category.sla_policy_id = cont.id
    await db_session.commit()
    ticket = await _resolved(client, world, clock, utc(26, 12))  # faltavam 7 h úteis (prazo terça 09:00)
    clock.set(utc(27, 10))  # reabre na terça às 10:00
    sla = await patch(client, world, ticket, status="IN_PROGRESS")
    assert (sla["state"], sla["cycle"], sla["resolved_at"]) == ("RUNNING", 1, None)
    assert same(sla["resolution_due_at"], utc(27, 17))  # 7 h úteis a partir de terça 10:00 = terça 17:00


async def test_reopen_to_a_pause_status_is_born_paused(client: AsyncClient, world: World, clock: Clock):
    ticket = await _resolved(client, world, clock, utc(26, 15))
    clock.set(utc(27, 10))
    sla = await patch(client, world, ticket, status="PENDING")
    assert sla["state"] == "PAUSED" and sla["resolution_due_at"] is None


async def test_reopen_window_blocks_late_reopening_except_for_admins(client: AsyncClient, world: World, clock: Clock):
    ticket = await _resolved(client, world, clock, utc(26, 15))
    clock.set(utc(26, 15) + timedelta(days=3, minutes=1))
    late = await client.patch(f"/api/v1/tickets/{ticket}", json={"status": "OPENED"}, headers=world.h_att)
    assert late.status_code == 422 and "reabrir" in late.text
    assert (await client.get(f"/api/v1/tickets/{ticket}", headers=world.h_att)).json()["status"] == "RESOLVED"

    clock.set(utc(26, 15) + timedelta(days=3))  # no limite exato ainda vale
    assert (await client.patch(f"/api/v1/tickets/{ticket}", json={"status": "OPENED"}, headers=world.h_att)).status_code == 200

    other = await _resolved(client, world, clock, utc(26, 15))
    clock.set(utc(26, 15) + timedelta(days=30))
    assert (await client.patch(f"/api/v1/tickets/{other}", json={"status": "OPENED"}, headers=world.h_admin)).status_code == 200


async def test_reopen_window_also_applies_to_tickets_without_sla(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    plain = await make_ticket_category(db_session, world.org.sector)
    ticket = await open_ticket(client, world, category=plain)
    assert (await client.patch(f"/api/v1/tickets/{ticket}", json={"status": "RESOLVED"}, headers=world.h_att)).status_code == 200
    clock.set(datetime.now(timezone.utc) + timedelta(days=4))  # a auditoria usa a hora real da resolução
    late = await client.patch(f"/api/v1/tickets/{ticket}", json={"status": "IN_PROGRESS"}, headers=world.h_att)
    assert late.status_code == 422
    clock.set(datetime.now(timezone.utc) + timedelta(hours=1))
    assert (await client.patch(f"/api/v1/tickets/{ticket}", json={"status": "IN_PROGRESS"}, headers=world.h_att)).status_code == 200


# --- Prioridade -----------------------------------------------------------------------------------


async def test_priority_change_recalculates_discounting_what_was_consumed(client: AsyncClient, world: World, clock: Clock):
    ticket = await open_ticket(client, world)  # HIGH: resolução 480 min
    clock.set(utc(26, 12))  # 60 min consumidos
    sla = await patch(client, world, ticket, priority="CRITICAL")  # alvo 240 -> faltam 180 min
    assert sla["priority"] == "CRITICAL" and same(sla["resolution_due_at"], utc(26, 15))
    # primeira resposta: alvo novo de 30 min e já se passaram 60: vencimento retroativo (11:30) e violação registrada na hora
    assert same(sla["first_response_due_at"], utc(26, 11, 30)) and sla["breaches"] == ["FIRST_RESPONSE"]


async def test_priority_change_to_an_already_exceeded_target_registers_the_breach_now(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    ticket = await open_ticket(client, world)
    clock.set(utc(27, 9))  # 480 min consumidos
    sla = await patch(client, world, ticket, priority="CRITICAL")  # alvo 240 já estourado
    assert sla["state"] == "RUNNING" and "RESOLUTION" in sla["breaches"]
    breach = (await db_session.execute(select(SlaBreach).where(SlaBreach.kind == "RESOLUTION"))).scalar_one()
    assert as_utc(breach.due_at) == utc(26, 15)  # retroativo: 11:00 + 240 min úteis
    # voltar para uma prioridade folgada não apaga a violação
    sla = await patch(client, world, ticket, priority="LOW")
    assert "RESOLUTION" in sla["breaches"]


async def test_priority_change_on_a_paused_cycle_only_adjusts_the_remaining_minutes(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    ticket = await open_ticket(client, world)
    clock.set(utc(26, 12))
    await patch(client, world, ticket, status="PENDING")
    sla = await patch(client, world, ticket, priority="CRITICAL")
    cycle = (await db_session.execute(select(TicketSlaCycle))).scalar_one()
    await db_session.refresh(cycle)
    assert sla["state"] == "PAUSED" and sla["resolution_due_at"] is None
    assert cycle.remaining_resolution_minutes == 180 and cycle.priority == "CRITICAL"


async def test_priority_change_after_resolution_does_not_touch_the_result(client: AsyncClient, world: World, clock: Clock):
    ticket = await _resolved(client, world, clock, utc(26, 15))
    before = await sla_of(client, world, ticket)
    after = await patch(client, world, ticket, priority="CRITICAL")
    assert after["state"] == before["state"] and after["priority"] == before["priority"]


# --- Categoria ------------------------------------------------------------------------------------


async def test_category_change_supersedes_and_restarts_from_the_original_start(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    fast = await make_policy(db_session, name="Rápida", targets={"HIGH": (30, 120)})
    other = await make_ticket_category(db_session, world.org.sector)
    other.sla_policy_id = fast.id
    await db_session.commit()
    ticket = await open_ticket(client, world)
    clock.set(utc(26, 12))  # 60 min consumidos
    sla = await patch(client, world, ticket, category_id=str(other.id))
    assert (sla["cycle"], sla["policy_name"], sla["state"]) == (2, "Rápida", "RUNNING")
    assert same(sla["resolution_due_at"], utc(26, 13))  # alvo 120 desde 11:00 -> 13:00
    assert same(sla["first_response_due_at"], utc(26, 11, 30))  # 30 min desde 11:00 já passaram: retroativo
    assert sla["breaches"] == ["FIRST_RESPONSE"]  # e a violação é registrada na hora da troca
    states = [c.state for c in (await db_session.execute(select(TicketSlaCycle).order_by(TicketSlaCycle.cycle))).scalars()]
    assert states == ["SUPERSEDED", "RUNNING"]
    assert (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "ticket.sla_cycle_superseded"))).scalar_one()


async def test_category_change_can_be_born_already_breached(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    fast = await make_policy(db_session, name="Rápida", targets={"HIGH": (30, 60)})
    other = await make_ticket_category(db_session, world.org.sector)
    other.sla_policy_id = fast.id
    await db_session.commit()
    ticket = await open_ticket(client, world)
    clock.set(utc(26, 14))  # 3 h úteis consumidas
    sla = await patch(client, world, ticket, category_id=str(other.id))
    assert sorted(sla["breaches"]) == ["FIRST_RESPONSE", "RESOLUTION"]


async def test_category_without_policy_ends_the_clock_as_not_applicable(client: AsyncClient, db_session: AsyncSession, world: World):
    plain = await make_ticket_category(db_session, world.org.sector)
    ticket = await open_ticket(client, world)
    sla = await patch(client, world, ticket, category_id=str(plain.id))
    assert sla["state"] == "NOT_APPLICABLE"
    assert [c.state for c in (await db_session.execute(select(TicketSlaCycle))).scalars()] == ["SUPERSEDED"]


async def test_category_with_the_same_policy_does_not_restart_the_clock(client: AsyncClient, db_session: AsyncSession, world: World):
    sibling = await make_ticket_category(db_session, world.org.sector)
    sibling.sla_policy_id = world.policy.id
    await db_session.commit()
    ticket = await open_ticket(client, world)
    sla = await patch(client, world, ticket, category_id=str(sibling.id))
    assert sla["cycle"] == 1 and sla["state"] == "RUNNING"


async def test_category_from_none_to_a_policy_starts_a_clock_from_the_creation(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    plain = await make_ticket_category(db_session, world.org.sector)
    ticket = await open_ticket(client, world, category=plain)
    created = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)
    await db_session.execute(update(Ticket).values(created_at=created))
    await db_session.commit()
    clock.set(utc(26, 12))
    sla = await patch(client, world, ticket, category_id=str(world.category.id))
    assert (sla["state"], sla["cycle"]) == ("RUNNING", 1)
    assert same(sla["resolution_due_at"], utc(27, 9))  # conta desde a abertura (11:00), não desde a troca


async def test_category_change_after_resolution_leaves_the_result_alone(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    ticket = await _resolved(client, world, clock, utc(26, 15))
    other = await make_ticket_category(db_session, world.org.sector)
    await db_session.commit()
    sla = await patch(client, world, ticket, category_id=str(other.id))
    assert sla["state"] in ("MET", "BREACHED") and sla["cycle"] == 1


# --- Idempotência -----------------------------------------------------------------------------------


async def test_breach_is_registered_once_per_cycle_and_kind(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    ticket = await open_ticket(client, world)
    cycle = (await db_session.execute(select(TicketSlaCycle))).scalar_one()
    service = SlaService(db_session)
    clock.set(utc(27, 12))
    for _ in range(3):
        await service._register_overdue(cycle, clock.now)
    await db_session.commit()
    kinds = sorted(b.kind for b in (await db_session.execute(select(SlaBreach))).scalars())
    assert kinds == ["FIRST_RESPONSE", "RESOLUTION"]
    assert (await sla_of(client, world, ticket))["breaches"] == ["FIRST_RESPONSE", "RESOLUTION"]


async def test_resolved_at_falls_back_to_the_audit_trail_for_tickets_without_cycles(client: AsyncClient, db_session: AsyncSession, world: World):
    plain = await make_ticket_category(db_session, world.org.sector)
    ticket = await open_ticket(client, world, category=plain)
    row = (await db_session.execute(select(Ticket).where(Ticket.id == uuid.UUID(ticket)))).scalar_one()
    assert await SlaService(db_session).resolved_at(row) is None
    await patch(client, world, ticket, status="RESOLVED")
    assert await SlaService(db_session).resolved_at(row) is not None


# --- Revisão independente do P4-S2 ------------------------------------------------------------------


async def test_category_change_on_a_resolved_ticket_without_a_cycle_opens_no_clock(client: AsyncClient, db_session: AsyncSession, world: World):
    plain = await make_ticket_category(db_session, world.org.sector)
    ticket = await open_ticket(client, world, category=plain)
    await patch(client, world, ticket, status="RESOLVED")
    sla = await patch(client, world, ticket, category_id=str(world.category.id))
    assert sla["state"] == "NOT_APPLICABLE"
    assert (await db_session.execute(select(TicketSlaCycle))).scalars().all() == []
    # fechado também
    await patch(client, world, ticket, status="CLOSED")
    other = await make_ticket_category(db_session, world.org.sector)
    other.sla_policy_id = world.policy.id
    await db_session.commit()
    assert (await patch(client, world, ticket, category_id=str(other.id)))["state"] == "NOT_APPLICABLE"


async def test_after_restart_a_category_without_policy_leaves_no_clock_and_no_stale_resolution(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    ticket = await _resolved(client, world, clock, utc(26, 15))
    clock.set(utc(27, 10))
    await patch(client, world, ticket, status="OPENED")  # RESTART: ciclo 2
    plain = await make_ticket_category(db_session, world.org.sector)
    sla = await patch(client, world, ticket, category_id=str(plain.id))
    assert sla["state"] == "NOT_APPLICABLE"
    row = (await db_session.execute(select(Ticket).where(Ticket.id == uuid.UUID(ticket)))).scalar_one()
    assert await SlaService(db_session).resolved_at(row) is not None  # vem da auditoria, não do ciclo antigo


async def test_continue_reopen_without_any_response_does_not_breach_the_first_response_at_once(client: AsyncClient, db_session: AsyncSession, world: World, clock: Clock):
    cont = await make_policy(db_session, name="Continua2", reopen="CONTINUE")
    world.category.sla_policy_id = cont.id
    await db_session.commit()
    ticket = await open_ticket(client, world)  # sem nenhuma resposta
    clock.set(utc(26, 11, 30))  # 30 min consumidos dos 60 da primeira resposta
    await patch(client, world, ticket, status="RESOLVED")
    clock.set(utc(27, 10))
    sla = await patch(client, world, ticket, status="IN_PROGRESS")
    assert sla["breaches"] == [] and same(sla["first_response_due_at"], utc(27, 10, 30))  # faltavam 30 min


async def test_reopen_window_is_checked_before_any_field_is_changed(client: AsyncClient, world: World, clock: Clock):
    ticket = await _resolved(client, world, clock, utc(26, 15))
    clock.set(utc(26, 15) + timedelta(days=4))
    late = await client.patch(f"/api/v1/tickets/{ticket}", json={"status": "OPENED", "priority": "LOW"}, headers=world.h_att)
    assert late.status_code == 422
    current = (await client.get(f"/api/v1/tickets/{ticket}", headers=world.h_att)).json()
    assert current["priority"] == "HIGH" and current["status"] == "RESOLVED"
