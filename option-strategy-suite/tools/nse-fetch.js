#!/usr/bin/env node
/* Local NSE helper for the Option Strategy Suite.
 *
 *   node tools/nse-fetch.js              → http://127.0.0.1:8123
 *   node tools/nse-fetch.js --mock       → deterministic fixture data, no network
 *   node tools/nse-fetch.js --check      → does this work on my machine? stage by stage
 *   node tools/nse-fetch.js --dump CE    → print the raw NSE payload it is reading
 *
 * Why this exists: nseindia.com sends no CORS headers and gates its APIs behind
 * session cookies set by a browser-like homepage visit. A static page therefore
 * cannot call NSE directly — the request is blocked before it leaves the tab.
 * This process does the handshake, aggregates the 09:15–09:20 candle from the
 * tick series, and re-serves it on localhost with CORS enabled.
 *
 * Node 18+. No dependencies.
 */

'use strict';

const http = require('http');

const ARGS = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = ARGS.indexOf('--' + name);
  return i !== -1 && ARGS[i + 1] && !ARGS[i + 1].startsWith('--') ? ARGS[i + 1] : fallback;
};
const has = (name) => ARGS.includes('--' + name);

const PORT = Number(flag('port', 8123));
const HOST = flag('host', '127.0.0.1');
const SYMBOL = flag('symbol', 'NIFTY').toUpperCase();
const STRIKE_STEP = Number(flag('strike-step', 100));
const MOCK = has('mock');

/* The window the strategy is built on, in IST. */
const CANDLE_FROM = flag('from', '09:15');
const CANDLE_TO = flag('to', '09:20');

const IST_OFFSET_MIN = 330;
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
           '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36';

/* ------------------------------------------------------------------ */
/* time helpers — everything is anchored to IST regardless of the host */
/* ------------------------------------------------------------------ */

function istParts(ms) {
  const d = new Date(ms + IST_OFFSET_MIN * 60000);
  return {
    y: d.getUTCFullYear(), m: d.getUTCMonth(), d: d.getUTCDate(),
    hh: d.getUTCHours(), mm: d.getUTCMinutes(), ss: d.getUTCSeconds()
  };
}

/** Epoch ms for a HH:MM on the IST calendar day containing `nowMs`. */
function istTimeToEpoch(hhmm, nowMs) {
  const [hh, mm] = hhmm.split(':').map(Number);
  const p = istParts(nowMs);
  return Date.UTC(p.y, p.m, p.d, hh, mm, 0) - IST_OFFSET_MIN * 60000;
}

function istClock(ms) {
  const p = istParts(ms);
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(p.hh)}:${pad(p.mm)}:${pad(p.ss)}`;
}

function istDateKey(ms) {
  const p = istParts(ms);
  return `${p.y}-${String(p.m + 1).padStart(2, '0')}-${String(p.d).padStart(2, '0')}`;
}

/* ------------------------------------------------------------------ */
/* candle aggregation — the one piece of real logic worth unit testing */
/* ------------------------------------------------------------------ */

/**
 * Fold a tick series into a single OHLC candle.
 * @param {Array<[number, number]>} ticks  [epochMs, price] pairs, any order
 * @param {number} fromMs inclusive
 * @param {number} toMs   exclusive
 */
function aggregate(ticks, fromMs, toMs) {
  const inWindow = (ticks || [])
    .filter((t) => Array.isArray(t) && t.length >= 2)
    .filter((t) => Number.isFinite(t[0]) && Number.isFinite(t[1]) && t[1] > 0)
    .filter((t) => t[0] >= fromMs && t[0] < toMs)
    .sort((a, b) => a[0] - b[0]);

  if (!inWindow.length) return null;

  const prices = inWindow.map((t) => t[1]);
  return {
    o: prices[0],
    h: Math.max.apply(null, prices),
    l: Math.min.apply(null, prices),
    c: prices[prices.length - 1],
    ticks: inWindow.length,
    firstTick: inWindow[0][0],
    lastTick: inWindow[inWindow.length - 1][0]
  };
}

function atmStrike(spot, step) {
  /* Rounded down, matching the strategy guide's own 23670 → 23600 example. */
  return Math.floor(spot / (step || STRIKE_STEP)) * (step || STRIKE_STEP);
}

/* ------------------------------------------------------------------ */
/* NSE session                                                         */
/* ------------------------------------------------------------------ */

let cookieJar = '';
let cookieSetAt = 0;

function baseHeaders() {
  return {
    'User-Agent': UA,
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.nseindia.com/option-chain',
    'Connection': 'keep-alive'
  };
}

/**
 * Pull Set-Cookie values off a response.
 *
 * getSetCookie() only exists from Node 18.14; older 18.x joins every cookie
 * into one comma-separated string, and `Expires=Wed, 21 Oct …` means a naive
 * split on commas corrupts them. Split only where a comma is followed by a
 * new `name=` pair instead. (headers.raw() is node-fetch, not native fetch —
 * it is never available here.)
 */
function readSetCookies(res) {
  if (typeof res.headers.getSetCookie === 'function') return res.headers.getSetCookie();
  const joined = res.headers.get('set-cookie');
  if (!joined) return [];
  return joined.split(/,\s*(?=[A-Za-z0-9!#$%&'*+._|~-]+=)/);
}

async function primeSession(force) {
  if (!force && cookieJar && Date.now() - cookieSetAt < 5 * 60000) return;
  const res = await fetch('https://www.nseindia.com/option-chain', {
    headers: Object.assign(baseHeaders(), { Accept: 'text/html,application/xhtml+xml' })
  });
  const raw = readSetCookies(res);
  cookieJar = raw.map((c) => c.split(';')[0]).filter(Boolean).join('; ');
  cookieSetAt = Date.now();
  if (!cookieJar) {
    throw new Error(
      `NSE returned no session cookies (HTTP ${res.status}). Usually the IP is blocked — ` +
      'datacenter, VPN and cloud addresses are refused where a home connection works.'
    );
  }
}

async function nseJson(url, attempt = 0) {
  await primeSession(attempt > 0);
  const res = await fetch(url, { headers: Object.assign(baseHeaders(), { Cookie: cookieJar }) });
  if ((res.status === 401 || res.status === 403) && attempt < 2) {
    return nseJson(url, attempt + 1);
  }
  if (!res.ok) throw new Error(`NSE ${res.status} for ${url}`);
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new Error(`NSE returned non-JSON (${text.slice(0, 80)}…) — session likely rejected`);
  }
}

/* ------------------------------------------------------------------ */
/* data assembly                                                       */
/* ------------------------------------------------------------------ */

async function optionChain() {
  return nseJson(`https://www.nseindia.com/api/option-chain-indices?symbol=${encodeURIComponent(SYMBOL)}`);
}

/**
 * NSE's chart endpoint returns { grapthData: [[ts, price], …] } (their spelling).
 * The timestamps are the one part of this that is undocumented and may need a
 * nudge — run with --dump CE to see what your feed actually sends.
 */
async function tickSeries(identifier) {
  const url = 'https://www.nseindia.com/api/chart-databyindex' +
              `?index=${encodeURIComponent(identifier)}&indices=false`;
  const data = await nseJson(url);
  return (data && (data.grapthData || data.graphData)) || [];
}

function pickContracts(chain, strike, expiry) {
  const rows = ((chain.records && chain.records.data) || [])
    .filter((r) => r.strikePrice === strike && r.expiryDate === expiry);
  const row = rows[0] || {};
  return { ce: row.CE || null, pe: row.PE || null };
}

async function firstCandle(nowMs) {
  if (MOCK) return mockPayload(nowMs);

  const chain = await optionChain();
  const records = chain.records || {};
  const spot = Number(records.underlyingValue);
  if (!Number.isFinite(spot)) throw new Error('option chain had no underlyingValue');

  const expiry = (records.expiryDates || [])[0];
  if (!expiry) throw new Error('option chain had no expiry dates');

  const strike = atmStrike(spot, STRIKE_STEP);
  const { ce, pe } = pickContracts(chain, strike, expiry);
  if (!ce || !pe) throw new Error(`no CE/PE rows for ${strike} ${expiry}`);

  const from = istTimeToEpoch(CANDLE_FROM, nowMs);
  const to = istTimeToEpoch(CANDLE_TO, nowMs);

  const [ceTicks, peTicks] = await Promise.all([
    tickSeries(ce.identifier), tickSeries(pe.identifier)
  ]);

  const ceCandle = aggregate(ceTicks, from, to);
  const peCandle = aggregate(peTicks, from, to);
  if (!ceCandle || !peCandle) {
    throw new Error(
      `no ticks inside ${CANDLE_FROM}–${CANDLE_TO} IST ` +
      `(CE ${ceTicks.length} raw, PE ${peTicks.length} raw). ` +
      'If the market has traded, the feed timestamps differ from the assumption — run with --dump CE.'
    );
  }

  return {
    symbol: SYMBOL,
    expiry,
    atm: strike,
    underlying: spot,
    window: { from: CANDLE_FROM, to: CANDLE_TO, tz: 'IST' },
    asOf: istClock(nowMs),
    source: 'nseindia.com',
    ce: ceCandle,
    pe: peCandle
  };
}

/* ------------------------------------------------------------------ */
/* mock mode — deterministic, so the client path can be tested offline */
/* ------------------------------------------------------------------ */

function mockSeries(base, shape, fromMs) {
  /* one tick every 10s across the five-minute window */
  return shape.map((delta, i) => [fromMs + i * 10000, Number((base + delta).toFixed(2))]);
}

function mockPayload(nowMs) {
  const from = istTimeToEpoch(CANDLE_FROM, nowMs);
  const to = istTimeToEpoch(CANDLE_TO, nowMs);
  const ce = aggregate(mockSeries(148.5, [0, 3.1, -7.3, 8.4, 14.25, 11.4], from), from, to);
  const pe = aggregate(mockSeries(155.0, [0, -4.2, 3.4, -12.1, -22.4, -17.85], from), from, to);
  return {
    symbol: SYMBOL, expiry: 'MOCK', atm: 23600, underlying: 23670,
    window: { from: CANDLE_FROM, to: CANDLE_TO, tz: 'IST' },
    asOf: istClock(nowMs), source: 'mock', ce, pe
  };
}

/* ------------------------------------------------------------------ */
/* server                                                              */
/* ------------------------------------------------------------------ */

const cache = new Map();

async function cachedFirstCandle(nowMs, fresh) {
  const key = `${istDateKey(nowMs)}:${SYMBOL}`;
  if (!fresh && cache.has(key)) return cache.get(key);
  const payload = await firstCandle(nowMs);
  cache.set(key, payload);   /* the 09:15–09:20 candle never changes once closed */
  return payload;
}

function send(res, status, body) {
  const json = JSON.stringify(body, null, 2);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Cache-Control': 'no-store'
  });
  res.end(json);
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${HOST}:${PORT}`);

  if (req.method === 'OPTIONS') return send(res, 204, {});

  if (url.pathname === '/health') {
    return send(res, 200, { ok: true, mode: MOCK ? 'mock' : 'live', symbol: SYMBOL, ist: istClock(Date.now()) });
  }

  if (url.pathname === '/first-candle') {
    try {
      const payload = await cachedFirstCandle(Date.now(), url.searchParams.get('fresh') === '1');
      return send(res, 200, payload);
    } catch (err) {
      return send(res, 502, { error: String(err.message || err), mode: MOCK ? 'mock' : 'live' });
    }
  }

  return send(res, 404, { error: 'try /health or /first-candle' });
});

/* ------------------------------------------------------------------ */

async function dump(which) {
  const chain = await optionChain();
  const records = chain.records || {};
  const strike = atmStrike(Number(records.underlyingValue), STRIKE_STEP);
  const expiry = (records.expiryDates || [])[0];
  const { ce, pe } = pickContracts(chain, strike, expiry);
  const leg = which.toUpperCase() === 'PE' ? pe : ce;
  console.log(`spot ${records.underlyingValue}  atm ${strike}  expiry ${expiry}`);
  console.log(`identifier ${leg && leg.identifier}`);
  const ticks = await tickSeries(leg.identifier);
  console.log(`${ticks.length} ticks; first 3 raw:`, JSON.stringify(ticks.slice(0, 3)));
  if (ticks.length) {
    console.log('first tick as IST :', istClock(ticks[0][0]));
    console.log('last  tick as IST :', istClock(ticks[ticks.length - 1][0]));
    console.log('window expected   :', CANDLE_FROM, '→', CANDLE_TO,
                '(', istClock(istTimeToEpoch(CANDLE_FROM, Date.now())), ')');
  }
}

/* ------------------------------------------------------------------ */
/* --check : answer "will this work on my machine?" stage by stage     */
/* ------------------------------------------------------------------ */

async function selfCheck() {
  const results = [];
  const step = async (name, fn, hint) => {
    try {
      const detail = await fn();
      results.push({ ok: true, name, detail });
      console.log(`  ✓ ${name}${detail ? ' — ' + detail : ''}`);
      return true;
    } catch (err) {
      results.push({ ok: false, name, detail: err.message });
      console.log(`  ✗ ${name} — ${err.message}`);
      if (hint) console.log(`      → ${hint}`);
      return false;
    }
  };

  console.log('NSE helper self-check\n');

  const major = Number(process.versions.node.split('.')[0]);
  const minor = Number(process.versions.node.split('.')[1]);
  await step('Node version', async () => {
    if (major < 18) throw new Error(`Node ${process.versions.node}; built-in fetch needs 18+`);
    if (major === 18 && minor < 14) {
      return `Node ${process.versions.node} (no getSetCookie — using the fallback cookie parser)`;
    }
    return `Node ${process.versions.node}`;
  }, 'Install Node 18.14 or newer.');

  let chain = null;
  const reachable = await step('Reach nseindia.com + session cookies', async () => {
    await primeSession(true);
    return `${cookieJar.split('; ').length} cookies`;
  }, 'Blocked IPs are the usual cause — try a home connection, VPN off.');

  if (!reachable) { summarise(results); return results; }

  await step('Option chain API', async () => {
    chain = await optionChain();
    const n = ((chain.records && chain.records.data) || []).length;
    if (!n) throw new Error('empty records.data');
    return `${n} strike rows`;
  }, 'The endpoint or its shape may have changed.');

  if (!chain) { summarise(results); return results; }

  const records = chain.records || {};
  const spot = Number(records.underlyingValue);
  const expiry = (records.expiryDates || [])[0];
  const strike = atmStrike(spot, STRIKE_STEP);
  let legs = { ce: null, pe: null };

  await step('ATM strike + nearest expiry', async () => {
    if (!Number.isFinite(spot)) throw new Error('no underlyingValue');
    if (!expiry) throw new Error('no expiryDates');
    legs = pickContracts(chain, strike, expiry);
    if (!legs.ce || !legs.pe) throw new Error(`no CE/PE rows at ${strike} ${expiry}`);
    return `spot ${spot} → ATM ${strike}, expiry ${expiry}`;
  });

  if (!legs.ce) { summarise(results); return results; }

  let ticks = [];
  await step('Tick series for the ATM call', async () => {
    ticks = await tickSeries(legs.ce.identifier);
    if (!Array.isArray(ticks) || !ticks.length) {
      throw new Error('chart endpoint returned no ticks (may be closed, or the shape changed)');
    }
    return `${ticks.length} ticks`;
  }, 'This endpoint is undocumented — it is the most likely thing to have moved.');

  if (ticks.length) {
    const now = Date.now();
    const from = istTimeToEpoch(CANDLE_FROM, now);
    const to = istTimeToEpoch(CANDLE_TO, now);
    await step('Timestamps land in the 09:15–09:20 IST window', async () => {
      const candle = aggregate(ticks, from, to);
      if (!candle) {
        throw new Error(
          `0 of ${ticks.length} ticks fall in the window. ` +
          `First tick reads as ${istClock(ticks[0][0])} IST, last ${istClock(ticks[ticks.length - 1][0])} IST`
        );
      }
      return `${candle.ticks} ticks → O ${candle.o} H ${candle.h} L ${candle.l} C ${candle.c}`;
    }, 'Run --dump CE to see raw timestamps, then correct with --from/--to if they are offset.');
  }

  summarise(results);
  return results;
}

function summarise(results) {
  const failed = results.filter((r) => !r.ok);
  console.log('');
  if (!failed.length) {
    console.log('All checks passed — start it with: node tools/nse-fetch.js');
  } else {
    console.log(`${failed.length} check(s) failed: ${failed.map((f) => f.name).join(', ')}`);
    console.log('The suite still works with values typed in by hand.');
  }
}

if (require.main === module) {
  if (has('check')) {
    selfCheck()
      .then((r) => process.exit(r.every((x) => x.ok) ? 0 : 1))
      .catch((e) => { console.error('self-check crashed:', e.message); process.exit(1); });
  } else if (has('dump')) {
    dump(flag('dump', 'CE')).catch((e) => { console.error('dump failed:', e.message); process.exit(1); });
  } else {
    server.listen(PORT, HOST, () => {
      console.log('NSE helper for the Option Strategy Suite');
      console.log(`  mode      ${MOCK ? 'mock (no network)' : 'live nseindia.com'}`);
      console.log(`  symbol    ${SYMBOL}, candle ${CANDLE_FROM}–${CANDLE_TO} IST`);
      console.log(`  listening http://${HOST}:${PORT}`);
      console.log(`  endpoints /health  /first-candle`);
      console.log('  point the app at this URL under "Auto-fetch" on the Analyser tab.');
    });
  }
}

module.exports = {
  aggregate, atmStrike, istTimeToEpoch, istClock, istDateKey, readSetCookies, selfCheck, server
};
