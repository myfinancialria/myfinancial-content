"""Push top news items to Telegram in image-first brief format.

ONE Telegram message per news item:
  • Publisher's og:image (scraped from the article URL; falls back to a
    text-only message when the publisher hides it).
  • Caption — bold title + one-paragraph synopsis + "Read on <source>" link.

Reads:
  data/news.json — produced by fetch_news.py (uses the `top` list, falls
                   back to `items`).

Slack delivery is unchanged (slack_post.py keeps consuming the digest JSON).

Required env:
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
Optional:
  TELEGRAM_MAX_ARTICLES   default 6  (Telegram throttles ~1 msg/sec/chat)
  SLOT                    "morning" | "evening" — labels the heading message
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import requests

DATA = Path(__file__).parent / "data"
NEWS_JSON = DATA / "news.json"

UA = {"User-Agent": "Mozilla/5.0 (compatible; myfinancial-news/2.0)"}
CAPTION_LIMIT = 1024
SEND_INTERVAL_SEC = 1.2
DEFAULT_MAX = 6


def _escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _resolve_url(url: str) -> str:
    """Google News links 302-redirect to the publisher — follow once."""
    if not url:
        return url
    try:
        r = requests.head(url, headers=UA, allow_redirects=True, timeout=8)
        return r.url or url
    except Exception:
        return url


def _fetch_og_image(url: str) -> str | None:
    if not url:
        return None
    try:
        r = requests.get(url, headers=UA, timeout=10)
        if r.status_code != 200:
            return None
        html = r.text
        for pat in (
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        ):
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                return m.group(1).strip()
    except Exception:
        return None
    return None


def _build_synopsis(title: str, desc: str) -> str:
    desc = re.sub(r"\s+", " ", (desc or "").strip())
    title = re.sub(r"\s+", " ", (title or "").strip())
    if desc:
        if not desc.endswith((".", "!", "?")):
            desc = desc.rstrip(",;:") + "."
        return desc
    return title.rstrip(".") + "."


def _build_caption(title: str, synopsis: str, link: str, source: str) -> str:
    label = f"Read on {source}" if source else "Read the full article"
    lines = [
        f"<b>{_escape(title)}</b>",
        "",
        _escape(synopsis),
        "",
        f'🔗 <a href="{link}">{_escape(label)}</a>',
    ]
    caption = "\n".join(lines)
    if len(caption) <= CAPTION_LIMIT:
        return caption
    overflow = len(caption) - CAPTION_LIMIT + 1
    lines[2] = _escape(synopsis[:-overflow].rstrip().rstrip(".") + "…")
    return "\n".join(lines)


def _send_photo(token: str, chat_id: str, photo_url: str, caption: str) -> bool:
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data={"chat_id": chat_id, "photo": photo_url,
              "caption": caption, "parse_mode": "HTML"},
        timeout=30,
    )
    j = r.json()
    if not j.get("ok"):
        print(f"  ❌ sendPhoto: {j.get('description', j)}", file=sys.stderr)
        return False
    return True


def _send_text(token: str, chat_id: str, text: str) -> bool:
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": False},
        timeout=30,
    )
    j = r.json()
    if not j.get("ok"):
        print(f"  ❌ sendMessage: {j.get('description', j)}", file=sys.stderr)
        return False
    return True


def _load_news() -> list[dict]:
    if not NEWS_JSON.exists():
        return []
    try:
        data = json.loads(NEWS_JSON.read_text())
    except Exception as e:
        print(f"news.json parse failed: {e}", file=sys.stderr)
        return []
    return data.get("top") or data.get("items") or []


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping",
              file=sys.stderr)
        return 0

    items = _load_news()
    if not items:
        print("No news items found in data/news.json")
        return 0

    max_n = int(os.environ.get("TELEGRAM_MAX_ARTICLES", DEFAULT_MAX))
    slot = (os.environ.get("SLOT") or "").strip().lower()
    label = {"morning": "🌅 Morning brief",
             "evening": "🌇 Evening wrap"}.get(slot, "📰 News brief")

    # Heading message so subscribers know a new batch is starting
    _send_text(token, chat_id, f"<b>{label}</b> — top stories")
    time.sleep(SEND_INTERVAL_SEC)

    sent, skipped = 0, 0
    for item in items[:max_n]:
        title = item.get("title", "")
        desc = item.get("description") or item.get("desc") or ""
        source = item.get("source", "")
        link = _resolve_url(item.get("link", ""))

        synopsis = _build_synopsis(title, desc)
        caption = _build_caption(title, synopsis, link, source)
        og_image = _fetch_og_image(link)

        ok = (_send_photo(token, chat_id, og_image, caption) if og_image
              else _send_text(token, chat_id, caption))
        if ok:
            sent += 1
            print(f"  ✓ {title[:80]}")
        else:
            skipped += 1
        time.sleep(SEND_INTERVAL_SEC)

    print(f"Telegram: {sent} posted, {skipped} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
