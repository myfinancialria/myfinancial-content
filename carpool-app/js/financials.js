/* CommuteCircle — 5-year financial model (illustrative).
 * All money values are ₹ crore (1 crore = ₹10,000,000) unless a driver is
 * explicitly in ₹. The base case here is the same one documented in
 * docs/financial-pnl.md; scenario levers scale the revenue drivers and the
 * two biggest cost lines. Pure functions, no DOM.
 */

const CC_FIN = (function () {
  const CR = 1e7;
  const YEARS = ['Year 1', 'Year 2', 'Year 3', 'Year 4', 'Year 5'];

  const BASE = {
    // Demand drivers (annual averages)
    mac:          [5000, 25000, 70000, 140000, 230000], // monthly active commuters
    ridesPerMac:  [12, 14, 15, 16, 16],                 // matched one-way rides / commuter / month
    feePerRide:   [7, 7, 8, 8, 9],                      // ₹ platform fee per matched seat-trip
    covered:      [8000, 45000, 140000, 330000, 580000],// B2B covered employees (avg)
    pepm:         [35, 35, 40, 40, 40],                 // ₹ per employee per month (B2B SaaS)
    premiumPct:   [0.04, 0.05, 0.06, 0.06, 0.07],       // premium subscribers as % of MAC
    premiumPrice: [129, 129, 129, 149, 149],            // ₹ / month
    otherRev:     [0, 0.30, 1.20, 3.00, 6.00],          // ₹ Cr: insurance, EV/fuel partners, ESG reports, ads

    // Cost of revenue (₹ Cr except pgRate)
    cogs: {
      cloud:     [0.18, 0.55, 1.60, 2.90, 4.60],
      apis:      [0.12, 0.50, 1.40, 2.60, 4.20], // maps, SMS/WhatsApp, KYC/verification
      support:   [0.10, 0.45, 1.30, 2.60, 4.30], // support + trust & safety ops
      insurance: [0.03, 0.18, 0.55, 1.10, 1.90], // per-ride micro-insurance cost
      pgRate: 0.021                               // payment gateway, on ride + subscription revenue
    },

    // Operating expenses (₹ Cr)
    opex: {
      people: [3.20, 6.70, 13.50, 21.00, 29.00], // headcount ~18 / 35 / 65 / 100 / 135
      snm:    [1.60, 4.20, 8.00, 12.00, 15.00],  // sales & marketing incl. community activation
      gna:    [0.55, 1.10, 2.20, 3.60, 5.00],    // rent, legal, finance, compliance
      tools:  [0.25, 0.55, 1.10, 1.70, 2.30]     // software, security audits, misc tech
    },

    dna: [0.10, 0.20, 0.40, 0.60, 0.80],          // depreciation & amortisation
    taxRate: 0.25
  };

  const DEFAULT_LEVERS = {
    fee: 1,       // platform fee per ride
    pepm: 1,      // B2B price per employee
    rides: 1,     // matched rides per commuter
    premium: 1,   // premium adoption
    snm: 1,       // marketing spend
    people: 1     // team cost
  };

  const round2 = (v) => Math.round(v * 100) / 100;

  /* Compute the full P&L for a set of levers (multipliers on the base case). */
  function computePnl(levers) {
    const L = Object.assign({}, DEFAULT_LEVERS, levers || {});
    const n = YEARS.length;
    const out = {
      years: YEARS.slice(),
      revenue: { rides: [], saas: [], subs: [], other: [], total: [] },
      cogs: { cloud: [], apis: [], support: [], insurance: [], pg: [], total: [] },
      grossProfit: [], grossMargin: [],
      opex: { people: [], snm: [], gna: [], tools: [], total: [] },
      ebitda: [], ebitdaMargin: [], cumEbitda: [],
      dna: [], ebit: [], tax: [], pat: [],
      drivers: {
        mac: BASE.mac.slice(),
        feePerRide: BASE.feePerRide.map((v) => round2(v * L.fee)),
        pepm: BASE.pepm.map((v) => round2(v * L.pepm)),
        ridesPerMac: BASE.ridesPerMac.map((v) => round2(v * L.rides))
      }
    };

    let cum = 0, cumEbit = 0, taxPaid = 0;
    for (let i = 0; i < n; i++) {
      const rides = BASE.mac[i] * BASE.ridesPerMac[i] * L.rides * BASE.feePerRide[i] * L.fee * 12 / CR;
      const saas = BASE.covered[i] * BASE.pepm[i] * L.pepm * 12 / CR;
      const subs = BASE.mac[i] * BASE.premiumPct[i] * L.premium * BASE.premiumPrice[i] * 12 / CR;
      const other = BASE.otherRev[i];
      const total = rides + saas + subs + other;
      out.revenue.rides.push(rides);
      out.revenue.saas.push(saas);
      out.revenue.subs.push(subs);
      out.revenue.other.push(other);
      out.revenue.total.push(total);

      const pg = BASE.cogs.pgRate * (rides + subs);
      const cogs = BASE.cogs.cloud[i] + BASE.cogs.apis[i] + BASE.cogs.support[i] + BASE.cogs.insurance[i] + pg;
      out.cogs.cloud.push(BASE.cogs.cloud[i]);
      out.cogs.apis.push(BASE.cogs.apis[i]);
      out.cogs.support.push(BASE.cogs.support[i]);
      out.cogs.insurance.push(BASE.cogs.insurance[i]);
      out.cogs.pg.push(pg);
      out.cogs.total.push(cogs);

      const gp = total - cogs;
      out.grossProfit.push(gp);
      out.grossMargin.push(total > 0 ? gp / total : 0);

      const people = BASE.opex.people[i] * L.people;
      const snm = BASE.opex.snm[i] * L.snm;
      const opex = people + snm + BASE.opex.gna[i] + BASE.opex.tools[i];
      out.opex.people.push(people);
      out.opex.snm.push(snm);
      out.opex.gna.push(BASE.opex.gna[i]);
      out.opex.tools.push(BASE.opex.tools[i]);
      out.opex.total.push(opex);

      const ebitda = gp - opex;
      cum += ebitda;
      out.ebitda.push(ebitda);
      out.ebitdaMargin.push(total > 0 ? ebitda / total : 0);
      out.cumEbitda.push(cum);

      const ebit = ebitda - BASE.dna[i];
      cumEbit += ebit;
      out.dna.push(BASE.dna[i]);
      out.ebit.push(ebit);

      // Tax only once cumulative pre-tax profit turns positive (loss carry-forward).
      const due = Math.max(0, BASE.taxRate * cumEbit - taxPaid);
      taxPaid += due;
      out.tax.push(due);
      out.pat.push(ebit - due);
    }

    out.peakFundingNeed = -Math.min(0, Math.min.apply(null, out.cumEbitda));
    const beIdx = out.ebitda.findIndex((v) => v >= 0);
    out.breakevenYear = beIdx === -1 ? null : beIdx + 1;
    return out;
  }

  /* Rows for the P&L table and the CSV export, from a computed model. */
  function pnlRows(m) {
    const pct = (v) => (v * 100).toFixed(1) + '%';
    const r = (arr) => arr.map(round2);
    return [
      { label: 'Ride convenience fees', values: r(m.revenue.rides), group: 'Revenue' },
      { label: 'B2B SaaS (employers & parks)', values: r(m.revenue.saas), group: 'Revenue' },
      { label: 'Premium subscriptions', values: r(m.revenue.subs), group: 'Revenue' },
      { label: 'Partnerships & other', values: r(m.revenue.other), group: 'Revenue' },
      { label: 'Total revenue', values: r(m.revenue.total), strong: true },
      { label: 'Cloud & infrastructure', values: r(m.cogs.cloud), group: 'Cost of revenue' },
      { label: 'Maps, messaging & verification', values: r(m.cogs.apis), group: 'Cost of revenue' },
      { label: 'Support, trust & safety', values: r(m.cogs.support), group: 'Cost of revenue' },
      { label: 'Ride micro-insurance', values: r(m.cogs.insurance), group: 'Cost of revenue' },
      { label: 'Payment gateway', values: r(m.cogs.pg), group: 'Cost of revenue' },
      { label: 'Total cost of revenue', values: r(m.cogs.total), strong: true },
      { label: 'Gross profit', values: r(m.grossProfit), strong: true },
      { label: 'Gross margin', values: m.grossMargin.map(pct), isText: true },
      { label: 'People', values: r(m.opex.people), group: 'Operating expenses' },
      { label: 'Sales & marketing', values: r(m.opex.snm), group: 'Operating expenses' },
      { label: 'General & administrative', values: r(m.opex.gna), group: 'Operating expenses' },
      { label: 'Tools & other tech', values: r(m.opex.tools), group: 'Operating expenses' },
      { label: 'Total operating expenses', values: r(m.opex.total), strong: true },
      { label: 'EBITDA', values: r(m.ebitda), strong: true, signed: true },
      { label: 'EBITDA margin', values: m.ebitdaMargin.map(pct), isText: true },
      { label: 'Cumulative EBITDA', values: r(m.cumEbitda), signed: true },
      { label: 'Depreciation & amortisation', values: r(m.dna) },
      { label: 'EBIT', values: r(m.ebit), strong: true, signed: true },
      { label: 'Tax', values: r(m.tax) },
      { label: 'Profit after tax', values: r(m.pat), strong: true, signed: true }
    ];
  }

  function toCsv(m) {
    const lines = [['Line item (₹ crore)'].concat(m.years).join(',')];
    for (const row of pnlRows(m)) {
      lines.push([row.label].concat(row.values).join(','));
    }
    return lines.join('\n');
  }

  return { BASE, DEFAULT_LEVERS, YEARS, computePnl, pnlRows, toCsv };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = CC_FIN;
