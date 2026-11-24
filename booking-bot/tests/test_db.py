import asyncio
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from bot.db import Database

TZ = ZoneInfo("Europe/Moscow")
DAY = date(2026, 12, 1)
NOW = datetime(2026, 11, 30, 12, 0, tzinfo=TZ)


def at(h: int, m: int = 0) -> datetime:
    return datetime.combine(DAY, time(h, m), tzinfo=TZ)


@pytest.fixture
def db(tmp_path):  # type: ignore[no-untyped-def]
    d = Database(str(tmp_path / "test.db"), TZ)
    yield d
    d.close()


async def test_create_and_read_back(db: Database) -> None:
    bid = await db.create_booking(1, "Иван", "+79001234567", "haircut", at(10), at(11), NOW)
    assert bid is not None
    b = await db.get(bid)
    assert b is not None
    assert b.start == at(10) and b.end == at(11) and b.status == "active"
    assert b.start.tzinfo is not None


async def test_double_booking_is_rejected(db: Database) -> None:
    assert await db.create_booking(1, "Иван", "+79001234567", "haircut", at(10), at(11), NOW)
    assert await db.create_booking(2, "Пётр", "+79007654321", "beard", at(10, 30), at(11), NOW) is None
    assert await db.create_booking(2, "Пётр", "+79007654321", "beard", at(11), at(11, 30), NOW)  # вплотную — можно


async def test_concurrent_booking_same_slot_only_one_wins(db: Database) -> None:
    results = await asyncio.gather(
        *[db.create_booking(i, "Клиент", "+79001234567", "haircut", at(15), at(16), NOW) for i in range(20)]
    )
    assert sum(r is not None for r in results) == 1


async def test_cancel_frees_slot_and_checks_owner(db: Database) -> None:
    bid = await db.create_booking(1, "Иван", "+79001234567", "haircut", at(10), at(11), NOW)
    assert bid is not None
    assert not await db.cancel(bid, user_id=999)  # чужую запись отменить нельзя
    assert await db.cancel(bid, user_id=1)
    assert not await db.cancel(bid, user_id=1)  # повторная отмена ничего не делает
    assert await db.busy_intervals(at(0), at(23, 59)) == []
    assert await db.create_booking(2, "Пётр", "+79007654321", "haircut", at(10), at(11), NOW)


async def test_busy_intervals_only_that_day(db: Database) -> None:
    await db.create_booking(1, "Иван", "+79001234567", "haircut", at(10), at(11), NOW)
    next_day = at(10) + timedelta(days=1)
    await db.create_booking(2, "Пётр", "+79007654321", "haircut", next_day, next_day + timedelta(hours=1), NOW)
    busy = await db.busy_intervals(at(0), at(0) + timedelta(days=1))
    assert busy == [(at(10), at(11))]


async def test_user_upcoming_hides_past_and_cancelled(db: Database) -> None:
    b1 = await db.create_booking(1, "Иван", "+79001234567", "haircut", at(10), at(11), NOW)
    await db.create_booking(1, "Иван", "+79001234567", "beard", at(12), at(12, 30), NOW)
    assert b1 is not None
    await db.cancel(b1, user_id=1)
    upcoming = await db.user_upcoming(1, NOW)
    assert [b.start for b in upcoming] == [at(12)]
    assert await db.user_upcoming(1, at(13)) == []


async def test_due_reminders_window_and_mark(db: Database) -> None:
    bid = await db.create_booking(1, "Иван", "+79001234567", "haircut", at(14), at(15), NOW)
    assert bid is not None
    assert await db.due_reminders(at(11, 59), 120) == []  # ещё рано (за 2 ч 01 мин)
    due = await db.due_reminders(at(12, 0), 120)
    assert [b.id for b in due] == [bid]
    await db.mark_reminded(bid)
    assert await db.due_reminders(at(12, 30), 120) == []  # повторно не напоминаем
    assert await db.due_reminders(at(14, 0), 120) == []  # началась — не напоминаем


async def test_naive_datetime_rejected(db: Database) -> None:
    with pytest.raises(ValueError):
        await db.create_booking(
            1, "Иван", "+79001234567", "haircut", datetime(2026, 12, 1, 10), datetime(2026, 12, 1, 11), NOW
        )
