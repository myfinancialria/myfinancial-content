"""Hard gate: refuse to publish if the article doesn't have ≥3 reachable refs."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

HERE = Path(__file__).parent
META = HERE / "data" / "article.json"
ARTS = HERE / "articles"

MIN_REFS = 3
REQUEST_TIMEOUT = 12
UA = {"User-Agent": "Mozilla/5.0 (compatible; business-mavericks/1.0)"}


def _load_body() -> str:
    if not META.exists():
        print("article.json missing", file=sys.stderr); sys.exit(3)
    meta = json.loads(META.read_text())
    fp = ARTS / meta["filename"]
    text = fp.read_text()
    return re.sub(r"^---\n[\s\S]+?\n---\n+", "", text, count=1)


def _refs_section(body: str) -> str:
    m = re.search(r"##\s+References\s*\n([\s\S]+?)(?=\n##\s|\Z)", body, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _extract_urls(text: str) -> list[str]:
    md_urls = re.findall(r"\[[^\]]+\]\((https?://[^)]+)\)", text)
    bare = re.findall(r"https?://[^\s\)<>\"']+", text)
    seen, out = set(), []
    for u in md_urls + bare:
        u = u.rstrip(".,;:)]\"'>")
        if u not in seen:
            seen.add(u); out.append(u)
    return out


def _check_url(url: str) -> tuple[bool, str]:
    try:
        r = requests.head(url, headers=UA, allow_redirects=True, timeout=REQUEST_TIMEOUT)
        if r.status_code < 400:
            return True, f"{r.status_code}"
        r = requests.get(url, headers=UA, allow_redirects=True,
                         timeout=REQUEST_TIMEOUT, stream=True); r.close()
        return (r.status_code < 400), f"{r.status_code}"
    except requests.exceptions.RequestException as e:
        return False, type(e).__name__


def main() -> int:
    body = _load_body()
    refs = _refs_section(body)
    if not refs:
        print("✗ No ## References section", file=sys.stderr); return 3
    urls = _extract_urls(refs)
    if len(urls) < MIN_REFS:
        print(f"✗ Only {len(urls)} URLs (need {MIN_REFS})", file=sys.stderr); return 3

    print(f"Checking {len(urls)} reference URLs...")
    working = []
    for u in urls:
        ok, detail = _check_url(u)
        host = urlparse(u).netloc
        if ok:
            working.append(u); print(f"  ✓ [{detail}] {host}")
        else:
            print(f"  ✗ [{detail}] {host}", file=sys.stderr)
    if len(working) < MIN_REFS:
        print(f"\n✗ Only {len(working)} reachable URLs — refusing.", file=sys.stderr)
        return 3
    print(f"\n✓ {len(working)}/{len(urls)} references verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
