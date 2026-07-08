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

    print("[6/8] Overnight news (RSS)...")
    news = md.fetch_news(hours_back=14)
    news = news[:15]  # most-recent first; the model ranks within the article

    print("[7/8] Technical levels (CPR / pivots / swings) via Fyers...")
    technicals = md.fetch_index_technicals(fyers)

    print("[8/8] Option-chain OI levels (support/resistance)...")
    oi_levels = md.fetch_oi_levels(fyers)

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
        "technicals": technicals,
        "oi_levels": oi_levels,
    }


# ---- Prompt construction ----
SYSTEM = """You are a senior markets editor at myfinancial.in. Write a
PRE-MARKET BRIEF for Indian retail investors and traders to read at 8:00 AM
IST before NSE opens at 9:15 AM IST.

Voice: clear, jargon-free, Indian English, ₹ symbol, lakhs/crores naturally.
Reader profile: salaried + self-employed Indians, NRIs and active traders.
Treats their money seriously — no clickbait, no broker tips, no "should you
buy" speculation.

CRITICAL RULES
- Use ONLY the data given in the user message for any number, level, name or
  news item. If a value is missing or zero, write "data unavailable" or skip the
  line — NEVER fabricate a number or a headline.
- Every data section must end with a short **Interpretation:** line in plain
  English — what it means and how it could affect today's Indian market. This is
  the most important part: readers want the *so what*, not just the numbers.
- This is educational, not investment advice. No buy/sell/target calls.

Article structure (in this exact order):

# Pre-Market Brief — <Date in 'DD Month YYYY' format>

**TL;DR**
- 6 punchy bullets: global tone, GIFT Nifty bias, FII/DII stance, the single
  biggest news, key Nifty level to watch, and the day's main risk.

## How global markets traded — and what it means for India
A short paragraph plus a clean table of the global indices given (Dow, Nasdaq,
S&P 500, FTSE, Nikkei, Hang Seng, Shanghai) with % change. **Interpretation:**
what the overnight tone (US close + Asia this morning) signals for the Indian open.

## Currency, commodities and yields
Cover USD/INR, Dollar Index, Brent/WTI, Gold, US 10Y Yield in plain English.
**Interpretation:** what each move means for India (e.g. crude ↑ → OMCs/paint/
aviation pressure; USD/INR ↑ → IT/pharma tailwind, importer pressure; yields ↑
→ FII flow risk).

## GIFT Nifty — what it's signalling
State GIFT Nifty's level and % change and the gap-up/gap-down it points to for
the Nifty open. If unavailable, say so.

## FII/DII flows — who's driving the tape
Two sentences plus a tiny markdown table of yesterday's net FII and DII cash
positions (₹ crore) and, if given, the 5-session trend. **Interpretation:** what
the flow stance means for market direction and which side has been supporting it.

## Key levels to watch — Nifty & Bank Nifty (technical)
For each index given in the technicals data, present a compact table with the
CPR (pivot, top, bottom), R1/R2 (resistance), S1/S2 (support), the recent swing
high/low and the 20-/50-DMA. **Interpretation:** where the day's likely range
sits, what a break above resistance or below support would signal, and what a
narrow vs wide CPR implies (narrow CPR → trending day likely; wide CPR →
range/sideways). Only use the numbers provided.

## Option-chain signals (OI) — where support & resistance sit
For each index in the OI data, state the highest call-OI strike(s) (acting as
resistance), the highest put-OI strike(s) (acting as support) and the PCR.
**Interpretation:** in simple words — high call OI = sellers expect a ceiling
there; high put OI = buyers defending that floor; PCR > 1 leans supportive/
bullish-to-neutral, PCR < 0.7 leans cautious. Combine with the technical levels
into a single "levels to respect today" takeaway.

## Companies reporting results today
If the list is non-empty, group them and add one-line context for recognisable
names and which sector's mood they could set. Skip if empty.

## Corporate actions today
List ex-dividend / split / bonus / AGM ex-dates with the company and a one-line
explanation of what each means for shareholders (e.g. price adjusts down by the
dividend on ex-date). Skip section if empty.

## Stock & sector news that matters
3-6 of the most market-relevant news items from the news list. For each:
**Headline** (bold), one-sentence summary, and **why it matters** for the stock/
sector/Indian market. Call out any item tied to a specific listed company.

## Events & data to watch — and how markets usually react
From the news and scheduled context, list the key events/data that could move
Indian markets today or this week (e.g. RBI policy, US Fed, CPI/GDP prints,
F&O expiry, auto/GST monthly data, global central-bank speak). For each, add a
brief, GENERAL note on how markets have *typically* reacted to that kind of event
in the past (volatility around policy days, expiry-day churn, etc.) — described
qualitatively, WITHOUT inventing specific past figures. If nothing notable is
scheduled, say so.

## What to watch in today's session
Numbered list of 4-6 specific things to monitor: the levels above, stocks
reporting, sectors in focus from the news, and the day's main risk.

## Bottom line
2-3 sentence conclusion: where the open is biased, the key level that decides
the day, and what to be cautious about. No advice, no buy/sell calls.

## Sources
Bullet links to the news sources cited + official sources (RBI / SEBI / NSE)
where relevant.

Target length: 1,300-1,800 words. Reply with ONLY the article in Markdown,
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


def _format_tech_block(rows: list[dict]) -> str:
    if not rows:
        return "data unavailable"
    out = []
    for r in rows:
        if not r.get("available"):
            out.append(f"- {r.get('name')}: data unavailable")
            continue
        cpr, res, sup = r["cpr"], r["resistance"], r["support"]
        out.append(
            f"- {r['name']} (prev close {r['prev_close']}): "
            f"CPR pivot {cpr['pivot']} (TC {cpr['tc']} / BC {cpr['bc']}, "
            f"width {cpr['width_pct']}%); "
            f"R1 {res['r1']}, R2 {res['r2']}, R3 {res['r3']}; "
            f"S1 {sup['s1']}, S2 {sup['s2']}, S3 {sup['s3']}; "
            f"swing high {r['swing_high']}, swing low {r['swing_low']}; "
            f"20-DMA {r['dma20']}, 50-DMA {r['dma50']}")
    return "\n".join(out)


def _format_oi_block(rows: list[dict]) -> str:
    if not rows:
        return "data unavailable"
    out = []
    for r in rows:
        if not r.get("available"):
            out.append(f"- {r.get('name')}: data unavailable")
            continue
        res = ", ".join(f"{x['strike']} (OI {x['oi']:,})" for x in r["resistance"])
        sup = ", ".join(f"{x['strike']} (OI {x['oi']:,})" for x in r["support"])
        out.append(
            f"- {r['name']}: PCR {r.get('pcr')}; "
            f"highest CALL OI (resistance) → {res}; "
            f"highest PUT OI (support) → {sup}")
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

KEY TECHNICAL LEVELS (Nifty & Bank Nifty, computed from the previous session):
{_format_tech_block(data.get('technicals', []))}

OPTION-CHAIN OI LEVELS (nearest expiry — highest OI strikes):
{_format_oi_block(data.get('oi_levels', []))}

Write the article now, following the structure exactly."""


# ---- LLM call (shared dispatcher: gemini default w/ Google Search grounding) ----
from llm import call_llm as _shared_call_llm


def call_gemini(prompt: str) -> Optional[str]:
    # Pre-market brief written by Qwen + Llama (both draft, then merge).
    # Low temp for a factual brief. Falls back to the env provider only if
    # OpenRouter is fully unavailable (see llm._call_qwen_llama).
    return _shared_call_llm(
        prompt, SYSTEM,
        temperature=0.4,
        max_tokens=16000,
        top_p=0.95,
        provider="qwen_llama",
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
