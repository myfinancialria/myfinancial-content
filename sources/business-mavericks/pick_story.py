"""Select today's story from data/stories.json — rotates through, dedups."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
STORIES = HERE / "data" / "stories.json"
STATE = HERE / "data" / "state.json"
TODAY = HERE / "data" / "today.json"


def _load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            pass
    return {"published": [], "rotations": 0}


def main() -> int:
    if not STORIES.exists():
        print(f"{STORIES} missing", file=sys.stderr)
        return 1
    stories = json.loads(STORIES.read_text())
    if not stories:
        print("Story list is empty", file=sys.stderr)
        return 1

    state = _load_state()
    published = set(state.get("published", []))

    pick = next((s for s in stories if s["slug"] not in published), None)
    if pick is None:
        print(f"All {len(stories)} stories used; resetting rotation.")
        state["published"] = []
        state["rotations"] = state.get("rotations", 0) + 1
        published = set()
        pick = stories[0]

    today = dt.date.today().isoformat()
    payload = {
        "date": today,
        "slug": pick["slug"],
        "title": pick["title"],
        "context": pick["context"],
        "angle": pick.get("angle", "rise"),
    }
    TODAY.write_text(json.dumps(payload, indent=2))
    print(f"Picked [{pick['angle']}] {pick['slug']}: {pick['title']}")

    state["published"] = list(published | {pick["slug"]})
    STATE.write_text(json.dumps(state, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
