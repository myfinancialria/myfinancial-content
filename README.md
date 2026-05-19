# myfinancial · Content Engine

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
| `publish.py` | Render Markdown → HTML, build sitemap, robots.txt |
| `slack_post.py` | Post to Slack — set `SLOT=morning\|midday\|evening` |
| `.github/workflows/generate.yml` | Daily generation (05:30 IST) |
| `.github/workflows/post_*.yml` | Three Slack-posting workflows |

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
