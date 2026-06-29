"""Pull last 24h market news from RSS feeds; rank by importance via Gemini.

Output: data/news.json with up to 30 raw items + the top 8 ranked items.
"""
from __future__ import annotations

import datetime as dt
import html as html_lib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

import score_news

OUT = Path(__file__).parent / "data" / "news.json"

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# Default feeds — overridable via NEWS_FEEDS env var (JSON list of [name, url])
DEFAULT_FEEDS = [
    ("ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("ET Stocks", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
    ("Livemint Markets", "https://www.livemint.com/rss/markets"),
    ("Livemint Money", "https://www.livemint.com/rss/money"),
    ("Moneycontrol Markets", "https://www.moneycontrol.com/rss/marketreports.xml"),
    ("Moneycontrol Business", "https://www.moneycontrol.com/rss/business.xml"),
    ("Business Standard Markets", "https://www.business-standard.com/rss/markets-106.rss"),
    ("CNBC TV18", "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml"),
]


def _load_feeds() -> list[tuple[str, str]]:
    raw = os.environ.get("NEWS_FEEDS")
    if not raw:
        return DEFAULT_FEEDS
    try:
        parsed = json.loads(raw)
        return [tuple(x) for x in parsed]
    except json.JSONDecodeError as e:
        print(f"NEWS_FEEDS invalid JSON ({e}) — using defaults", file=sys.stderr)
        return DEFAULT_FEEDS


def _clean(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_ts(raw: str) -> dt.datetime | None:
    if not raw:
        return None
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            ts = dt.datetime.strptime(raw, fmt)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt.timezone.utc)
            return ts.astimezone(dt.timezone.utc)
        except ValueError:
            continue
    return None


def fetch_feed(name: str, url: str, max_items: int = 15) -> list[dict]:
    try:
        r = requests.get(url, headers=UA, timeout=15)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        out: list[dict] = []
        for item in root.iter("item"):
            title = _clean(item.findtext("title") or "")
            if not title:
                continue
            ts = _parse_ts((item.findtext("pubDate") or "").strip())
            out.append({
                "source": name,
                "title": title,
                "description": _clean(item.findtext("description") or "")[:400],
                "link": (item.findtext("link") or "").strip(),
                "ts": ts.isoformat() if ts else None,
            })
            if len(out) >= max_items:
                break
        print(f"  {name}: {len(out)}")
        return out
    except Exception as e:
        print(f"  {name} failed: {e}")
        return []


def fetch_all(hours_back: int = 24) -> list[dict]:
    items: list[dict] = []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_back)
    feeds = _load_feeds()
    print(f"Fetching {len(feeds)} RSS feeds...")
    for name, url in feeds:
        for art in fetch_feed(name, url):
            if art["ts"]:
                ts = dt.datetime.fromisoformat(art["ts"])
                if ts < cutoff:
                    continue
            items.append(art)
        time.sleep(0.3)

    # Dedupe on title prefix (different sources running same wire story)
    seen, deduped = set(), []
    for a in items:
        key = a["title"][:80].lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(a)
    return deduped


def main() -> int:
    items = fetch_all(hours_back=24)
    print(f"{len(items)} unique items in last 24h")

    top_n = int(os.environ.get("NEWS_TOP_N", "8"))
    ranked = score_news.rank(items, top_n=top_n)
    print(f"{len(ranked)} ranked top items")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "fetched_at": dt.datetime.utcnow().isoformat() + "Z",
        "all": items[:50],
        "top": ranked,
    }, indent=2, default=str))
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
