"""Pull the latest 24h personal-finance articles from competitor sources.

The actual list of sources (RSS feeds, sitemap specs, Google News queries) is
loaded from the `CONTENT_FEEDS` env var so it can be set as a private GitHub
Actions secret without checking it into a public repo.

Set it with:
  gh secret set CONTENT_FEEDS -R <repo> < your-feeds.json

Expected JSON shape:
  {
    "rss":   [ ["Source Name", "https://example.com/feed"], ... ],
    "gnews": [ ["Source Name", "site:example.com query"], ... ],
    "sitemap": [
      { "name": "...", "sitemap": "...", "include_paths": [...],
        "exclude_paths": [...], "max_items": 8 }, ...
    ]
  }

Falls back to a minimal generic feed list if the env var isn't set so the
script still runs for anyone cloning the repo for development.

Writes data/raw_articles.json with a unified schema.
"""
from __future__ import annotations

import datetime as dt
import html as html_lib
import json
import os
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

DATA = Path(__file__).parent / "data"
OUT = DATA / "raw_articles.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# Minimal public fallback — just enough to run the pipeline end-to-end.
# Real source list lives in the CONTENT_FEEDS secret.
_FALLBACK_FEEDS = {
    "rss": [
        ["Livemint Money", "https://www.livemint.com/rss/money"],
    ],
    "gnews": [],
    "sitemap": [],
}


def _load_feeds() -> dict:
    raw = os.environ.get("CONTENT_FEEDS")
    if not raw:
        print("CONTENT_FEEDS not set — using minimal public fallback feed list",
              file=sys.stderr)
        return _FALLBACK_FEEDS
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"CONTENT_FEEDS is not valid JSON ({e}) — falling back",
              file=sys.stderr)
        return _FALLBACK_FEEDS
    return {
        "rss": parsed.get("rss") or [],
        "gnews": parsed.get("gnews") or [],
        "sitemap": parsed.get("sitemap") or [],
    }


_FEEDS = _load_feeds()
RSS_FEEDS = [tuple(x) for x in _FEEDS["rss"]]
GNEWS_TOPICS = [tuple(x) for x in _FEEDS["gnews"]]
SITEMAP_SOURCES = _FEEDS["sitemap"]


def _clean(html: str) -> str:
    """Strip tags, decode entities, normalise whitespace."""
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = html_lib.unescape(text)
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


def _mongo_id_timestamp(hex_id: str) -> int:
    """Decode the first 4 bytes of a MongoDB ObjectId as Unix seconds."""
    try:
        return int(hex_id[:8], 16)
    except Exception:
        return 0


def _title_from_url_slug(loc: str) -> str:
    """Last path segment, dashes → spaces, title-case (fallback only)."""
    slug = loc.rstrip("/").split("?", 1)[0].rsplit("/", 1)[-1]
    slug = re.sub(r"[-_]+", " ", slug).strip()
    return slug[:1].upper() + slug[1:]


def _html_title(url: str, sess: requests.Session) -> str | None:
    """Fetch the page and pull <title> or og:title — best-effort."""
    try:
        r = sess.get(url, timeout=12)
        if not r.ok:
            return None
        html = r.text
        # Open Graph first (usually cleaner)
        m = re.search(
            r'<meta\s+[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']',
            html, re.IGNORECASE)
        if m:
            return _clean(m.group(1))
        m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        if m:
            return _clean(m.group(1))
    except Exception as e:
        print(f"  title fetch failed for {url}: {e}")
    return None


def fetch_sitemap_source(spec: dict) -> list[dict]:
    """Parse sitemap → filter to relevant paths → sort by id-timestamp → fetch titles."""
    name = spec["name"]
    sitemap_url = spec["sitemap"]
    include = spec.get("include_paths", ())
    exclude = spec.get("exclude_paths", ())
    max_items = spec.get("max_items", 8)
    try:
        sess = requests.Session(); sess.headers.update(UA)
        r = sess.get(sitemap_url, timeout=15)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        candidates: list[tuple[int, str, str]] = []
        for u in root.findall(".//s:url", ns):
            loc = u.findtext("s:loc", default="", namespaces=ns) or ""
            if not loc:
                continue
            # path filtering
            from urllib.parse import urlparse, parse_qs
            path = urlparse(loc).path
            if include and not any(path.startswith(p + "/") or path == p for p in include):
                continue
            if exclude and any(path.startswith(p + "/") or path == p for p in exclude):
                continue
            # Pull id query param for ordering
            qs = parse_qs(urlparse(loc).query)
            id_hex = (qs.get("id") or [""])[0]
            ts = _mongo_id_timestamp(id_hex) if id_hex else 0
            # lastmod fallback
            lm = u.findtext("s:lastmod", default="", namespaces=ns) or ""
            candidates.append((ts, loc, lm))
        candidates.sort(reverse=True)  # newest first

        out: list[dict] = []
        for ts, loc, lm in candidates[:max_items]:
            title = _html_title(loc, sess) or _title_from_url_slug(loc)
            published = (dt.datetime.utcfromtimestamp(ts).strftime("%a, %d %b %Y %H:%M:%S +0000")
                         if ts else lm)
            out.append({
                "source": name,
                "title": title,
                "link": loc,
                "summary": "",
                "published": published,
                "via": "sitemap",
            })
            time.sleep(0.2)
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
    print("Fetching sitemap-based sources...")
    for spec in SITEMAP_SOURCES:
        all_items.extend(fetch_sitemap_source(spec))
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
