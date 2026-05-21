"""Load Nifty 500 constituents from NSE's published CSV archive.

Returns a list of {"symbol", "company", "industry"} dicts.
"""
from __future__ import annotations

import csv
import io
import sys

import requests

URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}


def load() -> list[dict]:
    r = requests.get(URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    out: list[dict] = []
    reader = csv.DictReader(io.StringIO(r.text))
    for row in reader:
        sym = (row.get("Symbol") or "").strip().upper()
        if not sym:
            continue
        out.append({
            "symbol": sym,
            "company": (row.get("Company Name") or "").strip(),
            "industry": (row.get("Industry") or "").strip(),
        })
    if not out:
        sys.exit("Nifty 500 CSV returned empty")
    print(f"nifty500: loaded {len(out)} symbols")
    return out


if __name__ == "__main__":
    syms = load()
    print(f"{len(syms)} symbols; sample: {syms[:3]}")
