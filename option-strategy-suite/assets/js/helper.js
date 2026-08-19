/* Staying connected to the local helper.

   "No helper at 127.0.0.1:8123" was a dead end: the message told you to start a
   process, and nothing happened afterwards even once you had. Two things fix
   that, and neither is a button.

   The helper itself no longer exits on an unhandled error, and the Windows
   launcher restarts it if it ever does — see tools/nse-fetch.js and
   run-helper.cmd. This module handles the other half: when a request fails
   because nothing is listening, it polls /health in the background and re-runs
   whatever failed the moment the helper answers again. Closing the laptop lid,
   restarting the helper mid-session, or starting the app before the helper all
   heal on their own. */
(function (APP) {
  'use strict';

  var U = APP.util;
  function t(key, vars) { return APP.i18n.t(key, vars); }

  /* One watcher per tab, keyed, so two tabs failing do not fight each other. */
  var watchers = {};

  /* A fetch that never reached a server, as opposed to one that answered with
     an error. Only the former is worth waiting on. */
  function isOffline(err) {
    var msg = String(err && err.message || err || '');
    return /Failed to fetch|NetworkError|ERR_CONNECTION|Load failed|abort|TypeError/i.test(msg);
  }

  function stop(key) {
    var w = watchers[key];
    if (!w) return;
    if (w.timer) window.clearTimeout(w.timer);
    delete watchers[key];
  }

  function stopAll() {
    Object.keys(watchers).forEach(stop);
  }

  /**
   * Begin waiting for the helper to come back.
   *
   * @param {string}   key       one per tab
   * @param {string}   endpoint  base URL to poll
   * @param {function} onStatus  (kind, message) — render into that tab's status line
   * @param {function} onBack    called once, when /health answers again
   */
  function watch(key, endpoint, onStatus, onBack) {
    stop(key);
    var attempt = 0;

    function tick() {
      attempt += 1;
      var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
      var timeout = window.setTimeout(function () { if (controller) controller.abort(); }, 4000);

      window.fetch(endpoint + '/health', { signal: controller ? controller.signal : undefined })
        .then(function (res) { return res.ok ? res.json() : Promise.reject(new Error('HTTP ' + res.status)); })
        .then(function () {
          window.clearTimeout(timeout);
          stop(key);
          onStatus('ok', t('hp.back'));
          /* Re-run what failed, so the user does not have to notice at all. */
          try { onBack(); } catch (e) { /* the tab will show its own error */ }
        })
        .catch(function () {
          window.clearTimeout(timeout);
          if (!watchers[key]) return;          /* stopped while in flight */
          onStatus('busy', t('hp.waiting', { endpoint: endpoint, n: attempt }));
          /* 2s, then easing out to 15s — quick enough to catch a restart, slow
             enough not to hammer a machine where the helper is simply not run. */
          var delay = Math.min(2000 * Math.pow(1.4, attempt - 1), 15000);
          watchers[key].timer = window.setTimeout(tick, delay);
        });
    }

    watchers[key] = { timer: null };
    onStatus('busy', t('hp.waiting', { endpoint: endpoint, n: 1 }));
    watchers[key].timer = window.setTimeout(tick, 1200);
  }

  /**
   * The standard failure branch for every tab that talks to the helper.
   * Returns the message to show; starts a watcher when the helper is missing.
   */
  function handleError(key, err, endpoint, onStatus, onBack) {
    if (isOffline(err)) {
      onStatus('err', t('af.helperOffline', { endpoint: endpoint }));
      watch(key, endpoint, onStatus, onBack);
      return true;
    }
    return false;
  }

  APP.helper = {
    isOffline: isOffline,
    watch: watch,
    stop: stop,
    stopAll: stopAll,
    handleError: handleError,
    watching: function (key) { return !!watchers[key]; }
  };
})(window.APP);
