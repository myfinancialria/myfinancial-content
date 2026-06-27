"""Generate LinkedIn share assets for published articles.

For each article (a markdown file under articles/) this produces, under
output/linkedin/<slug>/:

  1. poster.jpg   — a 9:16 (1080x1920) LinkedIn poster: an AI-generated
                    background with the article HEADING and TL;DR bullets
                    overlaid as crisp, always-legible text + brand framing.
  2. caption.txt  — a one-paragraph, very-simple-English caption to paste
                    when sharing / reposting the article on LinkedIn,
                    followed by the article link and a few hashtags.
  3. meta.json    — heading, tldr bullets, caption, paths (for tooling).

Then an index page output/linkedin/index.html lists every day's assets so
you can grab the image + caption in one click and post to LinkedIn manually.

Design choices (consistent with the rest of this repo):
  - Background image: Pollinations.ai FLUX, free + no API key (same engine
    as generate_image.py), requested at 9:16. We do NOT rely on the image
    model to render text — text-to-image models render text unreliably, so
    the heading/TL;DR are drawn with Pillow on top for guaranteed legibility.
  - Caption + background prompt: the shared LLM in llm.py. Both have
    deterministic fallbacks so the script still produces a usable poster
    even with no LLM key / no network for the LLM (Pollinations only).

CLI:
  python linkedin_poster.py                 # all of today's (UTC) articles
  python linkedin_poster.py --date 2026-06-27
  python linkedin_poster.py --slug 2026-06-27-macro-...-guide
  python linkedin_poster.py --category macro
  python linkedin_poster.py --force         # rebuild even if poster exists
Env:
  FORCE=1   same as --force
  POSTER_DATE=YYYY-MM-DD   same as --date (handy in CI)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import textwrap
import urllib.parse
from pathlib import Path
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = Path(__file__).parent
ARTICLES = HERE / "articles"
OUT = HERE / "output" / "linkedin"
FONTS = HERE / "assets" / "fonts"

# 9:16 portrait — LinkedIn vertical poster.
W, H = 1080, 1920

# Brand palette (matches site CSS: --navy, amber accent).
NAVY = (11, 37, 69)        # #0B2545
NAVY_DEEP = (6, 22, 43)    # darker scrim base
AMBER = (245, 158, 11)     # #F59E0B
OFF_WHITE = (248, 250, 252)
WHITE = (255, 255, 255)
MUTED = (203, 213, 225)    # slate-300

CATEGORY_LABELS = {
    "macro": "MACRO",
    "personal_finance": "PERSONAL FINANCE",
    "result_analysis": "RESULTS",
    "explainer": "EXPLAINER",
    "pre_market": "PRE-MARKET",
    "post_market": "POST-MARKET",
}

# --- LLM (shared with the rest of the pipeline; optional) -------------------
try:
    from llm import call_llm as _call_llm
except Exception:  # pragma: no cover - llm.py should always be importable
    _call_llm = None


# --------------------------------------------------------------------------- #
# Parsing: heading + TL;DR out of the article markdown
# --------------------------------------------------------------------------- #
def parse_front_matter(text: str) -> dict:
    """Return the YAML-ish front-matter as a flat dict (string values)."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    fm: dict = {}
    if not m:
        return fm
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        fm[key.strip()] = val.strip().strip('"').strip("'")
    return fm


def extract_heading_and_tldr(md_path: Path) -> tuple[str, list[str], dict]:
    """Return (heading, tldr_bullets, front_matter) for an article file."""
    text = md_path.read_text(encoding="utf-8")
    fm = parse_front_matter(text)

    # Heading: first H1 if present, else front-matter title.
    h1 = re.search(r"^#\s+(.+?)\s*$", text, re.M)
    heading = (h1.group(1) if h1 else fm.get("title", "")).strip()

    # TL;DR: the block after a "**TL;DR**" (or "## TL;DR") marker, collecting
    # the consecutive "- " / "* " bullets until the next blank-then-heading.
    bullets: list[str] = []
    tldr = re.search(r"(?im)^\s*(?:\*\*TL;DR\*\*|#+\s*TL;DR)\s*$", text)
    if tldr:
        rest = text[tldr.end():]
        for line in rest.splitlines():
            s = line.strip()
            if not s:
                if bullets:           # blank line after bullets ends the block
                    break
                continue
            mb = re.match(r"^[-*]\s+(.*)$", s)
            if mb:
                bullets.append(mb.group(1).strip())
            elif bullets or s.startswith("#"):
                break                 # hit prose / next heading
    # Fallback: split the front-matter description into 1-2 "bullets".
    if not bullets:
        desc = fm.get("description", "").strip().rstrip(".")
        if desc:
            parts = re.split(r"(?<=[.!?])\s+", desc)
            bullets = [p.strip() for p in parts if p.strip()][:3]

    # Tidy markdown emphasis out of bullets.
    bullets = [re.sub(r"\*\*?|__", "", b).strip() for b in bullets]
    return heading, bullets, fm


# --------------------------------------------------------------------------- #
# Background image (Pollinations FLUX, 9:16) + prompt
# --------------------------------------------------------------------------- #
BG_SYSTEM = (
    "You design editorial illustration backgrounds for myfinancial.in, an "
    "Indian personal-finance publication for mass-affluent (15L+/yr) earners "
    "and NRIs. You write ONE text-to-image prompt."
)
BG_TEMPLATE = """Article heading: {heading}
Key points: {points}

Write ONE image prompt (28-42 words) for a VERTICAL 9:16 social poster background:
- Editorial-magazine illustration (NOT photo-real, NOT cartoon, NOT 3D). The Economist / The Ken cover style.
- One clear visual metaphor for the topic. Specific and evocative.
- India context where natural; no clichés.
- Palette: deep navy blue background, muted gold accents, off-white.
- IMPORTANT: keep the LOWER 60% visually calm/dark/uncluttered (text overlay goes there). Put the subject in the UPPER third.
- Absolutely NO text, NO numbers, NO letters, NO logos, NO watermarks.
- Soft cinematic lighting, sharp focus, high contrast, lots of negative space.
Output JUST the prompt as one paragraph. No preamble, no quotes."""

POLLINATIONS = "https://image.pollinations.ai/prompt/{prompt}"


def _fallback_bg_prompt(heading: str) -> str:
    return (
        f"Editorial magazine illustration symbolizing '{heading}', single "
        "central metaphor in the upper third, deep navy blue background with "
        "muted gold accents and off-white, calm dark uncluttered lower half, "
        "soft cinematic lighting, high contrast, generous negative space, "
        "no text no logos no watermark"
    )


def write_bg_prompt(heading: str, bullets: list[str]) -> str:
    if _call_llm is not None:
        try:
            txt = _call_llm(
                BG_TEMPLATE.format(heading=heading,
                                   points="; ".join(bullets[:3]) or "(none)"),
                BG_SYSTEM,
                temperature=0.9, max_tokens=2048, top_p=0.95,
                grounding=False, thinking_budget=0,
            )
            if txt and txt.strip():
                return txt.strip().strip('"').strip("'")
        except Exception as e:  # pragma: no cover
            print(f"  bg prompt LLM failed ({e}); using fallback", file=sys.stderr)
    return _fallback_bg_prompt(heading)


def fetch_background(prompt: str, slug: str) -> Optional[Image.Image]:
    encoded = urllib.parse.quote(prompt, safe="")
    # Deterministic seed per slug so re-runs are stable.
    seed = abs(hash(slug)) % 1_000_000
    url = (f"{POLLINATIONS.format(prompt=encoded)}"
           f"?width={W}&height={H}&seed={seed}&nologo=true&model=flux&enhance=true")
    try:
        r = requests.get(url, timeout=180)
        r.raise_for_status()
        if len(r.content) < 5000:
            print(f"  background suspiciously small ({len(r.content)} B)", file=sys.stderr)
            return None
        from io import BytesIO
        return Image.open(BytesIO(r.content)).convert("RGB")
    except Exception as e:
        print(f"  background fetch failed: {e}", file=sys.stderr)
        return None


def _gradient_background() -> Image.Image:
    """Deterministic navy gradient used when Pollinations is unavailable."""
    img = Image.new("RGB", (W, H), NAVY_DEEP)
    top, bot = NAVY, NAVY_DEEP
    px = img.load()
    for y in range(H):
        t = y / H
        col = tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3))
        for x in range(W):
            px[x, y] = col
    return img


# --------------------------------------------------------------------------- #
# Poster composition
# --------------------------------------------------------------------------- #
def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def _fit_heading(draw, text, font_path, max_w, start_size, min_size, max_lines):
    """Pick the largest size at which `text` wraps into <= max_lines."""
    for size in range(start_size, min_size - 1, -2):
        font = _font(font_path, size)
        # Greedy wrap by measured width.
        words, lines, cur = text.split(), [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if draw.textlength(trial, font=font) <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines:
            return font, lines
    return _font(font_path, min_size), lines  # best effort


def _draw_scrim(img: Image.Image) -> Image.Image:
    """Darken the lower portion so overlaid text is always legible."""
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    # Vertical gradient: transparent at top -> opaque navy at bottom 65%.
    start = int(H * 0.32)
    for y in range(start, H):
        t = (y - start) / (H - start)
        a = int(225 * (t ** 0.85))
        sd.line([(0, y), (W, y)], fill=(*NAVY_DEEP, min(a, 235)))
    # Solid top strip for the brand bar.
    sd.rectangle([0, 0, W, 150], fill=(*NAVY_DEEP, 200))
    return Image.alpha_composite(img.convert("RGBA"), scrim)


def compose_poster(bg: Image.Image, heading: str, bullets: list[str],
                   category: str, out_path: Path) -> None:
    # Cover-fit background to 9:16, then soften it: a light blur both makes
    # the overlaid text pop AND smears any stray garbled "text" the image
    # model rendered despite the no-text instruction (a known FLUX quirk).
    bg = _cover(bg, W, H).filter(ImageFilter.GaussianBlur(5))
    img = _draw_scrim(bg)
    d = ImageDraw.Draw(img)

    pad = 84
    # --- Brand bar -------------------------------------------------------- #
    d.text((pad, 50), "myfinancial.in", font=_font("Poppins-Bold.ttf", 44),
           fill=WHITE)
    cat = CATEGORY_LABELS.get(category, (category or "").upper().replace("_", " "))
    if cat:
        cf = _font("Poppins-SemiBold.ttf", 26)
        tw = d.textlength(cat, font=cf)
        d.rounded_rectangle([W - pad - tw - 36, 56, W - pad, 110],
                            radius=27, fill=AMBER)
        d.text((W - pad - tw - 18, 66), cat, font=cf, fill=NAVY_DEEP)

    # --- Heading + TL;DR laid out from the bottom up ---------------------- #
    bullet_font = _font("Poppins-Medium.ttf", 33)
    bullet_lh, bullet_gap = 42, 20
    # Wrap each bullet (cap to 3 bullets, <=2 lines each, clean ellipsis so a
    # bullet never gets chopped mid-thought).
    wrapped: list[list[str]] = []
    for b in bullets[:3]:
        wrapped.append(_wrap_clip(d, b, bullet_font, W - 2 * pad - 46, 3))

    bullets_h = sum(len(w) * bullet_lh + bullet_gap for w in wrapped)

    hfont, hlines = _fit_heading(d, heading, "Poppins-Bold.ttf",
                                 W - 2 * pad, 78, 46, 4)
    head_lh = hfont.size + 12
    head_h = len(hlines) * head_lh

    cta_h = 70
    block_h = head_h + 40 + bullets_h + 30 + cta_h
    y = H - 96 - block_h
    # Accent rule above the heading.
    d.rectangle([pad, y - 28, pad + 96, y - 18], fill=AMBER)

    # Heading.
    for ln in hlines:
        d.text((pad, y), ln, font=hfont, fill=WHITE)
        y += head_lh
    y += 40

    # TL;DR bullets with amber dot markers.
    for lines in wrapped:
        d.ellipse([pad, y + 13, pad + 16, y + 29], fill=AMBER)
        for i, ln in enumerate(lines):
            d.text((pad + 46, y), ln, font=bullet_font, fill=OFF_WHITE)
            y += bullet_lh
        y += bullet_gap

    # CTA footer.
    y = H - 96 - cta_h + 10
    d.text((pad, y), "Read the full story »", font=_font("Poppins-SemiBold.ttf", 34),
           fill=AMBER)
    d.text((pad, y + 44), "Personal finance for 15L+ earners & NRIs",
           font=_font("Poppins-Regular.ttf", 26), fill=MUTED)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, "JPEG", quality=90)
    print(f"  wrote {out_path.relative_to(HERE)}")


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Resize+crop to exactly cover w x h (like CSS background-size: cover)."""
    src_ratio, dst_ratio = img.width / img.height, w / h
    if src_ratio > dst_ratio:
        new_h = h
        new_w = int(h * src_ratio)
    else:
        new_w = w
        new_h = int(w / src_ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left, top = (new_w - w) // 2, (new_h - h) // 2
    return img.crop((left, top, left + w, top + h))


def _wrap(draw, text, font, max_w) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _wrap_clip(draw, text, font, max_w, max_lines) -> list[str]:
    """Wrap to at most max_lines; if it overflows, end the last line with '…'."""
    lines = _wrap(draw, text, font, max_w)
    if len(lines) <= max_lines:
        return lines
    lines = lines[:max_lines]
    last = lines[-1]
    while last and draw.textlength(last + "…", font=font) > max_w:
        last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
    last = _trim_trailing_stopwords(last)
    lines[-1] = last.rstrip(",;:- ") + "…"
    return lines


_STOPWORDS = {"and", "or", "the", "a", "an", "to", "of", "in", "on", "for",
              "with", "by", "as", "at", "is", "are", "was", "were", "that",
              "this", "their", "its", "from", "into", "over", "than", "but"}


def _trim_trailing_stopwords(s: str) -> str:
    """Drop trailing connector words so a clipped line doesn't end on 'by…'."""
    words = s.split()
    while len(words) > 2 and words[-1].lower().strip(",.;:") in _STOPWORDS:
        words.pop()
    return " ".join(words)


# --------------------------------------------------------------------------- #
# Caption (simple-English paragraph for the LinkedIn share)
# --------------------------------------------------------------------------- #
CAP_SYSTEM = (
    "You write LinkedIn captions for myfinancial.in. Audience: Indian "
    "salaried professionals and NRIs, many new to investing. Write in very "
    "simple, plain English a 12-year-old could follow. Warm, clear, no jargon, "
    "no hype, no emojis-spam."
)
CAP_TEMPLATE = """Article heading: {heading}
TL;DR:
{tldr}

Write ONE short paragraph (55-85 words) to post when SHARING this article on
LinkedIn. Rules:
- Very simple words. Explain the 'so what' for an ordinary reader.
- No jargon. No clickbait. No hashtags inside the paragraph. At most one emoji.
- Start with a hook line that makes a busy person stop scrolling.
- End by inviting them to read the full article.
Output JUST the paragraph text."""


def _fallback_caption(heading: str, bullets: list[str]) -> str:
    lead = bullets[0] if bullets else heading
    return (
        f"{heading}. In simple terms: {lead} "
        "We broke this down in plain English so you can see exactly what it "
        "means for your money — and what to do about it. Give it a read."
    )


HASHTAGS = "#PersonalFinance #Investing #India #MoneyMatters #MyFinancial"


def build_caption(heading: str, bullets: list[str], url: str) -> str:
    para = None
    if _call_llm is not None:
        try:
            para = _call_llm(
                CAP_TEMPLATE.format(
                    heading=heading,
                    tldr="\n".join(f"- {b}" for b in bullets[:5]) or "(none)"),
                CAP_SYSTEM,
                temperature=0.7, max_tokens=512, top_p=0.95,
                grounding=False, thinking_budget=0,
            )
        except Exception as e:  # pragma: no cover
            print(f"  caption LLM failed ({e}); using fallback", file=sys.stderr)
    if not para or not para.strip():
        para = _fallback_caption(heading, bullets)
    para = para.strip().strip('"')
    return f"{para}\n\nRead more: {url}\n\n{HASHTAGS}"


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def article_files(date: Optional[str], slug: Optional[str],
                  category: Optional[str]) -> list[Path]:
    if slug:
        p = ARTICLES / f"{slug}.md"
        return [p] if p.exists() else []
    files = sorted(ARTICLES.glob("*.md"))
    if date:
        files = [f for f in files if f.name.startswith(date)]
    if category:
        files = [f for f in files if f"-{category}-" in f.name]
    # Skip the bundled sample.
    return [f for f in files if not f.stem.endswith("-sample")]


def process(md_path: Path, force: bool) -> Optional[dict]:
    slug = md_path.stem
    out_dir = OUT / slug
    poster = out_dir / "poster.jpg"
    heading, bullets, fm = extract_heading_and_tldr(md_path)
    if not heading:
        print(f"! {slug}: no heading, skipping", file=sys.stderr)
        return None
    category = fm.get("category", "")
    canonical = fm.get("canonical", "").rstrip("/") + "/"

    print(f"• {slug}")
    if poster.exists() and not force:
        print("  poster exists — skipping (use --force to rebuild)")
    else:
        prompt = write_bg_prompt(heading, bullets)
        bg = fetch_background(prompt, slug) or _gradient_background()
        compose_poster(bg, heading, bullets, category, poster)

    caption = build_caption(heading, bullets, canonical)
    (out_dir).mkdir(parents=True, exist_ok=True)
    (out_dir / "caption.txt").write_text(caption, encoding="utf-8")
    meta = {
        "slug": slug,
        "heading": heading,
        "tldr": bullets,
        "category": category,
        "canonical": canonical,
        "caption": caption,
        "poster": f"output/linkedin/{slug}/poster.jpg",
        "date": fm.get("date", slug[:10]),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def render_index() -> None:
    items = []
    for meta_file in sorted(OUT.glob("*/meta.json"), reverse=True):
        try:
            items.append(json.loads(meta_file.read_text()))
        except Exception:
            continue
    cards = []
    for m in items:
        bullets = "".join(f"<li>{_esc(b)}</li>" for b in m["tldr"][:5])
        cap = _esc(m["caption"])
        cards.append(f"""
      <article class="card">
        <img src="{m['slug']}/poster.jpg" alt="poster" loading="lazy">
        <div class="body">
          <span class="cat">{_esc(CATEGORY_LABELS.get(m['category'], m['category']))} · {m['date']}</span>
          <h2>{_esc(m['heading'])}</h2>
          <ul>{bullets}</ul>
          <h3>Caption</h3>
          <textarea readonly onclick="this.select()">{cap}</textarea>
          <div class="row">
            <a class="btn" href="{m['slug']}/poster.jpg" download>Download poster</a>
            <a class="btn ghost" href="{m['canonical']}" target="_blank">Open article</a>
          </div>
        </div>
      </article>""")
    html = _INDEX_HTML.replace("{{CARDS}}", "\n".join(cards) or "<p>No assets yet.</p>")
    (OUT).mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"Index: {(OUT / 'index.html').relative_to(HERE)} ({len(items)} posts)")


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


_INDEX_HTML = """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LinkedIn assets · myfinancial.in</title>
<style>
:root{--navy:#0B2545;--amber:#F59E0B}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,Segoe UI,Roboto,sans-serif;background:#F8FAFC;color:#0B2545}
header{background:var(--navy);color:#fff;padding:22px 28px}header b{font-size:20px}
header span{opacity:.8;font-size:14px;margin-left:8px}
.wrap{max-width:1200px;margin:0 auto;padding:24px;display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:24px}
.card{background:#fff;border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;display:flex;flex-direction:column}
.card img{width:100%;aspect-ratio:9/16;object-fit:cover;background:#0B2545}
.body{padding:16px;display:flex;flex-direction:column;gap:10px}
.cat{font-size:12px;font-weight:700;letter-spacing:.5px;color:#92400E}
h2{font-size:18px;margin:0;line-height:1.25}
ul{margin:0;padding-left:18px;font-size:13px;color:#334155}li{margin:3px 0}
h3{margin:6px 0 0;font-size:12px;text-transform:uppercase;letter-spacing:.5px;color:#64748B}
textarea{width:100%;height:120px;font:13px/1.5 system-ui;border:1px solid #E5E7EB;border-radius:8px;padding:10px;resize:vertical;background:#F8FAFC}
.row{display:flex;gap:10px;margin-top:6px}
.btn{flex:1;text-align:center;text-decoration:none;background:var(--amber);color:#0B2545;font-weight:700;padding:10px;border-radius:8px;font-size:14px}
.btn.ghost{background:#fff;border:1px solid var(--navy);color:var(--navy)}
</style></head><body>
<header><b>myfinancial.in</b><span>LinkedIn share assets — poster + ready-to-paste caption</span></header>
<main class="wrap">
{{CARDS}}
</main></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=os.environ.get("POSTER_DATE"))
    ap.add_argument("--slug")
    ap.add_argument("--category")
    ap.add_argument("--force", action="store_true",
                    default=os.environ.get("FORCE") == "1")
    args = ap.parse_args()

    # Default to today's (UTC) articles when nothing else is specified.
    if not args.date and not args.slug and not args.category:
        args.date = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")

    files = article_files(args.date, args.slug, args.category)
    if not files:
        print(f"No matching articles (date={args.date} slug={args.slug} "
              f"category={args.category}).")
        render_index()
        return 0

    print(f"Processing {len(files)} article(s)…")
    made = 0
    for f in files:
        try:
            if process(f, args.force):
                made += 1
        except Exception as e:
            print(f"! {f.stem}: {e}", file=sys.stderr)
    render_index()
    print(f"Done: {made}/{len(files)} assets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
