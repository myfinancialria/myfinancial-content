"""Ping Slack when fact-check verdict is 'rewrite' or 'review'.

Silent when verdict is 'ship' — we don't spam the channel with all-clears.

Required env (same as slack_post.py):
  SLACK_BOT_TOKEN + SLACK_CONTENT_CHANNEL  (preferred — rich blocks)
    OR
  SLACK_CONTENT_WEBHOOK_URL  (text fallback)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

HERE = Path(__file__).parent
DATA = HERE / "data"
META = DATA / "article.json"
REPORT = DATA / "fact_check.json"


VERDICT_LABEL = {
    "rewrite": ":rotating_light: NEEDS REVISION",
    "review":  ":warning: NEEDS REVIEW",
}
VERDICT_EMOJI = {"rewrite": ":red_circle:", "review": ":large_yellow_circle:"}
STATUS_EMOJI = {"likely_wrong": ":x:", "unsure": ":grey_question:",
                "verified": ":white_check_mark:"}


def short(s: str, n: int = 240) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def build_blocks(report: dict, meta: dict) -> tuple[str, list[dict]]:
    verdict = (report.get("verdict") or "").lower()
    label = VERDICT_LABEL.get(verdict, verdict.upper() or "UNKNOWN")
    title = meta.get("title") or report.get("article_title") or "Today's article"
    url = meta.get("canonical") or ""
    summary = report.get("summary") or "No summary."

    flagged = [c for c in report.get("claims", [])
               if c.get("status") in ("likely_wrong", "unsure")]
    n_lw = sum(1 for c in flagged if c.get("status") == "likely_wrong")
    n_un = sum(1 for c in flagged if c.get("status") == "unsure")

    header_text = f"Fact-check: {label.split(' ', 1)[-1]}"

    fields_text_parts = [f"*Article:* <{url}|{title}>" if url else f"*Article:* {title}",
                         f"*Verdict:* {VERDICT_EMOJI.get(verdict, '')} `{verdict}`",
                         f"*Flagged:* {n_lw} likely wrong · {n_un} unsure",
                         f"\n*Summary:* {summary}"]

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text}},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": "\n".join(fields_text_parts)}},
        {"type": "divider"},
    ]

    # Up to 5 flagged claims with detail
    for c in flagged[:5]:
        status = c.get("status", "")
        emoji = STATUS_EMOJI.get(status, "")
        claim_text = (
            f"{emoji} *{status.replace('_', ' ').title()}*\n"
            f">_Claim:_ {short(c.get('claim', ''), 220)}\n"
            f">_Why:_ {short(c.get('note', ''), 260)}"
        )
        src = c.get("source", "")
        if src:
            # Take only the first URL if multiple are concatenated
            first = src.split(",")[0].strip()
            claim_text += f"\n><{first}|Source>"
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": claim_text}})

    if len(flagged) > 5:
        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"_+ {len(flagged) - 5} more flagged claims — see fact_check.json in repo._"}
        ]})

    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn",
         "text": "Gemini-grounded fact-check · myfinancial.in content engine"}
    ]})

    plain = f"{label}: {title} — {n_lw} likely wrong, {n_un} unsure"
    return plain, blocks


def post(text: str, blocks: list[dict]) -> int:
    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CONTENT_CHANNEL")
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
            print(f"Slack alert failed: {j}", file=sys.stderr)
            return 1
        print(f"Alert posted to {channel}")
        return 0
    webhook = os.environ.get("SLACK_CONTENT_WEBHOOK_URL")
    if webhook:
        r = requests.post(webhook, json={"text": text, "blocks": blocks}, timeout=15)
        r.raise_for_status()
        print("Alert posted via webhook")
        return 0
    print("Set SLACK_BOT_TOKEN+SLACK_CONTENT_CHANNEL or SLACK_CONTENT_WEBHOOK_URL",
          file=sys.stderr)
    return 1


def main() -> int:
    if not REPORT.exists():
        print("No fact_check.json — nothing to alert on")
        return 0  # not an error — fact-check might have been skipped
    report = json.loads(REPORT.read_text())
    verdict = (report.get("verdict") or "").lower()
    if verdict not in ("rewrite", "review"):
        print(f"Verdict is '{verdict}' — no alert needed")
        return 0
    meta = json.loads(META.read_text()) if META.exists() else {}
    text, blocks = build_blocks(report, meta)
    return post(text, blocks)


if __name__ == "__main__":
    raise SystemExit(main())
