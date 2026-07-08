"""Shared market-data fetchers for the pre-market and post-market writers.

Pulls global indices/cues from yfinance, Indian market data from Fyers,
overnight news from RSS feeds, FII/DII flows from the public fii-dii-tracker
CSV, and corporate actions / expected results from NSE.

Each function fails soft (returns empty dict/list with a printed warning) so
the article writer can still produce *something* if one source is down.
"""
from __future__ import annotations

import csv
import datetime as dt
import html as html_lib
import io
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

HERE = Path(__file__).parent
TOKEN_PATH = HERE / "access_token.txt"

NSE_HOME = "https://www.nseindia.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

# ============================================================
# Fyers helpers
# ============================================================

def fyers_client():
    """Return an authed FyersModel — assumes auto_login.py already ran."""
    from fyers_apiv3 import fyersModel
    if not TOKEN_PATH.exists():
        sys.exit("access_token.txt missing — run auto_login.py first")
    cid = os.environ["FYERS_CLIENT_ID"]
    return fyersModel.FyersModel(
        client_id=cid, token=TOKEN_PATH.read_text().strip(), log_path="")


def fyers_quotes(fyers, symbols: list[str], batch: int = 50) -> dict[str, dict]:
    """Batched quote fetch — returns {symbol: {lp, ch, chp, high, low, prev_close}}."""
    out: dict[str, dict] = {}
    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i + batch]
        try:
            resp = fyers.quotes(data={"symbols": ",".join(chunk)})
        except Exception as e:
            print(f"  fyers quotes batch {i//batch} failed: {e}", file=sys.stderr)
            continue
        if resp.get("s") != "ok":
            continue
        for item in resp.get("d", []):
            v = item.get("v") or {}
            out[item.get("n", "")] = {
                "lp": float(v.get("lp") or 0),
                "ch": float(v.get("ch") or 0),
                "chp": float(v.get("chp") or 0),
                "high": float(v.get("high_price") or 0),
                "low": float(v.get("low_price") or 0),
                "prev_close": float(v.get("prev_close_price") or 0),
                "volume": int(v.get("volume") or 0),
            }
        time.sleep(0.2)
    return out


# ============================================================
# yfinance helpers (global cues)
# ============================================================

def yf_quote(ticker: str) -> dict:
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period="5d", auto_adjust=False)
        if len(h) < 2:
            return {}
        last = float(h["Close"].iloc[-1])
        prev = float(h["Close"].iloc[-2])
        return {"lp": last,
                "chp": (last - prev) / prev * 100 if prev else 0,
                "ch": last - prev}
    except Exception as e:
        print(f"yf {ticker} failed: {e}", file=sys.stderr)
        return {}


GLOBAL_INDICES = [
    ("Dow Jones", "^DJI"),
    ("Nasdaq", "^IXIC"),
    ("S&P 500", "^GSPC"),
    ("FTSE 100", "^FTSE"),
    ("Nikkei 225", "^N225"),
    ("Hang Seng", "^HSI"),
    ("Shanghai", "000001.SS"),
]

GLOBAL_CUES = [
    ("USD/INR", "INR=X"),
    ("Dollar Index", "DX-Y.NYB"),
    ("Brent Crude", "BZ=F"),
    ("WTI Crude", "CL=F"),
    ("Gold", "GC=F"),
    ("Silver", "SI=F"),
    ("US 10Y Yield", "^TNX"),
]


def fetch_global() -> dict:
    return {
        "indices": [{"name": n, **yf_quote(t)} for n, t in GLOBAL_INDICES],
        "cues": [{"name": n, **yf_quote(t)} for n, t in GLOBAL_CUES],
    }


# ============================================================
# NSE: expected results + corporate actions
# ============================================================

def _nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get(NSE_HOME, timeout=15)
        time.sleep(1)
    except Exception as e:
        print(f"NSE warmup failed: {e}", file=sys.stderr)
    return s


def fetch_results_today() -> list[dict]:
    """NSE board-meetings filtered to results scheduled today."""
    try:
        s = _nse_session()
        r = s.get(f"{NSE_HOME}/api/corporate-board-meetings?index=equities",
                  timeout=20)
        r.raise_for_status()
        rows = r.json() or []
    except Exception as e:
        print(f"NSE board meetings fetch failed: {e}", file=sys.stderr)
        return []
    today = dt.date.today()
    out: list[dict] = []
    for d in rows:
        purpose = (d.get("bm_purpose") or d.get("purpose") or "").lower()
        if not any(k in purpose for k in (
                "financial result", "audited", "unaudited", "quarterly",
                "q1 ", "q2 ", "q3 ", "q4 ", "standalone", "consolidated")):
            continue
        raw_date = (d.get("bm_date") or "").strip()
        try:
            parsed = dt.datetime.strptime(raw_date, "%d-%b-%Y").date()
        except ValueError:
            continue
        if parsed != today:
            continue
        out.append({
            "symbol": (d.get("bm_symbol") or d.get("symbol") or "").upper(),
            "purpose": (d.get("bm_purpose") or d.get("purpose") or "").strip(),
            "date": parsed.isoformat(),
        })
    return out


def fetch_corp_actions_today() -> list[dict]:
    """Corporate actions with ex-date == today (dividends, splits, bonus, AGM)."""
    try:
        s = _nse_session()
        r = s.get(f"{NSE_HOME}/api/corporates-corporateActions?index=equities",
                  timeout=20)
        r.raise_for_status()
        rows = r.json() or []
    except Exception as e:
        print(f"NSE corp actions fetch failed: {e}", file=sys.stderr)
        return []
    today = dt.date.today()
    out: list[dict] = []
    for row in rows:
        raw = row.get("exDate") or row.get("ex_date") or ""
        try:
            ex = dt.datetime.strptime(raw.strip(), "%d-%b-%Y").date()
        except ValueError:
            continue
        if ex != today:
            continue
        out.append({
            "symbol": (row.get("symbol") or "").upper(),
            "subject": (row.get("subject") or row.get("purpose")
                         or "").strip(),
            "ex_date": ex.isoformat(),
        })
    return out


# ============================================================
# FII / DII flows (from public fii-dii-tracker CSV)
# ============================================================

FIIDII_URL = ("https://raw.githubusercontent.com/myfinancialria/"
              "fii-dii-tracker/main/data/fii_dii_history.csv")


def fetch_fiidii(days: int = 10) -> dict:
    try:
        r = requests.get(FIIDII_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
        reader = csv.DictReader(io.StringIO(r.text))
    except Exception as e:
        print(f"FII/DII fetch failed: {e}", file=sys.stderr)
        return {"today": {}, "history": []}
    by_date: dict[str, dict] = {}
    for row in reader:
        d = row.get("date", "").strip()
        cat = row.get("category", "").strip()
        if not d or not cat:
            continue
        by_date.setdefault(d, {})[cat] = {
            "buy": float(row.get("buy_value") or 0),
            "sell": float(row.get("sell_value") or 0),
            "net": float(row.get("net_value") or 0),
        }
    dates = sorted(by_date.keys(), reverse=True)
    history = []
    for d in dates[:days]:
        rec = by_date[d]
        fii = rec.get("FII/FPI") or rec.get("FII") or {}
        dii = rec.get("DII") or {}
        history.append({
            "date": d,
            "fii_net": fii.get("net", 0),
            "dii_net": dii.get("net", 0),
        })
    return {"today": history[0] if history else {}, "history": history}


# ============================================================
# RSS news (Indian + global)
# ============================================================

DEFAULT_NEWS_FEEDS = [
    ("ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Livemint Markets", "https://www.livemint.com/rss/markets"),
    ("Moneycontrol Markets", "https://www.moneycontrol.com/rss/marketreports.xml"),
    ("ET International", "https://economictimes.indiatimes.com/news/international/business/rssfeeds/1086955.cms"),
    ("CNBC TV18", "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml"),
    ("Business Standard Markets", "https://www.business-standard.com/rss/markets-106.rss"),
]


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_ts(raw: str) -> dt.datetime | None:
    for fmt in ("%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S GMT",
                "%Y-%m-%dT%H:%M:%S%z"):
        try:
            ts = dt.datetime.strptime(raw, fmt)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt.timezone.utc)
            return ts.astimezone(dt.timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def fetch_news(hours_back: int = 18, max_per_feed: int = 12) -> list[dict]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_back)
    items: list[dict] = []
    for name, url in DEFAULT_NEWS_FEEDS:
        try:
            r = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]},
                              timeout=15)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception as e:
            print(f"  news {name} failed: {e}", file=sys.stderr)
            continue
        for it in root.iter("item"):
            title = _clean(it.findtext("title") or "")
            if not title:
                continue
            ts = _parse_ts((it.findtext("pubDate") or "").strip())
            if ts and ts < cutoff:
                continue
            items.append({
                "source": name,
                "title": title,
                "summary": _clean(it.findtext("description") or "")[:300],
                "link": (it.findtext("link") or "").strip(),
                "ts": ts.isoformat() if ts else None,
            })
            if len([x for x in items if x["source"] == name]) >= max_per_feed:
                break
        time.sleep(0.3)
    # Dedupe by title prefix
    seen, deduped = set(), []
    for a in items:
        k = a["title"][:80].lower()
        if k not in seen:
            seen.add(k)
            deduped.append(a)
    return deduped


# ============================================================
# Indian indices & sectors (Fyers)
# ============================================================

HEADLINE_INDICES = [
    ("NIFTY 50", ["NSE:NIFTY50-INDEX"]),
    ("BANK NIFTY", ["NSE:NIFTYBANK-INDEX"]),
    ("NIFTY MIDCAP 100",
     ["NSE:NIFTYMIDCAP100-INDEX", "NSE:NIFTYMID100-INDEX"]),
    ("NIFTY SMALLCAP 100",
     ["NSE:NIFTYSMLCAP100-INDEX", "NSE:NIFTYSML100-INDEX"]),
]
VIX_SYMBOL = "NSE:INDIAVIX-INDEX"
SECTORS = [
    ("IT", "NSE:NIFTYIT-INDEX"),
    ("BANK", "NSE:NIFTYBANK-INDEX"),
    ("AUTO", "NSE:NIFTYAUTO-INDEX"),
    ("PHARMA", "NSE:NIFTYPHARMA-INDEX"),
    ("FMCG", "NSE:NIFTYFMCG-INDEX"),
    ("METAL", "NSE:NIFTYMETAL-INDEX"),
    ("REALTY", "NSE:NIFTYREALTY-INDEX"),
    ("ENERGY", "NSE:NIFTYENERGY-INDEX"),
    ("PSU BANK", "NSE:NIFTYPSUBANK-INDEX"),
    ("MEDIA", "NSE:NIFTYMEDIA-INDEX"),
    ("FIN SERVICES", "NSE:NIFTYFINSERVICE-INDEX"),
    ("CONSUMER", "NSE:NIFTYCONSUMER-INDEX"),
]
GIFT_CANDIDATES = [
    "NSEIX:GIFTNIFTY1!FUT", "NSEIX:GIFTNIFTY-FUT",
    "NSEIX:GIFTNIFTY-INDEX",
]


def fetch_india(fyers) -> dict:
    syms = ([s for _, group in HEADLINE_INDICES for s in group]
            + [VIX_SYMBOL] + [s for _, s in SECTORS])
    q = fyers_quotes(fyers, syms)

    def first_hit(group):
        for s in group:
            d = q.get(s, {})
            if d.get("lp"):
                return d
        return {}

    indices = [{"name": lbl, **first_hit(g)} for lbl, g in HEADLINE_INDICES]
    vix = q.get(VIX_SYMBOL, {})
    sectors = [{"name": lbl, **q.get(s, {})} for lbl, s in SECTORS
               if q.get(s, {}).get("lp")]
    sectors.sort(key=lambda x: x.get("chp", 0), reverse=True)
    return {"indices": indices, "vix": vix, "sectors": sectors}


def fetch_gift_nifty(fyers) -> dict:
    for sym in GIFT_CANDIDATES:
        q = fyers_quotes(fyers, [sym])
        d = q.get(sym, {})
        if d.get("lp"):
            return {"name": "GIFT NIFTY", "symbol": sym, **d}
    return {"name": "GIFT NIFTY"}


# ============================================================
# Technical levels (CPR / pivots / swings / MAs) via Fyers history
# ============================================================

LEVEL_INDICES = [
    ("NIFTY 50", "NSE:NIFTY50-INDEX"),
    ("BANK NIFTY", "NSE:NIFTYBANK-INDEX"),
]


def _fyers_daily_candles(fyers, symbol: str, days: int = 90) -> list[list]:
    """Daily OHLC candles [[ts,o,h,l,c,v], ...] oldest→newest, fail-soft."""
    to = dt.date.today()
    frm = to - dt.timedelta(days=days * 2)  # buffer for weekends/holidays
    try:
        resp = fyers.history(data={
            "symbol": symbol, "resolution": "D", "date_format": "1",
            "range_from": frm.isoformat(), "range_to": to.isoformat(),
            "cont_flag": "1"})
    except Exception as e:
        print(f"  fyers history {symbol} failed: {e}", file=sys.stderr)
        return []
    if isinstance(resp, dict) and resp.get("s") == "ok":
        return resp.get("candles") or []
    return []


def _round(x, nd=0):
    try:
        return round(float(x), nd) if nd else int(round(float(x)))
    except (TypeError, ValueError):
        return None


def fetch_index_technicals(fyers, swing_lookback: int = 15) -> list[dict]:
    """CPR/pivots from the previous session + recent swing high/low + 20/50 DMA
    for Nifty and Bank Nifty. Everything computed from daily candles."""
    out: list[dict] = []
    for name, sym in LEVEL_INDICES:
        candles = _fyers_daily_candles(fyers, sym)
        if len(candles) < 5:
            out.append({"name": name, "available": False})
            continue
        closes = [c[4] for c in candles]
        highs = [c[2] for c in candles]
        lows = [c[3] for c in candles]
        h, l, c = candles[-1][2], candles[-1][3], candles[-1][4]  # prev session
        p = (h + l + c) / 3.0
        bc = (h + l) / 2.0
        tc = 2 * p - bc
        rec = {
            "name": name,
            "available": True,
            "prev_close": _round(c, 2),
            "cpr": {"pivot": _round(p, 2), "bc": _round(min(bc, tc), 2),
                     "tc": _round(max(bc, tc), 2),
                     "width_pct": _round(abs(tc - bc) / p * 100, 2)},
            "resistance": {
                "r1": _round(2 * p - l, 2),
                "r2": _round(p + (h - l), 2),
                "r3": _round(h + 2 * (p - l), 2),
            },
            "support": {
                "s1": _round(2 * p - h, 2),
                "s2": _round(p - (h - l), 2),
                "s3": _round(l - 2 * (h - p), 2),
            },
            "swing_high": _round(max(highs[-swing_lookback:]), 2),
            "swing_low": _round(min(lows[-swing_lookback:]), 2),
            "dma20": _round(sum(closes[-20:]) / min(20, len(closes)), 2),
            "dma50": _round(sum(closes[-50:]) / min(50, len(closes)), 2),
        }
        out.append(rec)
    return out


# ============================================================
# Option-chain OI levels (support/resistance from open interest)
# ============================================================

OI_INDICES = [
    ("NIFTY", "NSE:NIFTY50-INDEX"),
    ("BANK NIFTY", "NSE:NIFTYBANK-INDEX"),
]


def fetch_oi_levels(fyers, strikecount: int = 15) -> list[dict]:
    """Highest call-OI strikes (resistance), highest put-OI strikes (support),
    PCR and ATM from the nearest-expiry option chain. Fail-soft per index."""
    out: list[dict] = []
    for name, sym in OI_INDICES:
        try:
            resp = fyers.optionchain(data={
                "symbol": sym, "strikecount": strikecount, "timestamp": ""})
        except Exception as e:
            print(f"  fyers optionchain {sym} failed: {e}", file=sys.stderr)
            out.append({"name": name, "available": False})
            continue
        data = (resp or {}).get("data") or {}
        chain = data.get("optionsChain") or []
        calls = [x for x in chain if x.get("option_type") == "CE"
                 and x.get("strike_price")]
        puts = [x for x in chain if x.get("option_type") == "PE"
                and x.get("strike_price")]
        if not calls or not puts:
            out.append({"name": name, "available": False})
            continue
        top_ce = sorted(calls, key=lambda x: x.get("oi", 0) or 0, reverse=True)[:3]
        top_pe = sorted(puts, key=lambda x: x.get("oi", 0) or 0, reverse=True)[:3]
        tot_ce = sum((x.get("oi", 0) or 0) for x in calls)
        tot_pe = sum((x.get("oi", 0) or 0) for x in puts)
        # spot / underlying row is usually option_type == "" in the chain
        spot_row = next((x for x in chain if not x.get("option_type")), {})
        out.append({
            "name": name,
            "available": True,
            "spot": _round(spot_row.get("ltp") or data.get("indiavixData", {}).get("ltp"), 2),
            "pcr": _round(tot_pe / tot_ce, 2) if tot_ce else None,
            "resistance": [{"strike": _round(x["strike_price"], 0),
                            "oi": int(x.get("oi", 0) or 0)} for x in top_ce],
            "support": [{"strike": _round(x["strike_price"], 0),
                         "oi": int(x.get("oi", 0) or 0)} for x in top_pe],
        })
    return out


def fetch_n500(fyers) -> list[dict]:
    """Returns full Nifty 500 quotes with sector/company info."""
    import nifty500_live as nl
    n500 = nl.load()
    sym_to_meta = {s["symbol"]: s for s in n500}
    syms = [f"NSE:{s['symbol']}-EQ" for s in n500]
    q = fyers_quotes(fyers, syms)
    rows = []
    for full, d in q.items():
        sym = full.replace("NSE:", "").replace("-EQ", "")
        if not d.get("chp"):
            continue
        meta = sym_to_meta.get(sym, {})
        rows.append({
            "symbol": sym,
            "company": meta.get("company", sym),
            "sector": meta.get("industry", ""),
            "lp": d["lp"], "chp": d["chp"], "ch": d.get("ch", 0),
            "high": d.get("high", 0), "low": d.get("low", 0),
            "volume": d.get("volume", 0),
        })
    return rows
