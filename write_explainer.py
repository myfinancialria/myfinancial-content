"""Daily plain-English explainer — round-robin across 5 everyday themes.

Theme rotation (one per day, in order):
    economics → politics → business → people → market → (repeat)

Each run:
  1. Picks today's theme from a persisted rotation state (idempotent per day).
  2. Uses the configured LLM **with Google Search grounding ON** to choose ONE
     specific, currently-relevant concept/event/person in that theme and explain
     it from scratch, in very simple language, in a fixed structure.
  3. Writes articles/YYYY-MM-DD-explainer-<slug>.md (frontmatter, category=explainer)
     and data/articles/explainer.json — matching the conventions used by
     generate_image.py / fact_check.py / publish.py / slack_post.py.
  4. Records the concept in a rolling history so the next ~30 days don't repeat.

Guardrails baked into the prompt:
  - politics → neutral *political-economy* only (no party/leader opinions).
  - market  → explain CONCEPTS only. Never any buy/sell call, price target,
              forecast or "tip" (myfinancial is not a SEBI-registered advisor).
  - every fact must be grounded in current sources; define every term on first use.

Output is consumed unchanged by the rest of the pipeline via CATEGORY=explainer.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

HERE = Path(__file__).parent
DATA = HERE / "data"
ARTS = HERE / "articles"
ARTICLES_DIR = DATA / "articles"
ROTATION = DATA / "explainer_rotation.json"

CATEGORY = "explainer"
META = ARTICLES_DIR / f"{CATEGORY}.json"

BASE_URL = "https://myfinancialria.github.io/myfinancial-content"

# Round-robin order — exactly as requested. (Keys are internal slugs; the
# prompt shows a human label with underscores swapped for spaces.)
THEMES = ["economics", "politics", "business", "people", "market",
          "personal_finance"]

# How each theme should be interpreted for a personal-finance audience.
THEME_BRIEF: dict[str, str] = {
    "economics": (
        "everyday economics — an economic term, number, or event in the news "
        "(inflation, GDP, interest rates, jobs data, the rupee, trade, a global "
        "economic shift). Explain the concept, not a forecast."
    ),
    "politics": (
        "POLITICAL ECONOMY ONLY — a policy, law, government decision, budget "
        "move, or election outcome, explained strictly through its effect on "
        "the economy and ordinary people's money. Be scrupulously NEUTRAL: "
        "never praise or criticise any party, leader, or ideology; just explain "
        "what the policy is and what it changes."
    ),
    "business": (
        "everyday business — a company move, industry shift, deal, IPO, new "
        "business model, or sector story that ordinary people are hearing about. "
        "Explain how the business works and why it matters, in plain terms."
    ),
    "people": (
        "a person in the news in business, economics, finance, or policy (a "
        "CEO, central banker, regulator, investor, founder, or policymaker). "
        "Explain who they are, what they just did, and why it matters to "
        "ordinary people. Stay factual and neutral — no gossip, no judgement."
    ),
    "market": (
        "a stock-market / investing CONCEPT in the news (an index, a market "
        "term, how a mechanism works, what a piece of jargon means). "
        "STRICT RULE: explain the concept only. Do NOT recommend buying or "
        "selling anything, give price targets, predict levels, or offer 'tips'."
    ),
    "personal_finance": (
        "an everyday personal-finance topic an ordinary Indian is dealing with "
        "right now (tax, EPF/PPF/NPS, mutual funds & SIPs, insurance, home "
        "loans, credit score, UPI, savings, a new scheme, or an NRI money rule). "
        "Tie it to something current (a deadline, rule change, or season) and "
        "explain how it works and what to do — but NO specific product, fund, "
        "or stock recommendations; explain the concept and the choices, not a "
        "buy/sell call."
    ),
}

SYSTEM = """You write the daily 'Explained Simply' column for myfinancial.in — a trusted Indian personal-finance publication.

Your one job: take something ordinary Indians are hearing about in the news and explain it so clearly that a curious 15-year-old, a retiree, or a busy parent all understand it on the first read.

Voice & rules:
- Plain, warm, Indian English. Short sentences. No jargon — and when a technical word is unavoidable, define it the moment you use it, in brackets.
- Use the rupee symbol (₹) and lakhs/crores naturally. Use one concrete, everyday analogy to anchor the idea.
- Be accurate and current. Only state facts you can verify from live sources via search. Use the latest available figures and say roughly when they are from. If you are unsure of an exact number, describe it qualitatively rather than inventing one.
- Be strictly neutral on anything political: explain what a policy or decision DOES, never whether it is good/bad or which side is right.
- You are NOT a SEBI-registered investment adviser. Never give buy/sell calls, price targets, market predictions, or 'tips'. Explain how things work — that is all.
- Structured, skimmable, friendly. No filler, no hype, no clickbait.

Reply with ONLY the article in clean Markdown — no preamble, no commentary."""

USER_TEMPLATE = """Today is {today}. Today's theme is **{theme}**.

Interpret the theme as: {brief}

Step 1 — PICK: Using current information (prefer the last 7-10 days), choose ONE specific, real, genuinely-in-the-news {theme} topic that an ordinary Indian would actually have heard about this week. Pick something concrete (a named event, term, number, decision, company, or person) — not a vague evergreen topic.

Do NOT pick any of these recently-covered concepts:
{avoid}

Step 2 — EXPLAIN IT FROM SCRATCH in this EXACT structure:

# <a clear, curiosity-sparking plain-English title (no clickbait)>

**TL;DR**
- 4 to 5 one-line bullets a busy reader can scan in 15 seconds

## What's this about?
One or two short paragraphs: what happened / what the term means, in the simplest possible words.

## Why it's in the news right now
Tie it to the specific recent event or date that made it topical.

## How it actually works
Break the concept into simple, numbered steps or short paragraphs. Define every term.

## A simple way to think about it
One everyday analogy (a household, a kirana shop, a cricket match, etc.) that makes the idea click.

## Why it matters to you
Numbered list — concrete impact on an ordinary Indian's money, choices, or daily life.

## Common confusions cleared up
2 to 3 "Myth → Fact" style corrections.

## FAQ
4 to 5 short ### question headings, each with a 1-2 sentence answer.

## Sources
The real, current, authoritative URLs you actually relied on (official/regulator/reputable-news). Use canonical links only — never invent a URL.

Length: 900-1,300 words. Keep paragraphs short. Write the article now."""


def slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9\s-]", "", text.lower())
    text = re.sub(r"\s+", "-", text).strip("-")
    return text[:80]


def load_rotation() -> dict:
    if ROTATION.exists():
        try:
            return json.loads(ROTATION.read_text())
        except Exception:
            pass
    return {"last_date": None, "last_index": -1, "history": []}


def pick_theme(state: dict, today: str) -> tuple[str, int]:
    """Return (theme, index). Idempotent: re-running on the same day keeps the
    same theme. Falls back to a date-deterministic index if state is missing."""
    forced = (os.environ.get("EXPLAINER_THEME") or "").strip().lower()
    if forced in THEMES:
        return forced, THEMES.index(forced)

    last_date = state.get("last_date")
    last_index = state.get("last_index", -1)
    if last_date == today and 0 <= last_index < len(THEMES):
        # Already ran today — reuse the same theme (idempotent re-run).
        return THEMES[last_index], last_index

    if 0 <= last_index < len(THEMES):
        idx = (last_index + 1) % len(THEMES)
    else:
        # No usable state — derive a stable index from the date so the cycle
        # still advances predictably even if the state file is ever lost.
        idx = dt.date.fromisoformat(today).toordinal() % len(THEMES)
    return THEMES[idx], idx


def recent_concepts(state: dict, n: int = 30) -> list[str]:
    out = []
    for h in state.get("history", [])[-n:]:
        title = (h.get("title") or "").strip()
        if title:
            out.append(f"- [{h.get('theme')}] {title}")
    return out


from llm import call_llm as _shared_call_llm


def call_llm(prompt: str, system: str) -> Optional[str]:
    # Explainers want fresh, accurate facts → grounding ON, room for a long
    # article, moderate temperature for readable prose.
    return _shared_call_llm(
        prompt, system,
        temperature=0.55,
        max_tokens=16000,
        top_p=0.95,
        grounding=True,
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
    stop = {"income", "should", "section", "between", "before", "another",
            "however", "include", "amount", "person", "people", "simply",
            "actually"}
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


def main() -> int:
    today = dt.date.today().isoformat()
    state = load_rotation()
    theme, idx = pick_theme(state, today)
    theme_label = theme.replace("_", " ")
    brief = THEME_BRIEF[theme]
    avoid = "\n".join(recent_concepts(state)) or "(none yet)"

    print(f"Explainer theme for {today}: {theme} (index {idx})")

    prompt = USER_TEMPLATE.format(today=today, theme=theme_label, brief=brief,
                                  avoid=avoid)
    body = call_llm(prompt, SYSTEM)
    if not body:
        print("LLM returned nothing — aborting (rotation NOT advanced).",
              file=sys.stderr)
        return 1
    body = body.strip()
    # Strip stray code fences if the model wrapped the whole article.
    body = re.sub(r"^```(?:markdown)?\s*\n", "", body)
    body = re.sub(r"\n```\s*$", "", body)

    meta = derive_meta(body, f"{theme_label.title()} explained")
    title_slug = slugify(meta["title"]) or theme
    dated_slug = f"{today}-{CATEGORY}-{title_slug}"
    filename = f"{dated_slug}.md"
    faq = extract_faq(body)

    canonical = f"{BASE_URL}/articles/{dated_slug}/"
    frontmatter = (
        "---\n"
        f"title: \"{meta['title'].replace(chr(34), chr(39))}\"\n"
        f"date: {today}\n"
        f"author: myfinancial\n"
        f"category: {CATEGORY}\n"
        f"theme: {theme}\n"
        f"description: \"{meta['meta_description'].replace(chr(34), chr(39))}\"\n"
        f"keywords: [{', '.join(meta['keywords'])}]\n"
        f"canonical: {canonical}\n"
        f"slug: {dated_slug}\n"
        "---\n\n"
    )
    ARTS.mkdir(exist_ok=True)
    (ARTS / filename).write_text(frontmatter + body)
    print(f"Wrote {ARTS / filename}")

    META.parent.mkdir(parents=True, exist_ok=True)
    META.write_text(json.dumps({
        "date": today,
        "slug": dated_slug,
        "filename": filename,
        "category": CATEGORY,
        "theme": theme,
        "title": meta["title"],
        "description": meta["meta_description"],
        "keywords": meta["keywords"],
        "canonical": canonical,
        "faq": faq,
        # generate_image.py accepts a string here and uses it as the topic
        # summary for the hero-image prompt.
        "based_on": f"{theme} explainer: {meta['title']}",
    }, indent=2, default=str))
    print(f"Wrote {META}")

    # Advance rotation + record concept (only on success).
    state["last_date"] = today
    state["last_index"] = idx
    state.setdefault("history", []).append({
        "date": today, "theme": theme, "title": meta["title"], "slug": dated_slug,
    })
    state["history"] = state["history"][-90:]
    ROTATION.write_text(json.dumps(state, indent=2, default=str))
    print(f"Rotation advanced → next run will be "
          f"'{THEMES[(idx + 1) % len(THEMES)]}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
