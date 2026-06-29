"""Fetch quarterly results calendar for Nifty 500 companies.

Sources:
  - NSE board meetings API (results + AGM + others; we filter to results)
  - BSE forthcoming results as a fallback

Output: data/results.json with two buckets — today and upcoming (next 7 days).
"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Iterable

import requests

import nifty500

NSE_HOME = "https://www.nseindia.com"
NSE_BOARD_MEETINGS = f"{NSE_HOME}/api/corporate-board-meetings?index=equities"
BSE_FORTH_RESULTS = (
    "https://api.bseindia.com/BseIndiaAPI/api/Corpforthcoming/w"
    "?ddlcategorys=R&ddlindustrys=&scripcode=&strSearch=S"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

OUT = Path(__file__).parent / "data" / "results.json"


def _nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get(NSE_HOME, timeout=15)
        time.sleep(1)
    except Exception as e:
        print(f"NSE warmup failed: {e}")
    return s


def _looks_like_results(purpose: str) -> bool:
    p = (purpose or "").lower()
    keys = ("financial result", "audited", "unaudited", "quarterly", "q1 ", "q2 ",
            "q3 ", "q4 ", "annual result", "standalone", "consolidated")
    return any(k in p for k in keys)


def fetch_nse(n500: dict[str, str]) -> list[dict]:
    """Pull board meetings from NSE and keep only results-related ones in N500."""
    try:
        s = _nse_session()
        r = s.get(NSE_BOARD_MEETINGS, timeout=20)
        r.raise_for_status()
        data = r.json() or []
        out: list[dict] = []
        for d in data:
            sym = (d.get("bm_symbol") or d.get("symbol") or "").strip().upper()
            if sym not in n500:
                continue
            purpose = d.get("bm_purpose") or d.get("purpose") or ""
            if not _looks_like_results(purpose):
                continue
            out.append({
                "symbol": sym,
                "company": n500[sym],
                "date": (d.get("bm_date") or "").strip(),
                "purpose": purpose.strip(),
                "source": "NSE",
            })
        print(f"NSE results: {len(out)} N500 entries")
        return out
    except Exception as e:
        print(f"NSE results fetch failed: {e}")
        return []


def fetch_bse(n500: dict[str, str]) -> list[dict]:
    """BSE forthcoming results — used as a fallback / supplement.

    BSE doesn't expose NSE symbols, so we match on company-name prefix.
    """
    try:
        # Build a name -> symbol map for fuzzy matching
        rev = {name.lower().split()[0]: sym for sym, name in n500.items() if name}
        r = requests.get(BSE_FORTH_RESULTS, headers=HEADERS, timeout=20)
        r.raise_for_status()
        rows = r.json().get("Table", [])
        out: list[dict] = []
        for row in rows:
            name = (row.get("LONG_NAME") or row.get("SLONGNAME") or "").strip()
            first = name.lower().split()[0] if name else ""
            sym = rev.get(first)
            if not sym:
                continue
            out.append({
                "symbol": sym,
                "company": n500[sym],
                "date": (row.get("MEETING_DT") or row.get("BOARD_MTG_DT") or "").strip(),
                "purpose": (row.get("AGENDA") or row.get("PURPOSE") or "Results").strip(),
                "source": "BSE",
            })
        print(f"BSE results: {len(out)} N500 entries")
        return out
    except Exception as e:
        print(f"BSE results fetch failed: {e}")
        return []


def _parse_date(raw: str) -> dt.date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def bucket(rows: Iterable[dict]) -> dict:
    today = dt.date.today()
    horizon = today + dt.timedelta(days=7)
    today_b, upcoming_b = [], []
    seen: set[tuple[str, str]] = set()  # dedupe on (symbol, date)
    for r in rows:
        d = _parse_date(r.get("date", ""))
        if not d:
            continue
        key = (r["symbol"], d.isoformat())
        if key in seen:
            continue
        seen.add(key)
        r["date_iso"] = d.isoformat()
        if d == today:
            today_b.append(r)
        elif today < d <= horizon:
            upcoming_b.append(r)
    today_b.sort(key=lambda x: x["company"])
    upcoming_b.sort(key=lambda x: x["date_iso"])
    return {"today": today_b, "upcoming": upcoming_b}


def main() -> int:
    n500 = nifty500.load()
    if not n500:
        print("No Nifty 500 list — aborting")
        return 1
    all_rows = fetch_nse(n500) + fetch_bse(n500)
    payload = bucket(all_rows)
    payload["fetched_at"] = dt.datetime.utcnow().isoformat() + "Z"
    payload["n500_count"] = len(n500)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, default=str))
    print(f"Wrote {OUT} — today={len(payload['today'])} "
          f"upcoming={len(payload['upcoming'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
