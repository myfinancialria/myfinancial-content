/* Node sanity tests for the CommuteCircle matching engine and financial model.
 * Run: node carpool-app/test/model.test.cjs */

const assert = require('assert');
const D = require('../js/data.js');
const M = require('../js/matching.js');
const F = require('../js/financials.js');

let passed = 0;
function check(name, fn) {
  fn();
  passed++;
  console.log('ok  ' + name);
}
const close = (a, b, tol) => Math.abs(a - b) <= (tol == null ? 0.01 : tol);

/* ---------------- matching ---------------- */

check('default persona gets a healthy match list', () => {
  const ms = M.findMatches(D.defaultPersona, D.users, D);
  assert.strictEqual(ms.length, 6, 'expected 6 matches, got ' + ms.length);
  const ids = ms.map((m) => m.user.id);
  assert.ok(ids.indexOf('u13') === -1, 'different origin area must not match');
  assert.ok(ids.indexOf('u6') === -1, 'different corridor must not match');
});

check('top match shares all three circles', () => {
  const ms = M.findMatches(D.defaultPersona, D.users, D);
  assert.strictEqual(ms[0].user.id, 'u2');
  assert.ok(ms[0].score >= 95 && ms[0].score <= 100, 'score was ' + ms[0].score);
  assert.strictEqual(ms[0].tier.key, 'excellent');
});

check('scores are sorted and within bounds', () => {
  const ms = M.findMatches(D.defaultPersona, D.users, D);
  for (let i = 1; i < ms.length; i++) assert.ok(ms[i - 1].score >= ms[i].score);
  ms.forEach((m) => assert.ok(m.score >= M.MATCH_THRESHOLD && m.score <= 100));
});

check('women-only drivers are hidden from male riders', () => {
  const male = Object.assign({}, D.defaultPersona, { gender: 'M' });
  const ids = M.findMatches(male, D.users, D).map((m) => m.user.id);
  assert.ok(ids.indexOf('u9') === -1, 'women-only driver leaked to male rider');
  assert.ok(ids.indexOf('u2') !== -1, 'regular driver should still match');
});

check('a driver persona is matched with riders, not drivers', () => {
  const driver = Object.assign({}, D.defaultPersona, { role: 'driver', seats: 3 });
  const ms = M.findMatches(driver, D.users, D);
  assert.ok(ms.length >= 3, 'expected at least 3 rider matches');
  ms.forEach((m) => assert.notStrictEqual(m.user.role, 'driver'));
});

check('riders never match riders', () => {
  const ms = M.findMatches(D.defaultPersona, D.users, D);
  ms.forEach((m) => assert.notStrictEqual(m.user.role, 'rider'));
});

check('trip economics: 3-way split beats a cab by a wide margin', () => {
  const e = M.tripEconomics(D, 'whitefield', 'bellandur', 2);
  assert.ok(close(e.km, 12.0, 0.1), 'km was ' + e.km);
  assert.strictEqual(e.riderPays, 36);
  assert.ok(e.riderSavesVsCab >= 200, 'savings were ' + e.riderSavesVsCab);
});

/* ---------------- financial model ---------------- */

check('base case P&L matches the documented figures', () => {
  const m = F.computePnl();
  assert.ok(close(m.revenue.total[0], 0.87), 'Y1 revenue ' + m.revenue.total[0]);
  assert.ok(close(m.revenue.total[2], 18.65), 'Y3 revenue ' + m.revenue.total[2]);
  assert.ok(close(m.revenue.total[4], 76.46), 'Y5 revenue ' + m.revenue.total[4]);
  assert.ok(close(m.grossMargin[4], 0.792, 0.002), 'Y5 GM ' + m.grossMargin[4]);
  assert.ok(close(m.ebitda[0], -5.17), 'Y1 EBITDA ' + m.ebitda[0]);
  assert.ok(close(m.ebitda[4], 9.27), 'Y5 EBITDA ' + m.ebitda[4]);
  assert.ok(close(m.peakFundingNeed, 31.50), 'peak burn ' + m.peakFundingNeed);
  assert.strictEqual(m.breakevenYear, 5);
});

check('loss carry-forward keeps tax at zero through Year 5 in the base case', () => {
  const m = F.computePnl();
  m.tax.forEach((t) => assert.strictEqual(t, 0));
  for (let i = 0; i < 5; i++) assert.ok(close(m.pat[i], m.ebit[i]));
});

check('levers move the model in the right direction', () => {
  const base = F.computePnl();
  const up = F.computePnl({ fee: 1.2 });
  assert.ok(close(up.revenue.rides[4], base.revenue.rides[4] * 1.2, 0.02));
  assert.ok(up.ebitda[4] > base.ebitda[4]);
  const lean = F.computePnl({ people: 0.8, snm: 0.8 });
  assert.ok(lean.peakFundingNeed < base.peakFundingNeed);
  const heavy = F.computePnl({ people: 1.4, snm: 1.4, fee: 0.6 });
  assert.strictEqual(heavy.breakevenYear, null);
});

check('CSV export carries every P&L row', () => {
  const m = F.computePnl();
  const csv = F.toCsv(m);
  const lines = csv.split('\n');
  assert.strictEqual(lines.length, 1 + F.pnlRows(m).length);
  assert.ok(lines[0].indexOf('Year 5') !== -1);
  assert.ok(csv.indexOf('Total revenue') !== -1);
  assert.ok(csv.indexOf('Profit after tax') !== -1);
});

console.log('\n' + passed + ' checks passed');
