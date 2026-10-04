# CommuteCircle — Five-Year Financial Plan & P&L

All figures in **₹ crore** (1 crore = ₹10 million) unless stated otherwise.
Years are operating years from launch (FY basis once incorporated). This is
the **base case**; the interactive model in the app (`Financials` tab)
recomputes every line from the same drivers and lets you stress them ×0.60 to
×1.40. The code that produces these numbers is `js/financials.js`, pinned by
`test/model.test.cjs`.

---

## 1. Revenue drivers

| Driver | Y1 | Y2 | Y3 | Y4 | Y5 |
|---|---:|---:|---:|---:|---:|
| Cities live | 1 | 3 | 5 | 6 | 6 |
| Registered users (exit, '000) | 40 | 150 | 400 | 800 | 1,300 |
| Monthly active commuters, avg ('000) | 5 | 25 | 70 | 140 | 230 |
| Matched one-way rides / active / month | 12 | 14 | 15 | 16 | 16 |
| Platform fee per matched ride (₹) | 7 | 7 | 8 | 8 | 9 |
| B2B covered employees, avg ('000) | 8 | 45 | 140 | 330 | 580 |
| B2B price (₹ / employee / month) | 35 | 35 | 40 | 40 | 40 |
| Premium subscribers (% of actives) | 4% | 5% | 6% | 6% | 7% |
| Premium price (₹ / month) | 129 | 129 | 129 | 149 | 149 |
| Team size, approx. | 18 | 35 | 65 | 100 | 135 |

Activity logic: a five-day commuter makes ~44 one-way trips a month; the model
assumes only 27–36% of them are matched through the platform (12–16 rides),
which absorbs hybrid work and pool downtime.

## 2. Revenue build-up (₹ Cr)

| Stream | Formula | Y1 | Y2 | Y3 | Y4 | Y5 |
|---|---|---:|---:|---:|---:|---:|
| Ride convenience fees | actives × rides × fee × 12 | 0.50 | 2.94 | 10.08 | 21.50 | 39.74 |
| B2B SaaS (employers & parks) | covered × PEPM × 12 | 0.34 | 1.89 | 6.72 | 15.84 | 27.84 |
| Premium subscriptions | actives × adoption × price × 12 | 0.03 | 0.19 | 0.65 | 1.50 | 2.88 |
| Partnerships & other | insurance co-brand, EV/fuel, ESG, offers | 0.00 | 0.30 | 1.20 | 3.00 | 6.00 |
| **Total revenue** | | **0.87** | **5.32** | **18.65** | **41.85** | **76.46** |

Mix shifts from B2C-heavy to a healthy ~52/36/12 split (rides / B2B / rest)
by Year 5. No stream depends on taking a cut of the driver's cost share.

## 3. Profit & loss statement (₹ Cr)

| | Y1 | Y2 | Y3 | Y4 | Y5 |
|---|---:|---:|---:|---:|---:|
| **Revenue** | **0.87** | **5.32** | **18.65** | **41.85** | **76.46** |
| Cloud & infrastructure | 0.18 | 0.55 | 1.60 | 2.90 | 4.60 |
| Maps, messaging & verification APIs | 0.12 | 0.50 | 1.40 | 2.60 | 4.20 |
| Support, trust & safety ops | 0.10 | 0.45 | 1.30 | 2.60 | 4.30 |
| Ride micro-insurance | 0.03 | 0.18 | 0.55 | 1.10 | 1.90 |
| Payment gateway (~2.1% of B2C collections) | 0.01 | 0.07 | 0.23 | 0.48 | 0.90 |
| **Total cost of revenue** | **0.44** | **1.75** | **5.08** | **9.68** | **15.90** |
| **Gross profit** | **0.43** | **3.58** | **13.58** | **32.16** | **60.57** |
| *Gross margin* | *49.3%* | *67.2%* | *72.8%* | *76.9%* | *79.2%* |
| People | 3.20 | 6.70 | 13.50 | 21.00 | 29.00 |
| Sales & marketing (incl. community activation) | 1.60 | 4.20 | 8.00 | 12.00 | 15.00 |
| General & administrative | 0.55 | 1.10 | 2.20 | 3.60 | 5.00 |
| Tools & other tech | 0.25 | 0.55 | 1.10 | 1.70 | 2.30 |
| **Total operating expenses** | **5.60** | **12.55** | **24.80** | **38.30** | **51.30** |
| **EBITDA** | **(5.17)** | **(8.97)** | **(11.22)** | **(6.14)** | **9.27** |
| *EBITDA margin* | *—* | *−168.6%* | *−60.2%* | *−14.7%* | *+12.1%* |
| Cumulative EBITDA | (5.17) | (14.14) | (25.37) | (31.50) | (22.24) |
| Depreciation & amortisation | 0.10 | 0.20 | 0.40 | 0.60 | 0.80 |
| **EBIT** | **(5.27)** | **(9.17)** | **(11.62)** | **(6.74)** | **8.47** |
| Tax (losses carried forward) | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| **Profit after tax** | **(5.27)** | **(9.17)** | **(11.62)** | **(6.74)** | **8.47** |

Parentheses denote losses. Tax stays nil through Year 5 because cumulative
pre-tax losses (₹32.8 Cr by end-Y4) exceed the Year 5 profit; cash taxes begin
in Year 6 under the carried-forward-loss regime (or 22–25% on book profits
thereafter, depending on the regime elected).

### Reading the shape

- **Year 1 (₹0.87 Cr revenue, ₹5.2 Cr EBITDA loss, ~₹43 lakh/month burn):**
  product + two corridors + first 8–10 logos. Revenue is deliberately small;
  the year buys proof of matched-ride rate and B2B willingness to pay.
- **Years 2–3 (burn peaks at ~₹94 lakh/month in Y3):** city expansion runs
  ahead of revenue — the classic marketplace J-curve. Gross margin crossing
  70% in Y3 shows the model working; losses are a scaling choice, not a
  unit-economics failure.
- **Year 4 (loss narrows to ₹6.1 Cr):** existing corridors mature (S&M grows
  slower than gross profit).
- **Year 5 (+₹9.3 Cr EBITDA, 12.1% margin):** monthly EBITDA break-even lands
  in H1; the full year is positive.

## 4. Break-even math

At the Year 5 cost structure (~79% gross margin, ₹51.3 Cr opex), EBITDA
break-even needs ~₹64.8 Cr of annualised revenue (~₹5.4 Cr/month) — roughly
**195K monthly active commuters plus ~490K covered B2B employees** at Year 5
pricing. The base case crosses that run-rate during H1 of Year 5.

## 5. Sensitivity — Year 5 EBITDA (₹ Cr)

Two levers dominate: the platform fee and matched rides per active commuter.

| Y5 EBITDA | Rides ×0.8 | Rides ×1.0 | Rides ×1.2 |
|---|---:|---:|---:|
| **Fee ×0.8 (₹7.2)** | (4.7) | 1.5 | 7.7 |
| **Fee ×1.0 (₹9.0)** | 1.5 | **9.3** | 17.1 |
| **Fee ×1.2 (₹10.8)** | 7.7 | 17.1 | 26.4 |

Even the double-downside case (both ×0.8) loses only ~₹4.7 Cr in Year 5 —
survivable with the Series B buffer — while the B2B stream, which is
insensitive to ride volumes, keeps compounding. Cost-side stress: holding
people + marketing at ×1.2 through Year 5 delays EBITDA break-even beyond the
plan window; the model's levers make that visible instantly.

## 6. Funding plan

| Round | Timing | Size | Primary use |
|---|---|---:|---|
| Seed | now | ₹7 Cr | product, 2 corridors, first logos (18-month runway) |
| Series A | month 15–18 | ₹30 Cr | 3 cities, B2B sales team, trust & safety scale-up |
| Series B | year 3–4 | ₹25 Cr | 6 metros, ride to break-even, GRH float |
| **Total** | | **₹62 Cr** | vs peak cumulative EBITDA burn of **₹31.5 Cr** |

Headroom above operating burn covers capex (₹0.5–1 Cr/year), the
guaranteed-ride-home float, working capital and an 18-month buffer against the
downside sensitivity above.

## 7. What the model deliberately does *not* assume

- No commission on the driver's cost share (regulatory position).
- No intercity, freight or delivery revenue.
- No monetisation of individual-level data.
- No government/HOV incentives, though any would be upside.
- No Year 6+ terminal-value heroics — the plan is judged on reaching
  self-funding scale.

---

*Illustrative projections prepared for a product concept. These are planning
assumptions, not forecasts or guidance, and nothing here is investment
advice.*
