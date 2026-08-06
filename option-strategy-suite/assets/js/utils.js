/* Shared helpers. Attached to window.APP so the files load as plain scripts
   and the page also works when opened straight from disk. */
window.APP = window.APP || {};

(function (APP) {
  'use strict';

  function $(id) { return document.getElementById(id); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  /* Parse an input value. Returns NaN for blank/garbage so callers can validate. */
  function num(value) {
    if (value === null || value === undefined) return NaN;
    var s = String(value).trim();
    if (s === '') return NaN;
    var n = Number(s);
    return isFinite(n) ? n : NaN;
  }

  function fmt(n, decimals) {
    if (!isFinite(n)) return '—';
    var d = decimals === undefined ? 2 : decimals;
    return n.toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });
  }

  function pct(fraction, decimals) {
    if (!isFinite(fraction)) return '—';
    return fmt(fraction * 100, decimals === undefined ? 1 : decimals) + '%';
  }

  function clamp(n, lo, hi) { return Math.min(hi, Math.max(lo, n)); }

  /* Round to the nearest tick so displayed levels are actually placeable. */
  function toTick(value, tick) {
    if (!isFinite(value)) return NaN;
    var t = isFinite(tick) && tick > 0 ? tick : 0.05;
    return Math.round(value / t) * t;
  }

  /* Read an OHLC group whose inputs are `<prefix>-o|h|l|c`. */
  function readCandle(prefix) {
    return {
      o: num($(prefix + '-o').value),
      h: num($(prefix + '-h').value),
      l: num($(prefix + '-l').value),
      c: num($(prefix + '-c').value)
    };
  }

  function writeCandle(prefix, candle) {
    ['o', 'h', 'l', 'c'].forEach(function (k) {
      var el = $(prefix + '-' + k);
      if (el) el.value = isFinite(candle[k]) ? String(candle[k]) : '';
    });
  }

  function clearCandle(prefix) {
    ['o', 'h', 'l', 'c'].forEach(function (k) {
      var el = $(prefix + '-' + k);
      if (el) { el.value = ''; el.classList.remove('is-invalid'); }
    });
  }

  /* Validate a candle. Returns [] when usable, otherwise a list of messages.
     Also flags the offending inputs when a prefix is supplied. */
  function validateCandle(candle, label, prefix) {
    var errors = [];
    var bad = {};
    var keys = { o: 'open', h: 'high', l: 'low', c: 'close' };

    Object.keys(keys).forEach(function (k) {
      if (!isFinite(candle[k])) { errors.push(label + ': ' + keys[k] + ' is required.'); bad[k] = true; }
      else if (candle[k] <= 0) { errors.push(label + ': ' + keys[k] + ' must be greater than 0.'); bad[k] = true; }
    });

    if (!errors.length) {
      if (candle.h < candle.l) {
        errors.push(label + ': high cannot be below the low.');
        bad.h = bad.l = true;
      }
      if (candle.h < Math.max(candle.o, candle.c)) {
        errors.push(label + ': high must be the largest of the four values.');
        bad.h = true;
      }
      if (candle.l > Math.min(candle.o, candle.c)) {
        errors.push(label + ': low must be the smallest of the four values.');
        bad.l = true;
      }
      if (candle.h === candle.l) {
        errors.push(label + ': high and low are identical — the candle has no range to work from.');
        bad.h = bad.l = true;
      }
    }

    if (prefix) {
      ['o', 'h', 'l', 'c'].forEach(function (k) {
        var el = $(prefix + '-' + k);
        if (el) el.classList.toggle('is-invalid', !!bad[k]);
      });
    }
    return errors;
  }

  function showErrors(elId, errors) {
    var el = $(elId);
    if (!el) return;
    el.textContent = errors && errors.length ? errors.join(' ') : '';
  }

  /* Descriptive stats shared by all three tools. */
  function candleStats(candle) {
    var range = candle.h - candle.l;
    var body = Math.abs(candle.c - candle.o);
    return {
      range: range,
      body: body,
      bodyRatio: range > 0 ? body / range : 0,
      closePos: range > 0 ? (candle.c - candle.l) / range : 0.5,
      upperWick: range > 0 ? (candle.h - candle.c) / range : 0,
      lowerWick: range > 0 ? (candle.c - candle.l) / range : 0,
      bullish: candle.c > candle.o,
      mid: (candle.h + candle.l) / 2,
      pivot: (candle.h + candle.l + candle.c) / 3
    };
  }

  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  APP.util = {
    $: $, $$: $$, num: num, fmt: fmt, pct: pct, clamp: clamp, toTick: toTick,
    readCandle: readCandle, writeCandle: writeCandle, clearCandle: clearCandle,
    validateCandle: validateCandle, showErrors: showErrors,
    candleStats: candleStats, escapeHtml: escapeHtml
  };
})(window.APP);
