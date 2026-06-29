"""Compose morning / evening digest from cached fetcher outputs.

Reads:
  data/results.json
  data/corp_actions.json
  data/news.json
  data/fiidii.json

Writes:
  data/digest_morning.json  — slot=morning
  data/digest_evening.json  — slot=evening

Each digest has structured text blocks that slack_post.py and telegram_post.py
both consume; the surfaces format them their own way.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

DATA = Path(__file__).parent / "data"


def _load(name: str) -> dict:
    p = DATA / name
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception as e:
        print(f"load {name} failed: {e}", file=sys.stderr)
        return {}


def _fmt_cr(amount: float) -> str:
    """₹ formatting in crores with sign."""
    sign = "+" if amount >= 0 else "-"
    return f"{sign}₹{abs(amount):,.0f} cr"


def _results_line(r: dict) -> str:
    return f"• *{r['company']}* ({r['symbol']}) — {r.get('purpose', 'Results')[:60]}"


def _corp_line(c: dict) -> str:
    return f"• *{c['company']}* ({c['symbol']}) — {c['type']}: {c['subject'][:80]}"


def _news_line(n: dict) -> str:
    src = n.get("source", "")
    title = n.get("title", "")
    link = n.get("link", "")
    return f"• *{title}* _{src}_\n  {link}"


def build_morning() -> dict:
    results = _load("results.json")
    corp = _load("corp_actions.json")
    news = _load("news.json")
    fiidii = _load("fiidii.json")

    today = dt.date.today().strftime("%a, %d %b %Y")
    blocks = []

    # Header
    blocks.append({"type": "header", "text": f"🌅 Morning Brief — {today}"})

    # Today's results
    todays_results = results.get("today", [])
    if todays_results:
        body = "\n".join(_results_line(r) for r in todays_results[:12])
        blocks.append({"type": "section", "title": "📊 Results expected today",
                       "text": body})

    # Today's ex-date corp actions
    todays_corp = corp.get("today", [])
    if todays_corp:
        body = "\n".join(_corp_line(c) for c in todays_corp[:10])
        blocks.append({"type": "section", "title": "🏷️ Ex-date today",
                       "text": body})

    # Top overnight news (top 5)
    top_news = news.get("top", [])[:5]
    if top_news:
        body = "\n".join(_news_line(n) for n in top_news)
        blocks.append({"type": "section", "title": "📰 Overnight news that matters",
                       "text": body})

    # Yesterday's FII/DII (1-line summary)
    hist = fiidii.get("cash", {}).get("history", [])
    if hist:
        last = hist[0]
        body = (f"FII: *{_fmt_cr(last['fii_net'])}*  |  "
                f"DII: *{_fmt_cr(last['dii_net'])}*  ({last['date']})")
        blocks.append({"type": "section", "title": "💰 Yesterday's flows",
                       "text": body})

    return {
        "slot": "morning",
        "date": today,
        "blocks": blocks,
    }


def build_evening() -> dict:
    results = _load("results.json")
    corp = _load("corp_actions.json")
    news = _load("news.json")
    fiidii = _load("fiidii.json")

    today = dt.date.today().strftime("%a, %d %b %Y")
    blocks = []

    # Header
    blocks.append({"type": "header", "text": f"🌇 Evening Wrap — {today}"})

    # Today's results that came out (same bucket)
    todays_results = results.get("today", [])
    if todays_results:
        body = "\n".join(_results_line(r) for r in todays_results[:12])
        blocks.append({"type": "section", "title": "📊 Results out today",
                       "text": body})

    # Upcoming results (next 7 days)
    upcoming_results = results.get("upcoming", [])
    if upcoming_results:
        # Show next 8, grouped by date
        body_lines = []
        cur_date = None
        for r in upcoming_results[:8]:
            d = r.get("date_iso", "")
            if d != cur_date:
                body_lines.append(f"_{d}_")
                cur_date = d
            body_lines.append(_results_line(r))
        blocks.append({"type": "section", "title": "🗓️ Results — next 7 days",
                       "text": "\n".join(body_lines)})

    # Today's FII/DII cash
    today_cash = fiidii.get("cash", {}).get("today", {})
    if today_cash:
        body = (f"*Cash:*  FII *{_fmt_cr(today_cash.get('fii_net', 0))}*  |  "
                f"DII *{_fmt_cr(today_cash.get('dii_net', 0))}*")
        # Derivatives
        deriv = fiidii.get("derivatives", {})
        if deriv.get("by_instrument"):
            lines = [body, ""]
            lines.append("*F&O (FII):*")
            for d in deriv["by_instrument"]:
                lines.append(f"• {d['instrument']}: *{_fmt_cr(d['net_cr'])}*")
            lines.append(f"_Total F&O net: {_fmt_cr(deriv.get('total_net_cr', 0))}_")
            body = "\n".join(lines)
        blocks.append({"type": "section", "title": "💰 FII / DII — today", "text": body})

    # 10-day FII/DII trend
    hist = fiidii.get("cash", {}).get("history", [])
    if len(hist) >= 2:
        body_lines = ["```", f"{'Date':<12}{'FII (cr)':>12}{'DII (cr)':>12}"]
        for h in hist[:10]:
            body_lines.append(
                f"{h['date']:<12}{h['fii_net']:>12,.0f}{h['dii_net']:>12,.0f}"
            )
        body_lines.append("```")
        blocks.append({"type": "section",
                       "title": "📈 FII / DII — last 10 sessions",
                       "text": "\n".join(body_lines)})

    # Top news of the day
    top_news = news.get("top", [])[:6]
    if top_news:
        body = "\n".join(_news_line(n) for n in top_news)
        blocks.append({"type": "section", "title": "📰 Today's important news",
                       "text": body})

    return {
        "slot": "evening",
        "date": today,
        "blocks": blocks,
    }


def main() -> int:
    morning = build_morning()
    evening = build_evening()
    (DATA / "digest_morning.json").write_text(json.dumps(morning, indent=2))
    (DATA / "digest_evening.json").write_text(json.dumps(evening, indent=2))
    print(f"Wrote {DATA}/digest_morning.json ({len(morning['blocks'])} blocks)")
    print(f"Wrote {DATA}/digest_evening.json ({len(evening['blocks'])} blocks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
