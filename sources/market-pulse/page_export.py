"""Archive a market-pulse infographic as a web article.

The market-pulse scripts (premarket/postmarket/commodities) render a PNG and
post it to Telegram. Calling export() here additionally persists each run as a
markdown article + hero image so the unified site's "Market Pulse" tab has real
archived content.

  articles/<YYYY-MM-DD>-<kind>.md      — frontmatter + caption-as-body
  output/<slug>/hero.png               — the infographic (copied)

The root site_build.py picks these up automatically.
"""
from __future__ import annotations

import datetime as dt
import re
import shutil
from pathlib import Path

HERE = Path(__file__).parent
ARTS = HERE / "articles"
OUT = HERE / "output"

BASE_URL = "https://myfinancialria.github.io/myfinancial-content"


def _caption_to_md(caption_html: str) -> str:
    """Telegram HTML caption → markdown. Handles <b>/<i> and entities."""
    s = caption_html
    s = re.sub(r"</?b>", "**", s)
    s = re.sub(r"</?i>", "*", s)
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    # Drop the trailing "myfinancial.in" signature line — the site adds its own.
    lines = [ln.rstrip() for ln in s.splitlines()]
    lines = [ln for ln in lines if ln.strip().strip("*").strip().lower() != "myfinancial.in"]
    return "\n\n".join(ln for ln in lines if ln.strip())


def export(kind: str, title: str, when: dt.datetime, png_path: Path,
           caption_html: str, description: str = "") -> Path:
    """Write the article + copy the hero. `kind` e.g. 'pre-market'."""
    day = when.strftime("%Y-%m-%d")
    slug = f"{day}-{kind}"
    ARTS.mkdir(exist_ok=True)
    body = _caption_to_md(caption_html)
    if not description:
        # First non-empty line, stripped of markdown, as the meta description.
        first = next((ln for ln in body.splitlines() if ln.strip()), title)
        description = re.sub(r"[*_`]", "", first)[:180]

    md = (
        "---\n"
        f'title: "{title.replace(chr(34), chr(39))}"\n'
        f"date: {day}\n"
        "author: myfinancial\n"
        "category: market-pulse\n"
        f'description: "{description.replace(chr(34), chr(39))}"\n'
        f"slug: {slug}\n"
        f"canonical: {BASE_URL}/articles/{slug}/\n"
        "---\n\n"
        f"# {title}\n\n"
        f"{body}\n"
    )
    (ARTS / f"{slug}.md").write_text(md)

    if png_path and Path(png_path).exists():
        hero_dir = OUT / slug
        hero_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(png_path, hero_dir / "hero.png")

    print(f"page_export: wrote {ARTS / (slug + '.md')}")
    return ARTS / f"{slug}.md"
