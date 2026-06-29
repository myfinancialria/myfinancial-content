"""Apply the 14-row directional framework to the day's snapshot.

Reads data/YYYY-MM-DD.json from fetcher.py, computes per-instrument bias
votes, and writes data/YYYY-MM-DD.analysis.json with structured signals
that writer.py can turn into prose.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"


def vote_index(idx: dict) -> dict:
    """Apply the directional checklist to one index's option chain."""
    spot = idx["spot"]; chgp = idx["chgp"]
    atm = idx["atm"]; max_pain = idx["max_pain"]
    pcr_oi = idx.get("pcr_oi", 0); pcr_doi = idx.get("pcr_doi", 0)

    votes = []  # list of (signal, sentiment, note)

    # 1. PCR(OI) regime
    if pcr_oi > 1.3:
        votes.append(("PCR(OI) > 1.3", "bullish",
                      f"PCR {pcr_oi} — puts dominate, downside well-protected"))
    elif pcr_oi < 0.7:
        votes.append(("PCR(OI) < 0.7", "bearish",
                      f"PCR {pcr_oi} — calls dominate, upside capped"))
    else:
        votes.append(("PCR(OI)", "neutral", f"PCR {pcr_oi} — balanced book"))

    # 2. PCR(dOI) — today's flow
    if pcr_doi > 1.3:
        votes.append(("Today's flow ΔPCR", "bullish",
                      f"ΔPCR {pcr_doi} — today's fresh writing is put-heavy"))
    elif 0 < pcr_doi < 0.7:
        votes.append(("Today's flow ΔPCR", "bearish",
                      f"ΔPCR {pcr_doi} — today's fresh writing is call-heavy"))
    else:
        votes.append(("Today's flow ΔPCR", "neutral",
                      f"ΔPCR {pcr_doi} — mixed/balanced flow"))

    # 3. Max pain relative to spot
    diff_mp = (max_pain - spot) / spot * 100
    if abs(diff_mp) < 0.3:
        votes.append(("Max pain", "neutral", f"At spot ({max_pain})"))
    elif diff_mp > 0:
        votes.append(("Max pain", "bullish",
                      f"{max_pain} is {diff_mp:+.1f}% above spot — pin pull is up"))
    else:
        votes.append(("Max pain", "bearish",
                      f"{max_pain} is {diff_mp:+.1f}% below spot — pin pull is down"))

    # 4. Top call OI vs spot (resistance distance)
    if idx.get("top_ce_oi"):
        top_ce = idx["top_ce_oi"][0]
        dist_ce = (top_ce["strike"] - spot) / spot * 100
        if dist_ce < 1.0:
            votes.append(("Call wall proximity", "bearish",
                          f"Heaviest Call OI at {top_ce['strike']} "
                          f"({dist_ce:+.1f}% above spot) — close ceiling"))

    # 5. Top put OI vs spot
    if idx.get("top_pe_oi"):
        top_pe = idx["top_pe_oi"][0]
        dist_pe = (spot - top_pe["strike"]) / spot * 100
        if dist_pe < 1.0:
            votes.append(("Put base proximity", "bullish",
                          f"Heaviest Put OI at {top_pe['strike']} "
                          f"({dist_pe:+.1f}% below spot) — close floor"))

    # 6. Fresh call writing direction
    fc = idx.get("ce_fresh_writing", [])
    if fc:
        avg_fc = sum(c["strike"] for c in fc[:3]) / min(3, len(fc))
        if avg_fc < spot * 1.02:   # writers are close above spot
            votes.append(("Fresh CE writing", "bearish",
                          f"Today's heaviest CE writing near {int(avg_fc)} "
                          f"— call sellers expect cap"))

    # 7. Fresh put writing direction
    fp = idx.get("pe_fresh_writing", [])
    if fp:
        avg_fp = sum(p["strike"] for p in fp[:3]) / min(3, len(fp))
        if avg_fp > spot * 0.98:   # writers are close below spot
            votes.append(("Fresh PE writing", "bullish",
                          f"Today's heaviest PE writing near {int(avg_fp)} "
                          f"— put sellers expect floor"))

    # 8. Total OI shift direction
    ce_doi = idx.get("total_ce_doi", 0)
    pe_doi = idx.get("total_pe_doi", 0)
    if ce_doi > 0 and pe_doi > 0:
        ratio = ce_doi / pe_doi if pe_doi else 0
        if ratio > 2:
            votes.append(("Aggregate flow", "bearish",
                          f"Net CE OI build {ce_doi/1e6:.1f}M >> PE {pe_doi/1e6:.1f}M today"))
        elif ratio < 0.5 and ratio > 0:
            votes.append(("Aggregate flow", "bullish",
                          f"Net PE OI build {pe_doi/1e6:.1f}M >> CE {ce_doi/1e6:.1f}M today"))

    # tally
    bull = sum(1 for _, s, _ in votes if s == "bullish")
    bear = sum(1 for _, s, _ in votes if s == "bearish")
    neut = sum(1 for _, s, _ in votes if s == "neutral")
    net = bull - bear
    if net >= 3:
        bias = "Bullish"
    elif net <= -3:
        bias = "Bearish"
    elif abs(net) >= 1:
        bias = "Mildly " + ("bullish" if net > 0 else "bearish")
    else:
        bias = "Range-bound / mixed"

    return {
        "name": idx["name"],
        "spot": spot, "chgp": chgp, "atm": atm, "max_pain": max_pain,
        "pcr_oi": pcr_oi, "pcr_doi": pcr_doi,
        "expected_range_low": idx["top_pe_oi"][0]["strike"] if idx.get("top_pe_oi") else None,
        "expected_range_high": idx["top_ce_oi"][0]["strike"] if idx.get("top_ce_oi") else None,
        "votes": [{"signal": s, "sentiment": sent, "note": n} for s, sent, n in votes],
        "tally": {"bull": bull, "bear": bear, "neutral": neut, "net": net},
        "bias": bias,
    }


def summarise_fii(fii_data: dict | None) -> dict | None:
    if not fii_data:
        return None
    f = fii_data.get("fii", {})
    if not f:
        return fii_data

    # NSE participant CSV cols: future index long/short, future stock long/short,
    # option index call long/short, etc.  Just surface raw + computed long ratio.
    def fnum(x):
        try: return int(float(str(x).replace(",", "")))
        except: return 0

    fi_long = fnum(f.get("Future Index Long") or f.get("Future_Index_Long"))
    fi_short = fnum(f.get("Future Index Short") or f.get("Future_Index_Short"))
    fs_long = fnum(f.get("Future Stock Long") or f.get("Future_Stock_Long"))
    fs_short = fnum(f.get("Future Stock Short") or f.get("Future_Stock_Short"))

    out = {"raw_url": fii_data.get("raw_url")}
    if fi_long + fi_short > 0:
        out["index_long"]  = fi_long
        out["index_short"] = fi_short
        out["index_long_ratio_pct"] = round(fi_long / (fi_long + fi_short) * 100, 1)
    if fs_long + fs_short > 0:
        out["stock_long"]  = fs_long
        out["stock_short"] = fs_short
        out["stock_long_ratio_pct"] = round(fs_long / (fs_long + fs_short) * 100, 1)
    if "lag_day" in fii_data:
        out["lag_day"] = True
    return out


def top_stock_movers(stocks: list[dict], n: int = 10) -> dict:
    if not stocks:
        return {"gainers": [], "losers": []}
    gainers = sorted([s for s in stocks if (s.get("chgp") or 0) > 0],
                     key=lambda s: -s["chgp"])[:n]
    losers  = sorted([s for s in stocks if (s.get("chgp") or 0) < 0],
                     key=lambda s: s["chgp"])[:n]
    return {"gainers": gainers, "losers": losers}


def main(date_str: str | None = None):
    if date_str is None:
        date_str = dt.date.today().isoformat()
    in_path = DATA / f"{date_str}.json"
    if not in_path.exists():
        print(f"missing {in_path}", file=sys.stderr); return 1
    raw = json.loads(in_path.read_text())

    out: dict = {
        "date": raw["date"],
        "vix": raw.get("vix"),
        "indices": [vote_index(i) for i in raw.get("indices", [])],
        "fii": summarise_fii(raw.get("fii_derivatives")),
        "stocks": top_stock_movers(raw.get("stocks", []), n=8),
    }

    out_path = DATA / f"{date_str}.analysis.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"Wrote {out_path}")

    # print quick CLI summary
    print(f"\n=== {date_str} bias summary ===")
    for i in out["indices"]:
        print(f"  {i['name']:<11}  spot {i['spot']:>9,.0f}  bias {i['bias']:<25}  "
              f"votes B/N/B {i['tally']['bull']}/{i['tally']['neutral']}/{i['tally']['bear']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*([sys.argv[1]] if len(sys.argv) > 1 else [])))
