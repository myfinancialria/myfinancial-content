"""Post today's article to Telegram in image-first brief format.

ONE message per run:
  • Hero image (uploaded from output/articles/<slug>/hero.jpg, falling back
    to meta['hero_url'] if the local file isn't present).
  • Caption — title in bold + one simple paragraph synopsis of the entire
    piece + a "Read the full article" link to the canonical URL.

Falls back to a plain text message if no hero is available.

Usage:
  SLOT=morning python telegram_post.py
  SLOT=midday  python telegram_post.py
  SLOT=evening python telegram_post.py
  CATEGORY=personal_finance python telegram_post.py    # multi-article mode

Required env:
  TELEGRAM_BOT_TOKEN   bot token from @BotFather
  TELEGRAM_CHAT_ID     @channel_username (public) or -100… (private group)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent

# Per-category meta when CATEGORY env is set (5-category pipeline);
# otherwise the legacy single-article path.
CATEGORY = (os.environ.get("CATEGORY") or "").strip().lower() or None
META = (HERE / "data" / "articles" / f"{CATEGORY}.json") if CATEGORY \
    else (HERE / "data" / "article.json")
ARTS = HERE / "articles"
OUTPUT = HERE / "output" / "articles"
BASE_URL = "https://myfinancialria.github.io/myfinancial-content"

CAPTION_LIMIT = 1024
SYNOPSIS_TARGET = 700        # leaves headroom for title + link

_LAST_SEND_AT: float = 0.0
_SEND_INTERVAL_SEC = 1.1


def _throttle() -> None:
    global _LAST_SEND_AT
    elapsed = time.monotonic() - _LAST_SEND_AT
    if elapsed < _SEND_INTERVAL_SEC:
        time.sleep(_SEND_INTERVAL_SEC - elapsed)


def _post(method: str, payload: dict, files: dict | None = None) -> dict:
    """POST to Telegram Bot API with throttle + 429 retry."""
    global _LAST_SEND_AT
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    url = f"https://api.telegram.org/bot{token}/{method}"
    _throttle()
    for _ in range(3):
        if files:
            r = requests.post(url, data=payload, files=files, timeout=60)
        else:
            r = requests.post(url, json=payload, timeout=30)
        _LAST_SEND_AT = time.monotonic()
        if r.status_code == 429:
            try:
                retry_after = r.json().get("parameters", {}).get("retry_after", 5)
            except Exception:
                retry_after = 5
            print(f"  ⏸ rate-limited, sleeping {retry_after}s", file=sys.stderr)
            time.sleep(retry_after + 1)
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return r.json()


def _escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _strip_markdown(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"\*(.+?)\*", r"\1", s)
    s = re.sub(r"`(.+?)`", r"\1", s)
    s = re.sub(r"\[(.+?)\]\([^)]+\)", r"\1", s)
    return s


def _word_set(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def _too_similar(a: str, b: str, threshold: float = 0.6) -> bool:
    """Jaccard overlap on word sets — used to skip TL;DR bullets that
    just restate the description we already used."""
    wa, wb = _word_set(a), _word_set(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= threshold


def load_meta() -> dict:
    if not META.exists():
        print(f"{META.name} missing — run write_article.py first", file=sys.stderr)
        sys.exit(1)
    return json.loads(META.read_text())


def load_body() -> str:
    meta = load_meta()
    fp = ARTS / meta["filename"]
    if not fp.exists():
        return ""
    text = fp.read_text()
    return re.sub(r"^---\n[\s\S]+?\n---\n+", "", text, count=1)


def extract_tldr(body: str) -> list[str]:
    m = re.search(r"\*\*TL;DR\*\*\s*\n((?:[-*]\s+.+\n?)+)", body)
    if not m:
        return []
    return [re.sub(r"^[-*]\s+", "", line).strip()
            for line in m.group(1).strip().splitlines() if line.strip()]


def build_synopsis(meta: dict, body: str) -> str:
    """One flowing paragraph that captures the whole article.

    Source priority:
      1. TL;DR bullets (clean, complete sentences written by the article generator).
      2. Article description (often auto-truncated from TL;DR — used only as
         a fallback when no TL;DR is present, with mid-word truncations stripped).
      3. First body paragraph as a last resort.
    """
    tldr = extract_tldr(body)
    sentences: list[str] = []

    if tldr:
        for b in tldr[:5]:
            b = _strip_markdown(b).strip()
            if not b:
                continue
            if any(_too_similar(b, prev) for prev in sentences):
                continue
            sentences.append(b.rstrip(".") + ".")
    else:
        desc = (meta.get("description") or "").strip()
        # Strip mid-word truncations like "Indian S." or "poten." — drop the
        # last clause if its trailing token is suspiciously short or lowercase.
        if desc:
            parts = re.split(r"(?<=[.!?])\s+", desc)
            if len(parts) >= 2:
                last_word = (parts[-1].rstrip(".!?").split() or [""])[-1]
                if (len(last_word) <= 6
                        and last_word == last_word.lower()
                        and last_word not in {
                            "today", "money", "stock", "rupee", "india",
                            "bonds", "funds", "taxes", "filing", "people",
                        }):
                    desc = " ".join(parts[:-1]).strip()
        if desc:
            sentences.append(desc.rstrip(".") + ".")

    if not sentences:
        # Last resort: first non-empty paragraph
        for para in body.split("\n\n"):
            p = _strip_markdown(para).strip()
            if p and not p.startswith("#") and not p.startswith(">"):
                sentences.append(p[:500])
                break

    paragraph = re.sub(r"\s+", " ", " ".join(sentences)).strip()

    if len(paragraph) > SYNOPSIS_TARGET:
        cut = paragraph.rfind(". ", 0, SYNOPSIS_TARGET)
        if cut == -1:
            cut = SYNOPSIS_TARGET
        paragraph = paragraph[:cut + 1].rstrip()
        if not paragraph.endswith("."):
            paragraph += "…"
    return paragraph


def build_caption(meta: dict, body: str) -> str:
    title = meta["title"]
    url = meta.get("canonical") or BASE_URL
    synopsis = build_synopsis(meta, body)

    slot = (os.environ.get("SLOT") or "").strip().lower()
    tag = {"morning": "🌅 Today's brief",
           "midday":  "📚 Midday deep-dive",
           "evening": "🌙 Evening wrap"}.get(slot)

    lines: list[str] = []
    if tag:
        lines.append(tag)
    lines.append(f"<b>{_escape(title)}</b>")
    lines.append("")
    lines.append(_escape(synopsis))
    lines.append("")
    lines.append(f'🔗 <a href="{url}">Read the full article on myfinancial.in</a>')

    caption = "\n".join(lines)
    if len(caption) <= CAPTION_LIMIT:
        return caption

    # Trim synopsis to fit
    overflow = len(caption) - CAPTION_LIMIT + 1
    lines[-3] = _escape(synopsis[:-overflow].rstrip().rstrip(".") + "…")
    return "\n".join(lines)


def post() -> int:
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        print("TELEGRAM_CHAT_ID not set", file=sys.stderr)
        return 1
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        print("TELEGRAM_BOT_TOKEN not set", file=sys.stderr)
        return 1

    meta = load_meta()
    body = load_body()
    caption = build_caption(meta, body)
    slot_label = (os.environ.get("SLOT") or "post").lower()

    hero_url = meta.get("hero_url")
    local_hero = OUTPUT / meta.get("slug", "") / "hero.jpg"

    if local_hero.exists():
        files = {"photo": (local_hero.name, local_hero.read_bytes(), "image/jpeg")}
        payload = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        result = _post("sendPhoto", payload, files=files)
    elif hero_url:
        payload = {"chat_id": chat_id, "photo": hero_url,
                   "caption": caption, "parse_mode": "HTML"}
        result = _post("sendPhoto", payload)
    else:
        print("⚠ no hero image — sending text-only", file=sys.stderr)
        payload = {"chat_id": chat_id, "text": caption, "parse_mode": "HTML",
                   "disable_web_page_preview": False}
        result = _post("sendMessage", payload)

    if result.get("ok"):
        print(f"✓ [{slot_label}] sent "
              f"(msg_id {result['result']['message_id']})")
        return 0
    print(f"✗ send failed: {result}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(post())
