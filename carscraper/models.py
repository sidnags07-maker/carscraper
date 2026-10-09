"""Shared data structures."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Car:
    source: str
    listing_id: str
    title: str
    url: str
    price: Optional[int] = None            # USD, parsed
    year: Optional[int] = None
    make: str = ""
    model: str = ""
    trim: str = ""
    mileage: Optional[int] = None          # miles, parsed
    location: str = ""                     # human string from the listing
    distance_miles: Optional[float] = None # from search ZIP, if the site reports it
    seller_type: str = ""                  # "dealer" | "private" | ""
    posted: str = ""                       # human string, best-effort
    description: str = ""                   # filled only if we fetch the detail page

    # --- dealer reputation --------------------------------------------------
    dealer_name: str = ""
    dealer_rating: Optional[float] = None      # on-site star rating, 0..5
    dealer_review_count: Optional[int] = None  # on-site review count
    ext_rating: Optional[float] = None         # external (Google/BBB) rating, 0..5
    ext_review_count: Optional[int] = None
    ext_source: str = ""                       # where the external rating came from
    reputation_flag: str = ""                  # human note, e.g. "unrated (private)"

    def to_row(self) -> dict:
        d = asdict(self)
        # Keep the CSV readable: drop the (potentially huge) description body.
        d.pop("description", None)
        return d
