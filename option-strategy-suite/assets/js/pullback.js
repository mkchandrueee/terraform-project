/* Tool 3 — Stoploss Pullback Entry (Phase 4, steps 11–13).

   Input : the original 09:15–09:20 call and put candles.
   Output: the side to trade (call buy / put buy), zone 1 as the entry price
           and Target 1. No stop loss is produced — the setup is structural. */
(function (APP) {
  'use strict';

  var U = APP.util;
  function t(key, vars) { return APP.i18n.t(key, vars); }

  function scoreSide(candle, combinedRange) {
    var s = U.candleStats(candle);
    var relRange = combinedRange > 0 ? s.range / combinedRange : 0.5;
    /* Liquidity score: where the candle closed matters most, then how much of
       the range was body, then direction, then how much of the session's early
       movement this side actually captured. */
    var score = U.clamp(
      0.45 * s.closePos + 0.30 * s.bodyRatio + 0.15 * (s.bullish ? 1 : 0) + 0.10 * relRange,
      0, 1
    );
    return { stats: s, relRange: relRange, score: score };
  }

  function levelsFor(candle, cfg) {
    var range = candle.h - candle.l;
    return {
      zone1: U.toTick(candle.l + cfg.zone1Retrace * range, cfg.tickSize),
      zone2: U.toTick(candle.l + cfg.zone2Retrace * range, cfg.tickSize),
      target1: U.toTick(candle.h + cfg.pullbackTargetMult * range, cfg.tickSize),
      range: range
    };
  }

  function analyse(ceCandle, peCandle, cfg) {
    var combined = (ceCandle.h - ceCandle.l) + (peCandle.h - peCandle.l);
    var ce = scoreSide(ceCandle, combined);
    var pe = scoreSide(peCandle, combined);

    var side = ce.score >= pe.score ? 'call' : 'put';
    var chosenCandle = side === 'call' ? ceCandle : peCandle;
    var margin = Math.abs(ce.score - pe.score);

    return {
      side: side,
      margin: margin,
      confidence: margin < 0.05 ? 'low' : (margin < 0.15 ? 'moderate' : 'high'),
      ce: ce,
      pe: pe,
      ceCandle: ceCandle,
      peCandle: peCandle,
      levels: levelsFor(chosenCandle, cfg),
      chosenCandle: chosenCandle
    };
  }

  /* ---------- rendering ---------- */
  function render(result) {
    var isCall = result.side === 'call';

    U.$('pb-verdict').innerHTML = '' +
      '<div class="muted small" style="margin-bottom:12px">' + U.escapeHtml(t('pb.recommended')) + '</div>' +
      '<div class="pb-side ' + (isCall ? 'pb-call' : 'pb-put') + '">' +
        U.escapeHtml(t(isCall ? 'pb.callBuy' : 'pb.putBuy')) + '</div>' +
      '<p class="verdict-sub">' + U.escapeHtml(t('pb.reason', {
        leg: t(isCall ? 'f.call' : 'f.put'),
        win: U.pct(isCall ? result.ce.score : result.pe.score, 0),
        lose: U.pct(isCall ? result.pe.score : result.ce.score, 0),
        confidence: t('pb.conf.' + result.confidence)
      })) + '</p>';

    U.$('pb-levels').innerHTML = '' +
      '<div class="card-head"><h3><span class="step-pill">' + U.escapeHtml(t('pb.step13')) + '</span> ' +
        U.escapeHtml(t('pb.levels')) + '</h3>' +
      '<p class="muted">' + U.escapeHtml(t('pb.levelsDesc')) + '</p></div>' +
      '<div class="zone-grid">' +
        '<div class="zone zone-1"><div class="zone-label">' + U.escapeHtml(t('pb.zone1')) + '</div><div class="zone-value">' +
          U.fmt(result.levels.zone1) + '</div><div class="zone-note">' + U.escapeHtml(t('pb.zone1Note')) + '</div></div>' +
        '<div class="zone zone-2"><div class="zone-label">' + U.escapeHtml(t('pb.zone2')) + '</div><div class="zone-value">' +
          U.fmt(result.levels.zone2) + '</div><div class="zone-note">' + U.escapeHtml(t('pb.zone2Note')) + '</div></div>' +
        '<div class="zone zone-t"><div class="zone-label">' + U.escapeHtml(t('pb.target')) + '</div><div class="zone-value">' +
          U.fmt(result.levels.target1) + '</div><div class="zone-note">' + U.escapeHtml(t('pb.targetNote')) + '</div></div>' +
      '</div>' +
      '<p class="no-sl">' + U.escapeHtml(t('pb.noSl')) + '</p>';

    function row(name, ceVal, peVal, ceWins) {
      return '<tr><td>' + U.escapeHtml(name) + '</td>' +
        '<td class="' + (ceWins === true ? 'win' : '') + '">' + ceVal + '</td>' +
        '<td class="' + (ceWins === false ? 'win' : '') + '">' + peVal + '</td></tr>';
    }
    var c = result.ce, p = result.pe;

    U.$('pb-detail').innerHTML = '' +
      '<div class="card-head"><h3>' + U.escapeHtml(t('pb.compare')) + '</h3>' +
      '<p class="muted">' + U.escapeHtml(t('pb.compareDesc')) + '</p></div>' +
      '<div class="table-scroll"><table class="compare">' +
        '<thead><tr><th>' + U.escapeHtml(t('pb.measure')) + '</th><th>' + U.escapeHtml(t('pb.colCall')) +
          '</th><th>' + U.escapeHtml(t('pb.colPut')) + '</th></tr></thead><tbody>' +
        row(t('pb.rRange'), U.fmt(c.stats.range), U.fmt(p.stats.range), c.stats.range > p.stats.range) +
        row(t('pb.rClose'), U.pct(c.stats.closePos), U.pct(p.stats.closePos), c.stats.closePos > p.stats.closePos) +
        row(t('pb.rBody'), U.pct(c.stats.bodyRatio), U.pct(p.stats.bodyRatio), c.stats.bodyRatio > p.stats.bodyRatio) +
        row(t('pb.rDirection'), t(c.stats.bullish ? 'pb.bullish' : 'pb.bearish'),
            t(p.stats.bullish ? 'pb.bullish' : 'pb.bearish'),
            c.stats.bullish === p.stats.bullish ? null : c.stats.bullish) +
        row(t('pb.rShare'), U.pct(c.relRange), U.pct(p.relRange), c.relRange > p.relRange) +
        row(t('pb.rScore'), U.pct(c.score, 0), U.pct(p.score, 0), c.score >= p.score) +
        '</tbody></table></div>';

    U.$('pullback-output').hidden = false;
  }

  /* ---------- controller ---------- */
  function run() {
    var cfg = APP.config.get();
    var ce = U.readCandle('pb-ce');
    var pe = U.readCandle('pb-pe');

    var ceErrors = U.validateCandle(ce, t('v.call'), 'pb-ce');
    var peErrors = U.validateCandle(pe, t('v.put'), 'pb-pe');
    U.showErrors('pb-ce-err', ceErrors);
    U.showErrors('pb-pe-err', peErrors);

    if (ceErrors.length || peErrors.length) {
      U.$('pullback-output').hidden = true;
      return null;
    }

    var result = analyse(ce, pe, cfg);
    APP.state.pullback = result;
    render(result);
    return result;
  }

  function reset() {
    U.clearCandle('pb-ce');
    U.clearCandle('pb-pe');
    U.showErrors('pb-ce-err', []);
    U.showErrors('pb-pe-err', []);
    U.$('pullback-output').hidden = true;
    APP.state.pullback = null;
  }

  /* Step 11 reuses the very same candles typed into the analyser. */
  function importFromAnalyser() {
    var a = APP.state.analyser;
    if (a) {
      U.writeCandle('pb-ce', a.ce.candle);
      U.writeCandle('pb-pe', a.pe.candle);
    } else {
      U.writeCandle('pb-ce', U.readCandle('an-ce'));
      U.writeCandle('pb-pe', U.readCandle('an-pe'));
    }
    U.showErrors('pb-ce-err', []);
    U.showErrors('pb-pe-err', []);
    run();
  }

  function init() {
    U.$('btn-pullback').addEventListener('click', run);
    U.$('btn-pb-reset').addEventListener('click', reset);
    U.$('btn-pb-import').addEventListener('click', importFromAnalyser);
    U.$$('#panel-pullback input').forEach(function (input) {
      input.addEventListener('keydown', function (e) { if (e.key === 'Enter') run(); });
    });
  }

  APP.pullback = {
    init: init, run: run, reset: reset, analyse: analyse,
    importFromAnalyser: importFromAnalyser
  };
})(window.APP);
