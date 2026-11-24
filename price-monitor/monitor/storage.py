"""SQLite: текущие цены и история. Сравнение нового снимка с прошлым даёт список изменений."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from monitor.parse import Product

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    url        TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    price      TEXT NOT NULL,
    currency   TEXT NOT NULL,
    in_stock   INTEGER NOT NULL,
    rating     INTEGER NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS price_history (
    url   TEXT NOT NULL,
    ts    TEXT NOT NULL,
    price TEXT NOT NULL,
    in_stock INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_url ON price_history (url, ts);
"""


@dataclass(frozen=True)
class Change:
    kind: str  # new | price | stock_out | stock_in
    product: Product
    old_price: Decimal | None = None

    @property
    def percent(self) -> Decimal | None:
        if self.kind != "price" or not self.old_price:
            return None
        return ((self.product.price - self.old_price) / self.old_price * 100).quantize(Decimal("0.1"))


class Storage:
    def __init__(self, path: str) -> None:
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def is_empty(self) -> bool:
        count = int(self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0])
        return count == 0

    def update(
        self, products: Iterable[Product], now: datetime | None = None, min_change_pct: Decimal = Decimal(0)
    ) -> list[Change]:
        """Сохраняет снимок и возвращает изменения относительно прошлого запуска.
        Изменение цены меньше min_change_pct процентов не считается (защита от «шума»)."""
        ts = (now or datetime.now(UTC)).isoformat(timespec="seconds")
        changes: list[Change] = []
        with self.conn:
            for p in products:
                row = self.conn.execute("SELECT price, in_stock FROM products WHERE url = ?", (p.url,)).fetchone()
                if row is None:
                    changes.append(Change("new", p))
                else:
                    old_price, old_stock = Decimal(row[0]), bool(row[1])
                    if old_price != p.price:
                        pct = abs(p.price - old_price) / old_price * 100 if old_price else Decimal(100)
                        if pct >= min_change_pct:
                            changes.append(Change("price", p, old_price))
                    if old_stock and not p.in_stock:
                        changes.append(Change("stock_out", p))
                    elif not old_stock and p.in_stock:
                        changes.append(Change("stock_in", p))
                self.conn.execute(
                    "INSERT INTO products (url, title, price, currency, in_stock, rating, first_seen, last_seen)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(url) DO UPDATE SET title = excluded.title, price = excluded.price,"
                    " currency = excluded.currency, in_stock = excluded.in_stock, rating = excluded.rating,"
                    " last_seen = excluded.last_seen",
                    (p.url, p.title, str(p.price), p.currency, int(p.in_stock), p.rating, ts, ts),
                )
                self.conn.execute(
                    "INSERT INTO price_history (url, ts, price, in_stock) VALUES (?, ?, ?, ?)",
                    (p.url, ts, str(p.price), int(p.in_stock)),
                )
        return changes

    def all_products(self) -> list[Product]:
        rows = self.conn.execute(
            "SELECT url, title, price, currency, in_stock, rating FROM products ORDER BY title"
        ).fetchall()
        return [Product(r[0], r[1], Decimal(r[2]), r[3], bool(r[4]), r[5]) for r in rows]

    def history(self, url: str) -> list[tuple[str, Decimal]]:
        rows = self.conn.execute("SELECT ts, price FROM price_history WHERE url = ? ORDER BY ts", (url,)).fetchall()
        return [(r[0], Decimal(r[1])) for r in rows]

    def close(self) -> None:
        self.conn.close()
