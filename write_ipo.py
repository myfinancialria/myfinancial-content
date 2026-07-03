"""Write the two 'IPO Watch' reports from data/ipo.json — strictly educational.

Report 1 (category = ipo_upcoming): "Upcoming IPOs, Explained Simply"
    Walks through the IPOs currently open or lined up: what each company does,
    what the price band / lot size / issue size actually mean, the key dates,
    and how the IPO process works end-to-end.

Report 2 (category = ipo_listing): "IPO Report Card — 30 to 60 Days After Listing"
    Looks at IPOs that listed more than 30 and less than 60 days ago: their IPO
    price, listing-day move, where they trade now, and — most importantly — WHY
    listing pops and drops happen. A plain-English lesson in reading a listing.

HARD RULE baked into the prompt: NO recommendations of any kind. No
buy/sell/subscribe/avoid/hold calls, no "good IPO / bad IPO" verdicts, no price
targets or predictions. myfinancial is not a SEBI-registered adviser — these are
educational explainers only.

Output matches every existing convention (frontmatter + data/articles/<cat>.json)
so generate_image.py / fact_check.py / publish.py consume them unchanged. Run
with no args to produce BOTH reports; set IPO_REPORT=upcoming|listing for one.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

from llm import call_llm as _shared_call_llm

HERE = Path(__file__).parent
DATA = HERE / "data"
ARTS = HERE / "articles"
ARTICLES_DIR = DATA / "articles"
IPO_JSON = DATA / "ipo.json"

BASE_URL = "https://myfinancialria.github.io/myfinancial-content"

SYSTEM = """You write the 'IPO Watch' educational column for myfinancial.in — a trusted Indian personal-finance publication.

Your one job: help an ordinary Indian UNDERSTAND IPOs — what they are, how they work, and how to read the numbers — using this week's real IPOs as teaching examples. A curious 15-year-old, a retiree, and a busy parent should all understand you on the first read.

Voice & rules:
- Plain, warm, Indian English. Short sentences. Define every technical term the moment you use it, in brackets — e.g. "price band (the fixed range within which you can bid)".
- Use the rupee symbol (₹) and lakhs/crores naturally.
- Use ONLY the facts and figures given to you in the data block. Do not invent numbers, dates, or company details. If a figure is missing, say "not yet announced" rather than guessing.
- Explain concepts with one everyday analogy each (a shop selling shares in itself, a school fete stall, etc.).

ABSOLUTE RULE — you are NOT a SEBI-registered investment adviser:
- NEVER tell the reader to subscribe / apply / buy / sell / avoid / hold anything.
- NEVER call an IPO "good", "bad", "attractive", "overpriced", "a must", or rate it.
- NEVER give price targets, predict listing gains, or forecast where a stock will go.
- NEVER mention or endorse "grey market premium (GMP)" as a signal.
- Your job is to EXPLAIN what the numbers mean and how the process works, so the reader can think for themselves. Explaining ≠ advising.

Structured, skimmable, friendly. No filler, no hype, no clickbait. Reply with ONLY the article in clean Markdown — no preamble, no commentary."""

UPCOMING_TEMPLATE = """Today is {today}. Write the report **"Upcoming IPOs, Explained Simply"**.

Here is the real data on IPOs that are currently open or lined up (use ONLY this):

{data}

Write the article in this EXACT structure:

# Upcoming IPOs, Explained Simply — {month_year}

**TL;DR**
- 4 to 5 one-line bullets naming the IPOs in the pipeline and what a reader will learn (purely factual, no verdicts).

## First, what is an IPO — in one minute?
Explain, with a simple analogy, what an IPO is and why a company does one. Define "IPO", "primary market", and "listing".

## The IPOs on the calendar right now
For EACH company in the data, a short `###` sub-section:
- One line on what the business does (only if you can tell from the name/data; otherwise say the sector is not specified).
- Its price band, lot size, issue size and open/close dates, each explained in plain words the first time (what a "lot" is, what "issue size" means, etc.).
Present the hard numbers as a small Markdown table too.

## How to actually read an IPO (the 6 things on every IPO)
Teach the reader what each standard IPO field means: price band, lot size, minimum investment, issue size, fresh issue vs offer-for-sale, and the RHP/DRHP (the official prospectus). Neutral definitions only.

## The IPO process, step by step
Numbered steps from DRHP → price band → bidding (retail/HNI/QIB categories) → allotment → listing. Define each term.

## A simple way to think about it
One everyday analogy that makes "a company selling part of itself to the public" click.

## Things people get confused about
2 to 3 "Myth → Fact" corrections (e.g. "Listing gain is guaranteed" → Fact...). Keep them educational, never a call to act.

## FAQ
4 to 5 short ### question headings, each with a 1-2 sentence answer (e.g. "How do I even apply for an IPO?", "What is a lot size?").

## Sources
NSE upcoming/current issues data, and any official prospectus links only if present in the data. Never invent a URL.

End with one line, italicised: *This is an educational explainer, not investment advice. myfinancial is not a SEBI-registered adviser.*

Length: 1,000-1,400 words. Write the article now."""

LISTING_TEMPLATE = """Today is {today}. Write the report **"IPO Report Card — 30 to 60 Days After Listing"**.

Every IPO below listed MORE THAN 30 and LESS THAN 60 days ago — old enough that the listing-day frenzy has faded, so the current price is a calmer read. Here is the real data (use ONLY this). "return_vs_issue_pct" = change from the IPO price to the current price; "listing_gain_pct" = IPO price to listing-day open; "return_since_listing_pct" = listing-day to now:

{data}

Write the article in this EXACT structure:

# IPO Report Card: 30 to 60 Days After Listing — {month_year}

**TL;DR**
- 4 to 5 one-line factual bullets summarising how this batch has done (numbers only, no verdicts).

## Why look 30 to 60 days after listing?
Explain, simply, why the first day's pop tells you little and why checking a month or two later — after the initial excitement and anchor-investor lock-in fade — is a calmer, more instructive read. Define "listing gain" and "listing day".

## The scorecard
A clear Markdown table of every company in the data: Company, IPO price (₹), Listing-day open (₹), Listing gain (%), Price now (₹), Change vs IPO price (%), Days since listing. Then 1-2 factual sentences under the table describing the spread (how many are above vs below their IPO price) — describe, do NOT judge.

## Reading each listing (what the numbers say)
For EACH company a short `###` sub-section stating its numbers in words and explaining what "up X% from its IPO price" or "below issue price" factually means for someone who was allotted shares. No opinions, no predictions.

## Why do IPOs pop or drop on listing?
Teach the mechanics: demand vs supply, subscription levels, market mood, pricing, lock-in and anchor investors. Define each term. Explain both a pop and a drop neutrally.

## Why the first-day price is not the whole story
Explain volatility, the role of the broader market, and why a stock can list flat then move a lot (or vice-versa) — as concepts.

## A simple way to think about it
One everyday analogy for "the price the market settles on after the excitement fades".

## Things people get confused about
2 to 3 "Myth → Fact" corrections (e.g. "A big listing gain means it's a great company" → Fact...).

## FAQ
4 to 5 short ### question headings with 1-2 sentence answers.

## Sources
NSE public past issues data and current market prices (Fyers). Never invent a URL.

End with one line, italicised: *This is an educational explainer, not investment advice. Past performance is not indicative of future results. myfinancial is not a SEBI-registered adviser.*

Length: 1,000-1,400 words. Write the article now."""


REPORTS = {
    "upcoming": {
        "category": "ipo_upcoming",
        "template": UPCOMING_TEMPLATE,
        "fallback_title": "Upcoming IPOs, Explained Simply",
        "data_key": "upcoming",
    },
    "listing": {
        "category": "ipo_listing",
        "template": LISTING_TEMPLATE,
        "fallback_title": "IPO Report Card: 30 to 60 Days After Listing",
        "data_key": "recent_listings",
    },
}


def slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9\s-]", "", text.lower())
    text = re.sub(r"\s+", "-", text).strip("-")
    return text[:80]


def call_llm(prompt: str, system: str) -> Optional[str]:
    # Facts come from our own data block, so grounding is off — we want the model
    # to stick to what we gave it, not browse. Low temperature for accuracy.
    return _shared_call_llm(
        prompt, system,
        temperature=0.45,
        max_tokens=16000,
        top_p=0.95,
        grounding=False,
    )


def derive_meta(article_md: str, fallback_title: str) -> dict:
    title_match = re.search(r"^#\s+(.+)$", article_md, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else fallback_title

    tldr = re.search(r"\*\*TL;DR\*\*\s*\n((?:[-*]\s+.+\n?)+)", article_md)
    meta_desc = ""
    if tldr:
        bullets = re.findall(r"^[-*]+\s+(.+)$", tldr.group(1), re.MULTILINE)[:2]
        joined = " ".join(b.strip() for b in bullets)
        joined = re.sub(r"^[*\-\s]+", "", joined)
        meta_desc = joined[:158].rstrip(".") + "."
    if not meta_desc:
        paras = re.findall(r"^(?!#|\*|-)([^\n]{60,300})", article_md, re.MULTILINE)
        meta_desc = (paras[0][:158].rstrip(".") + ".") if paras else title

    words = re.findall(r"[a-zA-Z]{6,}", article_md.lower())
    stop = {"should", "section", "between", "before", "another", "however",
            "include", "amount", "person", "people", "simply", "actually"}
    common: dict[str, int] = {}
    for w in words:
        if w in stop:
            continue
        common[w] = common.get(w, 0) + 1
    keywords = [w for w, _ in sorted(common.items(),
                                     key=lambda x: x[1], reverse=True)[:8]]
    return {"title": title, "meta_description": meta_desc, "keywords": keywords}


def extract_faq(article_md: str) -> list[dict]:
    faq: list[dict] = []
    m = re.search(
        r"##\s*(?:FAQ|Frequently Asked Questions|F\.A\.Q\.?)\b[^\n]*\n([\s\S]+?)(?=\n##\s|\Z)",
        article_md, re.IGNORECASE,
    )
    if not m:
        return faq
    block = m.group(1)
    pairs = re.split(r"\n###\s+", "\n" + block)
    for p in pairs[1:]:
        lines = p.strip().split("\n", 1)
        if len(lines) < 2:
            continue
        q = lines[0].strip().rstrip("?") + "?"
        a = " ".join(lines[1].strip().split())
        if q and a:
            faq.append({"q": q, "a": a})
    return faq[:7]


def write_report(kind: str, ipo_data: dict, today: str) -> bool:
    spec = REPORTS[kind]
    rows = ipo_data.get(spec["data_key"]) or []
    if not rows:
        print(f"No data for '{kind}' report ({spec['data_key']} empty) — skipping",
              file=sys.stderr)
        return False

    # For the listing report, keep only the 30-60 day cohort; fall back to all
    # recent listings if none fall in the window so the report is never empty.
    if kind == "listing":
        cohort = [r for r in rows if r.get("in_window")] or rows
        rows = cohort

    month_year = dt.date.fromisoformat(today).strftime("%B %Y")
    data_block = json.dumps(rows, indent=2, default=str)
    prompt = spec["template"].format(today=today, month_year=month_year,
                                     data=data_block)

    body = call_llm(prompt, SYSTEM)
    if not body:
        print(f"LLM returned nothing for '{kind}' — skipping", file=sys.stderr)
        return False
    body = body.strip()
    body = re.sub(r"^```(?:markdown)?\s*\n", "", body)
    body = re.sub(r"\n```\s*$", "", body)

    category = spec["category"]
    meta = derive_meta(body, spec["fallback_title"])
    title_slug = slugify(meta["title"]) or category
    dated_slug = f"{today}-{title_slug}"
    filename = f"{dated_slug}.md"
    faq = extract_faq(body)
    canonical = f"{BASE_URL}/articles/{dated_slug}/"

    frontmatter = (
        "---\n"
        f"title: \"{meta['title'].replace(chr(34), chr(39))}\"\n"
        f"date: {today}\n"
        f"author: myfinancial\n"
        f"category: {category}\n"
        f"description: \"{meta['meta_description'].replace(chr(34), chr(39))}\"\n"
        f"keywords: [{', '.join(meta['keywords'])}]\n"
        f"canonical: {canonical}\n"
        f"slug: {dated_slug}\n"
        "---\n\n"
    )
    ARTS.mkdir(exist_ok=True)
    (ARTS / filename).write_text(frontmatter + body)
    print(f"Wrote {ARTS / filename}")

    meta_path = ARTICLES_DIR / f"{category}.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps({
        "date": today,
        "slug": dated_slug,
        "filename": filename,
        "category": category,
        "title": meta["title"],
        "description": meta["meta_description"],
        "keywords": meta["keywords"],
        "canonical": canonical,
        "faq": faq,
        "based_on": f"IPO {kind} report: {meta['title']}",
    }, indent=2, default=str))
    print(f"Wrote {meta_path}")
    return True


def main() -> int:
    if not IPO_JSON.exists():
        print(f"{IPO_JSON} missing — run ipo_data.py first", file=sys.stderr)
        return 1
    ipo_data = json.loads(IPO_JSON.read_text())
    today = dt.date.today().isoformat()

    which = (os.environ.get("IPO_REPORT") or "").strip().lower()
    kinds = [which] if which in REPORTS else list(REPORTS.keys())

    wrote_any = False
    for kind in kinds:
        wrote_any |= write_report(kind, ipo_data, today)
    return 0 if wrote_any else 1


if __name__ == "__main__":
    raise SystemExit(main())
