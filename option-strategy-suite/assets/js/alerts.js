/* Notifications and the 5-minute candle-close scheduler.

   Two honest limits, stated in the UI as well: the page must stay open for a
   reminder to fire, and system notifications only appear once the browser has
   granted permission. When either is unavailable everything still works — the
   alert lands in the in-page log instead. */
(function (APP) {
  'use strict';

  var U = APP.util;
  function t(key, vars) { return APP.i18n.t(key, vars); }

  var timer = null;
  var fired = 0;
  var log = [];

  function supported() { return typeof window.Notification !== 'undefined'; }
  function permission() { return supported() ? window.Notification.permission : 'unsupported'; }

  /* ---------- next 5-minute boundary, plus a second of settle time ---------- */
  function nextBoundary(from, minutes) {
    var step = (minutes || 5) * 60000;
    var base = from ? from.getTime() : Date.now();
    var next = Math.ceil((base + 1000) / step) * step;
    return new Date(next + 1000);
  }

  function clockText(date) {
    return String(date.getHours()).padStart(2, '0') + ':' + String(date.getMinutes()).padStart(2, '0');
  }

  /* ---------- delivery ---------- */
  function push(title, body, tag) {
    log.unshift({ time: clockText(new Date()), title: title, body: body });
    if (log.length > 12) log.pop();
    renderLog();

    if (supported() && window.Notification.permission === 'granted') {
      try {
        new window.Notification(title, { body: body, tag: tag || 'nifty-suite', lang: APP.i18n.get() });
      } catch (e) { /* some browsers require a service worker; the log still has it */ }
    }
  }

  /* ---------- signal notification ---------- */
  function signalText(result) {
    var m = result.m;
    return t('al.signalBody', {
      entry: '₹' + U.fmt(result.inputs.entry),
      sl: '₹' + U.fmt(result.inputs.sl),
      t2: '₹' + U.fmt(result.inputs.t2),
      win: U.fmt(result.winPct, 0),
      profit: '₹' + U.fmt(m.profitT2, 0),
      ev: '₹' + U.fmt(m.ev, 0),
      rr: U.fmt(m.rr, 2)
    });
  }

  function onSignal(result) {
    if (!U.$('al-auto').checked) return;
    var sideLabel = t(result.side === 'put' ? 'sg.putTrade' : 'sg.callTrade');
    push(result.headline + ' — ' + sideLabel, signalText(result), 'signal');
  }

  function notifyNow() {
    var result = APP.state.signal;
    if (!result) { push(t('al.noSignal'), t('al.noSignalBody'), 'signal'); return; }
    var sideLabel = t(result.side === 'put' ? 'sg.putTrade' : 'sg.callTrade');
    push(result.headline + ' — ' + sideLabel, signalText(result), 'signal');
  }

  /* ---------- candle-close reminders ---------- */
  function schedule() {
    var due = nextBoundary();
    U.$('al-next').textContent = t('al.nextAt', { time: clockText(due) });
    timer = window.setTimeout(function () {
      fired += 1;
      var result = APP.state.signal;
      var body = result
        ? t('al.candleBodyLevels', { entry: '₹' + U.fmt(result.inputs.entry), t1: '₹' + U.fmt(result.inputs.t1) })
        : t('al.candleBody');
      push(t('al.candleTitle', { time: clockText(new Date()) }), body, 'candle');

      var limit = Number(U.$('al-count').value) || 0;
      if (limit > 0 && fired >= limit) { stop(); return; }
      schedule();
    }, Math.max(1000, due.getTime() - Date.now()));
  }

  function start() {
    if (timer) return;
    fired = 0;
    U.$('btn-al-start').hidden = true;
    U.$('btn-al-stop').hidden = false;
    schedule();
  }

  function stop() {
    if (timer) { window.clearTimeout(timer); timer = null; }
    U.$('btn-al-start').hidden = false;
    U.$('btn-al-stop').hidden = true;
    U.$('al-next').textContent = t('al.stopped');
  }

  /* ---------- permission ---------- */
  function renderPermission() {
    var state = permission();
    var el = U.$('al-permission');
    el.className = 'perm perm-' + state;
    el.textContent = t('al.perm.' + state);
    U.$('btn-al-enable').hidden = (state === 'granted' || state === 'unsupported');
  }

  function requestPermission() {
    if (!supported()) { renderPermission(); return; }
    try {
      var res = window.Notification.requestPermission(function () { renderPermission(); });
      if (res && typeof res.then === 'function') res.then(renderPermission).catch(renderPermission);
    } catch (e) {
      renderPermission();
    }
  }

  /* ---------- log ---------- */
  function renderLog() {
    var el = U.$('al-log');
    if (!log.length) {
      el.innerHTML = '<li class="log-empty muted small">' + U.escapeHtml(t('al.logEmpty')) + '</li>';
      return;
    }
    el.innerHTML = log.map(function (entry) {
      return '<li class="log-item">' +
        '<span class="log-time">' + U.escapeHtml(entry.time) + '</span>' +
        '<span class="log-body"><b>' + U.escapeHtml(entry.title) + '</b>' +
          '<span>' + U.escapeHtml(entry.body) + '</span></span>' +
      '</li>';
    }).join('');
  }

  function init() {
    U.$('btn-al-enable').addEventListener('click', requestPermission);
    U.$('btn-al-notify').addEventListener('click', notifyNow);
    U.$('btn-al-start').addEventListener('click', start);
    U.$('btn-al-stop').addEventListener('click', stop);
    renderPermission();
    renderLog();
    U.$('al-next').textContent = t('al.stopped');
  }

  APP.alerts = {
    init: init, onSignal: onSignal, notifyNow: notifyNow,
    start: start, stop: stop, nextBoundary: nextBoundary,
    renderLog: renderLog, renderPermission: renderPermission
  };
})(window.APP);
