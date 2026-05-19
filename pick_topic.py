"""Pick today's article topic from scraped competitor content.

Heuristic v0:
  1. Score each article by relevance to the myfinancial audience
     (15L+ earners + NRIs: tax, MF, retirement, NPS, EPF, estate, NRI rules).
  2. Cluster near-duplicates by stem-keywords.
  3. Pick the highest-scoring cluster's representative article.
  4. Save the topic brief (title, angle, supporting links) for the writer.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

DATA = Path(__file__).parent / "data"
RAW = DATA / "raw_articles.json"
TOPIC = DATA / "today_topic.json"

# Keywords with weights — what *our* audience cares about
WEIGHTS = {
    # tax (high value — frequent search intent)
    "itr": 6, "tax": 5, "income tax": 5, "new tax regime": 6,
    "old tax regime": 6, "deduction": 4, "exemption": 4, "tds": 4,
    "capital gains": 6, "ltcg": 6, "stcg": 5, "dividend": 3, "tax saving": 5,
    # retirement / EPF / NPS
    "epf": 5, "ppf": 5, "nps": 5, "retirement": 5, "pension": 4,
    "gratuity": 4, "8th pay": 3,
    # investments
    "mutual fund": 5, "sip": 5, "elss": 5, "index fund": 4, "etf": 3,
    "equity": 4, "debt fund": 4, "gold": 3, "fixed deposit": 3, "fd": 3,
    "real estate": 4, "reit": 3, "smallcap": 3, "midcap": 3,
    # NRI angle
    "nri": 8, "fcnr": 6, "nre": 6, "nro": 6, "remittance": 5,
    "dtaa": 6, "lrs": 4, "repatriation": 5, "gulf": 4,
    # estate / planning
    "will": 5, "succession": 5, "nominee": 4, "estate planning": 5,
    "inheritance": 5,
    # protection
    "insurance": 4, "term plan": 5, "health insurance": 5, "mediclaim": 4,
    # personal finance basics
    "credit card": 3, "loan": 3, "home loan": 4, "credit score": 3,
    "scam": 5, "fraud": 4,
    # govt schemes (high engagement)
    "sukanya": 4, "scss": 3, "pmvvy": 3, "aadhaar": 3,
}

# Boilerplate/sponsored words → downweight
NEGATIVE = {"sponsored", "advertorial", "horoscope", "predictions",
            "lottery", "actress", "actor"}


def score(article: dict) -> int:
    text = (article.get("title", "") + " " + article.get("summary", "")).lower()
    s = 0
    for kw, w in WEIGHTS.items():
        if kw in text:
            s += w
    for kw in NEGATIVE:
        if kw in text:
            s -= 10
    # Prefer how-to / explainer angles
    if any(k in text for k in ("how", "what is", "explained", "guide",
                                "step by step", "should you", "stepwise")):
        s += 3
    return s


def stem_key(title: str) -> str:
    """Crude topic fingerprint — strip stopwords + numbers."""
    stop = {"the", "a", "an", "of", "to", "in", "is", "for", "with",
            "and", "or", "on", "your", "you", "by", "from", "be",
            "are", "this", "that", "as", "at", "all", "but"}
    words = re.findall(r"[a-zA-Z]+", title.lower())
    keep = [w for w in words if w not in stop and len(w) > 2]
    return " ".join(sorted(keep[:5]))


def main() -> int:
    if not RAW.exists():
        print("raw_articles.json missing — run scrape_sources.py first")
        return 1
    data = json.loads(RAW.read_text())
    arts = data.get("articles", [])
    ranked = sorted(((score(a), a) for a in arts),
                    key=lambda x: x[0], reverse=True)

    # Cluster by stem-key; keep the highest-scoring representative
    seen = set()
    clusters: list[tuple[int, dict, list[dict]]] = []
    for s, a in ranked:
        k = stem_key(a["title"])
        if k in seen or s <= 0:
            continue
        seen.add(k)
        related = [r for sc, r in ranked
                   if r is not a and len(set(stem_key(r["title"]).split())
                                         & set(k.split())) >= 2][:5]
        clusters.append((s, a, related))

    if not clusters:
        print("No relevant topic found — falling back to top-scored item")
        if not ranked:
            return 1
        s, a = ranked[0]
        clusters = [(s, a, [])]

    top_s, top_a, related = clusters[0]
    print(f"Picked: [{top_s}] {top_a['title'][:100]}")
    print(f"Related: {len(related)} articles")

    payload = {
        "picked_at": data.get("generated_at"),
        "score": top_s,
        "primary": top_a,
        "related": related,
        "shortlist": [{"score": s, "title": a["title"], "source": a["source"]}
                      for s, a in ranked[:10]],
    }
    TOPIC.write_text(json.dumps(payload, indent=2, default=str))
    print(f"Wrote {TOPIC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
