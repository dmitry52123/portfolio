"""Хранение записей в SQLite. Время хранится в UTC (unix-секунды), наружу отдаётся в часовом поясе салона.
Все операции идут через один поток и блокировку, поэтому двойная запись на одно время невозможна."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    client_name  TEXT    NOT NULL,
    phone        TEXT    NOT NULL,
    service_code TEXT    NOT NULL,
    start_ts     INTEGER NOT NULL,
    end_ts       INTEGER NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled')),
    reminded     INTEGER NOT NULL DEFAULT 0,
    created_ts   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookings_start ON bookings (status, start_ts);
CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings (user_id, status, start_ts);
"""


@dataclass(frozen=True)
class Booking:
    id: int
    user_id: int
    client_name: str
    phone: str
    service_code: str
    start: datetime
    end: datetime
    status: str
    reminded: bool


class Database:
    def __init__(self, path: str, tz: ZoneInfo) -> None:
        self.tz = tz
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    # ---------- вспомогательное ----------
    def _row(self, r: sqlite3.Row) -> Booking:
        return Booking(
            id=r["id"],
            user_id=r["user_id"],
            client_name=r["client_name"],
            phone=r["phone"],
            service_code=r["service_code"],
            start=datetime.fromtimestamp(r["start_ts"], self.tz),
            end=datetime.fromtimestamp(r["end_ts"], self.tz),
            status=r["status"],
            reminded=bool(r["reminded"]),
        )

    @staticmethod
    def _ts(dt: datetime) -> int:
        if dt.tzinfo is None:
            raise ValueError("Нужно время с часовым поясом")
        return int(dt.timestamp())

    # ---------- синхронные операции (выполняются в отдельном потоке) ----------
    def _create(
        self,
        user_id: int,
        client_name: str,
        phone: str,
        service_code: str,
        start: datetime,
        end: datetime,
        now: datetime,
    ) -> int | None:
        s, e = self._ts(start), self._ts(end)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            try:
                clash = cur.execute(
                    "SELECT 1 FROM bookings WHERE status = 'active' AND start_ts < ? AND end_ts > ? LIMIT 1", (e, s)
                ).fetchone()
                if clash:
                    cur.execute("ROLLBACK")
                    return None
                cur.execute(
                    "INSERT INTO bookings (user_id, client_name, phone, service_code, start_ts, end_ts, created_ts)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, client_name, phone, service_code, s, e, self._ts(now)),
                )
                new_id = cur.lastrowid
                cur.execute("COMMIT")
                return int(new_id) if new_id is not None else None
            except Exception:
                cur.execute("ROLLBACK")
                raise

    def _query(self, sql: str, params: tuple[object, ...] = ()) -> list[Booking]:
        with self._lock:
            return [self._row(r) for r in self._conn.execute(sql, params).fetchall()]

    def _execute(self, sql: str, params: tuple[object, ...]) -> int:
        with self._lock:
            return self._conn.execute(sql, params).rowcount

    # ---------- асинхронный интерфейс для бота ----------
    async def create_booking(
        self,
        user_id: int,
        client_name: str,
        phone: str,
        service_code: str,
        start: datetime,
        end: datetime,
        now: datetime,
    ) -> int | None:
        """Создаёт запись. Возвращает id или None, если время уже занято."""
        return await asyncio.to_thread(self._create, user_id, client_name, phone, service_code, start, end, now)

    async def busy_intervals(self, day_start: datetime, day_end: datetime) -> list[tuple[datetime, datetime]]:
        rows = await asyncio.to_thread(
            self._query,
            "SELECT * FROM bookings WHERE status = 'active' AND start_ts < ? AND end_ts > ? ORDER BY start_ts",
            (self._ts(day_end), self._ts(day_start)),
        )
        return [(b.start, b.end) for b in rows]

    async def get(self, booking_id: int) -> Booking | None:
        rows = await asyncio.to_thread(self._query, "SELECT * FROM bookings WHERE id = ?", (booking_id,))
        return rows[0] if rows else None

    async def user_upcoming(self, user_id: int, now: datetime) -> list[Booking]:
        return await asyncio.to_thread(
            self._query,
            "SELECT * FROM bookings WHERE user_id = ? AND status = 'active' AND end_ts > ? ORDER BY start_ts",
            (user_id, self._ts(now)),
        )

    async def upcoming(self, start: datetime, end: datetime) -> list[Booking]:
        return await asyncio.to_thread(
            self._query,
            "SELECT * FROM bookings WHERE status = 'active' AND start_ts >= ? AND start_ts < ? ORDER BY start_ts",
            (self._ts(start), self._ts(end)),
        )

    async def cancel(self, booking_id: int, user_id: int | None = None) -> bool:
        """Отменяет активную запись. Если передан user_id — только свою."""
        if user_id is None:
            n = await asyncio.to_thread(
                self._execute,
                "UPDATE bookings SET status = 'cancelled' WHERE id = ? AND status = 'active'",
                (booking_id,),
            )
        else:
            n = await asyncio.to_thread(
                self._execute,
                "UPDATE bookings SET status = 'cancelled' WHERE id = ? AND user_id = ? AND status = 'active'",
                (booking_id, user_id),
            )
        return n == 1

    async def due_reminders(self, now: datetime, before_min: int) -> list[Booking]:
        """Активные записи, до начала которых осталось не больше before_min минут и о которых ещё не напоминали."""
        ts = self._ts(now)
        return await asyncio.to_thread(
            self._query,
            "SELECT * FROM bookings WHERE status = 'active' AND reminded = 0 AND start_ts > ? AND start_ts <= ?"
            " ORDER BY start_ts",
            (ts, ts + before_min * 60),
        )

    async def mark_reminded(self, booking_id: int) -> None:
        await asyncio.to_thread(self._execute, "UPDATE bookings SET reminded = 1 WHERE id = ?", (booking_id,))

    def close(self) -> None:
        with self._lock:
            self._conn.close()
