"""Results published in the last 24 hours.

Fetches NSE corporate announcements for the last 24h, filters to 'Financial
Result' subjects, looks up today's closing prices via Fyers (best-effort),
formats as a Telegram digest with title + per-company section.

Runs at 5 PM IST. Posts directly to Telegram — no Pages publish.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

import market_data as md

HERE = Path(__file__).parent
OUT_DIR = HERE / "data" / "snapshots"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NSE_ANNOUNCEMENTS_URL = (
    "https://www.nseindia.com/api/corporate-announcements"
    "?index=equities&from_date={fr}&to_date={to}"
)
MAX_ITEMS = 25


def fetch_results_last24h() -> list[dict]:
    """Return announcements with subject containing 'Result' in the last 24h."""
    now = dt.datetime.now()
    fr = (now - dt.timedelta(hours=24)).strftime("%d-%m-%Y")
    to = now.strftime("%d-%m-%Y")
    try:
        s = md._nse_session()
        r = s.get(NSE_ANNOUNCEMENTS_URL.format(fr=fr, to=to), timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"NSE announcements fetch failed: {e}", file=sys.stderr)
        return []
    rows = data.get("data") if isinstance(data, dict) else data
    out: list[dict] = []
    for d in rows or []:
        subject = (d.get("desc") or d.get("subject")
                   or d.get("attchmntText") or "")
        if not re.search(r"\bresult\b|\bfinancial result\b|quarterly",
                          subject, re.I):
            continue
        sym = (d.get("symbol") or d.get("sym") or "").strip().upper()
        if not sym:
            continue
        out.append({
            "symbol": sym,
            "subject": subject.strip()[:160],
            "broadcast_at": (d.get("an_dt") or d.get("dt")
                              or d.get("broadcastdate") or "").strip(),
            "attachment": d.get("attchmntFile") or d.get("file") or "",
        })
    # Dedupe by symbol (keep first / most recent)
    seen, dedup = set(), []
    for a in out:
        if a["symbol"] in seen:
            continue
        seen.add(a["symbol"])
        dedup.append(a)
    return dedup[:MAX_ITEMS]


def fetch_prices(symbols: list[str]) -> dict[str, dict]:
    if not symbols:
        return {}
    try:
        fyers = md.fyers_client()
    except SystemExit:
        return {}
    return md.fyers_quotes(fyers, [f"NSE:{s}-EQ" for s in symbols])


def build_telegram_message(rows: list[dict],
                            quotes: dict[str, dict],
                            when: dt.datetime) -> list[str]:
    """Return list of message chunks (each ≤ 3800 chars, ready to send)."""
    header = (f"📊 <b>Results published in last 24h</b>\n"
              f"<i>Snapshot: {when.strftime('%I:%M %p IST, %d %b %Y')}</i>\n"
              f"Total companies: {len(rows)}\n\n")
    if not rows:
        return [header + "No fresh results in the last 24 hours."]

    lines = [header]
    for r in rows:
        sym = r["symbol"]
        q = quotes.get(f"NSE:{sym}-EQ", {})
        lp = q.get("lp", 0)
        chp = q.get("chp", 0)
        emoji = "🟢" if chp > 0 else "🔴" if chp < 0 else "⚪"
        subject = r["subject"]
        line = f"{emoji} <b>{sym}</b>"
        if lp:
            line += (f" — ₹{lp:,.2f} "
                     f"({'+' if chp >= 0 else ''}{chp:.2f}%)")
        line += f"\n<i>{subject[:140]}</i>\n"
        lines.append(line)

    lines.append("\n<i>Data: NSE corporate announcements + Fyers quotes</i>")

    # Chunk into ≤3800 char messages
    chunks: list[str] = []
    current = ""
    for piece in lines:
        if len(current) + len(piece) + 2 > 3800:
            chunks.append(current)
            current = piece
        else:
            current += "\n" + piece if current else piece
    if current:
        chunks.append(current)
    return chunks


def post_telegram(chunks: list[str]) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set", file=sys.stderr)
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for i, msg in enumerate(chunks):
        try:
            r = requests.post(url, json={
                "chat_id": chat_id, "text": msg, "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }, timeout=30)
            if r.status_code == 429:
                wait = r.json().get("parameters", {}).get("retry_after", 5)
                time.sleep(wait + 1)
                r = requests.post(url, json={
                    "chat_id": chat_id, "text": msg, "parse_mode": "HTML",
                    "disable_web_page_preview": True}, timeout=30)
            if not r.ok:
                print(f"Telegram chunk {i+1}/{len(chunks)} failed: "
                      f"{r.status_code} {r.text[:200]}", file=sys.stderr)
                return False
            print(f"✓ chunk {i+1}/{len(chunks)} sent "
                  f"(msg_id {r.json().get('result', {}).get('message_id')})")
            time.sleep(1.1)
        except Exception as e:
            print(f"Telegram send error: {e}", file=sys.stderr)
            return False
    return True


def main() -> int:
    when = dt.datetime.now()
    print(f"Fetching announcements ({when.strftime('%I:%M %p IST')})...")
    rows = fetch_results_last24h()
    print(f"  -> {len(rows)} results in last 24h")
    quotes = fetch_prices([r["symbol"] for r in rows])
    chunks = build_telegram_message(rows, quotes, when)
    snap = {
        "fetched_at": when.isoformat(),
        "count": len(rows),
        "rows": rows,
        "messages": chunks,
    }
    (OUT_DIR / "results_today.json").write_text(
        json.dumps(snap, indent=2, default=str))
    ok = post_telegram(chunks)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
