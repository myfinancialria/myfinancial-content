"""Post today's article to Telegram (image + body) with slot-based framing.

Mirror of slack_post.py — same SLOT env var, same three framings, same
article source. Difference: Telegram delivery is image-first (hero.jpg
sent as a photo with short caption), followed by the body as a text
message.

Usage:
  SLOT=morning python telegram_post.py
  SLOT=midday  python telegram_post.py
  SLOT=evening python telegram_post.py

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

# If CATEGORY env var is set, read per-category meta (multi-article mode);
# otherwise fall back to single-article path (legacy).
import os as _os
CATEGORY = (_os.environ.get("CATEGORY") or "").strip().lower() or None
META = (HERE / "data" / "articles" / f"{CATEGORY}.json") if CATEGORY \
    else (HERE / "data" / "article.json")
ARTS = HERE / "articles"
OUTPUT = HERE / "output" / "articles"
BASE_URL = "https://myfinancialria.github.io/myfinancial-content"

# Telegram limits
CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096

# Throttle to respect ~1 msg/sec to one chat
_LAST_SEND_AT: float = 0.0
_SEND_INTERVAL_SEC = 1.1


def _throttle() -> None:
    global _LAST_SEND_AT
    elapsed = time.monotonic() - _LAST_SEND_AT
    if elapsed < _SEND_INTERVAL_SEC:
        time.sleep(_SEND_INTERVAL_SEC - elapsed)


def _post(method: str, payload: dict, files: dict | None = None) -> dict:
    """POST to Telegram Bot API. Auto-retries on 429."""
    global _LAST_SEND_AT
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    url = f"https://api.telegram.org/bot{token}/{method}"
    _throttle()
    for attempt in range(3):
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


# ─── Markdown → Telegram HTML ─────────────────────────────────────────────

def _md_to_html(text: str) -> str:
    """Convert article markdown to Telegram-supported HTML.

    Telegram supports: <b>, <i>, <u>, <s>, <code>, <pre>, <a href>.
    We strip ## headers, convert **bold**/*italic*/`code`, leave bullets
    as plain text.
    """
    # Escape HTML special chars first
    out = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Headers — convert ## to bold + line break (Telegram doesn't render markdown headers)
    out = re.sub(r"^#{1,3}\s+(.+)$", r"<b>\1</b>", out, flags=re.MULTILINE)

    # **bold** → <b>
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)
    # *italic* (single asterisk) → <i>  — but careful, can clash with bullets
    out = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", out)
    # `code` → <code>
    out = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", out)

    # [text](url) → <a href="url">text</a>
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', out)

    # Bullet markers: '- ' → '• ' for nicer Telegram display
    out = re.sub(r"^[\*\-]\s+", "• ", out, flags=re.MULTILINE)

    return out


# ─── Article loading + framing (mirrors slack_post.py) ────────────────────

def load_meta() -> dict:
    if not META.exists():
        print("article.json missing — run write_article.py first", file=sys.stderr)
        sys.exit(1)
    return json.loads(META.read_text())


def load_body() -> str:
    meta = load_meta()
    fp = ARTS / meta["filename"]
    if not fp.exists():
        print(f"{fp} missing", file=sys.stderr)
        sys.exit(1)
    text = fp.read_text()
    # strip frontmatter
    return re.sub(r"^---\n[\s\S]+?\n---\n+", "", text, count=1)


def extract_tldr(body: str) -> list[str]:
    m = re.search(r"\*\*TL;DR\*\*\s*\n((?:[-*]\s+.+\n?)+)", body)
    if not m:
        return []
    return [re.sub(r"^[-*]\s+", "", line).strip()
            for line in m.group(1).strip().splitlines() if line.strip()]


def extract_first_section(body: str, header: str) -> str:
    pat = rf"##\s+[^\n]*{re.escape(header)}[^\n]*\n([\s\S]+?)(?=\n##\s|\Z)"
    m = re.search(pat, body, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def extract_action_items(body: str) -> list[str]:
    section = extract_first_section(body, "What to do this week")
    if not section:
        section = extract_first_section(body, "Action")
    return re.findall(r"^(?:\d+\.|[-*])\s+(.+)$", section, re.MULTILINE)[:5]


def extract_faq(body: str, meta: dict | None = None) -> list[tuple[str, str]]:
    """First try the frontmatter `faq` list, then the body's ## FAQ section."""
    if meta and meta.get("faq"):
        return [(item["q"], item["a"]) for item in meta["faq"][:3]]
    section = extract_first_section(body, "FAQ")
    if not section:
        return []
    pairs = []
    for p in re.split(r"\n###\s+", "\n" + section)[1:]:
        lines = p.strip().split("\n", 1)
        if len(lines) < 2:
            continue
        q = lines[0].strip().rstrip("?") + "?"
        a = " ".join(lines[1].strip().split())
        pairs.append((q, a))
    return pairs[:3]


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    cut = s[:limit - 1].rsplit(" ", 1)[0]
    return cut + "…"


def _truncate_clean(body: str, limit: int) -> str:
    """Truncate at a paragraph or sentence boundary so the cut feels natural."""
    if len(body) <= limit:
        return body
    snippet = body[:limit]
    # Prefer paragraph break, then sentence end, then space
    for marker in ("\n\n", ". ", "\n", " "):
        idx = snippet.rfind(marker)
        if idx > limit * 0.6:
            return snippet[:idx].rstrip()
    return snippet.rstrip() + "…"


def build_post(slot: str, meta: dict, body: str) -> tuple[str, str]:
    """Return (image_caption, body_text). Both already HTML-escaped + formatted."""
    title = meta["title"]
    url = meta.get("canonical") or BASE_URL
    tldr = extract_tldr(body)

    # ─── Caption (under image): ~600-800 chars to stay under 1024 limit ───
    if slot == "morning":
        framing_emoji = "🌅"
        framing_label = "Morning brief"
        bullets = "\n".join(f"• {b}" for b in tldr[:3]) if tldr else meta.get("description", "")
        teaser = f"{bullets}"
    elif slot == "midday":
        framing_emoji = "📚"
        framing_label = "Midday deep-dive"
        example = (extract_first_section(body, "real example")
                   or extract_first_section(body, "plain terms")
                   or extract_first_section(body, "Understanding")
                   or " ".join(body.split()[:80]))
        teaser = _truncate(" ".join(example.split()), 600)
    else:  # evening
        framing_emoji = "🌙"
        framing_label = "Evening wrap"
        actions = extract_action_items(body)
        teaser_lines = []
        if actions:
            teaser_lines.append("<b>What to do this week:</b>")
            teaser_lines.extend(f"• {a}" for a in actions[:4])
        else:
            teaser_lines.append("Wrap of today's piece — full breakdown linked below.")
        teaser = "\n".join(teaser_lines)

    # ─── Caption (under image): ~1000 chars under 1024 limit ───
    # Put the read-more link FIRST inside the teaser so it's always visible
    read_more = f'<a href="{url}"><b>📖 Read the full article →</b></a>'
    caption_parts = [
        f"{framing_emoji} <b>{framing_label}</b>",
        f"<b>{_md_to_html(title)}</b>",
        "",
        _truncate_clean(_md_to_html(teaser),
                          CAPTION_LIMIT - len(read_more) - 200),
        "",
        read_more,
    ]
    caption = "\n".join(caption_parts)
    if len(caption) > CAPTION_LIMIT:
        # Hard fallback — strip teaser to fit
        caption = "\n".join([
            f"{framing_emoji} <b>{framing_label}</b>",
            f"<b>{_md_to_html(title)}</b>",
            "",
            read_more,
        ])

    # ─── Body message — link at top, truncated body, link at bottom ───
    # Strip TL;DR (already shown in caption for morning slot) — keep rest
    body_clean = re.sub(r"\*\*TL;DR\*\*\s*\n(?:[-*]\s+.+\n?)+\n*",
                        "", body)
    body_clean_html = _md_to_html(body_clean)

    # Reserve space for: title + 2 links + footer + line breaks
    title_html = f"<b>{_md_to_html(title)}</b>"
    top_link = f'<a href="{url}">📖 Read full article →</a>'
    bottom_link = (f'<a href="{url}">'
                   f'<b>Continue reading on myfinancial.in →</b></a>')
    footer = "<i>For Indians who'd rather understand than be sold to.</i>"

    fixed_chars = (len(title_html) + len(top_link) + len(bottom_link)
                   + len(footer) + 80)  # 80 for separators
    body_budget = MESSAGE_LIMIT - fixed_chars - 100  # safety margin
    body_trimmed = _truncate_clean(body_clean_html, body_budget)
    truncated = len(body_clean_html) > len(body_trimmed)

    body_msg = "\n".join([
        title_html,
        top_link,
        "",
        body_trimmed,
        "",
        "—" + (" (truncated — link below for full piece)" if truncated else ""),
        footer,
        bottom_link,
    ])
    return caption, body_msg


# ─── Telegram delivery ────────────────────────────────────────────────────

def post(slot: str) -> int:
    meta = load_meta()
    body = load_body()
    caption, body_msg = build_post(slot, meta, body)

    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        print("TELEGRAM_CHAT_ID not set", file=sys.stderr)
        return 1

    # ─── 1. Send hero image with caption ──────────────────────────────────
    hero_url = meta.get("hero_url")
    # Fall back to local hero.jpg if hero_url is missing
    local_hero = OUTPUT / meta["slug"] / "hero.jpg"

    photo_payload: dict | None = None
    photo_files: dict | None = None

    if hero_url:
        photo_payload = {
            "chat_id": chat_id,
            "photo": hero_url,           # Telegram fetches the URL
            "caption": caption,
            "parse_mode": "HTML",
        }
    elif local_hero.exists():
        photo_payload = {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "HTML",
        }
        photo_files = {"photo": (local_hero.name, local_hero.read_bytes(), "image/jpeg")}
    else:
        print(f"⚠ no hero image (hero_url unset + {local_hero} missing) — sending text-only",
              file=sys.stderr)

    if photo_payload:
        result = _post("sendPhoto", photo_payload, files=photo_files)
        if result.get("ok"):
            print(f"✓ [{slot}] photo sent (msg_id {result['result']['message_id']})")
        else:
            print(f"✗ photo failed: {result}", file=sys.stderr)
            return 1

    # ─── 2. Send body as a follow-up text message ─────────────────────────
    result = _post("sendMessage", {
        "chat_id": chat_id,
        "text": body_msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })
    if result.get("ok"):
        print(f"✓ [{slot}] body sent (msg_id {result['result']['message_id']})")
        return 0
    print(f"✗ body failed: {result}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    slot = os.environ.get("SLOT", "morning").lower()
    if slot not in ("morning", "midday", "evening"):
        print(f"SLOT must be morning|midday|evening (got {slot!r})", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(post(slot))
