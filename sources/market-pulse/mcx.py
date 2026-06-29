"""MCX commodity symbol resolver.

Downloads Fyers' MCX symbol master CSV and finds the front-month futures
contract for each commodity we care about. Returns Fyers-format symbols
ready to feed into fyers.quotes().
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
import sys

import requests

SYMBOL_MASTER_URL = "https://public.fyers.in/sym_details/MCX_COM.csv"

# Display name → Fyers underlying root (the part before MMMyyFUT)
TARGETS = {
    "Crude Oil": "CRUDEOIL",
    "Crude Oil Mini": "CRUDEOILM",
    "Natural Gas": "NATURALGAS",
    "Natural Gas Mini": "NATGASMINI",
    "Gold": "GOLD",
    "Gold Mini": "GOLDM",
    "Silver": "SILVER",
    "Silver Mini": "SILVERM",
    "Silver Micro": "SILVERMIC",
    "Copper": "COPPER",
    "Aluminium": "ALUMINIUM",
    "Zinc": "ZINC",
    "Lead": "LEAD",
    "Nickel": "NICKEL",
    "Cotton": "COTTON",
    "Mentha Oil": "MENTHAOIL",
    "Crude Palm Oil": "CPO",
}

# Match Fyers MCX futures — note the order is YYMON (year then month),
# e.g. MCX:GOLD26JUNFUT (not GOLDJUN26FUT).
SYMBOL_RE = re.compile(r"^MCX:([A-Z]+)\d{2}[A-Z]{3}FUT$")


def active_commodities() -> dict[str, dict]:
    """Returns {display_name: {symbol, expiry}} for the front-month
    MCX futures contract of each commodity in TARGETS.

    Uses column 8 (unix epoch expiry timestamp) for sorting, column 9 for
    the Fyers symbol, and column 13 for the underlying root.
    """
    try:
        r = requests.get(SYMBOL_MASTER_URL, timeout=20)
        r.raise_for_status()
        text = r.text
    except Exception as e:
        print(f"MCX symbol master fetch failed: {e}", file=sys.stderr)
        return {}

    today_epoch = int(dt.datetime.combine(
        dt.date.today(), dt.time.min).timestamp())
    candidates: dict[str, list[tuple[int, str]]] = {}

    for row in csv.reader(io.StringIO(text)):
        if len(row) < 14:
            continue
        symbol = row[9].strip()
        m = SYMBOL_RE.match(symbol)
        if not m:
            continue
        underlying = row[13].strip() or m.group(1)
        if underlying not in TARGETS.values():
            continue
        try:
            expiry_epoch = int(row[8])
        except (ValueError, TypeError):
            continue
        if expiry_epoch < today_epoch:
            continue
        candidates.setdefault(underlying, []).append((expiry_epoch, symbol))

    result: dict[str, dict] = {}
    for display, underlying in TARGETS.items():
        if underlying not in candidates:
            continue
        expiry_epoch, symbol = min(candidates[underlying])
        expiry_str = dt.date.fromtimestamp(expiry_epoch).isoformat()
        result[display] = {"symbol": symbol, "expiry": expiry_str}

    print(f"MCX: resolved {len(result)} active contracts")
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(active_commodities(), indent=2))
