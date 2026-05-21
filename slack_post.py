"""Post today's article to Slack with one of three framings.

Usage:
  SLOT=morning python slack_post.py
  SLOT=midday  python slack_post.py
  SLOT=evening python slack_post.py

Required env:
  SLACK_BOT_TOKEN, SLACK_CONTENT_CHANNEL  (preferred — adds rich blocks)
    OR
  SLACK_CONTENT_WEBHOOK_URL  (fallback — text-only)
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import requests

HERE = Path(__file__).parent

import os as _os
CATEGORY = (_os.environ.get("CATEGORY") or "").strip().lower() or None
META = (HERE / "data" / "articles" / f"{CATEGORY}.json") if CATEGORY \
    else (HERE / "data" / "article.json")
ARTS = HERE / "articles"
BASE_URL = "https://myfinancialria.github.io/myfinancial-content"


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
    """Returns the body of the first H2 matching header (substring match)."""
    pat = rf"##\s+[^\n]*{re.escape(header)}[^\n]*\n([\s\S]+?)(?=\n##\s|\Z)"
    m = re.search(pat, body, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def extract_action_items(body: str) -> list[str]:
    section = extract_first_section(body, "What to do this week")
    if not section:
        section = extract_first_section(body, "Action")
    items = re.findall(r"^(?:\d+\.|[-*])\s+(.+)$", section, re.MULTILINE)
    return items[:5]


def extract_faq(body: str) -> list[tuple[str, str]]:
    section = extract_first_section(body, "FAQ")
    if not section:
        return []
    pairs = []
    parts = re.split(r"\n###\s+", "\n" + section)
    for p in parts[1:]:
        lines = p.strip().split("\n", 1)
        if len(lines) < 2:
            continue
        q = lines[0].strip().rstrip("?") + "?"
        a = " ".join(lines[1].strip().split())
        pairs.append((q, a))
    return pairs[:3]


def build_blocks(slot: str, meta: dict, body: str) -> tuple[str, list[dict]]:
    url = meta.get("canonical") or BASE_URL
    title = meta["title"]
    tldr = extract_tldr(body)

    if slot == "morning":
        header = "Today's brief"
        text = f":sunrise: *{header}* — {title}"
        teaser = "\n".join(f"• {b}" for b in tldr[:3]) if tldr else meta.get("description", "")
        intro = f"Good morning. Today's piece covers *{title}*.\n\n{teaser}"
    elif slot == "midday":
        header = "Midday deep-dive"
        text = f":books: *{header}* — {title}"
        # Pull a meaty middle section to share
        examples = extract_first_section(body, "real example")
        snippet = (examples or extract_first_section(body, "plain terms")
                   or "Read the full piece for the breakdown.")
        snippet = " ".join(snippet.split())[:550]
        intro = f"Lunch read: a worked example from today's piece.\n\n>{snippet}"
    elif slot == "evening":
        header = "Evening wrap"
        text = f":crescent_moon: *{header}* — {title}"
        actions = extract_action_items(body)
        faqs = extract_faq(body)
        parts = ["Wrapping the day. Here's what to actually do:"]
        if actions:
            parts.append("\n*Action items*")
            parts.extend(f"• {a}" for a in actions)
        if faqs:
            parts.append("\n*Quick FAQ*")
            for q, a in faqs[:2]:
                parts.append(f"• *{q}* {a[:200]}")
        intro = "\n".join(parts)
    else:
        raise ValueError(f"Unknown slot: {slot}")

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": header}},
    ]
    hero = meta.get("hero_url")
    if hero:
        blocks.append({"type": "image", "image_url": hero, "alt_text": title})
    blocks.extend([
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": intro}},
        {"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text",
                                         "text": "Read the full article"},
             "url": url, "style": "primary"},
        ]},
        {"type": "context", "elements": [
            {"type": "mrkdwn",
             "text": f"*MyFinancial* — for Indians who'd rather understand than be sold to · myfinancial.in · {meta.get('date', '')}"}
        ]},
    ])
    return text, blocks


def post(slot: str) -> int:
    meta = load_meta()
    body = load_body()
    text, blocks = build_blocks(slot, meta, body)

    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CONTENT_CHANNEL")
    webhook = os.environ.get("SLACK_CONTENT_WEBHOOK_URL")

    if token and channel:
        r = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            data=json.dumps({"channel": channel, "text": text, "blocks": blocks,
                             "unfurl_links": False, "unfurl_media": False}),
            timeout=15,
        )
        j = r.json()
        if not j.get("ok"):
            print(f"Slack postMessage failed: {j}", file=sys.stderr)
            return 1
        print(f"Posted [{slot}] to {channel}")
        return 0

    if webhook:
        r = requests.post(webhook, json={"text": text, "blocks": blocks}, timeout=15)
        r.raise_for_status()
        print(f"Posted [{slot}] via webhook")
        return 0

    print("Set SLACK_BOT_TOKEN+SLACK_CONTENT_CHANNEL or SLACK_CONTENT_WEBHOOK_URL",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    slot = os.environ.get("SLOT", "morning").lower()
    if slot not in ("morning", "midday", "evening"):
        print(f"SLOT must be morning|midday|evening (got {slot!r})", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(post(slot))
