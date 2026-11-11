# CommuteCircle — trust-circle carpooling (prototype + business plan)

A working web-app prototype and business case for a commute-pooling platform
that connects people from the **same residential community, the same
organisation, or the same commercial building** and matches those travelling
the same corridor at the same time, so they can travel together and split
costs.

## Run it

No build step, no dependencies:

```
open carpool-app/index.html        # or double-click it in a file manager
```

Everything runs client-side on fictional sample data. The demo profile and
connections persist in `localStorage` only.

## What's inside

| Path | What it is |
|---|---|
| `index.html` | The app shell: Home, Find matches, My commute, Business model, Financials |
| `js/data.js` | Sample circles (communities, orgs, buildings), areas and commuters |
| `js/matching.js` | Matching engine: trust-circle + schedule + destination scoring (0–100) |
| `js/financials.js` | Five-year P&L model with scenario levers (base case documented in docs) |
| `js/app.js` | UI: matching demo, pool/cost-split view, interactive financial dashboard |
| `css/styles.css` | Theming (light + dark), layout, chart styles |
| `docs/business-model.md` | Full business model: problem, product, market, revenue streams, GTM, moat, regulation, funding |
| `docs/financial-pnl.md` | Five-year P&L: drivers, statement, break-even, sensitivity, funding plan |
| `test/model.test.cjs` | Sanity tests pinning the matching engine and the P&L base case |

## Test

```
node carpool-app/test/model.test.cjs
```

11 checks cover match filtering (roles, women-only pools, origin/destination
gates), score ordering, trip economics, the documented base-case P&L figures,
loss carry-forward tax logic, lever behaviour and the CSV export.

## Headline numbers (base case, ₹ crore)

| | Y1 | Y2 | Y3 | Y4 | Y5 |
|---|---:|---:|---:|---:|---:|
| Revenue | 0.87 | 5.32 | 18.65 | 41.85 | 76.46 |
| Gross margin | 49% | 67% | 73% | 77% | 79% |
| EBITDA | (5.17) | (8.97) | (11.22) | (6.14) | 9.27 |

EBITDA-positive in Year 5; peak cumulative burn ~₹31.5 Cr; funding plan
₹62 Cr across three rounds. Details and sensitivities in
[`docs/financial-pnl.md`](docs/financial-pnl.md).

---

All people, companies, communities and buildings in the demo are fictional.
Financial projections are illustrative assumptions, not forecasts, and nothing
here is investment advice.
