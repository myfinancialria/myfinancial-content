"""Global news fetcher + Gemini importance scorer.

Pulls 12-24h headlines from a small set of global business RSS feeds, then
asks Gemini Flash to rank them 0-10 for impact on Indian markets. Falls back
to a keyword-heuristic scorer if Gemini is unreachable.
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

import requests

DEFAULT_FEEDS = [
    ("Reuters Asia", "https://www.reutersagency.com/feed/?best-regions=asia&post_type=best"),
    ("ET International",
     "https://economictimes.indiatimes.com/news/international/business/rssfeeds/1086955.cms"),
    ("ET World News",
     "https://economictimes.indiatimes.com/news/international/world-news/rssfeeds/296589292.cms"),
    ("MarketWatch Top",
     "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("CNBC Top News",
     "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
    ("Yahoo Finance",
     "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^DJI,^IXIC&region=US&lang=en-US"),
]

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


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
    ):
        try:
            ts = dt.datetime.strptime(raw, fmt)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt.timezone.utc)
            return ts.astimezone(dt.timezone.utc)
        except ValueError:
            continue
    return None


def fetch_feed(name: str, url: str, max_items: int = 12) -> list[dict]:
    try:
        r = requests.get(url, headers=UA, timeout=15)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"  {name} failed: {e}", file=sys.stderr)
        return []
    out: list[dict] = []
    for item in root.iter("item"):
        title = _clean(item.findtext("title") or "")
        if not title:
            continue
        ts = _parse_ts((item.findtext("pubDate") or "").strip())
        out.append({
            "source": name,
            "title": title,
            "link": (item.findtext("link") or "").strip(),
            "ts": ts.isoformat() if ts else None,
        })
        if len(out) >= max_items:
            break
    return out


def fetch_all(hours_back: int = 18) -> list[dict]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_back)
    items: list[dict] = []
    print(f"Fetching {len(DEFAULT_FEEDS)} RSS feeds...")
    for name, url in DEFAULT_FEEDS:
        for art in fetch_feed(name, url):
            if art["ts"]:
                ts = dt.datetime.fromisoformat(art["ts"])
                if ts < cutoff:
                    continue
            items.append(art)
        time.sleep(0.3)

    seen, deduped = set(), []
    for a in items:
        key = a["title"][:80].lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(a)
    print(f"  -> {len(deduped)} unique items in last {hours_back}h")
    return deduped


# ---- Importance scoring ----
_IMPORTANT = (
    "fed", "fomc", "rate", "inflation", "cpi", "ppi", "nfp", "jobs",
    "gdp", "treasury", "yield", "dollar", "rupee", "crude", "oil",
    "brent", "gold", "china", "tariff", "sanction", "geopolitic",
    "earnings", "guidance", "beat", "miss", "downgrade", "upgrade",
    "merger", "acquisition", "ipo", "default", "bankruptcy",
    "fii", "fpi", "sebi", "rbi", "modi", "budget",
)
_PENALTY = (
    "horoscope", "celebrity", "sports", "viral", "lifestyle",
    "should you buy", "stocks to buy", "5 stocks", "10 stocks",
)


def _heuristic(title: str) -> int:
    t = title.lower()
    score = 3
    for kw in _IMPORTANT:
        if kw in t:
            score += 1
    for kw in _PENALTY:
        if kw in t:
            score -= 4
    return max(0, min(10, score))


SYSTEM_PROMPT = (
    "You are a senior Indian markets editor. Score each global headline 0-10 "
    "for impact on Indian equity markets in the NEXT 24 hours. Reward: Fed/ECB "
    "actions, US/China macro data, oil moves, large-cap earnings, geopolitical "
    "shocks, FII flow drivers. Penalise: domestic-US-only stories, lifestyle, "
    "rumours, broker tip lists. Respond with ONLY a JSON array of objects with "
    "keys 'i' (input index) and 's' (score 0-10). No prose, no markdown."
)


def rank(items: list[dict], top_n: int = 5) -> list[dict]:
    if not items:
        return []
    key = os.environ.get("GEMINI_API_KEY")
    capped = items[:30]
    scored: list[dict] | None = None
    if key:
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={key}")
        lines = [f"{i}. [{a['source']}] {a['title']}"
                 for i, a in enumerate(capped)]
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user",
                          "parts": [{"text": "\n".join(lines)}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                "maxOutputTokens": 2000,
            },
        }
        try:
            r = requests.post(url, json=payload, timeout=60)
            if r.ok:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
                parsed = json.loads(text)
                scored = []
                for e in parsed:
                    i = e.get("i")
                    if not isinstance(i, int) or not (0 <= i < len(capped)):
                        continue
                    it = dict(capped[i])
                    it["score"] = int(e.get("s", 0))
                    scored.append(it)
        except Exception as e:
            print(f"Gemini ranking failed: {e}", file=sys.stderr)

    if scored is None:
        scored = []
        for a in capped:
            it = dict(a)
            it["score"] = _heuristic(a.get("title", ""))
            scored.append(it)

    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    return scored[:top_n]
