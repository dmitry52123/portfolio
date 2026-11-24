"""Бизнес-логика без Telegram: свободные слоты, проверка телефона, форматирование."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

Interval = tuple[datetime, datetime]


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Полуинтервалы [start, end) пересекаются: запись 10:00–11:00 не мешает записи с 11:00."""
    return a_start < b_end and b_start < a_end


def free_slots(
    day: date,
    duration_min: int,
    busy: list[Interval],
    now: datetime,
    tz: ZoneInfo,
    open_time: time,
    close_time: time,
    step_min: int = 30,
    min_lead_min: int = 60,
) -> list[datetime]:
    """Начала свободных окон на день: услуга целиком помещается до закрытия,
    не пересекается с занятыми интервалами и начинается не раньше чем через min_lead_min."""
    if duration_min <= 0 or step_min <= 0:
        raise ValueError("Длительность и шаг должны быть положительными")
    start = datetime.combine(day, open_time, tzinfo=tz)
    close = datetime.combine(day, close_time, tzinfo=tz)
    earliest = now + timedelta(minutes=min_lead_min)
    duration = timedelta(minutes=duration_min)
    result: list[datetime] = []
    slot = start
    while slot + duration <= close:
        end = slot + duration
        if slot >= earliest and not any(overlaps(slot, end, b0, b1) for b0, b1 in busy):
            result.append(slot)
        slot += timedelta(minutes=step_min)
    return result


def booking_days(today: date, days_ahead: int) -> list[date]:
    return [today + timedelta(days=i) for i in range(days_ahead)]


_PHONE_DIGITS = re.compile(r"\D+")


def normalize_phone(text: str) -> str | None:
    """Российский мобильный номер в формате +7XXXXXXXXXX или None, если номер неверный.
    Принимает 8 900 ..., +7 (900) ..., 900-..., 7900...."""
    digits = _PHONE_DIGITS.sub("", text or "")
    if len(digits) == 10 and digits.startswith("9"):
        digits = "7" + digits
    elif len(digits) == 11 and digits[0] in "78":
        digits = "7" + digits[1:]
    else:
        return None
    if digits[1] != "9":
        return None
    return "+" + digits


def valid_name(text: str) -> str | None:
    name = " ".join((text or "").split())
    if 2 <= len(name) <= 40 and re.fullmatch(r"[A-Za-zА-Яа-яЁё\- ]+", name):
        return name
    return None


def fmt_day(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]}"


def fmt_day_short(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d.day:02d}.{d.month:02d}"


def fmt_dt(dt: datetime) -> str:
    return f"{fmt_day(dt.date())}, {dt:%H:%M}"
