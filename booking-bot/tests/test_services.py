from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from bot.services import booking_days, fmt_day, free_slots, normalize_phone, overlaps, valid_name

TZ = ZoneInfo("Europe/Moscow")
DAY = date(2026, 12, 1)  # вторник


def at(h: int, m: int = 0, d: date = DAY) -> datetime:
    return datetime.combine(d, time(h, m), tzinfo=TZ)


def slots(**kw: Any) -> list[datetime]:
    params: dict[str, Any] = dict(
        day=DAY,
        duration_min=60,
        busy=[],
        now=at(0, 0, date(2026, 11, 30)),
        tz=TZ,
        open_time=time(10),
        close_time=time(21),
        step_min=30,
        min_lead_min=60,
    )
    params.update(kw)
    return free_slots(**params)


def test_overlaps_touching_intervals_do_not_clash() -> None:
    assert not overlaps(at(10), at(11), at(11), at(12))
    assert overlaps(at(10), at(11), at(10, 30), at(11, 30))
    assert overlaps(at(10), at(12), at(10, 30), at(11))


def test_empty_day_has_all_slots_and_service_fits_before_closing() -> None:
    result = slots()
    assert result[0] == at(10)
    assert result[-1] == at(20)  # 60-минутная услуга должна закончиться к 21:00
    assert len(result) == 21  # 10:00 … 20:00 с шагом 30 минут


def test_long_service_last_slot() -> None:
    assert slots(duration_min=90)[-1] == at(19, 30)


def test_busy_interval_removes_overlapping_slots() -> None:
    result = slots(busy=[(at(12), at(13))])
    assert at(11) in result  # 11:00–12:00 вплотную, можно
    assert at(11, 30) not in result  # 11:30–12:30 пересекается
    assert at(12) not in result
    assert at(12, 30) not in result
    assert at(13) in result


def test_lead_time_hides_too_close_slots() -> None:
    result = slots(now=at(12, 10))
    assert result[0] == at(13, 30)  # 12:10 + 60 мин = 13:10, ближайший шаг 13:30


def test_past_day_has_no_slots() -> None:
    assert slots(now=at(22)) == []


def test_invalid_duration() -> None:
    with pytest.raises(ValueError):
        slots(duration_min=0)


def test_booking_days() -> None:
    days = booking_days(DAY, 3)
    assert days == [date(2026, 12, 1), date(2026, 12, 2), date(2026, 12, 3)]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+7 (900) 123-45-67", "+79001234567"),
        ("8 900 123 45 67", "+79001234567"),
        ("9001234567", "+79001234567"),
        ("79001234567", "+79001234567"),
        ("+7 495 123-45-67", None),  # городской, не мобильный
        ("12345", None),
        ("", None),
        ("+7 900 123-45-67-89", None),
    ],
)
def test_normalize_phone(raw: str, expected: str | None) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Иван", "Иван"),
        ("  Анна   Мария ", "Анна Мария"),
        ("Jean-Luc", "Jean-Luc"),
        ("A", None),
        ("<b>Хакер</b>", None),
        ("x" * 41, None),
    ],
)
def test_valid_name(raw: str, expected: str | None) -> None:
    assert valid_name(raw) == expected


def test_fmt_day() -> None:
    assert fmt_day(DAY) == "вт, 1 декабря"
