/* Tool 5 — Multi-timeframe / multi-strike / multi-expiry scan.

   No new maths: every row is run through the same APP.analyser.analyse() the
   Option Analyser tab uses, so a scan row and the analyser agree by
   construction. What the scan adds is breadth — the same first candle measured
   over 5, 15, 30 and 60 minutes, across neighbouring strikes and the next
   expiry — plus a read on whether those timeframes agree with each other.

   Every timeframe starts at the session open, so "15m" is 09:15–09:30 and
   "60m" is 09:15–10:15. That is the first candle of the day at that
   timeframe, which is what the strategy is built on. */
(function (APP) {
  'use strict';

  var U = APP.util;
  function t(key, vars) { return APP.i18n.t(key, vars); }
  function money(n) { return '₹' + U.fmt(n); }

  var TFS = [5, 15, 30, 60];
  var last = null;

  /* ---------- run the analyser maths over each row ---------- */
  function evaluate(payload, cfg) {
    var rows = (payload.rows || []).map(function (r) {
      var res = APP.analyser.analyse(r.ce, r.pe, cfg);
      var leg = res.chosen;
      return {
        expiry: r.expiry, strike: r.strike, tf: r.tf,
        ce: r.ce, pe: r.pe,
        side: res.side, confidence: res.confidence, verdict: res.verdict,
        pcr: res.pcr,
        entry: leg.entry, target1: leg.target1, target2: leg.target2,
        target3: leg.target3, stopLoss: leg.stopLoss, range: leg.range
      };
    });

    rows.sort(function (a, b) {
      return a.expiry.localeCompare(b.expiry) || a.strike - b.strike || a.tf - b.tf;
    });

    var best = rows.reduce(function (acc, r) {
      if (r.verdict !== 'yes') return acc;
      return !acc || r.confidence > acc.confidence ? r : acc;
    }, null);

    return { payload: payload, rows: rows, best: best, agreement: agreement(rows) };
  }

  /* Do the timeframes agree, strike by strike? That is the whole point of
     looking at more than one — a side that only appears on 5m is noise. */
  function agreement(rows) {
    var groups = {};
    rows.forEach(function (r) {
      var key = r.expiry + '|' + r.strike;
      (groups[key] = groups[key] || []).push(r);
    });
    return Object.keys(groups).map(function (key) {
      var group = groups[key].slice().sort(function (a, b) { return a.tf - b.tf; });
      var calls = group.filter(function (r) { return r.side === 'call'; }).length;
      var puts = group.length - calls;
      var majority = calls === puts ? null : (calls > puts ? 'call' : 'put');
      var aligned = majority !== null && (majority === 'call' ? calls : puts) === group.length;
      var yes = group.filter(function (r) { return r.verdict === 'yes'; }).length;
      return {
        expiry: group[0].expiry, strike: group[0].strike, group: group,
        calls: calls, puts: puts, majority: majority, aligned: aligned,
        yes: yes, count: group.length
      };
    }).sort(function (a, b) {
      /* fully aligned and confident first — that is what you want to see */
      return (b.aligned - a.aligned) || (b.yes - a.yes) || a.strike - b.strike;
    });
  }

  /* ---------- rendering ---------- */
  function sideChip(side) {
    return '<span class="scan-side is-' + side + '">' +
      U.escapeHtml(t(side === 'call' ? 'sc.call' : 'sc.put')) + '</span>';
  }

  function renderAgreement(result) {
    var el = U.$('sc-agreement');
    el.innerHTML =
      '<div class="card-head"><h3>' + U.escapeHtml(t('sc.agreeTitle')) + '</h3>' +
      '<p class="muted">' + U.escapeHtml(t('sc.agreeDesc')) + '</p></div>' +
      '<div class="agree-grid">' +
        result.agreement.map(function (a) {
          var tfLine = a.group.map(function (r) {
            return '<span class="agree-tf ' + (r.side === a.majority ? 'is-with' : 'is-against') + '">' +
              r.tf + 'm ' + U.escapeHtml(t(r.side === 'call' ? 'sc.callShort' : 'sc.putShort')) +
              ' <b>' + U.fmt(r.confidence, 0) + '%</b></span>';
          }).join('');
          return '<div class="agree-card ' + (a.aligned ? 'is-aligned' : 'is-split') + '">' +
            '<div class="agree-head"><b>' + U.fmt(a.strike, 0) + '</b>' +
              '<span class="muted small">' + U.escapeHtml(a.expiry) + '</span>' +
              (a.aligned
                ? '<span class="agree-tag is-aligned">' + U.escapeHtml(t('sc.aligned', {
                    n: a.count, side: t(a.majority === 'call' ? 'sc.call' : 'sc.put') })) + '</span>'
                : '<span class="agree-tag is-split">' + U.escapeHtml(t('sc.split', {
                    calls: a.calls, puts: a.puts })) + '</span>') +
            '</div>' +
            '<div class="agree-tfs">' + tfLine + '</div>' +
          '</div>';
        }).join('') +
      '</div>';
  }

  function renderTable(result) {
    var rows = result.rows.map(function (r) {
      var isBest = result.best && r === result.best;
      return '<tr class="' + (isBest ? 'is-best' : '') + (r.verdict === 'yes' ? '' : ' is-no') + '">' +
        '<td>' + r.tf + 'm</td>' +
        '<td class="num">' + U.fmt(r.strike, 0) + '</td>' +
        '<td class="exp">' + U.escapeHtml(r.expiry) + '</td>' +
        '<td>' + sideChip(r.side) + '</td>' +
        '<td class="num conf">' + U.fmt(r.confidence, 0) + '%</td>' +
        '<td class="num">' + money(r.entry) + '</td>' +
        '<td class="num t">' + money(r.target1) + '</td>' +
        '<td class="num t">' + money(r.target2) + '</td>' +
        '<td class="num t">' + money(r.target3) + '</td>' +
        '<td class="num sl">' + money(r.stopLoss) + '</td>' +
        '<td class="num">' + U.fmt(r.range) + '</td>' +
        '<td>' + (isBest ? '<span class="best-tag">' + U.escapeHtml(t('sc.best')) + '</span>' : '') + '</td>' +
      '</tr>';
    }).join('');

    U.$('sc-table').innerHTML =
      '<div class="card-head"><h3>' + U.escapeHtml(t('sc.tableTitle')) + '</h3>' +
      '<p class="muted">' + U.escapeHtml(t('sc.tableDesc', { n: result.rows.length })) + '</p></div>' +
      '<div class="table-scroll"><table class="scan-table"><thead><tr>' +
        ['sc.h.tf', 'sc.h.strike', 'sc.h.expiry', 'sc.h.side', 'sc.h.conf', 'sc.h.entry',
         'sc.h.t1', 'sc.h.t2', 'sc.h.t3', 'sc.h.sl', 'sc.h.range', 'sc.h.flag']
          .map(function (k) { return '<th>' + U.escapeHtml(t(k)) + '</th>'; }).join('') +
      '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
      (result.payload.skipped && result.payload.skipped.length
        ? '<p class="muted small" style="margin-top:10px">' +
          U.escapeHtml(t('sc.skipped', { n: result.payload.skipped.length })) + '</p>'
        : '');
  }

  function renderHeadline(result) {
    var p = result.payload;
    var best = result.best;
    var el = U.$('sc-headline');
    el.className = 'card verdict-card ' + (best ? 'an-verdict is-yes' : 'an-verdict is-no');
    el.innerHTML =
      '<div class="an-verdict-top">' +
        '<div class="verdict-badge ' + (best ? (best.side === 'call' ? 'v-hold' : 'v-put') : 'v-partial') + '">' +
          (best
            ? U.escapeHtml(t('sc.bestIs', {
                side: t(best.side === 'call' ? 'an.buyCall' : 'an.buyPut'),
                strike: U.fmt(best.strike, 0), tf: best.tf }))
            : U.escapeHtml(t('sc.noneQualify'))) +
        '</div>' +
        (best ? '<div class="an-confidence"><b>' + U.fmt(best.confidence, 0) + '%</b>' +
          '<span>' + U.escapeHtml(t('an.confidence')) + '</span></div>' : '') +
      '</div>' +
      '<p class="verdict-sub">' + U.escapeHtml(t('sc.context', {
        symbol: p.symbol || 'NIFTY', atm: U.fmt(p.atm, 0),
        session: p.session || '—', rows: result.rows.length
      })) + (p.stale ? ' ' + U.escapeHtml(t('af.staleSession', { session: p.session })) : '') + '</p>' +
      (best
        ? '<div class="entry-strip">' +
            '<span class="entry-label">' + U.escapeHtml(t('an.entryPrice')) + '</span>' +
            '<span class="entry-value">' + money(best.entry) + '</span>' +
            '<span class="entry-side ' + (best.side === 'call' ? 'is-call' : 'is-put') + '">' +
              U.escapeHtml(t(best.side === 'call' ? 'an.buyCall' : 'an.buyPut')) + '</span>' +
          '</div>'
        : '');
  }

  function render(result) {
    renderHeadline(result);
    renderAgreement(result);
    renderTable(result);
    U.$('scan-output').hidden = false;
  }

  /* ---------- controller ---------- */
  function selectedTfs() {
    var out = TFS.filter(function (tf) {
      var el = U.$('sc-tf-' + tf);
      return el && el.checked;
    });
    return out.length ? out : [5];
  }

  /* Counted in strikes, not rupees: the helper reads each symbol's own strike
     spacing off its chain, so ±1 is the neighbouring contract whether NIFTY
     steps in 100s or RELIANCE in 20s. */
  function selectedOffsets() {
    var span = Math.max(0, Math.min(4, Math.round(U.num(U.$('sc-strikes').value)) || 0));
    var out = [];
    for (var i = -span; i <= span; i++) out.push(i);
    return out;
  }

  function symbol() {
    return APP.symbols.clean(U.$('sc-symbol').value) || 'NIFTY';
  }

  /* Contract size is a property of the symbol, not a preference — a scan of
     RELIANCE priced with NIFTY's 75 would be wrong in every money figure. */
  function applyLotSize(payload) {
    var lot = Number(payload && payload.lotSize);
    var cfg = APP.config.get();
    if (!isFinite(lot) || lot <= 0 || lot === cfg.lotSize) return null;
    APP.config.save({ lotSize: lot });
    return lot;
  }

  function status(kind, message) {
    var el = U.$('sc-status');
    el.className = 'af-status af-' + kind;
    el.textContent = message;
  }

  function run() {
    var endpoint = (U.$('sc-endpoint').value || '').trim().replace(/\/+$/, '') || 'http://127.0.0.1:8123';
    var sym = symbol();
    var url = endpoint + '/scan?symbol=' + encodeURIComponent(sym) +
              '&tfs=' + selectedTfs().join(',') +
              '&offsets=' + selectedOffsets().join(',') +
              '&expiries=' + Math.max(1, Math.min(3, Math.round(U.num(U.$('sc-expiries').value)) || 1));

    status('busy', t('sc.running'));
    return window.fetch(url)
      .then(function (res) {
        return res.json().then(function (body) {
          if (!res.ok) throw new Error(body && body.error ? body.error : 'HTTP ' + res.status);
          return body;
        });
      })
      .then(function (payload) {
        if (!payload.rows || !payload.rows.length) {
          /* An empty scan is nearly always one specific thing — a symbol NSE
             lists no options on. Say which, rather than "no rows". */
          var why = String(((payload.skipped || [])[0] || {}).reason || '');
          if (/no option-chain endpoint/.test(why)) {
            throw new Error(t('sym.noChain', { symbol: payload.symbol || sym }));
          }
          throw new Error(why ? why.split('\n')[0] : t('sc.empty'));
        }
        var lot = applyLotSize(payload);
        var result = evaluate(payload, APP.config.get());
        last = result;
        APP.state.scan = result;
        render(result);
        status('ok', t('sc.done', {
          rows: result.rows.length,
          source: payload.source === 'mock' ? t('af.mockSource') : payload.source
        }) + ' ' + t('sym.scanned', {
          symbol: payload.symbol || sym,
          step: payload.strikeStep ? U.fmt(payload.strikeStep, 0) : '—'
        }) + (lot ? ' ' + t('sym.lotApplied', { lot: lot }) : ''));
        return result;
      })
      .catch(function (err) {
        var msg = String(err && err.message || err);
        status('err', /Failed to fetch|NetworkError/i.test(msg)
          ? t('af.helperOffline', { endpoint: endpoint })
          : t('sc.failed', { reason: msg }));
        U.$('scan-output').hidden = true;
        APP.state.scan = null;
        return null;
      });
  }

  function reset() {
    U.$('scan-output').hidden = true;
    APP.state.scan = null;
    last = null;
    status('idle', t('sc.idle'));
  }

  /* Send the best row's candles to the Option Analyser, so the scan is a way
     in to the normal workflow rather than a dead end. */
  function useBest() {
    if (!last || !last.best) return;
    var r = last.best;
    U.writeCandle('an-ce', r.ce);
    U.writeCandle('an-pe', r.pe);
    U.$('atm-open').value = String(last.payload.underlying || r.strike);
    APP.analyser.renderAtm();
    APP.analyser.run();
    APP.tabs.show('analyser');
  }

  function init() {
    U.$('sc-endpoint').value = (function () {
      try { return window.localStorage.getItem('nifty-option-suite:endpoint') || 'http://127.0.0.1:8123'; }
      catch (e) { return 'http://127.0.0.1:8123'; }
    })();

    APP.symbols.fillDatalist('symbol-list');
    var symEl = U.$('sc-symbol');
    symEl.value = APP.symbols.remembered();
    /* Normalise as they leave the field, so "reliance " and "Reliance" both
       become the symbol NSE actually keys on. */
    symEl.addEventListener('change', function () {
      symEl.value = APP.symbols.clean(symEl.value) || 'NIFTY';
      APP.symbols.remember(symEl.value);
      var el = U.$('sc-symbol-note');
      el.textContent = APP.symbols.all().indexOf(symEl.value) === -1
        ? t('sym.unknown', { symbol: symEl.value })
        : t('sym.note');
    });

    U.$('btn-sc-run').addEventListener('click', run);
    U.$('btn-sc-reset').addEventListener('click', reset);
    U.$('btn-sc-use').addEventListener('click', useBest);
    status('idle', t('sc.idle'));
  }

  APP.scan = { init: init, run: run, reset: reset, evaluate: evaluate, agreement: agreement };
})(window.APP);
