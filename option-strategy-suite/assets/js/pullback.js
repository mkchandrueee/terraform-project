/* Tool 3 — Stoploss Pullback Entry (Phase 4, steps 11–13).

   Input : the original 09:15–09:20 call and put candles.
   Output: the side to trade (call buy / put buy), zone 1 as the entry price
           and Target 1. No stop loss is produced — the setup is structural. */
(function (APP) {
  'use strict';

  var U = APP.util;

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
    var label = isCall ? 'CALL BUY' : 'PUT BUY';
    var legend = isCall ? 'ATM call option (CE)' : 'ATM put option (PE)';

    U.$('pb-verdict').innerHTML = '' +
      '<div class="muted small" style="margin-bottom:12px">Recommended side · trade only this leg</div>' +
      '<div class="pb-side ' + (isCall ? 'pb-call' : 'pb-put') + '">' + label + '</div>' +
      '<p class="verdict-sub">The ' + legend + ' shows the stronger liquidity structure on the first candle ' +
        '(' + U.pct(isCall ? result.ce.score : result.pe.score, 0) + ' vs ' +
        U.pct(isCall ? result.pe.score : result.ce.score, 0) + ', ' + result.confidence + ' separation). ' +
        'Take the pullback entry on this side only.</p>';

    U.$('pb-levels').innerHTML = '' +
      '<div class="card-head"><h3><span class="step-pill">Step 13</span> Execution levels</h3>' +
      '<p class="muted">Zone 1 is your entry price. Target 1 is your target.</p></div>' +
      '<div class="zone-grid">' +
        '<div class="zone zone-1"><div class="zone-label">Zone 1 — entry</div><div class="zone-value">' +
          U.fmt(result.levels.zone1) + '</div><div class="zone-note">pullback into the first-candle range</div></div>' +
        '<div class="zone zone-2"><div class="zone-label">Zone 2 — deeper fill</div><div class="zone-value">' +
          U.fmt(result.levels.zone2) + '</div><div class="zone-note">optional second entry if zone 1 is swept</div></div>' +
        '<div class="zone zone-t"><div class="zone-label">Target 1</div><div class="zone-value">' +
          U.fmt(result.levels.target1) + '</div><div class="zone-note">exit level</div></div>' +
      '</div>' +
      '<p class="no-sl">⚠ No stop loss — do not place one on this setup.</p>';

    function row(name, ceVal, peVal, ceWins) {
      return '<tr><td>' + name + '</td>' +
        '<td class="' + (ceWins === true ? 'win' : '') + '">' + ceVal + '</td>' +
        '<td class="' + (ceWins === false ? 'win' : '') + '">' + peVal + '</td></tr>';
    }
    var c = result.ce, p = result.pe;

    U.$('pb-detail').innerHTML = '' +
      '<div class="card-head"><h3>Side comparison</h3>' +
      '<p class="muted">How the two first-candles scored against each other.</p></div>' +
      '<div class="table-scroll"><table class="compare">' +
        '<thead><tr><th>Measure</th><th>Call (CE)</th><th>Put (PE)</th></tr></thead><tbody>' +
        row('Range', U.fmt(c.stats.range), U.fmt(p.stats.range), c.stats.range > p.stats.range) +
        row('Close position', U.pct(c.stats.closePos), U.pct(p.stats.closePos), c.stats.closePos > p.stats.closePos) +
        row('Body of range', U.pct(c.stats.bodyRatio), U.pct(p.stats.bodyRatio), c.stats.bodyRatio > p.stats.bodyRatio) +
        row('Direction', c.stats.bullish ? 'bullish' : 'bearish', p.stats.bullish ? 'bullish' : 'bearish',
            c.stats.bullish === p.stats.bullish ? null : c.stats.bullish) +
        row('Share of early movement', U.pct(c.relRange), U.pct(p.relRange), c.relRange > p.relRange) +
        row('Liquidity score', U.pct(c.score, 0), U.pct(p.score, 0), c.score >= p.score) +
        '</tbody></table></div>';

    U.$('pullback-output').hidden = false;
  }

  /* ---------- controller ---------- */
  function run() {
    var cfg = APP.config.get();
    var ce = U.readCandle('pb-ce');
    var pe = U.readCandle('pb-pe');

    var ceErrors = U.validateCandle(ce, 'Call', 'pb-ce');
    var peErrors = U.validateCandle(pe, 'Put', 'pb-pe');
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
