"""Cálculo de tempo útil (ADR-017): funções puras, sem banco e sem relógio do sistema.

Um calendário diz em quais horários de cada dia da semana há expediente e quais datas são feriado.
`add_business_minutes` soma minutos úteis a um instante; `business_minutes_between` mede os minutos úteis
entre dois instantes. Tudo entra e sai em UTC; o fuso do calendário só decide onde "começa o dia".

Convenções:
- Minuto útil que termina exatamente no fim do expediente devolve o fim do expediente (não a abertura
  seguinte): resolver exatamente no prazo conta como cumprido.
- Com 0 minutos, devolve o próprio instante de início.
- Os cálculos internos são em segundos; `business_minutes_between` arredonda para baixo.
- Limitação: o expediente não vai até 24:00 (`datetime.time` não representa); um calendário 24x7 perde 1 minuto por dia (23:59-00:00).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

WEEKDAYS = range(7)  # 0 = segunda ... 6 = domingo
_MAX_DAYS = 3660  # trava contra calendário sem expediente ou prazo absurdo (~10 anos)
_MAX_MINUTES = 60 * 24 * 365  # 1 ano de minutos; prazo de SLA maior que isso é erro de configuração

Interval = tuple[time, time]


class CalendarError(ValueError):
    """Calendário inválido (sem expediente, intervalo invertido ou sobreposto)."""


def parse_time(value: str) -> time:
    try:
        hours, minutes = value.split(":")
        return time(int(hours), int(minutes))
    except (ValueError, AttributeError) as err:
        raise CalendarError(f"Horário inválido: {value!r} (use HH:MM)") from err


@dataclass(frozen=True)
class BusinessCalendar:
    timezone_name: str
    weekly: dict[int, tuple[Interval, ...]]
    holidays: frozenset[date] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.timezone_name)
        except Exception as err:  # ZoneInfoNotFoundError, ValueError
            raise CalendarError(f"Fuso inválido: {self.timezone_name!r}") from err
        has_hours = False
        for weekday, intervals in self.weekly.items():
            if weekday not in WEEKDAYS:
                raise CalendarError(f"Dia da semana inválido: {weekday}")
            previous_end: time | None = None
            for start, end in intervals:
                if start >= end:
                    raise CalendarError(f"Intervalo invertido ou vazio: {start}-{end}")
                if previous_end is not None and start < previous_end:
                    raise CalendarError("Intervalos do mesmo dia devem estar em ordem e sem sobreposição")
                previous_end = end
                has_hours = True
        if not has_hours:
            raise CalendarError("O calendário precisa de ao menos um intervalo de expediente")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    @classmethod
    def from_dict(cls, data: dict) -> "BusinessCalendar":
        """Lê o formato guardado no banco: {"timezone", "weekly_hours": {"0": [["08:00","18:00"]]}, "holidays": ["2026-12-25"]}."""
        try:
            weekly: dict[int, tuple[Interval, ...]] = {}
            for key, intervals in (data.get("weekly_hours") or {}).items():
                weekly[int(key)] = tuple((parse_time(a), parse_time(b)) for a, b in intervals)
            holidays = frozenset(date.fromisoformat(d) for d in data.get("holidays") or [])
            return cls(data["timezone"], weekly, holidays)
        except CalendarError:
            raise
        except (KeyError, ValueError, TypeError, AttributeError) as err:
            raise CalendarError(f"Calendário malformado: {err}") from err

    def to_dict(self) -> dict:
        return {
            "timezone": self.timezone_name,
            "weekly_hours": {
                str(day): [[a.strftime("%H:%M"), b.strftime("%H:%M")] for a, b in intervals]
                for day, intervals in sorted(self.weekly.items())
            },
            "holidays": sorted(d.isoformat() for d in self.holidays),
        }

    def intervals_on(self, day: date) -> list[tuple[datetime, datetime]]:
        """Expediente do dia local, em UTC (vazio em feriado ou dia sem expediente)."""
        if day in self.holidays:
            return []
        tz = self.tz
        out = []
        for start, end in self.weekly.get(day.weekday(), ()):
            out.append(
                (
                    datetime.combine(day, start, tzinfo=tz).astimezone(timezone.utc),
                    datetime.combine(day, end, tzinfo=tz).astimezone(timezone.utc),
                )
            )
        return out


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("Use datas com fuso (UTC); datas sem fuso são ambíguas")
    return moment.astimezone(timezone.utc)


def add_business_minutes(start: datetime, minutes: int, calendar: BusinessCalendar) -> datetime:
    """Instante (UTC) em que `minutes` minutos úteis terminam, contando a partir de `start`."""
    if isinstance(minutes, bool) or not isinstance(minutes, int):
        raise ValueError("minutes deve ser um inteiro")
    if minutes < 0 or minutes > _MAX_MINUTES:
        raise ValueError(f"minutes deve estar entre 0 e {_MAX_MINUTES}")
    cursor = _utc(start)
    if minutes == 0:
        return cursor
    remaining = timedelta(minutes=minutes)
    day = cursor.astimezone(calendar.tz).date()
    for _ in range(_MAX_DAYS):
        for open_at, close_at in calendar.intervals_on(day):
            if close_at <= cursor:
                continue
            begin = max(open_at, cursor)
            available = close_at - begin
            if available >= remaining:
                return begin + remaining
            remaining -= available
        day += timedelta(days=1)
    raise CalendarError("Prazo além do limite de cálculo (calendário sem expediente suficiente)")


def business_minutes_between(start: datetime, end: datetime, calendar: BusinessCalendar) -> int:
    """Minutos úteis (inteiros, para baixo) entre `start` e `end`; 0 se `end` não é depois de `start`."""
    begin, finish = _utc(start), _utc(end)
    if finish <= begin:
        return 0
    total = timedelta()
    day = begin.astimezone(calendar.tz).date()
    last_day = finish.astimezone(calendar.tz).date()
    while day <= last_day:
        for open_at, close_at in calendar.intervals_on(day):
            low, high = max(open_at, begin), min(close_at, finish)
            if high > low:
                total += high - low
        day += timedelta(days=1)
    return int(total.total_seconds() // 60)
