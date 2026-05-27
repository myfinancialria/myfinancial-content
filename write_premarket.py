"""Generate the daily pre-market article by feeding live market data to Gemini.

Pulls global indices/cues, GIFT Nifty, today's expected results, today's
ex-date corporate actions, FII/DII from yesterday, and overnight news. Then
asks Gemini to write a structured, simple-language article aimed at Indian
investors/traders before market open.

Output (when CATEGORY=pre_market is set externally — or always, since this
script is always pre_market):
  articles/<date>-pre_market-<slug>.md
  data/articles/pre_market.json
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
META = ARTICLES_DIR / "pre_market.json"
SNAPSHOT = HERE / "data" / "snapshots" / "pre_market.json"

CATEGORY = "pre_market"


# ---- Data collection ----
def collect_data() -> dict:
    """Fetch everything needed. Each fetch fails soft if a source is down."""
    print("[1/6] Global indices + cues via yfinance...")
    g = md.fetch_global()

    print("[2/6] GIFT Nifty via Fyers...")
    fyers = md.fyers_client()
    gift = md.fetch_gift_nifty(fyers)

    print("[3/6] Today's expected results (NSE)...")
    results = md.fetch_results_today()

    print("[4/6] Today's corporate actions (NSE)...")
    corp = md.fetch_corp_actions_today()

    print("[5/6] Recent FII/DII flows...")
    fiidii = md.fetch_fiidii(days=5)

    print("[6/6] Overnight news (RSS)...")
    news = md.fetch_news(hours_back=14)
    # Take top 15 most recent — Gemini ranks within the article
    news = news[:15]

    return {
        "fetched_at": dt.datetime.utcnow().isoformat() + "Z",
        "date": dt.date.today().isoformat(),
        "global_indices": g["indices"],
        "global_cues": g["cues"],
        "gift_nifty": gift,
        "results_today": results,
        "corp_actions_today": corp,
        "fiidii": fiidii,
        "news": news,
    }


# ---- Prompt construction ----
SYSTEM = """You are a senior markets editor at myfinancial.in. Write a
PRE-MARKET BRIEF for Indian retail investors and traders to read at 8:15 AM
IST before NSE opens at 9:15 AM IST.

Voice: clear, jargon-free, Indian English, ₹ symbol, lakhs/crores naturally.
Reader profile: salaried + self-employed Indians, NRIs. Treats their money
seriously — no clickbait, no broker tips, no "should you buy" speculation.

Use ONLY the data given in the user message. Do not invent numbers, sectors,
or news items. If a value is missing or zero, write "data unavailable" or
skip the line — never fabricate.

Article structure (in this exact order):

# Pre-Market Brief — <Date in 'DD Month YYYY' format>

**TL;DR**
- 5 punchy bullets summarising the most important takeaways for today

## Where global markets closed
A short paragraph plus a clean table of the global indices given (Dow, Nasdaq,
S&P 500, FTSE, Nikkei, Hang Seng, Shanghai) with % change. End with one line
on what the overall global tone says.

## Currency, commodities and yields
Cover USD/INR, Dollar Index, Brent/WTI, Gold, US 10Y Yield in plain English —
what's up, what's down, what each move means for Indian markets.

## GIFT Nifty — what it's signalling
If GIFT Nifty data is given, state its level and % change. Explain what
direction this points the Indian open. If data is unavailable, say so.

## Companies reporting results today
If the list is non-empty, group them and add one-line context for the
recognisable names. Skip if empty.

## Corporate actions today
List ex-dividend / split / bonus / AGM ex-dates with the company and one-line
explanation of what each means for shareholders. Skip section if empty.

## Recent FII/DII flows
A two-sentence summary plus a tiny markdown table of yesterday's net cash
positions for FII and DII (in ₹ crore). If 5-day trend is provided, note
direction.

## Overnight news that matters
3-5 of the most market-relevant news items from the news list. For each:
**Headline** (bold), one-sentence summary, why it matters to Indian markets.

## What to watch in today's session
Numbered list of 3-5 specific things investors should monitor today (sectors,
stocks reporting, key data releases, levels).

## Bottom line
2-3 sentence concluding paragraph: where the open is biased, what to be
cautious about. No advice, no buy/sell calls.

## Sources
Bullet links to the news sources cited in the article + official sources
(Income Tax India / RBI / SEBI / NSE) where relevant.

Target length: 1,100-1,500 words. Reply with ONLY the article in Markdown,
no extra commentary."""


def _format_indices_block(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        if not r.get("lp"):
            lines.append(f"- {r['name']}: data unavailable")
            continue
        lines.append(
            f"- {r['name']}: {r['lp']:.2f}  "
            f"({'+' if r.get('chp', 0) >= 0 else ''}{r.get('chp', 0):.2f}%)"
        )
    return "\n".join(lines)


def _format_cues_block(rows: list[dict]) -> str:
    return _format_indices_block(rows)


def _format_fiidii_block(fii: dict) -> str:
    if not fii.get("today"):
        return "data unavailable"
    t = fii["today"]
    lines = [
        f"Yesterday ({t['date']}):",
        f"- FII net: ₹{t['fii_net']:,.0f} cr",
        f"- DII net: ₹{t['dii_net']:,.0f} cr",
    ]
    if len(fii.get("history", [])) >= 2:
        lines.append("\nLast 5 sessions:")
        for h in fii["history"][:5]:
            lines.append(f"- {h['date']}: FII {h['fii_net']:+,.0f} cr, "
                          f"DII {h['dii_net']:+,.0f} cr")
    return "\n".join(lines)


def _format_results_block(rows: list[dict]) -> str:
    if not rows:
        return "No Nifty 500 / large-cap results scheduled today."
    return "\n".join(f"- **{r['symbol']}**: {r['purpose']}" for r in rows[:25])


def _format_corp_block(rows: list[dict]) -> str:
    if not rows:
        return "No major ex-dates today."
    return "\n".join(f"- **{r['symbol']}**: {r['subject']}" for r in rows[:25])


def _format_news_block(rows: list[dict]) -> str:
    if not rows:
        return "No overnight news available."
    out = []
    for r in rows:
        out.append(f"- [{r['source']}] {r['title']}")
        if r.get("summary"):
            out.append(f"  {r['summary'][:200]}")
        if r.get("link"):
            out.append(f"  {r['link']}")
    return "\n".join(out)


def build_prompt(data: dict) -> str:
    today = dt.date.today().strftime("%d %B %Y")
    gift = data["gift_nifty"]
    gift_line = ("data unavailable" if not gift.get("lp")
                 else f"GIFT Nifty: {gift['lp']:.2f} "
                      f"({'+' if gift.get('chp', 0) >= 0 else ''}"
                      f"{gift.get('chp', 0):.2f}%)")
    return f"""Today is {today}. Write the pre-market brief.

GLOBAL INDICES (yesterday's close):
{_format_indices_block(data['global_indices'])}

CURRENCIES / COMMODITIES / YIELDS:
{_format_cues_block(data['global_cues'])}

GIFT NIFTY:
{gift_line}

COMPANIES REPORTING RESULTS TODAY ({len(data['results_today'])} entries):
{_format_results_block(data['results_today'])}

CORPORATE ACTIONS — EX-DATE TODAY ({len(data['corp_actions_today'])} entries):
{_format_corp_block(data['corp_actions_today'])}

FII / DII FLOWS:
{_format_fiidii_block(data['fiidii'])}

OVERNIGHT NEWS ({len(data['news'])} items, most-recent first):
{_format_news_block(data['news'])}

Write the article now, following the structure exactly."""


# ---- LLM call (shared dispatcher: gemini default w/ Google Search grounding) ----
from llm import call_llm as _shared_call_llm


def call_gemini(prompt: str) -> Optional[str]:
    # Pre-market brief: low temp (factual), large output, grounding ON for
    # overnight news freshness.
    return _shared_call_llm(
        prompt, SYSTEM,
        temperature=0.4,
        max_tokens=16000,
        top_p=0.95,
    )


# ---- Article post-processing ----
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


def extract_faq(body: str) -> list[dict]:
    return []  # pre-market brief doesn't typically have FAQ


def main() -> int:
    data = collect_data()
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(data, indent=2, default=str))
    print(f"Snapshot saved: {SNAPSHOT}")

    prompt = build_prompt(data)
    print(f"Calling Gemini with {len(prompt)} char prompt...")
    body = call_gemini(prompt)
    if not body:
        print("Gemini failed — aborting", file=sys.stderr)
        return 1

    today = dt.date.today().isoformat()
    title = derive_title(body, f"Pre-Market Brief — {today}")
    description = derive_description(body) or "Daily pre-market brief"
    title_slug = slugify(title)
    dated_slug = f"{today}-{CATEGORY}-{title_slug}"
    filename = f"{dated_slug}.md"
    canonical = (f"https://myfinancialria.github.io/myfinancial-content/"
                 f"articles/{dated_slug}/")

    # Keywords — extract top common words
    words = re.findall(r"[a-zA-Z]{6,}", body.lower())
    stop = {"market", "today", "should", "between", "before"}
    common: dict[str, int] = {}
    for w in words:
        if w in stop:
            continue
        common[w] = common.get(w, 0) + 1
    keywords = [w for w, _ in sorted(common.items(), key=lambda x: x[1],
                                       reverse=True)[:8]]

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
        "based_on": "live data + RSS news + Fyers India quotes",
    }, indent=2, default=str))
    print(f"Wrote {META}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
