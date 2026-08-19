/* Auto-fill the first-candle values from the local NSE helper.

   The page cannot call nseindia.com itself — NSE sends no CORS headers and
   gates its APIs behind session cookies, so the browser blocks the request
   before it leaves the tab. tools/nse-fetch.js does the handshake on your
   machine and re-serves the candle on localhost; this module talks to that.

   Nothing here is required: if the helper is not running you get a clear
   message and type the four values in as before. */
(function (APP) {
  'use strict';

  var U = APP.util;
  function t(key, vars) { return APP.i18n.t(key, vars); }

  var STORAGE_KEY = 'nifty-option-suite:endpoint';
  function DEFAULT_ENDPOINT() { return APP.util.defaultEndpoint(8123); }

  /* The window the user asked for: fire just after the 09:20 candle closes and
     keep retrying for a minute in case the feed lags. */
  var ARM_AT = { h: 9, m: 21, s: 5 };
  var RETRY_MS = 15000;
  var GIVE_UP = { h: 9, m: 22, s: 30 };

  var armTimer = null;
  var retryTimer = null;
  var lastPayload = null;

  function endpoint() {
    var el = U.$('af-endpoint');
    var value = (el && el.value || '').trim().replace(/\/+$/, '');
    return value || DEFAULT_ENDPOINT();
  }

  function saveEndpoint() {
    try { window.localStorage.setItem(STORAGE_KEY, endpoint()); } catch (e) { /* ignore */ }
  }

  function loadEndpoint() {
    var stored = null;
    try { stored = window.localStorage.getItem(STORAGE_KEY); } catch (e) { /* ignore */ }
    U.$('af-endpoint').value = stored || DEFAULT_ENDPOINT();
  }

  function status(kind, message) {
    var el = U.$('af-status');
    el.className = 'af-status af-' + kind;
    el.textContent = message;
  }

  function clock(date) {
    var pad = function (n) { return String(n).padStart(2, '0'); };
    return pad(date.getHours()) + ':' + pad(date.getMinutes()) + ':' + pad(date.getSeconds());
  }

  function atTime(spec, from) {
    var d = new Date(from);
    d.setHours(spec.h, spec.m, spec.s, 0);
    return d;
  }

  function symbol() {
    var el = U.$('af-symbol');
    return APP.symbols.clean(el && el.value) || 'NIFTY';
  }

  /* ---------- fetching ---------- */
  function request(fresh) {
    var url = endpoint() + '/first-candle?symbol=' + encodeURIComponent(symbol()) +
              (fresh ? '&fresh=1' : '');
    var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timeout = window.setTimeout(function () { if (controller) controller.abort(); }, 12000);

    return window.fetch(url, { signal: controller ? controller.signal : undefined })
      .then(function (res) {
        return res.json().then(function (body) {
          if (!res.ok) throw new Error(body && body.error ? body.error : 'HTTP ' + res.status);
          return body;
        });
      })
      .finally(function () { window.clearTimeout(timeout); });
  }

  function validPayload(p) {
    if (!p || !p.ce || !p.pe) return false;
    return ['o', 'h', 'l', 'c'].every(function (k) {
      return isFinite(p.ce[k]) && p.ce[k] > 0 && isFinite(p.pe[k]) && p.pe[k] > 0;
    });
  }

  function applyPayload(p) {
    U.writeCandle('an-ce', p.ce);
    U.writeCandle('an-pe', p.pe);
    if (isFinite(p.underlying)) {
      U.$('atm-open').value = String(p.underlying);
      APP.analyser.renderAtm();
    }
    /* Contract size belongs to the symbol, not to the user's preferences — a
       RELIANCE candle priced against NIFTY's 75 would be wrong everywhere the
       Trade Signal tab talks about money. */
    lastPayload = p;
    APP.analyser.run();
  }

  function applyLotSize(p) {
    var lot = Number(p && p.lotSize);
    if (!isFinite(lot) || lot <= 0 || lot === APP.config.get().lotSize) return null;
    APP.config.save({ lotSize: lot });
    return lot;
  }

  function fetchNow(fresh, quiet) {
    status('busy', t('af.fetching'));
    return request(fresh).then(function (p) {
      if (!validPayload(p)) throw new Error(t('af.badPayload'));
      applyPayload(p);
      var lot = applyLotSize(p);
      var msg = t('af.filled', {
        symbol: p.symbol || symbol(),
        atm: U.fmt(p.atm, 0),
        time: p.asOf || clock(new Date()),
        source: p.source === 'mock' ? t('af.mockSource') : p.source,
        ticks: (p.ce.ticks || 0) + (p.pe.ticks || 0)
      }) + (lot ? ' ' + t('sym.lotApplied', { lot: lot }) : '');
      /* Before the open, or on a holiday, NSE serves the previous session.
         That must never look like today's candle. */
      if (p.stale && p.session) {
        status('armed', msg + ' ' + t('af.staleSession', { session: p.session }));
      } else {
        status('ok', msg + (p.session ? ' ' + t('af.session', { session: p.session }) : ''));
      }
      return p;
    }).catch(function (err) {
      var msg = String(err && err.message || err);
      /* Nothing listening: say so, then wait for it and retry by itself. */
      var handled = APP.helper.handleError('analyser', err, endpoint(), status, function () {
        fetchNow(fresh, true);
      });
      if (!handled) status('err', t('af.failed', { reason: msg }));
      if (!quiet) throw err;
      return null;
    });
  }

  /* ---------- the 09:21 schedule ---------- */
  function stopRetries() {
    if (retryTimer) { window.clearInterval(retryTimer); retryTimer = null; }
  }

  function runWindow() {
    stopRetries();
    var giveUp = atTime(GIVE_UP, new Date());

    var attempt = function () {
      if (Date.now() > giveUp.getTime()) {
        stopRetries();
        status('err', t('af.windowMissed'));
        disarm(true);
        return;
      }
      fetchNow(true, true).then(function (p) {
        if (p) { stopRetries(); disarm(true); }
      });
    };

    attempt();
    retryTimer = window.setInterval(attempt, RETRY_MS);
  }

  function arm() {
    disarm(true);
    var now = new Date();
    var due = atTime(ARM_AT, now);
    if (due.getTime() <= now.getTime()) due.setDate(due.getDate() + 1);

    armTimer = window.setTimeout(runWindow, due.getTime() - now.getTime());
    U.$('btn-af-arm').hidden = true;
    U.$('btn-af-disarm').hidden = false;
    status('armed', t('af.armed', { time: clock(due) }));
  }

  function disarm(keepStatus) {
    if (armTimer) { window.clearTimeout(armTimer); armTimer = null; }
    stopRetries();
    U.$('btn-af-arm').hidden = false;
    U.$('btn-af-disarm').hidden = true;
    if (!keepStatus) status('idle', t('af.idle'));
  }

  function checkHealth() {
    status('busy', t('af.checking'));
    return window.fetch(endpoint() + '/health')
      .then(function (r) { return r.json(); })
      .then(function (h) {
        status('ok', t('af.healthy', {
          mode: h.mode === 'mock' ? t('af.mockSource') : t('af.liveSource'),
          symbol: h.symbol || '—',
          ist: h.ist || '—'
        }));
      })
      .catch(function (err) {
        if (!APP.helper.handleError('analyser', err, endpoint(), status, checkHealth)) {
          status('err', t('af.helperOffline', { endpoint: endpoint() }));
        }
      });
  }

  function init() {
    loadEndpoint();
    U.$('af-endpoint').addEventListener('change', saveEndpoint);

    APP.symbols.fillDatalist('symbol-list');
    var symEl = U.$('af-symbol');
    symEl.value = APP.symbols.remembered();
    symEl.addEventListener('change', function () {
      symEl.value = APP.symbols.clean(symEl.value) || 'NIFTY';
      APP.symbols.remember(symEl.value);
    });

    U.$('btn-af-now').addEventListener('click', function () { fetchNow(true).catch(function () {}); });
    U.$('btn-af-health').addEventListener('click', checkHealth);
    U.$('btn-af-arm').addEventListener('click', function () { arm(); });
    /* not `addEventListener('click', disarm)` — the click Event would arrive as
       keepStatus and leave the stale "armed" message on screen. */
    U.$('btn-af-disarm').addEventListener('click', function () { disarm(); });
    status('idle', t('af.idle'));
  }

  APP.autofetch = {
    init: init, fetchNow: fetchNow, arm: arm, disarm: disarm, symbol: symbol,
    checkHealth: checkHealth, applyPayload: applyPayload, validPayload: validPayload,
    last: function () { return lastPayload; }
  };
})(window.APP);
