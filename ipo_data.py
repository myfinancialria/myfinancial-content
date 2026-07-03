"""Fetch IPO data for the 'IPO Watch' section — upcoming issues + a
one-month-on report card for recently-listed IPOs.

Sources (all public NSE JSON APIs, reached via the same warmed-up session that
market_data.py uses):
  - upcoming / live IPOs → /api/all-upcoming-issues + /api/ipo-current-issue
  - recently-listed IPOs → /api/public-past-issues

Recently-listed issues are enriched (best-effort) with the current market price
via Fyers so we can show how they have done since their IPO price and since
listing. Listing-day open/close is pulled from Fyers daily history when a token
is available.

Everything fails soft: any source that is down just yields fewer rows, and the
writer / publisher still produce *something*. Output → data/ipo.json.

This module computes NUMBERS only. It never forms an opinion — the reports built
on top of it are strictly educational (no buy/sell/subscribe/avoid calls).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import market_data as md  # reuse NSE session + Fyers helpers

HERE = Path(__file__).parent
OUT = HERE / "data" / "ipo.json"

NSE = "https://www.nseindia.com"
UPCOMING_URL = f"{NSE}/api/all-upcoming-issues?category=ipo"
CURRENT_URL = f"{NSE}/api/ipo-current-issue"
PAST_URL = f"{NSE}/api/public-past-issues"

# How far back a "recently listed" IPO can be and still make the report card.
LOOKBACK_DAYS = 60
# The performance window for the report: listed MORE THAN 30 and LESS THAN 60
# days ago (long enough for the listing-day frenzy to settle, still recent).
WINDOW_LO, WINDOW_HI = 30, 60


# ------------------------------------------------------------------
# small helpers
# ------------------------------------------------------------------

def _get(session, url: str):
    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001 — fail soft on any source
        print(f"  IPO fetch failed ({url}): {e}", file=sys.stderr)
        return []
    # NSE sometimes wraps the list in {"data": [...]}.
    if isinstance(data, dict):
        for key in ("data", "upcoming", "records"):
            if isinstance(data.get(key), list):
                return data[key]
        return []
    return data if isinstance(data, list) else []


def _pick(row: dict, *keys: str) -> str:
    for k in keys:
        v = row.get(k)
        if v not in (None, "", "-"):
            return str(v).strip()
    return ""


def _parse_date(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return None
    # NSE returns "%d-%b-%Y" ("07-Jul-2026") and occasionally ISO.
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d-%m-%Y", "%d %b %Y"):
        try:
            return dt.datetime.strptime(raw.split("T")[0], fmt).date()
        except ValueError:
            continue
    return None


def _num(raw: str):
    """Pull the first number out of a messy string like '₹ 100 - 105' → 100.0."""
    if raw is None:
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", str(raw).replace(",", ""))
    return float(m.group()) if m else None


# ------------------------------------------------------------------
# upcoming / live IPOs
# ------------------------------------------------------------------

def fetch_upcoming(session) -> list[dict]:
    rows = _get(session, UPCOMING_URL) + _get(session, CURRENT_URL)
    out, seen = [], set()
    today = dt.date.today()
    for row in rows:
        symbol = _pick(row, "symbol", "sr_no").upper()
        company = _pick(row, "companyName", "company", "name", "issuerName")
        if not company and not symbol:
            continue
        key = (symbol or company).upper()
        if key in seen:
            continue
        seen.add(key)

        open_d = _parse_date(_pick(row, "issueStartDate", "issue_start_date",
                                   "startDate"))
        close_d = _parse_date(_pick(row, "issueEndDate", "issue_end_date",
                                    "endDate"))
        # Drop anything that already closed more than a couple of days ago.
        if close_d and (today - close_d).days > 2:
            continue

        series = _pick(row, "series").upper()
        seg = "SME" if series in {"SME", "SM"} else "Mainboard"

        out.append({
            "company": company or symbol,
            "symbol": symbol,
            "segment": seg,
            "price_band": _pick(row, "issuePrice", "priceBand", "price"),
            "lot_size": _pick(row, "lotSize", "lot_size", "marketLot"),
            "issue_size": _pick(row, "issueSize", "issue_size", "totalIssueSize"),
            "open_date": open_d.isoformat() if open_d else "",
            "close_date": close_d.isoformat() if close_d else "",
            "status": _pick(row, "status") or (
                "Open" if open_d and close_d and open_d <= today <= close_d
                else "Upcoming"),
        })

    # Sort: currently-open first, then by soonest open date.
    def _sort_key(x):
        od = _parse_date(x["open_date"]) or dt.date.max
        return (0 if x["status"].lower().startswith("open") else 1, od)

    out.sort(key=_sort_key)
    return out


# ------------------------------------------------------------------
# recently-listed IPOs → one-month report card
# ------------------------------------------------------------------

def _fyers_daily_on(fyers, symbol: str, day: dt.date):
    """Best-effort: return the listing-day {open, close} for a symbol."""
    if not fyers or not symbol:
        return {}
    try:
        resp = fyers.history(data={
            "symbol": f"NSE:{symbol}-EQ",
            "resolution": "D",
            "date_format": "1",
            "range_from": day.isoformat(),
            "range_to": (day + dt.timedelta(days=3)).isoformat(),
            "cont_flag": "1",
        })
    except Exception as e:  # noqa: BLE001
        print(f"  history {symbol} failed: {e}", file=sys.stderr)
        return {}
    candles = resp.get("candles") if isinstance(resp, dict) else None
    if not candles:
        return {}
    o, c = candles[0][1], candles[0][4]  # [ts, o, h, l, c, v]
    return {"open": float(o), "close": float(c)}


def fetch_recent_listings(session) -> list[dict]:
    rows = _get(session, PAST_URL)
    today = dt.date.today()
    listings = []
    for row in rows:
        listing_d = _parse_date(_pick(row, "dateOfListing", "listingDate",
                                      "date_of_listing"))
        if not listing_d:
            continue
        age = (today - listing_d).days
        if not (0 <= age <= LOOKBACK_DAYS):
            continue
        symbol = _pick(row, "symbol").upper()
        issue_price = _num(_pick(row, "issuePrice", "issue_price", "finalPrice",
                                 "price"))
        listings.append({
            "company": _pick(row, "companyName", "company", "name") or symbol,
            "symbol": symbol,
            "series": _pick(row, "series").upper(),
            "issue_price": issue_price,
            "listing_date": listing_d.isoformat(),
            "days_since_listing": age,
        })

    if not listings:
        return []

    # Enrich with current price (Fyers) + listing-day open (Fyers history).
    fyers = None
    try:
        fyers = md.fyers_client()
    except SystemExit:
        print("  Fyers token missing — skipping price enrichment",
              file=sys.stderr)

    quotes = {}
    if fyers:
        syms = [f"NSE:{l['symbol']}-EQ" for l in listings if l["symbol"]]
        quotes = md.fyers_quotes(fyers, syms)

    for l in listings:
        q = quotes.get(f"NSE:{l['symbol']}-EQ", {})
        cur = q.get("lp") or None
        l["current_price"] = cur
        issue = l["issue_price"]
        l["return_vs_issue_pct"] = (
            round((cur - issue) / issue * 100, 1)
            if cur and issue else None)

        listing_px = _fyers_daily_on(
            fyers, l["symbol"], dt.date.fromisoformat(l["listing_date"]))
        l_open = listing_px.get("open")
        l["listing_open"] = l_open
        l["listing_gain_pct"] = (
            round((l_open - issue) / issue * 100, 1)
            if l_open and issue else None)
        l["return_since_listing_pct"] = (
            round((cur - l_open) / l_open * 100, 1)
            if cur and l_open else None)
        l["in_window"] = WINDOW_LO < l["days_since_listing"] < WINDOW_HI

    # In-window cohort (30-60 days) first, then the rest by recency.
    listings.sort(key=lambda x: (not x["in_window"], x["days_since_listing"]))
    return listings


def main() -> int:
    session = md._nse_session()
    print("Fetching upcoming IPOs...")
    upcoming = fetch_upcoming(session)
    print(f"  -> {len(upcoming)} upcoming/live")
    print("Fetching recently-listed IPOs...")
    recent = fetch_recent_listings(session)
    print(f"  -> {len(recent)} listed in last {LOOKBACK_DAYS}d "
          f"({sum(r['in_window'] for r in recent)} in the 30-60 day window)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
        "upcoming": upcoming,
        "recent_listings": recent,
    }, indent=2, default=str))
    print(f"Wrote {OUT}")
    return 0 if (upcoming or recent) else 1


if __name__ == "__main__":
    raise SystemExit(main())
