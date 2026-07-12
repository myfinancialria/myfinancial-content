# LinkedIn roadmap

Where the LinkedIn presence for myfinancial.in goes from here. The automation
that exists today is documented in [`LINKEDIN_AUTOMATION.md`](LINKEDIN_AUTOMATION.md);
this file is the plan for building on it.

## Where we are today (baseline)

- `linkedin_poster.py` turns each day's root-pipeline articles into a 9:16
  poster (`poster.jpg`), a plain-English caption (`caption.txt`), and
  `meta.json`, all under `output/linkedin/<slug>/`.
- A gallery at `output/linkedin/index.html` lets you download a poster and
  copy its caption in one click.
- The step runs inside `.github/workflows/generate.yml` only, so it covers
  the daily personal-finance / macro / results articles — **not** the
  explainer, pre-market, post-market, or `sources/` streams.
- **Posting is manual by design**: no LinkedIn API app, no OAuth tokens.
  Open the gallery, download, copy, post.

## Guiding principles

1. **Educational only.** Same rule as the IPO Watch tab: no buy/sell calls,
   ratings, or price targets — myfinancial is not a SEBI-registered adviser.
   Every format below inherits that constraint.
2. **Degrade gracefully.** Every stage keeps working with no LLM key and no
   image service, exactly like `linkedin_poster.py` does today.
3. **Audience first.** Content targets the same readers as the site:
   15L+ earners and NRIs. LinkedIn is where that audience already is.
4. **One post, one idea.** Heading + TL;DR + link. The article carries the
   depth; the post earns the click.

## Phase 1 — Full coverage of existing content (low effort)

Goal: every article the engine publishes gets LinkedIn assets, not just the
morning batch.

- [ ] Add the **Generate LinkedIn share posters + captions** step (identical
      to the one in `generate.yml`) to `explainer.yml`,
      `generate_premarket.yml`, and `generate_postmarket.yml`.
      (`linkedin_poster.py` is idempotent, so overlapping runs are safe.)
- [ ] Extend `linkedin_poster.py` to optionally pick up `sources/*/articles/`
      (F&O Pulse, Business Mavericks, Market Pulse, News) behind a
      `--source` flag, reusing each tab's category label.
- [ ] Surface the gallery link in the daily Slack post (`slack_post.py`
      morning slot) so posting becomes part of the morning routine instead
      of something to remember.

## Phase 2 — Better formats (medium effort)

Goal: match the format to the content instead of one poster style for
everything.

- [ ] **Text-first posts.** LinkedIn's algorithm favours native text over
      link posts. Generate a 3–5 line "hook + insight + question" variant in
      `caption_text.txt` alongside the current caption, with the article
      link as the first comment (stored in `first_comment.txt`).
- [ ] **Carousels (document posts).** For listicle-shaped articles
      (e.g. "5 ways to reduce your tax"), render each TL;DR bullet as one
      1080×1350 slide and assemble a PDF — carousels consistently outperform
      single images for educational finance content. Reuse the Pillow layout
      code and brand palette already in `linkedin_poster.py`.
- [ ] **Square variant.** Emit a 1080×1080 `poster_sq.jpg` next to the 9:16
      poster; feed posts crop verticals aggressively.
- [ ] **Category-aware templates.** Results posts get a numbers-forward
      layout; personal-finance posts get the checklist layout; pre/post-market
      briefs get a "3 things" layout. Keyed off the same
      `CATEGORY_LABELS` map.

## Phase 3 — Scheduling & semi-automation (medium effort)

Goal: reduce the manual step from "download, copy, post" to "approve".

- [ ] **Posting calendar.** Add a `schedule` field to `meta.json`
      (e.g. personal finance at 8:30 AM IST, results at market close) and
      sort the gallery by it, so the gallery becomes a queue, not a pile.
- [ ] **Slack approval flow.** Post the poster + caption to Slack with the
      existing bot; reacting ✅ marks it posted (tracked in
      `data/linkedin_log.json`) so the gallery shows what's still pending.
- [ ] **Evaluate the official LinkedIn API** (Community Management API,
      `w_member_social` scope) for direct posting from CI. Decision point:
      the token-refresh burden (60-day expiry, manual re-auth) vs. the
      minutes saved. If it stays manual, that's a valid outcome — document
      why.

## Phase 4 — Measurement & iteration (ongoing)

Goal: stop guessing which formats and topics work.

- [ ] **UTM tagging.** Append `?utm_source=linkedin&utm_medium=<format>` to
      every article link in captions so clicks are attributable per format
      (poster vs. text vs. carousel).
- [ ] **Weekly scorecard.** A manual-first `data/linkedin_stats.csv`
      (impressions, reactions, clicks per post) plus a small script that
      summarises "best format / best category / best time" into the weekly
      Slack digest.
- [ ] **Feed the winner back.** Let `pick_topic.py` weight topics by which
      categories earn LinkedIn engagement, closing the loop between
      distribution and topic selection.

## Explicitly out of scope

- Automated commenting, connection requests, or DM outreach — spam-adjacent
  and against LinkedIn ToS.
- Scraping LinkedIn analytics with a headless browser — brittle and a ToS
  risk; stats stay manual/CSV until the official API is adopted.
- Paid promotion — revisit only after Phase 4 shows which organic formats
  convert.

## Sequencing

Phase 1 is a few small workflow edits and can ship immediately. Phase 2
items are independent of each other — ship text-first posts before
carousels. Phase 3 only pays off once Phase 2 volume exists. Phase 4 starts
as a spreadsheet on day one; the tooling follows the habit.
