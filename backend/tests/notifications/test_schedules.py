"""Agendamento de mensagens (ADR-025 M4): recorrência, dia útil e feriado, idempotência na criação e na ocorrência,
tolerância após parada, permissão e setor reavaliados a cada ocorrência, pausa, retomada, cancelamento e edição
concorrente."""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.identity.models import Permission, Role, role_permission_association, user_role_association
from app.notifications import schedules as sched
from app.notifications.channel_store import save_channel
from app.notifications.models import Delivery, MessageSchedule, OutboundMessage
from app.organization.models import Employee
from app.sla.business_time import BusinessCalendar
from tests.factories import headers_for, make_employee, make_org, make_user

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/notifications/messages/schedules"
SCHEDULE = "notifications.messages.schedule"
SEND = "notifications.messages.send"
TZ = "America/Sao_Paulo"
BRT = timezone(timedelta(hours=-3))
WEEKDAYS_9_18 = {str(d): [["09:00", "18:00"]] for d in range(5)}


def local(y, m, d, hh=9, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=BRT).astimezone(timezone.utc)


def rule(kind="daily", **extra) -> sched.Recurrence:
    return sched.Recurrence(kind=kind, timezone_name=TZ, time_of_day=time(9, 0), **extra)


# --- Recorrência ----------------------------------------------------------------------------------


async def test_daily_weekly_and_monthly_occurrences():
    tuesday_10h = local(2026, 11, 3, 10)
    assert sched.next_occurrence(rule(), tuesday_10h) == local(2026, 11, 4)
    assert sched.next_occurrence(rule(), local(2026, 11, 3, 8)) == local(2026, 11, 3)
    weekly = rule("weekly", weekdays=frozenset({0, 2}))  # segunda e quarta
    assert sched.upcoming(weekly, tuesday_10h, 3) == [local(2026, 11, 4), local(2026, 11, 9), local(2026, 11, 11)]
    monthly = rule("monthly", month_day=31)  # mês curto: último dia
    assert sched.upcoming(monthly, local(2027, 1, 31, 10), 2) == [local(2027, 2, 28), local(2027, 3, 31)]


async def test_start_and_end_dates_bound_the_series_and_once_runs_a_single_time():
    bounded = rule(starts_on=date(2026, 11, 10), ends_on=date(2026, 11, 11))
    assert sched.upcoming(bounded, local(2026, 11, 1), 5) == [local(2026, 11, 10), local(2026, 11, 11)]
    once = sched.Recurrence(kind="once", timezone_name=TZ, run_at=local(2026, 11, 5, 14))
    assert sched.next_occurrence(once, local(2026, 11, 5, 13)) == local(2026, 11, 5, 14)
    assert sched.next_occurrence(once, local(2026, 11, 5, 14)) is None


async def test_business_calendar_skips_or_moves_non_working_days():
    calendar = BusinessCalendar.from_dict({"timezone": TZ, "weekly_hours": WEEKDAYS_9_18, "holidays": ["2026-11-20"]})
    friday_holiday = date(2026, 11, 20)
    skip = rule(calendar=calendar, non_business_rule="skip")
    assert sched.upcoming(skip, local(2026, 11, 19, 10), 2) == [local(2026, 11, 23), local(2026, 11, 24)]
    move = rule(calendar=calendar, non_business_rule="next")
    # sexta (feriado), sábado e domingo caem todos na segunda: uma ocorrência só
    assert sched.upcoming(move, local(2026, 11, 19, 10), 2) == [local(2026, 11, 23), local(2026, 11, 24)]
    saturday_only = rule("weekly", weekdays=frozenset({5}), calendar=calendar, non_business_rule="next")
    assert sched.next_occurrence(saturday_only, local(2026, 11, 22, 10)) == local(2026, 11, 23)  # sábado de ontem
    assert friday_holiday.weekday() == 4


# --- API ------------------------------------------------------------------------------------------


async def _grant(db: AsyncSession, user, *codes: str) -> None:
    role = Role(name=f"r-{uuid.uuid4().hex[:8]}")
    db.add(role)
    await db.flush()
    for code in codes:
        perm = (await db.execute(select(Permission).where(Permission.code == code))).scalar_one_or_none()
        if perm is None:
            perm = Permission(code=code)
            db.add(perm)
            await db.flush()
        await db.execute(role_permission_association.insert().values(role_id=role.id, permission_id=perm.id))
    await db.execute(user_role_association.insert().values(user_id=user.id, role_id=role.id))
    await db.commit()


@pytest.fixture
async def world(db_session: AsyncSession) -> SimpleNamespace:
    org = await make_org(db_session)
    author = await make_user(db_session, await make_employee(db_session, org))
    colleague = await make_user(db_session, await make_employee(db_session, org))
    other = await make_user(db_session, await make_employee(db_session, org))
    manager = await make_user(db_session, is_admin=True)
    await _grant(db_session, author, SCHEDULE, SEND)
    await save_channel(db_session, "email", True, {}, {})
    await db_session.commit()
    return SimpleNamespace(org=org, author=author, colleague=colleague, other=other, manager=manager)


def as_author(world) -> dict:
    return headers_for(world.author, SCHEDULE, SEND)


def body(world, recipients=None, **overrides) -> dict:
    return {
        "name": "Lembrete", "channel": "in_app", "subject": "Lembrete", "body": "Olá {{nome}}, reunião às 10h.",
        "recipient_ids": [str(r.id) for r in (recipients or [world.colleague])],
        "recurrence": "daily", "time_of_day": "09:00", "timezone": TZ, **overrides,
    }


async def _create(client, world, headers=None, key=None, **overrides):
    return await client.post(
        BASE, json=body(world, **overrides), headers={**(headers or as_author(world)), "Idempotency-Key": key or uuid.uuid4().hex}
    )


@pytest.fixture
def factory(db_session: AsyncSession) -> async_sessionmaker:
    return async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)


async def _schedule(db: AsyncSession, schedule_id: str) -> MessageSchedule:

    stmt = select(MessageSchedule).where(MessageSchedule.id == uuid.UUID(schedule_id)).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


async def _due(db: AsyncSession, schedule_id: str, moment: datetime) -> None:
    await db.execute(update(MessageSchedule).where(MessageSchedule.id == uuid.UUID(schedule_id)).values(next_run_at=moment))
    await db.commit()


async def test_scheduling_needs_its_own_permission(client: AsyncClient, world):
    only_send = headers_for(world.author, SEND)
    assert (await _create(client, world, headers=only_send)).status_code == 403
    assert (await client.get(BASE, headers=headers_for(world.colleague))).status_code == 403
    assert (await client.get(BASE, headers=headers_for(world.colleague, "notifications.messages.read"))).status_code == 200


async def test_create_is_idempotent_and_audited(client: AsyncClient, world, db_session: AsyncSession):
    first = await _create(client, world, key="agenda-0001")
    assert first.status_code == 201, first.text
    again = await _create(client, world, key="agenda-0001")
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    assert (await db_session.execute(select(func.count()).select_from(MessageSchedule))).scalar_one() == 1
    data = first.json()
    assert data["status"] == "ACTIVE" and data["next_run_at"] and data["recipient_count"] == 1
    audit = (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "notifications.message_schedule_created"))).scalars().all()
    assert len(audit) == 1


async def test_rule_and_content_are_validated(client: AsyncClient, world):
    assert (await _create(client, world, recurrence="weekly")).status_code == 422  # sem dias
    assert (await _create(client, world, time_of_day="25:00")).status_code == 422
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert (await _create(client, world, recurrence="once", run_at=past)).status_code == 422
    assert (await _create(client, world, recurrence="once", run_at="2030-01-01T09:00:00")).status_code == 422  # sem fuso
    missing = await _create(client, world, body="Oi {{setor}}")
    assert missing.status_code == 422 and "setor" in missing.text
    nobody = await _create(client, world, channel="email", recipients=[world.manager])  # fora do setor
    assert nobody.status_code == 400 and "Nenhum destinatário" in nobody.text
    ends_before = await _create(client, world, starts_on="2030-02-01", ends_on="2030-01-01")
    assert ends_before.status_code == 422


async def test_occurrences_preview_lists_the_next_dates(client: AsyncClient, world):
    resp = await client.post(
        f"{BASE}/occurrences", json={"recurrence": "weekly", "weekdays": [0], "time_of_day": "08:30", "timezone": TZ},
        headers=as_author(world),
    )
    assert resp.status_code == 200
    dates = [datetime.fromisoformat(d) for d in resp.json()["occurrences"]]
    assert len(dates) == 5 and all(d.astimezone(BRT).weekday() == 0 and d.astimezone(BRT).hour == 8 for d in dates)


async def test_due_occurrence_is_sent_once_and_the_schedule_advances(client, world, db_session, factory):
    created = (await _create(client, world)).json()
    due = datetime.now(timezone.utc) - timedelta(minutes=5)
    await _due(db_session, created["id"], due)

    result = await sched.run_due_schedules(factory)
    assert result.sent == 1
    again = await sched.run_due_schedules(factory)  # nada mais vencido
    assert again.sent == 0

    schedule = await _schedule(db_session, created["id"])
    assert schedule.runs_count == 1 and schedule.last_outcome == "sent"
    assert sched._utc(schedule.next_run_at) > datetime.now(timezone.utc)
    sent = (await db_session.execute(select(OutboundMessage).where(OutboundMessage.schedule_id == schedule.id))).scalars().all()
    assert len(sent) == 1 and sent[0].kind == "scheduled" and sent[0].idempotency_key == sched.occurrence_key(schedule.id, due)
    delivery = (await db_session.execute(select(Delivery).where(Delivery.message_id == sent[0].id))).scalar_one()
    assert delivery.recipient_user_id == world.colleague.id and "Olá" in delivery.message["body_text"]

    # a mesma ocorrência de novo (ex.: dois workers) não gera segundo envio
    await _due(db_session, created["id"], due)
    await sched.run_due_schedules(factory)
    assert (await db_session.execute(select(func.count()).where(OutboundMessage.schedule_id == schedule.id))).scalar_one() == 1

    history = await client.get("/api/v1/notifications/messages?kind=scheduled", headers=as_author(world))
    assert history.json()["total"] == 1 and history.json()["items"][0]["schedule_id"] == created["id"]
    detail = await client.get(f"{BASE}/{created['id']}", headers=as_author(world))
    assert len(detail.json()["runs"]) == 1 and len(detail.json()["upcoming"]) == 5


async def test_single_send_finishes_the_schedule(client, world, db_session, factory):
    run_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    created = (await _create(client, world, recurrence="once", run_at=run_at)).json()
    await _due(db_session, created["id"], datetime.now(timezone.utc) - timedelta(minutes=1))
    await db_session.execute(
        update(MessageSchedule).where(MessageSchedule.id == uuid.UUID(created["id"]))
        .values(run_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    )
    await db_session.commit()
    assert (await sched.run_due_schedules(factory)).sent == 1
    schedule = await _schedule(db_session, created["id"])
    assert schedule.status == "DONE" and schedule.next_run_at is None


async def test_occurrence_late_beyond_tolerance_is_skipped_and_recorded(client, world, db_session, factory):
    # Horário 12 h longe de agora: com 09:00 fixo, rodar entre 09:00 e 10:00 achava a ocorrência de hoje dentro da tolerância.
    far = (datetime.now(ZoneInfo(TZ)) + timedelta(hours=12)).strftime("%H:00")
    created = (await _create(client, world, time_of_day=far)).json()
    await _due(db_session, created["id"], datetime.now(timezone.utc) - timedelta(hours=3))
    result = await sched.run_due_schedules(factory)
    assert result.sent == 0 and result.missed >= 1
    schedule = await _schedule(db_session, created["id"])
    assert schedule.last_outcome == "missed" and "atraso" in schedule.last_error
    assert sched._utc(schedule.next_run_at) > datetime.now(timezone.utc)
    assert (await db_session.execute(select(func.count()).select_from(OutboundMessage))).scalar_one() == 0


async def test_author_without_permission_pauses_the_schedule(client, world, db_session, factory):
    created = (await _create(client, world)).json()
    await db_session.execute(user_role_association.delete().where(user_role_association.c.user_id == world.author.id))
    await _due(db_session, created["id"], datetime.now(timezone.utc) - timedelta(minutes=1))
    result = await sched.run_due_schedules(factory)
    assert result.paused == 1 and result.sent == 0
    schedule = await _schedule(db_session, created["id"])
    assert schedule.status == "PAUSED" and "permissão" in schedule.last_error


async def test_sector_is_checked_again_at_each_occurrence(client, world, db_session, factory):
    created = (await _create(client, world)).json()
    other_org = await make_org(db_session)
    await db_session.execute(
        update(Employee).where(Employee.id == world.colleague.employee_id).values(sector_id=other_org.sector.id)
    )
    await _due(db_session, created["id"], datetime.now(timezone.utc) - timedelta(minutes=1))
    result = await sched.run_due_schedules(factory)
    assert result.failed == 1
    schedule = await _schedule(db_session, created["id"])
    assert schedule.status == "ACTIVE" and schedule.last_outcome == "failed" and "Nenhum destinatário" in schedule.last_error


async def test_pause_resume_cancel_and_concurrent_edit(client, world, db_session):
    created = (await _create(client, world)).json()
    h = as_author(world)
    paused = await client.post(f"{BASE}/{created['id']}/pause", headers=h)
    assert paused.json()["status"] == "PAUSED"
    resumed = await client.post(f"{BASE}/{created['id']}/resume", headers=h)
    assert resumed.json()["status"] == "ACTIVE"

    stale = await client.put(f"{BASE}/{created['id']}", json={**body(world), "version": created["version"]}, headers=h)
    assert stale.status_code == 409
    edited = await client.put(
        f"{BASE}/{created['id']}", json={**body(world, time_of_day="15:30"), "version": resumed.json()["version"]}, headers=h
    )
    assert edited.status_code == 200 and edited.json()["time_of_day"] == "15:30"

    # quem não é o autor nem administra: não vê nem mexe
    stranger = headers_for(world.other, SCHEDULE, SEND)
    assert (await client.post(f"{BASE}/{created['id']}/cancel", headers=stranger)).status_code == 404
    reader = headers_for(world.other, SCHEDULE, "notifications.messages.read")
    assert (await client.post(f"{BASE}/{created['id']}/cancel", headers=reader)).status_code == 403

    cancelled = await client.post(f"{BASE}/{created['id']}/cancel", headers=h)
    assert cancelled.json()["status"] == "CANCELLED" and cancelled.json()["next_run_at"] is None
    assert (await client.post(f"{BASE}/{created['id']}/resume", headers=h)).status_code == 400
    events = set((await db_session.execute(select(AuditLog.event_type).where(AuditLog.event_type.like("notifications.message_schedule_%")))).scalars())
    assert events == {f"notifications.message_schedule_{e}" for e in ("created", "paused", "resumed", "updated", "cancelled")}


async def test_template_deactivated_later_does_not_block_editing(client, world, db_session):
    from app.notifications.models import MessageTemplate

    template = MessageTemplate(code="lembrete", name="Lembrete", channels=[], subject="S", body="Oi {{nome}}", is_active=True)
    db_session.add(template)
    await db_session.commit()
    created = (await _create(client, world, template_id=str(template.id))).json()
    template.is_active = False
    await db_session.commit()

    h = as_author(world)
    kept = await client.put(
        f"{BASE}/{created['id']}", json={**body(world, template_id=str(template.id), time_of_day="11:00"), "version": created["version"]}, headers=h
    )
    assert kept.status_code == 200, kept.text  # mesmo modelo: só o horário mudou
    other = MessageTemplate(code="outro", name="Outro", channels=[], subject="S", body="B", is_active=False)
    db_session.add(other)
    await db_session.commit()
    swapped = await client.put(
        f"{BASE}/{created['id']}", json={**body(world, template_id=str(other.id)), "version": kept.json()["version"]}, headers=h
    )
    assert swapped.status_code == 400 and "desativado" in swapped.text  # trocar para um modelo desativado continua barrado


async def test_open_schedules_per_person_are_capped(client, world, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "MESSAGES_MAX_ACTIVE_SCHEDULES", 1)
    assert (await _create(client, world)).status_code == 201
    capped = await _create(client, world)
    assert capped.status_code == 400 and "Limite" in capped.text


async def test_calendar_in_use_by_an_open_schedule_cannot_be_deleted(client, world, db_session):
    sla = headers_for(world.manager, "service_desk.sla.manage")
    cal = await client.post(
        "/api/v1/sla/calendars", json={"name": "Expediente", "timezone": TZ, "weekly_hours": WEEKDAYS_9_18}, headers=sla
    )
    assert cal.status_code == 201, cal.text
    once_with_calendar = await _create(
        client, world, recurrence="once", run_at="2030-01-01T09:00:00-03:00", calendar_id=cal.json()["id"]
    )
    assert once_with_calendar.status_code == 422
    created = await _create(client, world, calendar_id=cal.json()["id"], non_business_rule="next")
    assert created.status_code == 201, created.text
    assert datetime.fromisoformat(created.json()["next_run_at"]).astimezone(BRT).weekday() < 5

    blocked = await client.delete(f"/api/v1/sla/calendars/{cal.json()['id']}", headers=sla)
    assert blocked.status_code == 409 and "Lembrete" in blocked.text
    await client.post(f"{BASE}/{created.json()['id']}/cancel", headers=as_author(world))
    assert (await client.delete(f"/api/v1/sla/calendars/{cal.json()['id']}", headers=sla)).status_code == 204
    assert (await _schedule(db_session, created.json()["id"])).calendar_id is None
