"""Generate the daily post-market wrap article from live Indian market data.

Pulls Indian index closes (incl. day's range), sector winners/losers, top 5
N500 gainers/losers, India VIX, market breadth, today's FII/DII, and major
news from the session. Then asks Gemini to write a structured wrap article.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import requests

import market_data as md

HERE = Path(__file__).parent
ARTS = HERE / "articles"
ARTICLES_DIR = HERE / "data" / "articles"
META = ARTICLES_DIR / "post_market.json"
SNAPSHOT = HERE / "data" / "snapshots" / "post_market.json"

CATEGORY = "post_market"


def collect_data() -> dict:
    print("[1/5] Indian indices, sectors, VIX...")
    fyers = md.fyers_client()
    india = md.fetch_india(fyers)

    print("[2/5] Nifty 500 quotes...")
    n500 = md.fetch_n500(fyers)
    n500.sort(key=lambda x: x["chp"], reverse=True)
    gainers = n500[:5]
    losers = list(reversed(n500[-5:])) if n500 else []
    advances = sum(1 for r in n500 if r["chp"] > 0)
    declines = sum(1 for r in n500 if r["chp"] < 0)

    print("[3/5] FII/DII...")
    fiidii = md.fetch_fiidii(days=5)

    print("[4/5] Today's news...")
    news = md.fetch_news(hours_back=12)[:15]

    print("[5/6] Global cues for tomorrow...")
    g = md.fetch_global()

    print("[6/6] F&O long/short build-up (futures OI vs price)...")
    fno = md.fetch_fno_buildup(fyers)

    return {
        "fetched_at": dt.datetime.utcnow().isoformat() + "Z",
        "date": dt.date.today().isoformat(),
        "indices": india["indices"],
        "vix": india["vix"],
        "sectors": india["sectors"],
        "sector_gainers": india["sectors"][:3],
        "sector_losers": list(reversed(india["sectors"][-3:])),
        "gainers": gainers,
        "losers": losers,
        "breadth": {"adv": advances, "dec": declines, "total": len(n500)},
        "fiidii": fiidii,
        "news": news,
        "global_cues": g["cues"],
        "global_indices": g["indices"],
        "fno_buildup": fno,
    }


SYSTEM = """You are a senior markets editor at myfinancial.in. Write a
POST-MARKET WRAP for Indian retail investors to read at 4:30 PM IST, one hour
after NSE closes at 3:30 PM IST.

Voice: clear, jargon-free, Indian English, ₹ symbol, lakhs/crores naturally.
Use ONLY the data given in the user message. Do not invent numbers, sectors,
movers, or news. If data is missing for any section, write "data unavailable"
or skip the section — never fabricate. This is educational, not advice.

Article structure (in this exact order):

# Market Wrap — <Date in 'DD Month YYYY' format>

**TL;DR**
- 6 bullets: how the day went, the biggest factor behind it, the standout
  gainer and loser, the FII/DII stance, and the F&O positioning signal.

## How the market behaved today
Headline paragraph stating Nifty 50 + Bank Nifty close + % change and the shape
of the day (gap open, trend, reversal, range). Then a clean markdown table:
| Index | Close | Change | High | Low |
covering Nifty 50, Bank Nifty, Midcap 100, Smallcap 100.
Add India VIX + % move with a one-line read on volatility.

## What moved the market — the factors
A short, plain-English explainer of WHY the market did what it did today, tying
together the concrete drivers present in the data: global cues, FII/DII flows,
heavy-weight stock moves, sector rotation, VIX, and any big news/event. Be
specific — name the actual sectors and stocks from the data that pushed the
index. This is the "why", not just the "what".

## Sectors — winners and losers
Top 3 gainer sectors and top 3 loser sectors: name, % change, one-line context.

## Stocks that moved the market
### Top 5 gainers (Nifty 500) and ### Top 5 losers (Nifty 500): company name,
sector, close (₹), % change. For standout movers, add one line linking the move
to a specific news item from the data where the connection is clear.

## News that moved stocks
3-6 of the most important news items, grouped by theme. For each: **bold
headline**, one-sentence summary, and which stock/sector/the market it moved.

## F&O build-up — where traders are positioning
Using the F&O build-up data, present four short lists (skip any that are empty):
### Long build-up (bullish — price up, OI up)
### Short build-up (bearish — price down, OI up)
### Short covering (price up, OI down) and ### Long unwinding (price down, OI down)
List up to 5 stocks each with price% and OI%. Then 2-3 sentences of plain-English
**interpretation**: long build-up = fresh buying with conviction (often
continuation); short build-up = fresh selling pressure; short covering = a
bounce from shorts exiting, not always real strength; long unwinding = profit-
taking/weakness. If the build-up data says it is unavailable, state that OI
build-up needs the previous session and will appear from the next wrap.

## Market breadth
Plain-English line on the advance/decline ratio — how broad the move was.

## FII / DII flows
Short summary + small markdown table of today's net FII and DII cash (₹ crore);
comment on the 5-day trend if given, and what it implies.

## Event breakdown — what happened today and how it hit the market
If the news/data points to a specific event today (RBI/Fed decision, a big
result, GDP/CPI/IIP data, expiry, a policy/regulatory move, an index-heavy
company's news), break it down: what the event was, what the market did around
it, and which sectors/stocks reacted. Keep it factual from the data. If no
single defining event, say the session was driven by broad flows/global cues.

## Setup for tomorrow
2-3 sentences + a quick global-cues line: where US/Asian markets point, key
overnight data, and sectors/stocks/levels to watch tomorrow.

## Sources
Bullet links to news sources cited + official sources (NSE / RBI / SEBI).

Target length: 1,400-1,900 words. Reply with ONLY the article in Markdown,
no extra commentary."""


def _fmt(rows, formatter):
    return "\n".join(formatter(r) for r in rows) if rows else "data unavailable"


def _idx_row(r):
    if not r.get("lp"):
        return f"- {r['name']}: data unavailable"
    return (f"- {r['name']}: close {r['lp']:.2f}, "
            f"change {'+' if r.get('chp', 0) >= 0 else ''}{r.get('chp', 0):.2f}%, "
            f"high {r.get('high', 0):.2f}, low {r.get('low', 0):.2f}")


def _sector_row(r):
    return f"- {r['name']}: {'+' if r.get('chp', 0) >= 0 else ''}{r.get('chp', 0):.2f}%"


def _mover_row(r):
    return (f"- {r['company']} ({r['symbol']}, {r['sector']}): "
            f"close ₹{r['lp']:.2f}, "
            f"{'+' if r.get('chp', 0) >= 0 else ''}{r.get('chp', 0):.2f}%, "
            f"change ₹{'+' if r.get('ch', 0) >= 0 else ''}{r.get('ch', 0):.2f}")


def _news_row(r):
    base = f"- [{r['source']}] {r['title']}"
    if r.get("summary"):
        base += f"\n  {r['summary'][:200]}"
    if r.get("link"):
        base += f"\n  {r['link']}"
    return base


def _fno_rows(rows: list[dict]) -> str:
    if not rows:
        return "  (none today)"
    return "\n".join(
        f"  - {r['symbol']}: price {'+' if r['chp'] >= 0 else ''}{r['chp']}%, "
        f"OI {'+' if r['oi_change_pct'] >= 0 else ''}{r['oi_change_pct']}%"
        for r in rows)


def _format_fno_block(fno: dict) -> str:
    if not fno or not fno.get("available"):
        return (fno or {}).get("reason", "data unavailable")
    return (
        f"Scanned {fno['scanned']} F&O stocks that had prior-day OI.\n"
        f"LONG BUILD-UP (price UP + OI UP — fresh longs, bullish conviction):\n"
        f"{_fno_rows(fno['long_buildup'])}\n"
        f"SHORT BUILD-UP (price DOWN + OI UP — fresh shorts, bearish conviction):\n"
        f"{_fno_rows(fno['short_buildup'])}\n"
        f"SHORT COVERING (price UP + OI DOWN — shorts exiting):\n"
        f"{_fno_rows(fno['short_covering'])}\n"
        f"LONG UNWINDING (price DOWN + OI DOWN — longs exiting):\n"
        f"{_fno_rows(fno['long_unwinding'])}")


def build_prompt(data: dict) -> str:
    today = dt.date.today().strftime("%d %B %Y")
    vix = data["vix"]
    vix_line = ("data unavailable" if not vix.get("lp")
                else f"India VIX: {vix['lp']:.2f} "
                     f"({'+' if vix.get('chp', 0) >= 0 else ''}"
                     f"{vix.get('chp', 0):.2f}%)")
    br = data["breadth"]
    return f"""Today is {today}. Write the post-market wrap.

INDIAN INDICES (today's close with day's range):
{_fmt(data['indices'], _idx_row)}

INDIA VIX:
{vix_line}

SECTOR GAINERS (top 3):
{_fmt(data['sector_gainers'], _sector_row)}

SECTOR LOSERS (top 3):
{_fmt(data['sector_losers'], _sector_row)}

TOP 5 NIFTY 500 GAINERS:
{_fmt(data['gainers'], _mover_row)}

TOP 5 NIFTY 500 LOSERS:
{_fmt(data['losers'], _mover_row)}

MARKET BREADTH:
Advances: {br['adv']} | Declines: {br['dec']} | Total: {br['total']}

FII / DII TODAY:
{(lambda t: 'data unavailable' if not t else
  f"- FII net: ₹{t.get('fii_net', 0):,.0f} cr"
  + chr(10) + f"- DII net: ₹{t.get('dii_net', 0):,.0f} cr")(data['fiidii'].get('today', {}))}

FII/DII 5-DAY HISTORY (oldest last):
{_fmt(data['fiidii'].get('history', []),
       lambda h: f"- {h['date']}: FII {h['fii_net']:+,.0f} cr, DII {h['dii_net']:+,.0f} cr")}

TODAY'S NEWS ({len(data['news'])} items):
{_fmt(data['news'], _news_row)}

F&O BUILD-UP (stock futures — today's price move vs day-over-day OI change):
{_format_fno_block(data.get('fno_buildup'))}

GLOBAL CUES (overnight pointers for tomorrow's Indian session):
{_fmt(data['global_cues'], _idx_row)}

Write the article now, following the structure exactly."""


from llm import call_llm as _shared_call_llm


def call_gemini(prompt: str) -> Optional[str]:
    # Post-market wrap written by Qwen + Llama (both draft, then merge).
    # Falls back to the env provider only if OpenRouter is fully unavailable.
    return _shared_call_llm(
        prompt, SYSTEM,
        temperature=0.4,
        max_tokens=16000,
        top_p=0.95,
        provider="qwen_llama",
    )


def slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9\s-]", "", text.lower())
    text = re.sub(r"\s+", "-", text).strip("-")
    return text[:80]


def derive_title(body: str, default: str) -> str:
    m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    return m.group(1).strip() if m else default


def derive_description(body: str) -> str:
    m = re.search(r"\*\*TL;DR\*\*\s*\n((?:[-*]\s+.+\n?)+)", body)
    if m:
        bullets = re.findall(r"^[-*]+\s+(.+)$", m.group(1), re.MULTILINE)[:2]
        joined = " ".join(b.strip() for b in bullets)
        joined = re.sub(r"^[*\-\s]+", "", joined)
        return joined[:158].rstrip(".") + "."
    return ""


def main() -> int:
    data = collect_data()
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(data, indent=2, default=str))

    prompt = build_prompt(data)
    print(f"Calling Gemini with {len(prompt)} char prompt...")
    body = call_gemini(prompt)
    if not body:
        return 1

    today = dt.date.today().isoformat()
    title = derive_title(body, f"Market Wrap — {today}")
    description = derive_description(body) or "Daily post-market wrap"
    title_slug = slugify(title)
    dated_slug = f"{today}-{CATEGORY}-{title_slug}"
    filename = f"{dated_slug}.md"
    canonical = (f"https://myfinancialria.github.io/myfinancial-content/"
                 f"articles/{dated_slug}/")

    words = re.findall(r"[a-zA-Z]{6,}", body.lower())
    stop = {"market", "today", "should", "between", "before"}
    common: dict[str, int] = {}
    for w in words:
        if w in stop:
            continue
        common[w] = common.get(w, 0) + 1
    keywords = [w for w, _ in sorted(common.items(),
                                       key=lambda x: x[1], reverse=True)[:8]]

    frontmatter = (
        "---\n"
        f"title: \"{title.replace(chr(34), chr(39))}\"\n"
        f"date: {today}\n"
        f"author: myfinancial\n"
        f"category: {CATEGORY}\n"
        f"description: \"{description.replace(chr(34), chr(39))}\"\n"
        f"keywords: [{', '.join(keywords)}]\n"
        f"canonical: {canonical}\n"
        f"slug: {dated_slug}\n"
        "---\n\n"
    )
    ARTS.mkdir(exist_ok=True)
    (ARTS / filename).write_text(frontmatter + body)
    print(f"Wrote {ARTS / filename}")

    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    META.write_text(json.dumps({
        "date": today,
        "slug": dated_slug,
        "filename": filename,
        "category": CATEGORY,
        "title": title,
        "description": description,
        "keywords": keywords,
        "canonical": canonical,
        "faq": [],
        "based_on": "live Fyers India quotes + Nifty 500 + FII/DII + RSS",
    }, indent=2, default=str))
    print(f"Wrote {META}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
