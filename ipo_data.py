"""Fetch IPO data for the 'IPO Watch' section — upcoming issues + a
30-to-60-day post-listing report card.

Sources:
  - upcoming / live IPOs → NSE public JSON APIs (/api/all-upcoming-issues +
    /api/ipo-current-issue), reached via the warmed-up session market_data.py
    uses. These carry the applicant-facing fields (price band, lot, dates).
  - recently-listed IPOs → screener.in/ipo/recent/ (public, paginated HTML).
    screener has an IPO price + live current price for EVERY listed company —
    NSE mainboard AND SME alike — which is what lets us show real performance
    for the small-cap SME names that don't resolve on Fyers or Yahoo.

Everything fails soft: any source that is down just yields fewer rows, and the
writer / publisher still produce *something*. Output → data/ipo.json.

This module computes NUMBERS only. It never forms an opinion — the reports built
on top of it are strictly educational (no buy/sell/subscribe/avoid calls).
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
from pathlib import Path

import requests

import market_data as md  # reuse the warmed NSE session + shared UA

HERE = Path(__file__).parent
OUT = HERE / "data" / "ipo.json"

NSE = "https://www.nseindia.com"
UPCOMING_URL = f"{NSE}/api/all-upcoming-issues?category=ipo"
CURRENT_URL = f"{NSE}/api/ipo-current-issue"

SCREENER_RECENT = "https://www.screener.in/ipo/recent/?page={p}"
SCREENER_HEADERS = {
    "User-Agent": md.HEADERS["User-Agent"],
    "Accept-Language": "en-US,en;q=0.9",
}
MAX_PAGES = 8   # ~25 rows/page; 8 pages comfortably covers 60 days of listings

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
    low = raw.lower()
    if low == "today":
        return dt.date.today()
    if low == "yesterday":
        return dt.date.today() - dt.timedelta(days=1)
    # NSE returns "%d-%b-%Y" ("07-Jul-2026"); screener uses "10 Jul 2026".
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d-%m-%Y",
                "%d %b %Y", "%d %B %Y"):
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
# recently-listed IPOs → 30-to-60-day report card (screener.in)
# ------------------------------------------------------------------

def _screener_get(url: str) -> str:
    try:
        r = requests.get(url, headers=SCREENER_HEADERS, timeout=25)
        r.raise_for_status()
        return r.text
    except Exception as e:  # noqa: BLE001 — fail soft
        print(f"  screener fetch failed ({url}): {e}", file=sys.stderr)
        return ""


def _text(cell: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", cell)).strip()


def _parse_screener_recent(page_html: str) -> list[dict]:
    """Parse one /ipo/recent/ page. Columns:
    Name | Listing Date | IPO MCap Rs.Cr | IPO Price | Current Price | % Change.
    """
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page_html, re.S)[1:]:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 6:
            continue
        name = re.sub(r"\s+", " ", _text(tds[0]))
        cid = re.search(r"/company/([^/\"']+)/", tds[0])
        rows.append({
            "name": name,
            "screener_id": cid.group(1) if cid else "",
            "listing_raw": _text(tds[1]),
            "mcap_cr": _num(_text(tds[2])),
            "issue_price": _num(_text(tds[3])),
            "current_price": _num(_text(tds[4])),
        })
    return rows


def fetch_recent_listings() -> list[dict]:
    """Recently-listed IPOs (mainboard + SME) with real performance, from
    screener.in. Pages are newest-first; we stop once a page is entirely older
    than the lookback window."""
    today = dt.date.today()
    listings, seen = [], set()
    for p in range(1, MAX_PAGES + 1):
        page_html = _screener_get(SCREENER_RECENT.format(p=p))
        if not page_html:
            break
        rows = _parse_screener_recent(page_html)
        if not rows:
            break
        oldest_age = -1
        for r in rows:
            listing_d = _parse_date(r["listing_raw"])
            if not listing_d:
                continue
            age = (today - listing_d).days
            oldest_age = max(oldest_age, age)
            if age < 0 or age > LOOKBACK_DAYS:
                continue  # not yet listed, or older than the window
            issue, cur = r["issue_price"], r["current_price"]
            if not (issue and cur):
                continue  # price not populated yet
            key = r["screener_id"] or r["name"].upper()
            if key in seen:
                continue
            seen.add(key)
            listings.append({
                "company": r["name"],
                "screener_id": r["screener_id"],
                "issue_price": issue,
                "current_price": cur,
                "return_vs_issue_pct": round((cur - issue) / issue * 100, 1),
                "ipo_mcap_cr": r["mcap_cr"],
                "listing_date": listing_d.isoformat(),
                "days_since_listing": age,
                "in_window": WINDOW_LO < age < WINDOW_HI,
            })
        # Rows are newest-first; once the whole page predates the lookback
        # window there's nothing more to collect.
        if oldest_age > LOOKBACK_DAYS:
            break

    # In-window cohort (30-60 days) first, then the rest by recency.
    listings.sort(key=lambda x: (not x["in_window"], x["days_since_listing"]))
    return listings


def main() -> int:
    session = md._nse_session()
    print("Fetching upcoming IPOs...")
    upcoming = fetch_upcoming(session)
    print(f"  -> {len(upcoming)} upcoming/live")
    print("Fetching recently-listed IPOs (screener.in)...")
    recent = fetch_recent_listings()
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
