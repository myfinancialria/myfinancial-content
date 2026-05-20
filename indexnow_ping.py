"""Ping IndexNow with today's article + sitemap so Bing/Yandex/Seznam pick it up fast.

How the key works (per https://www.indexnow.org/documentation):
  - You drop a text file at the root of your site: <key>.txt
  - The file's CONTENT is also the key (same string).
  - You POST {host, key, keyLocation, urlList} to api.indexnow.org/IndexNow
    and it fans out to all participating engines.

This script:
  1. Auto-discovers the key file in static/  (e.g. abc123…indexnow.txt
     or just abc123….txt — anything ending in .txt that contains its own
     name is a valid key file).
  2. Pings today's article URL + the sitemap.
  3. Non-fatal: if no key file or any error, exits 0 with a warning.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

HERE = Path(__file__).parent
STATIC = HERE / "static"
META = HERE / "data" / "article.json"
SITE_HOST = "myfinancialria.github.io"
SITE_BASE = f"https://{SITE_HOST}/myfinancial-content"
ENDPOINT = "https://api.indexnow.org/IndexNow"


def find_key_file() -> Path | None:
    """The key file is a .txt at site root whose filename == its content."""
    if not STATIC.exists():
        return None
    for p in STATIC.glob("*.txt"):
        try:
            content = p.read_text(encoding="utf-8").strip()
            stem = p.stem  # filename without .txt
            # Standard IndexNow: file name is the key, content matches
            if content == stem and len(content) >= 8:
                return p
        except Exception:
            continue
    return None


def urls_to_ping() -> list[str]:
    out = [f"{SITE_BASE}/sitemap.xml", f"{SITE_BASE}/"]
    if META.exists():
        try:
            m = json.loads(META.read_text())
            url = m.get("canonical")
            if url:
                out.insert(0, url)
        except Exception:
            pass
    # Dedupe, preserve order
    seen, deduped = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


def main() -> int:
    key_file = find_key_file()
    if not key_file:
        print("No IndexNow key file found in static/ — skipping ping. "
              "Drop your <key>.txt from Bing Webmaster into static/ to enable.",
              file=sys.stderr)
        return 0  # non-fatal

    key = key_file.stem
    key_location = f"{SITE_BASE}/{key_file.name}"
    urls = urls_to_ping()

    payload = {
        "host": SITE_HOST,
        "key": key,
        "keyLocation": key_location,
        "urlList": urls,
    }
    try:
        r = requests.post(ENDPOINT, json=payload, timeout=15)
        if r.status_code in (200, 202):
            print(f"IndexNow OK ({r.status_code}) — pinged {len(urls)} URL(s)")
            for u in urls:
                print(f"  • {u}")
        else:
            # Common: 400 if key not yet propagated, 422 if URL not under host
            print(f"IndexNow returned {r.status_code}: {r.text[:200]}",
                  file=sys.stderr)
    except Exception as e:
        print(f"IndexNow ping failed: {e}", file=sys.stderr)
    return 0  # non-fatal — never block the publish


if __name__ == "__main__":
    raise SystemExit(main())
