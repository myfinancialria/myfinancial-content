# business-mavericks

Daily long-form business storytelling — auto-published to **Slack**.

Every day at **10:00 IST**, this repo picks one story from a curated rotation of business rises and falls, writes a 900-1,600-word narrative feature via Gemini 2.5 Flash with **Google Search grounding** for citeable sources, generates a hero illustration, **verifies that every reference URL is reachable**, and posts the result to a Slack channel.

## The reference gate

Storytelling without sources is fiction. This pipeline refuses to publish if it can't back up the claims:

- The article must contain a `## References` section with at least **3 URLs**.
- Every URL must return `200` (or `3xx`) before publish runs.
- If verification fails, the workflow logs a warning and skips publishing.

## Pipeline

```
pick_story.py        →  picks today's story from data/stories.json (rotates, dedups)
write_article.py     →  Gemini 2.5 Flash w/ Google Search grounding
                        produces markdown + ## References section
verify.py            →  hard gate: ≥3 reachable URLs or abort
generate_image.py    →  Pollinations.ai FLUX, 1200×675 editorial illustration
publish_slack.py     →  catbox.moe mirror + rich blocks
                        (hero + hook in main, full body + refs in thread)
```

## Setup

### 1. Get a Gemini API key (free tier)

https://aistudio.google.com/app/apikey — Gemini 2.5 Flash is free up to 1,500 requests/day.

### 2. Get a Slack incoming webhook (or bot token for threading)

**Webhook (simpler, no threading):**
https://api.slack.com/messaging/webhooks → create a webhook for the target channel.

**Bot token (better — enables threading):**
https://api.slack.com/apps → create app → OAuth scopes `chat:write` → install to workspace. Token starts with `xoxb-`. Channel ID is in the channel's URL.

### 3. Set GitHub Secrets

```bash
gh secret set GEMINI_API_KEY     -R myfinancialria/business-mavericks
gh secret set SLACK_WEBHOOK_URL  -R myfinancialria/business-mavericks
# OR if using bot token:
gh secret set SLACK_BOT_TOKEN    -R myfinancialria/business-mavericks
gh secret set SLACK_CHANNEL      -R myfinancialria/business-mavericks
```

### 4. Trigger manually first

```bash
gh workflow run "Daily business story → Slack" -R myfinancialria/business-mavericks
gh run watch -R myfinancialria/business-mavericks
```

## Local run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in
set -a; source .env; set +a

python pick_story.py
python write_article.py
python verify.py            # exits 3 if references can't be verified
python generate_image.py
python publish_slack.py
```

## Adding new stories

Append entries to `data/stories.json`:

```json
{
  "slug": "kebab-case-unique-identifier",
  "title": "Headline (the writer can keep or rewrite this)",
  "context": "2-3 sentences for Gemini — what's the angle, why does it matter",
  "angle": "rise"
}
```

`pick_story.py` rotates through the list, marking each slug as `published` in `data/state.json`. When every story has been used, the list wraps around. Curate the list to keep the back catalogue fresh.

## Cost

| Item | Cost |
|---|---|
| Gemini 2.5 Flash (one article + one image prompt) | Free tier — well under daily limit |
| Pollinations.ai image generation | Free |
| catbox.moe image hosting | Free, anonymous |
| Slack webhook | Free |
| GitHub Actions (private repo) | ~3 mins/day · well under the 2,000 free min/mo |
| **Total** | **₹0 / month** |
