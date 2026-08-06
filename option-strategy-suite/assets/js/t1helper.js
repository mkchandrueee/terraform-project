/* Tool 2 — T1 Decision Helper (Phase 3, steps 6–10).

   Input : the trade side, the three mapped levels (entry = analyser stop loss,
           T1 = analyser entry price, T2 = analyser Target 1) and the OHLC of
           the 5-minute candle that touched T1.
   Output: hold-to-T2 vs partial book vs book now, a momentum score, the
           T1→T2 reward ratio, four condition checks, the condition-4 gate and
           a step-by-step action plan. */
(function (APP) {
  'use strict';

  var U = APP.util;
  var side = 'call';

  function money(n) { return '₹' + U.fmt(n); }

  /* ---------- decision model ---------- */
  function decide(levels, candle, cfg) {
    var s = U.candleStats(candle);
    var isPut = levels.side === 'put';
    /* You are long the option on both legs, so a rising premium is a gain for a
       put trade too. The original tool inverts the put side; that is available
       behind a setting rather than baked in. */
    var wantFalling = cfg.sideAwareDirection >= 1 && isPut;

    var directionPass = wantFalling ? !s.bullish : s.bullish;
    var bodyPass = s.bodyRatio >= cfg.minBodyRatio;
    var closePass = wantFalling ? (s.closePos <= 1 - cfg.minClosePos) : (s.closePos >= cfg.minClosePos);
    var breakoutPass = candle.c > levels.t1;
    var breakoutGap = candle.c - levels.t1;

    var checks = [
      {
        id: 1,
        weight: 40,
        name: 'Direction',
        pass: directionPass,
        detail: wantFalling
          ? (s.bullish ? 'Candle is bullish — opposite to the put trade direction'
                       : 'Candle is bearish — matches the put trade direction')
          : (s.bullish ? 'Candle is bullish — the premium closed up, with the trade'
                       : 'Candle is bearish — the premium closed down, against the trade')
      },
      {
        id: 2,
        weight: 30,
        name: 'Body strength',
        pass: bodyPass,
        detail: 'Body is ' + U.pct(s.bodyRatio) + ' of the range — ' +
                (bodyPass ? 'decisive candle' : 'weak candle, a reversal is possible') +
                ' (need ' + U.pct(cfg.minBodyRatio, 0) + ')'
      },
      {
        id: 3,
        weight: 30,
        name: 'Close position',
        pass: closePass,
        detail: wantFalling
          ? 'Close sits ' + U.pct(s.closePos) + ' up the range — ' +
            (closePass ? 'held in the lower part, strong for a put' : 'in the upper part, put weakness')
          : 'Close sits in the top ' + U.pct(1 - s.closePos) + ' of the candle — ' +
            (closePass ? 'strong close' : 'gave back the upper part of the range')
      },
      {
        id: 4,
        weight: 0, /* the gate, scored separately from momentum */
        critical: true,
        name: 'T1 breakout strength',
        pass: breakoutPass,
        detail: breakoutPass
          ? 'Close is ' + money(breakoutGap) + ' above T1 — confirmed breakout'
          : 'Close is ' + money(Math.abs(breakoutGap)) + ' below T1 — no breakout yet'
      }
    ];

    /* Momentum is the three candle-quality checks; the breakout is the gate. */
    var momentum = checks.slice(0, 3).reduce(function (sum, c) {
      return sum + (c.pass ? c.weight : 0);
    }, 0);

    var riskLeg = levels.t1 - levels.entry;
    var rewardLeg = levels.t2 - levels.t1;
    var rewardRatio = riskLeg > 0 ? rewardLeg / riskLeg : NaN;

    var verdict, headline, explain;
    if (!breakoutPass) {
      verdict = 'wait';
      headline = 'WAIT — NO BREAKOUT';
      explain = 'The candle did not close above the T1 level, so nothing is confirmed yet. There is no position ' +
                'to hold or book — wait for a 5-minute candle to close above ' + money(levels.t1) + '.';
    } else if (momentum >= cfg.holdThreshold) {
      verdict = 'hold';
      headline = 'HOLD → T2';
      explain = 'Strength is showing (' + momentum + '%). The candle backs a continuation, so holding toward T2 at ' +
                money(levels.t2) + ' is the higher-probability play. Move the stop to entry and let it run.';
    } else if (momentum >= cfg.partialThreshold) {
      verdict = 'partial';
      headline = 'PARTIAL BOOK';
      explain = 'The signal is mixed (' + momentum + '%). Book part of the position here to lock in the T1 profit, ' +
                'and let the rest run toward ' + money(levels.t2) + ' only while price keeps making progress.';
    } else {
      verdict = 'book';
      headline = 'BOOK NOW';
      explain = 'Weakness is showing (' + momentum + '%). The chance of reversing before T2 is high — protecting ' +
                'the profit already at T1 is the smarter trade.';
    }

    return {
      side: levels.side,
      levels: levels,
      stats: s,
      checks: checks,
      check4: checks[3],
      momentum: momentum,
      rewardRatio: rewardRatio,
      breakoutGap: breakoutGap,
      verdict: verdict,
      headline: headline,
      explain: explain,
      plan: actionPlan(verdict, levels)
    };
  }

  /* ---------- action plan ---------- */
  function actionPlan(verdict, levels) {
    if (verdict === 'hold') {
      return [
        'Hold the current position — do not exit here.',
        'Move the stop loss up to your entry price ' + money(levels.entry) + ' — the trade is now risk-free.',
        'When T2 ' + money(levels.t2) + ' is hit, sell 80% of the position.',
        'Let the remaining 20% run toward T3 on a trailing stop.',
        'If a candle reverses before T2, exit immediately — the stop is already at entry.'
      ];
    }
    if (verdict === 'partial') {
      return [
        'Book roughly half the position now, at the T1 level ' + money(levels.t1) + '.',
        'Move the stop loss on the remainder to your entry price ' + money(levels.entry) + '.',
        'Hold the rest toward T2 ' + money(levels.t2) + ' only while each candle keeps closing higher.',
        'Exit the remainder on the first candle that closes back below ' + money(levels.t1) + '.',
        'Do not add to the position at this level.'
      ];
    }
    if (verdict === 'book') {
      return [
        'Exit the full position now, at market — take the T1 profit.',
        'Do not wait for T2; the candle is not supporting a continuation.',
        'Do not re-enter on the same candle.',
        'Wait for a fresh setup with a decisive body and a strong close.',
        'If the trade was not entered yet, skip it entirely.'
      ];
    }
    return [
      'No entry is confirmed — the candle did not close above T1 ' + money(levels.t1) + '.',
      'Do not enter or add here.',
      'Wait for a 5-minute candle to close above ' + money(levels.t1) + '.',
      'Re-run this check with that candle before doing anything.',
      'If price falls back to ' + money(levels.entry) + ', the setup is done — skip it.'
    ];
  }

  /* ---------- candle preview ---------- */
  function renderPreview() {
    var el = U.$('t1-preview');
    var c = U.readCandle('t1');
    var usable = ['o', 'h', 'l', 'c'].every(function (k) { return isFinite(c[k]) && c[k] > 0; }) &&
                 c.h > c.l && c.h >= Math.max(c.o, c.c) && c.l <= Math.min(c.o, c.c);
    if (!usable) { el.hidden = true; el.innerHTML = ''; return; }

    var s = U.candleStats(c);
    var H = 130, PAD = 3, CX = 26;
    var y = function (price) { return PAD + (c.h - price) / s.range * H; };
    var top = y(Math.max(c.o, c.c));
    var height = Math.max(2, Math.abs(y(c.c) - y(c.o)));
    var colour = s.bullish ? 'var(--call)' : 'var(--put)';

    el.innerHTML = '' +
      '<svg class="candle-svg" viewBox="0 0 52 ' + (H + PAD * 2) + '" width="52" height="' + (H + PAD * 2) + '" role="img" ' +
        'aria-label="Candle from ' + U.fmt(c.l) + ' to ' + U.fmt(c.h) + ', closing at ' + U.fmt(c.c) + '">' +
        '<line x1="' + CX + '" y1="' + y(c.h) + '" x2="' + CX + '" y2="' + y(c.l) + '" stroke="' + colour + '" stroke-width="2.5"/>' +
        '<rect x="' + (CX - 13) + '" y="' + top + '" width="26" height="' + height + '" rx="2" fill="' + colour + '"/>' +
      '</svg>' +
      '<div class="candle-facts">' +
        '<div class="candle-stat"><span>Body</span><b>' + U.pct(s.bodyRatio, 0) + '</b></div>' +
        '<div class="candle-stat"><span>Close</span><b>' + U.pct(s.closePos, 0) + ' of range</b></div>' +
        '<div class="candle-stat"><span>Range</span><b>' + U.fmt(s.range) + ' pts</b></div>' +
        '<div class="candle-dir ' + (s.bullish ? 'is-bull' : 'is-bear') + '">' +
          (s.bullish ? '▲ Bullish' : '▼ Bearish') + '</div>' +
      '</div>';
    el.hidden = false;
  }

  /* ---------- rendering ---------- */
  var VERDICT_CLASS = { hold: 'v-hold', partial: 'v-partial', book: 'v-book', wait: 'v-wait' };

  function render(result) {
    var sideLabel = result.side === 'put' ? 'Put trade' : 'Call trade';

    U.$('t1-verdict').innerHTML = '' +
      '<div class="muted small" style="margin-bottom:12px">' + sideLabel + ' · T1-touch candle assessed</div>' +
      '<div class="verdict-badge ' + VERDICT_CLASS[result.verdict] + '">' + U.escapeHtml(result.headline) + '</div>' +
      '<p class="verdict-sub">' + U.escapeHtml(result.explain) + '</p>';

    var ratioPct = isFinite(result.rewardRatio) ? U.clamp(result.rewardRatio / 2, 0, 1) * 100 : 0;
    U.$('t1-signal').innerHTML = '' +
      '<div class="card-head"><h3>Signal strength</h3></div>' +
      '<div class="signal">' +
        '<div class="signal-row">' +
          '<div class="signal-num"><span>Momentum score</span><b>' + result.momentum + '%</b></div>' +
          '<div class="bar"><i style="width:' + result.momentum + '%"></i></div>' +
        '</div>' +
        '<div class="signal-row">' +
          '<div class="signal-num"><span>T1 → T2 reward ratio' +
            (isFinite(result.rewardRatio) ? ' (' + U.fmt(result.rewardRatio) + '×)' : '') +
          '</span><b>' + U.fmt(ratioPct, 0) + '%</b></div>' +
          '<div class="bar"><i style="width:' + ratioPct + '%"></i></div>' +
        '</div>' +
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
          '<span class="check-verdict">' + (c.pass ? 'PASS' : 'FAIL') + '</span>' +
        '</li>';
    }).join('');

    var passed = result.check4.pass;
    U.$('t1-gate').className = 'card gate ' + (passed ? 'pass' : 'fail');
    U.$('t1-gate').innerHTML = '' +
      '<h3>Condition check 4 — ' + (passed ? 'PASSED' : 'NOT PASSED') + '</h3>' +
      '<p class="muted">' + (passed
        ? 'The pre-trade gate is satisfied — proceed with the trade, managing targets per the verdict above.'
        : 'The pre-trade gate failed — skip the trade. This overrides every other check and the verdict above.') +
      '</p>';

    U.$('t1-plan').innerHTML = '' +
      '<div class="card-head"><h3>Exact action plan</h3></div>' +
      '<ol class="action-plan">' +
        result.plan.map(function (step) { return '<li>' + U.escapeHtml(step) + '</li>'; }).join('') +
      '</ol>';

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
    [['entry', 'Entry price'], ['t1', 'T1 level'], ['t2', 'T2 level']].forEach(function (pair) {
      if (!isFinite(levels[pair[0]]) || levels[pair[0]] <= 0) {
        levelErrors.push(pair[1] + ' is required and must be greater than 0.');
      }
    });
    if (!levelErrors.length && !(levels.entry < levels.t1 && levels.t1 < levels.t2)) {
      levelErrors.push('Levels must rise in order: entry < T1 < T2. Mapped from the analyser that is stop loss < entry price < Target 1.');
    }
    U.showErrors('t1-levels-err', levelErrors);

    var candle = U.readCandle('t1');
    var candleErrors = U.validateCandle(candle, 'T1-touch candle', 't1');
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
    renderPreview();
    APP.state.t1 = null;
  }

  function loadSample() {
    setSide('call');
    U.$('t1-entry').value = '175';
    U.$('t1-t1').value = '219';
    U.$('t1-t2').value = '263';
    U.writeCandle('t1', { o: 217, h: 221, l: 210, c: 220 });
    renderPreview();
    run();
  }

  /* Steps 6–7: pull the analyser output across with the guide's mapping. */
  function importFromAnalyser(which) {
    var a = APP.state.analyser;
    if (!a) return;
    var r = which === 'put' ? a.pe : a.ce;
    setSide(which);
    U.$('t1-entry').value = r.stopLoss.toFixed(2);   // entry field  <- stop loss
    U.$('t1-t1').value = r.entry.toFixed(2);         // T1 level     <- entry price
    U.$('t1-t2').value = r.target1.toFixed(2);       // T2 level     <- Target 1
    U.showErrors('t1-levels-err', []);
    U.$('t1-output').hidden = true;
    APP.tabs.show('t1');
    U.$('t1-o').focus();
  }

  function init() {
    U.$$('#panel-t1 .side-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setSide(btn.getAttribute('data-side'));
        if (APP.state.t1) run();
      });
    });
    U.$('btn-decide').addEventListener('click', run);
    U.$('btn-t1-reset').addEventListener('click', reset);
    U.$('btn-t1-sample').addEventListener('click', loadSample);
    U.$$('#panel-t1 input').forEach(function (input) {
      input.addEventListener('keydown', function (e) { if (e.key === 'Enter') run(); });
    });
    U.$$('#panel-t1 .ohlc input').forEach(function (input) {
      input.addEventListener('input', renderPreview);
    });
  }

  APP.t1helper = {
    init: init, run: run, reset: reset, decide: decide,
    importFromAnalyser: importFromAnalyser, renderPreview: renderPreview
  };
})(window.APP);
