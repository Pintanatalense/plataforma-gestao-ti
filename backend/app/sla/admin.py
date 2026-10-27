"""Administração de SLA (ADR-017, P4-S4): calendários (expediente e feriados) e políticas (alvos por prioridade).

Editar uma política ou um calendário só vale para chamados novos: cada ciclo já guardou a sua cópia (`snapshot`).
Por isso nada aqui recalcula chamados em andamento. Toda alteração vai para a auditoria (quem, o quê, antes/depois).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit.repository import AuditRepository
from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.sla.business_time import BusinessCalendar, CalendarError
from app.sla.models import SlaCalendar, SlaHoliday, SlaPolicy, SlaPolicyTarget
from app.sla.schemas import (
    CalendarIn,
    CalendarOut,
    CalendarUpdate,
    HolidayIn,
    HolidayOut,
    PolicyIn,
    PolicyOut,
    PolicyUpdate,
    TargetIn,
    TargetOut,
)


def _normalized_hours(timezone_name: str, weekly_hours: dict, holidays: list[HolidayIn]) -> dict:
    """Valida o calendário com a mesma calculadora do relógio e devolve o expediente no formato guardado."""
    days = [h.day for h in holidays]
    if len(days) != len(set(days)):
        raise ValidationException("Há feriados repetidos na mesma data")
    try:
        calendar = BusinessCalendar.from_dict(
            {"timezone": timezone_name, "weekly_hours": weekly_hours, "holidays": [d.isoformat() for d in days]}
        )
    except CalendarError as err:
        raise ValidationException(str(err)) from err
    return calendar.to_dict()["weekly_hours"]


def _check_targets(targets: list[TargetIn]) -> None:
    priorities = [t.priority for t in targets]
    if len(priorities) != len(set(priorities)):
        raise ValidationException("Cada prioridade pode ter um único alvo")
    for target in targets:
        if target.resolution_minutes < target.first_response_minutes:
            raise ValidationException(f"Prioridade {target.priority}: a resolução não pode ser menor que a primeira resposta")


class SlaAdminService:
    def __init__(self, session: AsyncSession, user_id: uuid.UUID | None) -> None:
        self.session = session
        self.user_id = user_id

    async def _audit(self, event_type: str, entity_type: str, entity_id: uuid.UUID, data: dict) -> None:
        await AuditRepository(self.session).create(event_type, entity_type, entity_id, data, user_id=self.user_id)

    async def _name_taken(self, model, name: str, exclude: uuid.UUID | None) -> bool:
        stmt = select(model.id).where(func.lower(model.name) == name.strip().lower())
        if exclude is not None:
            stmt = stmt.where(model.id != exclude)
        return (await self.session.execute(stmt)).first() is not None

    # ------------------------------------------------------------------ calendários

    async def _calendar(self, calendar_id: uuid.UUID) -> SlaCalendar:
        calendar = (
            await self.session.execute(
                select(SlaCalendar)
                .where(SlaCalendar.id == calendar_id)
                .options(selectinload(SlaCalendar.holidays))
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if calendar is None:
            raise NotFoundException("Calendário de SLA", calendar_id)
        return calendar

    async def _calendar_out(self, calendar: SlaCalendar) -> CalendarOut:
        names = (
            await self.session.execute(select(SlaPolicy.name).where(SlaPolicy.calendar_id == calendar.id).order_by(SlaPolicy.name))
        ).scalars()
        return CalendarOut(
            id=calendar.id, name=calendar.name, timezone=calendar.timezone, weekly_hours=calendar.weekly_hours,
            holidays=[HolidayOut.model_validate(h) for h in calendar.holidays], policy_names=list(names),
        )

    async def list_calendars(self) -> list[CalendarOut]:
        rows = (
            await self.session.execute(select(SlaCalendar).options(selectinload(SlaCalendar.holidays)).order_by(SlaCalendar.name))
        ).scalars()
        return [await self._calendar_out(c) for c in rows]

    async def create_calendar(self, data: CalendarIn) -> CalendarOut:
        if await self._name_taken(SlaCalendar, data.name, None):
            raise ConflictException("Já existe um calendário com esse nome")
        hours = _normalized_hours(data.timezone, data.weekly_hours, data.holidays)
        calendar = SlaCalendar(name=data.name.strip(), timezone=data.timezone, weekly_hours=hours)
        calendar.holidays = [SlaHoliday(day=h.day, name=h.name) for h in data.holidays]
        self.session.add(calendar)
        await self.session.flush()
        await self._audit("sla.calendar_created", "sla_calendar", calendar.id, data.model_dump(mode="json"))
        return await self._calendar_out(await self._calendar(calendar.id))

    async def update_calendar(self, calendar_id: uuid.UUID, data: CalendarUpdate) -> CalendarOut:
        calendar = await self._calendar(calendar_id)
        changes = data.model_dump(mode="json", exclude_unset=True)
        if data.name is not None:
            if await self._name_taken(SlaCalendar, data.name, calendar.id):
                raise ConflictException("Já existe um calendário com esse nome")
            calendar.name = data.name.strip()
        holidays = data.holidays if data.holidays is not None else [HolidayIn(day=h.day, name=h.name) for h in calendar.holidays]
        calendar.weekly_hours = _normalized_hours(
            data.timezone or calendar.timezone, data.weekly_hours if data.weekly_hours is not None else calendar.weekly_hours, holidays
        )
        if data.timezone is not None:
            calendar.timezone = data.timezone
        if data.holidays is not None:
            calendar.holidays.clear()
            await self.session.flush()  # o único (calendário, data) não deixa trocar a lista numa tacada só
            calendar.holidays.extend(SlaHoliday(day=h.day, name=h.name) for h in data.holidays)
        await self.session.flush()
        await self._audit("sla.calendar_updated", "sla_calendar", calendar.id, changes)
        return await self._calendar_out(await self._calendar(calendar.id))

    async def delete_calendar(self, calendar_id: uuid.UUID) -> None:
        calendar = await self._calendar(calendar_id)
        used = (await self.session.execute(select(SlaPolicy.name).where(SlaPolicy.calendar_id == calendar.id))).scalars().all()
        if used:
            raise ConflictException(f"O calendário é usado pelas políticas: {', '.join(sorted(used))}")
        await self._audit("sla.calendar_deleted", "sla_calendar", calendar.id, {"name": calendar.name})
        await self.session.delete(calendar)
        await self.session.flush()

    # ------------------------------------------------------------------ políticas

    async def _policy(self, policy_id: uuid.UUID) -> SlaPolicy:
        policy = (
            await self.session.execute(
                select(SlaPolicy)
                .where(SlaPolicy.id == policy_id)
                .options(selectinload(SlaPolicy.targets), selectinload(SlaPolicy.calendar))
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if policy is None:
            raise NotFoundException("Política de SLA", policy_id)
        return policy

    async def _category_names(self, policy_id: uuid.UUID) -> list[str]:
        from app.service_desk.models import TicketCategory  # evita import circular (models de chamado importam sla)

        rows = await self.session.execute(
            select(TicketCategory.name).where(TicketCategory.sla_policy_id == policy_id).order_by(TicketCategory.name)
        )
        return list(rows.scalars())

    async def _policy_out(self, policy: SlaPolicy) -> PolicyOut:
        order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        return PolicyOut(
            id=policy.id, name=policy.name, description=policy.description, is_active=policy.is_active,
            calendar_id=policy.calendar_id, calendar_name=policy.calendar.name, pause_statuses=list(policy.pause_statuses or []),
            reopen_rule=policy.reopen_rule, alert_percent=policy.alert_percent,
            targets=[TargetOut.model_validate(t) for t in sorted(policy.targets, key=lambda t: order.get(t.priority, 9))],
            category_names=await self._category_names(policy.id),
        )

    async def list_policies(self) -> list[PolicyOut]:
        rows = (
            await self.session.execute(
                select(SlaPolicy).options(selectinload(SlaPolicy.targets), selectinload(SlaPolicy.calendar)).order_by(SlaPolicy.name)
            )
        ).scalars()
        return [await self._policy_out(p) for p in rows]

    async def get_policy(self, policy_id: uuid.UUID) -> PolicyOut:
        return await self._policy_out(await self._policy(policy_id))

    async def create_policy(self, data: PolicyIn) -> PolicyOut:
        if await self._name_taken(SlaPolicy, data.name, None):
            raise ConflictException("Já existe uma política com esse nome")
        await self._calendar(data.calendar_id)
        _check_targets(data.targets)
        policy = SlaPolicy(
            name=data.name.strip(), description=data.description, is_active=data.is_active, calendar_id=data.calendar_id,
            pause_statuses=sorted(set(data.pause_statuses)), reopen_rule=data.reopen_rule, alert_percent=data.alert_percent,
        )
        policy.targets = [SlaPolicyTarget(**t.model_dump()) for t in data.targets]
        self.session.add(policy)
        await self.session.flush()
        await self._audit("sla.policy_created", "sla_policy", policy.id, data.model_dump(mode="json"))
        return await self.get_policy(policy.id)

    async def update_policy(self, policy_id: uuid.UUID, data: PolicyUpdate) -> PolicyOut:
        policy = await self._policy(policy_id)
        changes = data.model_dump(mode="json", exclude_unset=True)
        if data.name is not None:
            if await self._name_taken(SlaPolicy, data.name, policy.id):
                raise ConflictException("Já existe uma política com esse nome")
            policy.name = data.name.strip()
        if "description" in data.model_fields_set:
            policy.description = data.description
        if data.is_active is not None:
            policy.is_active = data.is_active
        if data.calendar_id is not None:
            await self._calendar(data.calendar_id)
            policy.calendar_id = data.calendar_id
        if data.pause_statuses is not None:
            policy.pause_statuses = sorted(set(data.pause_statuses))
        if data.reopen_rule is not None:
            policy.reopen_rule = data.reopen_rule
        if data.alert_percent is not None:
            policy.alert_percent = data.alert_percent
        if data.targets is not None:
            _check_targets(data.targets)
            policy.targets.clear()
            await self.session.flush()  # o único (política, prioridade) não deixa trocar a lista numa tacada só
            policy.targets.extend(SlaPolicyTarget(**t.model_dump()) for t in data.targets)
        await self.session.flush()
        await self._audit("sla.policy_updated", "sla_policy", policy.id, changes)
        return await self.get_policy(policy.id)

    async def delete_policy(self, policy_id: uuid.UUID) -> None:
        policy = await self._policy(policy_id)
        used = await self._category_names(policy.id)
        if used:
            raise ConflictException(f"A política está ligada às categorias: {', '.join(used)}. Troque o SLA delas antes.")
        await self._audit("sla.policy_deleted", "sla_policy", policy.id, {"name": policy.name})
        await self.session.delete(policy)
        await self.session.flush()
