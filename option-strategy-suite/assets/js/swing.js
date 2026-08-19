/* Swing scan — the same maths on hourly, daily, weekly and monthly candles.

   The intraday scan asks "what did the first candle of the day do?". This asks
   "what did the last COMPLETED candle at this timeframe do?", which is the
   question a short-term or positional read is built on. 1h picks up intraday
   momentum, 1d a swing, 1w and 1M a position.

   Two things genuinely differ from the intraday scan, and both are about the
   instrument rather than the formula:

   1. These are the UNDERLYING's price candles, not an option premium's. NSE
      publishes no daily history worth reading for an individual option
      contract — each one is young, thin, and stops existing at expiry. So a
      stock's own bars drive the read, and the levels come out in share prices.

   2. There is no CE candle and no PE candle to compare, so the side is decided
      by reading the one candle two ways — bullish and bearish — and taking the
      higher score. The bullish reading IS APP.analyser.analyseSide, called
      unchanged. The bearish reading is its mirror, written out below.

   No coefficient is re-tuned. The single substitution is the target-step floor,
   which is 16 rupees of premium upstairs and a percentage of price here —
   see config.js for why. */
(function (APP) {
  'use strict';

  var U = APP.util;
  function t(key, vars) { return APP.i18n.t(key, vars); }
  function money(n) { return '₹' + U.fmt(n); }
  function round2(n) { return Number(n.toFixed(2)); }

  var TFS = ['1h', '1d', '1w', '1M'];
  var last = null;

  /* ---------- the two readings of one candle ---------- */

  /* A price-scale floor in place of the premium-scale ₹16. */
  function priceCfg(candle, cfg) {
    var floor = Math.abs(candle.c) * (cfg.swingMinStepPct / 100);
    var out = {};
    for (var k in cfg) { if (Object.prototype.hasOwnProperty.call(cfg, k)) out[k] = cfg[k]; }
    out.minTargetStep = floor;
    return out;
  }

  /* Long: the analyser's own function, unmodified. */
  function longRead(candle, cfg) {
    var r = APP.analyser.analyseSide(candle, priceCfg(candle, cfg));
    r.direction = 'long';
    return r;
  }

  /**
   * Short: the same formulas reflected. Every constant is the one above —
   * entry steps the same 0.5% off the close but downward, the step is the same
   * 0.8 × range with the same floor, the targets are the same 1 / 2 / 3.5
   * multiples, and the stop sits the same 0.3 × range beyond the extreme. Only
   * the sign of "away from the close" changes.
   */
  function shortRead(candle, cfg) {
    var c = priceCfg(candle, cfg);
    var s = U.candleStats(candle);
    var range = s.range;

    var entry = round2(candle.c * (1 - c.entryPremiumPct / 100));
    var step = Math.max(c.targetStepMult * range, c.minTargetStep);
    var target1 = round2(entry - step);
    var target2 = round2(entry - c.t2Mult * step);
    var target3 = round2(entry - c.t3Mult * step);
    var stopLoss = round2(candle.h + c.slRangeMult * range);

    /* Mirrored confidence: a bearish candle, a strong body, and a close near
       the low — the same three terms with the same 20 / 40 / 40 weights. */
    var confidence = U.clamp(
      20 * (candle.c < candle.o ? 1 : 0) + 40 * s.bodyRatio + 40 * (1 - s.closePos), 0, 100
    );

    return {
      candle: candle, stats: s, range: range, step: step,
      entry: entry, target1: target1, target2: target2, target3: target3,
      stopLoss: stopLoss, risk: stopLoss - entry,
      confidence: confidence, direction: 'short',
      targets: [
        { key: 't1', level: target1, action: 'book', pct: c.bookT1Pct },
        { key: 't2', level: target2, action: 'book', pct: c.bookT2Pct },
        { key: 't3', level: target3, action: 'hold', pct: c.holdT3Pct }
      ]
    };
  }

  function readCandle(candle, cfg) {
    var up = longRead(candle, cfg);
    var down = shortRead(candle, cfg);
    var side = up.confidence >= down.confidence ? 'long' : 'short';
    var chosen = side === 'long' ? up : down;
    return {
      long: up, short: down, side: side, chosen: chosen,
      confidence: chosen.confidence,
      verdict: chosen.confidence >= cfg.takeConfidence ? 'yes' : 'no'
    };
  }

  /* ---------- evaluate a payload ---------- */
  function evaluate(payload, cfg) {
    var rows = (payload.rows || []).map(function (r) {
      var read = readCandle(r.bar, cfg);
      var leg = read.chosen;
      return {
        tf: r.tf, label: r.label, running: !!r.running, barCount: r.bars || 1,
        candle: r.bar,
        side: read.side, confidence: read.confidence, verdict: read.verdict,
        entry: leg.entry, target1: leg.target1, target2: leg.target2,
        target3: leg.target3, stopLoss: leg.stopLoss, range: leg.range,
        risk: Math.abs(leg.entry - leg.stopLoss),
        rr: Math.abs(leg.entry - leg.stopLoss) > 0
          ? Math.abs(leg.target2 - leg.entry) / Math.abs(leg.entry - leg.stopLoss) : NaN
      };
    });

    var order = { '1h': 0, '1d': 1, '1w': 2, '1M': 3 };
    rows.sort(function (a, b) { return (order[a.tf] - order[b.tf]) || a.label.localeCompare(b.label); });

    /* The best row is chosen only from each timeframe's LATEST closed candle.
       Older candles are shown for context — asking for 3 daily bars is how you
       see whether the read has been consistent — but they are not tradable:
       last Tuesday's setup is not on offer today, and letting a stale candle
       win "BEST" would point at a level the market has already left behind. */
    var agree = agreement(rows);
    var best = agree.rows.reduce(function (acc, r) {
      if (r.verdict !== 'yes') return acc;
      return !acc || r.confidence > acc.confidence ? r : acc;
    }, null);

    return { payload: payload, rows: rows, best: best, agreement: agree };
  }

  /* Do the timeframes point the same way? The useful question here is whether
     an intraday signal is swimming against the weekly and monthly trend. */
  function agreement(rows) {
    var latest = {};
    rows.forEach(function (r) {
      if (r.running) return;
      /* evaluate() sorts each timeframe's candles oldest first, so the last
         one seen is the most recent closed candle — which is the only one the
         trend read should use. */
      latest[r.tf] = r;
    });
    var picked = TFS.map(function (tf) { return latest[tf]; }).filter(Boolean);
    var longs = picked.filter(function (r) { return r.side === 'long'; }).length;
    var shorts = picked.length - longs;
    return {
      rows: picked,
      longs: longs, shorts: shorts, count: picked.length,
      majority: longs === shorts ? null : (longs > shorts ? 'long' : 'short'),
      aligned: picked.length > 1 && (longs === picked.length || shorts === picked.length)
    };
  }

  /* ---------- rendering ---------- */
  var TF_LABEL = { '1h': 'sw.tf1h', '1d': 'sw.tf1d', '1w': 'sw.tf1w', '1M': 'sw.tf1M' };

  function sideChip(side) {
    return '<span class="scan-side is-' + (side === 'long' ? 'call' : 'put') + '">' +
      U.escapeHtml(t(side === 'long' ? 'sw.long' : 'sw.short')) + '</span>';
  }

  function renderHeadline(result) {
    var p = result.payload;
    var best = result.best;
    var el = U.$('sw-headline');
    el.className = 'card verdict-card ' + (best ? 'an-verdict is-yes' : 'an-verdict is-no');
    el.innerHTML =
      '<div class="an-verdict-top">' +
        '<div class="verdict-badge ' + (best ? (best.side === 'long' ? 'v-hold' : 'v-put') : 'v-partial') + '">' +
          (best
            ? U.escapeHtml(t('sw.bestIs', {
                side: t(best.side === 'long' ? 'sw.long' : 'sw.short'),
                symbol: p.symbol, tf: t(TF_LABEL[best.tf]) }))
            : U.escapeHtml(t('sw.noneQualify'))) +
        '</div>' +
        (best ? '<div class="an-confidence"><b>' + U.fmt(best.confidence, 0) + '%</b>' +
          '<span>' + U.escapeHtml(t('an.confidence')) + '</span></div>' : '') +
      '</div>' +
      '<p class="verdict-sub">' + U.escapeHtml(t('sw.context', {
        symbol: p.symbol,
        kind: t(p.kind === 'index' ? 'sw.kindIndex' : 'sw.kindEquity'),
        rows: result.rows.length
      })) +
      (p.stale && p.session
        ? ' ' + U.escapeHtml(t('sw.staleHour', { session: p.session }))
        : '') + '</p>' +
      (best
        ? '<div class="entry-strip">' +
            '<span class="entry-label">' + U.escapeHtml(t('an.entryPrice')) + '</span>' +
            '<span class="entry-value">' + money(best.entry) + '</span>' +
            '<span class="entry-side ' + (best.side === 'long' ? 'is-call' : 'is-put') + '">' +
              U.escapeHtml(t(best.side === 'long' ? 'sw.long' : 'sw.short')) + '</span>' +
          '</div>'
        : '');
  }

  function renderAgreement(result) {
    var a = result.agreement;
    var el = U.$('sw-agreement');
    if (!a.count) { el.innerHTML = ''; el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML =
      '<div class="card-head"><h3>' + U.escapeHtml(t('sw.trendTitle')) + '</h3>' +
      '<p class="muted">' + U.escapeHtml(t('sw.trendDesc')) + '</p></div>' +
      '<div class="agree-card ' + (a.aligned ? 'is-aligned' : 'is-split') + '">' +
        '<div class="agree-head">' +
          '<b>' + U.escapeHtml(result.payload.symbol) + '</b>' +
          (a.aligned
            ? '<span class="agree-tag is-aligned">' + U.escapeHtml(t('sw.aligned', {
                n: a.count, side: t(a.majority === 'long' ? 'sw.long' : 'sw.short') })) + '</span>'
            : '<span class="agree-tag is-split">' + U.escapeHtml(t('sw.split', {
                longs: a.longs, shorts: a.shorts })) + '</span>') +
        '</div>' +
        '<div class="agree-tfs">' +
          a.rows.map(function (r) {
            return '<span class="agree-tf ' + (r.side === a.majority ? 'is-with' : 'is-against') + '">' +
              U.escapeHtml(t(TF_LABEL[r.tf])) + ' ' +
              U.escapeHtml(t(r.side === 'long' ? 'sw.longShort' : 'sw.shortShort')) +
              ' <b>' + U.fmt(r.confidence, 0) + '%</b></span>';
          }).join('') +
        '</div>' +
      '</div>';
  }

  function renderTable(result) {
    var rows = result.rows.map(function (r) {
      var isBest = result.best && r === result.best;
      return '<tr class="' + (isBest ? 'is-best' : '') + (r.verdict === 'yes' ? '' : ' is-no') + '">' +
        '<td>' + U.escapeHtml(t(TF_LABEL[r.tf])) + '</td>' +
        '<td class="exp">' + U.escapeHtml(r.label) +
          (r.running ? ' <span class="running-tag">' + U.escapeHtml(t('sw.running')) + '</span>' : '') + '</td>' +
        '<td>' + sideChip(r.side) + '</td>' +
        '<td class="num conf">' + U.fmt(r.confidence, 0) + '%</td>' +
        '<td class="num">' + money(r.entry) + '</td>' +
        '<td class="num t">' + money(r.target1) + '</td>' +
        '<td class="num t">' + money(r.target2) + '</td>' +
        '<td class="num t">' + money(r.target3) + '</td>' +
        '<td class="num sl">' + money(r.stopLoss) + '</td>' +
        '<td class="num">' + U.fmt(r.range) + '</td>' +
        '<td class="num">' + (isFinite(r.rr) ? U.fmt(r.rr, 2) + '×' : '—') + '</td>' +
        '<td>' + (isBest ? '<span class="best-tag">' + U.escapeHtml(t('sc.best')) + '</span>' : '') + '</td>' +
      '</tr>';
    }).join('');

    U.$('sw-table').innerHTML =
      '<div class="card-head"><h3>' + U.escapeHtml(t('sw.tableTitle')) + '</h3>' +
      '<p class="muted">' + U.escapeHtml(t('sw.tableDesc', { n: result.rows.length })) + '</p></div>' +
      '<div class="table-scroll"><table class="scan-table"><thead><tr>' +
        ['sw.h.tf', 'sw.h.period', 'sc.h.side', 'sc.h.conf', 'sc.h.entry',
         'sc.h.t1', 'sc.h.t2', 'sc.h.t3', 'sc.h.sl', 'sc.h.range', 'sw.h.rr', 'sc.h.flag']
          .map(function (k) { return '<th>' + U.escapeHtml(t(k)) + '</th>'; }).join('') +
      '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
      '<p class="muted small" style="margin-top:10px">' + U.escapeHtml(t('sw.priceNote')) + '</p>' +
      (result.payload.skipped && result.payload.skipped.length
        ? '<p class="muted small">' + U.escapeHtml(t('sw.skipped', {
            detail: result.payload.skipped.map(function (s) { return s.tf + ': ' + s.reason; }).join('; ')
          })) + '</p>'
        : '');
  }

  function render(result) {
    renderHeadline(result);
    renderAgreement(result);
    renderTable(result);
    U.$('swing-output').hidden = false;
  }

  /* ---------- controller ---------- */
  function selectedTfs() {
    var out = TFS.filter(function (tf) {
      var el = U.$('sw-tf-' + tf);
      return el && el.checked;
    });
    return out.length ? out : ['1d'];
  }

  function status(kind, message) {
    var el = U.$('sw-status');
    el.className = 'af-status af-' + kind;
    el.textContent = message;
  }

  function run() {
    var endpoint = (U.$('sc-endpoint').value || '').trim().replace(/\/+$/, '') || U.defaultEndpoint(8123);
    var sym = APP.symbols.clean(U.$('sc-symbol').value) || 'NIFTY';
    var url = endpoint + '/history?symbol=' + encodeURIComponent(sym) +
              '&tfs=' + selectedTfs().join(',') +
              '&bars=' + Math.max(1, Math.min(10, Math.round(U.num(U.$('sw-bars').value)) || 1)) +
              (U.$('sw-running').checked ? '&running=1' : '');

    status('busy', t('sw.running.status'));
    return window.fetch(url)
      .then(function (res) {
        return res.json().then(function (body) {
          if (!res.ok) throw new Error(body && body.error ? body.error : 'HTTP ' + res.status);
          return body;
        });
      })
      .then(function (payload) {
        if (!payload.rows || !payload.rows.length) {
          var why = (payload.skipped || [])[0];
          throw new Error(why && why.reason ? String(why.reason).split('\n')[0] : t('sw.empty'));
        }
        var result = evaluate(payload, APP.config.get());
        last = result;
        APP.state.swing = result;
        render(result);
        status('ok', t('sw.done', {
          rows: result.rows.length, symbol: payload.symbol,
          source: payload.source === 'mock' ? t('af.mockSource') : payload.source
        }));
        return result;
      })
      .catch(function (err) {
        var msg = String(err && err.message || err);
        status('err', /Failed to fetch|NetworkError/i.test(msg)
          ? t('af.helperOffline', { endpoint: endpoint })
          : t('sw.failed', { reason: msg }));
        U.$('swing-output').hidden = true;
        APP.state.swing = null;
        return null;
      });
  }

  function reset() {
    U.$('swing-output').hidden = true;
    APP.state.swing = null;
    last = null;
    status('idle', t('sw.idle'));
  }

  /* Hand off to the Analyser's strike step — NOT to the Trade Signal tab.
     These levels are in share prices; every downstream tool works in option
     premium, and ₹1,520 of RELIANCE is not ₹1,520 of anything you can buy.
     What does carry across is the read itself: this underlying, at this price,
     leaning this way — so send the price to the ATM selector and let the normal
     option workflow start from there. */
  function useBest() {
    if (!last || !last.best) return;
    var r = last.best;
    U.$('atm-open').value = String(r.candle.c);
    U.$('af-symbol').value = last.payload.symbol;
    APP.symbols.remember(last.payload.symbol);
    APP.analyser.renderAtm();
    APP.tabs.show('analyser');
  }

  function init() {
    U.$('btn-sw-run').addEventListener('click', run);
    U.$('btn-sw-reset').addEventListener('click', reset);
    U.$('btn-sw-use').addEventListener('click', useBest);
    status('idle', t('sw.idle'));
  }

  APP.swing = {
    init: init, run: run, reset: reset,
    evaluate: evaluate, readCandle: readCandle,
    longRead: longRead, shortRead: shortRead, agreement: agreement
  };
})(window.APP);
