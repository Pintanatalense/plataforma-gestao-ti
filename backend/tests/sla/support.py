"""Apoio comum aos testes de SLA: relógio controlado, política de teste e um "mundo" com solicitante e atendente.

Calendário: segunda a sexta, 08:00-18:00 em America/Sao_Paulo (UTC-3).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.service_desk.models import TicketCategory
from app.sla.models import SlaCalendar, SlaPolicy, SlaPolicyTarget
from tests.factories import headers_for, make_employee, make_org, make_ticket_category, make_user

WEEKLY = {str(d): [["08:00", "18:00"]] for d in range(5)}
TARGETS = {"CRITICAL": (30, 240), "HIGH": (60, 480), "MEDIUM": (240, 1440), "LOW": (480, 2880)}
MONDAY_11H = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)  # segunda 11:00 em São Paulo


def utc(day: int, hour: int, minute: int = 0) -> datetime:
    """Horário LOCAL (UTC-3) de outubro/2026 -> UTC."""
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone(timedelta(hours=-3))).astimezone(timezone.utc)


@dataclass
class Clock:
    now: datetime

    def set(self, moment: datetime) -> None:
        self.now = moment


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock(MONDAY_11H)
    monkeypatch.setattr("app.sla.service._now", lambda: c.now)
    monkeypatch.setattr("app.service_desk.services.sla_now", lambda: c.now)
    return c


async def make_policy(db: AsyncSession, *, name: str = "Padrão", active: bool = True, reopen: str = "RESTART",
                      targets: dict | None = None, pause: list[str] | None = None) -> SlaPolicy:
    calendar = SlaCalendar(name=f"Cal {name}", timezone="America/Sao_Paulo", weekly_hours=WEEKLY)
    policy = SlaPolicy(name=name, calendar=calendar, is_active=active, reopen_rule=reopen, pause_statuses=pause or ["PENDING"])
    for priority, (first, resolution) in (targets or TARGETS).items():
        policy.targets.append(SlaPolicyTarget(priority=priority, first_response_minutes=first, resolution_minutes=resolution))
    db.add(policy)
    await db.commit()
    return policy


@dataclass
class World:
    org: object
    requester: object
    requester_emp: object
    attendant: object
    admin: object
    category: TicketCategory
    policy: SlaPolicy

    @property
    def h_req(self):
        return headers_for(self.requester)

    @property
    def h_att(self):
        return headers_for(self.attendant, "service_desk.tickets.manage")

    @property
    def h_admin(self):
        return headers_for(self.admin, is_admin=True)


@pytest.fixture
async def world(db_session: AsyncSession, clock: Clock) -> World:
    org = await make_org(db_session)
    requester_emp = await make_employee(db_session, org)
    requester = await make_user(db_session, requester_emp)
    attendant = await make_user(db_session, await make_employee(db_session, org))
    admin = await make_user(db_session, is_admin=True)
    policy = await make_policy(db_session)
    category = await make_ticket_category(db_session, org.sector)
    category.sla_policy_id = policy.id
    await db_session.commit()
    return World(org, requester, requester_emp, attendant, admin, category, policy)


async def open_ticket(client: AsyncClient, w: World, priority: str = "HIGH", category: TicketCategory | None = None) -> str:
    resp = await client.post(
        "/api/v1/tickets",
        json={"title": "Sem rede", "description": "d", "priority": priority, "category_id": str((category or w.category).id)},
        headers=w.h_req,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def patch(client: AsyncClient, w: World, ticket_id: str, headers=None, **body):
    resp = await client.patch(f"/api/v1/tickets/{ticket_id}", json=body, headers=headers or w.h_att)
    assert resp.status_code == 200, resp.text
    return resp.json()["sla"]


async def sla_of(client: AsyncClient, w: World, ticket_id: str) -> dict:
    return (await client.get(f"/api/v1/tickets/{ticket_id}", headers=w.h_att)).json()["sla"]


def as_utc(moment: datetime) -> datetime:
    """O SQLite devolve datas sem fuso; o sistema grava sempre UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def same(value: str | None, expected: datetime) -> bool:
    return value is not None and as_utc(datetime.fromisoformat(value.replace("Z", "+00:00"))) == expected
