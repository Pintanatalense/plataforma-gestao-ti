"""Calculadora de tempo útil (ADR-017): limites de expediente, fim de semana, feriado e fuso."""

from datetime import date, datetime, time, timezone

import pytest

from app.sla.business_time import (
    BusinessCalendar,
    CalendarError,
    add_business_minutes,
    business_minutes_between,
)

# São Paulo é UTC-3 o ano todo (sem horário de verão desde 2019): 08:00 local = 11:00 UTC.
WEEKDAYS_8_18 = {d: ((time(8), time(18)),) for d in range(5)}
SP = BusinessCalendar("America/Sao_Paulo", WEEKDAYS_8_18)


def utc(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def local(y, m, d, hh, mm=0):
    """Instante em UTC a partir do horário de São Paulo (UTC-3)."""
    return utc(y, m, d, hh + 3, mm)


# 2026-10-19 é segunda-feira; 2026-10-23 é sexta; 2026-10-24 é sábado.


class TestAdd:
    def test_inside_the_same_day(self):
        assert add_business_minutes(local(2026, 10, 19, 9), 60, SP) == local(2026, 10, 19, 10)

    def test_zero_minutes_returns_start(self):
        assert add_business_minutes(local(2026, 10, 19, 20), 0, SP) == local(2026, 10, 19, 20)

    def test_ends_exactly_at_closing_time(self):
        assert add_business_minutes(local(2026, 10, 19, 17), 60, SP) == local(2026, 10, 19, 18)

    def test_spills_to_next_business_day(self):
        assert add_business_minutes(local(2026, 10, 19, 17, 30), 60, SP) == local(2026, 10, 20, 8, 30)

    def test_start_after_hours_waits_for_opening(self):
        assert add_business_minutes(local(2026, 10, 19, 20), 30, SP) == local(2026, 10, 20, 8, 30)

    def test_start_before_opening_counts_from_opening(self):
        assert add_business_minutes(local(2026, 10, 19, 6), 30, SP) == local(2026, 10, 19, 8, 30)

    def test_friday_evening_goes_to_monday(self):
        assert add_business_minutes(local(2026, 10, 23, 17, 30), 60, SP) == local(2026, 10, 26, 8, 30)

    def test_weekend_start_goes_to_monday(self):
        assert add_business_minutes(local(2026, 10, 24, 12), 60, SP) == local(2026, 10, 26, 9)

    def test_holiday_is_skipped(self):
        cal = BusinessCalendar("America/Sao_Paulo", WEEKDAYS_8_18, frozenset({date(2026, 10, 20)}))
        assert add_business_minutes(local(2026, 10, 19, 17, 30), 60, cal) == local(2026, 10, 21, 8, 30)

    def test_multi_day_target(self):
        # 48 h úteis = 4,8 dias de 10 h: sexta 08:00 + 48 h cai na quinta seguinte às 16:00
        assert add_business_minutes(local(2026, 10, 23, 8), 48 * 60, SP) == local(2026, 10, 29, 16)

    def test_split_shift_skips_lunch(self):
        cal = BusinessCalendar("America/Sao_Paulo", {0: ((time(8), time(12)), (time(13), time(17)))})
        assert add_business_minutes(local(2026, 10, 19, 11), 120, cal) == local(2026, 10, 19, 14)

    def test_naive_datetime_is_rejected(self):
        with pytest.raises(ValueError):
            add_business_minutes(datetime(2026, 10, 19, 9), 10, SP)

    def test_negative_minutes_rejected(self):
        with pytest.raises(ValueError):
            add_business_minutes(utc(2026, 10, 19), -1, SP)

    def test_result_is_in_utc(self):
        assert add_business_minutes(local(2026, 10, 19, 9), 1, SP).utcoffset().total_seconds() == 0


class TestBetween:
    def test_same_day(self):
        assert business_minutes_between(local(2026, 10, 19, 9), local(2026, 10, 19, 11, 30), SP) == 150

    def test_skips_night_and_weekend(self):
        # sexta 17:00 -> segunda 09:00 = 1 h (sexta) + 1 h (segunda)
        assert business_minutes_between(local(2026, 10, 23, 17), local(2026, 10, 26, 9), SP) == 120

    def test_end_not_after_start_is_zero(self):
        assert business_minutes_between(local(2026, 10, 19, 11), local(2026, 10, 19, 9), SP) == 0

    def test_outside_hours_only_is_zero(self):
        assert business_minutes_between(local(2026, 10, 24, 9), local(2026, 10, 25, 17), SP) == 0

    def test_holiday_does_not_count(self):
        cal = BusinessCalendar("America/Sao_Paulo", WEEKDAYS_8_18, frozenset({date(2026, 10, 20)}))
        assert business_minutes_between(local(2026, 10, 19, 17), local(2026, 10, 21, 9), cal) == 120

    def test_is_the_inverse_of_add(self):
        start = local(2026, 10, 19, 15, 20)
        for minutes in (1, 59, 600, 2880):
            end = add_business_minutes(start, minutes, SP)
            assert business_minutes_between(start, end, SP) == minutes


class TestTimezone:
    def test_dst_zone_uses_wall_clock_hours(self):
        # Nova York muda para o horário de verão em 2026-03-08: 09:00 local passa de UTC-5 para UTC-4.
        cal = BusinessCalendar("America/New_York", {d: ((time(9), time(17)),) for d in range(7)})
        before = add_business_minutes(utc(2026, 3, 7, 13, 0), 60, cal)  # sábado 08:00 local (UTC-5) -> abre 09:00
        assert before == utc(2026, 3, 7, 15, 0)  # 10:00 local = 15:00 UTC
        after = add_business_minutes(utc(2026, 3, 9, 12, 0), 60, cal)  # segunda 08:00 local (UTC-4) -> abre 09:00
        assert after == utc(2026, 3, 9, 14, 0)  # 10:00 local = 14:00 UTC

    def test_other_timezone_is_converted_correctly(self):
        cal = BusinessCalendar("UTC", {d: ((time(8), time(18)),) for d in range(5)})
        assert add_business_minutes(utc(2026, 10, 19, 17, 30), 60, cal) == utc(2026, 10, 20, 8, 30)


class TestValidation:
    def test_calendar_without_hours_is_rejected(self):
        with pytest.raises(CalendarError):
            BusinessCalendar("UTC", {})

    def test_inverted_interval_is_rejected(self):
        with pytest.raises(CalendarError):
            BusinessCalendar("UTC", {0: ((time(18), time(8)),)})

    def test_overlapping_intervals_are_rejected(self):
        with pytest.raises(CalendarError):
            BusinessCalendar("UTC", {0: ((time(8), time(12)), (time(11), time(17)))})

    def test_unknown_timezone_is_rejected(self):
        with pytest.raises(CalendarError):
            BusinessCalendar("Marte/Olympus", WEEKDAYS_8_18)

    def test_dict_roundtrip(self):
        data = {"timezone": "America/Sao_Paulo", "weekly_hours": {"0": [["08:00", "18:00"]]}, "holidays": ["2026-12-25"]}
        assert BusinessCalendar.from_dict(data).to_dict() == data

    def test_bad_time_text_is_rejected(self):
        with pytest.raises(CalendarError):
            BusinessCalendar.from_dict({"timezone": "UTC", "weekly_hours": {"0": [["8h", "18:00"]]}})

    def test_malformed_dicts_raise_calendar_error(self):
        for bad in ({}, {"timezone": "UTC", "weekly_hours": {"x": [["08:00", "18:00"]]}},
                    {"timezone": "UTC", "weekly_hours": {"0": [["08:00", "18:00"]]}, "holidays": ["não-é-data"]}):
            with pytest.raises(CalendarError):
                BusinessCalendar.from_dict(bad)

    def test_minutes_must_be_a_reasonable_integer(self):
        for bad in (1.5, True, 10**16):
            with pytest.raises(ValueError):
                add_business_minutes(utc(2026, 10, 19), bad, SP)
