"""Indian commodities snapshot at 22:00 IST — MCX front-month futures
gainers and losers via Fyers.

Symbol resolution happens dynamically through mcx.py — no hardcoded
expiries to maintain.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from fyers_apiv3 import fyersModel
from PIL import Image, ImageDraw

import brand
import mcx

IST = ZoneInfo("Asia/Kolkata")
HERE = Path(__file__).parent
TOKEN_PATH = HERE / "access_token.txt"
OUT_DIR = HERE / "out"

CLIENT_ID = os.environ["FYERS_CLIENT_ID"]


def _client() -> fyersModel.FyersModel:
    if not TOKEN_PATH.exists():
        sys.exit("access_token.txt missing — run auto_login.py first")
    return fyersModel.FyersModel(
        client_id=CLIENT_ID, token=TOKEN_PATH.read_text().strip(),
        log_path="")


def fetch_quotes(fyers, symbols: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    # MCX symbols can be long; batch of 30 to be safe
    for i in range(0, len(symbols), 30):
        chunk = symbols[i:i + 30]
        resp = fyers.quotes(data={"symbols": ",".join(chunk)})
        if resp.get("s") != "ok":
            print(f"  batch {i//30} failed: {resp.get('message')}",
                  file=sys.stderr)
            continue
        for item in resp.get("d", []):
            v = item.get("v") or {}
            out[item.get("n", "")] = {
                "lp": float(v.get("lp") or 0),
                "ch": float(v.get("ch") or 0),
                "chp": float(v.get("chp") or 0),
            }
        time.sleep(0.2)
    return out


def collect() -> dict:
    contracts = mcx.active_commodities()
    if not contracts:
        print("No MCX contracts resolved — aborting")
        return {"all": [], "gainers": [], "losers": []}

    fyers = _client()
    sym_to_display = {info["symbol"]: name for name, info in contracts.items()}
    sym_to_expiry = {info["symbol"]: info["expiry"]
                     for info in contracts.values()}
    symbols = list(sym_to_display.keys())
    print(f"Fetching {len(symbols)} MCX quotes...")
    quotes = fetch_quotes(fyers, symbols)

    rows = []
    for sym, q in quotes.items():
        if not q.get("lp"):
            continue
        rows.append({
            "company": sym_to_display.get(sym, sym),
            "sector": f"MCX · exp {sym_to_expiry.get(sym, '')[:7]}",
            "lp": q["lp"],
            "ch": q.get("ch", 0),
            "chp": q.get("chp", 0),
            "symbol": sym,
        })
    rows.sort(key=lambda x: x["chp"], reverse=True)
    print(f"  -> {len(rows)} MCX commodities with valid data")
    return {
        "all": rows,
        "gainers": rows[:5],
        "losers": list(reversed(rows[-5:])) if rows else [],
    }


W = brand.W
H = 1380


def render(data: dict, when: dt.datetime) -> Image.Image:
    img = Image.new("RGB", (W, H), brand.LIGHT_BG)
    draw = ImageDraw.Draw(img)
    h_f = brand.font(26, bold=True)
    body_f = brand.font(24)
    small_f = brand.font(20)

    header_bottom = brand.draw_header(
        img, draw, "MCX Commodities",
        when.strftime("%I:%M %p · %a, %d %b"))

    # Two-panel mover tables
    y0 = header_bottom + 30
    panel_w = (W - 80 - 20) // 2
    panel_h = 380

    gain_rows = [{"name": r["company"], "sub": r["sector"],
                  "lp": r["lp"], "ch": r["ch"], "chp": r["chp"]}
                 for r in data["gainers"]]
    lose_rows = [{"name": r["company"], "sub": r["sector"],
                  "lp": r["lp"], "ch": r["ch"], "chp": r["chp"]}
                 for r in data["losers"]]

    brand.movers_table(draw, "Top Gainers · MCX", gain_rows, 40, y0,
                        panel_w, panel_h, brand.GREEN,
                        left_label="Contract", right_label="Last (₹)")
    brand.movers_table(draw, "Top Losers · MCX", lose_rows,
                        40 + panel_w + 20, y0, panel_w, panel_h,
                        brand.RED,
                        left_label="Contract", right_label="Last (₹)")

    # Full table below
    y_all = y0 + panel_h + 30
    all_h = H - y_all - 130
    brand.panel(draw, (40, y_all, W - 40, y_all + all_h))
    draw.rounded_rectangle((40, y_all, W - 40, y_all + 46),
                            radius=16, fill=brand.NAVY)
    draw.rectangle((40, y_all + 22, W - 40, y_all + 46), fill=brand.NAVY)
    draw.text((64, y_all + 12),
               "All MCX contracts · sorted by % change",
               fill=(255, 255, 255), font=h_f)

    ly = y_all + 64
    col_w = (W - 80) // 2
    col_left, col_right = [], []
    for i, r in enumerate(data["all"]):
        (col_left if i < (len(data["all"]) + 1) // 2 else col_right).append(r)

    chip_f = brand.font(20, bold=True)
    for col_idx, col in enumerate([col_left, col_right]):
        cx = 40 + col_idx * col_w
        cy = ly
        for r in col:
            name_text = brand.fit(draw, r["company"], body_f, col_w - 220)
            draw.text((cx + 24, cy), name_text,
                       fill=brand.DARK_TEXT, font=body_f)
            draw.text((cx + 24, cy + 28), r["sector"],
                       fill=brand.MUTED, font=small_f)
            lp_str = brand.fmt_num(r["lp"])
            lp_box = draw.textbbox((0, 0), lp_str, font=body_f)
            lp_w = lp_box[2] - lp_box[0]
            draw.text((cx + col_w - 24 - lp_w - 100, cy),
                       lp_str, fill=brand.DARK_TEXT, font=body_f)
            chp_str = brand.fmt_pct(r["chp"])
            chip_color = brand.pct_color(r["chp"])
            brand.chip(draw, (cx + col_w - 24 - 90, cy + 4,
                              cx + col_w - 24, cy + 38),
                       chp_str, chip_color, chip_f)
            cy += 56

    brand.draw_footer(img, draw, when, H)
    return img


def caption(data: dict, when: dt.datetime) -> str:
    parts = [f"<b>MCX Commodities</b> · {when.strftime('%I:%M %p, %d %b')}"]
    if data["gainers"]:
        g = data["gainers"][0]
        parts.append(f"Top gainer: <b>{g['company']}</b> "
                     f"{brand.fmt_pct(g['chp'])} @ ₹{brand.fmt_num(g['lp'])}")
    if data["losers"]:
        l = data["losers"][0]
        parts.append(f"Top loser: <b>{l['company']}</b> "
                     f"{brand.fmt_pct(l['chp'])} @ ₹{brand.fmt_num(l['lp'])}")
    parts.append("\n<i>myfinancial.in</i>")
    return "\n".join(parts)


def main() -> int:
    when = dt.datetime.now(IST)
    data = collect()
    if not data["all"]:
        print("No commodity data — aborting Telegram post", file=sys.stderr)
        return 1
    img = render(data, when)
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"commodities_{when:%Y-%m-%d_%H%M}.png"
    img.save(path, "PNG", optimize=True)
    print(f"Saved {path}")
    try:
        import page_export
        page_export.export("commodities", f"Commodities Snapshot — {when:%d %b %Y}",
                           when, path, caption(data, when))
    except Exception as e:
        print(f"page_export failed (non-fatal): {e}", file=sys.stderr)
    ok = brand.post_telegram(path, caption(data, when))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
