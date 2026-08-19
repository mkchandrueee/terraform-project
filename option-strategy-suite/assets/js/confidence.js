/* Confidence Scan — the whole board, ranked.

   Every other tab starts from a symbol you have already chosen. This one starts
   from the opposite end: run the same candle reading across all five F&O indices
   and all fifty NIFTY 50 stocks, and let the ranking tell you which ones are
   worth looking at at all.

   The maths is the analyser's, unchanged, via APP.swing.readCandle — the
   bullish reading is APP.analyser.analyseSide called verbatim and the bearish
   one is its mirror. Nothing new is invented here; this is breadth.

   WHAT 100% MEANS, because the number invites a wrong reading:
   confidence = 20 × (direction) + 40 × body ÷ range + 40 × close position.
   100% is a candle that opened at its low, closed at its high and is all body.
   It describes the SHAPE OF ONE CANDLE and nothing else. It is not a 100%
   chance of profit, not a probability, and carries no claim about what happens
   next. A 100% row is a clean-looking candle worth a second look — that is the
   whole of it, and the UI says so where the number appears. */
(function (APP) {
  'use strict';

  var U = APP.util;
  function t(key, vars) { return APP.i18n.t(key, vars); }
  function money(n) { return '₹' + U.fmt(n); }

  var last = null;

  /* ---------- evaluate the board ---------- */
  function evaluate(payload, cfg, opts) {
    var min = opts && isFinite(opts.min) ? opts.min : 80;
    var only = (opts && opts.universe) || 'all';

    var rows = (payload.rows || [])
      .filter(function (r) { return only === 'all' || r.kind === only; })
      .map(function (r) {
        var read = APP.swing.readCandle(r, cfg);
        var leg = read.chosen;
        var risk = Math.abs(leg.entry - leg.stopLoss);
        return {
          symbol: r.symbol, kind: r.kind, candle: r,
          pChange: r.pChange,
          side: read.side, confidence: read.confidence, verdict: read.verdict,
          entry: leg.entry, target1: leg.target1, target2: leg.target2,
          target3: leg.target3, stopLoss: leg.stopLoss, range: leg.range,
          risk: risk,
          rr: risk > 0 ? Math.abs(leg.target2 - leg.entry) / risk : NaN
        };
      });

    rows.sort(function (a, b) {
      return b.confidence - a.confidence || a.symbol.localeCompare(b.symbol);
    });

    var qualifying = rows.filter(function (r) { return r.confidence >= min; });
    var perfect = rows.filter(function (r) { return r.confidence >= 99.995; });

    return {
      payload: payload, cfg: cfg, min: min, universe: only,
      rows: rows, qualifying: qualifying, perfect: perfect,
      best: qualifying[0] || null,
      longs: qualifying.filter(function (r) { return r.side === 'long'; }).length,
      shorts: qualifying.filter(function (r) { return r.side === 'short'; }).length
    };
  }

  /* ---------- rendering ---------- */
  function sideChip(side) {
    return '<span class="scan-side is-' + (side === 'long' ? 'call' : 'put') + '">' +
      U.escapeHtml(t(side === 'long' ? 'sw.long' : 'sw.short')) + '</span>';
  }

  function renderHeadline(result) {
    var el = U.$('cs-headline');
    var n = result.qualifying.length;
    var p = result.perfect.length;
    el.className = 'card verdict-card ' + (n ? 'an-verdict is-yes' : 'an-verdict is-no');

    el.innerHTML =
      '<div class="an-verdict-top">' +
        '<div class="verdict-badge ' + (n ? 'v-hold' : 'v-partial') + '">' +
          U.escapeHtml(n
            ? t('cs.found', { n: n, min: U.fmt(result.min, 0) })
            : t('cs.foundNone', { min: U.fmt(result.min, 0) })) +
        '</div>' +
        (n ? '<div class="an-confidence"><b>' + U.fmt(result.rows[0].confidence, 0) + '%</b>' +
          '<span>' + U.escapeHtml(t('cs.topScore')) + '</span></div>' : '') +
      '</div>' +
      '<p class="verdict-sub">' + U.escapeHtml(t('cs.context', {
        scanned: result.rows.length,
        index: result.payload.counts.index,
        equity: result.payload.counts.equity,
        longs: result.longs, shorts: result.shorts,
        time: result.payload.asOf
      })) + '</p>' +
      (p ? '<div class="perfect-strip">' +
             '<span class="perfect-label">' + U.escapeHtml(t('cs.perfectLabel', { n: p })) + '</span>' +
             result.perfect.map(function (r) {
               return '<span class="perfect-chip is-' + r.side + '">' + U.escapeHtml(r.symbol) + '</span>';
             }).join('') +
           '</div>' : '') +
      /* The number invites "100% = certain". Say plainly that it is not. */
      '<p class="muted small warn-note">' + U.escapeHtml(t('cs.meaning')) + '</p>' +
      (result.payload.live
        ? '<p class="muted small warn-note">' + U.escapeHtml(t('cs.liveWarn', {
            session: result.payload.session })) + '</p>'
        : '');
  }

  function renderTable(result) {
    var shown = result.qualifying.length ? result.qualifying : result.rows.slice(0, 15);

    var rows = shown.map(function (r) {
      var isPerfect = r.confidence >= 99.995;
      return '<tr class="' + (isPerfect ? 'is-best' : '') + (r.confidence >= result.min ? '' : ' is-no') + '">' +
        '<td><b>' + U.escapeHtml(r.symbol) + '</b>' +
          (r.kind === 'index' ? ' <span class="kind-tag">' + U.escapeHtml(t('sw.kindIndex')) + '</span>' : '') + '</td>' +
        '<td>' + sideChip(r.side) + '</td>' +
        '<td class="num conf">' + U.fmt(r.confidence, 0) + '%</td>' +
        '<td class="num">' + (isFinite(r.pChange) ? U.fmt(r.pChange, 2) + '%' : '—') + '</td>' +
        '<td class="num">' + money(r.entry) + '</td>' +
        '<td class="num t">' + money(r.target1) + '</td>' +
        '<td class="num t">' + money(r.target2) + '</td>' +
        '<td class="num t">' + money(r.target3) + '</td>' +
        '<td class="num sl">' + money(r.stopLoss) + '</td>' +
        '<td class="num">' + U.fmt(r.range) + '</td>' +
        '<td class="num">' + (isFinite(r.rr) ? U.fmt(r.rr, 2) + '×' : '—') + '</td>' +
      '</tr>';
    }).join('');

    U.$('cs-table').innerHTML =
      '<div class="card-head"><h3>' + U.escapeHtml(t('cs.tableTitle')) + '</h3>' +
      '<p class="muted">' + U.escapeHtml(result.qualifying.length
        ? t('cs.tableDesc', { n: shown.length, min: U.fmt(result.min, 0) })
        : t('cs.tableDescNone', { n: shown.length })) + '</p></div>' +
      '<div class="table-scroll"><table class="scan-table"><thead><tr>' +
        ['cs.h.symbol', 'sc.h.side', 'sc.h.conf', 'cs.h.day', 'sc.h.entry',
         'sc.h.t1', 'sc.h.t2', 'sc.h.t3', 'sc.h.sl', 'sc.h.range', 'sw.h.rr']
          .map(function (k) { return '<th>' + U.escapeHtml(t(k)) + '</th>'; }).join('') +
      '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
      '<p class="muted small" style="margin-top:10px">' + U.escapeHtml(t('sw.priceNote')) + '</p>' +
      (result.payload.skipped && result.payload.skipped.length
        ? '<p class="muted small">' + U.escapeHtml(t('cs.skipped', {
            detail: result.payload.skipped.map(function (s) { return s.group + ': ' + s.reason; }).join('; ')
          })) + '</p>'
        : '');
  }

  function render(result) {
    renderHeadline(result);
    renderTable(result);
    U.$('confidence-output').hidden = false;
  }

  /* ---------- controller ---------- */
  function status(kind, message) {
    var el = U.$('cs-status');
    el.className = 'af-status af-' + kind;
    el.textContent = message;
  }

  function options() {
    return {
      min: U.clamp(Math.round(U.num(U.$('cs-min').value)) || 0, 0, 100),
      universe: U.$('cs-universe').value || 'all'
    };
  }

  function run() {
    var endpoint = (U.$('cs-endpoint').value || '').trim().replace(/\/+$/, '') || U.defaultEndpoint(8123);

    status('busy', t('cs.running'));
    return window.fetch(endpoint + '/universe')
      .then(function (res) {
        return res.json().then(function (body) {
          if (!res.ok) throw new Error(body && body.error ? body.error : 'HTTP ' + res.status);
          return body;
        });
      })
      .then(function (payload) {
        if (!payload.rows || !payload.rows.length) throw new Error(t('cs.empty'));
        var result = evaluate(payload, APP.config.get(), options());
        last = result;
        APP.state.confidence = result;
        render(result);
        status('ok', t('cs.done', {
          scanned: result.rows.length,
          n: result.qualifying.length,
          source: payload.source === 'mock' ? t('af.mockSource') : payload.source
        }));
        return result;
      })
      .catch(function (err) {
        var msg = String(err && err.message || err);
        if (!APP.helper.handleError('confidence', err, endpoint, status, run)) {
          status('err', t('cs.failed', { reason: msg }));
        }
        U.$('confidence-output').hidden = true;
        APP.state.confidence = null;
        return null;
      });
  }

  function reset() {
    U.$('confidence-output').hidden = true;
    APP.state.confidence = null;
    last = null;
    status('idle', t('cs.idle'));
  }

  /* Same hand-off rule as the swing scan: these are share prices, so the honest
     next step is the ATM selector, not a premium-based tool. */
  function useBest() {
    if (!last || !last.best) return;
    var r = last.best;
    U.$('atm-open').value = String(r.candle.c);
    U.$('af-symbol').value = r.symbol;
    U.$('sc-symbol').value = r.symbol;
    APP.symbols.remember(r.symbol);
    APP.analyser.renderAtm();
    APP.tabs.show('analyser');
  }

  function init() {
    U.$('cs-endpoint').value = (function () {
      try { return window.localStorage.getItem('nifty-option-suite:endpoint') || U.defaultEndpoint(8123); }
      catch (e) { return U.defaultEndpoint(8123); }
    })();
    U.$('btn-cs-run').addEventListener('click', run);
    U.$('btn-cs-reset').addEventListener('click', reset);
    U.$('btn-cs-use').addEventListener('click', useBest);
    status('idle', t('cs.idle'));
  }

  APP.confidence = { init: init, run: run, reset: reset, evaluate: evaluate };
})(window.APP);
