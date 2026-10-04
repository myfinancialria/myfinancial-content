# CommuteCircle — Business Model

**Trust-circle carpooling for Indian metros: ride with people you already know.**

CommuteCircle connects commuters who belong to the same *trust circles* — the
same residential community, the same organisation, or the same commercial
building / tech park — and matches those travelling the same corridor at the
same time so they can pool one car instead of driving three. A working
prototype of the product (matching engine, cost split, interactive financial
model) lives in this folder; the five-year P&L behind this plan is in
[`financial-pnl.md`](financial-pnl.md).

---

## 1. Executive summary

- **What it is:** a commute-pooling platform where matching happens only inside
  verified circles (community, employer, building), never on an open
  marketplace.
- **Why it wins:** trust is the real blocker to carpooling in India, especially
  for women; circles import trust that already exists (the RWA knows the
  driver, HR knows the rider, the building knows both).
- **Who pays:** riders pay a small per-ride convenience fee; employers and tech
  park operators pay SaaS for verified circles, parking relief and Scope 3
  commute reporting; power users pay a premium subscription; partners
  (insurance, EV/fuel, ESG) add a fourth stream.
- **Scale plan:** density-first. Two Bengaluru corridors in Year 1, six metros
  by Year 5, reaching ~1.3M registered users, ~230K monthly active commuters
  and ~580K B2B-covered employees.
- **Money plan:** ₹0.9 Cr revenue in Year 1 growing to ₹76.5 Cr in Year 5,
  EBITDA-positive in Year 5, peak cumulative burn ~₹31.5 Cr, funded by ~₹62 Cr
  across Seed / Series A / Series B.

---

## 2. The problem

1. **Commutes are expensive and slow.** A metro office commuter loses 1.5–3
   hours and roughly ₹6,000–₹15,000 a month (fuel + parking, or cabs). Tech
   corridors like Bengaluru's ORR move tens of thousands of cars a day at
   average occupancy near 1.2.
2. **Employers subsidise the mess.** Parking costs ₹3,000–₹8,000 per slot per
   month in commercial buildings; long commutes drive attrition; new ESG rules
   (BRSR) push large companies to measure and cut employee-commute emissions.
3. **Open carpooling stalled on trust and regulation.** Stranger-matching apps
   have existed for a decade. Women (roughly half of tech park headcount) use
   them least; several states have pushed back on private cars earning fare
   income, which scares casual drivers away.

The insight: **matching was never the hard part — trust and regulatory
cleanliness were.** Both are solved structurally, not by features: match only
inside accountable groups, and cap money flows at cost sharing.

## 3. The product

- **Trust circles.** Members verify into circles: a *residential community*
  (society code issued by the RWA / association), an *organisation* (work
  email), a *commercial building or tech park* (facility operator). Profiles
  are visible only inside shared circles.
- **Commute posting.** Each member posts a recurring commute: origin, workplace
  destination, departure window, weekdays, and role (driver offering seats /
  rider needing one / either).
- **Matching engine.** Scores every compatible member of your circles:
  shared community (30), shared organisation (20), shared building (15),
  schedule overlap (up to 15), destination proximity (up to 15), full
  verification (5). Threshold and tiering keep only credible matches. Women-only
  pools are a hard filter, not a preference.
- **Pools.** Matches form recurring pools with one schedule, automatic cost
  split (capped at fuel + tolls), in-app payments, live trip sharing, ratings
  and a guaranteed-ride-home backstop.
- **Employer/operator console.** Verified onboarding, circle analytics, parking
  demand dashboards, Scope 3 commute reports.

Roadmap after v1: en-route pickups along a corridor (not just same-origin),
shift-worker matching, EV pool incentives, inter-community shuttle
aggregation where density supports a 12-seater.

## 4. Market

| Layer | Size | Basis |
|---|---|---|
| TAM | ~70M | daily commuters across the top-10 Indian metros |
| SAM | ~12M | private-vehicle office commuters in the top-6 metros (Bengaluru, NCR, Mumbai, Hyderabad, Chennai, Pune) |
| SOM (Year 5) | 1.3M registered / 230K monthly active | 6 metros, corridor-by-corridor rollout |

Value pools on top of consumer fees: corporate mobility / employee-transport
software spend (PEPM budgets already exist for transport SaaS), commercial
real estate parking management, and ESG reporting budgets.

## 5. Customers and value propositions

| Stakeholder | Pain | What CommuteCircle gives them |
|---|---|---|
| Rider | Cab costs, unreliable autos, safety worries | Seat with a verified neighbour/colleague at ~15–20% of cab cost; women-only pools |
| Driver | Fuel + parking burn, solo drive | Recovers ₹2,000–₹4,500/month of running cost; HOV/parking perks where available |
| Employer (HR / admin / ESG) | Parking crunch, attrition, BRSR Scope 3 reporting | Verified employee circles, measurable emission cuts, cheaper than adding parking or buses |
| Tech park / building operator | Parking demand > supply, tenant experience | Building-wide pooling, priority pool parking, congestion analytics |
| RWA / residential community | Gate congestion, resident demand | Free community tool, safer than residents using open apps |

## 6. Revenue streams and pricing

1. **Ride convenience fee — ₹7–9 per matched seat-trip** (rider-side, on top of
   the cost share). The cost share itself passes driver-to-rider and is capped
   at fuel + tolls; the platform monetises matching, not mileage. ~52% of
   Year 5 revenue.
2. **B2B SaaS — ₹35–40 per covered employee per month** for employers
   (verified circles, guaranteed-ride-home pool, ESG reports), plus **₹2–3
   lakh/year per tech park** licences. ~36% of Year 5 revenue, and the reason
   CAC stays low: the employer recruits users for us.
3. **Premium subscription — ₹129–149/month** (4–7% of monthly actives):
   priority matching, extra guaranteed-ride-home cover, multi-circle
   visibility.
4. **Partnerships & data products:** per-ride micro-insurance (bundled, costed
   in COGS; co-branded upside), fuel/EV-charging tie-ups, hyperlocal corridor
   offers, anonymised congestion insights for operators. Scales from ~₹0.3 Cr
   (Y2) to ~₹6 Cr (Y5).

**Deliberately not revenue:** a percentage of the cost share. That would make
pooling commercial, break the regulatory position, and cap driver supply.

## 7. Unit economics (Year 3 steady state)

| Metric | Value |
|---|---|
| Blended revenue per monthly active commuter | ~₹222/month |
| Variable cost per active commuter | ~₹61/month |
| Contribution | ~₹161/month (73%) |
| Blended CAC per *activated* commuter | ~₹750 (60%+ join via community/employer channels) |
| CAC payback | ~4.7 months |
| Retained active life | ~24 months (commutes are habitual; density raises retention) |
| LTV / CAC | ~5× |

Driver and rider economics (typical 12 km Whitefield → Bellandur leg, 3
people/car): running cost ₹84/trip; each person's share ₹28; rider pays ₹36
including the platform fee vs ~₹276 by cab; the driver recovers ~₹56/trip
(~₹2,400/month). One pooled rider avoids ~0.9–1.0 tonne CO₂ a year.

## 8. Go-to-market: the corridor playbook

Carpooling dies when demand is thin, so growth is corridor-by-corridor
(5–7 km micro-markets), not city-wide:

1. **Sign the origin side:** 10–15 large residential communities via RWAs;
   society-code onboarding at the gate; launch-week pool fairs.
2. **Sign the destination side:** two anchor employers as paid pilots; HR
   pushes verified onboarding to long-commute employees.
3. **Unlock adoption:** women-only pools and guaranteed ride home are on from
   day one — they are the reason people try it, not add-ons.
4. **Convert the operator:** the tech park licenses building circles and gives
   pools priority parking (a free, powerful incentive).
5. **Replicate.** Each new circle raises match rates for existing members;
   liquidity compounds and churn falls.

Year 1 = two Bengaluru corridors (e.g., Whitefield→ORR, Sarjapur→ORR).
Year 2 adds Hyderabad and Pune. Years 3–5 deepen six metros.

## 9. Competition and moat

| Player | Model | Gap CommuteCircle exploits |
|---|---|---|
| Quick Ride, sRide | Open intracity carpool marketplaces | Open discovery = trust ceiling, weak with women; consumer-fee-only economics |
| BlaBlaCar | Intercity pooling | Not a daily-commute product |
| Uber/Ola share | Commercial ride-hailing | 4–6× the cost of cost-shared pooling; driver supply cost |
| MoveInSync, Routematic | Employer transport ops (buses/cabs) | Asset-heavy, employer-paid transport; we're the asset-light layer beside it |

**Moat, in order of durability:** (1) the verified trust graph — circles,
ratings and history that an open app cannot retrofit; (2) corridor density —
the liquid network in a corridor wins it outright; (3) multi-year B2B
contracts that make pooling part of employer policy; (4) a compounding
ESG/commute dataset employers need for BRSR reporting.

## 10. Regulation, risk and mitigation

| Risk | Reality | Mitigation |
|---|---|---|
| Private-car pooling legality | Grey zone under the Motor Vehicles Act; some states (e.g., Karnataka in 2023) have moved against monetised private rides | Hard product cap: cost share ≤ fuel + tolls, drivers cannot profit; platform revenue = tech fee + SaaS, never a fare cut; state-level legal review before each launch |
| Insurance on shared rides | Private policies can dispute shared-ride claims | Bundled per-ride group micro-cover (costed in COGS) with an insurer partner |
| Safety incident | Low-probability, existential brand risk | Verified-only circles, women-only pools, live trip share, SOS, 24×7 desk, incident SOPs with communities/employers |
| Data privacy | Commute data is sensitive; DPDP Act 2023 applies | Consent-first design, circle-scoped visibility, no individual-level data sales, Indian data residency |
| Cold start / liquidity | Matching fails below density threshold | Corridor playbook, employer-pushed onboarding, guaranteed ride home to de-risk trying |
| WFH / hybrid swings | Fewer commute days per user | Model already assumes 12–16 matched rides/month (≈3–4 pooled days/week); B2B revenue is attendance-insensitive |

## 11. Milestones and funding

| Round | Size | Gets us to |
|---|---|---|
| Seed (now) | ₹7 Cr | 2 corridors live, 8–10 paying logos, 8K monthly actives, matched-ride rate > 55% |
| Series A (month ~15–18) | ₹30 Cr | 3 cities, 70K monthly actives, ₹18–19 Cr revenue run-rate by Y3 exit |
| Series B (year 3–4) | ₹25 Cr | 6 metros, EBITDA break-even in Year 5, ~₹76 Cr Year 5 revenue |

Peak cumulative EBITDA burn is ~₹31.5 Cr (end of Year 4); the raise adds
capex, the guaranteed-ride-home float, working capital and an 18-month buffer.
Full statement: [`financial-pnl.md`](financial-pnl.md).

## 12. KPIs

- Matched-commute rate (posted → matched within 48h): target 60%+ in dense corridors
- Matched rides per monthly active commuter: 12 → 16 across the plan
- Circle density: verified members per community / per building
- B2B: covered employees, logo retention (>90%), PEPM expansion
- CAC payback < 6 months blended; contribution margin ≥ 70% from Year 3
- Safety: incidents per 100K rides, median response time, women-only pool share

---

*This is an illustrative business plan for a product concept. Market figures
are directional estimates for planning, not audited data, and nothing here is
investment advice.*
