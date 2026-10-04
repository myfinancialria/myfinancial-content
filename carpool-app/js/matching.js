/* CommuteCircle — matching engine.
 * Pure functions: no DOM, no globals beyond CC_MATCH. The score is built from
 * shared trust circles (residential community, employer, commercial building),
 * schedule overlap and destination proximity, so it maxes at 100:
 *   community 30 + org 20 + building 15 + time 15 + destination 15 + verified 5
 */

const CC_MATCH = (function () {
  const WEIGHTS = {
    community: 30,
    org: 20,
    building: 15,
    time: 15,
    dest: 15,
    verified: 5
  };
  const MIN_OVERLAP_MIN = 15;   // minimum departure-window overlap
  const MAX_DEST_KM = 10;       // destinations further apart than this don't match
  const MATCH_THRESHOLD = 35;   // minimum score to surface a match

  function planarKm(areas, a, b) {
    const p = areas[a], q = areas[b];
    if (!p || !q) return Infinity;
    return Math.hypot(p.x - q.x, p.y - q.y);
  }

  function roadKm(data, a, b) {
    return planarKm(data.areas, a, b) * data.ROAD_FACTOR;
  }

  // Overlap of two [start, end] hour windows, in minutes.
  function overlapMinutes(w1, w2) {
    return Math.max(0, (Math.min(w1[1], w2[1]) - Math.max(w1[0], w2[0])) * 60);
  }

  function sharedDays(d1, d2) {
    const set = new Set(d2);
    return d1.filter((d) => set.has(d));
  }

  function rolesCompatible(a, b) {
    if (a === 'both' || b === 'both') return true;
    return a !== b; // driver <-> rider
  }

  function womenOnlyCompatible(a, b) {
    if (!a.womenOnly && !b.womenOnly) return true;
    return a.gender === 'F' && b.gender === 'F';
  }

  function tierFor(score) {
    if (score >= 80) return { key: 'excellent', label: 'Excellent match' };
    if (score >= 60) return { key: 'strong', label: 'Strong match' };
    if (score >= 45) return { key: 'good', label: 'Good match' };
    return { key: 'fair', label: 'Fair match' };
  }

  /* Trip economics for one shared car on the rider's route.
   * Assumes average occupancy of one driver + `ridersSharing` riders. */
  function tripEconomics(data, homeArea, destArea, ridersSharing) {
    const km = Math.max(2, roadKm(data, homeArea, destArea));
    const runCost = km * data.COST_PER_KM;
    const occupants = 1 + Math.max(1, ridersSharing);
    const seatShare = runCost / occupants;
    const riderPays = seatShare + data.PLATFORM_FEE;
    const cabFare = km * data.CAB_PER_KM + 60; // base fare + per-km
    return {
      km: Math.round(km * 10) / 10,
      runCost: Math.round(runCost),
      seatShare: Math.round(seatShare),
      riderPays: Math.round(riderPays),
      cabFare: Math.round(cabFare),
      riderSavesVsCab: Math.round(cabFare - riderPays),
      driverRecovers: Math.round(seatShare * Math.max(1, ridersSharing)),
      co2PerTrip: Math.round(km * data.CO2_PER_KM * Math.max(1, ridersSharing) * 100) / 100
    };
  }

  /* Find and score matches for `person` among `candidates`. */
  function findMatches(person, candidates, data) {
    const results = [];
    for (const cand of candidates) {
      if (cand.id === person.id) continue;
      if (!rolesCompatible(person.role, cand.role)) continue;
      if (!womenOnlyCompatible(person, cand)) continue;

      const days = sharedDays(person.days, cand.days);
      if (days.length === 0) continue;

      const overlap = overlapMinutes(person.window, cand.window);
      if (overlap < MIN_OVERLAP_MIN) continue;

      // Origin: same residential community, or at least the same home area.
      const sameCommunity = person.community && person.community === cand.community;
      if (!sameCommunity && person.home !== cand.home) continue;

      const destKm = roadKm(data, person.dest, cand.dest);
      if (destKm > MAX_DEST_KM) continue;

      const sameOrg = person.org && person.org === cand.org;
      const sameBuilding = person.building && person.building === cand.building;

      const personSpan = Math.max(1, (person.window[1] - person.window[0]) * 60);
      const timePts = Math.min(1, overlap / personSpan) * WEIGHTS.time;
      const destPts = Math.max(0, 1 - destKm / MAX_DEST_KM) * WEIGHTS.dest;
      const verifiedPts = cand.verified && cand.verified.community && cand.verified.org
        ? WEIGHTS.verified : 0;

      const reasons = [];
      let score = 0;
      if (sameCommunity) { score += WEIGHTS.community; reasons.push({ label: 'Same residential community', pts: WEIGHTS.community }); }
      if (sameOrg) { score += WEIGHTS.org; reasons.push({ label: 'Same organisation', pts: WEIGHTS.org }); }
      if (sameBuilding) { score += WEIGHTS.building; reasons.push({ label: 'Same commercial building', pts: WEIGHTS.building }); }
      score += timePts; reasons.push({ label: 'Departure windows overlap ' + Math.round(overlap) + ' min', pts: Math.round(timePts * 10) / 10 });
      score += destPts; reasons.push({ label: destKm < 0.5 ? 'Same destination area' : 'Destinations ' + (Math.round(destKm * 10) / 10) + ' km apart', pts: Math.round(destPts * 10) / 10 });
      if (verifiedPts) { score += verifiedPts; reasons.push({ label: 'Fully verified member', pts: verifiedPts }); }

      score = Math.round(Math.min(100, score) * 10) / 10;
      if (score < MATCH_THRESHOLD) continue;

      results.push({
        user: cand,
        score,
        tier: tierFor(score),
        reasons,
        overlapMin: Math.round(overlap),
        sharedDays: days,
        destKm: Math.round(destKm * 10) / 10,
        womenOnlyPool: Boolean(person.womenOnly || cand.womenOnly),
        econ: tripEconomics(data, person.home, person.dest, 2)
      });
    }
    results.sort((a, b) => b.score - a.score);
    return results;
  }

  return { findMatches, tripEconomics, overlapMinutes, roadKm, WEIGHTS, MATCH_THRESHOLD };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = CC_MATCH;
