"""Best-effort parsing of price / mileage / year / make+model from text."""
from __future__ import annotations

import re
from typing import Optional, Tuple

# A small, extensible set of common makes. Used to split a free-text title
# like "2017 Toyota Camry SE" into make/model/trim. Lowercase keys.
KNOWN_MAKES = {
    "acura", "audi", "bmw", "buick", "cadillac", "chevrolet", "chevy",
    "chrysler", "dodge", "fiat", "ford", "genesis", "gmc", "honda",
    "hyundai", "infiniti", "jaguar", "jeep", "kia", "land rover",
    "lexus", "lincoln", "mazda", "mercedes", "mercedes-benz", "mini",
    "mitsubishi", "nissan", "porsche", "ram", "subaru", "tesla",
    "toyota", "volkswagen", "vw", "volvo",
}

_MAKE_ALIASES = {"chevy": "chevrolet", "vw": "volkswagen", "mercedes": "mercedes-benz"}


def parse_price(text: str) -> Optional[int]:
    """First $-amount in the text, as an int. Ignores values under $100
    (those are usually fees/down-payments, not the sale price)."""
    if not text:
        return None
    for m in re.finditer(r"\$\s*([\d,]{3,})", text):
        val = int(m.group(1).replace(",", ""))
        if val >= 100:
            return val
    return None


def parse_mileage(text: str) -> Optional[int]:
    """Find a mileage figure: '85,000 miles', '85k mi', '85000mi'."""
    if not text:
        return None
    t = text.lower()
    m = re.search(r"([\d,]+)\s*k\b", t)
    if m:
        return int(m.group(1).replace(",", "")) * 1000
    m = re.search(r"([\d,]{3,})\s*(?:miles|mile|mi\b|mi\.)", t)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def parse_year(text: str) -> Optional[int]:
    """First plausible model year (1960..2027) in the text."""
    if not text:
        return None
    for m in re.finditer(r"\b(19[6-9]\d|20[0-2]\d)\b", text):
        return int(m.group(1))
    return None


def split_make_model(title: str) -> Tuple[str, str, str]:
    """Pull make/model/trim out of a free-text title. Best-effort; returns
    empty strings when nothing recognizable is found."""
    if not title:
        return "", "", ""
    tokens = title.split()
    low = [t.lower().strip(",") for t in tokens]

    make = model = trim = ""
    for i, tok in enumerate(low):
        # handle two-word makes ("land rover", "mercedes benz")
        two = f"{tok} {low[i+1]}" if i + 1 < len(low) else ""
        if two in KNOWN_MAKES:
            make = _MAKE_ALIASES.get(two, two)
            rest = tokens[i + 2:]
        elif tok in KNOWN_MAKES:
            make = _MAKE_ALIASES.get(tok, tok)
            rest = tokens[i + 1:]
        else:
            continue
        if rest:
            model = rest[0].strip(",")
            trim = " ".join(rest[1:3]).strip(", ")
        break
    return make, model, trim
