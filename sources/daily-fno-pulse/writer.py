"""Generate a retail-friendly EOD F&O interpretation article via Gemini.

SEBI compliance is non-negotiable: educational tone only. Explicit:
  - NO buy/sell recommendations
  - NO target prices for any security
  - NO advisory language ("you should ...")
  - Frame everything as "the data shows X, which historically tends to mean Y"
  - End with disclaimer + author NISM-only status

Reads data/<date>.analysis.json (from analyzer.py).
Writes articles/<date>-fno-pulse.md.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests

HERE = Path(__file__).parent
DATA = HERE / "data"
ARTS = HERE / "articles"
ARTS.mkdir(exist_ok=True)


SYSTEM = """You are a patient, jargon-light financial educator writing the
daily Indian F&O end-of-day note for myfinancial.in readers (mass-affluent
salaried earners + NRIs). You explain how to READ the day's options open
interest and futures positioning data — not what to trade. Your readers
are intelligent but not professional traders; assume they know what a Call
and Put are but may not know what "max pain" or "PCR" mean — define jargon
on first use in plain English.

HARD RULES (SEBI compliance — your author holds NISM only, NOT SEBI RA/RIA):
1. NEVER recommend specific buy/sell/hold actions on any security.
2. NEVER state price targets.
3. NEVER use advisory phrases: "you should buy", "I recommend", "go long",
   "trade this", "this is a sure thing".
4. SAFE phrasing: "the data suggests X", "historically this pattern has
   tended to coincide with Y", "writers are positioned for Z".
5. Always include the disclaimer block at the bottom (provided in prompt).
6. Educational, descriptive, retrospective interpretation only.

VOICE:
- Indian English, ₹ symbol, lakhs/crores naturally
- Calm, clear, NEWSROOM tone (not hype, not fear)
- 800-1100 words total
- Open with a one-sentence headline that captures the dominant signal
- Use H2 (##) for sections, never H1
"""


USER_TEMPLATE = """Today's date: {date}
India VIX: {vix}

INDEX SNAPSHOTS — each index has a structured "bias vote" already done:

{indices_block}

FII derivative positioning (NSE participant CSV, end-of-day):
{fii_block}

Top stock movers (F&O watchlist):
{stocks_block}

---

Write the article now in the following structure:

# (skip — this is supplied by frontmatter)

**TL;DR** — three bullets, plain-English, what the day's positioning suggests for tomorrow's session bias for each major index.

## What the indices did today
One short paragraph per index (NIFTY 50, SENSEX, BANK NIFTY) covering: spot, day's change, where it closed vs the option-chain walls, and a one-line interpretation.

## Decoding today's open interest
Explain what the highest Call OI strike and highest Put OI strike actually mean (as a teaching moment). Then tell the reader what today's biggest fresh writing tells us — which strikes attracted new sellers (calls or puts), at what levels relative to spot.

## PCR — what the put-call ratio is whispering
Define PCR briefly. State today's PCR(OI) and PCR(today's flow) for each index, and what the combination means in plain language.

## Max pain and the magnet effect
Explain what max pain is. Show where each index's max pain sits vs spot. Note this is a stronger pull as expiry approaches.

## FII positioning — what the big money did today
Use the FII derivatives block. Note the long ratio in index futures, change vs prior day if available, and what that historically tends to coincide with.

## Stocks where money moved today
List the top 3-5 gainers and losers from the watchlist. Note any unusual volume. Treat as observational only.

## What this combination historically tends to mean for tomorrow
A measured paragraph synthesising the votes. NO predictions, NO targets, NO trade calls. Frame as "when these signals align in this direction, the next session has historically tended to..."

## How to read this yourself daily
Two-paragraph teaching note: what data points to pull, where (NSE site, broker), and how to combine them. Empower the reader.

---

End with EXACTLY this disclaimer block, verbatim:

> **Disclaimer:** This article is published for educational and analytical
> purposes only. The author holds a NISM certification but is not a SEBI
> Registered Investment Adviser or Research Analyst. Nothing here
> constitutes investment advice, a recommendation to buy, sell or hold any
> security, or a forecast of future prices. Markets carry risk; please
> consult a SEBI-registered adviser before making any investment decision.
> Data sourced from NSE, BSE, and Fyers (broker API).

Now write the article."""


def _call_gemini(prompt: str, system: str) -> Optional[str]:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY missing", file=sys.stderr); return None
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],   # grounding so it can verify NSE/BSE data freshness
        "generationConfig": {
            "temperature": 0.5,
            "maxOutputTokens": 12000,
            "topP": 0.95,
        },
    }
    delays = [10, 30, 60]
    for attempt in range(len(delays) + 1):
        try:
            r = requests.post(url, json=payload, timeout=180)
            if 400 <= r.status_code < 500 and r.status_code != 429:
                print(f"Gemini {r.status_code}: {r.text[:400]}", file=sys.stderr)
                return None
            if r.status_code in (429, 500, 502, 503, 504):
                if attempt < len(delays):
                    time.sleep(delays[attempt]); continue
                print(f"Gemini gave up: {r.status_code}", file=sys.stderr); return None
            r.raise_for_status()
            j = r.json()
            parts = j["candidates"][0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts)
        except requests.exceptions.RequestException as e:
            if attempt < len(delays):
                time.sleep(delays[attempt]); continue
            print(f"Gemini network error: {e}", file=sys.stderr); return None


def fmt_indices(indices: list[dict]) -> str:
    lines = []
    for i in indices:
        lines.append(f"### {i['name']}")
        lines.append(f"- Spot: {i['spot']:,.2f}  (today {i['chgp']:+.2f}%)")
        lines.append(f"- ATM: {i['atm']}   |   Max pain: {i['max_pain']}")
        lines.append(f"- PCR(OI): {i['pcr_oi']}   PCR(today flow ΔOI): {i['pcr_doi']}")
        if i.get("expected_range_low") and i.get("expected_range_high"):
            lines.append(f"- Option-chain implied range (max OI walls): "
                         f"{i['expected_range_low']} – {i['expected_range_high']}")
        lines.append(f"- **Bias from 8-vote check: {i['bias']}** "
                     f"(bull/neut/bear: {i['tally']['bull']}/{i['tally']['neutral']}/{i['tally']['bear']})")
        if i.get("votes"):
            lines.append("- Individual signals:")
            for v in i["votes"]:
                lines.append(f"   - [{v['sentiment'].upper()}] {v['signal']}: {v['note']}")
        lines.append("")
    return "\n".join(lines)


def fmt_fii(fii: dict | None) -> str:
    if not fii:
        return "(NSE participant CSV not yet available at fetch time. Often publishes by ~18:00 IST.)"
    lines = []
    if "index_long_ratio_pct" in fii:
        lines.append(f"- FII Index futures long ratio: **{fii['index_long_ratio_pct']}%** "
                     f"(long {fii.get('index_long'):,}, short {fii.get('index_short'):,})")
    if "stock_long_ratio_pct" in fii:
        lines.append(f"- FII Stock futures long ratio: **{fii['stock_long_ratio_pct']}%** "
                     f"(long {fii.get('stock_long'):,}, short {fii.get('stock_short'):,})")
    if fii.get("lag_day"):
        lines.append("- (Showing yesterday's data — today's NSE archive not yet published)")
    if fii.get("raw_url"):
        lines.append(f"- Source: {fii['raw_url']}")
    return "\n".join(lines) if lines else "(present but couldn't parse — investigate fetcher.py)"


def fmt_stocks(stocks: dict) -> str:
    g = stocks.get("gainers", []); l = stocks.get("losers", [])
    lines = ["TOP GAINERS:"] + [
        f"- {s['ticker']}: ₹{s['spot']:.2f}  ({s['chgp']:+.2f}%, vol {s.get('volume',0):,})"
        for s in g[:5]
    ] + ["TOP LOSERS:"] + [
        f"- {s['ticker']}: ₹{s['spot']:.2f}  ({s['chgp']:+.2f}%, vol {s.get('volume',0):,})"
        for s in l[:5]
    ]
    return "\n".join(lines)


def slugify(date_str: str) -> str:
    return f"{date_str}-fno-pulse"


def main(date_str: str | None = None):
    if date_str is None:
        date_str = dt.date.today().isoformat()
    a_path = DATA / f"{date_str}.analysis.json"
    if not a_path.exists():
        print(f"missing {a_path} — run analyzer.py first", file=sys.stderr); return 1
    a = json.loads(a_path.read_text())

    vix = a.get("vix") or {}
    vix_str = (f"{vix.get('ltp')} ({vix.get('chgp',0):+.2f}%)"
               if vix else "n/a")

    prompt = USER_TEMPLATE.format(
        date=a["date"], vix=vix_str,
        indices_block=fmt_indices(a.get("indices", [])),
        fii_block=fmt_fii(a.get("fii")),
        stocks_block=fmt_stocks(a.get("stocks", {})),
    )

    print("Calling Gemini ...")
    body = _call_gemini(prompt, SYSTEM)
    if not body:
        print("LLM call failed — falling back to deterministic article", file=sys.stderr)
        body = fallback_article(a)

    title = (f"India F&O Pulse — {dt.date.fromisoformat(date_str).strftime('%d %b %Y')}: "
             f"what the day's options & futures positioning is whispering")
    description = ("End-of-day reading of India's F&O open interest, PCR, max pain and "
                   "FII positioning — explained simply.")
    front = "\n".join([
        "---",
        f'title: "{title}"',
        f"date: {date_str}",
        "author: myfinancial editorial team",
        "category: fno-pulse",
        f'description: "{description}"',
        f"slug: {slugify(date_str)}",
        f"canonical: https://myfinancialria.github.io/daily-fno-pulse/articles/{slugify(date_str)}/",
        "---",
        ""
    ])
    out_path = ARTS / f"{slugify(date_str)}.md"
    out_path.write_text(front + f"# {title}\n\n" + body.strip() + "\n")
    print(f"Wrote {out_path}")
    return 0


def fallback_article(a: dict) -> str:
    """Deterministic backup if Gemini is down — still useful, just less polish."""
    parts = ["**TL;DR**\n"]
    for i in a.get("indices", []):
        parts.append(f"- **{i['name']}**: closed at {i['spot']:,.2f} "
                     f"({i['chgp']:+.2f}%). Read: {i['bias']}.")
    parts.append("")
    parts.append("## What the indices did today\n")
    for i in a.get("indices", []):
        parts.append(f"**{i['name']}** closed at {i['spot']:,.2f} ({i['chgp']:+.2f}%). "
                     f"ATM strike for the nearest weekly expiry: {i['atm']}. "
                     f"Option-chain implied range "
                     f"({i.get('expected_range_low','?')}–{i.get('expected_range_high','?')}) "
                     f"with max pain at {i['max_pain']}. PCR(OI) {i['pcr_oi']}. "
                     f"Eight-vote bias check: **{i['bias']}**.\n")
    parts.append("## How to read this\n")
    parts.append("Compare today's spot vs the highest Call OI strike (potential ceiling) and "
                 "highest Put OI strike (potential floor). When fresh writing today is "
                 "concentrated on calls just above spot, it tends to coincide with a session "
                 "where the upper band acts as resistance the next day, and vice versa.\n")
    parts.append("\n> **Disclaimer:** This article is published for educational and analytical "
                 "purposes only. The author holds a NISM certification but is not a SEBI "
                 "Registered Investment Adviser or Research Analyst. Nothing here "
                 "constitutes investment advice...\n")
    return "\n".join(parts)


if __name__ == "__main__":
    sys.exit(main(*([sys.argv[1]] if len(sys.argv) > 1 else [])))
