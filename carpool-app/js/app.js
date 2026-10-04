/* CommuteCircle — UI layer. Depends on CC_DATA, CC_MATCH, CC_FIN. */

(function () {
  'use strict';
  const D = CC_DATA, M = CC_MATCH, F = CC_FIN;
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.prototype.slice.call((root || document).querySelectorAll(sel));
  const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const SVG_NS = 'http://www.w3.org/2000/svg';

  /* ---------- storage (per-viewer convenience only; app works without it) */
  function loadLS(key) {
    try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : null; }
    catch (e) { return null; }
  }
  function saveLS(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* fine */ }
  }
  function clearLS() {
    try { localStorage.removeItem('cc_persona'); localStorage.removeItem('cc_connections'); }
    catch (e) { /* fine */ }
  }

  /* ---------- state */
  const state = {
    persona: Object.assign({}, D.defaultPersona, loadLS('cc_persona') || {}),
    connections: loadLS('cc_connections') || [],
    levers: Object.assign({}, F.DEFAULT_LEVERS),
    matches: []
  };

  /* ---------- lookups & formatting */
  const byId = (arr) => arr.reduce((m, o) => { m[o.id] = o; return m; }, {});
  const COMM = byId(D.communities), ORG = byId(D.orgs), BLDG = byId(D.buildings);
  const USER = byId(D.users);

  function fmtTime(h) {
    const hh = Math.floor(h), mm = Math.round((h - hh) * 60);
    const ampm = hh >= 12 ? 'pm' : 'am';
    const h12 = ((hh + 11) % 12) + 1;
    return h12 + ':' + String(mm).padStart(2, '0') + ' ' + ampm;
  }
  function fmtCr(v, dp) {
    const d = dp == null ? 1 : dp;
    const s = Math.abs(v).toFixed(d);
    return (v < 0 ? '−' : '') + '₹' + s + ' Cr';
  }
  function fmtNum(v) { return v.toLocaleString('en-IN'); }
  function initials(name) {
    return name.split(/\s+/).slice(0, 2).map((w) => w[0] || '').join('').toUpperCase();
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) for (const k in attrs) {
      if (k === 'text') node.textContent = attrs[k];
      else if (k === 'class') node.className = attrs[k];
      else if (k.slice(0, 2) === 'on') node.addEventListener(k.slice(2), attrs[k]);
      else node.setAttribute(k, attrs[k]);
    }
    (children || []).forEach((c) => { if (c) node.appendChild(c); });
    return node;
  }
  function svgEl(tag, attrs) {
    const node = document.createElementNS(SVG_NS, tag);
    if (attrs) for (const k in attrs) {
      if (k === 'text') node.textContent = attrs[k];
      else node.setAttribute(k, attrs[k]);
    }
    return node;
  }

  /* ---------- toast */
  let toastTimer = null;
  function toast(msg) {
    const t = $('#toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 2600);
  }

  /* ---------- router */
  const VIEWS = ['home', 'matches', 'commute', 'business', 'financials'];
  function showView(id, skipHash) {
    if (VIEWS.indexOf(id) === -1) id = 'home';
    VIEWS.forEach((v) => { $('#view-' + v).hidden = v !== id; });
    $$('.nav-link').forEach((a) => {
      const on = a.getAttribute('data-view') === id;
      if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    if (id === 'matches') renderMatches();
    if (id === 'commute') renderCommute();
    if (!skipHash && location.hash !== '#' + id) {
      try { location.hash = id; } catch (e) { /* fine */ }
    }
    window.scrollTo(0, 0);
  }

  /* ---------- profile form */
  function fillSelect(sel, items, current, noneLabel) {
    sel.textContent = '';
    if (noneLabel) sel.appendChild(el('option', { value: '', text: noneLabel }));
    items.forEach((it) => {
      const o = el('option', { value: it.id, text: it.name });
      if (it.id === current) o.selected = true;
      sel.appendChild(o);
    });
  }
  function timeOptions(sel, from, to, current) {
    sel.textContent = '';
    for (let h = from; h <= to + 0.001; h += 0.25) {
      const v = Math.round(h * 100) / 100;
      const o = el('option', { value: String(v), text: fmtTime(v) });
      if (Math.abs(v - current) < 0.01) o.selected = true;
      sel.appendChild(o);
    }
  }

  function syncRoleFields() {
    const role = $('#f-role').value;
    $('#f-seats-wrap').hidden = role === 'rider';
    const isF = $('#f-gender').value === 'F';
    $('#f-women-wrap').hidden = !isF;
    if (!isF) $('#f-women').checked = false;
  }

  function initProfileForm() {
    const p = state.persona;
    $('#f-name').value = p.name;
    $('#f-gender').value = p.gender;
    $('#f-role').value = p.role;
    fillSelect($('#f-community'), D.communities, p.community);
    fillSelect($('#f-org'), D.orgs, p.org, 'No organisation circle');
    fillSelect($('#f-building'), D.buildings, p.building, 'No building circle');
    timeOptions($('#f-start'), 6, 11, p.window[0]);
    timeOptions($('#f-end'), 6.5, 12, p.window[1]);
    $('#f-seats').value = String(p.seats || 2);
    $('#f-women').checked = Boolean(p.womenOnly);
    for (let d = 0; d < 7; d++) $('#f-day-' + d).checked = p.days.indexOf(d) !== -1;
    syncRoleFields();

    $('#f-role').addEventListener('change', syncRoleFields);
    $('#f-gender').addEventListener('change', syncRoleFields);
    $('#profile-form').addEventListener('submit', (ev) => {
      ev.preventDefault();
      const community = $('#f-community').value;
      const building = $('#f-building').value || null;
      const days = [];
      for (let d = 0; d < 7; d++) if ($('#f-day-' + d).checked) days.push(d);
      let w0 = parseFloat($('#f-start').value), w1 = parseFloat($('#f-end').value);
      if (w1 <= w0) w1 = w0 + 0.5;
      if (days.length === 0) { toast('Pick at least one travel day'); return; }
      state.persona = Object.assign({}, state.persona, {
        name: $('#f-name').value.trim() || 'You',
        gender: $('#f-gender').value,
        role: $('#f-role').value,
        community,
        org: $('#f-org').value || null,
        building,
        home: (COMM[community] || {}).area || state.persona.home,
        dest: building ? BLDG[building].area : state.persona.dest,
        window: [w0, w1],
        days,
        seats: parseInt($('#f-seats').value, 10) || 0,
        womenOnly: $('#f-women').checked
      });
      saveLS('cc_persona', state.persona);
      renderMatches();
      toast('Profile updated — matches refreshed');
      const results = $('#match-results');
      if (results) results.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  /* ---------- matches */
  function circleChips(u) {
    const p = state.persona;
    const chips = [];
    if (u.community === p.community) chips.push({ label: COMM[u.community].name, kind: 'community' });
    if (u.org && u.org === p.org) chips.push({ label: ORG[u.org].name, kind: 'org' });
    if (u.building && u.building === p.building) chips.push({ label: BLDG[u.building].name, kind: 'building' });
    return chips;
  }

  function renderMatches() {
    state.matches = M.findMatches(state.persona, D.users, D);
    const p = state.persona;
    const wrap = $('#match-results');
    const summary = $('#match-summary');
    wrap.textContent = '';

    const destName = p.building ? BLDG[p.building].name : D.areas[p.dest].name;
    summary.textContent = state.matches.length + ' match' + (state.matches.length === 1 ? '' : 'es') +
      ' for ' + p.name + ' · ' + COMM[p.community].name + ' → ' + destName +
      ' · leaves ' + fmtTime(p.window[0]) + '–' + fmtTime(p.window[1]) +
      (p.role === 'rider' ? ' · looking for a seat' : p.role === 'driver' ? ' · offering seats' : '');

    if (state.matches.length === 0) {
      wrap.appendChild(el('div', { class: 'empty card', text: 'No matches inside your circles yet. Widen your departure window, add your workplace circle, or invite neighbours — matching quality grows with circle density.' }));
      return;
    }

    state.matches.forEach((m) => {
      const u = m.user;
      const connected = state.connections.indexOf(u.id) !== -1;
      const chips = circleChips(u);

      const head = el('div', { class: 'mc-head' }, [
        el('div', { class: 'avatar', text: initials(u.name), 'aria-hidden': 'true' }),
        el('div', { class: 'mc-id' }, [
          el('div', { class: 'mc-name', text: u.name }),
          el('div', { class: 'mc-sub', text: (u.role === 'driver' ? 'Drives · ' + (u.vehicle || 'car') + ' · ' + u.seats + ' seats' : u.role === 'rider' ? 'Looking for a seat' : 'Drives or rides') })
        ]),
        el('div', { class: 'score score-' + m.tier.key }, [
          el('span', { class: 'score-num', text: String(Math.round(m.score)) }),
          el('span', { class: 'score-cap', text: m.tier.label })
        ])
      ]);

      const chipRow = el('div', { class: 'chip-row' },
        chips.map((c) => el('span', { class: 'chip chip-' + c.kind, text: c.label }))
          .concat(m.womenOnlyPool ? [el('span', { class: 'chip chip-women', text: 'Women-only pool' })] : [])
          .concat(u.verified.community && u.verified.org ? [el('span', { class: 'chip chip-verified', text: 'Verified' })] : []));

      const route = el('div', { class: 'mc-route' }, [
        el('span', { text: D.areas[u.home].name }),
        el('span', { class: 'mc-arrow', 'aria-hidden': 'true', text: '→' }),
        el('span', { text: D.areas[u.dest].name }),
        el('span', { class: 'mc-dot', 'aria-hidden': 'true', text: '·' }),
        el('span', { text: fmtTime(u.window[0]) + '–' + fmtTime(u.window[1]) }),
        el('span', { class: 'mc-dot', 'aria-hidden': 'true', text: '·' }),
        el('span', { text: m.sharedDays.map((d) => DAY_NAMES[d]).join(' ') })
      ]);

      const econLine = el('div', { class: 'mc-econ' , text:
        (p.role === 'driver'
          ? 'You recover ~₹' + fmtNum(m.econ.driverRecovers) + '/trip with 2 riders sharing'
          : 'You pay ~₹' + fmtNum(m.econ.riderPays) + '/trip · save ~₹' + fmtNum(m.econ.riderSavesVsCab) + ' vs a cab') +
        ' · ~' + m.econ.km + ' km' });

      const why = el('details', { class: 'mc-why' }, [
        el('summary', { text: 'Why this match scores ' + Math.round(m.score) }),
        el('ul', {}, m.reasons.map((r) => el('li', {}, [
          el('span', { text: r.label }),
          el('span', { class: 'why-pts', text: '+' + r.pts })
        ])))
      ]);

      const btn = el('button', {
        class: 'btn ' + (connected ? 'btn-quiet' : 'btn-primary'),
        type: 'button',
        text: connected ? 'Connected ✓' : (p.role === 'driver' ? 'Offer a seat' : 'Request a seat')
      });
      btn.addEventListener('click', () => {
        if (state.connections.indexOf(u.id) === -1) {
          state.connections.push(u.id);
          saveLS('cc_connections', state.connections);
          btn.textContent = 'Connected ✓';
          btn.className = 'btn btn-quiet';
          updateCommuteBadge();
          toast(u.name.split(' ')[0] + ' added to your pool (demo auto-accepts)');
        }
        showView('commute');
      });

      wrap.appendChild(el('article', { class: 'card match-card' }, [
        head, chipRow, route, econLine, why,
        el('div', { class: 'mc-actions' }, [btn])
      ]));
    });
  }

  /* ---------- my commute */
  function updateCommuteBadge() {
    const b = $('#nav-commute-badge');
    b.textContent = String(state.connections.length);
    b.hidden = state.connections.length === 0;
  }

  function renderCommute() {
    const wrap = $('#commute-content');
    wrap.textContent = '';
    const p = state.persona;
    const members = state.connections.map((id) => USER[id]).filter(Boolean);

    if (members.length === 0) {
      wrap.appendChild(el('div', { class: 'card empty' }, [
        el('p', { text: 'No pool yet. Connect with a match and your ride group, schedule and cost split will appear here.' }),
        el('button', { class: 'btn btn-primary', type: 'button', text: 'Find matches', onclick: () => showView('matches') })
      ]));
      return;
    }

    const drivers = members.filter((u) => u.role !== 'rider');
    const ridersSharing = Math.min(3, Math.max(1, members.length));
    const econ = M.tripEconomics(D, p.home, p.dest, ridersSharing);
    const tripsPerMonth = Math.round(p.days.length * 4.33) * 2;
    const iAmDriver = p.role === 'driver';
    const monthlyCost = (iAmDriver ? Math.max(0, econ.runCost - econ.driverRecovers) : econ.riderPays) * tripsPerMonth;
    const monthlySave = (iAmDriver ? econ.driverRecovers : econ.riderSavesVsCab) * tripsPerMonth;
    const monthlyCo2 = Math.round(econ.co2PerTrip * tripsPerMonth);

    const tiles = el('div', { class: 'tiles' }, [
      tile('Your cost per month', '₹' + fmtNum(monthlyCost), iAmDriver ? 'fuel after rider shares' : 'seat share + ₹8 platform fee'),
      tile(iAmDriver ? 'You recover per month' : 'You save per month', '₹' + fmtNum(monthlySave), iAmDriver ? 'from ' + ridersSharing + ' riders sharing' : 'vs commuting by cab'),
      tile('CO₂ avoided per month', fmtNum(monthlyCo2) + ' kg', 'one shared car instead of ' + (ridersSharing + 1)),
      tile('Round trips per month', String(tripsPerMonth / 2), p.days.length + ' travel days a week')
    ]);

    const memberList = el('div', { class: 'member-list' },
      [personRow(p, true)].concat(members.map((u) => personRow(u, false))));

    const schedule = el('div', { class: 'sched' }, [el('div', { class: 'sched-row sched-head' },
      [el('span', { class: 'sched-name', text: '' })].concat(DAY_NAMES.slice(0, 5).map((d) => el('span', { class: 'sched-cell', text: d }))))]
    );
    [p].concat(members).forEach((u) => {
      schedule.appendChild(el('div', { class: 'sched-row' },
        [el('span', { class: 'sched-name', text: u.name.split(' ')[0] })].concat(
          [0, 1, 2, 3, 4].map((d) => el('span', {
            class: 'sched-cell' + (u.days.indexOf(d) !== -1 ? ' on' : ''),
            text: u.days.indexOf(d) !== -1 ? '●' : '–',
            'aria-label': DAY_NAMES[d] + (u.days.indexOf(d) !== -1 ? ' travelling' : ' off')
          })))));
    });

    const note = drivers.length === 0 && !iAmDriver
      ? el('p', { class: 'soft-note', text: 'Everyone in this pool is a rider so far — connect with a driver to get rolling.' })
      : el('p', { class: 'soft-note', text: 'Guaranteed ride home: if your pool falls through on a given day, CommuteCircle books you a cab and the platform absorbs the difference (twice a month on the premium plan).' });

    wrap.appendChild(el('div', { class: 'card' }, [
      el('h3', { text: 'Your pool · ' + D.areas[p.home].name + ' → ' + D.areas[p.dest].name + ' · ~' + econ.km + ' km' }),
      memberList,
      el('h4', { text: 'Weekly schedule' }),
      schedule,
      note
    ]));
    wrap.appendChild(tiles);
    wrap.appendChild(el('div', { class: 'card' }, [
      el('h3', { text: 'Cost split per one-way trip' }),
      splitTable(econ, ridersSharing),
      el('p', { class: 'soft-note', text: 'Cost sharing is capped at fuel + tolls so pooling stays non-commercial; the platform charges riders a flat ₹' + D.PLATFORM_FEE + ' convenience fee per matched trip.' })
    ]));
    wrap.appendChild(el('button', { class: 'btn btn-quiet', type: 'button', text: 'Reset demo data', onclick: () => {
      state.connections = [];
      state.persona = Object.assign({}, D.defaultPersona);
      clearLS();
      updateCommuteBadge();
      initFormValuesOnly();
      renderCommute();
      toast('Demo reset');
    } }));
  }

  function initFormValuesOnly() {
    const p = state.persona;
    $('#f-name').value = p.name; $('#f-gender').value = p.gender; $('#f-role').value = p.role;
    fillSelect($('#f-community'), D.communities, p.community);
    fillSelect($('#f-org'), D.orgs, p.org, 'No organisation circle');
    fillSelect($('#f-building'), D.buildings, p.building, 'No building circle');
    timeOptions($('#f-start'), 6, 11, p.window[0]);
    timeOptions($('#f-end'), 6.5, 12, p.window[1]);
    for (let d = 0; d < 7; d++) $('#f-day-' + d).checked = p.days.indexOf(d) !== -1;
    $('#f-women').checked = Boolean(p.womenOnly);
    syncRoleFields();
  }

  function personRow(u, isYou) {
    return el('div', { class: 'member' }, [
      el('div', { class: 'avatar', text: initials(u.name), 'aria-hidden': 'true' }),
      el('div', {}, [
        el('div', { class: 'member-name', text: u.name + (isYou ? ' (you)' : '') }),
        el('div', { class: 'member-sub', text: (u.role === 'rider' ? 'Rider' : 'Driver · ' + (u.vehicle || 'car')) +
          ' · ' + fmtTime(u.window[0]) + '–' + fmtTime(u.window[1]) })
      ])
    ]);
  }

  function splitTable(econ, riders) {
    const t = el('table', { class: 'mini-table' });
    t.appendChild(el('thead', {}, [el('tr', {}, [
      el('th', { text: 'Line' }), el('th', { class: 'num', text: 'Amount' })])]));
    const rows = [
      ['Running cost (' + econ.km + ' km × ₹' + D.COST_PER_KM + '/km)', '₹' + fmtNum(econ.runCost)],
      ['Split ' + (riders + 1) + ' ways (driver + ' + riders + ')', '₹' + fmtNum(econ.seatShare) + ' per person'],
      ['Rider pays incl. ₹' + D.PLATFORM_FEE + ' platform fee', '₹' + fmtNum(econ.riderPays)],
      ['Same trip by cab (approx.)', '₹' + fmtNum(econ.cabFare)],
      ['Rider saves vs cab', '₹' + fmtNum(econ.riderSavesVsCab)]
    ];
    t.appendChild(el('tbody', {}, rows.map((r) => el('tr', {}, [
      el('td', { text: r[0] }), el('td', { class: 'num', text: r[1] })]))));
    return t;
  }

  function tile(label, value, sub) {
    return el('div', { class: 'tile' }, [
      el('div', { class: 'tile-label', text: label }),
      el('div', { class: 'tile-value', text: value }),
      sub ? el('div', { class: 'tile-sub', text: sub }) : null
    ]);
  }

  /* ---------- home stats */
  function renderHomeStats() {
    const econ = M.tripEconomics(D, 'whitefield', 'bellandur', 2);
    const circles = D.communities.length + D.orgs.length + D.buildings.length;
    $('#stat-members').textContent = fmtNum(D.users.length + 1);
    $('#stat-circles').textContent = fmtNum(circles);
    $('#stat-save').textContent = '₹' + fmtNum(Math.round(econ.riderSavesVsCab * 43 / 100) * 100);
    $('#stat-co2').textContent = Math.round(econ.co2PerTrip / 2 * 43 * 12) + ' kg';
  }

  /* ---------- financial dashboard */
  const SERIES = [
    { key: 'rides', name: 'Ride fees', varName: '--s1' },
    { key: 'saas', name: 'B2B SaaS', varName: '--s2' },
    { key: 'subs', name: 'Subscriptions', varName: '--s3' },
    { key: 'other', name: 'Partnerships', varName: '--s4' }
  ];
  const LEVER_DEFS = [
    { key: 'fee', label: 'Ride fee', eff: (m) => '₹' + m.drivers.feePerRide[4] + '/ride in Y5' },
    { key: 'pepm', label: 'B2B price', eff: (m) => '₹' + m.drivers.pepm[4] + '/employee/mo in Y5' },
    { key: 'rides', label: 'Matched rides', eff: (m) => m.drivers.ridesPerMac[4] + '/commuter/mo in Y5' },
    { key: 'premium', label: 'Premium adoption', eff: (m, L) => (7 * L.premium).toFixed(1) + '% of actives in Y5' },
    { key: 'snm', label: 'Marketing spend', eff: (m) => fmtCr(m.opex.snm[4]) + ' in Y5' },
    { key: 'people', label: 'Team cost', eff: (m) => fmtCr(m.opex.people[4]) + ' in Y5' }
  ];

  function initFinancials() {
    const leverWrap = $('#fin-levers');
    LEVER_DEFS.forEach((def) => {
      const input = el('input', {
        type: 'range', min: '60', max: '140', step: '5', value: '100',
        id: 'lev-' + def.key, 'aria-label': def.label + ' multiplier'
      });
      input.addEventListener('input', () => {
        state.levers[def.key] = parseInt(input.value, 10) / 100;
        renderFinancials();
      });
      leverWrap.appendChild(el('div', { class: 'lever' }, [
        el('label', { class: 'lever-label', for: 'lev-' + def.key, text: def.label }),
        input,
        el('div', { class: 'lever-read', id: 'lev-read-' + def.key, text: '' })
      ]));
    });
    $('#btn-reset-levers').addEventListener('click', () => {
      state.levers = Object.assign({}, F.DEFAULT_LEVERS);
      LEVER_DEFS.forEach((d) => { $('#lev-' + d.key).value = '100'; });
      renderFinancials();
    });
    $('#btn-copy-csv').addEventListener('click', () => {
      const csv = F.toCsv(F.computePnl(state.levers));
      const done = () => toast('P&L copied as CSV — paste into any spreadsheet');
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(csv).then(done).catch(() => fallbackCopy(csv, done));
      } else fallbackCopy(csv, done);
    });
    renderFinancials();
  }

  function fallbackCopy(text, done) {
    const ta = el('textarea', { class: 'sr-copy' });
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); done(); }
    catch (e) { toast('Copy blocked — select the table and copy manually'); }
    document.body.removeChild(ta);
  }

  function renderFinancials() {
    const m = F.computePnl(state.levers);

    LEVER_DEFS.forEach((def) => {
      const mult = state.levers[def.key];
      $('#lev-read-' + def.key).textContent = '×' + mult.toFixed(2) + ' · ' + def.eff(m, state.levers);
    });

    const tilesWrap = $('#fin-tiles');
    tilesWrap.textContent = '';
    tilesWrap.appendChild(tile('Year 5 revenue', fmtCr(m.revenue.total[4]), '₹' + (m.revenue.total[4] * 10).toFixed(0) + ' lakh/month run-rate by exit'));
    tilesWrap.appendChild(tile('Year 5 EBITDA', fmtCr(m.ebitda[4]), (m.ebitdaMargin[4] * 100).toFixed(1) + '% margin'));
    tilesWrap.appendChild(tile('Peak cumulative burn', fmtCr(m.peakFundingNeed), 'total EBITDA losses before turning'));
    tilesWrap.appendChild(tile('EBITDA break-even', m.breakevenYear ? 'Year ' + m.breakevenYear : 'Beyond Y5', m.breakevenYear ? 'first full positive year' : 'needs stronger levers'));

    renderRevenueChart(m);
    renderEbitdaChart(m);
    renderPnlTable(m);
    renderAssumptions(m);
  }

  /* ----- shared chart tooltip */
  function ttShow(evt, title, rows) {
    const tt = $('#cc-tooltip');
    tt.textContent = '';
    tt.appendChild(el('div', { class: 'tt-title', text: title }));
    rows.forEach((r) => {
      const key = el('span', { class: 'tt-key' });
      if (r.color) key.style.background = r.color; else key.classList.add('tt-key-none');
      tt.appendChild(el('div', { class: 'tt-row' }, [
        key,
        el('span', { class: 'tt-label', text: r.label }),
        el('span', { class: 'tt-value', text: r.value })
      ]));
    });
    tt.hidden = false;
    const pad = 14;
    const rect = tt.getBoundingClientRect();
    let x = evt.clientX + pad, y = evt.clientY + pad;
    if (x + rect.width > window.innerWidth - 8) x = evt.clientX - rect.width - pad;
    if (y + rect.height > window.innerHeight - 8) y = evt.clientY - rect.height - pad;
    tt.style.left = Math.max(8, x) + 'px';
    tt.style.top = Math.max(8, y) + 'px';
  }
  function ttShowAt(node, title, rows) {
    const r = node.getBoundingClientRect();
    ttShow({ clientX: r.left + r.width / 2, clientY: r.top }, title, rows);
  }
  function ttHide() { $('#cc-tooltip').hidden = true; }

  function seriesColor(varName) {
    return getComputedStyle(document.documentElement).getPropertyValue(varName).trim() || '#888';
  }

  function roundedTopRect(x, y, w, h, r) {
    r = Math.min(r, w / 2, h);
    return 'M' + x + ',' + (y + h) + ' L' + x + ',' + (y + r) +
      ' Q' + x + ',' + y + ' ' + (x + r) + ',' + y +
      ' L' + (x + w - r) + ',' + y +
      ' Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + r) +
      ' L' + (x + w) + ',' + (y + h) + ' Z';
  }
  function roundedBottomRect(x, y, w, h, r) {
    r = Math.min(r, w / 2, h);
    return 'M' + x + ',' + y + ' L' + (x + w) + ',' + y +
      ' L' + (x + w) + ',' + (y + h - r) +
      ' Q' + (x + w) + ',' + (y + h) + ' ' + (x + w - r) + ',' + (y + h) +
      ' L' + (x + r) + ',' + (y + h) +
      ' Q' + x + ',' + (y + h) + ' ' + x + ',' + (y + h - r) + ' Z';
  }

  function niceCeil(v) {
    if (v <= 0) return 1;
    const mag = Math.pow(10, Math.floor(Math.log10(v)));
    for (const k of [1, 2, 2.5, 4, 5, 8, 10]) if (v <= k * mag) return k * mag;
    return 10 * mag;
  }

  function chartFrame(width, height, mLeft, mTop, mRight, mBottom) {
    const svg = svgEl('svg', { viewBox: '0 0 ' + width + ' ' + height, class: 'viz', role: 'img' });
    return {
      svg,
      x0: mLeft, y0: mTop,
      plotW: width - mLeft - mRight,
      plotH: height - mTop - mBottom
    };
  }

  function renderRevenueChart(m) {
    const host = $('#chart-revenue');
    host.textContent = '';
    const W = 640, H = 300;
    const f = chartFrame(W, H, 46, 26, 10, 26);
    const yMax = niceCeil(Math.max.apply(null, m.revenue.total));
    const ticks = 4;
    const y = (v) => f.y0 + f.plotH - (v / yMax) * f.plotH;

    for (let i = 0; i <= ticks; i++) {
      const val = (yMax / ticks) * i;
      f.svg.appendChild(svgEl('line', { x1: f.x0, x2: f.x0 + f.plotW, y1: y(val), y2: y(val), class: i === 0 ? 'viz-axisline' : 'viz-grid' }));
      f.svg.appendChild(svgEl('text', { x: f.x0 - 8, y: y(val) + 4, class: 'viz-tick', 'text-anchor': 'end', text: String(val) }));
    }

    const colors = SERIES.map((s) => seriesColor(s.varName));
    const bandW = f.plotW / 5;
    const barW = Math.min(24, bandW * 0.5);
    const GAP = 2;

    for (let i = 0; i < 5; i++) {
      const cx = f.x0 + bandW * i + bandW / 2;
      const bx = cx - barW / 2;
      const colG = svgEl('g', { class: 'viz-col' });
      let acc = 0;
      const vals = SERIES.map((s) => m.revenue[s.key][i]);
      const drawn = [];
      vals.forEach((v, si) => {
        const hTop = y(acc + v), hBot = y(acc);
        const hPx = hBot - hTop;
        if (hPx > 2.5) drawn.push({ si, top: hTop, bot: hBot });
        acc += v;
      });
      drawn.forEach((seg, di) => {
        const isTop = di === drawn.length - 1;
        const gapTop = isTop ? 0 : GAP;
        const h = Math.max(1, seg.bot - seg.top - gapTop);
        const ytop = seg.top + gapTop;
        if (isTop) {
          colG.appendChild(svgEl('path', { d: roundedTopRect(bx, ytop, barW, h, 4), fill: colors[seg.si] }));
        } else {
          colG.appendChild(svgEl('rect', { x: bx, y: ytop, width: barW, height: h, fill: colors[seg.si] }));
        }
      });
      colG.appendChild(svgEl('text', { x: cx, y: y(m.revenue.total[i]) - 7, class: 'viz-caplabel', 'text-anchor': 'middle', text: m.revenue.total[i].toFixed(1) }));
      colG.appendChild(svgEl('text', { x: cx, y: f.y0 + f.plotH + 18, class: 'viz-tick', 'text-anchor': 'middle', text: 'Y' + (i + 1) }));

      const hit = svgEl('rect', { x: f.x0 + bandW * i, y: f.y0, width: bandW, height: f.plotH, fill: 'transparent', tabindex: '0', class: 'viz-hit' });
      const title = m.years[i] + ' revenue';
      const rows = SERIES.map((s, si) => ({ color: colors[si], label: s.name, value: fmtCr(m.revenue[s.key][i], 2) }))
        .concat([{ label: 'Total', value: fmtCr(m.revenue.total[i], 2) }]);
      hit.addEventListener('pointermove', (ev) => { colG.classList.add('lift'); ttShow(ev, title, rows); });
      hit.addEventListener('pointerleave', () => { colG.classList.remove('lift'); ttHide(); });
      hit.addEventListener('focus', () => { colG.classList.add('lift'); ttShowAt(hit, title, rows); });
      hit.addEventListener('blur', () => { colG.classList.remove('lift'); ttHide(); });
      f.svg.appendChild(colG);
      f.svg.appendChild(hit);
    }
    f.svg.setAttribute('aria-label', 'Stacked bars: total revenue growing from ' + fmtCr(m.revenue.total[0]) + ' in year 1 to ' + fmtCr(m.revenue.total[4]) + ' in year 5, split by stream.');
    host.appendChild(f.svg);

    const legend = $('#chart-revenue-legend');
    legend.textContent = '';
    SERIES.forEach((s, si) => {
      const sw = el('span', { class: 'legend-swatch' });
      sw.style.background = colors[si];
      legend.appendChild(el('span', { class: 'legend-item' }, [sw, el('span', { text: s.name })]));
    });
  }

  function renderEbitdaChart(m) {
    const host = $('#chart-ebitda');
    host.textContent = '';
    const W = 640, H = 300;
    const f = chartFrame(W, H, 46, 22, 10, 26);
    const maxAbs = niceCeil(Math.max.apply(null, m.ebitda.map(Math.abs)));
    const yMax = maxAbs, yMin = -maxAbs;
    const y = (v) => f.y0 + (yMax - v) / (yMax - yMin) * f.plotH;
    const posColor = seriesColor('--viz-pos'), negColor = seriesColor('--viz-neg');

    for (let i = -2; i <= 2; i++) {
      const val = (maxAbs / 2) * i;
      f.svg.appendChild(svgEl('line', { x1: f.x0, x2: f.x0 + f.plotW, y1: y(val), y2: y(val), class: val === 0 ? 'viz-axisline' : 'viz-grid' }));
      f.svg.appendChild(svgEl('text', { x: f.x0 - 8, y: y(val) + 4, class: 'viz-tick', 'text-anchor': 'end', text: (val > 0 ? '+' : '') + val }));
    }

    const bandW = f.plotW / 5;
    const barW = Math.min(24, bandW * 0.5);
    const minIdx = m.ebitda.indexOf(Math.min.apply(null, m.ebitda));

    for (let i = 0; i < 5; i++) {
      const v = m.ebitda[i];
      const cx = f.x0 + bandW * i + bandW / 2;
      const bx = cx - barW / 2;
      const g = svgEl('g', { class: 'viz-col' });
      const zero = y(0);
      const vy = y(v);
      const h = Math.max(1.5, Math.abs(vy - zero));
      if (v >= 0) g.appendChild(svgEl('path', { d: roundedTopRect(bx, zero - h, barW, h, 4), fill: posColor }));
      else g.appendChild(svgEl('path', { d: roundedBottomRect(bx, zero, barW, h, 4), fill: negColor }));

      if (i === minIdx || i === 4) {
        const labelY = v >= 0 ? vy - 7 : vy + 15;
        g.appendChild(svgEl('text', { x: cx, y: labelY, class: 'viz-caplabel', 'text-anchor': 'middle', text: (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(1) }));
      }
      g.appendChild(svgEl('text', { x: cx, y: f.y0 + f.plotH + 18, class: 'viz-tick', 'text-anchor': 'middle', text: 'Y' + (i + 1) }));

      const hit = svgEl('rect', { x: f.x0 + bandW * i, y: f.y0, width: bandW, height: f.plotH, fill: 'transparent', tabindex: '0', class: 'viz-hit' });
      const title = m.years[i] + ' EBITDA';
      const rows = [
        { color: v >= 0 ? posColor : negColor, label: 'EBITDA', value: fmtCr(v, 2) },
        { label: 'Margin', value: (m.ebitdaMargin[i] * 100).toFixed(1) + '%' },
        { label: 'Cumulative', value: fmtCr(m.cumEbitda[i], 2) }
      ];
      hit.addEventListener('pointermove', (ev) => { g.classList.add('lift'); ttShow(ev, title, rows); });
      hit.addEventListener('pointerleave', () => { g.classList.remove('lift'); ttHide(); });
      hit.addEventListener('focus', () => { g.classList.add('lift'); ttShowAt(hit, title, rows); });
      hit.addEventListener('blur', () => { g.classList.remove('lift'); ttHide(); });
      f.svg.appendChild(g);
      f.svg.appendChild(hit);
    }
    f.svg.setAttribute('aria-label', 'Bars around a zero line: EBITDA losses peak at ' + fmtCr(Math.min.apply(null, m.ebitda)) + ' and turn positive at ' + fmtCr(m.ebitda[4]) + ' in year 5.');
    host.appendChild(f.svg);
  }

  function renderPnlTable(m) {
    const wrap = $('#pnl-table-wrap');
    wrap.textContent = '';
    const t = el('table', { class: 'pnl' });
    t.appendChild(el('thead', {}, [el('tr', {},
      [el('th', { text: '₹ crore' })].concat(m.years.map((yr) => el('th', { class: 'num', text: yr }))))]));
    const tb = el('tbody');
    let lastGroup = null;
    F.pnlRows(m).forEach((row) => {
      if (row.group && row.group !== lastGroup) {
        lastGroup = row.group;
        tb.appendChild(el('tr', { class: 'group-row' }, [el('td', { colspan: '6', text: row.group })]));
      }
      if (!row.group) lastGroup = null;
      const tr = el('tr', { class: row.strong ? 'strong-row' : '' });
      tr.appendChild(el('td', { text: row.label }));
      row.values.forEach((v) => {
        if (row.isText) tr.appendChild(el('td', { class: 'num', text: String(v) }));
        else {
          const neg = v < 0;
          tr.appendChild(el('td', { class: 'num' + (neg ? ' neg' : ''), text: neg ? '(' + Math.abs(v).toFixed(2) + ')' : Number(v).toFixed(2) }));
        }
      });
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    wrap.appendChild(t);
  }

  function renderAssumptions(m) {
    const wrap = $('#fin-assumptions');
    wrap.textContent = '';
    const t = el('table', { class: 'mini-table' });
    t.appendChild(el('thead', {}, [el('tr', {},
      [el('th', { text: 'Driver' })].concat(m.years.map((yr) => el('th', { class: 'num', text: yr.replace('Year ', 'Y') }))))]));
    const rows = [
      ['Monthly active commuters (avg)', F.BASE.mac.map(fmtNum)],
      ['Matched rides / commuter / month', m.drivers.ridesPerMac],
      ['Platform fee per ride (₹)', m.drivers.feePerRide],
      ['B2B covered employees (avg)', F.BASE.covered.map(fmtNum)],
      ['B2B price (₹ / employee / month)', m.drivers.pepm],
      ['Team size (approx.)', [18, 35, 65, 100, 135]]
    ];
    t.appendChild(el('tbody', {}, rows.map((r) => el('tr', {}, [el('td', { text: r[0] })]
      .concat(r[1].map((v) => el('td', { class: 'num', text: String(v) })))))));
    wrap.appendChild(t);
  }

  /* ---------- boot */
  function boot() {
    $$('a[data-view]').forEach((a) => a.addEventListener('click', (ev) => {
      ev.preventDefault();
      showView(a.getAttribute('data-view'));
    }));
    $$('[data-goto]').forEach((b) => b.addEventListener('click', () => showView(b.getAttribute('data-goto'))));
    window.addEventListener('hashchange', () => showView((location.hash || '#home').slice(1), true));
    window.addEventListener('scroll', ttHide, { passive: true });

    initProfileForm();
    initFinancials();
    renderHomeStats();
    updateCommuteBadge();
    renderMatches();
    showView((location.hash || '#home').slice(1), true);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
