"""Generate an SEO + AEO optimised article via an LLM provider.

Providers (pick via LLM_PROVIDER env var, default = gemini):
  - gemini    → Google Gemini 2.5 Flash (free tier: 1,500 req/day, no card)
                Set GEMINI_API_KEY. Get one at https://aistudio.google.com/app/apikey
  - groq      → Groq Llama 3.3 70B (free tier: 30 RPM, no card)
                Set GROQ_API_KEY. Get one at https://console.groq.com/keys
  - anthropic → Claude Sonnet 4.6 (paid, ~₹30-50/mo)
                Set ANTHROPIC_API_KEY.

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
TOPIC = DATA / "today_topic.json"
META = DATA / "article.json"

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

SYSTEM = os.environ.get("ARTICLE_SYSTEM_PROMPT", _FALLBACK_SYSTEM)

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


def _call_gemini(prompt: str, system: str) -> Optional[str]:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY not set", file=sys.stderr)
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.6,
            "maxOutputTokens": 16000,
            "topP": 0.95,
        },
    }
    import time as _time
    delays = [10, 30, 60, 120]  # exponential-ish backoff for transient errors
    last_err = None
    for attempt in range(len(delays) + 1):
        try:
            r = requests.post(url, json=payload, timeout=120)
            if r.status_code in (429, 500, 502, 503, 504):
                if attempt < len(delays):
                    wait = delays[attempt]
                    print(f"Gemini {r.status_code} (transient) — retrying in {wait}s "
                          f"[{attempt+1}/{len(delays)}]", file=sys.stderr)
                    _time.sleep(wait)
                    continue
                print(f"Gemini failed after retries: HTTP {r.status_code}",
                      file=sys.stderr)
                print(r.text[:400], file=sys.stderr)
                return None
            r.raise_for_status()
            j = r.json()
            return j["candidates"][0]["content"]["parts"][0]["text"]
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < len(delays):
                wait = delays[attempt]
                print(f"Gemini network error — retrying in {wait}s "
                      f"[{attempt+1}/{len(delays)}]: {e}", file=sys.stderr)
                _time.sleep(wait)
                continue
            break
        except Exception as e:
            print(f"Gemini call failed (non-retryable): {e}", file=sys.stderr)
            return None
    print(f"Gemini failed after retries: {last_err}", file=sys.stderr)
    return None


def _call_groq(prompt: str, system: str) -> Optional[str]:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        print("GROQ_API_KEY not set", file=sys.stderr)
        return None
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 6000,
            },
            timeout=90,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Groq call failed: {e}", file=sys.stderr)
        return None


def _call_anthropic(prompt: str, system: str) -> Optional[str]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set", file=sys.stderr)
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        print("anthropic SDK not installed (pip install anthropic)", file=sys.stderr)
        return None
    client = Anthropic()
    msg = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        max_tokens=4500, system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def call_llm(prompt: str, system: str) -> Optional[str]:
    provider = os.environ.get("LLM_PROVIDER", "gemini").lower()
    print(f"Using LLM provider: {provider}")
    if provider == "gemini":
        return _call_gemini(prompt, system)
    if provider == "groq":
        return _call_groq(prompt, system)
    if provider == "anthropic":
        return _call_anthropic(prompt, system)
    print(f"Unknown LLM_PROVIDER: {provider}", file=sys.stderr)
    return None


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
    dated_slug = f"{today}-{title_slug}"
    filename = f"{dated_slug}.md"
    faq = extract_faq(body)

    canonical = f"https://myfinancialria.github.io/myfinancial-content/articles/{dated_slug}/"
    frontmatter = (
        "---\n"
        f"title: \"{meta['title'].replace(chr(34), chr(39))}\"\n"
        f"date: {today}\n"
        f"author: Nithin (CFP)\n"
        f"description: \"{meta['meta_description'].replace(chr(34), chr(39))}\"\n"
        f"keywords: [{', '.join(meta['keywords'])}]\n"
        f"canonical: {canonical}\n"
        f"slug: {dated_slug}\n"
        "---\n\n"
    )
    ARTS.mkdir(exist_ok=True)
    (ARTS / filename).write_text(frontmatter + body)
    print(f"Wrote {ARTS / filename}")

    META.write_text(json.dumps({
        "date": today,
        "slug": dated_slug,
        "filename": filename,
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
