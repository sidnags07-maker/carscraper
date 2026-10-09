"""External dealer-reputation cross-check (Google / BBB), best-effort.

Two backends:
  * "requests" — a single polite HTTP GET. Fast, but Google usually serves a
    consent / anti-bot wall to non-browser clients, so it rarely returns data.
  * "browser"  — drive the real Chromium (Playwright) with Google's CONSENT
    cookie pre-set to skip the interstitial. Slower, but actually renders the
    rating. One browser is shared across all lookups in a run.

Either way: NO evasion beyond a normal UA + consent cookie, results are cached
to disk, and on a block/consent page we return *unknown* rather than inventing a
rating. Treat the external rating as a hint, not ground truth.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Optional

import requests

CACHE_PATH = os.path.join(os.path.dirname(__file__), ".reputation_cache.json")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Phrases meaning Google served a consent / anti-bot wall, not a result page.
_GOOGLE_BLOCK = (
    "unusual traffic", "/sorry/", "before you continue", "enablejs",
    "detected unusual", "our systems have detected",
)


@dataclass
class Reputation:
    rating: Optional[float] = None     # 0..5
    review_count: Optional[int] = None
    source: str = ""                   # "google" | "bbb" | "" (unknown)


def _parse_google(low: str) -> Reputation:
    """Pull a business rating out of Google result HTML (lowercased). Requires
    the rating to sit next to a review count so we don't match stray digits."""
    m = re.search(
        r"\b([1-5](?:\.\d))\b[^\d]{0,8}\(?\s*([\d,]{2,7})\s*(?:google\s+)?review",
        low,
    )
    if m and float(m.group(1)) > 0:
        return Reputation(float(m.group(1)),
                          int(m.group(2).replace(",", "")), "google")
    m2 = re.search(r"rated\s+([1-5](?:\.\d))\s+out of\s+5", low)
    if m2 and float(m2.group(1)) > 0:
        return Reputation(float(m2.group(1)), None, "google")
    return Reputation()


class ReputationLookup:
    """Caches per-dealer lookups in memory and on disk. Call close() when done
    (browser backend holds a live Chromium until then)."""

    def __init__(self, enabled: bool = True, method: str = "requests",
                 delay_seconds: float = 2.0, headless: bool = True,
                 api_key: str = ""):
        self.enabled = enabled
        self.method = method
        self.delay = delay_seconds
        self.headless = headless
        # Places API key: explicit config wins, else environment.
        self.api_key = api_key or os.environ.get("GOOGLE_PLACES_API_KEY", "")
        self._mem: dict[str, Reputation] = {}
        self._disk = self._load_cache()
        self._pw = self._browser = self._ctx = self._page = None

    def lookup(self, dealer_name: str, location: str = "") -> Reputation:
        if not self.enabled or not dealer_name:
            return Reputation()
        key = f"{dealer_name.lower().strip()}|{location.lower().strip()}"
        if key in self._mem:
            return self._mem[key]
        if key in self._disk:
            rep = Reputation(**self._disk[key])
            self._mem[key] = rep
            return rep

        if self.method == "places":
            rep = self._fetch_places(dealer_name, location)
        elif self.method == "browser":
            rep = self._fetch_google_browser(dealer_name, location)
        else:
            rep = self._fetch_google_requests(dealer_name, location)
        if rep.rating is None and self.method != "places":
            rep = self._fetch_bbb(dealer_name, location)

        self._mem[key] = rep
        self._disk[key] = rep.__dict__
        self._save_cache()
        time.sleep(self.delay)  # be polite between external lookups
        return rep

    # ---- google places api (legitimate, ToS-compliant) ---------------------

    def _fetch_places(self, name: str, location: str) -> Reputation:
        """Official Google Places API. Returns a real rating + review count and
        is NOT blocked (unlike scraping the SERP). Needs a free API key in
        GOOGLE_PLACES_API_KEY or reputation.api_key."""
        if not self.api_key:
            return Reputation()  # no key -> unknown (caller still has on-site)
        url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
        params = {
            "input": f"{name} {location}",
            "inputtype": "textquery",
            "fields": "rating,user_ratings_total,name",
            "key": self.api_key,
        }
        try:
            r = requests.get(url, params=params, timeout=15)
            data = r.json()
        except (requests.RequestException, ValueError):
            return Reputation()
        cands = data.get("candidates") or []
        if not cands or "rating" not in cands[0]:
            return Reputation()
        c = cands[0]
        return Reputation(rating=float(c["rating"]),
                          review_count=c.get("user_ratings_total"),
                          source="google_places")

    # ---- google: requests backend ------------------------------------------

    def _fetch_google_requests(self, name: str, location: str) -> Reputation:
        url = self._google_url(name, location)
        html = self._get(url)
        low = html.lower()
        if not html or any(b in low for b in _GOOGLE_BLOCK):
            return Reputation()
        return _parse_google(low)

    # ---- google: browser backend -------------------------------------------

    def _ensure_browser(self) -> bool:
        if self._page is not None:
            return True
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("  ! reputation: playwright not installed; external check off")
            return False
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._ctx = self._browser.new_context(user_agent=USER_AGENT, locale="en-US")
        # Pre-accept Google's consent interstitial so the SERP renders.
        self._ctx.add_cookies([
            {"name": "CONSENT", "value": "YES+cb", "domain": ".google.com", "path": "/"},
            {"name": "SOCS", "value": "CAISNQgDEitib3FfaWRlbnRpdHlmcm9udGVuZA", "domain": ".google.com", "path": "/"},
        ])
        self._page = self._ctx.new_page()
        return True

    def _fetch_google_browser(self, name: str, location: str) -> Reputation:
        if not self._ensure_browser():
            return Reputation()
        url = self._google_url(name, location)
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
            self._page.wait_for_timeout(1200)
            # If a consent dialog still appears, try to accept it once.
            low = self._page.content().lower()
            if "before you continue" in low or "consent.google" in self._page.url:
                for label in ("Accept all", "I agree", "Reject all"):
                    btn = self._page.query_selector(f"button:has-text('{label}')")
                    if btn:
                        btn.click()
                        self._page.wait_for_timeout(1000)
                        break
            html = self._page.content()
        except Exception:
            return Reputation()
        low = html.lower()
        if any(b in low for b in _GOOGLE_BLOCK):
            return Reputation()
        return _parse_google(low)

    def _google_url(self, name: str, location: str) -> str:
        q = urllib.parse.quote_plus(f"{name} {location} car dealer reviews")
        return f"https://www.google.com/search?hl=en&gl=us&q={q}"

    # ---- bbb ----------------------------------------------------------------

    def _fetch_bbb(self, name: str, location: str) -> Reputation:
        """BBB exposes a letter grade (A+..F); map it onto a rough 0..5 so it
        composes with the rating threshold."""
        q = urllib.parse.quote_plus(f"{name} {location}")
        html = self._get(f"https://www.bbb.org/search?find_text={q}")
        if not html:
            return Reputation()
        m = re.search(r'BBB Rating[^A-F]{0,40}?\b(A\+|A|B\+|B|C\+|C|D|F)\b', html)
        if not m:
            return Reputation()
        grade_to_5 = {"A+": 5.0, "A": 4.5, "B+": 4.0, "B": 3.5,
                      "C+": 3.0, "C": 2.5, "D": 2.0, "F": 1.0}
        return Reputation(rating=grade_to_5.get(m.group(1)), source="bbb")

    # ---- io / lifecycle -----------------------------------------------------

    def _get(self, url: str) -> str:
        try:
            r = requests.get(
                url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US"},
                timeout=15,
            )
            if r.status_code == 200:
                return r.text
        except requests.RequestException:
            pass
        return ""

    def close(self) -> None:
        for obj, meth in ((self._ctx, "close"), (self._browser, "close"),
                          (self._pw, "stop")):
            try:
                if obj is not None:
                    getattr(obj, meth)()
            except Exception:
                pass
        self._pw = self._browser = self._ctx = self._page = None

    def _load_cache(self) -> dict:
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self) -> None:
        try:
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(self._disk, f, indent=2)
        except OSError:
            pass
