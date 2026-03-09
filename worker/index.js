const DELTAPLAN_BASE = 'https://deltaplan.dk/deltaplan_v2/classic';
const API_URL = `${DELTAPLAN_BASE}/API`;
const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

function corsHeaders(origin) {
  return {
    'Access-Control-Allow-Origin': origin || '*',
    'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
  };
}

function jsonResp(data, status, origin) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) },
  });
}

function extractCookies(response) {
  const cookies = {};

  // Method 1: getSetCookie() — modern standard, returns array
  try {
    if (typeof response.headers.getSetCookie === 'function') {
      const arr = response.headers.getSetCookie();
      for (const sc of arr) {
        const nv = sc.split(';')[0];
        const eq = nv.indexOf('=');
        if (eq > 0) cookies[nv.substring(0, eq).trim()] = nv.substring(eq + 1).trim();
      }
      if (Object.keys(cookies).length > 0) return cookies;
    }
  } catch {}

  // Method 2: getAll() — non-standard, some runtimes support it
  try {
    if (typeof response.headers.getAll === 'function') {
      const arr = response.headers.getAll('set-cookie');
      for (const sc of arr) {
        const nv = sc.split(';')[0];
        const eq = nv.indexOf('=');
        if (eq > 0) cookies[nv.substring(0, eq).trim()] = nv.substring(eq + 1).trim();
      }
      if (Object.keys(cookies).length > 0) return cookies;
    }
  } catch {}

  // Method 3: get('set-cookie') — returns comma-joined string
  // Split on ", " followed by a token that looks like a cookie name (alpha=)
  try {
    const raw = response.headers.get('set-cookie');
    if (raw) {
      const parts = raw.split(/,\s*(?=[A-Za-z_][A-Za-z0-9_]*=)/);
      for (const part of parts) {
        const nv = part.split(';')[0];
        const eq = nv.indexOf('=');
        if (eq > 0) cookies[nv.substring(0, eq).trim()] = nv.substring(eq + 1).trim();
      }
    }
  } catch {}

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

function commonHeaders() {
  return {
    'User-Agent': UA,
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9,da;q=0.8',
    'Referer': `${DELTAPLAN_BASE}/`,
  };
}

async function fetchJson(url, extraHeaders) {
  const r = await fetch(url, { headers: { ...commonHeaders(), ...extraHeaders } });
  const cookies = extractCookies(r);
  const text = await r.text();
  try {
    return { json: JSON.parse(text), cookies };
  } catch {
    throw new Error(`Non-JSON from ${url.split('?')[0]} (HTTP ${r.status}): ${text.substring(0, 150)}`);
  }
}

async function doLogin(username, password) {
  // POST login
  const loginResp = await fetch(`${API_URL}/login`, {
    method: 'POST',
    headers: {
      ...commonHeaders(),
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
    redirect: 'manual',
  });

  const cookies = extractCookies(loginResp);
  const loc = loginResp.headers.get('location') || '';
  const status = loginResp.status;

  // Debug info to include in errors
  const debugInfo = {
    loginStatus: status,
    location: loc,
    cookieCount: Object.keys(cookies).length,
    cookieNames: Object.keys(cookies),
    hasGetSetCookie: typeof loginResp.headers.getSetCookie === 'function',
    responseType: loginResp.type,
  };

  if (loc.includes('err=')) {
    throw new Error(`Login failed — invalid credentials (loc: ${loc})`);
  }

  if (Object.keys(cookies).length === 0) {
    // No cookies extracted — try following redirect to see if we get cookies there
    const followResp = await fetch(`${API_URL}/login`, {
      method: 'POST',
      headers: {
        ...commonHeaders(),
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
      // default redirect: 'follow'
    });
    const followCookies = extractCookies(followResp);
    if (Object.keys(followCookies).length > 0) {
      Object.assign(cookies, followCookies);
    } else {
      throw new Error(`Login succeeded (HTTP ${status}) but no cookies extracted. Debug: ${JSON.stringify(debugInfo)}`);
    }
  }

  return cookies;
}

export default {
  async fetch(request) {
    const origin = request.headers.get('Origin') || '*';

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    const url = new URL(request.url);

    // Health check
    if ((url.pathname === '/' || url.pathname === '/health') && request.method === 'GET') {
      return jsonResp({ status: 'ok', message: 'Deltaplan proxy worker is running' }, 200, origin);
    }

    // Debug endpoint — helps diagnose login/cookie issues
    if (url.pathname === '/debug' && request.method === 'POST') {
      try {
        const { username, password } = await request.json();
        const loginResp = await fetch(`${API_URL}/login`, {
          method: 'POST',
          headers: {
            ...commonHeaders(),
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
          redirect: 'manual',
        });

        const allHeaders = {};
        loginResp.headers.forEach((v, k) => {
          allHeaders[k] = allHeaders[k] ? allHeaders[k] + ' | ' + v : v;
        });

        let setCookieArray = [];
        try { setCookieArray = loginResp.headers.getSetCookie(); } catch (e) { setCookieArray = [`error: ${e.message}`]; }

        const cookies = extractCookies(loginResp);

        return jsonResp({
          loginStatus: loginResp.status,
          responseType: loginResp.type,
          location: loginResp.headers.get('location'),
          allHeaders,
          getSetCookieResult: setCookieArray,
          setCookieRaw: loginResp.headers.get('set-cookie')?.substring(0, 500),
          extractedCookies: Object.keys(cookies),
          extractedCookieCount: Object.keys(cookies).length,
        }, 200, origin);
      } catch (e) {
        return jsonResp({ error: e.message }, 500, origin);
      }
    }

    if (url.pathname !== '/schedule' || request.method !== 'POST') {
      return jsonResp({ error: 'POST /schedule required' }, 404, origin);
    }

    try {
      const { username, password, date_from, date_to } = await request.json();
      if (!username || !password || !date_from || !date_to) {
        return jsonResp({ error: 'Missing required fields' }, 400, origin);
      }

      // 1. Login
      let cookies = await doLogin(username, password);

      // 2. Extract user info from cookies (base64-encoded)
      // vs_medarb_id = base64(employee_id), vs_virksomhed_id = base64(company_id)
      let userId, companyId;
      try {
        userId = atob(decodeURIComponent(cookies.vs_medarb_id || ''));
        companyId = atob(decodeURIComponent(cookies.vs_virksomhed_id || ''));
      } catch {
        return jsonResp({ error: 'Could not decode user info from cookies' }, 500, origin);
      }
      if (!userId || !companyId) {
        return jsonResp({ error: `Missing user cookies (have: ${Object.keys(cookies).join(', ')})` }, 500, origin);
      }

      const apiH = {
        Cookie: cookieStr(cookies),
        'User-Id': userId,
        'User-Company-Id': companyId,
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
      };

      // 3. Fetch shift types + schedule in parallel (just 2 API calls)
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

      // Collect available shift types from the shift types list
      const seenTypes = new Set();
      for (const abbr of Object.values(idToAbbr)) {
        seenTypes.add(abbr);
      }

      return jsonResp({
        success: true,
        own_shifts: ownShifts,
        vacant_shifts: vacantShifts,
        available_types: [...seenTypes].sort(),
      }, 200, origin);

    } catch (e) {
      return jsonResp({ error: e.message || 'Internal error' }, 500, origin);
    }
  },
};
