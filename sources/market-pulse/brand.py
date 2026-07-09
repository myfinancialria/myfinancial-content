"""Shared image-rendering primitives for all reports (pulse, premarket,
postmarket, commodities).

Colors, fonts, panel helper, text-fit helper, formatters, header/footer
drawers, Telegram post helper — everything that should look identical
across reports.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
LOGO_PATH = HERE / "assets" / "myfinancial_logo.png"

# Brand palette
NAVY = (15, 42, 74)
GOLD = (201, 162, 39)
GREEN = (27, 127, 58)
RED = (178, 58, 72)
LIGHT_BG = (250, 250, 248)
DARK_TEXT = (26, 26, 26)
MUTED = (110, 110, 110)
PANEL_BG = (255, 255, 255)
PANEL_BORDER = (230, 230, 226)
HEADER_TINT = (245, 245, 243)

W = 1080  # all images share this width


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """DejaVu (Ubuntu runners) → macOS Helvetica/Arial → PIL default."""
    candidates = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
         if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ("/System/Library/Fonts/Supplemental/Arial Bold.ttf"
         if bold else "/System/Library/Fonts/Supplemental/Arial.ttf"),
        ("/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf"),
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def panel(draw: ImageDraw.ImageDraw, xy: tuple, r: int = 16):
    draw.rounded_rectangle(xy, radius=r, fill=PANEL_BG,
                            outline=PANEL_BORDER, width=1)


def chip(draw: ImageDraw.ImageDraw, xy: tuple, text: str, color: tuple,
         f: ImageFont.FreeTypeFont):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=8, fill=color)
    box = draw.textbbox((0, 0), text, font=f)
    tw, th = box[2] - box[0], box[3] - box[1]
    draw.text(((x1 + x2 - tw) / 2, (y1 + y2 - th) / 2 - 2),
              text, fill=(255, 255, 255), font=f)


def wrap_text(draw: ImageDraw.ImageDraw, text: str,
              f: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap text into lines that each fit within max_width pixels.

    Never truncates — returns every word. Long single words that overflow
    a line are left intact (rare for news headlines)."""
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for w in words:
        candidate = " ".join(current + [w])
        box = draw.textbbox((0, 0), candidate, font=f)
        if box[2] - box[0] <= max_width:
            current.append(w)
        else:
            if current:
                lines.append(" ".join(current))
            current = [w]
    if current:
        lines.append(" ".join(current))
    return lines


def fit(draw: ImageDraw.ImageDraw, text: str,
        f: ImageFont.FreeTypeFont, max_width: int) -> str:
    """Truncate text with '…' so it fits within max_width pixels."""
    if not text:
        return ""
    box = draw.textbbox((0, 0), text, font=f)
    if box[2] - box[0] <= max_width:
        return text
    ell = "…"
    while text:
        text = text[:-1].rstrip()
        candidate = text + ell
        box = draw.textbbox((0, 0), candidate, font=f)
        if box[2] - box[0] <= max_width:
            return candidate
    return ell


def pct_color(pct: float) -> tuple:
    return GREEN if pct >= 0 else RED


def fmt_pct(p: float) -> str:
    return f"{'+' if p >= 0 else ''}{p:.2f}%"


def fmt_num(v: float, d: int = 2) -> str:
    return f"{v:,.{d}f}"


def draw_header(img: Image.Image, draw: ImageDraw.ImageDraw,
                title: str, subtitle: str = "",
                logo_h: int = 140) -> int:
    """Top branded header. Returns y-coordinate of the bottom divider."""
    title_f = font(38, bold=True)
    sub_f = font(22)
    if LOGO_PATH.exists():
        logo = Image.open(LOGO_PATH).convert("RGBA")
        ratio = logo_h / logo.height
        logo = logo.resize((int(logo.width * ratio), logo_h), Image.LANCZOS)
        img.paste(logo, (40, 30), logo)
    draw.text((W - 380, 50), title, fill=NAVY, font=title_f)
    if subtitle:
        draw.text((W - 380, 100), subtitle, fill=MUTED, font=sub_f)
    header_bottom = 30 + logo_h + 20
    draw.line([(40, header_bottom), (W - 40, header_bottom)],
              fill=GOLD, width=2)
    return header_bottom


def draw_footer(img: Image.Image, draw: ImageDraw.ImageDraw,
                when: dt.datetime, H: int) -> None:
    """Three-line footer: brand tagline, data line, SEBI-standard disclaimer."""
    body_f = font(24)
    small_f = font(20)
    draw.line([(40, H - 110), (W - 40, H - 110)], fill=GOLD, width=2)
    draw.text((40, H - 95),
              "myfinancial.in — For Indians who'd rather understand than be sold to",
              fill=NAVY, font=body_f)
    data_line = (f"Live market data · Snapshot at "
                 f"{when.strftime('%I:%M %p IST, %d %b %Y')}")
    draw.text((40, H - 60), data_line, fill=MUTED, font=small_f)
    draw.text((40, H - 32),
              "Investments are subject to market risks · "
              "Not investment advice · Consult a SEBI-registered advisor",
              fill=MUTED, font=small_f)


def movers_table(draw: ImageDraw.ImageDraw, title: str,
                 rows: list[dict], x: int, y: int,
                 panel_w: int, panel_h: int, color: tuple,
                 left_label: str = "Symbol",
                 right_label: str = "Live price") -> None:
    """Reusable 2-column table panel — title bar + column headers + 5 data rows.

    Each row dict expects keys: name (left header text), sub (left footer text,
    e.g. sector), lp (right header value), ch (absolute change), chp (% change).
    """
    h_f = font(26, bold=True)
    body_f = font(24)
    small_f = font(20)

    # Outer
    panel(draw, (x, y, x + panel_w, y + panel_h))

    # Title bar
    draw.rounded_rectangle((x, y, x + panel_w, y + 46),
                            radius=16, fill=NAVY)
    draw.rectangle((x, y + 22, x + panel_w, y + 46), fill=NAVY)
    draw.text((x + 24, y + 12), title, fill=(255, 255, 255), font=h_f)

    # Column headers strip
    hdr_y = y + 46
    draw.rectangle((x + 1, hdr_y, x + panel_w - 1, hdr_y + 34),
                    fill=HEADER_TINT)
    draw.line([(x + 1, hdr_y + 34), (x + panel_w - 1, hdr_y + 34)],
              fill=PANEL_BORDER, width=1)
    draw.text((x + 24, hdr_y + 8), left_label, fill=MUTED, font=small_f)
    rl_box = draw.textbbox((0, 0), right_label, font=small_f)
    rl_w = rl_box[2] - rl_box[0]
    draw.text((x + panel_w - 24 - rl_w, hdr_y + 8), right_label,
               fill=MUTED, font=small_f)

    ly = hdr_y + 34 + 6
    row_h = 58
    GAP = 16
    for i, r in enumerate(rows[:5]):
        if i > 0:
            draw.line([(x + 16, ly - 4), (x + panel_w - 16, ly - 4)],
                       fill=PANEL_BORDER, width=1)

        # Measure right side first
        lp_str = fmt_num(r["lp"])
        lp_box = draw.textbbox((0, 0), lp_str, font=body_f)
        lp_w = lp_box[2] - lp_box[0]
        lp_x = x + panel_w - 24 - lp_w

        ch = r.get("ch", 0)
        sign = "+" if ch >= 0 else ""
        ch_str = f"{sign}{fmt_num(ch)} ({fmt_pct(r['chp'])})"
        ch_box = draw.textbbox((0, 0), ch_str, font=small_f)
        ch_w = ch_box[2] - ch_box[0]
        ch_x = x + panel_w - 24 - ch_w

        # Left side budgets
        name_budget = lp_x - GAP - (x + 24)
        sub_budget = ch_x - GAP - (x + 24)

        name = fit(draw, r.get("name") or "", body_f, name_budget)
        draw.text((x + 24, ly), name, fill=DARK_TEXT, font=body_f)
        sub = fit(draw, r.get("sub") or "", small_f, sub_budget)
        draw.text((x + 24, ly + 30), sub, fill=MUTED, font=small_f)

        draw.text((lp_x, ly), lp_str, fill=DARK_TEXT, font=body_f)
        draw.text((ch_x, ly + 30), ch_str, fill=color, font=small_f)

        ly += row_h


def post_telegram(image_path: Path, caption: str,
                  chat_id_env: str = "TELEGRAM_PULSE_CHAT_ID") -> bool:
    """sendPhoto helper. Returns True on success OR when Telegram isn't
    configured (an unconfigured optional channel is a no-op, not a failure —
    the caller shouldn't fail content publishing just because there's no chat)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get(chat_id_env)
    if not token or not chat_id:
        print(f"TELEGRAM_BOT_TOKEN / {chat_id_env} not set — skipping Telegram post",
              file=sys.stderr)
        return True
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    for attempt in range(3):
        with open(image_path, "rb") as f:
            files = {"photo": ("report.png", f, "image/png")}
            data = {"chat_id": chat_id, "caption": caption,
                    "parse_mode": "HTML"}
            try:
                r = requests.post(url, data=data, files=files, timeout=30)
                if r.status_code == 429:
                    wait = int(r.json().get("parameters", {})
                                .get("retry_after", 5))
                    print(f"Telegram 429 — waiting {wait}s", file=sys.stderr)
                    time.sleep(wait + 1)
                    continue
                if r.ok:
                    print(f"Sent to Telegram {chat_id}")
                    return True
                print(f"Telegram {r.status_code}: {r.text[:200]}",
                       file=sys.stderr)
                return False
            except Exception as e:
                print(f"Telegram error (attempt {attempt+1}): {e}",
                       file=sys.stderr)
                time.sleep(3)
    return False
