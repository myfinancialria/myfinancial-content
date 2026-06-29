"""Archive a news digest as a web article.

build_digest.py writes data/digest_<slot>.json (structured blocks consumed by
slack_post.py / telegram_post.py). export() turns that same digest into a
markdown article so the unified site's "News" tab has real archived content.

  articles/<YYYY-MM-DD>-<slot>-brief.md

The root site_build.py picks these up automatically.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"
ARTS = HERE / "articles"

BASE_URL = "https://myfinancialria.github.io/myfinancial-content"


def _block_text_to_md(text: str) -> str:
    """Slack/Telegram block text → markdown our renderer understands."""
    out = []
    for line in text.splitlines():
        ln = line
        # Slack bullets → markdown list items
        ln = re.sub(r"^\s*•\s+", "- ", ln)
        # Slack single-asterisk bold → markdown double-asterisk bold
        ln = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"**\1**", ln)
        out.append(ln)
    return "\n".join(out)


def export(slot: str, when: dt.datetime | None = None) -> Path | None:
    when = when or dt.datetime.now()
    digest_path = DATA / f"digest_{slot}.json"
    if not digest_path.exists():
        print(f"page_export: {digest_path} missing — nothing to archive", file=sys.stderr)
        return None
    digest = json.loads(digest_path.read_text())
    blocks = digest.get("blocks", [])
    if not blocks:
        print("page_export: empty digest — skipping", file=sys.stderr)
        return None

    day = when.strftime("%Y-%m-%d")
    slug = f"{day}-{slot}-brief"
    header = next((b for b in blocks if b.get("type") == "header"), None)
    title = (header or {}).get("text", f"Market News — {when:%d %b %Y}").strip()

    body_parts = []
    desc_bits = []
    for b in blocks:
        if b.get("type") == "header":
            continue
        bt = b.get("title", "").strip()
        if bt:
            body_parts.append(f"## {bt}")
            desc_bits.append(bt)
        body_parts.append(_block_text_to_md(b.get("text", "")))
    body = "\n\n".join(p for p in body_parts if p.strip())
    description = ("Today's " + ", ".join(re.sub(r"[^\w &/]", "", d).strip()
                  for d in desc_bits[:3])).strip(", ")[:180] or title

    ARTS.mkdir(exist_ok=True)
    md = (
        "---\n"
        f'title: "{title.replace(chr(34), chr(39))}"\n'
        f"date: {day}\n"
        "author: myfinancial\n"
        "category: news\n"
        f'description: "{description.replace(chr(34), chr(39))}"\n'
        f"slug: {slug}\n"
        f"canonical: {BASE_URL}/articles/{slug}/\n"
        "---\n\n"
        f"# {title}\n\n"
        f"{body}\n"
    )
    (ARTS / f"{slug}.md").write_text(md)
    print(f"page_export: wrote {ARTS / (slug + '.md')}")
    return ARTS / f"{slug}.md"


if __name__ == "__main__":
    import os
    raise SystemExit(0 if export(os.environ.get("SLOT", "morning")) else 1)
