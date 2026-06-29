"""Render the day's article + the running index as plain HTML for GitHub Pages.

Minimal — no Jekyll, no Hugo, no JS framework. Just clean readable HTML.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
ARTS = HERE / "articles"
OUT = HERE / "output"
OUT.mkdir(exist_ok=True)


CSS = """
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:780px;margin:2em auto;padding:0 1.2em;line-height:1.65;color:#222}
header{border-bottom:2px solid #eee;padding-bottom:.6em;margin-bottom:1.4em}
header a{color:#0a4a8a;text-decoration:none;font-weight:600}
h1{color:#0a2540;font-size:1.7em;line-height:1.25;margin-top:.2em}
h2{color:#0a2540;margin-top:1.8em;border-left:4px solid #0a4a8a;padding-left:.5em}
h3{color:#264363}
code{background:#f4f4f6;padding:1px 5px;border-radius:3px;font-size:.92em}
blockquote{border-left:4px solid #d4d4d4;padding-left:1em;color:#555;font-style:italic;background:#fafafa;margin-left:0}
table{border-collapse:collapse;width:100%;margin:1em 0;font-size:.95em}
th,td{border:1px solid #ddd;padding:.5em .7em;text-align:left}
th{background:#f4f6f9}
.meta{color:#666;font-size:.85em;margin-bottom:1em}
.footer{margin-top:3em;padding-top:1em;border-top:1px solid #eee;color:#666;font-size:.85em}
a{color:#0a4a8a}
ul,ol{padding-left:1.4em}
"""


def md_to_html(md: str) -> str:
    """Tiny markdown→HTML. Handles headings, paragraphs, lists, blockquotes,
    bold, italic, code, links. Good enough for our generated articles; we're
    not parsing arbitrary user content."""
    lines = md.splitlines()
    html = []
    in_list = False
    in_quote = False
    in_para = []

    def flush_para():
        nonlocal in_para
        if in_para:
            text = " ".join(in_para).strip()
            if text:
                html.append("<p>" + inline(text) + "</p>")
            in_para = []

    def flush_list():
        nonlocal in_list
        if in_list:
            html.append("</ul>")
            in_list = False

    def flush_quote():
        nonlocal in_quote
        if in_quote:
            html.append("</blockquote>")
            in_quote = False

    def inline(s: str) -> str:
        # links
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        # bold + italic
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
        # inline code
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        return s

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush_para(); flush_list(); flush_quote()
            continue

        if line.startswith("# "):
            flush_para(); flush_list(); flush_quote()
            html.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.startswith("## "):
            flush_para(); flush_list(); flush_quote()
            html.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("### "):
            flush_para(); flush_list(); flush_quote()
            html.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("> "):
            flush_para(); flush_list()
            if not in_quote:
                html.append("<blockquote>"); in_quote = True
            html.append(f"<p>{inline(line[2:])}</p>")
        elif re.match(r"^[-*]\s+", line):
            flush_para(); flush_quote()
            if not in_list:
                html.append("<ul>"); in_list = True
            item_text = re.sub(r"^[-*]\s+", "", line)
            html.append(f"<li>{inline(item_text)}</li>")
        else:
            flush_list(); flush_quote()
            in_para.append(line)
    flush_para(); flush_list(); flush_quote()
    return "\n".join(html)


def parse_front_matter(md: str):
    if not md.startswith("---"):
        return {}, md
    end = md.find("---", 3)
    if end < 0:
        return {}, md
    front_raw = md[3:end].strip()
    body = md[end+3:].lstrip()
    meta = {}
    for line in front_raw.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def render_article(md_path: Path) -> Path:
    md = md_path.read_text()
    meta, body = parse_front_matter(md)
    slug = meta.get("slug", md_path.stem)
    title = meta.get("title", slug)
    date = meta.get("date", "")
    desc = meta.get("description", "")
    body_html = md_to_html(body)
    page = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<style>{CSS}</style>
</head><body>
<header><a href="../index.html">← Daily F&O Pulse</a></header>
<div class="meta">Published {date} · educational interpretation, not investment advice</div>
{body_html}
<div class="footer">myfinancial · F&O pulse · data: NSE, BSE, Fyers</div>
</body></html>"""
    out_dir = OUT / "articles" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(page)
    return out_path


def render_index():
    items = []
    for md in sorted(ARTS.glob("*.md"), reverse=True):
        meta, _ = parse_front_matter(md.read_text())
        items.append({
            "slug": meta.get("slug", md.stem),
            "title": meta.get("title", md.stem),
            "date": meta.get("date", ""),
            "description": meta.get("description", ""),
        })
    cards = "\n".join(
        f'<article><h2><a href="articles/{i["slug"]}/">{i["title"]}</a></h2>'
        f'<div class="meta">{i["date"]}</div><p>{i["description"]}</p></article>'
        for i in items[:60]
    )
    home = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily F&O Pulse — India</title>
<meta name="description" content="End-of-day interpretation of Indian F&O open interest, futures positioning, and FII flows. Educational, jargon-light, every weekday.">
<style>{CSS}</style>
</head><body>
<header><h1>Daily F&amp;O Pulse — India</h1>
<div class="meta">Auto-published every weekday at 18:30 IST. Data from NSE, BSE, Fyers. Educational, not investment advice.</div></header>
{cards if cards else "<p>No articles published yet.</p>"}
<div class="footer">myfinancial · open-source pipeline · <a href="https://github.com/myfinancialria/daily-fno-pulse">source on GitHub</a></div>
</body></html>"""
    (OUT / "index.html").write_text(home)


def main(date_str: str | None = None):
    if date_str is None:
        date_str = dt.date.today().isoformat()
    md_path = ARTS / f"{date_str}-fno-pulse.md"
    if not md_path.exists():
        print(f"missing {md_path}", file=sys.stderr); return 1
    out = render_article(md_path)
    render_index()
    print(f"Rendered {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*([sys.argv[1]] if len(sys.argv) > 1 else [])))
