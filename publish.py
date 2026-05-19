"""Render today's article Markdown → output/ for GitHub Pages.

Outputs:
  output/index.html       — landing page listing latest articles
  output/articles/<slug>/index.html  — clean URL for each article
  output/sitemap.xml      — for Google indexing
  output/robots.txt
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
ARTS = HERE / "articles"
OUT = HERE / "output"
STATIC = HERE / "static"   # files copied as-is into output/ (verification, etc.)
META = HERE / "data" / "article.json"

BASE_URL = "https://myfinancialria.github.io/myfinancial-content"

CSS = """
:root { --navy:#0B2545; --green:#16A34A; --red:#DC2626; --grey:#6B7280; --bg:#F8FAFC; --card:#FFFFFF; --grid:#E5E7EB; }
* { box-sizing:border-box; }
body { font-family:'Inter',system-ui,-apple-system,sans-serif; background:var(--bg); color:var(--navy); margin:0; padding:0; line-height:1.65; -webkit-font-smoothing:antialiased; }
.wrap { max-width:760px; margin:0 auto; padding:48px 22px 80px; }
header.site { display:flex; justify-content:space-between; align-items:center; padding:18px 22px; border-bottom:1px solid var(--grid); background:#fff; position:sticky; top:0; z-index:5; }
header.site a { color:var(--navy); font-weight:800; text-decoration:none; font-size:18px; }
header.site .meta { color:var(--grey); font-size:13px; }
article h1 { font-size:34px; line-height:1.2; margin:0 0 8px; font-weight:800; letter-spacing:-0.02em; }
article .byline { color:var(--grey); font-size:14px; margin-bottom:30px; }
article h2 { font-size:24px; margin:38px 0 14px; font-weight:700; letter-spacing:-0.01em; }
article h3 { font-size:18px; margin:24px 0 10px; font-weight:700; color:#1E293B; }
article p { margin:10px 0; font-size:17px; }
article ul, article ol { padding-left:24px; }
article li { margin:6px 0; font-size:17px; }
article strong { font-weight:600; }
article a { color:#1D4ED8; text-decoration:none; border-bottom:1px solid #BFDBFE; }
article a:hover { background:#EFF6FF; }
article blockquote { border-left:3px solid var(--grid); margin:14px 0; padding:6px 14px; color:var(--grey); }
article code { background:#F1F5F9; padding:2px 6px; border-radius:4px; font-size:15px; }
article hr { border:none; border-top:1px solid var(--grid); margin:28px 0; }
article figure.hero { margin:0 0 28px; border-radius:14px; overflow:hidden; aspect-ratio:16/9; background:#E2E8F0; }
article figure.hero img { width:100%; height:100%; object-fit:cover; display:block; }
.list-item .thumb { display:block; width:100%; aspect-ratio:16/9; border-radius:10px; overflow:hidden; background:#E2E8F0; margin-bottom:10px; }
.list-item .thumb img { width:100%; height:100%; object-fit:cover; display:block; }
.tldr { background:#FFFBEB; border-left:3px solid #F59E0B; padding:16px 18px; border-radius:6px; margin:24px 0; }
.tldr p:first-child { font-weight:700; margin-top:0; color:#92400E; }
.fc { display:inline-flex; align-items:center; gap:6px; padding:4px 10px; border-radius:999px; font-size:12px; font-weight:600; margin-left:8px; }
.fc.ship { background:#DCFCE7; color:#166534; }
.fc.review { background:#FEF3C7; color:#92400E; }
.fc.rewrite { background:#FEE2E2; color:#991B1B; }
.list-item { padding:18px 0; border-bottom:1px solid var(--grid); }
.list-item h3 { margin:0 0 6px; font-size:20px; }
.list-item h3 a { color:var(--navy); border:none; }
.list-item .meta { color:var(--grey); font-size:13px; }
footer.site { text-align:center; color:var(--grey); font-size:13px; padding:36px 22px; border-top:1px solid var(--grid); margin-top:48px; }
@media (max-width: 640px) { .wrap { padding:28px 18px 60px; } article h1 { font-size:28px; } article h2 { font-size:21px; } article p, article li { font-size:16px; } }
"""

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{css}</style>
{seo}
</head>
<body>
<header class="site"><a href="/">myfinancial.in</a><span class="meta">Personal finance · For 15L+ earners and NRIs</span></header>
"""

FOOTER = """<footer class="site">© myfinancial.in · Built by Nithin (CFP) · <a href="https://myfinancial.in" style="color:inherit;">myfinancial.in</a></footer>
</body></html>
"""


def parse_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n([\s\S]+?)\n---\n+", text)
    if not m:
        return {}, text
    fm_raw = m.group(1)
    body = text[m.end():]
    fm: dict = {}
    for line in fm_raw.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip() for x in v[1:-1].split(",") if x.strip()]
        elif v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        fm[k.strip()] = v
    return fm, body


def md_to_html(md: str) -> str:
    """Lightweight Markdown → HTML. Enough for our article structure."""
    out_lines = []
    in_list = None  # "ul" / "ol" / None
    in_para = False
    in_tldr = False

    def close_para():
        nonlocal in_para
        if in_para:
            out_lines.append("</p>")
            in_para = False

    def close_list():
        nonlocal in_list
        if in_list:
            out_lines.append(f"</{in_list}>")
            in_list = None

    def inline(s: str) -> str:
        # Escape first, then re-apply markdown
        s = html.escape(s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                   r'<a href="\2" rel="noopener" target="_blank">\1</a>', s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*([^*\n]+)\*", r"<em>\1</em>", s)
        return s

    for raw in md.splitlines():
        line = raw.rstrip()
        # Headings
        if m := re.match(r"^(#{1,6})\s+(.+)$", line):
            close_para(); close_list()
            if in_tldr:
                out_lines.append("</div>")
                in_tldr = False
            lvl = len(m.group(1))
            out_lines.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
            continue
        # TL;DR detection
        if "**TL;DR**" in line.strip():
            close_para(); close_list()
            out_lines.append('<div class="tldr"><p>TL;DR</p>')
            in_tldr = True
            continue
        # Lists
        if m := re.match(r"^[-*]\s+(.+)$", line):
            close_para()
            if in_list != "ul":
                close_list()
                out_lines.append("<ul>")
                in_list = "ul"
            out_lines.append(f"<li>{inline(m.group(1))}</li>")
            continue
        if m := re.match(r"^\d+\.\s+(.+)$", line):
            close_para()
            if in_list != "ol":
                close_list()
                out_lines.append("<ol>")
                in_list = "ol"
            out_lines.append(f"<li>{inline(m.group(1))}</li>")
            continue
        # Blank line → close paragraph
        if not line.strip():
            close_para(); close_list()
            if in_tldr:
                out_lines.append("</div>")
                in_tldr = False
            continue
        # HR
        if re.match(r"^-{3,}$", line):
            close_para(); close_list()
            out_lines.append("<hr>")
            continue
        # Paragraph
        if not in_para:
            out_lines.append("<p>")
            in_para = True
        out_lines.append(inline(line))

    close_para(); close_list()
    if in_tldr:
        out_lines.append("</div>")
    return "\n".join(out_lines)


def seo_block(meta: dict, faq: list[dict], hero_url: str | None = None) -> str:
    canonical = meta.get("canonical", BASE_URL)
    title = meta.get("title", "myfinancial")
    desc = meta.get("description", "")
    keywords = ", ".join(meta.get("keywords") or [])
    schema_article = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": desc,
        "author": {"@type": "Person", "name": "Nithin",
                   "jobTitle": "Certified Financial Planner",
                   "url": "https://myfinancial.in"},
        "publisher": {"@type": "Organization", "name": "myfinancial.in",
                      "url": "https://myfinancial.in"},
        "datePublished": meta.get("date"),
        "dateModified": meta.get("date"),
        "mainEntityOfPage": canonical,
    }
    if hero_url:
        schema_article["image"] = hero_url
    schema_faq = None
    if faq:
        schema_faq = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": f["q"],
                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                for f in faq
            ],
        }
    schema_json = (json.dumps(schema_article)
                   + ("\n" + json.dumps(schema_faq) if schema_faq else ""))
    og_image = (
        f'<meta property="og:image" content="{html.escape(hero_url)}">\n'
        f'<meta name="twitter:image" content="{html.escape(hero_url)}">\n'
        if hero_url else ""
    )
    return (
        f'<title>{html.escape(title)}</title>\n'
        f'<meta name="description" content="{html.escape(desc)}">\n'
        f'<meta name="keywords" content="{html.escape(keywords)}">\n'
        f'<meta name="author" content="Nithin (CFP)">\n'
        f'<link rel="canonical" href="{canonical}">\n'
        f'<meta property="og:title" content="{html.escape(title)}">\n'
        f'<meta property="og:description" content="{html.escape(desc)}">\n'
        f'<meta property="og:url" content="{canonical}">\n'
        f'<meta property="og:type" content="article">\n'
        f'{og_image}'
        f'<meta name="twitter:card" content="summary_large_image">\n'
        f'<script type="application/ld+json">{schema_json}</script>'
    )


def render_article(md_path: Path) -> dict:
    fm, body = parse_frontmatter(md_path.read_text())
    faq, hero_url, hero_local, fact_check = [], None, None, None
    if META.exists():
        try:
            m = json.loads(META.read_text())
            faq = m.get("faq", [])
            if m.get("slug") == (fm.get("slug") or md_path.stem):
                hero_url = m.get("hero_url")
                hero_local = m.get("hero_local")
                fact_check = m.get("fact_check")
        except Exception:
            pass
    html_body = md_to_html(body)
    seo = seo_block(fm, faq, hero_url=hero_url)
    slug = fm.get("slug") or md_path.stem
    out_dir = OUT / "articles" / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    # If hero exists in output already, show it
    hero_html = ""
    if (out_dir / "hero.jpg").exists():
        hero_html = (
            '<figure class="hero">'
            '<img src="hero.jpg" alt="" loading="eager">'
            '</figure>'
        )

    fc_badge = ""
    if fact_check and fact_check.get("verdict") in ("ship", "review", "rewrite"):
        verdict = fact_check["verdict"]
        label = {"ship": "Fact-checked",
                 "review": "Review",
                 "rewrite": "Needs revision"}[verdict]
        fc_badge = f'<span class="fc {verdict}" title="{html.escape(fact_check.get("summary", ""))}">✓ {label}</span>'

    page = (HEAD.format(css=CSS, seo=seo)
            + '<article class="wrap">'
            + hero_html
            + (f'<div class="byline">By {fm.get("author", "Nithin")} · {fm.get("date", "")}{fc_badge}</div>'
               if fm.get("date") else "")
            + html_body
            + "</article>" + FOOTER)
    (out_dir / "index.html").write_text(page)
    return {"slug": slug, "title": fm.get("title", slug),
            "date": fm.get("date", ""),
            "description": fm.get("description", ""),
            "has_hero": bool(hero_html)}


def render_index(articles: list[dict]) -> None:
    def card(a: dict) -> str:
        thumb = (f'<a class="thumb" href="articles/{a["slug"]}/">'
                 f'<img src="articles/{a["slug"]}/hero.jpg" alt="" loading="lazy">'
                 f'</a>') if a.get("has_hero") else ""
        return (
            f'<div class="list-item">'
            f'{thumb}'
            f'<h3><a href="articles/{a["slug"]}/">{html.escape(a["title"])}</a></h3>'
            f'<div class="meta">{a.get("date", "")}</div>'
            f'<p>{html.escape(a.get("description", ""))}</p>'
            f'</div>'
        )
    items = "\n".join(
        card(a) for a in sorted(articles, key=lambda x: x.get("date", ""),
                                 reverse=True)
    )
    seo = seo_block({"title": "myfinancial.in · Insights for 15L+ earners and NRIs",
                     "description": "Personal-finance explainers, tax guides, and NRI planning by a Certified Financial Planner.",
                     "canonical": BASE_URL, "date": dt.date.today().isoformat()},
                    [])
    page = (HEAD.format(css=CSS, seo=seo)
            + '<div class="wrap"><h1>Latest insights</h1>' + items
            + "</div>" + FOOTER)
    (OUT / "index.html").write_text(page)


def render_sitemap(articles: list[dict]) -> None:
    urls = [f"{BASE_URL}/"] + [f"{BASE_URL}/articles/{a['slug']}/" for a in articles]
    today = dt.date.today().isoformat()
    body = "\n".join(
        f"<url><loc>{u}</loc><lastmod>{today}</lastmod></url>" for u in urls
    )
    (OUT / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}\n</urlset>'
    )
    (OUT / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n"
    )


def copy_static() -> None:
    """Copy anything in static/ into output/ as-is."""
    if not STATIC.exists():
        return
    import shutil
    for src in STATIC.iterdir():
        if src.is_file():
            shutil.copy2(src, OUT / src.name)
        elif src.is_dir():
            shutil.copytree(src, OUT / src.name, dirs_exist_ok=True)


def main() -> int:
    OUT.mkdir(exist_ok=True)
    copy_static()
    md_files = sorted(ARTS.glob("*.md"))
    if not md_files:
        print("No articles in articles/ — run write_article.py first")
        return 1
    rendered = [render_article(p) for p in md_files]
    render_index(rendered)
    render_sitemap(rendered)
    print(f"Rendered {len(rendered)} article(s) → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
