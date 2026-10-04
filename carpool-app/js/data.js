/* CommuteCircle — seed data for the prototype.
 * All people, companies, residential communities and buildings below are
 * fictional sample data. Areas are real Bengaluru localities used only as
 * geography for the demo; coordinates are approximate km offsets on a flat
 * grid, good enough for demo-level distance math. */

const CC_DATA = (function () {
  // Approximate planar coordinates (km). Distance = euclidean * ROAD_FACTOR.
  const areas = {
    whitefield:   { name: 'Whitefield',            x: 16,   y: 6 },
    brookefield:  { name: 'Brookefield',           x: 13.5, y: 5.5 },
    marathahalli: { name: 'Marathahalli',          x: 11,   y: 4 },
    bellandur:    { name: 'Bellandur / ORR',       x: 9,    y: 0 },
    sarjapur:     { name: 'Sarjapur Road',         x: 10,   y: -4 },
    hsr:          { name: 'HSR Layout',            x: 6,    y: -3 },
    koramangala:  { name: 'Koramangala',           x: 4,    y: -1 },
    indiranagar:  { name: 'Indiranagar',           x: 5,    y: 3 },
    cbd:          { name: 'MG Road / CBD',         x: 2,    y: 2 },
    ecity:        { name: 'Electronic City',       x: 2,    y: -12 },
    hebbal:       { name: 'Hebbal',                x: 0,    y: 10 }
  };

  const ROAD_FACTOR = 1.3;     // planar km -> road km
  const COST_PER_KM = 7;       // ₹/km: fuel (~₹105/L at ~15 km/L) incl. light wear share
  const CAB_PER_KM = 18;       // ₹/km typical cab fare for comparison
  const PLATFORM_FEE = 8;      // ₹ per matched seat-trip (platform convenience fee)
  const CO2_PER_KM = 0.14;     // kg CO2 avoided per pooled rider-km

  // Trust circles — all fictional.
  const communities = [
    { id: 'c1', name: 'Lakeside Habitat',     area: 'whitefield' },
    { id: 'c2', name: 'Cosmopolis Heights',   area: 'whitefield' },
    { id: 'c3', name: 'Riviera Gardens',      area: 'marathahalli' },
    { id: 'c4', name: 'Palm Retreat Enclave', area: 'bellandur' },
    { id: 'c5', name: 'Silicon Oasis',        area: 'ecity' }
  ];

  const orgs = [
    { id: 'o1', name: 'Zentara Systems' },
    { id: 'o2', name: 'Kalpataru Software' },
    { id: 'o3', name: 'QuickBasket' },
    { id: 'o4', name: 'Meridian Consulting' },
    { id: 'o5', name: 'BrightHive Analytics' },
    { id: 'o6', name: 'Nexval Technologies' }
  ];

  const buildings = [
    { id: 'b1', name: 'Emerald Tech Park',    area: 'bellandur' },
    { id: 'b2', name: 'Bayview Tech Village', area: 'bellandur' },
    { id: 'b3', name: 'Northgate Tech Park',  area: 'hebbal' },
    { id: 'b4', name: 'Centralia Tech Park',  area: 'marathahalli' },
    { id: 'b5', name: 'Innovation Park',      area: 'whitefield' }
  ];

  // Days: 0=Mon … 6=Sun. Windows are decimal hours [start, end].
  const users = [
    { id: 'u1',  name: 'Rahul Menon',    gender: 'M', role: 'driver', community: 'c1', org: 'o1', building: 'b1',
      home: 'whitefield', dest: 'bellandur', window: [8.0, 9.0],  days: [0,1,2,3,4], seats: 3,
      vehicle: 'Hyundai Creta', womenOnly: false, verified: { community: true, org: true } },
    { id: 'u2',  name: 'Divya Krishnan', gender: 'F', role: 'driver', community: 'c1', org: 'o3', building: 'b2',
      home: 'whitefield', dest: 'bellandur', window: [8.5, 9.5],  days: [0,1,2,3], seats: 2,
      vehicle: 'Maruti Baleno', womenOnly: false, verified: { community: true, org: true } },
    { id: 'u3',  name: 'Arjun Nair',     gender: 'M', role: 'driver', community: 'c2', org: 'o3', building: 'b2',
      home: 'whitefield', dest: 'bellandur', window: [7.75, 8.75], days: [0,1,2,3,4], seats: 3,
      vehicle: 'Tata Nexon EV', womenOnly: false, verified: { community: true, org: true } },
    { id: 'u4',  name: 'Meera Pillai',   gender: 'F', role: 'rider',  community: 'c1', org: 'o5', building: 'b1',
      home: 'whitefield', dest: 'bellandur', window: [8.0, 9.0],  days: [4], seats: 0,
      vehicle: null, womenOnly: false, verified: { community: true, org: true } },
    { id: 'u5',  name: 'Sandeep Rao',    gender: 'M', role: 'driver', community: 'c3', org: 'o2', building: null,
      home: 'marathahalli', dest: 'ecity', window: [8.0, 9.0],  days: [0,1,2,3,4], seats: 3,
      vehicle: 'Honda City', womenOnly: false, verified: { community: true, org: true } },
    { id: 'u6',  name: 'Kavitha Reddy',  gender: 'F', role: 'driver', community: 'c4', org: 'o4', building: null,
      home: 'bellandur', dest: 'cbd', window: [8.5, 9.5],  days: [0,1,2,3,4], seats: 2,
      vehicle: 'Kia Sonet', womenOnly: false, verified: { community: true, org: true } },
    { id: 'u7',  name: 'Vikram Shetty',  gender: 'M', role: 'driver', community: 'c2', org: 'o6', building: 'b2',
      home: 'whitefield', dest: 'bellandur', window: [9.0, 10.0], days: [0,1,2,3,4], seats: 2,
      vehicle: 'Skoda Slavia', womenOnly: false, verified: { community: true, org: true } },
    { id: 'u8',  name: 'Anjali Varma',   gender: 'F', role: 'driver', community: 'c1', org: 'o5', building: null,
      home: 'whitefield', dest: 'cbd', window: [8.0, 9.0],  days: [0,1,2,3,4], seats: 2,
      vehicle: 'Maruti Brezza', womenOnly: false, verified: { community: true, org: true } },
    { id: 'u9',  name: 'Shruti Iyer',    gender: 'F', role: 'driver', community: 'c2', org: 'o3', building: 'b2',
      home: 'whitefield', dest: 'bellandur', window: [8.25, 9.0], days: [0,1,2,3,4], seats: 2,
      vehicle: 'Hyundai i20', womenOnly: true, verified: { community: true, org: true } },
    { id: 'u10', name: 'Rakesh Kumar',   gender: 'M', role: 'rider',  community: 'c1', org: 'o1', building: 'b1',
      home: 'whitefield', dest: 'bellandur', window: [8.5, 9.5],  days: [0,1,2,3,4], seats: 0,
      vehicle: null, womenOnly: false, verified: { community: true, org: true } },
    { id: 'u11', name: 'Nisha Thomas',   gender: 'F', role: 'rider',  community: 'c2', org: 'o3', building: 'b2',
      home: 'whitefield', dest: 'bellandur', window: [8.0, 8.75], days: [0,1,2,3,4], seats: 0,
      vehicle: null, womenOnly: true, verified: { community: true, org: true } },
    { id: 'u12', name: 'Farhan Ali',     gender: 'M', role: 'driver', community: 'c5', org: 'o1', building: null,
      home: 'ecity', dest: 'ecity', window: [8.5, 9.5],  days: [0,1,2,3,4], seats: 3,
      vehicle: 'Toyota Glanza', womenOnly: false, verified: { community: true, org: true } },
    { id: 'u13', name: 'Deepak Joshi',   gender: 'M', role: 'driver', community: 'c3', org: 'o4', building: 'b1',
      home: 'marathahalli', dest: 'bellandur', window: [8.25, 9.25], days: [0,1,2,3,4], seats: 3,
      vehicle: 'Mahindra XUV300', womenOnly: false, verified: { community: true, org: true } },
    { id: 'u14', name: 'Lakshmi Narayanan', gender: 'F', role: 'rider', community: 'c4', org: 'o2', building: 'b3',
      home: 'bellandur', dest: 'hebbal', window: [8.0, 9.0], days: [0,1,2,3,4], seats: 0,
      vehicle: null, womenOnly: false, verified: { community: true, org: true } }
  ];

  // Default demo persona shown in the profile form.
  const defaultPersona = {
    id: 'me',
    name: 'Priya Nair',
    gender: 'F',
    role: 'rider',
    community: 'c1',
    org: 'o3',
    building: 'b2',
    home: 'whitefield',
    dest: 'bellandur',
    window: [8.25, 9.25],
    days: [0, 1, 2, 3, 4],
    seats: 0,
    vehicle: null,
    womenOnly: false,
    verified: { community: true, org: false }
  };

  return {
    areas, communities, orgs, buildings, users, defaultPersona,
    ROAD_FACTOR, COST_PER_KM, CAB_PER_KM, PLATFORM_FEE, CO2_PER_KM
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = CC_DATA;
