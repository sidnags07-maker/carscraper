#!/usr/bin/env python3
"""Car scraper entry point.

Usage:
    python run.py                 # uses config.json
    python run.py my_config.json  # custom config

Loads config -> fetches every enabled source -> filters on your criteria and
dealer reputation -> writes a CSV and prints a summary.
"""
from __future__ import annotations

import json
import os
import sys
from typing import List


def _load_env(path: str = ".env") -> None:
    """Minimal .env loader (no dependency): KEY=value lines become env vars,
    without overriding anything already set in the real environment."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass

from carscraper.filters import apply_filters
from carscraper.history import record_run
from carscraper.models import Car
from carscraper.output import write_csv
from carscraper.sources import get_sources


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    _load_env()  # pull GOOGLE_PLACES_API_KEY from .env if present
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    cfg = load_config(cfg_path)

    sources = get_sources(cfg.get("sources", []))
    if not sources:
        print("No sources enabled. Set 'sources' in your config.")
        return 1

    raw: List[Car] = []
    for src in sources:
        print(f"[{src.name}] fetching ...")
        try:
            found = src.fetch(cfg)
        except Exception as e:  # one bad source shouldn't kill the run
            print(f"  ! [{src.name}] crashed: {e}")
            found = []
        print(f"[{src.name}] {len(found)} raw listings")
        raw.extend(found)

    print(f"\nTotal raw: {len(raw)}. Filtering + checking dealer reputation ...")
    kept = apply_filters(raw, cfg)

    out_path = cfg.get("output_csv", "cars.csv")
    write_csv(kept, out_path)

    report = record_run(kept, cfg.get("history_db", "history.db"))

    print(f"\n{len(kept)} cars matched -> {out_path}\n")
    for car in sorted(kept, key=lambda c: (c.price is None, c.price or 0)):
        price = f"${car.price:,}" if car.price else "?"
        miles = f"{car.mileage:,} mi" if car.mileage else "? mi"
        print(f"  {car.year or '????'} {car.make} {car.model} {car.trim} — "
              f"{price}, {miles} — {car.reputation_flag}")
        print(f"      {car.url}")

    print(f"\nSince the last run: {len(report.new)} new, "
          f"{len(report.drops)} price drops, {len(report.increases)} price increases")
    for ch in sorted(report.drops, key=lambda c: c.delta):
        c = ch.car
        print(f"  DROP  {c.year or '????'} {c.make} {c.model} {c.trim}: "
              f"${ch.old_price:,} -> ${ch.new_price:,} ({ch.delta:+,})")
        print(f"        {c.url}")
    for ch in report.increases:
        c = ch.car
        print(f"  UP    {c.year or '????'} {c.make} {c.model} {c.trim}: "
              f"${ch.old_price:,} -> ${ch.new_price:,} ({ch.delta:+,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
