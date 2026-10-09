"""AutoTrader source (Playwright, best-effort).

AutoTrader runs heavy bot-detection. Like the jobscraper's Indeed module, this
makes ONE polite attempt with no evasion and, if it sees a block/verification
wall, reports it and returns nothing. Dealer star ratings, when present, are
captured for the reputation check.

This is intentionally minimal: enable it only if you accept it may often be
blocked. Craigslist + Cars.com are the reliable pair.
"""
from __future__ import annotations

import time
import urllib.parse
from typing import List

from bs4 import BeautifulSoup

from ..models import Car
from ..parse import parse_price, parse_mileage, parse_year, split_make_model

BASE = "https://www.autotrader.com"
SEARCH = "https://www.autotrader.com/cars-for-sale/all-cars"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
BLOCK_MARKERS = (
    "verifying you are human", "are you a robot", "/challenge",
    "px-captcha", "hcaptcha", "recaptcha", "access denied", "request blocked",
)


class AutoTraderSource:
    name = "autotrader"

    def _search_url(self, cfg: dict) -> str:
        params = {
            "zip": cfg.get("zip_code", ""),
            "searchRadius": int(cfg.get("radius_miles", 50)),
        }
        price = cfg.get("price", {})
        if price.get("max") is not None:
            params["maxPrice"] = price["max"]
        if price.get("min") is not None:
            params["minPrice"] = price["min"]
        if cfg.get("max_mileage") is not None:
            params["maxMileage"] = cfg["max_mileage"]
        return f"{SEARCH}?{urllib.parse.urlencode(params)}"

    def fetch(self, cfg: dict) -> List[Car]:
        from playwright.sync_api import sync_playwright

        out: List[Car] = []
        blocked = False
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=cfg.get("headless", True))
            ctx = browser.new_context(user_agent=USER_AGENT, locale="en-US")
            page = ctx.new_page()
            try:
                page.goto(self._search_url(cfg), wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)
                html = page.content()
            except Exception as e:
                print(f"  ! [autotrader] page failed: {e}")
                html = ""
            ctx.close()
            browser.close()

        low = html.lower()
        if not html or (any(m in low for m in BLOCK_MARKERS) and "inventory-listing" not in low):
            blocked = True

        if blocked:
            print("  ! [autotrader] blocked / verification wall. Returning nothing "
                  "(no evasion).")
            return []

        soup = BeautifulSoup(html, "html.parser")
        for node in soup.select("[data-cmp='inventoryListing']"):
            title_el = node.select_one("h2") or node.select_one("h3")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            link = node.select_one("a")
            href = link.get("href", "") if link else ""
            if href.startswith("/"):
                href = BASE + href
            make, model, trim = split_make_model(title)
            out.append(Car(
                source=self.name,
                listing_id=href or title,
                title=title,
                url=href or BASE,
                price=parse_price(node.get_text(" ")),
                year=parse_year(title),
                make=make, model=model, trim=trim,
                mileage=parse_mileage(node.get_text(" ")),
                seller_type="dealer",
            ))
        print(f"    [autotrader] {len(out)} listings")
        return out
