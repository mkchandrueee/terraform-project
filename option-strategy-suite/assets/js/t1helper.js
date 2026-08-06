/* Tool 2 — T1 Decision Helper (Phase 3, steps 6–10).

   Input : the triggered side, the three mapped levels (entry = analyser stop
           loss, T1 = analyser entry, T2 = analyser Target 1) and the OHLC of
           the candle that confirmed the entry.
   Output: hold-to-T2 vs book-now, a probability score, five condition checks
           and the condition-4 gate that decides whether the trade is taken. */
(function (APP) {
  'use strict';

  var U = APP.util;
  var side = 'call';

  /* ---------- decision model ---------- */
  function decide(levels, candle, cfg) {
    var s = U.candleStats(candle);
    var remaining = levels.t2 - candle.c;                     // distance still to cover
    var spanT1toT2 = levels.t2 - levels.t1;
    var progress = spanT1toT2 > 0 ? (candle.c - levels.t1) / spanT1toT2 : 0;
    var reach = remaining > 0 ? s.range / remaining : Infinity; // candle ranges needed for T2

    var checks = [
      {
        id: 1,
        weight: 25,
        name: 'Entry confirmed above the T1 level',
        pass: candle.c > levels.t1,
        detail: 'Close ' + U.fmt(candle.c) + ' vs T1 ' + U.fmt(levels.t1) +
                ' → ' + (candle.c > levels.t1 ? '+' : '') + U.fmt(candle.c - levels.t1)
      },
      {
        id: 2,
        weight: 20,
        name: 'Decisive body on the confirmation candle',
        pass: s.bullish && s.bodyRatio >= cfg.minBodyRatio,
        detail: 'Body ' + U.pct(s.bodyRatio) + ' of range (need ' + U.pct(cfg.minBodyRatio, 0) + ')' +
                (s.bullish ? ', bullish' : ', not bullish')
      },
      {
        id: 3,
        weight: 20,
        name: 'Close held in the upper part of the candle',
        pass: s.closePos >= cfg.minClosePos,
        detail: 'Close at ' + U.pct(s.closePos) + ' of range (need ' + U.pct(cfg.minClosePos, 0) +
                '), upper wick ' + U.pct(s.upperWick)
      },
      {
        id: 4,
        weight: 25,
        critical: true,
        name: 'T2 is within reach of the current momentum',
        pass: remaining <= 0 || reach >= cfg.reachFactor,
        detail: remaining <= 0
          ? 'Close is already at or beyond T2 (' + U.fmt(levels.t2) + ')'
          : 'Distance left ' + U.fmt(remaining) + ' vs candle range ' + U.fmt(s.range) +
            ' → ' + U.fmt(reach) + '× (need ' + U.fmt(cfg.reachFactor) + '×)'
      },
      {
        id: 5,
        weight: 10,
        name: 'Structure intact above the entry level',
        pass: candle.l >= levels.entry && candle.c > levels.entry,
        detail: 'Candle low ' + U.fmt(candle.l) + ' vs entry ' + U.fmt(levels.entry) +
                (candle.l >= levels.entry ? ' — never traded back below' : ' — dipped below the entry level')
      }
    ];

    var score = checks.reduce(function (sum, c) { return sum + (c.pass ? c.weight : 0); }, 0);
    var check4 = checks[3];

    var verdict, headline, explain;
    if (!checks[0].pass) {
      verdict = 'book';
      headline = 'AVOID — ENTRY NOT CONFIRMED';
      explain = 'The candle did not close above the T1 level, so the entry the strategy requires never triggered. ' +
                'There is no trade to hold or book here — wait for a candle that closes above ' + U.fmt(levels.t1) + '.';
    } else if (score >= cfg.holdThreshold && check4.pass) {
      verdict = 'hold';
      headline = 'HOLD T2';
      explain = 'Probability of reaching the target is high. The confirmation candle closed strongly and T2 at ' +
                U.fmt(levels.t2) + ' sits within reach of the current momentum — the trade can be held.';
    } else if (score >= cfg.partialThreshold) {
      verdict = 'partial';
      headline = 'PARTIAL BOOK';
      explain = 'Probability is mixed. Book part of the position at or near ' + U.fmt(levels.t1) +
                ' and let the remainder run only while price keeps making progress toward ' + U.fmt(levels.t2) + '.';
    } else {
      verdict = 'book';
      headline = 'BOOK NOW';
      explain = 'Probability of reaching the target is low. Exit the position at market rather than waiting for T2 — ' +
                'if the trade has not been entered yet, skip it.';
    }

    return {
      side: levels.side,
      levels: levels,
      stats: s,
      checks: checks,
      check4: check4,
      score: score,
      remaining: remaining,
      progress: progress,
      reach: reach,
      verdict: verdict,
      headline: headline,
      explain: explain
    };
  }

  /* ---------- rendering ---------- */
  var VERDICT_CLASS = { hold: 'v-hold', partial: 'v-partial', book: 'v-book' };

  function render(result) {
    var sideLabel = result.side === 'put' ? 'Put target' : 'Call target';

    U.$('t1-verdict').innerHTML = '' +
      '<div class="muted small" style="margin-bottom:12px">' + sideLabel + ' · confirmation candle assessed</div>' +
      '<div class="verdict-badge ' + VERDICT_CLASS[result.verdict] + '">' + U.escapeHtml(result.headline) + '</div>' +
      '<p class="verdict-sub">' + U.escapeHtml(result.explain) + '</p>' +
      '<div class="score-wrap">' +
        '<div class="score-num"><span>Probability score</span><b>' + result.score + ' / 100</b></div>' +
        '<div class="bar"><i style="width:' + result.score + '%"></i></div>' +
        '<div class="score-num" style="margin-top:8px"><span>Distance left to T2</span><b>' +
          (result.remaining > 0 ? U.fmt(result.remaining) : 'reached') + '</b></div>' +
        '<div class="score-num"><span>Progress past T1</span><b>' + U.pct(U.clamp(result.progress, 0, 1), 0) + '</b></div>' +
      '</div>';

    U.$('t1-checks').innerHTML = result.checks.map(function (c) {
      return '' +
        '<li class="check ' + (c.pass ? 'pass' : 'fail') + (c.critical ? ' is-critical' : '') + '">' +
          '<span class="check-icon" aria-hidden="true">' + (c.pass ? '✓' : '✕') + '</span>' +
          '<span class="check-body">' +
            '<span class="check-name">Check ' + c.id + ' — ' + U.escapeHtml(c.name) +
              (c.critical ? '<span class="crit-tag">Decisive</span>' : '') + '</span>' +
            '<span class="check-detail">' + U.escapeHtml(c.detail) + '</span>' +
          '</span>' +
        '</li>';
    }).join('');

    var passed = result.check4.pass;
    U.$('t1-gate').className = 'card gate ' + (passed ? 'pass' : 'fail');
    U.$('t1-gate').innerHTML = '' +
      '<h3>Condition check 4 — ' + (passed ? 'PASSED' : 'NOT PASSED') + '</h3>' +
      '<p class="muted">' + (passed
        ? 'The final pre-trade condition is satisfied. Proceed with the trade, following the verdict above for target management.'
        : 'The final pre-trade condition failed. Skip the trade — this gate overrides every other check and the verdict above.') +
      '</p>';

    U.$('t1-output').hidden = false;
  }

  /* ---------- controller ---------- */
  function setSide(next) {
    side = next === 'put' ? 'put' : 'call';
    U.$$('#panel-t1 .side-btn').forEach(function (btn) {
      var active = btn.getAttribute('data-side') === side;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-checked', active ? 'true' : 'false');
    });
  }

  function run() {
    var cfg = APP.config.get();
    var levels = {
      side: side,
      entry: U.num(U.$('t1-entry').value),
      t1: U.num(U.$('t1-t1').value),
      t2: U.num(U.$('t1-t2').value)
    };

    var levelErrors = [];
    [['entry', 'Entry'], ['t1', 'T1 target'], ['t2', 'T2 target']].forEach(function (pair) {
      if (!isFinite(levels[pair[0]]) || levels[pair[0]] <= 0) {
        levelErrors.push(pair[1] + ' is required and must be greater than 0.');
      }
    });
    if (!levelErrors.length && !(levels.entry < levels.t1 && levels.t1 < levels.t2)) {
      levelErrors.push('Levels must rise in order: entry < T1 < T2. Mapped from the analyser that is stop loss < entry price < Target 1.');
    }
    U.showErrors('t1-levels-err', levelErrors);

    var candle = U.readCandle('t1');
    var candleErrors = U.validateCandle(candle, 'Confirmation candle', 't1');
    U.showErrors('t1-candle-err', candleErrors);

    if (levelErrors.length || candleErrors.length) {
      U.$('t1-output').hidden = true;
      return null;
    }

    var result = decide(levels, candle, cfg);
    APP.state.t1 = result;
    render(result);
    return result;
  }

  function reset() {
    ['t1-entry', 't1-t1', 't1-t2'].forEach(function (id) { U.$(id).value = ''; });
    U.clearCandle('t1');
    U.showErrors('t1-levels-err', []);
    U.showErrors('t1-candle-err', []);
    U.$('t1-output').hidden = true;
    APP.state.t1 = null;
  }

  /* Steps 6–7: pull the analyser output across with the guide's mapping. */
  function importFromAnalyser(which) {
    var a = APP.state.analyser;
    if (!a) return;
    var r = which === 'put' ? a.pe : a.ce;
    setSide(which);
    U.$('t1-entry').value = r.stopLoss.toFixed(2);   // entry field  <- stop loss
    U.$('t1-t1').value = r.entry.toFixed(2);         // T1 field     <- entry price
    U.$('t1-t2').value = r.target1.toFixed(2);       // T2 field     <- Target 1
    U.showErrors('t1-levels-err', []);
    U.$('t1-output').hidden = true;
    APP.tabs.show('t1');
    U.$('t1-o').focus();
  }

  function init() {
    U.$$('#panel-t1 .side-btn').forEach(function (btn) {
      btn.addEventListener('click', function () { setSide(btn.getAttribute('data-side')); });
    });
    U.$('btn-decide').addEventListener('click', run);
    U.$('btn-t1-reset').addEventListener('click', reset);
    U.$$('#panel-t1 input').forEach(function (input) {
      input.addEventListener('keydown', function (e) { if (e.key === 'Enter') run(); });
    });
  }

  APP.t1helper = { init: init, run: run, reset: reset, decide: decide, importFromAnalyser: importFromAnalyser };
})(window.APP);
