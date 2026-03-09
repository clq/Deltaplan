const DELTAPLAN_BASE = 'https://deltaplan.dk/deltaplan_v2/classic';
const API_URL = `${DELTAPLAN_BASE}/API`;

function corsHeaders(origin) {
  return {
    'Access-Control-Allow-Origin': origin || '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
  };
}

function jsonResp(data, status, origin) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) },
  });
}

function extractCookies(response) {
  const cookies = {};
  const headers = typeof response.headers.getSetCookie === 'function'
    ? response.headers.getSetCookie()
    : (response.headers.getAll ? response.headers.getAll('set-cookie') : []);
  for (const sc of headers) {
    const nv = sc.split(';')[0];
    const eq = nv.indexOf('=');
    if (eq > 0) cookies[nv.substring(0, eq).trim()] = nv.substring(eq + 1).trim();
  }
  return cookies;
}

function cookieStr(cookies) {
  return Object.entries(cookies).map(([k, v]) => `${k}=${v}`).join('; ');
}

function stripHtml(obj) {
  if (typeof obj === 'string') return obj.replace(/<[^>]*>/g, '').trim();
  if (Array.isArray(obj)) return obj.map(stripHtml);
  if (obj && typeof obj === 'object') {
    const r = {};
    for (const [k, v] of Object.entries(obj)) r[k] = stripHtml(v);
    return r;
  }
  return obj;
}

async function fetchJson(url, headers) {
  const r = await fetch(url, { headers });
  const cookies = extractCookies(r);
  const text = await r.text();
  try {
    return { json: JSON.parse(text), cookies };
  } catch {
    throw new Error(`Non-JSON response from ${url.split('?')[0]}: ${text.substring(0, 150)}`);
  }
}

export default {
  async fetch(request) {
    const origin = request.headers.get('Origin') || '*';

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    const url = new URL(request.url);

    // Health check
    if (url.pathname === '/' || url.pathname === '/health') {
      return jsonResp({ status: 'ok', message: 'Deltaplan proxy worker is running' }, 200, origin);
    }

    if (url.pathname !== '/schedule' || request.method !== 'POST') {
      return jsonResp({ error: 'POST /schedule required' }, 404, origin);
    }

    try {
      const { username, password, date_from, date_to } = await request.json();
      if (!username || !password || !date_from || !date_to) {
        return jsonResp({ error: 'Missing required fields' }, 400, origin);
      }

      let cookies = {};

      // 1. Login
      const loginResp = await fetch(`${API_URL}/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'Referer': `${DELTAPLAN_BASE}/`,
        },
        body: `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
        redirect: 'manual',
      });
      Object.assign(cookies, extractCookies(loginResp));

      const loc = loginResp.headers.get('location') || '';
      if (loc.includes('err=')) {
        return jsonResp({ error: 'Login failed — invalid credentials' }, 401, origin);
      }

      // 2. Get user info
      const userResult = await fetchJson(`${API_URL}/login`, {
        Cookie: cookieStr(cookies),
        'Referer': `${DELTAPLAN_BASE}/`,
      });
      Object.assign(cookies, userResult.cookies);
      const userData = userResult.json;
      const userId = userData.medarbejder_id;
      const companyId = userData.virksomhed_id;
      if (!userId || !companyId) {
        return jsonResp({ error: 'Could not extract user info after login' }, 500, origin);
      }

      const apiH = {
        Cookie: cookieStr(cookies),
        'User-Id': String(userId),
        'User-Company-Id': String(companyId),
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Referer': `${DELTAPLAN_BASE}/`,
      };

      // 3. Fetch shift types + schedule in parallel
      const [typesResult, schedResult] = await Promise.all([
        fetchJson(`${API_URL}/shifttypes`, apiH),
        fetchJson(
          `${API_URL}/employees-schedule/schedule?method=GET&period[]=${date_from}&period[]=${date_to}`,
          apiH,
        ),
      ]);

      const typesRaw = typesResult.json;
      const schedRaw = schedResult.json;
      if (!schedRaw.success) {
        return jsonResp({ error: 'Schedule fetch failed' }, 500, origin);
      }

      // Build vagttype_id → abbreviation map
      const idToAbbr = {};
      const tObj = typesRaw.data || typesRaw;
      if (Array.isArray(tObj)) {
        for (const t of tObj) {
          if (t.vagttype_forkortelse) idToAbbr[String(t.vagttype_id)] = t.vagttype_forkortelse;
        }
      } else if (typeof tObj === 'object') {
        for (const [, t] of Object.entries(tObj)) {
          if (t.vagttype_forkortelse) idToAbbr[String(t.vagttype_id)] = t.vagttype_forkortelse;
        }
      }

      const schedule = schedRaw.data || schedRaw;

      // Own shifts: strip HTML, filter anti-shifts
      let ownShifts = stripHtml(schedule.own_shifts || []);
      ownShifts = ownShifts.filter(s => String(s.department_id) !== '1');

      // Vacant shifts: strip HTML
      const vacantShifts = stripHtml(schedule.vacant_shifts || {});

      // 4. Enrich colleague shifts
      const empIds = new Set();
      const empNames = {};
      for (const shifts of Object.values(schedule.colleagues_shifts || {})) {
        for (const s of (Array.isArray(shifts) ? shifts : [])) {
          if (s.employee_id) {
            empIds.add(s.employee_id);
            empNames[s.employee_id] = s.employee_name || '?';
          }
        }
      }

      const empArr = [...empIds].slice(0, 44); // stay under 50 subrequest limit
      const enriched = {}; // date → [shift, …]
      const seenTypes = new Set();

      // Batch colleague fetches in groups of 6
      for (let i = 0; i < empArr.length; i += 6) {
        const batch = empArr.slice(i, i + 6);
        const results = await Promise.all(
          batch.map(eid =>
            fetchJson(
              `${API_URL}/employees-schedule?emp_id=${eid}&date_from=${date_from}&date_to=${date_to}&employees=${eid}`,
              apiH,
            ).then(r => ({ eid, data: r.json })).catch(() => ({ eid, data: null }))
          )
        );
        for (const { eid, data } of results) {
          if (!data?.success || !data.data) continue;
          for (const s of data.data) {
            const abbr = idToAbbr[String(s.vagttype_id || '')];
            if (!abbr) continue;
            seenTypes.add(abbr);
            const date = s.vagt_dato;
            if (!enriched[date]) enriched[date] = [];
            enriched[date].push({
              date,
              time_start: (s.vagt_start || '').substring(0, 5),
              time_end: (s.vagt_slut || '').substring(0, 5),
              employee_name: empNames[eid] || String(eid),
              employee_id: eid,
              shift_type: abbr,
              department_name: 'Resepsjon',
              status: s.status || '',
              vagt_id: s.vagt_id || '',
            });
          }
        }
      }

      for (const shifts of Object.values(enriched)) {
        shifts.sort((a, b) => (a.time_start || '').localeCompare(b.time_start || ''));
      }

      return jsonResp({
        success: true,
        own_shifts: ownShifts,
        colleagues_shifts: enriched,
        vacant_shifts: vacantShifts,
        available_types: [...seenTypes].sort(),
      }, 200, origin);

    } catch (e) {
      return jsonResp({ error: e.message || 'Internal error' }, 500, origin);
    }
  },
};
