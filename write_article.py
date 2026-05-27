"""Generate an SEO + AEO optimised article via an LLM provider.

Providers (pick via LLM_PROVIDER env var, default = gemini):
  - gemini    → Google Gemini 2.5 Flash (free tier: 1,500 req/day, no card)
                Set GEMINI_API_KEY. Get one at https://aistudio.google.com/app/apikey
                Google Search grounding is ON by default for fresh data;
                set GEMINI_GROUNDING=0 to disable.
  - groq      → Groq Llama 3.3 70B (free tier: 30 RPM, no card)
                Set GROQ_API_KEY. Get one at https://console.groq.com/keys
  - anthropic → Claude Sonnet 4.6 (paid, ~₹30-50/mo)
                Set ANTHROPIC_API_KEY.
  - openai    → OpenAI ChatGPT (paid). Default model gpt-4.1-mini (~₹300-400/mo
                for current pipeline). Set OPENAI_API_KEY, optional OPENAI_MODEL
                (e.g. gpt-4.1-mini, gpt-4.1, gpt-4o, gpt-5).

Input:   data/today_topic.json
Output:  articles/YYYY-MM-DD-<slug>.md + data/article.json
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

import requests

HERE = Path(__file__).parent
DATA = HERE / "data"
ARTS = HERE / "articles"
TOPICS_DIR = DATA / "topics"
ARTICLES_DIR = DATA / "articles"

# CATEGORY env var, if set, switches to per-category I/O paths
CATEGORY = (os.environ.get("CATEGORY") or "").strip().lower() or None
TOPIC = (TOPICS_DIR / f"{CATEGORY}.json") if CATEGORY \
    else (DATA / "today_topic.json")
META = (ARTICLES_DIR / f"{CATEGORY}.json") if CATEGORY \
    else (DATA / "article.json")


# Per-category prompt additions — appended to the base ARTICLE_SYSTEM_PROMPT
# so each category gets its own structure + length expectation. The base
# prompt remains the source of myfinancial's voice + guardrails.
CATEGORY_PROMPT_ADDITIONS: dict[str, str] = {
    "pre_market": (
        "\n\nThis article is a PRE-MARKET PREVIEW. Keep it concise (700–900 "
        "words). Structure: TL;DR (3 bullets) → What overnight moves matter "
        "→ Key events / data to watch today → Sectors / stocks in focus → "
        "What investors should do (numbered, 3 items) → FAQ (3–4 Qs). "
        "Lead with what changed since yesterday's close. Skip lengthy "
        "personas — keep the tone newsroom-brisk."
    ),
    "post_market": (
        "\n\nThis article is a POST-MARKET WRAP. Aim for 800–1,100 words. "
        "Structure: TL;DR (4 bullets) → Headline closing levels → What "
        "drove today's session → Sector winners / losers → FII/DII or "
        "flow note (if data is in the source) → What it means for tomorrow "
        "→ FAQ (3–4 Qs). Use today's date prominently."
    ),
    "result_analysis": (
        "\n\nThis article is a CORPORATE RESULT ANALYSIS. Aim for 1,300–"
        "1,700 words. Structure: TL;DR (5 bullets) → Headline numbers vs "
        "estimates → Segment / margin breakdown → Management commentary "
        "and guidance → Peer / industry context → What it means for "
        "investors (long-term + short-term) → FAQ (5 Qs). Use real numbers "
        "from the source — never invent figures."
    ),
    "macro": (
        "\n\nThis article EXPLAINS A MACRO EVENT (RBI/SEBI/Fed/inflation/"
        "GDP/policy). 1,100–1,500 words. Structure: TL;DR (4 bullets) → "
        "What happened (one-paragraph plain-English explainer) → Key "
        "numbers and how they compare to last reading / expectations → "
        "Market reaction → What it means for retail investors (numbered "
        "implications) → FAQ (4 Qs). Avoid jargon — define every acronym "
        "on first use."
    ),
    "personal_finance": "",  # keep the base prompt as-is — already personal-finance shaped
}

# Authoritative source links to encourage Claude to cite
AUTH_SOURCES = """
Authoritative sources to cite where relevant (use canonical URLs only):
- Income Tax India: https://incometax.gov.in
- CBDT notifications: https://incometaxindia.gov.in
- RBI: https://rbi.org.in
- SEBI: https://sebi.gov.in
- AMFI India: https://amfiindia.com
- EPFO: https://epfindia.gov.in
- NPS Trust: https://npstrust.org.in
- IRDAI: https://irdai.gov.in
- PFRDA: https://pfrda.org.in
- Ministry of Finance: https://finmin.nic.in
"""

# The full editorial system prompt (article voice + structure + constraints) is
# loaded from an env var so it can be set as a private GitHub Actions secret
# (`ARTICLE_SYSTEM_PROMPT`) without checking it into a public repo.
#
# Set it with:
#   gh secret set ARTICLE_SYSTEM_PROMPT -R <repo> < your-prompt.txt
#
# If the env var isn't set, we fall back to a minimal generic prompt so the
# script still runs for anyone cloning the repo for development.
_FALLBACK_SYSTEM = """You write India-focused personal-finance articles.

Audience: Indian salaried + self-employed earners and NRIs.
Voice: clear, jargon-free, Indian English, ₹ symbol, lakhs/crores naturally.

Structure each article with:
- # Title (single H1)
- **TL;DR** with 5 bullets
- ## What this means in plain terms
- 3-4 ## deep-dive H2 sections
- ## A real example (worked numbers with a named persona)
- ## What to do this week (3-5 numbered action items)
- ## FAQ (5-7 ### questions)
- ## Sources (official Indian government links)

Target 1,300-1,700 words. Reply with ONLY the article in Markdown."""

_BASE_SYSTEM = os.environ.get("ARTICLE_SYSTEM_PROMPT", _FALLBACK_SYSTEM)
SYSTEM = _BASE_SYSTEM + (CATEGORY_PROMPT_ADDITIONS.get(CATEGORY, "")
                          if CATEGORY else "")

USER_TEMPLATE = """Today's topic:

Primary headline: {primary_title}
Source: {primary_source}
Link: {primary_link}
Source summary: {primary_summary}

Related coverage from other personal-finance outlets:
{related_block}

{auth_sources}

Write the article now."""


def slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9\s-]", "", text.lower())
    text = re.sub(r"\s+", "-", text).strip("-")
    return text[:80]


from llm import call_llm as _shared_call_llm


def call_llm(prompt: str, system: str) -> Optional[str]:
    # Articles want long output, default temperature, grounding ON.
    return _shared_call_llm(
        prompt, system,
        temperature=0.6,
        max_tokens=16000,
        top_p=0.95,
    )


def derive_meta(article_md: str, fallback_title: str) -> dict:
    title_match = re.search(r"^#\s+(.+)$", article_md, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else fallback_title
    # TL;DR block becomes meta description seed
    tldr = re.search(
        r"\*\*TL;DR\*\*\s*\n((?:[-*]\s+.+\n?)+)",
        article_md,
    )
    meta_desc = ""
    if tldr:
        # First two bullets, content only, max ~155 chars
        bullets = re.findall(r"^[-*]+\s+(.+)$", tldr.group(1), re.MULTILINE)[:2]
        joined = " ".join(b.strip() for b in bullets)
        # Defensive: strip any stray leading bullet markers / asterisks
        joined = re.sub(r"^[*\-\s]+", "", joined)
        meta_desc = joined[:158].rstrip(".") + "."
    if not meta_desc:
        # Fall back to the first paragraph
        paras = re.findall(r"^(?!#|\*|-)([^\n]{60,300})", article_md, re.MULTILINE)
        meta_desc = (paras[0][:158].rstrip(".") + ".") if paras else title

    # Keywords: dumb but works — top distinct lower-case words >5 chars
    words = re.findall(r"[a-zA-Z]{6,}", article_md.lower())
    stop = {"income", "should", "section", "between", "before", "another",
            "however", "include", "amount", "person", "people"}
    common = {}
    for w in words:
        if w in stop:
            continue
        common[w] = common.get(w, 0) + 1
    keywords = [w for w, _ in sorted(common.items(),
                                      key=lambda x: x[1], reverse=True)[:8]]
    return {"title": title, "meta_description": meta_desc, "keywords": keywords}


def extract_faq(article_md: str) -> list[dict]:
    """Pull H3 Q/A pairs under the FAQ section for FAQPage schema."""
    faq = []
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
    if not TOPIC.exists():
        print("today_topic.json missing — run pick_topic.py first", file=sys.stderr)
        return 1
    topic = json.loads(TOPIC.read_text())
    primary = topic["primary"]
    related = topic.get("related", [])
    related_block = "\n".join(
        f"- [{r['source']}] {r['title']} ({r.get('link', '')})"
        for r in related[:6]
    ) or "(none)"
    prompt = USER_TEMPLATE.format(
        primary_title=primary["title"],
        primary_source=primary["source"],
        primary_link=primary.get("link", ""),
        primary_summary=primary.get("summary", ""),
        related_block=related_block,
        auth_sources=AUTH_SOURCES,
    )

    print(f"Generating article on: {primary['title'][:80]}")
    body = call_llm(prompt, SYSTEM)
    if not body:
        return 1

    today = dt.date.today().isoformat()
    meta = derive_meta(body, primary["title"])
    title_slug = slugify(meta["title"])
    # Prefix slug with category to avoid same-day filename collisions
    if CATEGORY:
        dated_slug = f"{today}-{CATEGORY}-{title_slug}"
    else:
        dated_slug = f"{today}-{title_slug}"
    filename = f"{dated_slug}.md"
    faq = extract_faq(body)

    canonical = f"https://myfinancialria.github.io/myfinancial-content/articles/{dated_slug}/"
    category_line = f"category: {CATEGORY}\n" if CATEGORY else ""
    frontmatter = (
        "---\n"
        f"title: \"{meta['title'].replace(chr(34), chr(39))}\"\n"
        f"date: {today}\n"
        f"author: myfinancial\n"
        f"{category_line}"
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
        "title": meta["title"],
        "description": meta["meta_description"],
        "keywords": meta["keywords"],
        "canonical": canonical,
        "faq": faq,
        "topic_score": topic.get("score"),
        "based_on": {
            "title": primary["title"],
            "source": primary["source"],
            "link": primary.get("link"),
        },
    }, indent=2, default=str))
    print(f"Wrote {META}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
