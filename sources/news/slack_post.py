"""Post the morning or evening digest to Slack.

Env:
  SLOT                       = "morning" | "evening" (default: morning)
  SLACK_BOT_TOKEN            (preferred — chat.postMessage)
  SLACK_NEWS_CHANNEL         (channel ID or #name)
  SLACK_NEWS_WEBHOOK_URL     (fallback — incoming webhook)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

DATA = Path(__file__).parent / "data"

SLOT_FILES = {
    "morning": DATA / "digest_morning.json",
    "evening": DATA / "digest_evening.json",
}


def _to_slack_blocks(digest: dict) -> list[dict]:
    out = []
    for b in digest["blocks"]:
        if b["type"] == "header":
            out.append({"type": "header",
                        "text": {"type": "plain_text", "text": b["text"][:150]}})
        elif b["type"] == "section":
            title = b.get("title", "")
            body = b.get("text", "")
            text = f"*{title}*\n{body}" if title else body
            # Slack section text caps at 3000 chars
            out.append({"type": "section",
                        "text": {"type": "mrkdwn", "text": text[:2900]}})
            out.append({"type": "divider"})
    out.append({"type": "context",
                "elements": [{"type": "mrkdwn",
                              "text": "*myfinancial* — Markets digest"}]})
    return out


def post_chat(token: str, channel: str, blocks: list[dict], text: str) -> bool:
    r = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=utf-8"},
        json={"channel": channel, "text": text, "blocks": blocks},
        timeout=20,
    )
    ok = r.ok and r.json().get("ok")
    if not ok:
        print(f"Slack chat.postMessage failed: {r.status_code} {r.text[:200]}",
              file=sys.stderr)
    return bool(ok)


def post_webhook(url: str, blocks: list[dict], text: str) -> bool:
    r = requests.post(url, json={"text": text, "blocks": blocks}, timeout=20)
    if not r.ok:
        print(f"Slack webhook failed: {r.status_code} {r.text[:200]}",
              file=sys.stderr)
    return r.ok


def main() -> int:
    slot = os.environ.get("SLOT", "morning").lower()
    path = SLOT_FILES.get(slot)
    if not path or not path.exists():
        print(f"No digest at {path}", file=sys.stderr)
        return 1
    digest = json.loads(path.read_text())
    blocks = _to_slack_blocks(digest)
    fallback_text = digest["blocks"][0].get("text", "myfinancial digest")

    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_NEWS_CHANNEL")
    if token and channel:
        return 0 if post_chat(token, channel, blocks, fallback_text) else 1

    webhook = os.environ.get("SLACK_NEWS_WEBHOOK_URL")
    if webhook:
        return 0 if post_webhook(webhook, blocks, fallback_text) else 1

    print("No Slack credentials set — skipping", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
