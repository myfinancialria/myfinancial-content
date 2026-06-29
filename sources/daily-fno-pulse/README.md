# Daily F&O Pulse — India

**Auto-published every weekday at 18:30 IST**: a retail-friendly end-of-day reading of Indian
Futures & Options positioning across Nifty, Sensex, Bank Nifty + top F&O stocks.
Educational only — no trade calls, no targets.

🌐 **Live site:** https://myfinancialria.github.io/daily-fno-pulse/
📡 **Sources:** NSE (FII derivative stats) · BSE · Fyers broker API
🤖 **Pipeline:** GitHub Actions cron → Fyers/NSE fetch → analyser → Gemini-grounded article → GitHub Pages + Telegram notification

## Architecture

```
17:30 IST (post-close)            18:00 IST                    18:30 IST  (cron)
NSE settles bhav copies      NSE pubs FII derivative CSV     this workflow runs
                                                                    ↓
                              1. auto_login.py  (Fyers token refresh)
                              2. fetcher.py    (Fyers chains + quotes + NSE CSV)
                                    ↓ data/YYYY-MM-DD.json
                              3. analyzer.py   (8-vote directional framework per index)
                                    ↓ data/YYYY-MM-DD.analysis.json
                              4. writer.py     (Gemini 2.5 + Google-search grounding → MD)
                                    ↓ articles/YYYY-MM-DD-fno-pulse.md
                              5. publish.py    (MD → HTML + index page)
                                    ↓ output/
                              6. git commit + push + GitHub Pages deploy
                              7. Telegram ping → @myfinancialinbot
```

## Files

| File | Purpose |
|---|---|
| `auto_login.py` | Daily Fyers TOTP login (reused from main fyers-bot) |
| `fetcher.py` | Pulls option chains, futures, FII derivative stats |
| `analyzer.py` | Applies the 8-signal directional framework |
| `writer.py` | Calls Gemini 2.5 with grounding to write the article (SEBI-compliant tone) |
| `publish.py` | Renders the Markdown to plain HTML + index |
| `.github/workflows/daily.yml` | 18:30 IST cron, runs the whole pipeline |
| `data/*.json` | Daily structured snapshots |
| `articles/*.md` | Published article source |
| `output/*` | Rendered site for GitHub Pages |

## Manual run

```bash
gh workflow run daily.yml --repo myfinancialria/daily-fno-pulse
```

## Compliance

The author holds a NISM certification but is **not** a SEBI Registered Investment Adviser
or Research Analyst. All articles are framed as educational interpretation of public
end-of-day market data:

- No buy / sell / hold recommendations
- No price targets
- No advisory phrasing
- Disclaimer block at the bottom of every article

This boundary is enforced by the system prompt in `writer.py` and by the deterministic
fallback article in case the LLM misbehaves.
