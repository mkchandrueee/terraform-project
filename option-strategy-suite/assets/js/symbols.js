/* Tradable underlyings — the five F&O indices and the NIFTY 50 stocks.

   This list only fills the picker's suggestions. The field itself stays free
   text and the helper accepts any NSE F&O symbol, so an index reconstitution
   (which happens twice a year) makes the list stale, never wrong: type the new
   name and it works. Nothing here is used in any calculation. */
(function (APP) {
  'use strict';

  var INDICES = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50'];

  /* NIFTY 50 constituents. Trading symbols, not company names — that is what
     NSE's option-chain endpoint keys on. */
  var STOCKS = [
    'ADANIENT', 'ADANIPORTS', 'APOLLOHOSP', 'ASIANPAINT', 'AXISBANK',
    'BAJAJ-AUTO', 'BAJAJFINSV', 'BAJFINANCE', 'BEL', 'BHARTIARTL',
    'CIPLA', 'COALINDIA', 'DRREDDY', 'EICHERMOT', 'ETERNAL',
    'GRASIM', 'HCLTECH', 'HDFCBANK', 'HDFCLIFE', 'HEROMOTOCO',
    'HINDALCO', 'HINDUNILVR', 'ICICIBANK', 'INDUSINDBK', 'INFY',
    'ITC', 'JIOFIN', 'JSWSTEEL', 'KOTAKBANK', 'LT',
    'M&M', 'MARUTI', 'NESTLEIND', 'NTPC', 'ONGC',
    'POWERGRID', 'RELIANCE', 'SBILIFE', 'SBIN', 'SHRIRAMFIN',
    'SUNPHARMA', 'TATACONSUM', 'TATAMOTORS', 'TATASTEEL', 'TCS',
    'TECHM', 'TITAN', 'TRENT', 'ULTRACEMCO', 'WIPRO'
  ];

  function isIndex(symbol) {
    return INDICES.indexOf(String(symbol || '').toUpperCase()) !== -1;
  }

  /* Same rule the helper applies, so the field cannot send something the
     server will only reject after a round trip. */
  function clean(raw) {
    return String(raw == null ? '' : raw).trim().toUpperCase().replace(/[^A-Z0-9&\-]/g, '');
  }

  /** Fills a <datalist> once; the input keeps accepting anything typed. */
  function fillDatalist(id) {
    var el = document.getElementById(id);
    if (!el || el.childElementCount) return;
    el.innerHTML =
      INDICES.map(function (s) { return '<option value="' + s + '"></option>'; }).join('') +
      STOCKS.map(function (s) { return '<option value="' + s + '"></option>'; }).join('');
  }

  /* Both symbol fields share one remembered value — picking RELIANCE on the
     Scan tab and then fetching on the Analyser tab should not silently go back
     to NIFTY. */
  var KEY = 'nifty-option-suite:symbol';

  function remembered() {
    try { return clean(window.localStorage.getItem(KEY)) || 'NIFTY'; }
    catch (e) { return 'NIFTY'; }
  }

  function remember(symbol) {
    try { window.localStorage.setItem(KEY, clean(symbol) || 'NIFTY'); } catch (e) { /* private mode */ }
  }

  APP.symbols = {
    INDICES: INDICES,
    STOCKS: STOCKS,
    all: function () { return INDICES.concat(STOCKS); },
    isIndex: isIndex,
    clean: clean,
    fillDatalist: fillDatalist,
    remembered: remembered,
    remember: remember
  };
})(window.APP);
