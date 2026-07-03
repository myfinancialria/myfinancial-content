# myfinancial · Content Engine (monorepo)

This repo is the **single home for every myfinancial.in content stream**. It
hosts the personal-finance content engine (at the repo root) plus four merged
pipelines under [`sources/`](sources/), and builds **one GitHub Pages site with
a tab per stream**.

## Unified tabbed site

[`site_build.py`](site_build.py) aggregates every source's `articles/*.md` into
one site at `https://myfinancialria.github.io/myfinancial-content/`, with a
sticky top-nav:

| Tab | Source | Origin repo (merged) |
|---|---|---|
| Personal Finance / Macro & Markets / Result Analysis / Pre-Market / Market Wrap / Explained | root `articles/` split by frontmatter `category` | *(this repo)* |
| F&O Pulse | `sources/daily-fno-pulse/` | `daily-fno-pulse` |
| Business Mavericks | `sources/business-mavericks/` | `business-mavericks` |
| Market Pulse | `sources/market-pulse/` | `myfinancial-market-pulse` |
| News | `sources/news/` | `myfinancial-news` |

Each pipeline only has to drop markdown into its own `articles/` folder; the
generation workflows then run `site_build.py` and deploy. The two
Slack/Telegram-only streams (market-pulse infographics, news digests) gained a
`page_export.py` that also archives each run as a web article so their tabs have
real content.

- Add a source: drop its repo under `sources/<name>/`, give it an `articles/`
  folder of frontmatter+markdown, and add an entry to `SOURCES` + `TABS` in
  `site_build.py`.
- Build locally: `python site_build.py` then `open output/index.html`.

## Workflows

- Root content workflows (`generate.yml`, `generate_premarket.yml`,
  `generate_postmarket.yml`, `explainer.yml`) now build the **unified** site via
  `site_build.py` and deploy.
- One workflow per merged source: `src-fno-daily.yml`, `src-mavericks-daily.yml`,
  `src-marketpulse-*.yml`, `src-news.yml`. Each generates into `sources/<name>/`,
  commits, rebuilds the unified site, and deploys (Pages deploys are serialized
  by the `github-pages` environment + a shared `pages-deploy` concurrency group).

## Secrets to migrate

The merged workflows reference secrets that previously lived in the source
repos. Add these to **this** repo (Settings → Secrets and variables → Actions)
before enabling the schedules:

| Secret | Used by |
|---|---|
| `GEMINI_API_KEY`, `GEMINI_API_KEYS` | all (LLM) |
| `FYERS_CLIENT_ID`, `FYERS_SECRET`, `FYERS_REDIRECT`, `FYERS_FY_ID`, `FYERS_PIN`, `FYERS_TOTP_KEY` | F&O Pulse, Market Pulse (Fyers login) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_PULSE_CHAT_ID`, `TELEGRAM_NEWS_CHAT_ID` | Market Pulse, News |
| `SLACK_BOT_TOKEN`, `SLACK_WEBHOOK_URL`, `SLACK_CHANNEL`, `SLACK_NEWS_CHANNEL`, `SLACK_NEWS_WEBHOOK_URL` | Mavericks, News |
| `NEWS_FEEDS`, `CONTENT_FEEDS` | News, content scraper |

The four source repos are superseded by this monorepo and can be archived once
the schedules here run green.

---

## Content engine (root pipeline)

A daily content pipeline for myfinancial.in. Every morning it:

1. **Scrapes** the latest personal-finance articles from Livemint, ET Money, Moneycontrol, 1Finance, The Fynprint, INDmoney
2. **Picks** the hottest topic for our audience (15L+ earners + NRIs) using a relevance-weighted heuristic
3. **Writes** a 1,200–1,800-word SEO + AEO-optimised article via Claude — frontmatter, JSON-LD `Article` + `FAQPage` schema, citations to RBI/SEBI/IT Dept
4. **Publishes** as Markdown + HTML on GitHub Pages with a sitemap
5. **Posts to Slack 3× a day** with different framings:
   - **8 AM IST** — Morning brief (title + 3-bullet TL;DR + link)
   - **1 PM IST** — Midday deep-dive (worked example excerpt + link)
   - **7 PM IST** — Evening wrap (action items + quick FAQ + link)

## Files

| File | Purpose |
|---|---|
| `scrape_sources.py` | Pull latest articles from RSS feeds + Google News |
| `pick_topic.py` | Score + cluster articles, pick today's topic |
| `write_article.py` | Claude generates the article with SEO+AEO frontmatter |
| `publish.py` | Render Markdown → HTML, build sitemap, robots.txt, **IPO Watch tab** |
| `slack_post.py` | Post to Slack — set `SLOT=morning\|midday\|evening` |
| `ipo_data.py` | Fetch upcoming IPOs + a one-month post-listing report card (NSE + Fyers) → `data/ipo.json` |
| `write_ipo.py` | Two **educational** IPO reports (upcoming; one-month-after-listing) — no recommendations |
| `.github/workflows/generate.yml` | Daily generation (05:30 IST) |
| `.github/workflows/ipo.yml` | Weekly IPO Watch refresh (Mon 09:00 IST) |
| `.github/workflows/post_*.yml` | Three Slack-posting workflows |

### IPO Watch tab

A dedicated **IPO Watch** tab (`/ipo/`) tracks two things in plain English:

1. **Upcoming & open IPOs** — a quick-reference table (price band, lot size, issue size, dates) plus a full "Upcoming IPOs, Explained Simply" report.
2. **Post-listing report card (30–60 days)** — how IPOs that listed more than 30 and less than 60 days ago are trading now vs their issue price, plus an "IPO Report Card: 30 to 60 Days After Listing" report.

Both reports are **strictly educational** — the prompt forbids any buy/sell/subscribe/avoid call, rating, price target, or GMP signal (myfinancial is not a SEBI-registered adviser). Data comes from public NSE APIs; current prices from Fyers.

## One-time setup

### 1. LLM API key — pick ONE provider (default: Gemini, free)

| Provider | Cost | Free tier | Get key at |
|---|---|---|---|
| **Gemini 2.5 Flash** (default) | Free | 1,500 req/day, no card | https://aistudio.google.com/app/apikey |
| Groq Llama 3.3 70B | Free | 30 req/min, no card | https://console.groq.com/keys |
| Anthropic Sonnet 4.6 | Paid (~₹30-50/mo) | Trial credit | https://console.anthropic.com/settings/keys |

**For Gemini (recommended):**
```bash
gh secret set GEMINI_API_KEY -R myfinancialria/myfinancial-content
```

To switch providers later, set repo variable `LLM_PROVIDER` to `gemini` / `groq` / `anthropic`.

### 2. Slack — dedicated channel for content

Create a channel (e.g. `#myfinancial-content`) and invite the existing Market Pulse bot (or create a new one with `chat:write`).

```bash
gh secret set SLACK_BOT_TOKEN       -R myfinancialria/myfinancial-content
gh secret set SLACK_CONTENT_CHANNEL -R myfinancialria/myfinancial-content
```

(Webhook alternative: set `SLACK_CONTENT_WEBHOOK_URL` instead.)

### 3. GitHub Pages

Repo Settings → Pages → Source: **GitHub Actions**.

After the first generate run, the site goes live at `https://myfinancialria.github.io/myfinancial-content/`.

## Local run

```bash
cd ~/fyers-bot/content-engine
~/fyers-bot/.venv/bin/pip install -r requirements.txt
~/fyers-bot/.venv/bin/python scrape_sources.py
~/fyers-bot/.venv/bin/python pick_topic.py
GEMINI_API_KEY=YOUR_KEY ~/fyers-bot/.venv/bin/python write_article.py
~/fyers-bot/.venv/bin/python publish.py
# Preview locally:
open output/index.html
```

## SEO + AEO design choices

- **E-E-A-T**: every article credits "Nithin (CFP)" — author schema + visible byline
- **JSON-LD**: `Article` on every page; `FAQPage` when an FAQ section exists (this is what ranks in Claude/Perplexity/ChatGPT)
- **TL;DR block at the top** — LLMs grab this as the canonical answer
- **Cited sources only** — Income Tax Dept, RBI, SEBI, AMFI, EPFO, IRDAI, PFRDA, MoF. No anonymous claims.
- **Canonical URLs** — every article has a stable URL via slug
- **Sitemap + robots.txt** at the root for fast Google indexing
- **Mobile-first CSS** — 17px body text, single column, no clutter

## Cost

- **Gemini 2.5 Flash (default)** — ₹0/month (free tier covers 1,500 req/day; you'll use ~1)
- Groq Llama 3.3 70B — ₹0/month (free tier)
- Anthropic Sonnet 4.6 — ~₹30-50/month (if you switch to paid)
- GitHub Actions — free (well under 2,000 mins/mo on public repos)
- GitHub Pages — free
