"""Load the Nifty 500 constituent list.

Tries NSE's official archive CSV first, falls back to the bundled
data/nifty500.csv (refresh manually every quarter).

Returns a dict: {symbol: company_name} — symbols are the NSE trading symbols.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

import requests

ARCHIVE_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}
FALLBACK = Path(__file__).parent / "data" / "nifty500.csv"


def _parse_csv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        sym = (row.get("Symbol") or row.get("symbol") or "").strip().upper()
        name = (row.get("Company Name") or row.get("company_name") or "").strip()
        if sym:
            out[sym] = name
    return out


def load() -> dict[str, str]:
    try:
        r = requests.get(ARCHIVE_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
        parsed = _parse_csv(r.text)
        if parsed:
            print(f"nifty500: loaded {len(parsed)} from NSE archive")
            return parsed
    except Exception as e:
        print(f"nifty500 archive fetch failed: {e} — using bundled fallback")
    if FALLBACK.exists():
        parsed = _parse_csv(FALLBACK.read_text())
        print(f"nifty500: loaded {len(parsed)} from bundled fallback")
        return parsed
    print("nifty500: no data available")
    return {}


if __name__ == "__main__":
    syms = load()
    print(f"{len(syms)} symbols; sample: {list(syms.items())[:5]}")
