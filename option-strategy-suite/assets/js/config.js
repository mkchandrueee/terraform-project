/* Tunable model coefficients + browser persistence.

   The strategy guide fixes *what* each tool outputs (entry / T1 / stop loss,
   hold-vs-book, buy side / zone 1 / target 1) but not the arithmetic. Every
   number that drives those outputs lives here so it can be re-tuned without
   touching the tools themselves. */
(function (APP) {
  'use strict';

  var STORAGE_KEY = 'nifty-option-suite:v1';

  var DEFAULTS = {
    /* Option Analyser */
    entryBufferPct: 0,      // % of range added above the first-candle high
    slBufferPct: 0,         // % of range subtracted below the first-candle low
    t1Multiplier: 1.0,      // Target 1 = entry + (multiplier x range)
    tickSize: 0.05,         // exchange tick; confirmation must clear entry by one

    /* T1 Decision Helper */
    minBodyRatio: 0.50,     // body / range for a candle to count as decisive
    minClosePos: 0.50,      // close must sit in the upper half of its range
    holdThreshold: 70,      // momentum at or above this => HOLD T2
    partialThreshold: 40,   // momentum at or above this => PARTIAL BOOK, below => BOOK NOW
    sideAwareDirection: 0,  // 0 = rising premium is good on both sides (you are long the
                            // option either way); 1 = a put trade wants a falling candle,
                            // reproducing the original helper tool's behaviour

    /* Stoploss Pullback Entry */
    zone1Retrace: 0.382,    // zone 1 = low + (fraction x range)
    zone2Retrace: 0.236,    // deeper liquidity fill
    pullbackTargetMult: 1.0 // target 1 = high + (multiplier x range)
  };

  var state = null;

  function load() {
    var stored = {};
    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) stored = JSON.parse(raw) || {};
    } catch (e) {
      stored = {}; // private mode / disabled storage / corrupt value
    }
    state = {};
    Object.keys(DEFAULTS).forEach(function (k) {
      var v = Number(stored[k]);
      state[k] = isFinite(v) ? v : DEFAULTS[k];
    });
    return state;
  }

  function get() { return state || load(); }

  function save(patch) {
    var cfg = get();
    Object.keys(patch || {}).forEach(function (k) {
      if (!(k in DEFAULTS)) return;
      var v = Number(patch[k]);
      if (isFinite(v)) cfg[k] = v;
    });
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
    } catch (e) { /* nothing persistable — keep the in-memory values */ }
    return cfg;
  }

  function reset() {
    state = null;
    try { window.localStorage.removeItem(STORAGE_KEY); } catch (e) { /* ignore */ }
    return load();
  }

  APP.config = { DEFAULTS: DEFAULTS, get: get, save: save, reset: reset, load: load };
})(window.APP);
