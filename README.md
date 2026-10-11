# CarWatch

Find used cars near you that match your criteria, from multiple sites at once,
with a dealer-reputation check, and track how each listing's price changes
between runs. Same architecture as `jobscraper`: pluggable
`sources/`, central `filters.py`, a `Car` dataclass, CSV output.

## Setup

```bash
cd carscraper
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/playwright install chromium   # only needed for cars_com / autotrader
```

## Configure

Copy `config.example.json` to `config.json` and edit it (`config.json` is gitignored so your
ZIP code and API key stay private):

- `sources` — any of `craigslist`, `cars_com`, `autotrader`, `facebook`.
  Reliable pair: **craigslist + cars_com**. AutoTrader/Facebook often hit
  block/login walls and return nothing (by design — no evasion).
- `craigslist_site` — your nearest Craigslist subdomain (e.g. `indianapolis`,
  `bloomington`, `sfbay`).
- `zip_code` + `radius_miles` — "near me".
- `vehicles` — list of `{make, model}` you want. Model optional.
- `price` / `year` / `max_mileage` — your filters.
- `reputation`:
  - `external_check` — look each dealer up on Google/BBB (slow, cached, best-effort).
  - `policy` — `keep_flag` (keep everything, annotate),
    `drop_unrated` (dealers above threshold only),
    `private_ok_drop_bad_dealers` (keep private, drop low-rated dealers).
  - `min_dealer_rating` / `min_dealer_reviews` — the bar a dealer must clear.

## Run

```bash
./.venv/bin/python run.py
```

Writes `cars.csv` and prints a sorted summary with a reputation flag per car.

## Price tracking

Every run stores the matched listings in a local SQLite file (`history.db`,
set with `history_db` in the config). A price is only written when it changes,
so the `prices` table is a change log. After each run you get a summary like:

```
Since the last run: 3 new, 1 price drops, 0 price increases
  DROP  2023 Volkswagen Tiguan 2.0T SE: $29,245 -> $28,500 (-745)
```

Run it on a schedule (cron or launchd) to watch prices over time.

## Tests

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

## Reality check

- Each car keeps the on-site dealer rating where available; for dealers we also
  cross-check Google/BBB. **Private sellers and all Craigslist listings have no
  reputation data** — they're flagged `unrated`, never silently trusted.
- The external check parses public pages politely with no evasion and caches
  results in `.reputation_cache.json`. Treat ratings as a hint, not gospel.
- Scrapers break when sites change their markup; the CSS selectors in
  `sources/*.py` are where you'd adjust.
```

## Responsible use

This tool is for personal use. Check each site's terms of use before scraping,
keep the request rate low (see `delay_seconds`), and do not try to evade blocks
or log-in walls. If a site blocks the scraper, the source returns nothing.
