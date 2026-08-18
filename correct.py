"""Auto-correct the claims fact_check.py flagged, using Gemini + Google Search.

Pipeline position:
    write_*.py  →  fact_check.py  →  correct.py  →  publish.py

What it does:
  1. Reads data/fact_check[_CATEGORY].json and picks the claims that came back
     `likely_wrong` or `unsure`.
  2. Sends the article plus those claims (with the fact-checker's note and the
     authoritative source URL it found) back to Gemini with Google Search
     grounding, asking for SURGICAL find/replace edits — not a full rewrite.
  3. Applies only the edits whose `find` string matches the article verbatim,
     so a hallucinated anchor can never corrupt the file.
  4. Re-runs the grounded fact-check on the corrected body and updates both the
     report and article.json, so publish.py shows the post-correction verdict.

Env:
  CATEGORY          same semantics as fact_check.py (per-category meta/report)
  CORRECT_UNSURE=0  only fix `likely_wrong`; leave `unsure` claims alone
  CORRECT_RECHECK=0 skip the re-verification pass (saves one grounded call)

Non-destructive: if nothing is flagged, or the model returns no usable edit,
the article is left exactly as written and this exits 0.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"
ARTS = HERE / "articles"

CATEGORY = (os.environ.get("CATEGORY") or "").strip().lower() or None
META = (DATA / "articles" / f"{CATEGORY}.json") if CATEGORY \
    else (DATA / "article.json")
REPORT = (DATA / f"fact_check_{CATEGORY}.json") if CATEGORY \
    else (DATA / "fact_check.json")

FIX_UNSURE = os.environ.get("CORRECT_UNSURE", "1") != "0"
RECHECK = os.environ.get("CORRECT_RECHECK", "1") != "0"

SYSTEM = (
    "You are a correcting editor for an Indian personal-finance publication. "
    "A fact-checker has flagged specific claims in a published-ready article. "
    "You repair those claims against authoritative Indian sources "
    "(incometax.gov.in, rbi.org.in, sebi.gov.in, amfiindia.com, epfindia.gov.in, "
    "npstrust.org.in, irdai.gov.in, pfrda.org.in, finmin.nic.in) using Google "
    "Search. You make the SMALLEST edit that makes the claim true. You never "
    "invent a fact to replace another fact — if you cannot verify a correct "
    "replacement, you remove the unverifiable specific or soften the sentence "
    "to what IS supported. You never change the article's voice, structure, "
    "headings, or Markdown formatting."
)

USER_PROMPT = """Article (Markdown body) that needs correcting:

----- BEGIN ARTICLE -----
{article}
----- END ARTICLE -----

A fact-checker flagged these claims:

{flagged}

For each flagged claim, produce a minimal edit to the article.

How to fix, by status:
- `likely_wrong` — the claim is factually incorrect. Replace it with the
  correct fact, verified via Google Search against the authoritative source.
  If the claim is a fabricated event (e.g. a circular or announcement that
  never happened), DELETE the fabricated specific and keep only what is true.
- `unsure` — the claim could not be verified. Do NOT restate it as fact.
  Either attribute it ("according to <source>"), soften it to the supported
  range, or drop the unverifiable number. Never invent a replacement figure.

Output a single JSON object — no preamble, no markdown fences:

{{
  "edits": [
    {{
      "find": "<EXACT substring copied verbatim from the article above, long enough to be unique — include the full sentence>",
      "replace": "<the corrected text that should take its place, same Markdown style. Empty string to delete the sentence.>",
      "why": "<one line: what was wrong and what source you verified against>",
      "source": "<URL you verified the correction against, or empty if this is a deletion>"
    }}
  ],
  "note": "<one sentence on what you changed overall>"
}}

CRITICAL rules for `find`:
- It MUST appear character-for-character in the article above. Copy it, do not
  retype it or normalise its punctuation, dashes, quotes or spacing.
- Include the whole sentence, not a fragment.
- If a flagged claim appears twice (e.g. in the TL;DR and in the body), emit a
  separate edit for each occurrence with enough surrounding text to be unique.
- If you cannot fix a claim safely, omit it from `edits` rather than guessing.

Output ONLY the JSON object. No code fences. No commentary."""


from llm import call_llm as _shared_call_llm


def _parse_json(text: str, debug_name: str) -> dict | None:
    """Gemini occasionally wraps JSON in fences or adds a preamble."""
    text = (text or "").strip()
    if not text:
        return None
    (DATA / debug_name).write_text(text)
    cleaned = re.sub(r"^```(?:json)?\s*", "", text)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError as e:
                print(f"JSON salvage failed: {e}", file=sys.stderr)
        print(f"Raw response saved to {DATA / debug_name}", file=sys.stderr)
        print(cleaned[:600], file=sys.stderr)
        return None


def split_frontmatter(raw: str) -> tuple[str, str]:
    """Return (frontmatter_including_trailing_newlines, body)."""
    m = re.match(r"^---\n[\s\S]+?\n---\n+", raw)
    if not m:
        return "", raw
    return m.group(0), raw[m.end():]


def format_flagged(flagged: list[dict]) -> str:
    lines = []
    for i, c in enumerate(flagged, 1):
        lines.append(
            f"{i}. [{c.get('status')}] {c.get('claim')}\n"
            f"   fact-checker note: {c.get('note') or '(none)'}\n"
            f"   source checked:    {c.get('source') or '(none)'}"
        )
    return "\n\n".join(lines)


def apply_edits(body: str, edits: list[dict]) -> tuple[str, list[dict], list[dict]]:
    """Apply only edits whose `find` matches verbatim. Returns
    (new_body, applied, missed)."""
    applied: list[dict] = []
    missed: list[dict] = []
    for e in edits:
        find = e.get("find") or ""
        repl = e.get("replace")
        if not find or repl is None:
            missed.append({**e, "reason": "empty find/replace"})
            continue
        count = body.count(find)
        if count == 0:
            missed.append({**e, "reason": "anchor not found in article"})
            continue
        if count > 1:
            # Ambiguous anchor — replacing all occurrences is what the model
            # asked for only if it knew there were several. Be safe: replace
            # every occurrence, but record it.
            e = {**e, "occurrences": count}
        body = body.replace(find, repl)
        applied.append(e)
    return body, applied, missed


def tidy(body: str) -> str:
    """Deletions can leave dangling blank lines or empty list bullets."""
    body = re.sub(r"^[ \t]*[-*][ \t]*$\n?", "", body, flags=re.MULTILINE)
    body = re.sub(r"\n{4,}", "\n\n\n", body)
    return body


def main() -> int:
    if not REPORT.exists():
        print(f"No fact-check report at {REPORT} — nothing to correct.")
        return 0
    if not META.exists():
        print(f"{META} missing", file=sys.stderr)
        return 1

    report = json.loads(REPORT.read_text())
    meta = json.loads(META.read_text())

    wanted = {"likely_wrong"} | ({"unsure"} if FIX_UNSURE else set())
    flagged = [c for c in report.get("claims", [])
               if (c.get("status") or "").lower() in wanted]

    print(f"Article: {meta.get('title', '')[:80]}")
    print(f"Fact-check verdict: {report.get('verdict')}  ·  "
          f"{len(flagged)} claim(s) to correct "
          f"(fixing: {', '.join(sorted(wanted))})")
    if not flagged:
        print("Nothing flagged — article left untouched.")
        return 0

    md_path = ARTS / meta["filename"]
    if not md_path.exists():
        print(f"Article md not found: {md_path}", file=sys.stderr)
        return 1
    raw = md_path.read_text()
    fm, body = split_frontmatter(raw)

    text = _shared_call_llm(
        USER_PROMPT.format(article=body, flagged=format_flagged(flagged)),
        SYSTEM,
        temperature=0.1,
        max_tokens=24000,
        top_p=0.95,
        grounding=True,
        thinking_budget=0,
    )
    result = _parse_json(text, f"correct_raw{'_' + CATEGORY if CATEGORY else ''}.txt")
    if not result:
        print("Correction call failed — article left untouched.", file=sys.stderr)
        return 1

    edits = result.get("edits") or []
    if not edits:
        print("Model returned no edits — article left untouched.")
        return 0

    new_body, applied, missed = apply_edits(body, edits)
    for e in applied:
        occ = f" (x{e['occurrences']})" if e.get("occurrences") else ""
        print(f"  ✓ fixed{occ}: {e.get('why', '')[:120]}")
    for e in missed:
        print(f"  ✗ skipped ({e.get('reason')}): {str(e.get('find'))[:90]}",
              file=sys.stderr)

    if not applied:
        print("No edit anchored cleanly — article left untouched.", file=sys.stderr)
        return 1

    new_body = tidy(new_body)
    md_path.write_text(fm + new_body)
    print(f"Applied {len(applied)}/{len(edits)} edits to {md_path.name}")

    meta["corrections"] = {
        "applied": len(applied),
        "skipped": len(missed),
        "note": result.get("note"),
        "edits": [{"why": e.get("why"), "source": e.get("source")}
                  for e in applied],
        "verdict_before": report.get("verdict"),
    }

    if RECHECK:
        print("Re-verifying corrected article…")
        try:
            from fact_check import call_gemini_grounded
        except Exception as e:  # noqa: BLE001
            print(f"Could not import fact_check for re-verify: {e}",
                  file=sys.stderr)
            call_gemini_grounded = None  # type: ignore[assignment]
        if call_gemini_grounded:
            recheck = call_gemini_grounded(new_body)
            if recheck:
                counts: dict[str, int] = {}
                for c in recheck.get("claims", []):
                    s = c.get("status", "unknown")
                    counts[s] = counts.get(s, 0) + 1
                print(f"Post-correction verdict: {recheck.get('verdict')} "
                      f"— {counts}")
                recheck["article_slug"] = meta.get("slug")
                recheck["article_title"] = meta.get("title")
                recheck["corrected"] = True
                recheck["verdict_before"] = report.get("verdict")
                REPORT.write_text(json.dumps(recheck, indent=2, default=str))
                meta["fact_check"] = {
                    "verdict": recheck.get("verdict"),
                    "summary": recheck.get("summary"),
                    "claim_count": len(recheck.get("claims", [])),
                    "counts": counts,
                    "corrected": True,
                }
                meta["corrections"]["verdict_after"] = recheck.get("verdict")
            else:
                print("Re-verify failed — keeping original report.",
                      file=sys.stderr)

    META.write_text(json.dumps(meta, indent=2, default=str))
    print(f"Updated {META.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
