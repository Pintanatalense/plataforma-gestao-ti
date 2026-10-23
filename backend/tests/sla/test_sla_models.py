"""Modelos de SLA: persistem, ligam a calendário e categoria, e alimentam a calculadora."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.sla.business_time import BusinessCalendar, add_business_minutes
from app.sla.models import SlaCalendar, SlaHoliday, SlaPolicy, SlaPolicyTarget
from tests.factories import make_ticket_category

pytestmark = pytest.mark.asyncio

WEEKLY = {str(d): [["08:00", "18:00"]] for d in range(5)}


async def _policy(db: AsyncSession) -> SlaPolicy:
    calendar = SlaCalendar(name="Comercial", timezone="America/Sao_Paulo", weekly_hours=WEEKLY)
    calendar.holidays.append(SlaHoliday(day=datetime(2026, 10, 20).date(), name="Feriado"))
    policy = SlaPolicy(name="Padrão", calendar=calendar)
    policy.targets.append(SlaPolicyTarget(priority="HIGH", first_response_minutes=60, resolution_minutes=480))
    db.add(policy)
    await db.commit()
    return policy


async def test_policy_defaults_to_inactive_and_restart(db_session: AsyncSession):
    policy = await _policy(db_session)
    assert policy.is_active is False
    assert policy.reopen_rule == "RESTART"
    assert policy.alert_percent == 80
    assert policy.pause_statuses == ["PENDING"]


async def test_calendar_row_feeds_the_calculator(db_session: AsyncSession):
    policy = await _policy(db_session)
    calendar = (await db_session.execute(select(SlaCalendar).where(SlaCalendar.id == policy.calendar_id))).scalar_one()
    await db_session.refresh(calendar, ["holidays"])
    business = BusinessCalendar.from_dict(
        {
            "timezone": calendar.timezone,
            "weekly_hours": calendar.weekly_hours,
            "holidays": [h.day.isoformat() for h in calendar.holidays],
        }
    )
    # segunda 17:30 (UTC-3) + 60 min úteis; terça é feriado -> quarta 08:30
    start = datetime(2026, 10, 19, 20, 30, tzinfo=timezone.utc)
    assert add_business_minutes(start, 60, business) == datetime(2026, 10, 21, 11, 30, tzinfo=timezone.utc)


async def test_target_is_unique_per_policy_and_priority(db_session: AsyncSession):
    policy = await _policy(db_session)
    db_session.add(SlaPolicyTarget(policy_id=policy.id, priority="HIGH", first_response_minutes=1, resolution_minutes=2))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_category_has_no_sla_by_default_and_can_link_one(db_session: AsyncSession):
    category = await make_ticket_category(db_session)
    assert category.sla_policy_id is None  # "Não se aplica"
    policy = await _policy(db_session)
    category.sla_policy_id = policy.id
    await db_session.commit()
    assert category.sla_policy_id == policy.id
