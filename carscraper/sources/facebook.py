"""Facebook Marketplace source (Playwright, best-effort).

Marketplace requires a logged-in session and aggressively blocks automation;
its ToS prohibits scraping. This module does NOT log in or evade anything. It
makes a single anonymous attempt and, as expected, will almost always hit a
login/auth wall — at which point it says so plainly and returns nothing.

Included for completeness so the source list is uniform. For real Marketplace
data you would have to browse manually. Leave this disabled unless you know
what you're doing.
"""
from __future__ import annotations

import time
import urllib.parse
from typing import List

from ..models import Car

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
LOGIN_MARKERS = ("log in", "log into facebook", "you must log in", "/login")


class FacebookSource:
    name = "facebook"

    def fetch(self, cfg: dict) -> List[Car]:
        from playwright.sync_api import sync_playwright

        zip_code = cfg.get("zip_code", "")
        radius = int(cfg.get("radius_miles", 50))
        # Marketplace search by location is normally city-based; this anonymous
        # URL is best-effort and expected to redirect to a login wall.
        params = {"query": "cars", "radius": radius}
        url = f"https://www.facebook.com/marketplace/category/vehicles?{urllib.parse.urlencode(params)}"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=cfg.get("headless", True))
            ctx = browser.new_context(user_agent=USER_AGENT, locale="en-US")
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)
                html = page.content().lower()
            except Exception as e:
                print(f"  ! [facebook] page failed: {e}")
                html = ""
            ctx.close()
            browser.close()

        if not html or any(m in html for m in LOGIN_MARKERS):
            print("  ! [facebook] login/auth wall (expected). Marketplace requires "
                  "a session; returning nothing. Browse it manually.")
            return []

        # If Facebook ever serves anonymous results, we'd parse them here.
        print("  ! [facebook] no parseable anonymous results.")
        return []
