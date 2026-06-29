"""Pull end-of-day F&O snapshot for indices + top stocks.

Authorised data sources only:
  - Fyers API (broker-grade option chains, futures quotes, indices)
  - NSE archives (FII derivative-stats CSV, end-of-day participant-wise OI)

Writes a single JSON to data/YYYY-MM-DD.json that analyser.py reads.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv
from fyers_apiv3 import fyersModel

HERE = Path(__file__).parent
DATA = HERE / "data"
DATA.mkdir(exist_ok=True)
load_dotenv(HERE / ".env")
CID = os.getenv("FYERS_CLIENT_ID")

INDICES = [
    {"name": "NIFTY 50",   "underlying": "NSE:NIFTY50-INDEX",   "lot": 75,  "strike_int": 50},
    {"name": "SENSEX",     "underlying": "BSE:SENSEX-INDEX",    "lot": 20,  "strike_int": 100},
    {"name": "BANK NIFTY", "underlying": "NSE:NIFTYBANK-INDEX", "lot": 15,  "strike_int": 100},
]

# Top F&O stocks to watch (subset — chosen by typical OI activity)
STOCK_WATCHLIST = [
    "RELIANCE","HDFCBANK","ICICIBANK","INFY","TCS","SBIN","BHARTIARTL",
    "AXISBANK","KOTAKBANK","LT","ITC","HINDUNILVR","ADANIENT","TATAMOTORS",
    "BAJFINANCE","MARUTI","TITAN",
]


def fy_client():
    tok = (HERE / "access_token.txt").read_text().strip()
    return fyersModel.FyersModel(client_id=CID, token=tok, log_path="")


def fetch_quote(fy, sym):
    try:
        r = fy.quotes({"symbols": sym})
        if r.get("s") == "ok" and r.get("d"):
            return r["d"][0]["v"]
    except Exception as e:
        print(f"  quote err {sym}: {e}", file=sys.stderr)
    return None


def fetch_option_chain(fy, underlying, strike_count=25):
    try:
        r = fy.optionchain(data={"symbol": underlying,
                                 "strikecount": strike_count, "timestamp": ""})
        if r.get("code") == 200:
            return r["data"]
    except Exception as e:
        print(f"  chain err {underlying}: {e}", file=sys.stderr)
    return None


def analyse_chain(chain_data):
    """Extract structured signals from a Fyers option-chain response."""
    if not chain_data:
        return None
    exp = chain_data.get("expiryData", [{}])[0]
    chain = chain_data.get("optionsChain", [])

    spot_row = next((r for r in chain
                     if r.get("strike_price", -1) == -1
                     and "INDEX" in r.get("symbol", "")), None)
    if not spot_row:
        return None
    spot = float(spot_row["ltp"])
    chg = float(spot_row.get("ltpch", 0))
    chgp = float(spot_row.get("ltpchp", 0))

    opts = [r for r in chain if r.get("option_type") in ("CE", "PE")]
    if not opts:
        return None
    df = pd.DataFrame(opts)[["strike_price","option_type","ltp","oi","oich","volume"]]
    df = df.rename(columns={"strike_price": "strike"})
    calls = df[df.option_type == "CE"].sort_values("strike").reset_index(drop=True)
    puts  = df[df.option_type == "PE"].sort_values("strike").reset_index(drop=True)
    if calls.empty or puts.empty:
        return None

    atm = int(calls.iloc[(calls.strike - spot).abs().argmin()].strike)

    # max pain
    strikes = sorted(set(calls.strike) & set(puts.strike))
    pain = {}
    for k in strikes:
        loss_c = sum(max(0, s - k) * o for s, o in zip(calls.strike, calls.oi))
        loss_p = sum(max(0, k - s) * o for s, o in zip(puts.strike,  puts.oi))
        pain[k] = loss_c + loss_p
    max_pain = int(min(pain, key=pain.get))

    ce_oi = float(calls.oi.sum()); pe_oi = float(puts.oi.sum())
    ce_doi = float(calls.oich.sum()); pe_doi = float(puts.oich.sum())
    pcr_oi  = pe_oi / ce_oi if ce_oi else 0
    pcr_doi = pe_doi / ce_doi if ce_doi else 0

    # top OI strikes
    def to_list(df_, n=5):
        return [{
            "strike": int(r.strike), "ltp": float(r.ltp),
            "oi": int(r.oi), "doi": int(r.oich),
        } for _, r in df_.nlargest(n, "oi").iterrows()]

    def to_list_doi(df_, n=3, asc=False):
        d = df_.nsmallest(n, "oich") if asc else df_.nlargest(n, "oich")
        return [{
            "strike": int(r.strike), "ltp": float(r.ltp),
            "oi": int(r.oi), "doi": int(r.oich),
        } for _, r in d.iterrows()]

    return {
        "expiry": exp.get("date"),
        "spot": round(spot, 2),
        "chg": round(chg, 2), "chgp": round(chgp, 2),
        "atm": atm, "max_pain": max_pain,
        "pcr_oi": round(pcr_oi, 2),
        "pcr_doi": round(pcr_doi, 2),
        "total_ce_oi": int(ce_oi), "total_pe_oi": int(pe_oi),
        "total_ce_doi": int(ce_doi), "total_pe_doi": int(pe_doi),
        "top_ce_oi":  to_list(calls, 5),
        "top_pe_oi":  to_list(puts,  5),
        "ce_fresh_writing": to_list_doi(calls, 5),
        "pe_fresh_writing": to_list_doi(puts,  5),
        "ce_unwinding":     to_list_doi(calls, 3, asc=True),
        "pe_unwinding":     to_list_doi(puts,  3, asc=True),
    }


def fetch_nse_fii_derivatives(day: dt.date) -> dict | None:
    """NSE publishes daily participant-wise FNO OI. URL changes form occasionally;
    we try the current and prior-day CSVs. Returns a dict with FII rows."""
    candidates = [
        f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{day.strftime('%d%m%Y')}.csv",
    ]
    headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/123.0 Safari/537.36"),
        "Accept": "text/csv,application/csv,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/all-reports-derivatives",
    }
    for url in candidates:
        try:
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code == 200 and "Client Type" in r.text[:500]:
                # parse CSV: rows starting with client_type column
                from io import StringIO
                # First line is the date; skip until header
                lines = [l for l in r.text.splitlines() if l.strip()]
                # find "Client Type" header
                hdr_idx = next((i for i, l in enumerate(lines)
                               if l.lower().startswith("client type")), 1)
                df = pd.read_csv(StringIO("\n".join(lines[hdr_idx:])))
                df.columns = [c.strip() for c in df.columns]
                fii_row = df[df["Client Type"].str.upper().str.contains("FII", na=False)]
                if len(fii_row):
                    row = fii_row.iloc[0].to_dict()
                    return {"raw_url": url, "fii": {k: row[k] for k in row}}
        except Exception as e:
            print(f"  NSE FII fetch err {url}: {e}", file=sys.stderr)
    return None


def fetch_stock_snapshot(fy, ticker: str) -> dict | None:
    """Stock futures quote + option-chain summary (for top FNO stocks)."""
    fut = fetch_quote(fy, f"NSE:{ticker}-EQ")
    if not fut:
        return None
    chain = fetch_option_chain(fy, f"NSE:{ticker}-EQ", strike_count=10)
    sig = analyse_chain(chain) if chain else None
    return {
        "ticker": ticker,
        "spot": fut.get("lp"), "chg": fut.get("ch"), "chgp": fut.get("chp"),
        "volume": fut.get("volume"),
        "options": sig,
    }


def main():
    fy = fy_client()
    today = dt.date.today()
    print(f"Fetching F&O snapshot for {today}")

    out: dict[str, Any] = {
        "date": today.isoformat(),
        "indices": [],
        "stocks": [],
        "fii_derivatives": None,
        "vix": None,
    }

    # VIX
    vix_q = fetch_quote(fy, "NSE:INDIAVIX-INDEX")
    if vix_q:
        out["vix"] = {"ltp": vix_q.get("lp"), "chg": vix_q.get("ch"), "chgp": vix_q.get("chp")}
        print(f"  VIX: {out['vix']}")

    # Indices
    for idx in INDICES:
        print(f"\n=== {idx['name']} ===")
        chain = fetch_option_chain(fy, idx["underlying"], strike_count=30)
        sig = analyse_chain(chain)
        if sig:
            sig["lot"] = idx["lot"]
            sig["strike_int"] = idx["strike_int"]
            sig["name"] = idx["name"]
            out["indices"].append(sig)
            print(f"  spot {sig['spot']:.2f} ({sig['chgp']:+.2f}%) "
                  f"ATM {sig['atm']} maxPain {sig['max_pain']} "
                  f"PCR(OI) {sig['pcr_oi']} PCR(dOI) {sig['pcr_doi']}")
        time.sleep(0.5)

    # FII derivative stats (NSE archive, end-of-day)
    print(f"\n--- FII derivative stats ({today}) ---")
    fii = fetch_nse_fii_derivatives(today)
    if not fii:
        # try yesterday
        y = today - dt.timedelta(days=1)
        fii = fetch_nse_fii_derivatives(y)
        if fii: fii["lag_day"] = True
    if fii:
        print("  ✓ got FII row")
        out["fii_derivatives"] = fii
    else:
        print("  ⚠ FII data not available yet (NSE publishes ~6 PM IST)")

    # Top stocks (limited; full chain fetch is rate-limit-heavy)
    print(f"\n--- top {len(STOCK_WATCHLIST)} F&O stocks (quote only for speed) ---")
    for t in STOCK_WATCHLIST:
        q = fetch_quote(fy, f"NSE:{t}-EQ")
        if q:
            out["stocks"].append({
                "ticker": t,
                "spot": q.get("lp"), "chg": q.get("ch"), "chgp": q.get("chp"),
                "volume": q.get("volume"),
            })
        time.sleep(0.15)
    # Sort by absolute % change to highlight biggest movers
    out["stocks"].sort(key=lambda s: abs(s.get("chgp") or 0), reverse=True)

    out_path = DATA / f"{today.isoformat()}.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
