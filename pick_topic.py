"""Pick today's article topic from scraped competitor content.

Heuristic v1:
  1. Score each article by relevance to the myfinancial audience
     (15L+ earners + NRIs: tax, MF, retirement, NPS, EPF, estate, NRI rules).
  2. Cluster near-duplicates by stem-keywords.
  3. SKIP topics covered in the last 7 days (see topic_history.json).
  4. Pick the highest-scoring un-skipped cluster's representative article.
  5. Append the pick to topic_history.json.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from collections import Counter
from pathlib import Path

DATA = Path(__file__).parent / "data"
RAW = DATA / "raw_articles.json"
TOPICS_DIR = DATA / "topics"

# If CATEGORY env var is set, write per-category JSON; otherwise stay
# backward-compatible and write the single today_topic.json
CATEGORY = (os.environ.get("CATEGORY") or "").strip().lower() or None
TOPIC = (TOPICS_DIR / f"{CATEGORY}.json") if CATEGORY \
    else (DATA / "today_topic.json")
HISTORY = (DATA / f"topic_history_{CATEGORY}.json") if CATEGORY \
    else (DATA / "topic_history.json")

RECENT_DAYS = 7      # block any topic whose stem overlaps a pick in this window
HISTORY_MAX = 60     # keep at most this many entries (≈ 2 months)
STEM_OVERLAP_MIN = 2 # 2+ shared keywords → consider it the same topic

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


def load_history() -> list[dict]:
    if not HISTORY.exists():
        return []
    try:
        return json.loads(HISTORY.read_text())
    except Exception:
        return []


def save_history(history: list[dict]) -> None:
    HISTORY.write_text(json.dumps(history[-HISTORY_MAX:], indent=2))


def is_recent_topic(stem: str, history: list[dict]) -> tuple[bool, str | None]:
    """Return (blocked, blocking_title) — True if stem overlaps any pick in the last RECENT_DAYS."""
    cutoff = (dt.date.today() - dt.timedelta(days=RECENT_DAYS)).isoformat()
    new_words = set(stem.split())
    for h in history:
        if h.get("date", "") < cutoff:
            continue
        old_words = set((h.get("stem") or "").split())
        if len(new_words & old_words) >= STEM_OVERLAP_MIN:
            return True, h.get("title", "")
    return False, None


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
    # When a CATEGORY is requested, only consider articles tagged with it
    if CATEGORY:
        arts = [a for a in arts if a.get("category") == CATEGORY]
        print(f"Category={CATEGORY}: {len(arts)} candidates after filter")
        if not arts:
            print(f"No articles for category {CATEGORY} — skipping pick")
            return 1
    ranked = sorted(((score(a), a) for a in arts),
                    key=lambda x: x[0], reverse=True)

    history = load_history()
    skipped: list[str] = []

    # Cluster by stem-key; keep the highest-scoring un-skipped representative
    seen = set()
    clusters: list[tuple[int, dict, list[dict], str]] = []
    for s, a in ranked:
        k = stem_key(a["title"])
        if k in seen or s <= 0:
            continue
        seen.add(k)
        blocked, blocker = is_recent_topic(k, history)
        if blocked:
            skipped.append(f"  - [{s}] {a['title'][:80]}  (overlaps recent: {blocker[:60]})")
            continue
        related = [r for sc, r in ranked
                   if r is not a and len(set(stem_key(r["title"]).split())
                                         & set(k.split())) >= 2][:5]
        clusters.append((s, a, related, k))

    if skipped:
        print(f"Skipped {len(skipped)} topic(s) covered in last {RECENT_DAYS} days:")
        for line in skipped[:5]:
            print(line)

    if not clusters:
        print("No fresh topic — falling back to top-scored item (may repeat).")
        if not ranked:
            return 1
        s, a = ranked[0]
        clusters = [(s, a, [], stem_key(a["title"]))]

    top_s, top_a, related, top_stem = clusters[0]
    print(f"Picked: [{top_s}] {top_a['title'][:100]}")
    print(f"Related: {len(related)} articles")

    # Append to history
    today = dt.date.today().isoformat()
    history.append({
        "date": today,
        "title": top_a["title"],
        "source": top_a.get("source"),
        "stem": top_stem,
        "score": top_s,
    })
    save_history(history)
    print(f"History now has {len(history)} entries")

    payload = {
        "picked_at": data.get("generated_at"),
        "score": top_s,
        "primary": top_a,
        "related": related,
        "shortlist": [{"score": s, "title": a["title"], "source": a["source"]}
                      for s, a in ranked[:10]],
    }
    TOPIC.parent.mkdir(parents=True, exist_ok=True)
    if CATEGORY:
        payload["category"] = CATEGORY
    TOPIC.write_text(json.dumps(payload, indent=2, default=str))
    print(f"Wrote {TOPIC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
