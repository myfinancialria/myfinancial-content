"""Orchestrator: fetch everything, build the digest for the chosen slot, post.

Usage:
  SLOT=morning python run.py   # fetch + build + post morning brief
  SLOT=evening python run.py   # fetch + build + post evening wrap

Individual fetch steps fail soft (printed warning, empty section) so a single
upstream outage doesn't kill the whole run.
"""
from __future__ import annotations

import os
import subprocess
import sys


def step(name: str, cmd: list[str]) -> bool:
    print(f"\n=== {name} ===")
    rc = subprocess.call([sys.executable] + cmd)
    if rc != 0:
        print(f"  ! {name} returned {rc}")
        return False
    return True


def main() -> int:
    slot = os.environ.get("SLOT", "morning").lower()
    if slot not in ("morning", "evening"):
        print(f"SLOT must be 'morning' or 'evening' (got {slot})", file=sys.stderr)
        return 2

    # Fetchers — failures don't abort; build_digest will skip empty sections.
    step("nifty500 sanity", ["nifty500.py"])
    step("fetch results", ["fetch_results.py"])
    step("fetch corp actions", ["fetch_corp_actions.py"])
    step("fetch news", ["fetch_news.py"])
    # Evening run is the one that needs today's FII/DII; morning uses yesterday's
    step("fetch FII/DII", ["fetch_fiidii.py"])

    if not step("build digest", ["build_digest.py"]):
        return 1

    # Post to both surfaces — Slack first (faster failure surface), then Telegram
    slack_ok = step("post Slack", ["slack_post.py"])
    tg_ok = step("post Telegram", ["telegram_post.py"])

    # Archive the digest as a web article for the unified site's News tab.
    try:
        import page_export
        page_export.export(slot)
    except Exception as e:
        print(f"page_export failed (non-fatal): {e}")

    print(f"\n=== Done — slot={slot} slack={'ok' if slack_ok else 'FAIL'} "
          f"telegram={'ok' if tg_ok else 'FAIL'} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
