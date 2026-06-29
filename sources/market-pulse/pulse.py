"""Hourly market-pulse image: indices + N500 movers + sector movers → Telegram.

Refactored from fyers-bot/hourly_market_pulse.py for headless CI use:
  - Reads Fyers access_token from access_token.txt (written by auto_login.py)
  - Loads Nifty 500 list live from NSE archive (no bundled CSV)
  - Env vars sourced from GitHub Actions secrets

Env:
  FYERS_CLIENT_ID            (required)
  TELEGRAM_BOT_TOKEN          (required to actually post)
  TELEGRAM_PULSE_CHAT_ID      (required to actually post)
  PULSE_FORCE=1               (optional — skip market-hours guard)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from fyers_apiv3 import fyersModel
from PIL import Image, ImageDraw, ImageFont

import nifty500

HERE = Path(__file__).parent
CLIENT_ID = os.environ["FYERS_CLIENT_ID"]
TOKEN_PATH = HERE / "access_token.txt"
LOGO_PATH = HERE / "assets" / "myfinancial_logo.png"
OUT_DIR = HERE / "out"
IST = ZoneInfo("Asia/Kolkata")

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

W, H = 1080, 1560

# Each headline index has a list of candidate Fyers symbols — first non-empty wins.
# Fyers sometimes renames index symbols; this lets us survive minor changes.
HEADLINE_INDICES = [
    ("NIFTY 50", ["NSE:NIFTY50-INDEX"]),
    ("BANK NIFTY", ["NSE:NIFTYBANK-INDEX"]),
    ("MIDCAP 100", ["NSE:NIFTYMIDCAP100-INDEX", "NSE:NIFTYMID100-INDEX",
                    "NSE:CNXMIDCAP-INDEX"]),
    ("SMLCAP 100", ["NSE:NIFTYSMLCAP100-INDEX", "NSE:NIFTYSML100-INDEX",
                    "NSE:NIFTYSMALLCAP100-INDEX", "NSE:CNXSMCAP-INDEX"]),
]
VIX = ("INDIA VIX", "NSE:INDIAVIX-INDEX")
SECTORS = [
    ("IT", "NSE:NIFTYIT-INDEX"),
    ("BANK", "NSE:NIFTYBANK-INDEX"),
    ("AUTO", "NSE:NIFTYAUTO-INDEX"),
    ("PHARMA", "NSE:NIFTYPHARMA-INDEX"),
    ("FMCG", "NSE:NIFTYFMCG-INDEX"),
    ("METAL", "NSE:NIFTYMETAL-INDEX"),
    ("REALTY", "NSE:NIFTYREALTY-INDEX"),
    ("ENERGY", "NSE:NIFTYENERGY-INDEX"),
    ("PSU BANK", "NSE:NIFTYPSUBANK-INDEX"),
    ("MEDIA", "NSE:NIFTYMEDIA-INDEX"),
    ("FIN SVC", "NSE:NIFTYFINSERVICE-INDEX"),
    ("CONSUMER", "NSE:NIFTYCONSUMER-INDEX"),
]


def market_is_open(now: dt.datetime) -> bool:
    if now.weekday() >= 5:
        return False
    return dt.time(9, 15) <= now.time() <= dt.time(15, 30)


def _client() -> fyersModel.FyersModel:
    if not TOKEN_PATH.exists():
        sys.exit("access_token.txt missing — run auto_login.py first")
    return fyersModel.FyersModel(
        client_id=CLIENT_ID, token=TOKEN_PATH.read_text().strip(), log_path="")


def fetch_quotes(fyers, symbols: list[str], batch: int = 50) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i + batch]
        resp = fyers.quotes(data={"symbols": ",".join(chunk)})
        if resp.get("s") != "ok":
            print(f"  batch {i//batch} failed: {resp.get('message')}",
                  file=sys.stderr)
            continue
        for item in resp.get("d", []):
            v = item.get("v") or {}
            out[item.get("n", "")] = {
                "lp": float(v.get("lp") or 0),
                "ch": float(v.get("ch") or 0),
                "chp": float(v.get("chp") or 0),
                "prev_close": float(v.get("prev_close_price") or 0),
                "volume": int(v.get("volume") or 0),
            }
        time.sleep(0.2)
    return out


def fetch_history_returns(fyers, symbols: list[str], days_back: int = 5,
                           rate_sleep: float = 0.12) -> dict[str, dict]:
    """For each symbol, return {chp, old_close} where chp is the % change from
    the close `days_back` trading days ago to the latest close in the candles.

    Sequential — ~60s for 500 symbols at 8 req/sec.
    """
    end = dt.date.today()
    start = end - dt.timedelta(days=days_back * 3 + 5)
    out: dict[str, dict] = {}
    for i, sym in enumerate(symbols):
        try:
            resp = fyers.history(data={
                "symbol": sym, "resolution": "D", "date_format": "1",
                "range_from": start.isoformat(), "range_to": end.isoformat(),
                "cont_flag": "1",
            })
            candles = resp.get("candles") or []
            if len(candles) < days_back + 1:
                continue
            old_close = candles[-(days_back + 1)][4]
            new_close = candles[-1][4]
            if not old_close:
                continue
            out[sym] = {
                "chp": (new_close - old_close) / old_close * 100,
                "old_close": old_close,
            }
        except Exception as e:
            print(f"  history {sym} failed: {e}", file=sys.stderr)
        time.sleep(rate_sleep)
        if i and i % 100 == 0:
            print(f"  history progress: {i}/{len(symbols)}")
    return out


def collect_data(fyers) -> dict:
    # Flatten all candidate symbols across headline indices + sectors + VIX
    all_idx_syms: list[str] = []
    for _, syms in HEADLINE_INDICES:
        all_idx_syms.extend(syms)
    all_idx_syms.append(VIX[1])
    all_idx_syms.extend(s for _, s in SECTORS)
    print(f"Fetching {len(all_idx_syms)} index symbols...")
    idx_q = fetch_quotes(fyers, all_idx_syms)

    def first_hit(candidates: list[str]) -> dict:
        for c in candidates:
            q = idx_q.get(c, {})
            if q.get("lp"):
                return q
        return {}

    indices = []
    for label, syms in HEADLINE_INDICES:
        q = first_hit(syms)
        indices.append({"name": label, "lp": q.get("lp", 0),
                        "chp": q.get("chp", 0), "ch": q.get("ch", 0)})
    vix_q = idx_q.get(VIX[1], {})
    vix = {"name": "INDIA VIX", "lp": vix_q.get("lp", 0),
           "chp": vix_q.get("chp", 0)}

    sectors = []
    for label, sym in SECTORS:
        q = idx_q.get(sym, {})
        if q:
            sectors.append({"name": label, "chp": q.get("chp", 0)})
    sectors.sort(key=lambda x: x["chp"], reverse=True)
    sector_gainers = sectors[:2]
    sector_losers = sectors[-2:][::-1]

    n500 = nifty500.load()
    n500_meta = {s["symbol"]: s for s in n500}
    n500_syms = [f"NSE:{s['symbol']}-EQ" for s in n500]
    print(f"Fetching {len(n500_syms)} N500 stocks...")
    n500_q = fetch_quotes(fyers, n500_syms)

    rows = []
    for sym_full, q in n500_q.items():
        sym = sym_full.replace("NSE:", "").replace("-EQ", "")
        if not q.get("chp"):
            continue
        meta = n500_meta.get(sym, {})
        rows.append({
            "symbol": sym,
            "company": meta.get("company") or sym,
            "sector": meta.get("industry", ""),
            "lp": q["lp"],
            "chp": q["chp"],
            "ch": q.get("ch", 0),  # absolute price change
        })
    rows.sort(key=lambda x: x["chp"], reverse=True)

    # 5-day return sweep — only for symbols we successfully got today's data for
    print(f"Fetching 5-day history for {len(rows)} N500 stocks...")
    sym_to_full = {r["symbol"]: f"NSE:{r['symbol']}-EQ" for r in rows}
    returns_5d = fetch_history_returns(
        fyers, list(sym_to_full.values()), days_back=5)
    rows_5d = []
    for r in rows:
        info = returns_5d.get(sym_to_full[r["symbol"]])
        if info is None:
            continue
        rows_5d.append({
            "symbol": r["symbol"],
            "company": r["company"],
            "sector": r["sector"],
            "lp": r["lp"],
            "chp": info["chp"],
            "ch": r["lp"] - info["old_close"],  # absolute change vs 5d ago close
        })
    rows_5d.sort(key=lambda x: x["chp"], reverse=True)
    print(f"  5-day: {len(rows_5d)} stocks ranked, "
          f"top {rows_5d[0]['symbol']} +{rows_5d[0]['chp']:.2f}%, "
          f"bottom {rows_5d[-1]['symbol']} {rows_5d[-1]['chp']:.2f}%"
          if rows_5d else "  5-day: no data")

    return {
        "indices": indices,
        "vix": vix,
        "sector_gainers": sector_gainers,
        "sector_losers": sector_losers,
        "gainers": rows[:5],
        "losers": list(reversed(rows[-5:])),
        "gainers_5d": rows_5d[:5],
        "losers_5d": list(reversed(rows_5d[-5:])) if rows_5d else [],
    }


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Try DejaVu (always on Ubuntu runners) → macOS fonts → PIL default."""
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


def _panel(draw: ImageDraw.ImageDraw, xy: tuple, r: int = 16):
    draw.rounded_rectangle(xy, radius=r, fill=PANEL_BG,
                           outline=PANEL_BORDER, width=1)


def _chip(draw, xy, text, color, font):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=8, fill=color)
    box = draw.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    draw.text(((x1 + x2 - tw) / 2, (y1 + y2 - th) / 2 - 2),
              text, fill=(255, 255, 255), font=font)


def _pct_color(pct: float) -> tuple:
    return GREEN if pct >= 0 else RED


def _fmt_pct(p: float) -> str:
    return f"{'+' if p >= 0 else ''}{p:.2f}%"


def _fmt_num(v: float, d: int = 2) -> str:
    return f"{v:,.{d}f}"


def render(data: dict, when: dt.datetime) -> Image.Image:
    img = Image.new("RGB", (W, H), LIGHT_BG)
    draw = ImageDraw.Draw(img)

    title_f = _font(38, bold=True)
    sub_f = _font(22)
    h_f = _font(26, bold=True)
    body_f = _font(24)
    big_f = _font(34, bold=True)
    small_f = _font(20)
    chip_f = _font(20, bold=True)

    # Header — larger logo for visibility
    LOGO_H = 140
    HEADER_BOTTOM = 60 + LOGO_H + 20  # logo top (60) + logo + 20px buffer
    if LOGO_PATH.exists():
        logo = Image.open(LOGO_PATH).convert("RGBA")
        ratio = LOGO_H / logo.height
        logo = logo.resize((int(logo.width * ratio), LOGO_H), Image.LANCZOS)
        img.paste(logo, (40, 30), logo)
    draw.text((W - 380, 50), "Market Pulse", fill=NAVY, font=title_f)
    draw.text((W - 380, 100), when.strftime("%I:%M %p · %a, %d %b"),
              fill=MUTED, font=sub_f)
    draw.line([(40, HEADER_BOTTOM), (W - 40, HEADER_BOTTOM)], fill=GOLD, width=2)

    # Headline indices
    y0 = HEADER_BOTTOM + 25
    card_w = (W - 40 * 2 - 30) // 4
    for i, idx in enumerate(data["indices"]):
        x = 40 + i * (card_w + 10)
        _panel(draw, (x, y0, x + card_w, y0 + 130))
        draw.text((x + 16, y0 + 14), idx["name"], fill=MUTED, font=small_f)
        draw.text((x + 16, y0 + 42), _fmt_num(idx["lp"]),
                  fill=DARK_TEXT, font=big_f)
        draw.text((x + 16, y0 + 88), _fmt_pct(idx["chp"]),
                  fill=_pct_color(idx["chp"]), font=h_f)

    # VIX inline
    vix = data["vix"]
    y_vix = y0 + 145
    draw.text((40, y_vix), "INDIA VIX", fill=MUTED, font=small_f)
    draw.text((180, y_vix), _fmt_num(vix["lp"]), fill=DARK_TEXT, font=h_f)
    risk_label = ("· risk-off" if vix["chp"] > 5
                  else "· calm" if vix["chp"] < -3 else "")
    draw.text((300, y_vix), _fmt_pct(vix["chp"]) + " " + risk_label,
              fill=_pct_color(-vix["chp"]), font=body_f)

    # Movers panels
    y1 = y_vix + 60
    panel_h = 380
    panel_w = (W - 40 * 2 - 20) // 2

    def movers_panel(title: str, rows: list[dict], x: int, y: int,
                     color: tuple):
        """Clean two-column table — company / sector on left, price / change on right.

        Used for both today's and 5-day movers so styling stays consistent.
        """
        # Outer rounded panel
        _panel(draw, (x, y, x + panel_w, y + panel_h))

        # Title bar (navy strip, top corners rounded)
        draw.rounded_rectangle((x, y, x + panel_w, y + 46),
                                radius=16, fill=NAVY)
        draw.rectangle((x, y + 22, x + panel_w, y + 46), fill=NAVY)
        draw.text((x + 24, y + 12), title, fill=(255, 255, 255), font=h_f)

        # Column headers (subtle grey strip)
        hdr_y = y + 46
        draw.rectangle((x + 1, hdr_y, x + panel_w - 1, hdr_y + 34),
                        fill=(245, 245, 243))
        # Bottom border under headers
        draw.line([(x + 1, hdr_y + 34), (x + panel_w - 1, hdr_y + 34)],
                  fill=PANEL_BORDER, width=1)
        draw.text((x + 24, hdr_y + 8), "Symbol", fill=MUTED, font=small_f)
        lp_label = "Live price"
        lp_lbl_box = draw.textbbox((0, 0), lp_label, font=small_f)
        lp_lbl_w = lp_lbl_box[2] - lp_lbl_box[0]
        draw.text((x + panel_w - 24 - lp_lbl_w, hdr_y + 8), lp_label,
                   fill=MUTED, font=small_f)

        # Helper: truncate a string with an ellipsis to fit within max_width pixels
        def _fit(text: str, font, max_width: int) -> str:
            if not text:
                return ""
            box = draw.textbbox((0, 0), text, font=font)
            if box[2] - box[0] <= max_width:
                return text
            ell = "…"
            ell_w = draw.textbbox((0, 0), ell, font=font)[2]
            while text:
                text = text[:-1].rstrip()
                box = draw.textbbox((0, 0), text + ell, font=font)
                if box[2] - box[0] <= max_width:
                    return text + ell
            return ell

        # Data rows
        ly = hdr_y + 34 + 6
        row_h = 58
        GAP = 16  # px between left text end and right text start
        for i, r in enumerate(rows[:5]):
            if i > 0:
                draw.line([(x + 16, ly - 4), (x + panel_w - 16, ly - 4)],
                          fill=PANEL_BORDER, width=1)

            # ---- Measure right-side text FIRST so we know how much room is left ----
            lp_str = _fmt_num(r["lp"])
            lp_box = draw.textbbox((0, 0), lp_str, font=body_f)
            lp_w = lp_box[2] - lp_box[0]
            lp_x = x + panel_w - 24 - lp_w

            ch = r.get("ch", 0)
            sign = "+" if ch >= 0 else ""
            ch_str = f"{sign}{_fmt_num(ch)} ({_fmt_pct(r['chp'])})"
            ch_box = draw.textbbox((0, 0), ch_str, font=small_f)
            ch_w = ch_box[2] - ch_box[0]
            ch_x = x + panel_w - 24 - ch_w

            # Left-text budgets per line
            name_budget = lp_x - GAP - (x + 24)
            sec_budget = ch_x - GAP - (x + 24)

            # ---- Draw left side, truncated to fit ----
            name = _fit(r.get("company") or r["symbol"], body_f, name_budget)
            draw.text((x + 24, ly), name, fill=DARK_TEXT, font=body_f)

            sec = _fit(r.get("sector") or "", small_f, sec_budget)
            draw.text((x + 24, ly + 30), sec, fill=MUTED, font=small_f)

            # ---- Draw right side ----
            draw.text((lp_x, ly), lp_str, fill=DARK_TEXT, font=body_f)
            draw.text((ch_x, ly + 30), ch_str, fill=color, font=small_f)

            ly += row_h

    movers_panel("Top Gainers · Today", data["gainers"], 40, y1, GREEN)
    movers_panel("Top Losers · Today", data["losers"],
                  40 + panel_w + 20, y1, RED)

    # Sectors
    y2 = y1 + panel_h + 24
    _panel(draw, (40, y2, W - 40, y2 + 170))
    draw.text((64, y2 + 18), "Sectors — top movers", fill=NAVY, font=h_f)

    def sec_row(label, rows, y, color):
        draw.text((64, y), label, fill=color, font=body_f)
        for j, s in enumerate(rows[:2]):
            x = 320 + j * 360
            _chip(draw, (x, y - 2, x + 320, y + 32),
                  f"{s['name']}  {_fmt_pct(s['chp'])}", color, chip_f)
    sec_row("Gainers", data["sector_gainers"], y2 + 60, GREEN)
    sec_row("Losers", data["sector_losers"], y2 + 110, RED)

    # 5-day movers — same layout via shared helper
    y3 = y2 + 170 + 24
    movers_panel("5-Day Gainers · Nifty 500",
                 data.get("gainers_5d", []), 40, y3, GREEN)
    movers_panel("5-Day Losers · Nifty 500",
                 data.get("losers_5d", []),
                 40 + panel_w + 20, y3, RED)

    # Footer — 3 lines: brand · data source · SEBI-standard disclaimer
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
    return img


def caption(data: dict, when: dt.datetime) -> str:
    n50 = next((i for i in data["indices"] if i["name"] == "NIFTY 50"), {})
    bn = next((i for i in data["indices"] if i["name"] == "BANK NIFTY"), {})
    parts = [
        f"<b>Market Pulse</b> · {when.strftime('%I:%M %p, %d %b')}",
        f"NIFTY 50 <b>{_fmt_num(n50.get('lp', 0))}</b> ({_fmt_pct(n50.get('chp', 0))})",
        f"BANK NIFTY <b>{_fmt_num(bn.get('lp', 0))}</b> ({_fmt_pct(bn.get('chp', 0))})",
    ]
    if data["sector_gainers"]:
        sg = data["sector_gainers"][0]
        parts.append(f"Best sector: <b>{sg['name']}</b> {_fmt_pct(sg['chp'])}")
    if data["sector_losers"]:
        sl = data["sector_losers"][0]
        parts.append(f"Worst sector: <b>{sl['name']}</b> {_fmt_pct(sl['chp'])}")
    parts.append("\n<i>myfinancial.in</i>")
    return "\n".join(parts)


def post_telegram(path: Path, cap: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_PULSE_CHAT_ID")
    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_PULSE_CHAT_ID not set", file=sys.stderr)
        return False
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    for attempt in range(3):
        with open(path, "rb") as f:
            files = {"photo": ("pulse.png", f, "image/png")}
            data = {"chat_id": chat_id, "caption": cap, "parse_mode": "HTML"}
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
                print(f"Telegram {r.status_code}: {r.text[:200]}", file=sys.stderr)
                return False
            except Exception as e:
                print(f"Telegram error (attempt {attempt+1}): {e}", file=sys.stderr)
                time.sleep(3)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    now = dt.datetime.now(IST)
    force = args.force or os.environ.get("PULSE_FORCE") == "1"
    if not force and not market_is_open(now):
        print(f"Market closed ({now:%a %H:%M IST}) — exiting")
        return 0

    fyers = _client()
    profile = fyers.get_profile()
    if profile.get("s") != "ok":
        print(f"Fyers token check failed: {profile}", file=sys.stderr)
        return 1

    data = collect_data(fyers)
    img = render(data, now)

    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"pulse_{now:%Y-%m-%d_%H%M}.png"
    img.save(path, "PNG", optimize=True)
    print(f"Saved {path}")

    if args.dry_run:
        return 0
    ok = post_telegram(path, caption(data, now))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
