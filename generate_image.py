"""Generate a hero image for today's article.

Pipeline:
  1. Read data/article.json (title + based_on summary).
  2. Ask the LLM to compose a short, editorial-style image prompt.
  3. Fetch the image from Pollinations.ai (free, no key, FLUX model).
  4. Save it to output/articles/<slug>/hero.jpg.
  5. Update data/article.json with hero_url + image_prompt.

Why Pollinations: free, no API key, generous limits, FLUX model output is
magazine-quality. Falls back to a placeholder if generation fails.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path
from typing import Optional

import requests

HERE = Path(__file__).parent

# Per-category meta when CATEGORY env is set (5-category pipeline);
# otherwise the legacy single-article path.
CATEGORY = (os.environ.get("CATEGORY") or "").strip().lower() or None
META = (HERE / "data" / "articles" / f"{CATEGORY}.json") if CATEGORY \
    else (HERE / "data" / "article.json")
OUT_ARTICLES = HERE / "output" / "articles"

PROMPT_SYSTEM = (
    "You design editorial illustrations for an Indian personal-finance "
    "publication called myfinancial.in. The audience is mass-affluent "
    "(₹15L+/year earners) and NRIs. Your only job is to write ONE image "
    "prompt that a text-to-image model can render."
)

PROMPT_TEMPLATE = """Article details:
- Title: {title}
- Topic summary: {topic_summary}
- Source headline: {source_headline}

Write ONE image prompt (28-45 words) following ALL rules:
- Editorial-magazine illustration style (NOT photo-realistic, NOT cartoon, NOT 3D render). Think The Economist or The Ken cover art.
- One central visual metaphor for the topic. Specific, evocative, not generic.
- India context where natural (rupee symbol, an Indian setting, Indian people if needed) but no clichés.
- Color palette: navy blue, off-white, muted gold accents.
- Composition: 16:9 horizontal, clean negative space on one side.
- NO text, NO numbers, NO logos, NO watermarks anywhere in the image.
- Soft lighting, sharp focus, high contrast.

Output JUST the prompt as a single paragraph. No preamble, no labels, no quotes."""

POLLINATIONS = "https://image.pollinations.ai/prompt/{prompt}"
WIDTH, HEIGHT = 1200, 675   # 16:9, good for Open Graph + Slack


def write_prompt(title: str, topic_summary: str, source_headline: str) -> Optional[str]:
    """Use the configured LLM to compose the image prompt."""
    user = PROMPT_TEMPLATE.format(
        title=title,
        topic_summary=topic_summary[:400] or "(none)",
        source_headline=source_headline or "(none)",
    )
    provider = os.environ.get("LLM_PROVIDER", "gemini").lower()
    if provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            print("GEMINI_API_KEY missing — cannot compose prompt", file=sys.stderr)
            return None
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={key}")
        payload = {
            "system_instruction": {"parts": [{"text": PROMPT_SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.9,
                "maxOutputTokens": 2048,
                # Gemini 2.5 reasons before emitting; setting budget=0
                # forces it to skip thinking and write the prompt directly.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        try:
            r = requests.post(url, json=payload, timeout=60)
            r.raise_for_status()
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return txt.strip().strip('"').strip("'")
        except Exception as e:
            print(f"Prompt compose failed: {e}", file=sys.stderr)
            return None
    # Other providers can be added if you switch
    return None


def fetch_image(prompt: str, out_path: Path) -> bool:
    encoded = urllib.parse.quote(prompt, safe="")
    url = (f"{POLLINATIONS.format(prompt=encoded)}"
           f"?width={WIDTH}&height={HEIGHT}&nologo=true&model=flux&enhance=true")
    try:
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        if len(r.content) < 5000:
            print(f"Image response suspiciously small ({len(r.content)} bytes)",
                  file=sys.stderr)
            return False
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(r.content)
        print(f"Wrote {out_path} ({len(r.content) // 1024} KB)")
        return True
    except Exception as e:
        print(f"Image fetch failed: {e}", file=sys.stderr)
        return False


def main() -> int:
    if not META.exists():
        print(f"{META.name} missing — run write_article.py first", file=sys.stderr)
        return 1
    meta = json.loads(META.read_text())
    slug = meta["slug"]
    title = meta["title"]
    based_on = meta.get("based_on", {})
    topic_summary = based_on.get("summary", "") or meta.get("description", "")
    source_headline = based_on.get("title", "")

    print(f"Composing image prompt for: {title[:80]}")
    prompt = write_prompt(title, topic_summary, source_headline)
    if not prompt:
        return 1
    print(f"Prompt: {prompt}\n")

    out_path = OUT_ARTICLES / slug / "hero.jpg"
    ok = fetch_image(prompt, out_path)
    if not ok:
        return 1

    meta["image_prompt"] = prompt
    meta["hero_url"] = f"{meta['canonical'].rstrip('/')}/hero.jpg"
    meta["hero_local"] = f"articles/{slug}/hero.jpg"
    META.write_text(json.dumps(meta, indent=2, default=str))
    print(f"Updated {META}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
