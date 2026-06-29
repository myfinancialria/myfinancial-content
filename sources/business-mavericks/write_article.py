"""Generate today's narrative business article via Gemini 2.5 Flash w/ Google Search grounding."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import requests

HERE = Path(__file__).parent
TODAY = HERE / "data" / "today.json"
ARTICLE_META = HERE / "data" / "article.json"
ARTS = HERE / "articles"

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

SYSTEM = """You are a long-form business storyteller writing for an Indian
finance + business audience. Your readers are curious, time-poor working
professionals — not MBAs, not analysts. They want to read a story about a
business or person that rose or fell, learn what actually happened, and
walk away with takeaways they can use.

Voice:
- Narrative, like a magazine feature. Open with a vivid scene, a specific
  year, a quote, or a moment. Never start with "In recent times..." or a
  generic preamble.
- Plain English. Avoid jargon. When using a business term (CAC, EBITDA,
  unit economics), explain it in one sentence.
- Show, don't tell. Use concrete numbers, dates, names, quotes.
- The reader should feel they're sitting across from someone who actually
  knows the story — not reading a Wikipedia summary.

Every claim must be defensible. Use Google Search grounding to find
sources and cite them. If you cannot find 3+ credible, accessible sources
for a specific claim — DROP THAT CLAIM rather than fabricate."""

PROMPT_TEMPLATE = """Write a long-form narrative article on this topic:

TITLE: {title}
CONTEXT: {context}
ANGLE: {angle} (focus on how this is a story of rise / fall)

Structure (900-1,300 words total — Slack-friendly length):

## Hook (~150 words)
Open on a specific scene. A year, a room, a quote, a moment of decision.
Pull the reader in.

## The world before
What did the market / industry / category look like? Why was the move
that follows considered impossible, foolish, or beneath consideration?

## The crack
The actual story. What did they do, how did they do it, and why did it
work (or fail)? Use specifics — numbers, quotes, dates. Walk the reader
through the key decisions in narrative form, not bullet points.

## What happened next
The aftermath. Numbers preferred — revenue, valuation, market share,
job cuts, share price. Be precise.

## Lessons to take away
3-5 takeaways — but written as observations, not platitudes. Each should
follow directly from the story above, not be generic business wisdom.

## References
A bulleted list of 3-5 URLs to the actual primary or secondary sources
you used. Format each as: - [Source name](URL) — one-line description.

CRITICAL RULES:
- Use the Google Search tool. Do not write from memory.
- If you cannot find at least 3 high-quality sources to cite, output
  ONLY the single line: INSUFFICIENT_SOURCES — and nothing else.
- Every claim with a specific number or quote must be traceable to one
  of the cited sources.
- Do NOT make up URLs. Only cite URLs that the search tool actually
  returned.
- Output is markdown only. No preamble, no postscript wrapper.
"""


def _load_today() -> dict:
    if not TODAY.exists():
        print(f"{TODAY} missing — run pick_story.py first", file=sys.stderr)
        sys.exit(1)
    return json.loads(TODAY.read_text())


def _call_gemini(prompt: str) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY missing", file=sys.stderr)
        sys.exit(1)
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={key}")
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.85, "maxOutputTokens": 8192},
    }
    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, timeout=180)
            if r.status_code in (429, 500, 502, 503, 504):
                import time; time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            data = r.json()
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except Exception as e:
            print(f"Gemini call failed (attempt {attempt+1}): {e}", file=sys.stderr)
            import time; time.sleep(5)
    print("Gemini call exhausted retries", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    today = _load_today()
    prompt = PROMPT_TEMPLATE.format(
        title=today["title"], context=today["context"], angle=today["angle"]
    )
    print(f"Generating: {today['title']}")
    body = _call_gemini(prompt)

    if body.strip().startswith("INSUFFICIENT_SOURCES"):
        print("Gemini reported insufficient sources — skipping today's post.",
              file=sys.stderr)
        return 2

    if "## References" not in body:
        print("Output missing ## References section — refusing to publish.",
              file=sys.stderr)
        return 2

    date = today["date"]
    full_slug = f"{date}-{today['slug']}"
    filename = f"{full_slug}.md"
    fp = ARTS / filename
    body_clean = re.sub(r"^#\s+.+\n+", "", body, count=1)

    frontmatter = (
        "---\n"
        f"title: \"{today['title']}\"\n"
        f"slug: {full_slug}\n"
        f"date: {date}\n"
        f"angle: {today['angle']}\n"
        "---\n\n"
    )
    fp.write_text(frontmatter + body_clean)
    print(f"Wrote {fp}")

    ARTICLE_META.write_text(json.dumps({
        "date": date,
        "slug": full_slug,
        "filename": filename,
        "title": today["title"],
        "angle": today["angle"],
    }, indent=2))
    print(f"Updated {ARTICLE_META}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
