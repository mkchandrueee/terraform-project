#!/usr/bin/env node
/* Local NSE helper for the Option Strategy Suite.
 *
 *   node tools/nse-fetch.js              → http://127.0.0.1:8123
 *   node tools/nse-fetch.js --mock       → deterministic fixture data, no network
 *   node tools/nse-fetch.js --check      → does this work on my machine? stage by stage
 *   node tools/nse-fetch.js --dump CE    → print the raw tick payload it is reading
 *   node tools/nse-fetch.js --dump chain    → which chain endpoint answered, and its shape
 *   node tools/nse-fetch.js --dump expiries → the expiry dates it will try
 *
 *   node tools/nse-fetch.js --serve --token SECRET
 *       serves the app AND the API on one port, gated by a shared secret, so a
 *       single tunnel puts the whole thing on a phone from anywhere. See IOS.md.
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
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ARGS = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = ARGS.indexOf('--' + name);
  return i !== -1 && ARGS[i + 1] && !ARGS[i + 1].startsWith('--') ? ARGS[i + 1] : fallback;
};
const has = (name) => ARGS.includes('--' + name);

const BASE = (flag('base', 'https://www.nseindia.com')).replace(/\/+$/, '');
const CHAIN_URL = flag('chain-url', '');     /* force one endpoint */
const EXPIRY = flag('expiry', '');           /* force one expiry */
const EXPIRY_DAY = Number(flag('expiry-day', 2)); /* 0=Sun … 2=Tue, NIFTY weekly */
const PORT = Number(flag('port', 8123));
const HOST = flag('host', '127.0.0.1');
const SYMBOL = flag('symbol', 'NIFTY').toUpperCase();
const STRIKE_STEP = Number(flag('strike-step', 0));   /* 0 = derive from the chain */
const MOCK = has('mock');

/* --serve makes this one process the whole app: the API and the static files
   on a single origin. That matters off the LAN, where the phone reaches the PC
   through one tunnel — two ports would need two tunnels and two URLs.
   --token gates it, because a tunnel is reachable by anyone holding the URL. */
const SERVE_APP = has('serve');
const TOKEN = flag('token', '');
const APP_ROOT = path.resolve(__dirname, '..');

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

/** Full IST stamp — a date mismatch otherwise reads as a timezone bug. */
function istStamp(ms) {
  return istDateKey(ms) + ' ' + istClock(ms);
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

/**
 * NSE's chart timestamps are IST wall-clock already, not true epoch, so adding
 * the IST offset again lands them 5h30m late. Rather than hardcode that (it is
 * undocumented and could change), test both readings and keep whichever puts
 * the first tick nearest the 09:15 open.
 */
function detectTickOffset(ticks) {
  if (!ticks || !ticks.length) return { offset: 0, convention: 'unknown', dist: Infinity };
  var first = ticks[0][0];
  var open = 9 * 60 + 15;
  var candidates = [
    { offset: 0, convention: 'epoch-utc' },
    { offset: -IST_OFFSET_MIN * 60000, convention: 'ist-wall-clock' }
  ];
  var best = null;
  candidates.forEach(function (c) {
    var p = istParts(first + c.offset);
    var dist = Math.abs((p.hh * 60 + p.mm) - open);
    if (!best || dist < best.dist) best = { offset: c.offset, convention: c.convention, dist: dist };
  });
  return best;
}

function shiftTicks(ticks, offset) {
  if (!offset) return ticks || [];
  return (ticks || []).map(function (t) { return [t[0] + offset, t[1]]; });
}

function atmStrike(spot, step) {
  /* Rounded down, matching the strategy guide's own 23670 → 23600 example. */
  var s = step || STRIKE_STEP || 100;
  return Math.floor(spot / s) * s;
}

/* ------------------------------------------------------------------ */
/* symbols — indices and NIFTY 50 stocks use different endpoints, strike
   steps and expiry calendars                                          */
/* ------------------------------------------------------------------ */

const INDEX_SYMBOLS = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50'];

function isIndex(symbol) {
  return INDEX_SYMBOLS.indexOf(String(symbol).toUpperCase()) !== -1;
}

/** NSE trading symbols are upper-case letters, digits, & - and &. Anything
    else is somebody's typo or an injection attempt, not a stock. */
function cleanSymbol(raw, fallback) {
  const s = String(raw == null ? '' : raw).trim().toUpperCase().replace(/[^A-Z0-9&\-]/g, '');
  return s || fallback || SYMBOL;
}

/**
 * Strike spacing differs per stock — RELIANCE steps in 20s, BAJFINANCE in
 * 50s or 100s, and NSE revises them. Read it off the chain instead of
 * keeping a table that goes stale: take the most common gap between
 * adjacent strikes.
 */
function strikeStepFromChain(payload) {
  const strikes = Array.from(new Set(chainRows(payload)
    .map(function (r) { return Number(r.strikePrice); })
    .filter(function (n) { return Number.isFinite(n) && n > 0; }))).sort(function (a, b) { return a - b; });
  if (strikes.length < 3) return 0;

  const counts = new Map();
  for (let i = 1; i < strikes.length; i++) {
    const gap = Math.round((strikes[i] - strikes[i - 1]) * 100) / 100;
    if (gap > 0) counts.set(gap, (counts.get(gap) || 0) + 1);
  }
  let best = 0, bestCount = -1;
  counts.forEach(function (count, gap) {
    if (count > bestCount || (count === bestCount && gap < best)) { best = gap; bestCount = count; }
  });
  return best;
}

/** Contract size, needed for the money maths — it is per stock, not per lot. */
async function marketLot(symbol) {
  try {
    const data = await nseJson(BASE + '/api/quote-derivative?symbol=' + encodeURIComponent(symbol));
    const stocks = (data && data.stocks) || [];
    for (let i = 0; i < stocks.length; i++) {
      const lot = Number(stocks[i].marketDeptOrderBook &&
                         stocks[i].marketDeptOrderBook.tradeInfo &&
                         stocks[i].marketDeptOrderBook.tradeInfo.marketLot);
      if (Number.isFinite(lot) && lot > 0) return lot;
    }
    const info = data && data.info;
    const alt = Number(info && info.marketLot);
    return Number.isFinite(alt) && alt > 0 ? alt : NaN;
  } catch (e) {
    return NaN;
  }
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
    'Referer': BASE + '/option-chain',
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
  const res = await fetch(BASE + '/option-chain', {
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

/* NSE keeps moving this. option-chain-indices now 404s for many users; the
   replacement is option-chain-v3, which needs an explicit expiry, and the
   expiry list comes from its own endpoint. Rather than pick one and hope, try
   them in order and report which answered — see --check and --dump chain. */
var lastExpirySource = '';

function chainRows(payload) {
  if (!payload) return [];
  if (Array.isArray(payload.data)) return payload.data;
  if (payload.records && Array.isArray(payload.records.data)) return payload.records.data;
  if (payload.filtered && Array.isArray(payload.filtered.data)) return payload.filtered.data;
  return [];
}

function chainUnderlying(payload) {
  var candidates = [
    payload && payload.underlyingValue,
    payload && payload.records && payload.records.underlyingValue,
    payload && payload.filtered && payload.filtered.underlyingValue
  ];
  for (var i = 0; i < candidates.length; i++) {
    var n = Number(candidates[i]);
    if (Number.isFinite(n) && n > 0) return n;
  }
  /* last resort: the option chain carries the spot on every row */
  var rows = chainRows(payload);
  for (var j = 0; j < rows.length; j++) {
    var leg = rows[j].CE || rows[j].PE;
    var v = leg && Number(leg.underlyingValue);
    if (Number.isFinite(v) && v > 0) return v;
  }
  return NaN;
}

function chainExpiries(payload) {
  if (!payload) return [];
  return payload.expiryDates
      || (payload.records && payload.records.expiryDates)
      || [];
}

var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** NSE's own format, e.g. 30-Oct-2025. */
function formatExpiry(ms) {
  var p = istParts(ms);
  return String(p.d).padStart(2, '0') + '-' + MONTHS[p.m] + '-' + p.y;
}

/** Upcoming weekly expiries, so a missing expiry list is not fatal. NIFTY
    weeklies are Tuesdays; --expiry-day covers the next time NSE moves them. */
function upcomingExpiries(count) {
  var out = [];
  var day = 86400000;
  var start = Date.now();
  for (var i = 0; i < 70 && out.length < count; i++) {
    var ms = start + i * day;
    var d = new Date(ms + IST_OFFSET_MIN * 60000);
    if (d.getUTCDay() === EXPIRY_DAY) out.push(formatExpiry(ms));
  }
  return out;
}

/** Returns { list, source } so --check can say where the expiries came from. */
function legacyChainUrl(symbol) {
  return BASE + (isIndex(symbol) ? '/api/option-chain-indices' : '/api/option-chain-equities') +
         '?symbol=' + encodeURIComponent(symbol);
}

function v3ChainUrl(symbol, expiry) {
  return BASE + '/api/option-chain-v3?type=' + (isIndex(symbol) ? 'Indices' : 'Equity') +
         '&symbol=' + encodeURIComponent(symbol) + '&expiry=' + encodeURIComponent(expiry);
}

/** Stock options are monthly, index weeklies are not — so the calendar
    fallback differs: last <EXPIRY_DAY> of each month rather than every one. */
function upcomingMonthlies(count) {
  const out = [];
  const now = new Date(Date.now() + IST_OFFSET_MIN * 60000);
  for (let m = 0; m < 12 && out.length < count; m++) {
    const y = now.getUTCFullYear();
    const monthIdx = now.getUTCMonth() + m;
    const lastDay = new Date(Date.UTC(y, monthIdx + 1, 0));
    while (lastDay.getUTCDay() !== EXPIRY_DAY) lastDay.setUTCDate(lastDay.getUTCDate() - 1);
    const ms = lastDay.getTime() - IST_OFFSET_MIN * 60000;
    if (ms + 86400000 > Date.now()) out.push(formatExpiry(ms));
  }
  return out;
}

async function expiryList(symbol) {
  symbol = symbol || SYMBOL;
  if (EXPIRY) return { list: [EXPIRY], source: '--expiry flag' };

  var sources = [
    ['contract-info', BASE + '/api/option-chain-contract-info?symbol=' + encodeURIComponent(symbol)],
    ['legacy chain', legacyChainUrl(symbol)]
  ];
  for (var i = 0; i < sources.length; i++) {
    try {
      var list = chainExpiries(await nseJson(sources[i][1]));
      if (list.length) return { list: list, source: sources[i][0] };
    } catch (e) { /* try the next one */ }
  }
  /* Nothing published one — fall back to the calendar. */
  if (isIndex(symbol)) {
    return { list: upcomingExpiries(6), source: 'calendar (next 6 weeklies)' };
  }
  return { list: upcomingMonthlies(3), source: 'calendar (next 3 monthlies)' };
}

/** Returns { payload, url, expiry } from whichever endpoint answers. */
async function optionChain(symbol) {
  symbol = symbol || SYMBOL;
  var tried = [];

  async function attempt(url) {
    try {
      var payload = await nseJson(url);
      if (chainRows(payload).length) return { payload: payload, url: url };
      tried.push(url + ' → 200 but no strike rows');
    } catch (e) {
      tried.push(url + ' → ' + e.message);
    }
    return null;
  }

  if (CHAIN_URL) {
    var forced = await attempt(CHAIN_URL);
    if (forced) return forced;
    throw new Error('forced --chain-url failed:\n  ' + tried.join('\n  '));
  }

  /* 1. current: v3, which needs an explicit expiry — without one it answers
        200 with an empty object, so every candidate has to be tried. */
  var found = await expiryList(symbol);
  lastExpirySource = found.source;
  for (var i = 0; i < found.list.length; i++) {
    var v3 = await attempt(v3ChainUrl(symbol, found.list[i]));
    if (v3) { v3.expiry = found.list[i]; v3.expirySource = found.source; return v3; }
  }

  /* 2. legacy: whole chain in one call */
  var legacy = await attempt(legacyChainUrl(symbol));
  if (legacy) return legacy;

  throw new Error(
    'no option-chain endpoint returned strike rows. Tried:\n  ' + tried.join('\n  ') +
    '\nSymbol ' + symbol + ' (' + (isIndex(symbol) ? 'index' : 'equity') + '), expiries came from: ' + lastExpirySource +
    '\nAn empty {} from v3 usually means the expiry is wrong — but for a stock it' +
    '\nmore often means NSE lists no options on it. Only F&O-approved symbols have' +
    '\na chain; the NIFTY 50 all do. Open' +
    '\n  ' + BASE + '/api/option-chain-contract-info?symbol=' + symbol +
    '\nin your browser, then pass a date from it: --expiry 30-Oct-2025'
  );
}

/**
 * NSE's chart endpoint returns { grapthData: [[ts, price], …] } (their spelling).
 * The timestamps are the one part of this that is undocumented and may need a
 * nudge — run with --dump CE to see what your feed actually sends.
 */
async function tickSeries(identifier) {
  const url = BASE + '/api/chart-databyindex' +
              `?index=${encodeURIComponent(identifier)}&indices=false`;
  const data = await nseJson(url);
  return (data && (data.grapthData || data.graphData)) || [];
}

function pickContracts(payload, strike, expiry) {
  const all = chainRows(payload);
  let rows = all.filter((r) => Number(r.strikePrice) === strike && r.expiryDate === expiry);
  /* a v3 response is already one expiry, so the date may not be echoed per row */
  if (!rows.length) rows = all.filter((r) => Number(r.strikePrice) === strike);
  const row = rows[0] || {};
  return { ce: row.CE || null, pe: row.PE || null };
}

async function firstCandle(nowMs, symbol) {
  symbol = cleanSymbol(symbol, SYMBOL);
  if (MOCK) return mockPayload(nowMs, symbol);

  const chain = await optionChain(symbol);
  const spot = chainUnderlying(chain.payload);
  if (!Number.isFinite(spot)) throw new Error('option chain carried no underlying value');

  const expiry = chain.expiry || chainExpiries(chain.payload)[0] ||
                 (chainRows(chain.payload)[0] || {}).expiryDate;
  if (!expiry) throw new Error('could not determine the expiry from the option chain');

  /* --strike-step wins when set; otherwise read the spacing off this chain, so
     a stock stepping in 20s is not rounded as if it stepped in 100s. */
  const step = STRIKE_STEP || strikeStepFromChain(chain.payload) || (isIndex(symbol) ? 100 : 0);
  if (!step) throw new Error(`could not work out the strike spacing for ${symbol} — pass --strike-step`);

  const strike = atmStrike(spot, step);
  const { ce, pe } = pickContracts(chain.payload, strike, expiry);
  if (!ce || !pe) throw new Error(`no CE/PE rows for ${symbol} ${strike} ${expiry}`);

  const lotSize = await marketLot(symbol);

  const [ceRaw, peRaw] = await Promise.all([
    tickSeries(ce.identifier), tickSeries(pe.identifier)
  ]);

  const conv = detectTickOffset(ceRaw.length ? ceRaw : peRaw);
  const ceTicks = shiftTicks(ceRaw, conv.offset);
  const peTicks = shiftTicks(peRaw, conv.offset);

  /* Anchor the window to the session the feed actually returned. Before the
     open, or on a holiday, NSE serves the previous session — silently treating
     that as today's candle would be the worst kind of wrong. */
  const anchor = (ceTicks[0] || peTicks[0] || [nowMs])[0];
  const from = istTimeToEpoch(CANDLE_FROM, anchor);
  const to = istTimeToEpoch(CANDLE_TO, anchor);
  const session = istDateKey(anchor);
  const stale = session !== istDateKey(nowMs);

  const ceCandle = aggregate(ceTicks, from, to);
  const peCandle = aggregate(peTicks, from, to);
  if (!ceCandle || !peCandle) {
    const sample = ceTicks.length ? ceTicks : peTicks;
    throw new Error(
      `no ticks inside ${istStamp(from)} – ${CANDLE_TO} IST (session ${session}, ` +
      `timestamps read as ${conv.convention}) ` +
      `(CE ${ceTicks.length} raw, PE ${peTicks.length} raw)` +
      (sample.length
        ? `. The feed's own ticks run ${istStamp(sample[0][0])} → ${istStamp(sample[sample.length - 1][0])} IST` +
          ' — compare the dates, not just the clock times.'
        : '.') +
      ' Run --dump CE to see the raw values.'
    );
  }

  return {
    symbol: symbol,
    kind: isIndex(symbol) ? 'index' : 'equity',
    expiry,
    atm: strike,
    strikeStep: step,
    lotSize: Number.isFinite(lotSize) ? lotSize : null,
    underlying: spot,
    window: { from: CANDLE_FROM, to: CANDLE_TO, tz: 'IST' },
    asOf: istClock(nowMs),
    session: session,
    stale: stale,
    tickConvention: conv.convention,
    source: 'nseindia.com',
    endpoint: chain.url,
    ce: ceCandle,
    pe: peCandle
  };
}

/* ------------------------------------------------------------------ */
/* scan — the same first-candle maths across timeframes, strikes, expiries.
   Every timeframe starts at the session open and runs for its own length, so
   the 5-minute candle is 09:15–09:20 and the hour is 09:15–10:15. Tick series
   are fetched once per contract and re-aggregated per timeframe.            */
/* ------------------------------------------------------------------ */

const tickCache = new Map();

async function cachedTicks(identifier, session, symbol) {
  const key = symbol + ':' + session + ':' + identifier;
  if (tickCache.has(key)) return tickCache.get(key);
  const raw = await tickSeries(identifier);
  tickCache.set(key, raw);
  return raw;
}

function windowFor(tf, anchor) {
  const from = istTimeToEpoch(CANDLE_FROM, anchor);
  return { from: from, to: from + tf * 60000 };
}

async function scan(opts, nowMs) {
  const symbol = cleanSymbol(opts.symbol, SYMBOL);
  if (MOCK) return mockScan(opts, nowMs, symbol);

  const tfs = opts.tfs;
  const rows = [];
  const skipped = [];

  const found = await expiryList(symbol);
  const expiries = found.list.slice(0, Math.max(1, opts.expiries));

  let atm = NaN, underlying = NaN, session = null, stale = false, conv = null;
  let step = STRIKE_STEP;
  const lotSize = await marketLot(symbol);

  for (const expiry of expiries) {
    let chain;
    try {
      chain = await optionChain(symbol);
    } catch (err) {
      skipped.push({ expiry: expiry, reason: err.message });
      continue;
    }
    /* v3 is scoped to one expiry, so re-request per expiry when forced */
    if (!CHAIN_URL && chain.expiry && chain.expiry !== expiry) {
      try {
        const payload = await nseJson(v3ChainUrl(symbol, expiry));
        if (chainRows(payload).length) chain = { payload: payload, url: 'v3', expiry: expiry };
      } catch (err) {
        skipped.push({ expiry: expiry, reason: err.message });
        continue;
      }
    }

    if (!Number.isFinite(underlying)) {
      underlying = chainUnderlying(chain.payload);
      step = step || strikeStepFromChain(chain.payload) || (isIndex(symbol) ? 100 : 0);
      if (!step) {
        skipped.push({ expiry: expiry, reason: 'could not work out the strike spacing — pass --strike-step' });
        continue;
      }
      atm = atmStrike(underlying, step);
    }

    /* Offsets are counted in strikes, not rupees, so ±1 means the neighbouring
       contract whether the symbol steps in 20s, 50s or 100s. */
    for (const offset of opts.offsets) {
      const strike = atm + offset * step;
      const legs = pickContracts(chain.payload, strike, expiry);
      if (!legs.ce || !legs.pe) {
        skipped.push({ expiry: expiry, strike: strike, reason: 'no CE/PE rows' });
        continue;
      }
      let ceRaw, peRaw;
      try {
        [ceRaw, peRaw] = await Promise.all([
          cachedTicks(legs.ce.identifier, expiry, symbol),
          cachedTicks(legs.pe.identifier, expiry, symbol)
        ]);
      } catch (err) {
        skipped.push({ expiry: expiry, strike: strike, reason: err.message });
        continue;
      }
      if (!ceRaw.length && !peRaw.length) {
        skipped.push({ expiry: expiry, strike: strike, reason: 'no ticks' });
        continue;
      }

      conv = conv || detectTickOffset(ceRaw.length ? ceRaw : peRaw);
      const ceT = shiftTicks(ceRaw, conv.offset);
      const peT = shiftTicks(peRaw, conv.offset);
      const anchor = (ceT[0] || peT[0])[0];
      if (!session) {
        session = istDateKey(anchor);
        stale = session !== istDateKey(nowMs);
      }

      for (const tf of tfs) {
        const w = windowFor(tf, anchor);
        const ce = aggregate(ceT, w.from, w.to);
        const pe = aggregate(peT, w.from, w.to);
        if (!ce || !pe) {
          skipped.push({ expiry: expiry, strike: strike, tf: tf, reason: 'no ticks in window' });
          continue;
        }
        rows.push({ expiry: expiry, strike: strike, tf: tf, ce: ce, pe: pe });
      }
    }
  }

  return {
    symbol: symbol, kind: isIndex(symbol) ? 'index' : 'equity',
    atm: atm, underlying: underlying,
    strikeStep: step || null,
    lotSize: Number.isFinite(lotSize) ? lotSize : null,
    session: session, stale: stale,
    tickConvention: conv ? conv.convention : 'unknown',
    asOf: istClock(nowMs), source: 'nseindia.com',
    rows: rows, skipped: skipped
  };
}

/* ------------------------------------------------------------------ */
/* mock mode — deterministic, so the client path can be tested offline */
/* ------------------------------------------------------------------ */

function mockSeries(base, shape, fromMs) {
  /* one tick every 10s across the five-minute window */
  return shape.map((delta, i) => [fromMs + i * 10000, Number((base + delta).toFixed(2))]);
}

/* Deterministic scan fixture: a wider timeframe sees a wider range, which is
   what makes the multi-timeframe comparison worth looking at. */
function mockScan(opts, nowMs, symbol) {
  symbol = cleanSymbol(symbol, SYMBOL);
  const anchor = istTimeToEpoch(CANDLE_FROM, nowMs);
  const rows = [];
  /* Stand-ins that behave like the real thing: an index steps in 100s off a
     24300 spot, a stock in 20s off 1500 — enough to prove the strike maths. */
  const index = isIndex(symbol);
  const step = STRIKE_STEP || (index ? 100 : 20);
  const base = index ? 24300 : 1500;
  const lot = index ? 75 : 500;
  opts.expiriesList = (index ? ['MOCK-W1', 'MOCK-W2'] : ['MOCK-M1', 'MOCK-M2'])
    .slice(0, Math.max(1, opts.expiries));
  opts.expiriesList.forEach(function (expiry, ei) {
    opts.offsets.forEach(function (offset) {
      const strike = base + offset * step;
      opts.tfs.forEach(function (tf) {
        const grow = Math.sqrt(tf / 5);
        const ceBase = 130 + offset * 5 + ei * 3;
        const peBase = 120 - offset * 5 + ei * 2;
        rows.push({
          expiry: expiry, strike: strike, tf: tf,
          ce: { o: round2(ceBase), h: round2(ceBase + 8 * grow), l: round2(ceBase - 4 * grow),
                c: round2(ceBase - 3 * grow), ticks: tf * 6 },
          pe: { o: round2(peBase), h: round2(peBase + 12 * grow), l: round2(peBase - 1),
                c: round2(peBase + 10 * grow), ticks: tf * 6 }
        });
      });
    });
  });
  return {
    symbol: symbol, kind: index ? 'index' : 'equity',
    atm: base, underlying: base + step / 2,
    strikeStep: step, lotSize: lot,
    session: istDateKey(anchor), stale: false, tickConvention: 'mock',
    asOf: istClock(nowMs), source: 'mock', rows: rows, skipped: []
  };
}

function round2(n) { return Number(n.toFixed(2)); }

function mockPayload(nowMs, symbol) {
  symbol = cleanSymbol(symbol, SYMBOL);
  const index = isIndex(symbol);
  const from = istTimeToEpoch(CANDLE_FROM, nowMs);
  const to = istTimeToEpoch(CANDLE_TO, nowMs);
  const ce = aggregate(mockSeries(148.5, [0, 3.1, -7.3, 8.4, 14.25, 11.4], from), from, to);
  const pe = aggregate(mockSeries(155.0, [0, -4.2, 3.4, -12.1, -22.4, -17.85], from), from, to);
  return {
    symbol: symbol, kind: index ? 'index' : 'equity', expiry: 'MOCK',
    atm: index ? 23600 : 1500, underlying: index ? 23670 : 1512.4,
    strikeStep: STRIKE_STEP || (index ? 100 : 20),
    lotSize: index ? 75 : 500,
    window: { from: CANDLE_FROM, to: CANDLE_TO, tz: 'IST' },
    asOf: istClock(nowMs), source: 'mock', ce, pe
  };
}

/* ------------------------------------------------------------------ */
/* server                                                              */
/* ------------------------------------------------------------------ */

const cache = new Map();

async function cachedFirstCandle(nowMs, fresh, symbol) {
  symbol = cleanSymbol(symbol, SYMBOL);
  const key = `${istDateKey(nowMs)}:${symbol}`;
  if (!fresh && cache.has(key)) return cache.get(key);
  const payload = await firstCandle(nowMs, symbol);
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

/* ------------------------------------------------------------------ */
/* serving the app from this same process (--serve)                    */
/* ------------------------------------------------------------------ */

const STATIC_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.md': 'text/markdown; charset=utf-8'
};

/* Tells the page the helper is its own origin, so it stops guessing from the
   hostname — behind a tunnel there is no ":8123" to append. */
const SAME_ORIGIN_META = '<meta name="nos-helper" content="" />';

function injectHelperMeta(html) {
  if (html.indexOf('name="nos-helper"') !== -1) return html;
  /* After the charset declaration, which has to stay first. */
  const charset = '<meta charset="utf-8" />';
  if (html.indexOf(charset) !== -1) {
    return html.replace(charset, charset + '\n' + SAME_ORIGIN_META);
  }
  return html.replace('<head>', '<head>\n' + SAME_ORIGIN_META);
}

function serveStatic(req, res, url) {
  let pathname;
  try {
    pathname = decodeURIComponent(url.pathname);
  } catch (e) {
    res.writeHead(400, { 'Content-Type': 'text/plain; charset=utf-8' });
    return res.end('bad request');
  }
  pathname = '/' + pathname.replace(/^\/+/, '');
  if (pathname.endsWith('/')) pathname += 'index.html';

  const filePath = path.resolve(APP_ROOT, '.' + pathname);
  if (filePath !== APP_ROOT && !filePath.startsWith(APP_ROOT + path.sep)) {
    res.writeHead(403).end('forbidden');
    return;
  }

  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      return res.end('404 — ' + pathname);
    }
    const ext = path.extname(filePath).toLowerCase();
    let body = data;
    if (ext === '.html') body = Buffer.from(injectHelperMeta(data.toString('utf8')), 'utf8');
    res.writeHead(200, {
      'Content-Type': STATIC_TYPES[ext] || 'application/octet-stream',
      'Cache-Control': 'no-cache'
    });
    res.end(body);
  });
}

/* ------------------------------------------------------------------ */
/* token gate — only active when --token is passed                     */
/* ------------------------------------------------------------------ */

const COOKIE = 'nos_token';

function sameSecret(a, b) {
  const x = Buffer.from(String(a));
  const y = Buffer.from(String(b));
  /* Compare every time even on a length mismatch, so the reply time does not
     leak the length. */
  if (x.length !== y.length) return crypto.timingSafeEqual(x, x) && false;
  return crypto.timingSafeEqual(x, y);
}

function presentedToken(req, url) {
  const q = url.searchParams.get('token');
  if (q) return q;
  const header = req.headers['x-helper-token'];
  if (header) return String(header);
  const cookies = String(req.headers.cookie || '');
  const match = cookies.match(new RegExp('(?:^|;\\s*)' + COOKIE + '=([^;]*)'));
  return match ? decodeURIComponent(match[1]) : '';
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${HOST}:${PORT}`);

  if (req.method === 'OPTIONS') return send(res, 204, {});

  if (TOKEN) {
    if (!sameSecret(presentedToken(req, url), TOKEN)) {
      res.writeHead(401, { 'Content-Type': 'text/plain; charset=utf-8' });
      return res.end('401 — add ?token=… to the URL');
    }
    /* Remember it, so a reload, an Add-to-Home-Screen launch and the page's own
       fetches all carry it without the secret being written into the HTML. */
    if (url.searchParams.get('token')) {
      res.setHeader('Set-Cookie',
        COOKIE + '=' + encodeURIComponent(TOKEN) + '; Path=/; Max-Age=2592000; HttpOnly; SameSite=Lax');
    }
  }

  if (url.pathname === '/health') {
    return send(res, 200, {
      ok: true, mode: MOCK ? 'mock' : 'live',
      symbol: SYMBOL, indices: INDEX_SYMBOLS,
      note: 'any NSE F&O symbol works — pass ?symbol=RELIANCE to /first-candle or /scan',
      ist: istClock(Date.now())
    });
  }

  if (url.pathname === '/scan') {
    try {
      const parseList = function (name, fallback) {
        const raw = url.searchParams.get(name);
        if (!raw) return fallback;
        const out = raw.split(',').map(Number).filter(function (n) { return Number.isFinite(n); });
        return out.length ? out : fallback;
      };
      const opts = {
        symbol: url.searchParams.get('symbol') || SYMBOL,
        tfs: parseList('tfs', [5, 15, 30, 60]).filter(function (n) { return n > 0 && n <= 375; }),
        /* offsets are strike counts, e.g. -1,0,1 — the server turns them into
           prices with the spacing it read off that symbol's own chain */
        offsets: parseList('offsets', [0])
          .map(function (n) { return Math.round(n); })
          .filter(function (n) { return Math.abs(n) <= 10; }).slice(0, 9),
        expiries: Math.min(3, Math.max(1, Number(url.searchParams.get('expiries')) || 1))
      };
      return send(res, 200, await scan(opts, Date.now()));
    } catch (err) {
      return send(res, 502, { error: String(err.message || err), mode: MOCK ? 'mock' : 'live' });
    }
  }

  if (url.pathname === '/first-candle') {
    try {
      const payload = await cachedFirstCandle(
        Date.now(), url.searchParams.get('fresh') === '1', url.searchParams.get('symbol'));
      return send(res, 200, payload);
    } catch (err) {
      return send(res, 502, { error: String(err.message || err), mode: MOCK ? 'mock' : 'live' });
    }
  }

  /* Anything left is the app itself when --serve is on, a 404 otherwise. */
  if (SERVE_APP) return serveStatic(req, res, url);
  return send(res, 404, { error: 'try /health, /first-candle or /scan' });
});

/* ------------------------------------------------------------------ */

async function dump(which) {
  const chain = await optionChain(SYMBOL);
  const spot = chainUnderlying(chain.payload);
  const step = STRIKE_STEP || strikeStepFromChain(chain.payload) || (isIndex(SYMBOL) ? 100 : 0);
  const strike = atmStrike(spot, step);
  const expiry = chain.expiry || chainExpiries(chain.payload)[0] ||
                 (chainRows(chain.payload)[0] || {}).expiryDate;

  if (which.toLowerCase() === 'expiries') {
    var found = await expiryList(SYMBOL);
    console.log('symbol:', SYMBOL, isIndex(SYMBOL) ? '(index)' : '(equity)');
    console.log('source:', found.source);
    console.log('expiries:', found.list.join(', ') || '(none)');
    console.log('calendar guesses would be:',
      (isIndex(SYMBOL) ? upcomingExpiries(6) : upcomingMonthlies(3)).join(', '));
    return;
  }

  if (which.toLowerCase() === 'chain') {
    console.log('endpoint that answered:', chain.url);
    console.log('top-level keys:', Object.keys(chain.payload).join(', '));
    console.log('rows:', chainRows(chain.payload).length, ' spot:', spot, ' expiry:', expiry);
    console.log('strike step read off the chain:', strikeStepFromChain(chain.payload) || '(unknown)');
    console.log('lot size:', await marketLot(SYMBOL));
    console.log('first row:', JSON.stringify(chainRows(chain.payload)[0] || null).slice(0, 600));
    return;
  }

  const { ce, pe } = pickContracts(chain.payload, strike, expiry);
  const leg = which.toUpperCase() === 'PE' ? pe : ce;
  if (!leg) throw new Error(`no ${which} leg at strike ${strike}`);
  console.log(`endpoint ${chain.url}`);
  console.log(`spot ${spot}  atm ${strike}  expiry ${expiry}`);
  console.log(`identifier ${leg && leg.identifier}`);
  const ticks = await tickSeries(leg.identifier);
  console.log(`${ticks.length} ticks; first 3 raw:`, JSON.stringify(ticks.slice(0, 3)));
  if (ticks.length) {
    const conv = detectTickOffset(ticks);
    const shifted = shiftTicks(ticks, conv.offset);
    console.log('detected convention:', conv.convention, '(offset', conv.offset / 60000, 'min)');
    console.log('raw first tick as IST      :', istStamp(ticks[0][0]));
    console.log('corrected first tick as IST:', istStamp(shifted[0][0]));
    console.log('corrected last  tick as IST:', istStamp(shifted[shifted.length - 1][0]));
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

  await step(`Option chain endpoint (${SYMBOL}, ${isIndex(SYMBOL) ? 'index' : 'equity'})`, async () => {
    chain = await optionChain(SYMBOL);
    return `${chainRows(chain.payload).length} strike rows from ${chain.url.replace(BASE, '')}` +
           (chain.expirySource ? ` (expiry via ${chain.expirySource})` : '');
  }, 'v3 needs a valid expiry — without one it answers {}. See the error above for how to supply one.');

  if (!chain) { summarise(results); return results; }

  const spot = chainUnderlying(chain.payload);
  const expiry = chain.expiry || chainExpiries(chain.payload)[0] ||
                 (chainRows(chain.payload)[0] || {}).expiryDate;
  const step0 = STRIKE_STEP || strikeStepFromChain(chain.payload) || (isIndex(SYMBOL) ? 100 : 0);
  const strike = atmStrike(spot, step0);
  let legs = { ce: null, pe: null };

  await step('Strike spacing and lot size', async () => {
    if (!step0) throw new Error('could not read the strike spacing from the chain — pass --strike-step');
    const lot = await marketLot(SYMBOL);
    return `strikes step ${step0}` +
           (STRIKE_STEP ? ' (from --strike-step)' : ' (read off the chain)') +
           `, lot ${Number.isFinite(lot) ? lot : 'unknown'}`;
  }, 'Stock strike spacing varies by symbol and NSE revises it — this reads it live.');

  await step('ATM strike + nearest expiry', async () => {
    if (!Number.isFinite(spot)) throw new Error('no underlying value in the payload');
    if (!expiry) throw new Error('no expiry could be determined');
    legs = pickContracts(chain.payload, strike, expiry);
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
    const conv = detectTickOffset(ticks);
    const shifted = shiftTicks(ticks, conv.offset);
    const anchor = shifted[0][0];
    const from = istTimeToEpoch(CANDLE_FROM, anchor);
    const to = istTimeToEpoch(CANDLE_TO, anchor);

    await step('Tick timestamp convention', async () => {
      return `${conv.convention} — first tick reads ${istStamp(anchor)} IST`;
    });

    await step('Session the feed returned', async () => {
      const session = istDateKey(anchor);
      const today = istDateKey(Date.now());
      if (session !== today) {
        return `${session} — the LAST COMPLETED session, not today (${today})`;
      }
      return `${session} (today)`;
    }, 'Before the open, or on a holiday, NSE serves the previous session. The app labels it.');

    await step('Timestamps land in the 09:15–09:20 IST window', async () => {
      const candle = aggregate(shifted, from, to);
      if (!candle) {
        throw new Error(
          `0 of ${shifted.length} ticks fall in it. Window ${istStamp(from)} → ${CANDLE_TO}; ` +
          `feed ticks run ${istStamp(shifted[0][0])} → ${istStamp(shifted[shifted.length - 1][0])} IST ` +
          '(check the date as well as the clock)'
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
      console.log(`  symbol    ${SYMBOL} (default; ?symbol=RELIANCE etc. per request)`);
      console.log(`  candle    ${CANDLE_FROM}–${CANDLE_TO} IST`);
      console.log(`  listening http://${HOST}:${PORT}`);
      console.log(`  endpoints /health  /first-candle  /scan`);
      if (SERVE_APP) {
        console.log(`  app       served from this same port — open http://${HOST}:${PORT}/`);
      } else {
        console.log('  point the app at this URL under "Auto-fetch" on the Analyser tab.');
      }
      if (TOKEN) {
        console.log(`  token     required — open http://${HOST}:${PORT}/?token=${TOKEN}`);
      } else if (SERVE_APP && HOST !== '127.0.0.1') {
        console.log('  WARNING   no --token set, and this is not bound to localhost only.');
      }
    });
  }
}

module.exports = {
  aggregate, atmStrike, istTimeToEpoch, istClock, istDateKey, readSetCookies,
  chainRows, chainUnderlying, chainExpiries, pickContracts, optionChain,
  detectTickOffset, shiftTicks, istStamp, scan, windowFor, firstCandle,
  formatExpiry, upcomingExpiries, upcomingMonthlies, expiryList, selfCheck, server,
  isIndex, cleanSymbol, strikeStepFromChain, marketLot,
  legacyChainUrl, v3ChainUrl, INDEX_SYMBOLS
};
