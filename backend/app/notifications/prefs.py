"""
Preferências de notificação: canais desligados, categorias silenciadas e horário de silêncio.

Regras (ADR-013 §6.2): `in_app` é o piso e nunca é suprimido nem adiado; canais externos respeitam
as preferências; `critical` ignora o horário de silêncio quando `critical_bypass` está ligado.
"""
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.jobs import local_timezone
from app.notifications.models import UserNotificationPref

CATEGORIES = ("ticket", "asset", "stock", "system")
_CATEGORY_BY_PREFIX = {"ticket": "ticket", "asset": "asset", "stock": "stock", "inventory": "stock"}
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def category_of(event_type: str) -> str:
    return _CATEGORY_BY_PREFIX.get(event_type.split(".", 1)[0], "system")


@dataclass
class Prefs:
    channels_disabled: list[str] = field(default_factory=list)
    categories_disabled: list[str] = field(default_factory=list)
    quiet_enabled: bool = True
    quiet_start: str = "20:00"
    quiet_end: str = "07:00"
    critical_bypass: bool = True


def _parse(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def quiet_until(prefs: Prefs, now: datetime, priority: str) -> datetime | None:
    """Fim da janela de silêncio (UTC) se `now` estiver dentro dela; senão None."""
    if not prefs.quiet_enabled or (priority == "critical" and prefs.critical_bypass):
        return None
    start, end = _parse(prefs.quiet_start), _parse(prefs.quiet_end)
    if start == end:
        return None
    local = now.astimezone(local_timezone())
    t = local.time()
    inside = (start <= t < end) if start < end else (t >= start or t < end)
    if not inside:
        return None
    finish = local.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if finish <= local:
        finish += timedelta(days=1)
    return finish.astimezone(timezone.utc)


def allows(prefs: Prefs, channel: str, event_type: str) -> bool:
    if channel == "in_app":
        return True
    return channel not in prefs.channels_disabled and category_of(event_type) not in prefs.categories_disabled


async def load_prefs(session: AsyncSession, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, Prefs]:
    if not user_ids:
        return {}
    rows = (
        await session.execute(select(UserNotificationPref).where(UserNotificationPref.user_id.in_(user_ids)))
    ).scalars()
    return {
        row.user_id: Prefs(
            channels_disabled=list(row.channels_disabled or []),
            categories_disabled=list(row.categories_disabled or []),
            quiet_enabled=row.quiet_enabled,
            quiet_start=row.quiet_start,
            quiet_end=row.quiet_end,
            critical_bypass=row.critical_bypass,
        )
        for row in rows
    }
