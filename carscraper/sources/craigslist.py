"""Craigslist 'cars & trucks' source (requests + BeautifulSoup).

Craigslist serves plain server-rendered HTML and is the most scrape-friendly
source here. Listings are overwhelmingly PRIVATE sellers, so there is no dealer
rating to read — those rows get flagged 'unrated (private)' downstream.

We query the nearest Craigslist site by ZIP-derived subdomain if provided in
config, otherwise default to the configured `craigslist_site`.
"""
from __future__ import annotations

import random
import time
import urllib.parse
from typing import List

import requests
from bs4 import BeautifulSoup

from ..models import Car
from ..parse import parse_price, parse_mileage, parse_year, split_make_model

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class CraigslistSource:
    name = "craigslist"

    def _search_url(self, cfg: dict, start: int) -> str:
        site = cfg.get("craigslist_site", "sfbay")
        base = f"https://{site}.craigslist.org/search/cta"
        params = {"s": start}
        if cfg.get("zip_code"):
            params["postal"] = cfg["zip_code"]
        if cfg.get("radius_miles"):
            params["search_distance"] = int(cfg["radius_miles"])
        price = cfg.get("price", {})
        if price.get("min") is not None:
            params["min_price"] = price["min"]
        if price.get("max") is not None:
            params["max_price"] = price["max"]
        year = cfg.get("year", {})
        if year.get("min") is not None:
            params["min_auto_year"] = year["min"]
        if year.get("max") is not None:
            params["max_auto_year"] = year["max"]
        if cfg.get("max_mileage") is not None:
            params["max_auto_miles"] = cfg["max_mileage"]
        # Optional free-text query from the first wanted vehicle, if any.
        vehicles = cfg.get("vehicles", [])
        if vehicles:
            q = f"{vehicles[0].get('make','')} {vehicles[0].get('model','')}".strip()
            if q:
                params["query"] = q
        return f"{base}?{urllib.parse.urlencode(params)}"

    def fetch(self, cfg: dict) -> List[Car]:
        lo, hi = cfg.get("delay_seconds", [2.0, 4.0])
        out: dict[str, Car] = {}
        for page_idx in range(cfg.get("max_pages", 3)):
            url = self._search_url(cfg, page_idx * 120)
            cars = self._scrape_page(url)
            if not cars:
                break
            for car in cars:
                out.setdefault(car.listing_id, car)
            print(f"    [craigslist] {len(out)} listings so far")
            time.sleep(random.uniform(lo, hi))
        return list(out.values())

    def _scrape_page(self, url: str) -> List[Car]:
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  ! [craigslist] page failed: {e}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        # Craigslist has changed markup over time; try the common containers.
        nodes = soup.select("li.cl-static-search-result") or soup.select("li.cl-search-result")
        results = []
        for node in nodes:
            car = self._parse_node(node)
            if car:
                results.append(car)
        return results

    def _parse_node(self, node) -> Car | None:
        link = node.select_one("a")
        if not link:
            return None
        href = link.get("href", "")
        title = link.get_text(strip=True) or (node.get("title") or "")
        price_el = node.select_one(".price")
        loc_el = node.select_one(".location")

        price = parse_price(price_el.get_text() if price_el else title)
        year = parse_year(title)
        make, model, trim = split_make_model(title)

        listing_id = node.get("data-pid") or href
        return Car(
            source=self.name,
            listing_id=str(listing_id),
            title=title,
            url=href,
            price=price,
            year=year,
            make=make,
            model=model,
            trim=trim,
            mileage=parse_mileage(title),
            location=loc_el.get_text(strip=True) if loc_el else "",
            seller_type="private",  # Craigslist cta is overwhelmingly private
        )
