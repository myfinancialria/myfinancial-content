"""Daily Personal-Finance Newsletter → Slack only.

Pulls last-24h personal-finance RSS items, uses Gemini to:
  1. Filter strictly to PF-relevant items
  2. Pick 5 most important / trending — at least 2 MUST be about taxation
  3. Write a Slack-formatted newsletter (blocks-friendly markdown)

Categories covered: investment, mutual funds, taxation, retirement,
goal planning, insurance.

Output: posts as a single Slack message + saves snapshot for audit.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import requests

import market_data as md

HERE = Path(__file__).parent
SNAP = HERE / "data" / "snapshots" / "pf_newsletter.json"
SNAP.parent.mkdir(parents=True, exist_ok=True)


PF_FEEDS = [
    ("Livemint Money", "https://www.livemint.com/rss/money"),
    ("Moneycontrol Personal Finance",
     "https://www.moneycontrol.com/rss/personalfinance.xml"),
    ("ET Wealth",
     "https://economictimes.indiatimes.com/wealth/rssfeeds/837555174.cms"),
    ("1Finance", "https://1finance.co.in/blog/feed/"),
    ("Groww Blog", "https://groww.in/blog/feed"),
    ("Dhan Blog", "https://dhan.co/blog/feed/"),
    ("ET Tax",
     "https://economictimes.indiatimes.com/wealth/tax/rssfeeds/82485631.cms"),
    ("Livemint Tax",
     "https://www.livemint.com/rss/tax"),
]


def fetch_pf_news(hours_back: int = 36) -> list[dict]:
    """Borrow market_data._clean / _parse_ts pattern but with PF-tuned feeds."""
    import xml.etree.ElementTree as ET
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_back)
    items: list[dict] = []
    for name, url in PF_FEEDS:
        try:
            r = requests.get(url, headers={"User-Agent": md.HEADERS["User-Agent"]},
                              timeout=15)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception as e:
            print(f"  {name} failed: {e}", file=sys.stderr)
            continue
        for it in root.iter("item"):
            title = md._clean(it.findtext("title") or "")
            if not title:
                continue
            ts = md._parse_ts((it.findtext("pubDate") or "").strip())
            if ts and ts < cutoff:
                continue
            items.append({
                "source": name,
                "title": title,
                "summary": md._clean(it.findtext("description") or "")[:400],
                "link": (it.findtext("link") or "").strip(),
                "ts": ts.isoformat() if ts else None,
            })
        time.sleep(0.3)
    seen, dedup = set(), []
    for a in items:
        key = a["title"][:80].lower()
        if key in seen:
            continue
        seen.add(key)
        dedup.append(a)
    print(f"  -> {len(dedup)} PF items in last {hours_back}h")
    return dedup


SYSTEM = """You are the editor of myfinancial.in's daily personal-finance
newsletter. The reader is an Indian salaried / self-employed earner or NRI
who values clear, jargon-free explanations of money topics — not market
trading.

TASK
- From the list of news headlines provided, pick EXACTLY 5 items.
- AT LEAST 2 of the 5 MUST be about TAXATION (income tax, ITR, deductions,
  TDS, capital gains, GST, tax planning).
- The remaining 3 should cover: investments, mutual funds, retirement, goal
  planning, or insurance. Pick the most newsworthy / actionable mix.
- Skip anything purely about market levels, stock tips, or trading.
- Reject sensational / clickbait items.

OUTPUT FORMAT — Slack-friendly Markdown, no HTML.
The output must follow this structure EXACTLY:

📬 *MyFinancial Personal-Finance Newsletter — <DD Month YYYY>*

_Five things every Indian earner should know today._

---

*1. <Category emoji> <Headline (your own writing, not the original)>*
<2-3 sentence plain-English explainer of what happened and why it matters>
_Why it matters:_ <1 line on actionability — who's affected, what to do>
🔗 <link from source>

(repeat for items 2-5)

---

📌 *Tax tip of the day*
<Single practical tax tip — 50-80 words, actionable, India-relevant>

_— myfinancial.in · For Indians who'd rather understand than be sold to._

CATEGORY EMOJIS (use the one matching item type):
• 💰 Taxation
• 📈 Investments / Mutual Funds
• 🪙 Gold / Fixed Income
• 🛡️ Insurance
• 🏖️ Retirement / NPS / EPF
• 🎯 Goal Planning

Reply with ONLY the newsletter content. No preamble, no closing remarks."""


from llm import call_llm as _shared_call_llm


def call_gemini(prompt: str, system: str) -> Optional[str]:
    # PF newsletter: low temp (factual), medium output, grounding ON for
    # fresh PF news.
    return _shared_call_llm(
        prompt, system,
        temperature=0.4,
        max_tokens=8000,
        top_p=0.95,
    )


def build_prompt(items: list[dict]) -> str:
    today = dt.date.today().strftime("%d %B %Y")
    lines = [f"Today is {today}. Write the newsletter.\n\n",
             "AVAILABLE HEADLINES (most recent first):\n"]
    for i, it in enumerate(items[:40], 1):
        lines.append(f"{i}. [{it['source']}] {it['title']}")
        if it.get("summary"):
            lines.append(f"   {it['summary'][:200]}")
        if it.get("link"):
            lines.append(f"   {it['link']}")
        lines.append("")
    return "\n".join(lines)


def post_slack(body: str) -> bool:
    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CONTENT_CHANNEL")
    webhook = os.environ.get("SLACK_CONTENT_WEBHOOK_URL")
    if token and channel:
        r = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json; charset=utf-8"},
            json={"channel": channel, "text": body, "mrkdwn": True,
                  "unfurl_links": False, "unfurl_media": False},
            timeout=30,
        )
        ok = r.ok and r.json().get("ok")
        if not ok:
            print(f"Slack chat.postMessage failed: {r.status_code} "
                  f"{r.text[:200]}", file=sys.stderr)
        else:
            print(f"✓ posted to Slack channel {channel}")
        return bool(ok)
    if webhook:
        r = requests.post(webhook, json={"text": body}, timeout=30)
        if not r.ok:
            print(f"Slack webhook failed: {r.status_code} {r.text[:200]}",
                  file=sys.stderr)
        else:
            print("✓ posted to Slack webhook")
        return r.ok
    print("Neither SLACK_BOT_TOKEN+SLACK_CONTENT_CHANNEL nor "
          "SLACK_CONTENT_WEBHOOK_URL set", file=sys.stderr)
    return False


def main() -> int:
    items = fetch_pf_news(hours_back=36)
    if not items:
        print("No PF items fetched — aborting", file=sys.stderr)
        return 1
    prompt = build_prompt(items)
    print(f"Calling Gemini with {len(prompt)} char prompt...")
    body = call_gemini(prompt, SYSTEM)
    if not body:
        print("Gemini returned nothing — aborting", file=sys.stderr)
        return 1

    SNAP.write_text(json.dumps({
        "fetched_at": dt.datetime.utcnow().isoformat() + "Z",
        "item_count": len(items),
        "newsletter": body,
    }, indent=2, default=str))

    return 0 if post_slack(body) else 1


if __name__ == "__main__":
    raise SystemExit(main())
