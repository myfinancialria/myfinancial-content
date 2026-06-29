"""Rank news items by market-impact importance using Gemini Flash.

Falls back to a heuristic scorer if GEMINI_API_KEY is unset or the API fails,
so the pipeline always produces output.

`rank(items, top_n=8)` returns the top N items in descending importance, each
with an added `score` (0-10) and `reason` field.
"""
from __future__ import annotations

import json
import os
import re
import sys

import requests

GEMINI_URL_TPL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={key}"
)

SYSTEM = (
    "You are a senior Indian equity-markets editor. Score each headline 0-10 "
    "for IMPORTANCE to a retail investor / NRI audience in India. Reward: "
    "RBI/SEBI policy, large-cap earnings beats/misses, M&A, regulatory action, "
    "macro data (GDP/CPI/IIP), index reshuffles, geopolitical shocks affecting "
    "Indian markets, large FII flows. Penalise: rumours, broker tips, "
    "individual stock-recommendation listicles, generic 'what to do' content, "
    "promo content, repeats. Respond with ONLY a JSON array of objects with "
    "keys 'i' (the input index, integer) and 's' (the score, integer 0-10) "
    "and 'r' (one-line reason, max 80 chars). No prose, no markdown fences."
)


_IMPORTANT_KEYWORDS = (
    "rbi", "sebi", "repo rate", "monetary policy", "mpc", "cpi", "wpi", "iip",
    "gdp", "budget", "finance minister", "fii", "fpi", "dii", "buyback",
    "merger", "acquisition", "demerger", "bonus", "split", "ipo", "qip",
    "results", "q1 ", "q2 ", "q3 ", "q4 ", "earnings", "profit", "revenue",
    "guidance", "sanctions", "tariff", "crude", "rupee", "10-year",
    "nifty 50", "sensex", "ban", "fraud", "default", "downgrade", "upgrade",
)

_LARGE_CAP_TICKERS = (
    "reliance", "tcs", "infosys", "hdfc", "icici", "sbi", "kotak", "axis",
    "bharti", "itc", "lt ", "l&t", "larsen", "hul", "asian paints", "maruti",
    "bajaj", "wipro", "adani", "tata motors", "tata steel", "ongc", "ntpc",
    "powergrid", "coal india", "ultracratech", "ultratech", "nestle",
    "titan", "sun pharma", "dr reddy", "cipla", "divis", "tech mahindra",
    "hcl", "jsw", "vedanta", "hindalco", "grasim", "britannia",
)

_PENALTY_KEYWORDS = (
    "buy these", "should you buy", "stocks to buy", "best stocks",
    "5 stocks", "10 stocks", "multibagger", "penny stock", "tip",
    "horoscope", "rashifal", "viral", "lifestyle",
)


def _heuristic_score(title: str, description: str) -> tuple[int, str]:
    """Quick fallback when LLM is unavailable."""
    text = f"{title} {description}".lower()
    score = 3
    hits = []
    for kw in _IMPORTANT_KEYWORDS:
        if kw in text:
            score += 1
            hits.append(kw)
    for kw in _LARGE_CAP_TICKERS:
        if kw in text:
            score += 1
            hits.append(kw)
            break
    for kw in _PENALTY_KEYWORDS:
        if kw in text:
            score -= 4
            hits.append(f"-{kw}")
    score = max(0, min(10, score))
    reason = ("matched: " + ", ".join(hits[:4])) if hits else "no signals"
    return score, reason


def _call_gemini(items: list[dict]) -> list[dict] | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = GEMINI_URL_TPL.format(model=model, key=key)

    # Build a numbered list (cap at ~50 so prompt stays small)
    capped = items[:50]
    lines = [f"{i}. [{a['source']}] {a['title']}" for i, a in enumerate(capped)]
    prompt = "\n".join(lines)
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "maxOutputTokens": 4000,
        },
    }
    try:
        r = requests.post(url, json=payload, timeout=60)
        if not r.ok:
            print(f"Gemini score HTTP {r.status_code}: {r.text[:200]}",
                  file=sys.stderr)
            return None
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        # Strip code-fence if Gemini added one
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        scored = json.loads(text)
        out = []
        for entry in scored:
            i = entry.get("i")
            if not isinstance(i, int) or not (0 <= i < len(capped)):
                continue
            item = dict(capped[i])
            item["score"] = int(entry.get("s", 0))
            item["reason"] = (entry.get("r") or "")[:120]
            out.append(item)
        return out
    except Exception as e:
        print(f"Gemini score call failed: {e}", file=sys.stderr)
        return None


def rank(items: list[dict], top_n: int = 8) -> list[dict]:
    if not items:
        return []
    scored = _call_gemini(items)
    if scored is None:
        print("score_news: using heuristic fallback")
        scored = []
        for a in items[:50]:
            s, r = _heuristic_score(a.get("title", ""), a.get("description", ""))
            a2 = dict(a)
            a2["score"] = s
            a2["reason"] = r
            scored.append(a2)
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    return scored[:top_n]


if __name__ == "__main__":
    sample = [
        {"source": "ET", "title": "RBI keeps repo rate unchanged at 6.5%",
         "description": "Monetary policy committee voted 5-1 to hold..."},
        {"source": "ET", "title": "5 multibagger stocks to buy this week",
         "description": "Top picks from brokers"},
    ]
    print(json.dumps(rank(sample, top_n=2), indent=2))
