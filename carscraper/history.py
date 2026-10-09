"""Price history: remember every listing across runs and report price changes."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from .models import Car

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    key        TEXT PRIMARY KEY,
    source     TEXT NOT NULL,
    title      TEXT NOT NULL,
    url        TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prices (
    key      TEXT NOT NULL REFERENCES listings(key),
    seen_at  TEXT NOT NULL,
    price    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prices_key ON prices(key, seen_at);
"""


@dataclass
class PriceChange:
    car: Car
    old_price: int
    new_price: int

    @property
    def delta(self) -> int:
        return self.new_price - self.old_price


@dataclass
class RunReport:
    new: List[Car]
    drops: List[PriceChange]
    increases: List[PriceChange]


def _key(car: Car) -> str:
    return f"{car.source}:{car.listing_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _last_price(db: sqlite3.Connection, key: str) -> Optional[int]:
    row = db.execute(
        "SELECT price FROM prices WHERE key = ? ORDER BY seen_at DESC, rowid DESC LIMIT 1",
        (key,),
    ).fetchone()
    return row[0] if row else None


def record_run(cars: List[Car], db_path: str) -> RunReport:
    """Store this run's listings and return what is new or changed in price.

    A price is only written when it differs from the last stored price, so the
    prices table is a clean change log rather than one row per run.
    """
    db = sqlite3.connect(db_path)
    db.executescript(SCHEMA)
    now = _now()
    report = RunReport(new=[], drops=[], increases=[])
    with db:
        for car in cars:
            if car.price is None:
                continue
            key = _key(car)
            known = db.execute("SELECT 1 FROM listings WHERE key = ?", (key,)).fetchone()
            if not known:
                db.execute(
                    "INSERT INTO listings VALUES (?, ?, ?, ?, ?, ?)",
                    (key, car.source, car.title, car.url, now, now),
                )
                db.execute("INSERT INTO prices VALUES (?, ?, ?)", (key, now, car.price))
                report.new.append(car)
                continue
            db.execute("UPDATE listings SET last_seen = ? WHERE key = ?", (now, key))
            last = _last_price(db, key)
            if last is not None and last != car.price:
                db.execute("INSERT INTO prices VALUES (?, ?, ?)", (key, now, car.price))
                change = PriceChange(car, last, car.price)
                (report.drops if change.delta < 0 else report.increases).append(change)
    db.close()
    return report


def price_history(db_path: str, key: str) -> List[tuple]:
    db = sqlite3.connect(db_path)
    rows = db.execute(
        "SELECT seen_at, price FROM prices WHERE key = ? ORDER BY seen_at", (key,)
    ).fetchall()
    db.close()
    return rows
