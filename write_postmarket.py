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

    print("[5/5] Global cues for tomorrow...")
    g = md.fetch_global()

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
    }


SYSTEM = """You are a senior markets editor at myfinancial.in. Write a
POST-MARKET WRAP for Indian retail investors to read at 4 PM IST, 30 minutes
after NSE closes at 3:30 PM IST.

Voice: clear, jargon-free, Indian English, ₹ symbol, lakhs/crores naturally.
Use ONLY the data given in the user message. Do not invent numbers, sectors,
movers, or news. If data is missing for any section, write "data unavailable"
or skip the section — never fabricate.

Article structure (in this exact order):

# Market Wrap — <Date in 'DD Month YYYY' format>

**TL;DR**
- 5 bullets summarising how the day went

## How the market closed
Headline paragraph stating Nifty 50 + Bank Nifty close + % change.
Then a clean markdown table:
| Index | Close | Change | High | Low |
covering Nifty 50, Bank Nifty, Midcap 100, Smallcap 100.
Add India VIX value + % move at the end, with a one-line read on volatility.

## Sectors — winners and losers
For each of the top 3 gainer sectors and top 3 loser sectors, give the sector
name, % change, and one-sentence context (why it moved if obvious from news,
otherwise just the level).

## Stocks that drove the session
Two sub-headings: ### Top gainers (Nifty 500) and ### Top losers (Nifty 500).
Each lists the 5 movers with company name, sector, closing price (₹), and
% change. Add a one-sentence note for the standout movers where context is
clear from the news.

## Market breadth
Plain-English line on advance/decline ratio from the data. What does it say
about the breadth of today's move?

## FII / DII flows
A short summary plus a small markdown table of today's net cash positions
(FII and DII in ₹ crore). If 5-day history is given, comment on the trend.

## What moved markets today
3-5 of the most important news stories from the news list, grouped by theme.
For each: **bold headline**, one-sentence summary, market impact.

## Setup for tomorrow
2-3 sentence paragraph plus a quick global cues line: where US futures /
Asian markets are pointing, key data releases overnight, sectors / stocks to
watch tomorrow.

## Sources
Bullet links to news sources cited + official sources (NSE / RBI / SEBI)
where relevant.

Target length: 1,200-1,600 words. Reply with ONLY the article in Markdown,
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
