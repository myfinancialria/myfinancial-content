"""Generate a hero image via Pollinations.ai (free, no key) — also stashes
the publicly addressable Pollinations URL so Slack can use it directly."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

import requests

HERE = Path(__file__).parent
META = HERE / "data" / "article.json"
ARTS = HERE / "articles"
OUTPUT = HERE / "output"

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

POLLINATIONS = "https://image.pollinations.ai/prompt/{prompt}"
WIDTH, HEIGHT = 1200, 675

PROMPT_SYSTEM = (
    "You design editorial illustrations for a long-form business "
    "storytelling publication. Each image accompanies a feature on the "
    "rise or fall of a business or person. Your only job is to write ONE "
    "image prompt that a text-to-image model can render."
)

PROMPT_TEMPLATE = """Article title: {title}
Article opening: {opening}

Write ONE image prompt (28-45 words) following ALL rules:
- Editorial-magazine illustration style, like The Economist or Bloomberg
  Businessweek covers. NOT photo-realistic, NOT cartoon, NOT 3D render.
- One central visual metaphor for the story's core tension or moment.
- Mood matches the angle (rise = ascending/golden; fall = falling/muted).
- Palette: muted navy, off-white, with one accent (gold for rise, red/grey for fall).
- 16:9 horizontal composition, clean negative space on one side.
- NO text, NO numbers, NO logos, NO faces of real people, NO watermarks.
- Soft lighting, sharp focus, high contrast.

Output JUST the prompt as a single paragraph. No preamble, no quotes."""


def _load_meta() -> dict:
    return json.loads(META.read_text())


def _load_body(meta: dict) -> str:
    text = (ARTS / meta["filename"]).read_text()
    return re.sub(r"^---\n[\s\S]+?\n---\n+", "", text, count=1)


def _compose_prompt(title: str, opening: str) -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY missing", file=sys.stderr); return None
    user = PROMPT_TEMPLATE.format(title=title, opening=opening[:400] or "(none)")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={key}")
    payload = {
        "system_instruction": {"parts": [{"text": PROMPT_SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": 0.9, "maxOutputTokens": 2048,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    try:
        r = requests.post(url, json=payload, timeout=60); r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip().strip('"\'')
    except Exception as e:
        print(f"Prompt compose failed: {e}", file=sys.stderr); return None


def _fetch_image(prompt: str, out_path: Path) -> tuple[bool, str]:
    """Returns (success, public_url). Slack can use the public_url directly."""
    encoded = urllib.parse.quote(prompt, safe="")
    public_url = (f"{POLLINATIONS.format(prompt=encoded)}"
                  f"?width={WIDTH}&height={HEIGHT}&nologo=true&model=flux&enhance=true")
    try:
        r = requests.get(public_url, timeout=180); r.raise_for_status()
        if len(r.content) < 5000:
            print(f"Image suspiciously small ({len(r.content)} bytes)", file=sys.stderr)
            return False, public_url
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(r.content)
        print(f"Wrote {out_path} ({len(r.content) // 1024} KB)")
        return True, public_url
    except Exception as e:
        print(f"Image fetch failed: {e}", file=sys.stderr); return False, public_url


def main() -> int:
    meta = _load_meta()
    body = _load_body(meta)
    opening = " ".join(body.split())[:400]

    print(f"Composing image prompt for: {meta['title'][:80]}")
    prompt = _compose_prompt(meta["title"], opening)
    if not prompt:
        return 1
    print(f"Prompt: {prompt}\n")

    out_path = OUTPUT / meta["slug"] / "hero.jpg"
    ok, public_url = _fetch_image(prompt, out_path)

    meta["image_prompt"] = prompt
    meta["hero_local"] = str(out_path.relative_to(HERE))
    meta["hero_url"] = public_url   # Slack uses this directly via blocks
    META.write_text(json.dumps(meta, indent=2))
    print(f"Updated {META}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
