"""Assign each scraped article to one of 5 myfinancial content categories.

Reads data/raw_articles.json (written by scrape_sources.py), adds a `category`
field to each article (or None if no strong match), and writes back to the
same file.

Categories:
  - pre_market       — overnight cues, opening preview, GIFT Nifty, Asia open
  - post_market      — closing wrap, sectors, end-of-day recap
  - result_analysis  — quarterly results, corporate earnings deep-dives
  - macro            — RBI/SEBI/Fed/inflation/GDP/budget/policy
  - personal_finance — tax, MF, EPF, NPS, retirement, NRI, estate, insurance
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DATA = Path(__file__).parent / "data"
RAW = DATA / "raw_articles.json"

CATEGORY_KEYWORDS: dict[str, dict[str, int]] = {
    "pre_market": {
        "pre-market": 6, "premarket": 6, "pre market": 6,
        "opening bell": 5, "market open": 4, "gift nifty": 5,
        "sgx nifty": 4, "today's market": 3, "asia markets": 3,
        "overnight": 3, "morning brief": 4, "what to watch": 3,
    },
    "post_market": {
        "closing bell": 6, "market close": 6, "closed in": 5,
        "closing": 5, "market wrap": 6, "today's close": 5,
        "sensex closed": 5, "nifty closed": 5, "end of day": 4,
        "eod": 3, "session close": 4,
    },
    "result_analysis": {
        "results": 4, "quarterly results": 6, "quarterly": 4,
        "earnings": 5, "q1 fy": 5, "q2 fy": 5, "q3 fy": 5, "q4 fy": 5,
        "q1fy": 5, "q2fy": 5, "q3fy": 5, "q4fy": 5,
        "net profit": 4, "revenue beat": 4, "profit beat": 4,
        "guidance": 3, "margin": 2, "topline": 3, "bottomline": 3,
        "results announcement": 5, "board meeting": 2,
    },
    "macro": {
        "rbi": 6, "sebi": 5, "monetary policy": 6, "mpc": 5,
        "repo rate": 6, "inflation": 5, "cpi": 5, "wpi": 4,
        "gdp": 5, "iip": 4, "fiscal deficit": 4, "current account": 3,
        "trade deficit": 3, "fed": 4, "fomc": 4, "ecb": 3,
        "budget": 4, "finance minister": 4, "fiscal": 3, "policy rate": 4,
        "rate cut": 5, "rate hike": 5,
    },
    "personal_finance": {
        "income tax": 5, "itr": 6, "tax saving": 5, "new tax regime": 6,
        "old tax regime": 6, "tds": 4, "capital gains": 5,
        "ltcg": 5, "stcg": 5, "mutual fund": 5, "sip": 5, "elss": 5,
        "epf": 6, "ppf": 5, "nps": 6, "nri": 7, "fcnr": 5, "nre": 5,
        "nro": 5, "retirement": 5, "pension": 4, "insurance": 4,
        "term plan": 5, "health insurance": 5, "estate planning": 5,
        "will": 4, "succession": 4, "credit score": 3, "home loan": 4,
        "credit card": 3, "personal finance": 5, "financial planning": 4,
        "lrs": 4, "dtaa": 5, "remittance": 4,
    },
}


# Some sources are category-typed by their nature — strong prior
SOURCE_HINTS: dict[str, str] = {
    "Dhan Closing Bell": "post_market",
}

# URL slug fragments that strongly indicate a category
URL_HINTS: dict[str, str] = {
    "closing-bell": "post_market",
    "market-today": "post_market",
    "market-wrap": "post_market",
    "market-recap": "post_market",
    "pre-market": "pre_market",
    "premarket": "pre_market",
    "morning-brief": "pre_market",
    "opening-bell": "pre_market",
    "today-stocks-to-buy": "pre_market",
    "stocks-to-watch": "pre_market",
    "results-": "result_analysis",
    "quarterly-results": "result_analysis",
    "/results/": "result_analysis",
    "rbi-": "macro",
    "monetary-policy": "macro",
    "inflation": "macro",
    "gdp": "macro",
}


def categorize(article: dict) -> tuple[str | None, int]:
    """Return (category, score) — best-matching category and its score.

    Tries three signals in order:
      1. Source name hint (e.g. 'Dhan Closing Bell' → post_market)
      2. URL slug hint (e.g. '/closing-bell-21st-may/' → post_market)
      3. Title/summary keyword scoring
    Returns (None, 0) if all three fail to produce a confident match.
    """
    source = (article.get("source") or "").strip()
    if source in SOURCE_HINTS:
        return SOURCE_HINTS[source], 10

    link = (article.get("link") or "").lower()
    for frag, cat in URL_HINTS.items():
        if frag in link:
            return cat, 8

    text = (article.get("title", "") + " "
            + article.get("summary", "")).lower()
    scores: dict[str, int] = {}
    for cat, weights in CATEGORY_KEYWORDS.items():
        s = sum(w for kw, w in weights.items() if kw in text)
        if s > 0:
            scores[cat] = s
    if not scores:
        return None, 0
    best = max(scores, key=scores.get)
    return (best, scores[best]) if scores[best] >= 3 else (None, scores[best])


def main() -> int:
    if not RAW.exists():
        print("raw_articles.json missing — run scrape_sources.py first",
              file=sys.stderr)
        return 1
    data = json.loads(RAW.read_text())
    arts = data.get("articles", [])

    counts: dict[str | None, int] = {}
    for a in arts:
        cat, sc = categorize(a)
        a["category"] = cat
        a["category_score"] = sc
        counts[cat] = counts.get(cat, 0) + 1

    data["articles"] = arts
    RAW.write_text(json.dumps(data, indent=2, default=str))

    print("Categorized:")
    for cat, n in sorted(counts.items(), key=lambda x: (x[0] is None, x[0] or "")):
        print(f"  {cat or '<uncategorized>'}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
