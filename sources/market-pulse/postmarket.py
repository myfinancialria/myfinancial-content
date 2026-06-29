"""Post-market wrap report at 16:00 IST.

Day's recap: closing levels with day's range, sector winners/losers,
top 5 Nifty 500 gainers/losers (closing %), India VIX close, brief
global cues hint.

Uses Fyers for India data, yfinance for global cues. Workflow runs
auto_login.py first.
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
import nifty500

IST = ZoneInfo("Asia/Kolkata")
HERE = Path(__file__).parent
TOKEN_PATH = HERE / "access_token.txt"
OUT_DIR = HERE / "out"

CLIENT_ID = os.environ["FYERS_CLIENT_ID"]

HEADLINE_INDICES = [
    ("NIFTY 50", ["NSE:NIFTY50-INDEX"]),
    ("BANK NIFTY", ["NSE:NIFTYBANK-INDEX"]),
    ("MIDCAP 100", ["NSE:NIFTYMIDCAP100-INDEX", "NSE:NIFTYMID100-INDEX"]),
    ("SMLCAP 100", ["NSE:NIFTYSMLCAP100-INDEX", "NSE:NIFTYSML100-INDEX"]),
]
VIX = "NSE:INDIAVIX-INDEX"
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

GLOBAL_CUES = [
    ("S&P FUT", "ES=F"),
    ("FTSE 100", "^FTSE"),
    ("BRENT", "BZ=F"),
]


def _client() -> fyersModel.FyersModel:
    if not TOKEN_PATH.exists():
        sys.exit("access_token.txt missing — run auto_login.py first")
    return fyersModel.FyersModel(
        client_id=CLIENT_ID, token=TOKEN_PATH.read_text().strip(),
        log_path="")


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
                "high": float(v.get("high_price") or 0),
                "low": float(v.get("low_price") or 0),
                "prev_close": float(v.get("prev_close_price") or 0),
            }
        time.sleep(0.2)
    return out


def fetch_yf(ticker: str) -> dict:
    try:
        h = yf.Ticker(ticker).history(period="5d", auto_adjust=False)
        if len(h) < 2:
            return {}
        last = float(h["Close"].iloc[-1])
        prev = float(h["Close"].iloc[-2])
        return {"lp": last, "chp": (last - prev) / prev * 100 if prev else 0}
    except Exception as e:
        print(f"yf {ticker} failed: {e}", file=sys.stderr)
        return {}


def collect() -> dict:
    fyers = _client()

    # Indices + sectors + VIX in one shot
    idx_syms: list[str] = []
    for _, syms in HEADLINE_INDICES:
        idx_syms.extend(syms)
    idx_syms.append(VIX)
    idx_syms.extend(s for _, s in SECTORS)
    print(f"Fetching {len(idx_syms)} index symbols...")
    idx_q = fetch_quotes(fyers, idx_syms)

    def first_hit(candidates):
        for c in candidates:
            q = idx_q.get(c, {})
            if q.get("lp"):
                return q
        return {}

    indices = []
    for label, syms in HEADLINE_INDICES:
        q = first_hit(syms)
        indices.append({"name": label, **q})
    vix_q = idx_q.get(VIX, {})

    sectors = [{"name": lbl, **idx_q.get(sym, {})} for lbl, sym in SECTORS
               if idx_q.get(sym, {}).get("lp")]
    sectors.sort(key=lambda x: x.get("chp", 0), reverse=True)

    # Nifty 500 closing data
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
            "lp": q["lp"], "chp": q["chp"], "ch": q.get("ch", 0),
        })
    rows.sort(key=lambda x: x["chp"], reverse=True)

    # Market breadth (advances vs declines)
    advances = sum(1 for r in rows if r["chp"] > 0)
    declines = sum(1 for r in rows if r["chp"] < 0)

    # Global cues (yfinance)
    print("Fetching global cues...")
    cues = [{"name": n, **fetch_yf(t)} for n, t in GLOBAL_CUES]

    return {
        "indices": indices,
        "vix": vix_q,
        "sectors": sectors,
        "sector_gainers": sectors[:3],
        "sector_losers": list(reversed(sectors[-3:])),
        "gainers": rows[:5],
        "losers": list(reversed(rows[-5:])),
        "breadth": {"adv": advances, "dec": declines, "total": len(rows)},
        "cues": cues,
    }


# ---- Rendering ----
W = brand.W
H = 1740


def render(data: dict, when: dt.datetime) -> Image.Image:
    img = Image.new("RGB", (W, H), brand.LIGHT_BG)
    draw = ImageDraw.Draw(img)

    title_f = brand.font(38, bold=True)
    h_f = brand.font(26, bold=True)
    body_f = brand.font(24)
    small_f = brand.font(20)
    big_f = brand.font(34, bold=True)

    header_bottom = brand.draw_header(
        img, draw, "Market Wrap",
        when.strftime("%I:%M %p · %a, %d %b · Closing"))

    # ---- Indices with day's range ----
    y0 = header_bottom + 25
    card_w = (W - 80 - 30) // 4
    for i, idx in enumerate(data["indices"]):
        x = 40 + i * (card_w + 10)
        brand.panel(draw, (x, y0, x + card_w, y0 + 170))
        draw.text((x + 16, y0 + 14), idx["name"],
                   fill=brand.MUTED, font=small_f)
        draw.text((x + 16, y0 + 42), brand.fmt_num(idx.get("lp", 0)),
                   fill=brand.DARK_TEXT, font=big_f)
        draw.text((x + 16, y0 + 88), brand.fmt_pct(idx.get("chp", 0)),
                   fill=brand.pct_color(idx.get("chp", 0)), font=h_f)
        # Day's range
        if idx.get("high"):
            range_text = (f"H {brand.fmt_num(idx['high'])}  "
                          f"L {brand.fmt_num(idx.get('low', 0))}")
            range_fit = brand.fit(draw, range_text, small_f, card_w - 32)
            draw.text((x + 16, y0 + 130), range_fit,
                       fill=brand.MUTED, font=small_f)

    # ---- VIX + breadth ----
    y_meta = y0 + 170 + 16
    draw.text((40, y_meta), "INDIA VIX",
               fill=brand.MUTED, font=small_f)
    vix = data["vix"]
    if vix:
        draw.text((180, y_meta), brand.fmt_num(vix.get("lp", 0)),
                   fill=brand.DARK_TEXT, font=h_f)
        draw.text((300, y_meta), brand.fmt_pct(vix.get("chp", 0)),
                   fill=brand.pct_color(-vix.get("chp", 0)), font=body_f)
    # Breadth
    br = data["breadth"]
    breadth_text = (f"Adv {br['adv']} · Dec {br['dec']}  "
                    f"({br['total']} stocks)")
    bb = draw.textbbox((0, 0), breadth_text, font=body_f)
    draw.text((W - 40 - (bb[2] - bb[0]), y_meta),
               breadth_text, fill=brand.DARK_TEXT, font=body_f)

    # ---- Top movers (two-column tables) ----
    y_mov = y_meta + 50
    panel_w = (W - 40 * 2 - 20) // 2
    panel_h = 380

    gain_rows = [{"name": r["company"], "sub": r["sector"],
                  "lp": r["lp"], "ch": r["ch"], "chp": r["chp"]}
                 for r in data["gainers"]]
    lose_rows = [{"name": r["company"], "sub": r["sector"],
                  "lp": r["lp"], "ch": r["ch"], "chp": r["chp"]}
                 for r in data["losers"]]
    brand.movers_table(draw, "Top Gainers · Today", gain_rows,
                        40, y_mov, panel_w, panel_h, brand.GREEN)
    brand.movers_table(draw, "Top Losers · Today", lose_rows,
                        40 + panel_w + 20, y_mov, panel_w, panel_h,
                        brand.RED)

    # ---- Sectors (top 3 / bottom 3) ----
    y_sec = y_mov + panel_h + 24
    sec_h = 200
    brand.panel(draw, (40, y_sec, W - 40, y_sec + sec_h))
    draw.rounded_rectangle((40, y_sec, W - 40, y_sec + 46),
                            radius=16, fill=brand.NAVY)
    draw.rectangle((40, y_sec + 22, W - 40, y_sec + 46), fill=brand.NAVY)
    draw.text((64, y_sec + 12), "Sectors — winners & losers",
               fill=(255, 255, 255), font=h_f)

    def sec_row(label: str, rows: list[dict], y: int, color: tuple):
        draw.text((64, y), label, fill=color, font=body_f)
        for j, s in enumerate(rows[:3]):
            x = 220 + j * 260
            brand.chip(draw, (x, y - 2, x + 240, y + 32),
                       f"{s['name']}  {brand.fmt_pct(s.get('chp', 0))}",
                       color, brand.font(20, bold=True))
    sec_row("Gainers", data["sector_gainers"], y_sec + 80, brand.GREEN)
    sec_row("Losers", data["sector_losers"], y_sec + 140, brand.RED)

    # ---- Next-session global cues ----
    y_cue = y_sec + sec_h + 24
    cue_h = 150
    brand.panel(draw, (40, y_cue, W - 40, y_cue + cue_h))
    draw.text((64, y_cue + 18),
               "Global cues for next session",
               fill=brand.NAVY, font=h_f)
    cy = y_cue + 70
    cue_col_w = (W - 80) // 3
    for i, c in enumerate(data["cues"]):
        cx = 40 + i * cue_col_w
        draw.text((cx + 24, cy), c["name"],
                   fill=brand.MUTED, font=small_f)
        if c.get("lp"):
            draw.text((cx + 24, cy + 26),
                       brand.fmt_num(c["lp"]),
                       fill=brand.DARK_TEXT, font=body_f)
            draw.text((cx + 24 + 130, cy + 30),
                       brand.fmt_pct(c.get("chp", 0)),
                       fill=brand.pct_color(c.get("chp", 0)),
                       font=body_f)

    # Footer
    brand.draw_footer(img, draw, when, H)
    return img


def caption(data: dict, when: dt.datetime) -> str:
    n50 = next((i for i in data["indices"] if i["name"] == "NIFTY 50"), {})
    bn = next((i for i in data["indices"] if i["name"] == "BANK NIFTY"), {})
    parts = [
        f"<b>Market Wrap</b> · {when.strftime('%I:%M %p, %d %b')}",
        f"NIFTY 50 <b>{brand.fmt_num(n50.get('lp', 0))}</b> "
        f"({brand.fmt_pct(n50.get('chp', 0))})",
        f"BANK NIFTY <b>{brand.fmt_num(bn.get('lp', 0))}</b> "
        f"({brand.fmt_pct(bn.get('chp', 0))})",
    ]
    br = data["breadth"]
    parts.append(f"Breadth: {br['adv']} adv · {br['dec']} dec")
    if data["sector_gainers"]:
        sg = data["sector_gainers"][0]
        parts.append(f"Best sector: <b>{sg['name']}</b> "
                     f"{brand.fmt_pct(sg.get('chp', 0))}")
    parts.append("\n<i>myfinancial.in</i>")
    return "\n".join(parts)


def main() -> int:
    when = dt.datetime.now(IST)
    data = collect()
    img = render(data, when)
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"postmarket_{when:%Y-%m-%d_%H%M}.png"
    img.save(path, "PNG", optimize=True)
    print(f"Saved {path}")
    try:
        import page_export
        page_export.export("post-market", f"Market Wrap — {when:%d %b %Y}",
                           when, path, caption(data, when))
    except Exception as e:
        print(f"page_export failed (non-fatal): {e}", file=sys.stderr)
    ok = brand.post_telegram(path, caption(data, when))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
