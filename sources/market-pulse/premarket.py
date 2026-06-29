"""Pre-market report — global indices, currencies, commodities, GIFT Nifty,
and top news affecting Indian markets. Posts at 08:15 IST.

GIFT Nifty (NSE IFSC) is fetched via Fyers — others come from yfinance.
Workflow needs to run auto_login.py before this script.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf
from fyers_apiv3 import fyersModel
from PIL import Image, ImageDraw

import brand
import news_rss

IST = ZoneInfo("Asia/Kolkata")
HERE = Path(__file__).parent
TOKEN_PATH = HERE / "access_token.txt"
OUT_DIR = HERE / "out"

CLIENT_ID = os.environ.get("FYERS_CLIENT_ID")

# US / global headline indices (yfinance tickers)
GLOBAL_INDICES = [
    ("DOW JONES", "^DJI"),
    ("NASDAQ", "^IXIC"),
    ("S&P 500", "^GSPC"),
    ("NIKKEI 225", "^N225"),
]

# Pre-open cues
CUES = [
    ("USD/INR", "INR=X"),
    ("DOLLAR INDEX", "DX-Y.NYB"),
    ("BRENT CRUDE", "BZ=F"),
    ("GOLD", "GC=F"),
    ("US 10Y YIELD", "^TNX"),
    ("HANG SENG", "^HSI"),
]

# GIFT Nifty (NSE IFSC) — try multiple symbol variants for resilience
GIFT_NIFTY_CANDIDATES = [
    "NSEIX:GIFTNIFTY1!FUT",
    "NSEIX:GIFTNIFTY-FUT",
    "NSEIX:GIFTNIFTY-INDEX",
]


def fetch_yf_quote(ticker: str) -> dict:
    try:
        h = yf.Ticker(ticker).history(period="5d", auto_adjust=False)
        if len(h) < 2:
            return {}
        last = float(h["Close"].iloc[-1])
        prev = float(h["Close"].iloc[-2])
        return {"lp": last, "chp": (last - prev) / prev * 100 if prev else 0,
                "ch": last - prev}
    except Exception as e:
        print(f"yf {ticker} failed: {e}", file=sys.stderr)
        return {}


def fetch_gift_nifty() -> dict:
    """Try Fyers NSEIX symbols for GIFT Nifty until one returns a price."""
    if not TOKEN_PATH.exists() or not CLIENT_ID:
        print("No Fyers token — skipping GIFT Nifty", file=sys.stderr)
        return {}
    fyers = fyersModel.FyersModel(
        client_id=CLIENT_ID, token=TOKEN_PATH.read_text().strip(),
        log_path="")
    for sym in GIFT_NIFTY_CANDIDATES:
        try:
            resp = fyers.quotes(data={"symbols": sym})
            if resp.get("s") != "ok":
                continue
            for item in resp.get("d", []):
                v = item.get("v") or {}
                lp = float(v.get("lp") or 0)
                if lp:
                    return {
                        "name": "GIFT NIFTY", "lp": lp,
                        "ch": float(v.get("ch") or 0),
                        "chp": float(v.get("chp") or 0),
                        "symbol": sym,
                    }
        except Exception as e:
            print(f"  GIFT Nifty {sym} failed: {e}", file=sys.stderr)
            continue
        time.sleep(0.2)
    print("GIFT Nifty: no symbol returned data", file=sys.stderr)
    return {"name": "GIFT NIFTY"}


def collect() -> dict:
    print("Fetching global indices...")
    indices = [{"name": n, **fetch_yf_quote(t)} for n, t in GLOBAL_INDICES]

    print("Fetching GIFT Nifty via Fyers...")
    gift = fetch_gift_nifty()

    print("Fetching cues (currencies, commodities, yields)...")
    cues = []
    for name, t in CUES:
        q = fetch_yf_quote(t)
        if q:
            cues.append({"name": name, **q})

    print("Fetching news...")
    items = news_rss.fetch_all(hours_back=18)
    top_news = news_rss.rank(items, top_n=5)
    print(f"  -> {len(top_news)} top news selected")

    return {"indices": indices, "gift": gift, "cues": cues, "news": top_news}


# ---- Render ----
W = brand.W
H = 1900


def render(data: dict, when: dt.datetime) -> Image.Image:
    img = Image.new("RGB", (W, H), brand.LIGHT_BG)
    draw = ImageDraw.Draw(img)

    h_f = brand.font(26, bold=True)
    body_f = brand.font(24)
    small_f = brand.font(20)
    big_f = brand.font(34, bold=True)
    chip_f = brand.font(20, bold=True)

    header_bottom = brand.draw_header(
        img, draw, "Pre-Market Brief",
        when.strftime("%I:%M %p · %a, %d %b"))

    # ---- Global indices cards (4 across) ----
    y0 = header_bottom + 25
    card_w = (W - 80 - 30) // 4
    for i, idx in enumerate(data["indices"]):
        x = 40 + i * (card_w + 10)
        brand.panel(draw, (x, y0, x + card_w, y0 + 130))
        draw.text((x + 16, y0 + 14), idx["name"],
                   fill=brand.MUTED, font=small_f)
        if idx.get("lp"):
            draw.text((x + 16, y0 + 42), brand.fmt_num(idx["lp"]),
                       fill=brand.DARK_TEXT, font=big_f)
            draw.text((x + 16, y0 + 88), brand.fmt_pct(idx.get("chp", 0)),
                       fill=brand.pct_color(idx.get("chp", 0)), font=h_f)
        else:
            draw.text((x + 16, y0 + 50), "—", fill=brand.MUTED, font=big_f)

    # ---- GIFT Nifty band ----
    y_gift = y0 + 130 + 16
    brand.panel(draw, (40, y_gift, W - 40, y_gift + 90))
    draw.text((64, y_gift + 14), "GIFT NIFTY",
               fill=brand.NAVY, font=h_f)
    gift = data["gift"]
    if gift.get("lp"):
        # Right-aligned: ₹value + chip
        chp_str = brand.fmt_pct(gift.get("chp", 0))
        chip_color = brand.pct_color(gift.get("chp", 0))
        chip_w = 110
        brand.chip(draw, (W - 40 - chip_w - 24, y_gift + 28,
                          W - 40 - 24, y_gift + 62),
                   chp_str, chip_color, chip_f)
        # LTP big
        lp_str = brand.fmt_num(gift["lp"])
        lp_box = draw.textbbox((0, 0), lp_str, font=big_f)
        lp_w = lp_box[2] - lp_box[0]
        draw.text((W - 40 - chip_w - 24 - 24 - lp_w, y_gift + 22),
                   lp_str, fill=brand.DARK_TEXT, font=big_f)
        # Subtitle
        sub = (f"Indicator for Indian market open · "
               f"change {brand.fmt_num(gift.get('ch', 0))}")
        draw.text((64, y_gift + 50), sub, fill=brand.MUTED, font=small_f)
    else:
        draw.text((W - 40 - 24 - 50, y_gift + 28), "—",
                   fill=brand.MUTED, font=big_f)
        draw.text((64, y_gift + 50),
                   "Indicator for Indian market open · data unavailable",
                   fill=brand.MUTED, font=small_f)

    # ---- Cues panel ----
    y_cues = y_gift + 90 + 18
    cues_h = 280
    brand.panel(draw, (40, y_cues, W - 40, y_cues + cues_h))
    draw.rounded_rectangle((40, y_cues, W - 40, y_cues + 46),
                            radius=16, fill=brand.NAVY)
    draw.rectangle((40, y_cues + 22, W - 40, y_cues + 46), fill=brand.NAVY)
    draw.text((64, y_cues + 12), "Global Cues",
               fill=(255, 255, 255), font=h_f)

    inner_top = y_cues + 60
    col_w = (W - 80) // 2
    row_h = 70
    for i, c in enumerate(data["cues"][:6]):
        col = i % 2
        row = i // 2
        cx = 40 + col * col_w
        cy = inner_top + row * row_h
        # Name
        draw.text((cx + 24, cy + 4), c["name"],
                   fill=brand.MUTED, font=small_f)
        if c.get("lp"):
            decimals = 4 if c["name"] == "USD/INR" else 2
            val = brand.fmt_num(c["lp"], decimals)
            val_box = draw.textbbox((0, 0), val, font=body_f)
            val_w = val_box[2] - val_box[0]
            draw.text((cx + col_w - 24 - val_w - 110, cy + 2), val,
                       fill=brand.DARK_TEXT, font=body_f)
            chp_str = brand.fmt_pct(c.get("chp", 0))
            chip_color = brand.pct_color(c.get("chp", 0))
            brand.chip(draw, (cx + col_w - 24 - 100, cy + 4,
                              cx + col_w - 24, cy + 38),
                       chp_str, chip_color, chip_f)
        if row < 2:
            draw.line([(cx + 16, cy + row_h - 8),
                       (cx + col_w - 16, cy + row_h - 8)],
                      fill=brand.PANEL_BORDER, width=1)

    # ---- News panel (multi-line headlines) ----
    y_news = y_cues + cues_h + 24
    news_h = H - y_news - 130
    brand.panel(draw, (40, y_news, W - 40, y_news + news_h))
    draw.rounded_rectangle((40, y_news, W - 40, y_news + 46),
                            radius=16, fill=brand.NAVY)
    draw.rectangle((40, y_news + 22, W - 40, y_news + 46), fill=brand.NAVY)
    draw.text((64, y_news + 12),
               "Overnight news that matters",
               fill=(255, 255, 255), font=h_f)

    # Each news item: numbered bullet + wrapped title + source line
    ly = y_news + 64
    title_max_width = W - 56 - 90 - 56  # left padding + bullet space + right pad
    LINE_HEIGHT = 32
    for i, n in enumerate(data["news"][:5]):
        if i > 0:
            draw.line([(56, ly - 8), (W - 56, ly - 8)],
                       fill=brand.PANEL_BORDER, width=1)
        # Bullet number
        draw.text((56, ly + 2), f"{i+1}",
                   fill=brand.GOLD, font=body_f)
        # Wrap title to fit
        lines = brand.wrap_text(draw, n["title"], body_f, title_max_width)
        cur_y = ly
        for line in lines:
            draw.text((90, cur_y), line,
                       fill=brand.DARK_TEXT, font=body_f)
            cur_y += LINE_HEIGHT
        # Source under title
        src = (n.get("source") or "")[:50]
        draw.text((90, cur_y + 4), src,
                   fill=brand.MUTED, font=small_f)
        ly = cur_y + 36  # source line + bottom padding

    brand.draw_footer(img, draw, when, H)
    return img


def caption(data: dict, when: dt.datetime) -> str:
    sp = next((i for i in data["indices"] if i["name"] == "S&P 500"), {})
    nk = next((i for i in data["indices"] if i["name"] == "NIKKEI 225"), {})
    parts = [
        f"<b>Pre-Market Brief</b> · {when.strftime('%I:%M %p, %d %b')}",
        f"S&amp;P 500 <b>{brand.fmt_num(sp.get('lp', 0))}</b> "
        f"({brand.fmt_pct(sp.get('chp', 0))})",
        f"NIKKEI <b>{brand.fmt_num(nk.get('lp', 0))}</b> "
        f"({brand.fmt_pct(nk.get('chp', 0))})",
    ]
    g = data.get("gift") or {}
    if g.get("lp"):
        parts.append(f"GIFT NIFTY <b>{brand.fmt_num(g['lp'])}</b> "
                     f"({brand.fmt_pct(g.get('chp', 0))})")
    inr = next((c for c in data["cues"] if c["name"] == "USD/INR"), {})
    if inr:
        parts.append(f"USD/INR <b>{brand.fmt_num(inr.get('lp', 0), 4)}</b> "
                     f"({brand.fmt_pct(inr.get('chp', 0))})")
    parts.append("\n<i>myfinancial.in</i>")
    return "\n".join(parts)


def main() -> int:
    when = dt.datetime.now(IST)
    data = collect()
    img = render(data, when)
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"premarket_{when:%Y-%m-%d_%H%M}.png"
    img.save(path, "PNG", optimize=True)
    print(f"Saved {path}")
    try:
        import page_export
        page_export.export("pre-market", f"Pre-Market Brief — {when:%d %b %Y}",
                           when, path, caption(data, when))
    except Exception as e:
        print(f"page_export failed (non-fatal): {e}", file=sys.stderr)
    ok = brand.post_telegram(path, caption(data, when))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
