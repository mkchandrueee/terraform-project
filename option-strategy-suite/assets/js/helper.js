/* Staying connected to the local helper.

   When a request fails because nothing is listening, this polls /health in the
   background and re-runs whatever failed the moment the helper answers, so
   starting the app before the helper — or restarting the helper mid-session —
   heals without a click.

   Two rules keep that from becoming a worse problem than the one it solves:

   1. Only a genuine network failure counts. Classifying by message is coarse,
      so the pattern is deliberately narrow: a bug in this app throwing a
      TypeError must NOT be read as "the helper is down", because then the
      retry throws it again, and the watcher restarts, forever.

   2. Waiting is bounded, and never hides what to do. If the helper is simply
      not running, no amount of polling will change that — the instruction to
      start it stays on screen the whole time, and the polling gives up rather
      than spinning silently. */
(function (APP) {
  'use strict';

  var U = APP.util;
  function t(key, vars) { return APP.i18n.t(key, vars); }

  /* One watcher per tab, keyed, so two tabs failing do not fight each other. */
  var watchers = {};
  /* Consecutive automatic recoveries that failed again, per tab. */
  var retries = {};

  var MAX_POLLS = 20;      /* ~3 minutes, then stop and leave the instruction up */
  var MAX_RETRIES = 2;     /* auto-retries that fail again before giving up */

  /**
   * A request that never reached a server, as opposed to one that answered with
   * an error. Only the former is worth waiting on.
   *
   * Deliberately NOT matching a bare "TypeError": every browser words a failed
   * fetch differently, but a TypeError is also what a bug in this file looks
   * like, and treating our own bug as an offline helper produces an endless
   * retry loop that says "waiting for the helper" and never stops.
   */
  function isOffline(err) {
    var msg = String(err && err.message || err || '');
    return /Failed to fetch/i.test(msg)              /* Chrome, Edge */
        || /NetworkError/i.test(msg)                 /* Firefox */
        || /Load failed/i.test(msg)                  /* Safari */
        || /ERR_CONNECTION|ECONNREFUSED/i.test(msg)
        || /aborted|AbortError/i.test(msg);          /* our own timeout */
  }

  function stop(key) {
    var w = watchers[key];
    if (!w) return;
    if (w.timer) window.clearTimeout(w.timer);
    delete watchers[key];
  }

  function stopAll() { Object.keys(watchers).forEach(stop); }

  /** A tab calls this when a request succeeds, so the give-up counter resets. */
  function ok(key) {
    retries[key] = 0;
    stop(key);
  }

  /**
   * Poll until the helper answers, then re-run what failed.
   *
   * @param {string}   key       one per tab
   * @param {string}   endpoint  base URL to poll
   * @param {function} onStatus  (kind, message) — render into that tab's status line
   * @param {function} onBack    called once, when /health answers again
   */
  function watch(key, endpoint, onStatus, onBack) {
    stop(key);
    var attempt = 0;

    function giveUp() {
      stop(key);
      /* Back to the instruction. Polling has proved nothing is there. */
      onStatus('err', t('af.helperOffline', { endpoint: endpoint }));
    }

    function tick() {
      attempt += 1;
      var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
      var timeout = window.setTimeout(function () { if (controller) controller.abort(); }, 4000);

      window.fetch(endpoint + '/health', { signal: controller ? controller.signal : undefined })
        .then(function (res) { return res.ok ? res.json() : Promise.reject(new Error('HTTP ' + res.status)); })
        .then(function () {
          window.clearTimeout(timeout);
          stop(key);
          retries[key] = (retries[key] || 0) + 1;
          if (retries[key] > MAX_RETRIES) {
            /* The helper answers /health but the actual work keeps failing.
               Retrying again would just loop; show the real problem instead. */
            retries[key] = 0;
            onStatus('err', t('hp.retryExhausted'));
            return;
          }
          onStatus('ok', t('hp.back'));
          try { onBack(); } catch (e) { onStatus('err', String(e && e.message || e)); }
        })
        .catch(function () {
          window.clearTimeout(timeout);
          if (!watchers[key]) return;          /* stopped while in flight */
          if (attempt >= MAX_POLLS) return giveUp();
          onStatus('busy', t('hp.waiting', {
            endpoint: endpoint, n: attempt, max: MAX_POLLS
          }));
          /* 2s easing out to 15s — quick enough to catch a restart, slow enough
             not to hammer a machine where the helper is simply not running. */
          var delay = Math.min(2000 * Math.pow(1.4, attempt - 1), 15000);
          watchers[key].timer = window.setTimeout(tick, delay);
        });
    }

    watchers[key] = { timer: null };
    onStatus('busy', t('hp.waiting', { endpoint: endpoint, n: 1, max: MAX_POLLS }));
    watchers[key].timer = window.setTimeout(tick, 1200);
  }

  /**
   * The standard failure branch for every tab that talks to the helper.
   * Returns true if it handled the error (and started waiting).
   */
  function handleError(key, err, endpoint, onStatus, onBack) {
    if (!isOffline(err)) return false;
    if ((retries[key] || 0) > MAX_RETRIES) {
      /* Already tried and failed repeatedly — do not start another watcher. */
      retries[key] = 0;
      onStatus('err', t('af.helperOffline', { endpoint: endpoint }));
      return true;
    }
    watch(key, endpoint, onStatus, onBack);
    return true;
  }

  APP.helper = {
    isOffline: isOffline,
    watch: watch,
    stop: stop,
    stopAll: stopAll,
    ok: ok,
    handleError: handleError,
    watching: function (key) { return !!watchers[key]; }
  };
})(window.APP);
