"""CSV writer."""
from __future__ import annotations

import csv
from typing import List

from .models import Car

COLUMNS = [
    "source", "year", "make", "model", "trim", "price", "mileage",
    "location", "distance_miles", "seller_type",
    "dealer_name", "dealer_rating", "ext_rating", "ext_source",
    "reputation_flag", "posted", "title", "url", "listing_id",
]


def write_csv(cars: List[Car], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for car in cars:
            writer.writerow(car.to_row())
