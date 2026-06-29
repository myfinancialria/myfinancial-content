"""Build FII/DII payload — last 10 trading days cash + today's derivatives.

Cash data:    reuses myfinancialria/fii-dii-tracker published CSV.
Derivative:   live NSE F&O stats (FII index futures / options + stock futures).

Output: data/fiidii.json with shape:
  {
    "fetched_at": "...",
    "cash": {
      "today": {"date": "...", "fii_net": ..., "dii_net": ...},
      "history": [ ...10 latest entries... ]
    },
    "derivatives": {
      "today": { "fii_index_fut_net": ..., "fii_index_opt_net": ..., ... }
    }
  }
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import time
from pathlib import Path

import requests

OUT = Path(__file__).parent / "data" / "fiidii.json"

CASH_HISTORY_URL = (
    "https://raw.githubusercontent.com/myfinancialria/fii-dii-tracker/"
    "main/data/fii_dii_history.csv"
)

NSE_HOME = "https://www.nseindia.com"
FII_DERIV_URL = f"{NSE_HOME}/api/fiidii-derivatives-statistics"

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


def fetch_cash_history(days: int = 10) -> dict:
    """Pull the public CSV from fii-dii-tracker and return last `days` trading days."""
    try:
        r = requests.get(CASH_HISTORY_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
        reader = csv.DictReader(io.StringIO(r.text))
        rows = list(reader)
    except Exception as e:
        print(f"FII/DII cash history fetch failed: {e}")
        return {"today": {}, "history": []}

    # Group by date → {date: {FII: row, DII: row}}
    by_date: dict[str, dict] = {}
    for row in rows:
        d = row.get("date", "").strip()
        cat = row.get("category", "").strip()
        if not d or not cat:
            continue
        by_date.setdefault(d, {})[cat] = {
            "buy": float(row.get("buy_value") or 0),
            "sell": float(row.get("sell_value") or 0),
            "net": float(row.get("net_value") or 0),
        }

    dates_desc = sorted(by_date.keys(), reverse=True)
    history: list[dict] = []
    for d in dates_desc[:days]:
        rec = by_date[d]
        fii = rec.get("FII/FPI") or rec.get("FII") or {}
        dii = rec.get("DII") or {}
        history.append({
            "date": d,
            "fii_net": fii.get("net", 0),
            "dii_net": dii.get("net", 0),
            "fii_buy": fii.get("buy", 0),
            "fii_sell": fii.get("sell", 0),
            "dii_buy": dii.get("buy", 0),
            "dii_sell": dii.get("sell", 0),
        })
    today_entry = history[0] if history else {}
    return {"today": today_entry, "history": history}


def _nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get(NSE_HOME, timeout=15)
        time.sleep(1)
    except Exception as e:
        print(f"NSE warmup failed: {e}")
    return s


def fetch_derivatives() -> dict:
    """FII activity in F&O — Index Futures / Index Options / Stock Futures.

    The endpoint returns:
      { "data": [ {"instrument": "...", "no_of_contracts_buy": ..., "amt_buy": ...,
                   "no_of_contracts_sell": ..., "amt_sell": ...}, ... ] }
    """
    try:
        s = _nse_session()
        r = s.get(FII_DERIV_URL, timeout=20)
        r.raise_for_status()
        rows = r.json().get("data", [])
    except Exception as e:
        print(f"NSE FII derivatives fetch failed: {e}")
        return {}

    out: dict = {"by_instrument": []}
    total_net = 0.0
    for row in rows:
        instrument = (row.get("instrument") or "").strip()
        buy = float(row.get("amt_buy") or 0)
        sell = float(row.get("amt_sell") or 0)
        net = buy - sell
        total_net += net
        out["by_instrument"].append({
            "instrument": instrument,
            "buy_cr": buy,
            "sell_cr": sell,
            "net_cr": net,
        })
    out["total_net_cr"] = total_net
    return out


def main() -> int:
    cash = fetch_cash_history(days=10)
    deriv = fetch_derivatives()
    payload = {
        "fetched_at": dt.datetime.utcnow().isoformat() + "Z",
        "cash": cash,
        "derivatives": deriv,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, default=str))
    print(f"Wrote {OUT} — history={len(cash.get('history', []))} "
          f"deriv_rows={len(deriv.get('by_instrument', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
