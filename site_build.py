"""Unified tabbed-site builder for myfinancial.in.

Aggregates every content source into ONE GitHub Pages site with a sticky
top-nav of tabs:

  Root  articles/*.md            → split by frontmatter `category` into tabs
  sources/daily-fno-pulse/articles → "F&O Pulse"
  sources/business-mavericks/articles → "Business Mavericks"
  sources/market-pulse/articles    → "Market Pulse"   (written by page_export)
  sources/news/articles            → "News"           (written by page_export)

Outputs (into output/):
  output/index.html                  — landing page, latest across all tabs
  output/<tab>/index.html            — one listing page per tab
  output/articles/<slug>/index.html  — clean URL per article (+ hero.jpg)
  output/sitemap.xml, output/robots.txt

Pure stdlib — no external deps. Supersedes the per-source publish.py for the
purpose of building the public site; each source pipeline only needs to drop
its markdown into its own articles/ folder.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import shutil
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "output"
STATIC = HERE / "static"

BASE_URL = "https://myfinancialria.github.io/myfinancial-content"

# ---------------------------------------------------------------------------
# Tab configuration
# ---------------------------------------------------------------------------
# Ordered nav. `key` is the URL segment (empty for home). Content-category tabs
# match on frontmatter `category`; source tabs match on the source folder.
CONTENT_CAT_TAB = {
    "personal_finance": "personal-finance",
    "macro": "macro",
    "result_analysis": "results",
    "pre_market": "pre-market",
    "post_market": "market-wrap",
    "explainer": "explained",
}
CONTENT_FALLBACK_TAB = "personal-finance"

TABS = [
    {"key": "", "label": "Latest"},
    {"key": "personal-finance", "label": "Personal Finance"},
    {"key": "macro", "label": "Macro & Markets"},
    {"key": "results", "label": "Result Analysis"},
    {"key": "pre-market", "label": "Pre-Market"},
    {"key": "market-wrap", "label": "Market Wrap"},
    {"key": "explained", "label": "Explained"},
    {"key": "fno-pulse", "label": "F&O Pulse"},
    {"key": "mavericks", "label": "Business Mavericks"},
    {"key": "market-pulse", "label": "Market Pulse"},
    {"key": "news", "label": "News"},
]
TAB_LABEL = {t["key"]: t["label"] for t in TABS}
TAB_BLURB = {
    "": "Personal-finance explainers, market briefs, F&O positioning and business stories — all in one place.",
    "personal-finance": "Tax, investing and money guides for 15L+ earners and NRIs.",
    "macro": "What global and Indian macro means for your portfolio.",
    "results": "Plain-English reads of company earnings and sector moves.",
    "pre-market": "What to know before the Indian market opens.",
    "market-wrap": "How the session played out, in two minutes.",
    "explained": "Markets and money concepts, explained simply.",
    "fno-pulse": "End-of-day options & futures positioning — PCR, max pain, FII flows.",
    "mavericks": "The rise, fall and comeback stories behind India's biggest businesses.",
    "market-pulse": "Pre-market, post-market and commodities snapshots.",
    "news": "Results calendar, corporate actions, FII/DII flows and the news that moves markets.",
}

# Each source: (source_key, articles_dir, hero_dir_template)
# hero_dir_template: a dir holding <slug>/hero.{jpg,png} to copy, or None.
SOURCES = [
    ("content", HERE / "articles", HERE / "output" / "articles"),
    ("fno", HERE / "sources" / "daily-fno-pulse" / "articles", None),
    ("mavericks", HERE / "sources" / "business-mavericks" / "articles",
     HERE / "sources" / "business-mavericks" / "output"),
    ("market-pulse", HERE / "sources" / "market-pulse" / "articles",
     HERE / "sources" / "market-pulse" / "output"),
    ("news", HERE / "sources" / "news" / "articles", None),
]

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
CSS = """
:root { --navy:#0B2545; --green:#16A34A; --red:#DC2626; --grey:#6B7280; --bg:#F8FAFC; --card:#FFFFFF; --grid:#E5E7EB; --accent:#1D4ED8; }
* { box-sizing:border-box; }
body { font-family:'Inter',system-ui,-apple-system,sans-serif; background:var(--bg); color:var(--navy); margin:0; padding:0; line-height:1.65; -webkit-font-smoothing:antialiased; }
.wrap { max-width:760px; margin:0 auto; padding:40px 22px 80px; }
header.site { display:flex; justify-content:space-between; align-items:center; padding:16px 22px; border-bottom:1px solid var(--grid); background:#fff; }
header.site a.brand { color:var(--navy); font-weight:800; text-decoration:none; font-size:18px; }
header.site .meta { color:var(--grey); font-size:13px; }
nav.tabs { position:sticky; top:0; z-index:10; background:#fff; border-bottom:1px solid var(--grid); overflow-x:auto; -webkit-overflow-scrolling:touch; white-space:nowrap; }
nav.tabs .inner { display:inline-flex; gap:4px; padding:0 14px; }
nav.tabs a { display:inline-block; padding:13px 14px; color:var(--grey); text-decoration:none; font-size:14px; font-weight:600; border-bottom:2px solid transparent; }
nav.tabs a:hover { color:var(--navy); }
nav.tabs a.active { color:var(--accent); border-bottom-color:var(--accent); }
h1.page { font-size:30px; font-weight:800; letter-spacing:-0.02em; margin:0 0 6px; }
.blurb { color:var(--grey); font-size:15px; margin:0 0 24px; }
article h1 { font-size:34px; line-height:1.2; margin:0 0 8px; font-weight:800; letter-spacing:-0.02em; }
article .byline { color:var(--grey); font-size:14px; margin-bottom:30px; }
article h2 { font-size:24px; margin:38px 0 14px; font-weight:700; letter-spacing:-0.01em; }
article h3 { font-size:18px; margin:24px 0 10px; font-weight:700; color:#1E293B; }
article p { margin:10px 0; font-size:17px; }
article ul, article ol { padding-left:24px; }
article li { margin:6px 0; font-size:17px; }
article strong { font-weight:600; }
article a { color:var(--accent); text-decoration:none; border-bottom:1px solid #BFDBFE; }
article a:hover { background:#EFF6FF; }
article blockquote { border-left:3px solid var(--grid); margin:14px 0; padding:6px 14px; color:var(--grey); }
article code { background:#F1F5F9; padding:2px 6px; border-radius:4px; font-size:15px; }
article pre { background:#0B2545; color:#E2E8F0; padding:14px 16px; border-radius:10px; overflow-x:auto; font-size:14px; }
article pre code { background:none; padding:0; color:inherit; }
article hr { border:none; border-top:1px solid var(--grid); margin:28px 0; }
article table { border-collapse:collapse; width:100%; margin:18px 0; font-size:15px; }
article th, article td { border:1px solid var(--grid); padding:8px 10px; text-align:left; }
article th { background:#F1F5F9; }
article figure.hero { margin:0 0 28px; border-radius:14px; overflow:hidden; aspect-ratio:16/9; background:#E2E8F0; }
article figure.hero img { width:100%; height:100%; object-fit:cover; display:block; }
.tldr { background:#FFFBEB; border-left:3px solid #F59E0B; padding:16px 18px; border-radius:6px; margin:24px 0; }
.tldr p:first-child { font-weight:700; margin-top:0; color:#92400E; }
.list-item { padding:18px 0; border-bottom:1px solid var(--grid); }
.list-item .thumb { display:block; width:100%; aspect-ratio:16/9; border-radius:10px; overflow:hidden; background:#E2E8F0; margin-bottom:10px; }
.list-item .thumb img { width:100%; height:100%; object-fit:cover; display:block; }
.list-item h3 { margin:0 0 6px; font-size:20px; }
.list-item h3 a { color:var(--navy); border:none; text-decoration:none; }
.list-item .meta { color:var(--grey); font-size:13px; }
.list-item .meta .cat { color:var(--accent); font-weight:600; }
.empty { color:var(--grey); font-size:15px; padding:30px 0; }
footer.site { text-align:center; color:var(--grey); font-size:13px; padding:36px 22px; border-top:1px solid var(--grid); margin-top:48px; }
@media (max-width: 640px) { .wrap { padding:26px 18px 60px; } article h1 { font-size:28px; } article h2 { font-size:21px; } article p, article li { font-size:16px; } h1.page { font-size:25px; } }
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
<header class="site"><a class="brand" href="{home}">myfinancial.in</a><span class="meta">Personal finance · markets · for 15L+ earners and NRIs</span></header>
<nav class="tabs"><div class="inner">{nav}</div></nav>
"""

FOOTER = """<footer class="site">© myfinancial.in · <em>For Indians who'd rather understand than be sold to.</em> · <a href="https://myfinancial.in" style="color:inherit;">myfinancial.in</a></footer>
</body></html>
"""


# ---------------------------------------------------------------------------
# Markdown + frontmatter (shared with the legacy publish.py renderer)
# ---------------------------------------------------------------------------
def parse_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n([\s\S]+?)\n---\n+", text)
    if not m:
        return {}, text
    fm_raw, body = m.group(1), text[m.end():]
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
    """Lightweight Markdown → HTML. Headings, lists, tables, code fences,
    blockquotes, TL;DR callout, inline emphasis/links."""
    out, in_list, in_para, in_tldr, in_code = [], None, False, False, False
    code_buf: list[str] = []
    table_buf: list[str] = []

    def close_para():
        nonlocal in_para
        if in_para:
            out.append("</p>"); in_para = False

    def close_list():
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>"); in_list = None

    def close_tldr():
        nonlocal in_tldr
        if in_tldr:
            out.append("</div>"); in_tldr = False

    def flush_table():
        if not table_buf:
            return
        rows = [r for r in table_buf if r.strip()]
        table_buf.clear()
        if len(rows) < 2:
            for r in rows:
                out.append(f"<p>{inline(r)}</p>")
            return
        def cells(r):
            return [c.strip() for c in r.strip().strip("|").split("|")]
        head = cells(rows[0])
        body_rows = rows[2:]
        out.append("<table><thead><tr>"
                   + "".join(f"<th>{inline(c)}</th>" for c in head)
                   + "</tr></thead><tbody>")
        for r in body_rows:
            out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells(r)) + "</tr>")
        out.append("</tbody></table>")

    def inline(s: str) -> str:
        s = html.escape(s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                   r'<a href="\2" rel="noopener" target="_blank">\1</a>', s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
        s = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"<em>\1</em>", s)
        return s

    for raw in md.splitlines():
        line = raw.rstrip()
        # Code fences
        if line.strip().startswith("```"):
            if in_code:
                out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
                code_buf.clear(); in_code = False
            else:
                close_para(); close_list(); close_tldr(); flush_table()
                in_code = True
            continue
        if in_code:
            code_buf.append(raw)
            continue
        # Tables (lines starting with |)
        if line.strip().startswith("|"):
            close_para(); close_list(); close_tldr()
            table_buf.append(line)
            continue
        elif table_buf:
            flush_table()
        # Headings
        if m := re.match(r"^(#{1,6})\s+(.+)$", line):
            close_para(); close_list(); close_tldr()
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
            continue
        if "**TL;DR**" in line.strip():
            close_para(); close_list()
            out.append('<div class="tldr"><p>TL;DR</p>'); in_tldr = True
            continue
        if m := re.match(r"^[-*]\s+(.+)$", line):
            close_para()
            if in_list != "ul":
                close_list(); out.append("<ul>"); in_list = "ul"
            out.append(f"<li>{inline(m.group(1))}</li>")
            continue
        if m := re.match(r"^\d+\.\s+(.+)$", line):
            close_para()
            if in_list != "ol":
                close_list(); out.append("<ol>"); in_list = "ol"
            out.append(f"<li>{inline(m.group(1))}</li>")
            continue
        if not line.strip():
            close_para(); close_list(); close_tldr()
            continue
        if re.match(r"^-{3,}$", line):
            close_para(); close_list(); close_tldr()
            out.append("<hr>")
            continue
        if not in_para:
            out.append("<p>"); in_para = True
        out.append(inline(line))

    flush_table(); close_para(); close_list(); close_tldr()
    if in_code:
        out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
    return "\n".join(out)


def seo_block(meta: dict, canonical: str) -> str:
    title = meta.get("title", "myfinancial.in")
    desc = meta.get("description", "")
    keywords = ", ".join(meta["keywords"]) if isinstance(meta.get("keywords"), list) else (meta.get("keywords") or "")
    hero_url = meta.get("hero_url")
    schema = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": title, "description": desc,
        "author": {"@type": "Organization", "name": "myfinancial", "url": "https://myfinancial.in"},
        "publisher": {"@type": "Organization", "name": "myfinancial", "url": "https://myfinancial.in"},
        "datePublished": meta.get("date"), "dateModified": meta.get("date"),
        "mainEntityOfPage": canonical,
    }
    if hero_url:
        schema["image"] = hero_url
    og_image = (f'<meta property="og:image" content="{html.escape(hero_url)}">\n'
                f'<meta name="twitter:image" content="{html.escape(hero_url)}">\n') if hero_url else ""
    return (
        f'<title>{html.escape(title)}</title>\n'
        f'<meta name="description" content="{html.escape(desc)}">\n'
        f'<meta name="keywords" content="{html.escape(keywords)}">\n'
        f'<meta name="author" content="MyFinancial">\n'
        f'<link rel="canonical" href="{canonical}">\n'
        f'<meta property="og:title" content="{html.escape(title)}">\n'
        f'<meta property="og:description" content="{html.escape(desc)}">\n'
        f'<meta property="og:url" content="{canonical}">\n'
        f'<meta property="og:type" content="article">\n'
        f'{og_image}'
        f'<meta name="twitter:card" content="summary_large_image">\n'
        f'<script type="application/ld+json">{json.dumps(schema)}</script>'
    )


def build_nav(prefix: str, active: str) -> str:
    parts = []
    for t in TABS:
        href = prefix + (t["key"] + "/" if t["key"] else "")
        cls = " class=\"active\"" if t["key"] == active else ""
        parts.append(f'<a href="{href}"{cls}>{html.escape(t["label"])}</a>')
    return "".join(parts)


# ---------------------------------------------------------------------------
# Collection + rendering
# ---------------------------------------------------------------------------
def tab_for(source: str, category: str | None) -> str:
    if source == "content":
        return CONTENT_CAT_TAB.get((category or "").strip(), CONTENT_FALLBACK_TAB)
    return {"fno": "fno-pulse", "mavericks": "mavericks",
            "market-pulse": "market-pulse", "news": "news"}[source]


def copy_hero(slug: str, hero_dir: Path | None, out_dir: Path) -> bool:
    """Copy a source hero image into the article output dir as hero.jpg."""
    if (out_dir / "hero.jpg").exists():
        return True  # content heroes already live in output/
    if not hero_dir:
        return False
    src_dir = hero_dir / slug
    for name in ("hero.jpg", "hero.png", "hero.jpeg", "hero.webp"):
        cand = src_dir / name
        if cand.exists():
            shutil.copy2(cand, out_dir / "hero.jpg")
            return True
    return False


def render_article(md_path: Path, source: str, hero_dir: Path | None) -> dict:
    fm, body = parse_frontmatter(md_path.read_text())
    slug = fm.get("slug") or md_path.stem
    category = fm.get("category")
    tab = tab_for(source, category)
    out_dir = OUT / "articles" / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    has_hero = copy_hero(slug, hero_dir, out_dir)
    hero_html = ('<figure class="hero"><img src="hero.jpg" alt="" loading="eager"></figure>'
                 if has_hero else "")

    canonical = fm.get("canonical") or f"{BASE_URL}/articles/{slug}/"
    seo = seo_block(fm, canonical)
    nav = build_nav("../../", tab)
    tab_label = TAB_LABEL.get(tab, "")
    byline = ""
    if fm.get("date"):
        byline = f'<div class="byline">{html.escape(tab_label)} · {fm.get("date")}</div>'

    page = (HEAD.format(css=CSS, seo=seo, home="../../", nav=nav)
            + '<article class="wrap">' + hero_html + byline
            + md_to_html(body) + "</article>" + FOOTER)
    (out_dir / "index.html").write_text(page)

    return {"slug": slug, "title": fm.get("title", slug), "date": fm.get("date", ""),
            "description": fm.get("description", ""), "category": category,
            "source": source, "tab": tab, "has_hero": has_hero}


def list_card(a: dict, prefix: str) -> str:
    thumb = (f'<a class="thumb" href="{prefix}articles/{a["slug"]}/">'
             f'<img src="{prefix}articles/{a["slug"]}/hero.jpg" alt="" loading="lazy"></a>'
             ) if a.get("has_hero") else ""
    label = TAB_LABEL.get(a["tab"], "")
    return (
        f'<div class="list-item">{thumb}'
        f'<h3><a href="{prefix}articles/{a["slug"]}/">{html.escape(a["title"])}</a></h3>'
        f'<div class="meta"><span class="cat">{html.escape(label)}</span> · {a.get("date", "")}</div>'
        f'<p>{html.escape(a.get("description", ""))}</p></div>'
    )


def render_listing(tab_key: str, articles: list[dict]) -> None:
    is_home = tab_key == ""
    prefix = "" if is_home else "../"
    nav = build_nav(prefix, tab_key)
    label = "Latest insights" if is_home else TAB_LABEL[tab_key]
    blurb = TAB_BLURB.get(tab_key, "")
    arts = sorted(articles, key=lambda x: x.get("date", ""), reverse=True)
    if is_home:
        arts = arts[:60]
    items = "\n".join(list_card(a, prefix) for a in arts) or '<p class="empty">No articles here yet — check back soon.</p>'
    seo = seo_block(
        {"title": f"{label} · myfinancial.in", "description": blurb,
         "date": dt.date.today().isoformat()},
        BASE_URL + ("/" if is_home else f"/{tab_key}/"))
    page = (HEAD.format(css=CSS, seo=seo, home=prefix or "./", nav=nav)
            + f'<div class="wrap"><h1 class="page">{html.escape(label)}</h1>'
            + (f'<p class="blurb">{html.escape(blurb)}</p>' if blurb else "")
            + items + "</div>" + FOOTER)
    out_path = OUT / "index.html" if is_home else OUT / tab_key / "index.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page)


def render_sitemap(articles: list[dict]) -> None:
    urls = [f"{BASE_URL}/"]
    urls += [f"{BASE_URL}/{t['key']}/" for t in TABS if t["key"]]
    urls += [f"{BASE_URL}/articles/{a['slug']}/" for a in articles]
    today = dt.date.today().isoformat()
    body = "\n".join(f"<url><loc>{u}</loc><lastmod>{today}</lastmod></url>" for u in urls)
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + body + "\n</urlset>")
    (OUT / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n")


def copy_static() -> None:
    if not STATIC.exists():
        return
    for src in STATIC.iterdir():
        if src.is_file():
            shutil.copy2(src, OUT / src.name)
        elif src.is_dir():
            shutil.copytree(src, OUT / src.name, dirs_exist_ok=True)


def main() -> int:
    OUT.mkdir(exist_ok=True)
    copy_static()

    all_articles: list[dict] = []
    for source, arts_dir, hero_dir in SOURCES:
        if not arts_dir.exists():
            continue
        for md in sorted(arts_dir.glob("*.md")):
            if md.stem == "sample":
                continue
            try:
                all_articles.append(render_article(md, source, hero_dir))
            except Exception as e:  # one bad article shouldn't kill the build
                print(f"  ! failed {md}: {e}")

    # Home + one listing per tab
    render_listing("", all_articles)
    for t in TABS:
        if not t["key"]:
            continue
        render_listing(t["key"], [a for a in all_articles if a["tab"] == t["key"]])

    render_sitemap(all_articles)

    by_tab: dict[str, int] = {}
    for a in all_articles:
        by_tab[a["tab"]] = by_tab.get(a["tab"], 0) + 1
    print(f"Rendered {len(all_articles)} articles across {len(by_tab)} tabs → {OUT}")
    for t in TABS:
        if t["key"]:
            print(f"  {t['label']:<22} {by_tab.get(t['key'], 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
