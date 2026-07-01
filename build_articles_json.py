"""
build_articles_json.py — emit a machine-readable feed of every article.

Writes `output/articles.json`, a single manifest the MyFinancial website (or any
front-end, e.g. a Stitch-designed UI) can fetch to render article lists, category
tabs and "related reads" rails — no HTML scraping needed.

It reuses site_build.py's own frontmatter parser, source list and category→tab
mapping, so the JSON always matches exactly what the site publishes.

Served at:  https://myfinancialria.github.io/myfinancial-content/articles.json

Run:
    python build_articles_json.py
Typically right after `python site_build.py` in the same CI job.
"""
from __future__ import annotations
import json, re, datetime as dt
from pathlib import Path

import site_build as sb   # single source of truth for parsing + categorisation

WORDS_PER_MIN = 220
FALLBACK_AUTHOR = "Nithin (CFP)"
HERO_NAMES = ("hero.jpg", "hero.png", "hero.jpeg", "hero.webp")


def hero_url(slug: str, source: str, hero_dir: Path | None) -> str | None:
    """Mirror site_build.copy_hero: content heroes live in output/, source heroes
    in their own output/<slug>/ dir. Return the public URL if one exists."""
    if (sb.OUT / "articles" / slug / "hero.jpg").exists():
        return f"{sb.BASE_URL}/articles/{slug}/hero.jpg"
    if hero_dir:
        for name in HERO_NAMES:
            if (hero_dir / slug / name).exists():
                return f"{sb.BASE_URL}/articles/{slug}/hero.jpg"  # copied out as hero.jpg
    return None


def first_paragraph(body: str, limit: int = 220) -> str:
    for block in re.split(r"\n\s*\n", body):
        text = re.sub(r"[#>*_`\-\[\]()!]", "", block).strip()
        text = re.sub(r"\s+", " ", text)
        # skip TL;DR labels / headings-only lines
        if len(text) > 40 and not text.lower().startswith("tl;dr"):
            return (text[:limit].rstrip() + "…") if len(text) > limit else text
    return ""


def reading_time(body: str) -> int:
    words = len(re.findall(r"\w+", body))
    return max(1, round(words / WORDS_PER_MIN))


def clean_author(fm: dict) -> str:
    a = (fm.get("author") or "").strip()
    return FALLBACK_AUTHOR if a.lower() in ("", "myfinancial", "myfinancial.in") else a


def collect() -> list[dict]:
    out = []
    for source, articles_dir, hero_dir in sb.SOURCES:
        if not articles_dir.exists():
            continue
        for md in sorted(articles_dir.glob("*.md")):
            fm, body = sb.parse_frontmatter(md.read_text(encoding="utf-8"))
            slug = fm.get("slug") or md.stem
            if slug == "2026-05-20-sample":          # skip the placeholder sample
                continue
            tab = sb.tab_for(source, fm.get("category"))
            kws = fm.get("keywords")
            out.append({
                "id": slug,
                "title": fm.get("title", slug),
                "slug": slug,
                "date": fm.get("date", ""),
                "author": clean_author(fm),
                "category": tab,                             # url key used across the site
                "categoryLabel": sb.TAB_LABEL.get(tab, ""),  # display label
                "rawCategory": fm.get("category") or "",
                "source": source,
                "excerpt": fm.get("description") or first_paragraph(body),
                "keywords": kws if isinstance(kws, list) else [],
                "url": fm.get("canonical") or f"{sb.BASE_URL}/articles/{slug}/",
                "thumbnail": hero_url(slug, source, hero_dir),
                "readingTimeMin": reading_time(body),
            })
    out.sort(key=lambda a: a["date"], reverse=True)
    return out


def category_facets(articles: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for a in articles:
        counts[a["category"]] = counts.get(a["category"], 0) + 1
    facets = []
    for t in sb.TABS:                     # preserve the site's tab order
        if not t["key"]:
            continue
        facets.append({"key": t["key"], "label": t["label"],
                       "count": counts.get(t["key"], 0)})
    return facets


def main() -> int:
    articles = collect()
    payload = {
        "generated": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "baseUrl": sb.BASE_URL,
        "count": len(articles),
        "categories": category_facets(articles),
        "articles": articles,
    }
    sb.OUT.mkdir(parents=True, exist_ok=True)
    dest = sb.OUT / "articles.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=None), encoding="utf-8")
    print(f"Wrote {dest}  ({len(articles)} articles, "
          f"{sum(1 for a in articles if a['thumbnail'])} with thumbnails)")
    for f in payload["categories"]:
        print(f"  {f['label']:<22} {f['count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
