"""Fact-check the day's article using Gemini with Google Search grounding.

What it does:
  1. Reads the freshly-written article markdown.
  2. Asks Gemini (with Google Search tool enabled) to extract 5-8 specific
     factual claims and verify each against live web sources — preferring
     RBI, SEBI, Income Tax India, AMFI, EPFO, IRDAI, PFRDA, MoF.
  3. Writes data/fact_check.json with a status per claim
     (verified / unsure / likely_wrong) plus the cited URL.

This is non-blocking — it doesn't gate the publish step. v2 will
auto-rewrite flagged paragraphs.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests

HERE = Path(__file__).parent
DATA = HERE / "data"
ARTS = HERE / "articles"
META = DATA / "article.json"
REPORT = DATA / "fact_check.json"

SYSTEM = (
    "You are a meticulous fact-checker for an Indian personal-finance "
    "publication. You verify claims by searching authoritative Indian "
    "government and regulatory sources: incometax.gov.in, rbi.org.in, "
    "sebi.gov.in, amfiindia.com, epfindia.gov.in, npstrust.org.in, "
    "irdai.gov.in, pfrda.org.in, finmin.nic.in. Be conservative — when in "
    "doubt, mark as 'unsure', not 'verified'."
)

USER_PROMPT = """Article (Markdown) to fact-check:

----- BEGIN ARTICLE -----
{article}
----- END ARTICLE -----

Do the following:

1. Extract 5 to 8 SPECIFIC factual claims that, if wrong, would mislead a reader.
   Prefer claims that include: a number, a date, a tax section, a percentage,
   a regulatory rule, or a named scheme.
   IGNORE generic statements ("investors should be careful") or value
   judgements — only check verifiable facts.

2. For each claim, use Google Search to verify against authoritative sources
   (prioritise the regulator/official portal for that topic).

3. Output a single JSON object — no preamble, no markdown fences — matching:

{{
  "summary": "<one sentence: how reliable is this article overall?>",
  "verdict": "ship | review | rewrite",
  "claims": [
    {{
      "claim": "<exact claim from the article, verbatim or near-verbatim>",
      "status": "verified | unsure | likely_wrong",
      "source": "<URL of the authoritative source you checked>",
      "note": "<one-line explanation. If likely_wrong, state what's correct.>"
    }}
  ]
}}

Rules for verdict:
- "ship"     = all claims verified or only ≤1 unsure
- "review"   = 2+ unsure, no likely_wrong
- "rewrite"  = any claim is likely_wrong

Output ONLY the JSON object. No code fences. No commentary."""


def call_gemini_grounded(article_md: str) -> dict | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY not set — skipping fact-check", file=sys.stderr)
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    payload: dict[str, Any] = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user",
                      "parts": [{"text": USER_PROMPT.format(article=article_md)}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 24000,
            # Structured fact-check doesn't need reasoning tokens
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    try:
        r = requests.post(url, json=payload, timeout=180)
        r.raise_for_status()
        j = r.json()
    except Exception as e:
        print(f"Fact-check HTTP failed: {e}", file=sys.stderr)
        return None
    try:
        text = j["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"Unexpected response shape: {e}", file=sys.stderr)
        print(json.dumps(j)[:800], file=sys.stderr)
        return None

    # Always save raw response for debug
    (DATA / "fact_check_raw.txt").write_text(text)

    # Strip code-fence wrapping if model added it
    cleaned = re.sub(r"^```(?:json)?\s*", "", text)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find the first complete JSON object in the response
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError as e:
                print(f"JSON salvage failed: {e}", file=sys.stderr)
        print(f"Raw response saved to {DATA / 'fact_check_raw.txt'}", file=sys.stderr)
        print(cleaned[:600], file=sys.stderr)
        return None


def load_article_body() -> tuple[str, dict] | None:
    if not META.exists():
        print("article.json missing", file=sys.stderr)
        return None
    meta = json.loads(META.read_text())
    md_path = ARTS / meta["filename"]
    if not md_path.exists():
        print(f"Article md not found: {md_path}", file=sys.stderr)
        return None
    body = re.sub(r"^---\n[\s\S]+?\n---\n+", "", md_path.read_text(), count=1)
    return body, meta


def main() -> int:
    loaded = load_article_body()
    if not loaded:
        return 1
    body, meta = loaded
    print(f"Fact-checking: {meta['title'][:80]}")
    report = call_gemini_grounded(body)
    if not report:
        return 1

    n = len(report.get("claims", []))
    counts: dict[str, int] = {}
    for c in report.get("claims", []):
        counts[c.get("status", "unknown")] = counts.get(c.get("status", "unknown"), 0) + 1
    print(f"Checked {n} claims — {counts}")
    print(f"Verdict: {report.get('verdict')}  ·  {report.get('summary')}")

    report["article_slug"] = meta.get("slug")
    report["article_title"] = meta.get("title")
    REPORT.write_text(json.dumps(report, indent=2, default=str))

    # Also stash into article.json so publish can show a badge
    meta["fact_check"] = {
        "verdict": report.get("verdict"),
        "summary": report.get("summary"),
        "claim_count": n,
        "counts": counts,
    }
    META.write_text(json.dumps(meta, indent=2, default=str))
    print(f"Wrote {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
