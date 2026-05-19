"""Pull the latest 24h personal-finance articles from competitor sources.

Sources (all free, no API key needed):
  - Livemint Money (RSS)
  - 1Finance blog
  - The Fynprint
  - ET Money blog
  - INDmoney blog

Writes data/raw_articles.json with a unified schema.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

DATA = Path(__file__).parent / "data"
OUT = DATA / "raw_articles.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

RSS_FEEDS = [
    ("Livemint Money", "https://www.livemint.com/rss/money"),
    ("Livemint Markets", "https://www.livemint.com/rss/markets"),
    ("ET Money Blog", "https://www.etmoney.com/blog/feed"),
    ("Moneycontrol Personal Finance",
     "https://www.moneycontrol.com/rss/personalfinance.xml"),
]

# Google News search proxies for sources without clean RSS
GNEWS_TOPICS = [
    ("1Finance", "site:1finance.co.in personal finance"),
    ("The Fynprint", "site:thefynprint.com"),
    ("INDmoney", "site:indmoney.com blog"),
]


def _clean(html: str) -> str:
    """Strip tags, normalise whitespace."""
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_rss(name: str, url: str, max_items: int = 12) -> list[dict]:
    try:
        r = requests.get(url, headers=UA, timeout=15)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        out = []
        for item in root.findall(".//item")[:max_items]:
            out.append({
                "source": name,
                "title": _clean(item.findtext("title") or ""),
                "link": (item.findtext("link") or "").strip(),
                "summary": _clean(item.findtext("description") or "")[:400],
                "published": (item.findtext("pubDate") or "").strip(),
                "via": "rss",
            })
        print(f"  {name}: {len(out)} items")
        return out
    except Exception as e:
        print(f"  {name} failed: {e}")
        return []


def fetch_gnews(name: str, query: str, max_items: int = 8) -> list[dict]:
    q = urllib.parse.quote_plus(f"{query} when:1d")
    url = (f"https://news.google.com/rss/search?q={q}"
           "&hl=en-IN&gl=IN&ceid=IN:en")
    try:
        r = requests.get(url, headers=UA, timeout=15)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        out = []
        for item in root.findall(".//item")[:max_items]:
            title_raw = (item.findtext("title") or "").strip()
            # Google News titles end with " - Source"
            title = title_raw.rsplit(" - ", 1)[0] if " - " in title_raw else title_raw
            out.append({
                "source": name,
                "title": _clean(title),
                "link": (item.findtext("link") or "").strip(),
                "summary": _clean(item.findtext("description") or "")[:400],
                "published": (item.findtext("pubDate") or "").strip(),
                "via": "google-news",
            })
        print(f"  {name}: {len(out)} items")
        return out
    except Exception as e:
        print(f"  {name} failed: {e}")
        return []


def main() -> int:
    DATA.mkdir(exist_ok=True)
    all_items: list[dict] = []
    print("Fetching RSS feeds...")
    for name, url in RSS_FEEDS:
        all_items.extend(fetch_rss(name, url))
        time.sleep(0.3)
    print("Fetching via Google News...")
    for name, query in GNEWS_TOPICS:
        all_items.extend(fetch_gnews(name, query))
        time.sleep(0.3)

    # Deduplicate on title prefix
    seen, deduped = set(), []
    for a in all_items:
        key = a["title"][:80].lower()
        if key not in seen:
            seen.add(key)
            deduped.append(a)

    payload = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "count": len(deduped),
        "articles": deduped,
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str))
    print(f"Wrote {OUT} — {len(deduped)} unique items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
