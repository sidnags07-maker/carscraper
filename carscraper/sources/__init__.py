"""Source registry. Map config names -> source classes."""
from __future__ import annotations

from .autotrader import AutoTraderSource
from .cars_com import CarsComSource
from .craigslist import CraigslistSource
from .facebook import FacebookSource

REGISTRY = {
    "craigslist": CraigslistSource,
    "cars_com": CarsComSource,
    "autotrader": AutoTraderSource,
    "facebook": FacebookSource,
}


def get_sources(names):
    """Instantiate the sources named in config, skipping unknown ones."""
    out = []
    for name in names:
        cls = REGISTRY.get(name)
        if cls is None:
            print(f"  ! unknown source '{name}', skipping")
            continue
        out.append(cls())
    return out
