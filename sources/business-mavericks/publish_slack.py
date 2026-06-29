"""Post today's business story to Slack.

Layout:
  1. Main message — hero image + bold title + the article's "Hook" section
     (the opening scene) + a "Full story below 👇" note.
  2. Threaded reply — the rest of the article body (sections after Hook),
     split by Slack's 3000-char-per-block limit if needed.
  3. Threaded reply — the References section as a separate clean block.

Required env:
  SLACK_WEBHOOK_URL                 (incoming webhook — fine for text+image_url)
                                    OR
  SLACK_BOT_TOKEN + SLACK_CHANNEL   (bot token — needed if you want threading;
                                     webhooks can't thread).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import requests

HERE = Path(__file__).parent
META = HERE / "data" / "article.json"
ARTS = HERE / "articles"

SLACK_BLOCK_LIMIT = 3000   # max chars in a section block's text


def _load_meta() -> dict:
    return json.loads(META.read_text())


def _load_body(meta: dict) -> str:
    text = (ARTS / meta["filename"]).read_text()
    return re.sub(r"^---\n[\s\S]+?\n---\n+", "", text, count=1)


def _md_to_slack(text: str) -> str:
    """Convert article markdown → Slack mrkdwn (very small subset)."""
    out = text
    # Headers ## → *bold*
    out = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", out, flags=re.MULTILINE)
    # **bold** → *bold*
    out = re.sub(r"\*\*([^*]+)\*\*", r"*\1*", out)
    # Markdown links [text](url) → <url|text>
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", out)
    # Bullets: keep
    return out.strip()


def _parse_article(body: str) -> tuple[str, list[tuple[str, str]], str]:
    """Returns (hook_text, [(section_name, section_body), ...], references_body).

    Robust to LLM markdown style — auto-detects whether sections are at
    level 2 (##) or level 3 (###). If the model used a level-2 article
    title with level-3 sections, the title is dropped and everything
    between it and the first level-3 header becomes the hook.
    """
    matches = list(re.finditer(r"^(#{2,6})\s+(.+?)$", body, flags=re.MULTILINE))
    if not matches:
        return body.strip(), [], ""

    levels = [len(m.group(1)) for m in matches]
    # The level used for body sections is whichever level appears most often.
    body_level = max(set(levels), key=levels.count)
    section_matches = [m for m in matches if len(m.group(1)) == body_level]

    if not section_matches:
        return body.strip(), [], ""

    # Hook = everything between the start of body (or end of an outer title
    # header, if one exists above body_level) and the first body-level section.
    if body_level > 2 and any(len(m.group(1)) < body_level for m in matches):
        outer = next((m for m in matches if len(m.group(1)) < body_level), None)
        hook_start = outer.end() if outer else 0
    else:
        hook_start = 0
    hook = body[hook_start:section_matches[0].start()].strip()

    sections: list[tuple[str, str]] = []
    references = ""
    for i, m in enumerate(section_matches):
        name = m.group(2).strip()
        end = section_matches[i + 1].start() if i + 1 < len(section_matches) else len(body)
        section_body = body[m.end():end].strip()
        if "reference" in name.lower() or "source" in name.lower():
            references = section_body
        else:
            sections.append((name, section_body))
    return hook, sections, references


def _chunk_for_slack(text: str, limit: int = SLACK_BLOCK_LIMIT) -> list[str]:
    """Split at paragraph boundaries to stay under limit."""
    if len(text) <= limit:
        return [text] if text.strip() else []
    chunks, cur = [], ""
    for para in text.split("\n\n"):
        if len(cur) + len(para) + 2 <= limit:
            cur = (cur + "\n\n" + para) if cur else para
        else:
            if cur:
                chunks.append(cur)
            cur = para[:limit]
    if cur:
        chunks.append(cur)
    return chunks


def _upload_to_catbox(image_path: Path) -> str | None:
    """Upload the hero JPG to catbox.moe (anonymous, free) so Slack can
    fetch a short, fast URL instead of the slow Pollinations endpoint."""
    if not image_path.exists():
        return None
    try:
        with image_path.open("rb") as f:
            r = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": (image_path.name, f, "image/jpeg")},
                timeout=30,
            )
        if r.status_code < 400 and r.text.startswith("https://"):
            url = r.text.strip()
            print(f"  → mirrored hero to {url}")
            return url
        print(f"  catbox upload failed [{r.status_code}]: {r.text[:120]}",
              file=sys.stderr)
    except Exception as e:
        print(f"  catbox upload error: {e}", file=sys.stderr)
    return None


def _build_main_blocks(meta: dict, hook: str) -> list[dict]:
    angle_emoji = "📈" if meta.get("angle") == "rise" else "📉"
    angle_label = "RISE" if meta.get("angle") == "rise" else "FALL"
    blocks: list[dict] = [
        {"type": "header",
         "text": {"type": "plain_text",
                  "text": f"{angle_emoji} Today's business story — {angle_label}"}},
    ]
    # Slack's webhook image validator TIMES OUT on slow generative URLs
    # like Pollinations and returns invalid_blocks — so only embed an image
    # when we have a fast mirror (catbox). If mirroring failed, fall back
    # to a clickable link in a context block so the post still ships.
    mirror_url = meta.get("hero_mirror_url")
    raw_url = meta.get("hero_url")
    alt = (meta.get("title") or "hero image")[:1000] or "hero image"
    if mirror_url:
        blocks.append({"type": "image", "image_url": mirror_url,
                       "alt_text": alt})
    elif raw_url:
        blocks.append({"type": "context",
                       "elements": [{"type": "mrkdwn",
                                     "text": f"<{raw_url}|🖼 Hero image>"}]})
    blocks.append({"type": "section",
                   "text": {"type": "mrkdwn", "text": f"*{meta['title']}*"}})
    hook_md = _md_to_slack(hook)
    if len(hook_md) > SLACK_BLOCK_LIMIT:
        hook_md = hook_md[:SLACK_BLOCK_LIMIT - 1].rstrip() + "…"
    blocks.append({"type": "section",
                   "text": {"type": "mrkdwn", "text": hook_md}})
    blocks.append({"type": "context",
                   "elements": [{"type": "mrkdwn",
                                 "text": "_Full story + lessons + sources in the thread below 👇_"}]})
    return blocks


def _post_webhook(webhook_url: str, blocks: list[dict], text: str) -> bool:
    r = requests.post(webhook_url,
                      json={"text": text, "blocks": blocks,
                            "unfurl_links": False, "unfurl_media": False},
                      timeout=20)
    if r.status_code >= 400:
        print(f"Slack webhook failed [{r.status_code}]: {r.text[:200]}",
              file=sys.stderr)
        return False
    print(f"✓ Webhook posted")
    return True


def _post_bot(token: str, channel: str, blocks: list[dict], text: str,
              thread_ts: str | None = None) -> str | None:
    payload = {"channel": channel, "text": text, "blocks": blocks,
               "unfurl_links": False, "unfurl_media": False}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    r = requests.post("https://slack.com/api/chat.postMessage",
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "application/json"},
                      data=json.dumps(payload), timeout=20)
    j = r.json()
    if not j.get("ok"):
        print(f"Slack postMessage failed: {j}", file=sys.stderr)
        return None
    print(f"✓ Bot posted (ts={j['ts']})")
    return j["ts"]


def main() -> int:
    meta = _load_meta()
    body = _load_body(meta)
    hook, body_sections, refs_section = _parse_article(body)

    # Mirror hero to catbox so Slack's image-URL validator doesn't time out
    # waiting for Pollinations' slow generative endpoint.
    hero_local = meta.get("hero_local")
    if hero_local:
        mirror = _upload_to_catbox(HERE / hero_local)
        if mirror:
            meta["hero_mirror_url"] = mirror
            META.write_text(json.dumps(meta, indent=2))

    main_blocks = _build_main_blocks(meta, hook)
    plain_text = f"{meta['title']} — {hook[:120]}…"

    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL")
    webhook = os.environ.get("SLACK_WEBHOOK_URL")

    if token and channel:
        # Bot-token path — supports threading
        ts = _post_bot(token, channel, main_blocks, plain_text)
        if not ts:
            return 1
        # Threaded body
        for h, b in body_sections:
            section_md = f"*{h}*\n\n" + _md_to_slack(b)
            for chunk in _chunk_for_slack(section_md):
                _post_bot(token, channel,
                          [{"type": "section",
                            "text": {"type": "mrkdwn", "text": chunk}}],
                          f"{h}…", thread_ts=ts)
        # Threaded references
        if refs_section:
            refs_md = "*References*\n\n" + _md_to_slack(refs_section)
            _post_bot(token, channel,
                      [{"type": "section",
                        "text": {"type": "mrkdwn", "text": refs_md}}],
                      "References", thread_ts=ts)
        return 0

    if webhook:
        # Webhook path — no threading, send everything as separate messages
        if not _post_webhook(webhook, main_blocks, plain_text):
            return 1
        for h, b in body_sections:
            section_md = f"*{h}*\n\n" + _md_to_slack(b)
            for chunk in _chunk_for_slack(section_md):
                _post_webhook(webhook,
                              [{"type": "section",
                                "text": {"type": "mrkdwn", "text": chunk}}],
                              f"{h}…")
        if refs_section:
            refs_md = "*References*\n\n" + _md_to_slack(refs_section)
            _post_webhook(webhook,
                          [{"type": "section",
                            "text": {"type": "mrkdwn", "text": refs_md}}],
                          "References")
        return 0

    print("Set SLACK_WEBHOOK_URL or SLACK_BOT_TOKEN+SLACK_CHANNEL", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
