"""Source interface. Every site we scrape implements `fetch`."""
from __future__ import annotations

from typing import List, Protocol

from ..models import Car


class Source(Protocol):
    name: str

    def fetch(self, cfg: dict) -> List[Car]:
        """Return raw listings (unfiltered). Filtering happens centrally."""
        ...
