"""Central filtering: criteria match (price/year/mileage/make+model/distance)
plus dealer-reputation enrichment and flagging."""
from __future__ import annotations

from typing import List, Optional

from .models import Car
from .reputation import ReputationLookup


def _in_range(value: Optional[float], lo, hi) -> bool:
    """True if value is within [lo, hi]. Unknown values pass (we don't have
    the data to exclude them; that's surfaced via flags instead)."""
    if value is None:
        return True
    if lo is not None and value < lo:
        return False
    if hi is not None and value > hi:
        return False
    return True


def _make_model_ok(car: Car, wanted: List[dict]) -> bool:
    """wanted is a list like [{"make": "toyota", "model": "camry"}, ...].
    Empty list = accept anything. Model is optional within an entry."""
    if not wanted:
        return True
    cm, cmod = car.make.lower(), car.model.lower()
    for w in wanted:
        wmake = (w.get("make") or "").lower()
        wmodel = (w.get("model") or "").lower()
        if wmake and wmake not in cm:
            continue
        if wmodel and wmodel not in cmod:
            continue
        return True
    return False


def _dedupe(cars: List[Car], max_per_dealer: int) -> List[Car]:
    seen: set[tuple] = set()
    per_dealer: dict[str, int] = {}
    out = []
    for car in cars:
        key = (car.source, car.listing_id)
        if key in seen:
            continue
        dealer = (car.dealer_name or "").strip().lower()
        if dealer and max_per_dealer and per_dealer.get(dealer, 0) >= max_per_dealer:
            continue
        seen.add(key)
        if dealer:
            per_dealer[dealer] = per_dealer.get(dealer, 0) + 1
        out.append(car)
    return out


def _rating_and_source(car: Car):
    """The rating we judge a dealer by. The on-site (Cars.com) dealer rating is
    the reliable, primary signal; the external Google/BBB check is only a
    fallback when there is no on-site rating, and a corroborating column
    otherwise. A failed external lookup must NEVER override a good on-site
    rating."""
    if car.dealer_rating is not None:
        return car.dealer_rating, car.dealer_review_count, "on-site"
    if car.ext_rating is not None:
        return car.ext_rating, car.ext_review_count, car.ext_source or "external"
    return None, None, ""


def _reputation_pass(car: Car, cfg: dict) -> bool:
    """Apply the chosen reputation policy.

    Policy "keep_flag" (this build): keep everything, but annotate. Unrated
    private/Craigslist listings are flagged for eyeballing; dealers below the
    threshold are flagged as risky but NOT dropped.
    """
    min_rating = cfg.get("min_dealer_rating")
    min_reviews = cfg.get("min_dealer_reviews")
    policy = cfg.get("reputation_policy", "keep_flag")

    rating, reviews, src = _rating_and_source(car)

    # No reputation data at all (private seller / Craigslist / dealer not found).
    if rating is None:
        seller = car.seller_type or "unknown seller"
        car.reputation_flag = f"unrated ({seller}) — verify manually"
        if policy == "drop_unrated":
            return False
        if policy == "private_ok_drop_bad_dealers":
            # keep: there is no dealer rating to fail against
            return True
        return True  # keep_flag

    # We have a rating. Decide pass/flag against thresholds. Only enforce the
    # review-count bar when we actually know the count.
    below = False
    if min_rating is not None and rating < float(min_rating):
        below = True
    if min_reviews is not None and reviews is not None and reviews < int(min_reviews):
        below = True

    # If an external rating exists and disagrees, note it for transparency.
    corroborate = ""
    if src == "on-site" and car.ext_rating is not None:
        corroborate = f"; Google {car.ext_rating}/5"

    if below:
        car.reputation_flag = f"LOW reputation ({rating}/5 via {src}{corroborate}) — caution"
        if policy in ("drop_unrated", "private_ok_drop_bad_dealers"):
            return False
        return True  # keep_flag: keep but flagged
    car.reputation_flag = f"ok ({rating}/5 via {src}{corroborate})"
    return True


def apply_filters(cars: List[Car], cfg: dict) -> List[Car]:
    rep_cfg = cfg.get("reputation", {})
    lookup = ReputationLookup(
        enabled=bool(rep_cfg.get("external_check", True)),
        method=rep_cfg.get("method", "requests"),
        delay_seconds=float(rep_cfg.get("delay_seconds", 2.0)),
        headless=bool(cfg.get("headless", True)),
        api_key=rep_cfg.get("api_key", ""),
    )

    try:
        kept = _run_filters(cars, cfg, rep_cfg, lookup)
    finally:
        lookup.close()

    if cfg.get("dedupe", True):
        kept = _dedupe(kept, int(cfg.get("max_per_dealer", 0) or 0))
    return kept


def _run_filters(cars, cfg, rep_cfg, lookup) -> List[Car]:
    price = cfg.get("price", {})
    year = cfg.get("year", {})
    max_mileage = cfg.get("max_mileage")
    radius = cfg.get("radius_miles")
    wanted = cfg.get("vehicles", [])

    kept = []
    for car in cars:
        if not _in_range(car.price, price.get("min"), price.get("max")):
            continue
        if not _in_range(car.year, year.get("min"), year.get("max")):
            continue
        if max_mileage is not None and car.mileage is not None and car.mileage > max_mileage:
            continue
        if radius is not None and car.distance_miles is not None and car.distance_miles > radius:
            continue
        if not _make_model_ok(car, wanted):
            continue

        # Reputation: external cross-check for dealers, then policy decision.
        if car.seller_type == "dealer" and car.dealer_name:
            rep = lookup.lookup(car.dealer_name, car.location)
            if rep.rating is not None:
                car.ext_rating = rep.rating
                car.ext_review_count = rep.review_count
                car.ext_source = rep.source
        if not _reputation_pass(car, {**rep_cfg, "reputation_policy": rep_cfg.get("policy", "keep_flag")}):
            continue

        kept.append(car)

    return kept
