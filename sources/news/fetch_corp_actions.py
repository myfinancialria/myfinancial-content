"""Fetch corporate actions for Nifty 500 — dividends, splits, bonus, AGM, buybacks.

Source: NSE /api/corporates-corporateActions

Output: data/corp_actions.json with two buckets — today (ex-date today) and
upcoming (ex-date within next 14 days).
"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import requests

import nifty500

NSE_HOME = "https://www.nseindia.com"
ENDPOINT = f"{NSE_HOME}/api/corporates-corporateActions?index=equities"

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

OUT = Path(__file__).parent / "data" / "corp_actions.json"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get(NSE_HOME, timeout=15)
        time.sleep(1)
    except Exception as e:
        print(f"NSE warmup failed: {e}")
    return s


def _classify(subject: str) -> str:
    s = (subject or "").lower()
    if "dividend" in s:
        return "Dividend"
    if "split" in s or "face value" in s:
        return "Stock Split"
    if "bonus" in s:
        return "Bonus"
    if "buy" in s and "back" in s:
        return "Buyback"
    if "rights" in s:
        return "Rights Issue"
    if "agm" in s or "annual general" in s:
        return "AGM"
    if "egm" in s or "extraordinary general" in s:
        return "EGM"
    if "spin" in s or "demerger" in s:
        return "Demerger"
    return "Other"


def _parse_date(raw: str) -> dt.date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def fetch(n500: dict[str, str]) -> list[dict]:
    try:
        s = _session()
        r = s.get(ENDPOINT, timeout=20)
        r.raise_for_status()
        rows = r.json() or []
    except Exception as e:
        print(f"NSE corp actions fetch failed: {e}")
        return []
    out: list[dict] = []
    for row in rows:
        sym = (row.get("symbol") or "").strip().upper()
        if sym not in n500:
            continue
        ex_raw = row.get("exDate") or row.get("ex_date") or ""
        ex = _parse_date(ex_raw)
        if not ex:
            continue
        subject = row.get("subject") or row.get("purpose") or ""
        out.append({
            "symbol": sym,
            "company": n500[sym],
            "type": _classify(subject),
            "subject": subject.strip(),
            "ex_date": ex.isoformat(),
            "record_date": (row.get("recDate") or row.get("recordDate") or "").strip(),
        })
    print(f"Corp actions: {len(out)} N500 entries")
    return out


def bucket(rows: list[dict]) -> dict:
    today = dt.date.today()
    horizon = today + dt.timedelta(days=14)
    today_b, upcoming_b = [], []
    for r in rows:
        d = dt.date.fromisoformat(r["ex_date"])
        if d == today:
            today_b.append(r)
        elif today < d <= horizon:
            upcoming_b.append(r)
    today_b.sort(key=lambda x: (x["type"], x["company"]))
    upcoming_b.sort(key=lambda x: (x["ex_date"], x["type"]))
    return {"today": today_b, "upcoming": upcoming_b}


def main() -> int:
    n500 = nifty500.load()
    if not n500:
        print("No Nifty 500 list — aborting")
        return 1
    rows = fetch(n500)
    payload = bucket(rows)
    payload["fetched_at"] = dt.datetime.utcnow().isoformat() + "Z"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, default=str))
    print(f"Wrote {OUT} — today={len(payload['today'])} "
          f"upcoming={len(payload['upcoming'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
