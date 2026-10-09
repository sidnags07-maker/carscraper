"""Cars.com source (Playwright, best-effort).

Cars.com renders listing cards that include the seller type and, for dealers, a
star rating and review count — exactly the on-site reputation signal we want.
It does run bot-detection; this module makes a polite, single-browser attempt
with NO evasion and reports clearly if it is blocked, returning nothing rather
than fighting a challenge (same posture as the jobscraper's Indeed source).
"""
from __future__ import annotations

import json
import random
import re
import time
import urllib.parse
from typing import List

from bs4 import BeautifulSoup

from ..models import Car

BASE = "https://www.cars.com"
SEARCH = "https://www.cars.com/shopping/results/"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

BLOCK_MARKERS = (
    "verifying you are human", "are you a robot", "/challenge",
    "px-captcha", "hcaptcha", "recaptcha", "access denied",
)


class CarsComSource:
    name = "cars_com"

    def _search_url(self, cfg: dict, page: int) -> str:
        vehicles = cfg.get("vehicles", [])
        params = [
            ("stock_type", "all"),
            ("zip", cfg.get("zip_code", "")),
            ("maximum_distance", int(cfg.get("radius_miles", 50))),
            ("page", page),
            ("page_size", 20),
            ("sort", "best_match_desc"),
        ]
        price = cfg.get("price", {})
        if price.get("max") is not None:
            params.append(("list_price_max", price["max"]))
        if price.get("min") is not None:
            params.append(("list_price_min", price["min"]))
        year = cfg.get("year", {})
        if year.get("min") is not None:
            params.append(("year_min", year["min"]))
        if year.get("max") is not None:
            params.append(("year_max", year["max"]))
        if cfg.get("max_mileage") is not None:
            params.append(("mileage_max", cfg["max_mileage"]))
        for v in vehicles:
            if v.get("make"):
                params.append(("makes[]", v["make"].lower()))
            if v.get("model"):
                params.append(("models[]", f"{v['make'].lower()}-{v['model'].lower()}"))
        return f"{SEARCH}?{urllib.parse.urlencode(params)}"

    def fetch(self, cfg: dict) -> List[Car]:
        from playwright.sync_api import sync_playwright

        lo, hi = cfg.get("delay_seconds", [2.5, 5.0])
        out: dict[str, Car] = {}
        blocked = False

        with sync_playwright() as p:
            # --disable-http2 avoids intermittent ERR_HTTP2_PROTOCOL_ERROR that
            # Cars.com's edge throws on automated connections.
            browser = p.chromium.launch(
                headless=cfg.get("headless", True),
                args=["--disable-http2"],
            )
            ctx = browser.new_context(user_agent=USER_AGENT, locale="en-US")
            page = ctx.new_page()
            for page_idx in range(1, cfg.get("max_pages", 3) + 1):
                url = self._search_url(cfg, page_idx)
                cars, blocked = self._scrape_page(page, url)
                if blocked or not cars:
                    break
                for car in cars:
                    out.setdefault(car.listing_id, car)
                print(f"    [cars_com] {len(out)} listings so far")
                time.sleep(random.uniform(lo, hi))
            ctx.close()
            browser.close()

        if blocked:
            print("  ! [cars_com] served a block / verification page. Stopping "
                  "(no evasion). Try headless:false or rely on craigslist.")
        return list(out.values())

    def _scrape_page(self, page, url: str):
        # Retry transient navigation errors (HTTP/2 resets, timeouts) a couple
        # of times before giving up on the page.
        last_err = None
        for attempt in range(3):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)
                break
            except Exception as e:
                last_err = e
                time.sleep(2 + attempt * 2)
        else:
            print(f"  ! [cars_com] page failed after retries: {last_err}")
            return [], False

        html = page.content()
        low = html.lower()
        # Results render as <fuse-card data-listing-id ...>. If those are absent
        # AND a challenge marker is present, treat it as a real block.
        if "data-listing-id" not in low and any(m in low for m in BLOCK_MARKERS):
            return [], True

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("[data-listing-id][data-vehicle-details]")
        return [c for c in (self._parse_card(n) for n in cards) if c], False

    def _parse_card(self, card) -> Car | None:
        """Cars.com embeds the structured listing in a `data-vehicle-details`
        JSON blob (price, year/make/model/trim, mileage, vin, stockType). The
        dealer name, star rating, and distance live in the rendered DOM."""
        raw = card.get("data-vehicle-details")
        if not raw:
            return None
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            return None

        def _int(v):
            try:
                return int(str(v).replace(",", ""))
            except (TypeError, ValueError):
                return None

        price = _int(d.get("price"))
        if price == 0:
            price = None
        year = _int(d.get("year"))
        mileage = _int(d.get("mileage"))
        make = (d.get("make") or "").lower()
        model = d.get("model") or ""
        trim = d.get("trim") or ""

        link = card.select_one("a[href]")
        href = link.get("href", "") if link else ""
        if href.startswith("/"):
            href = BASE + href

        # Dealer rating: the `.review-star` datum holds e.g. "4.9".
        rating_el = card.select_one(".review-star")
        rating = None
        if rating_el:
            try:
                rating = float(rating_el.get_text(strip=True))
            except ValueError:
                rating = None
        # Dealer name: the <p>/span immediately preceding the rating widget.
        dealer_name = ""
        if rating_el:
            prev = rating_el.find_previous("p")
            dealer_name = prev.get_text(strip=True) if prev else ""

        # Location + distance: the footer reads "Town, ST (33 mi)".
        location, distance = "", None
        foot = card.select_one("[slot=footer]")
        if foot:
            m = re.search(r"(.*?)\s*\((\d+)\s*mi\)", foot.get_text(" ", strip=True))
            if m:
                location, distance = m.group(1).strip(), float(m.group(2))

        title = f"{year or ''} {make.title()} {model} {trim}".strip()
        return Car(
            source=self.name,
            listing_id=d.get("listingId") or d.get("vin") or href,
            title=title,
            url=href or BASE,
            price=price,
            year=year,
            make=make,
            model=model,
            trim=trim,
            mileage=mileage,
            location=location,
            distance_miles=distance,
            seller_type="dealer" if dealer_name else "private",
            dealer_name=dealer_name,
            dealer_rating=rating,
        )
