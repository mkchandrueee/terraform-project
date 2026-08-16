/* Tool 2 — T1 Decision Helper (Phase 3, steps 6–10).

   Input : the trade side, the three mapped levels the guide specifies at
           steps 6–7 (entry = analyser stop loss, T1 = analyser entry price,
           T2 = analyser Target 1) and the OHLC of the candle that confirmed
           the entry by closing above the entry price.
   Output: hold-to-T2 vs partial book vs book now, a momentum score, the
           T1→T2 reward ratio, four condition checks, the condition-4 gate and
           a step-by-step action plan.

   Momentum weights are direction 40, body {strong 15, moderate 7.5, weak 0}
   and close 40, floored — the combination that reproduces the reference
   tool's own published scores of 0%, 15% and 87%. */
(function (APP) {
  'use strict';

  var U = APP.util;
  var side = 'call';

  /* Weights recovered from every momentum score the original has published:
       0%  direction fail, body weak,     close fail
       2%  direction fail, body moderate, close fail
      15%  direction fail, body strong,   close fail
      87%  direction pass, body moderate, close pass
     Body is pinned exactly at 15 / 2 / 0. Direction and close must total 85;
     no published case separates them, so they are split 40 / 45. */
  var W_DIRECTION = 40;
  var W_BODY_STRONG = 15;
  var W_BODY_MODERATE = 2;
  var W_CLOSE = 45;

  function t(key, vars) { return APP.i18n.t(key, vars); }
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
    var closePass = wantFalling ? (s.closePos <= 1 - cfg.minClosePos) : (s.closePos >= cfg.minClosePos);
    var bodyStatus = s.bodyRatio >= cfg.bodyStrong ? 'pass'
                   : (s.bodyRatio >= cfg.bodyModerate ? 'warn' : 'fail');
    var breakoutPass = candle.c > levels.t1;
    var breakoutGap = candle.c - levels.t1;

    var bodyDetail = bodyStatus === 'pass'
      ? t('t1.c2.strong', { pct: U.pct(s.bodyRatio), min: U.pct(cfg.bodyStrong, 0) })
      : (bodyStatus === 'warn'
          ? t('t1.c2.moderate', { pct: U.pct(s.bodyRatio), min: U.pct(cfg.bodyModerate, 0), max: U.pct(cfg.bodyStrong, 0) })
          : t('t1.c2.weak', { pct: U.pct(s.bodyRatio) }));

    var closeDetail = wantFalling
      ? t(closePass ? 't1.c3.invStrong' : 't1.c3.invWeak', { pct: U.pct(s.closePos) })
      : t(closePass ? 't1.c3.strong' : 't1.c3.weak', { pct: U.pct(1 - s.closePos) });

    var checks = [
      {
        id: 1,
        status: directionPass ? 'pass' : 'fail',
        name: t('t1.c1'),
        detail: wantFalling
          ? t(s.bullish ? 't1.c1.invAgainst' : 't1.c1.invMatch')
          : t(s.bullish ? 't1.c1.match' : 't1.c1.against')
      },
      { id: 2, status: bodyStatus, name: t('t1.c2'), detail: bodyDetail },
      { id: 3, status: closePass ? 'pass' : 'fail', name: t('t1.c3'), detail: closeDetail },
      {
        id: 4,
        critical: true,
        status: breakoutPass ? 'pass' : 'fail',
        name: t('t1.c4'),
        detail: t(breakoutPass ? 't1.c4.pass' : 't1.c4.fail', { gap: money(Math.abs(breakoutGap)) })
      }
    ];

    /* Momentum is the three candle-quality checks; the breakout is the gate. */
    var bodyPoints = bodyStatus === 'pass' ? W_BODY_STRONG
                   : (bodyStatus === 'warn' ? W_BODY_MODERATE : 0);
    var momentum = Math.floor(
      (directionPass ? W_DIRECTION : 0) + bodyPoints + (closePass ? W_CLOSE : 0)
    );

    var riskLeg = levels.t1 - levels.entry;
    var rewardLeg = levels.t2 - levels.t1;
    var rewardRatio = riskLeg > 0 ? rewardLeg / riskLeg : NaN;
    var expected = levels.t2 - levels.entry;

    var verdict, headline, explain;
    if (!breakoutPass) {
      verdict = 'wait';
      headline = t('t1.wait');
      explain = t('t1.waitText', { t1: money(levels.t1) });
    } else if (momentum >= cfg.holdThreshold) {
      verdict = 'hold';
      headline = t('t1.hold');
      explain = t('t1.holdText', { momentum: momentum, t2: money(levels.t2), expected: U.fmt(expected) });
    } else if (momentum >= cfg.partialThreshold) {
      verdict = 'partial';
      headline = t('t1.partial');
      explain = t('t1.partialText', { momentum: momentum, t2: money(levels.t2) });
    } else {
      verdict = 'book';
      headline = t('t1.book');
      explain = t('t1.bookText', { momentum: momentum });
    }

    return {
      side: levels.side,
      levels: levels,
      stats: s,
      checks: checks,
      check4: checks[3],
      momentum: momentum,
      rewardRatio: rewardRatio,
      expected: expected,
      breakoutGap: breakoutGap,
      verdict: verdict,
      headline: headline,
      explain: explain,
      plan: actionPlan(verdict, levels)
    };
  }

  /* ---------- action plan ---------- */
  var PLAN_STEPS = { hold: 5, partial: 5, book: 4, wait: 5 };

  function actionPlan(verdict, levels) {
    var vars = {
      entry: money(levels.entry), t1: money(levels.t1), t2: money(levels.t2),
      profit: U.fmt(levels.t1 - levels.entry)
    };
    var prefix = 't1.plan.' + verdict;
    var out = [];
    for (var n = 1; n <= PLAN_STEPS[verdict]; n++) out.push(t(prefix + n, vars));
    return out;
  }

  /* ---------- what the mapped ladder means in trade terms ---------- */
  function renderReading() {
    var el = U.$('t1-reading');
    var entry = U.num(U.$('t1-entry').value);
    var t1 = U.num(U.$('t1-t1').value);
    var t2 = U.num(U.$('t1-t2').value);
    if (!(isFinite(entry) && isFinite(t1) && isFinite(t2))) { el.hidden = true; el.innerHTML = ''; return; }
    el.innerHTML =
      '<b>' + U.escapeHtml(t('t1.reading', { entry: money(entry), t1: money(t1), t2: money(t2) })) + '</b>' +
      '<span>' + U.escapeHtml(t('t1.readingHint')) + '</span>';
    el.hidden = false;
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
        'aria-label="' + U.fmt(c.l) + ' – ' + U.fmt(c.h) + ', close ' + U.fmt(c.c) + '">' +
        '<line x1="' + CX + '" y1="' + y(c.h) + '" x2="' + CX + '" y2="' + y(c.l) + '" stroke="' + colour + '" stroke-width="2.5"/>' +
        '<rect x="' + (CX - 13) + '" y="' + top + '" width="26" height="' + height + '" rx="2" fill="' + colour + '"/>' +
      '</svg>' +
      '<div class="candle-facts">' +
        '<div class="candle-stat"><span>' + t('t1.body') + '</span><b>' + U.pct(s.bodyRatio, 0) + '</b></div>' +
        '<div class="candle-stat"><span>' + t('f.close') + '</span><b>' + U.pct(s.closePos, 0) + ' ' + t('t1.closeOf') + '</b></div>' +
        '<div class="candle-stat"><span>' + t('t1.rangeLabel') + '</span><b>' + U.fmt(s.range) + ' ' + t('t1.pts') + '</b></div>' +
        '<div class="candle-dir ' + (s.bullish ? 'is-bull' : 'is-bear') + '">' +
          (s.bullish ? '▲ ' + t('t1.bullish') : '▼ ' + t('t1.bearish')) + '</div>' +
      '</div>';
    el.hidden = false;
  }

  /* ---------- rendering ---------- */
  var VERDICT_CLASS = { hold: 'v-hold', partial: 'v-partial', book: 'v-book', wait: 'v-wait' };
  var STATUS_ICON = { pass: '✓', warn: '⚠', fail: '✕' };
  var STATUS_KEY = { pass: 't1.pass', warn: 't1.weak', fail: 't1.fail' };

  function render(result) {
    var sideLabel = t(result.side === 'put' ? 't1.putTrade' : 't1.callTrade');

    U.$('t1-verdict').innerHTML = '' +
      '<div class="muted small" style="margin-bottom:12px">' +
        U.escapeHtml(t('t1.assessed', { side: sideLabel })) + '</div>' +
      '<div class="verdict-badge ' + VERDICT_CLASS[result.verdict] + '">' + U.escapeHtml(result.headline) + '</div>' +
      '<p class="verdict-sub">' + U.escapeHtml(result.explain) + '</p>';

    var ratioPct = isFinite(result.rewardRatio) ? U.clamp(result.rewardRatio / 2, 0, 1) * 100 : 0;
    U.$('t1-signal').innerHTML = '' +
      '<div class="card-head"><h3>' + U.escapeHtml(t('t1.signal')) + '</h3></div>' +
      '<div class="signal">' +
        '<div class="signal-row">' +
          '<div class="signal-num"><span>' + U.escapeHtml(t('t1.momentum')) + '</span><b>' + result.momentum + '%</b></div>' +
          '<div class="bar"><i style="width:' + result.momentum + '%"></i></div>' +
        '</div>' +
        '<div class="signal-row">' +
          '<div class="signal-num"><span>' + U.escapeHtml(t('t1.rewardRatio')) +
            (isFinite(result.rewardRatio) ? ' (' + U.fmt(result.rewardRatio) + '×)' : '') +
          '</span><b>' + U.fmt(ratioPct, 0) + '%</b></div>' +
          '<div class="bar"><i style="width:' + ratioPct + '%"></i></div>' +
        '</div>' +
      '</div>';

    U.$('t1-checks').innerHTML = result.checks.map(function (c) {
      return '' +
        '<li class="check ' + c.status + (c.critical ? ' is-critical' : '') + '">' +
          '<span class="check-icon" aria-hidden="true">' + STATUS_ICON[c.status] + '</span>' +
          '<span class="check-body">' +
            '<span class="check-name">' + U.escapeHtml(t('t1.check', { n: c.id })) + ' — ' + U.escapeHtml(c.name) +
              (c.critical ? '<span class="crit-tag">' + U.escapeHtml(t('t1.decisive')) + '</span>' : '') + '</span>' +
            '<span class="check-detail">' + U.escapeHtml(c.detail) + '</span>' +
          '</span>' +
          '<span class="check-verdict">' + U.escapeHtml(t(STATUS_KEY[c.status])) + '</span>' +
        '</li>';
    }).join('');

    var passed = result.check4.status === 'pass';
    U.$('t1-gate').className = 'card gate ' + (passed ? 'pass' : 'fail');
    U.$('t1-gate').innerHTML = '' +
      '<h3>' + U.escapeHtml(t(passed ? 't1.gatePass' : 't1.gateFail')) + '</h3>' +
      '<p class="muted">' + U.escapeHtml(t(passed ? 't1.gatePassText' : 't1.gateFailText')) + '</p>';

    U.$('t1-plan').innerHTML = '' +
      '<div class="card-head"><h3>' + U.escapeHtml(t('t1.plan')) + '</h3></div>' +
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
    [['entry', 't1.entryLabel'], ['t1', 't1.t1Label'], ['t2', 't1.t2Label']].forEach(function (pair) {
      if (!isFinite(levels[pair[0]]) || levels[pair[0]] <= 0) {
        levelErrors.push(t('t1.err.required', { field: t(pair[1]) }));
      }
    });
    if (!levelErrors.length && !(levels.entry < levels.t1 && levels.t1 < levels.t2)) {
      levelErrors.push(t('t1.err.ladder'));
    }
    U.showErrors('t1-levels-err', levelErrors);

    var candle = U.readCandle('t1');
    var candleErrors = U.validateCandle(candle, t('v.t1candle'), 't1');
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
    renderReading();
    APP.state.t1 = null;
  }

  function loadSample() {
    setSide('call');
    U.$('t1-entry').value = '152';
    U.$('t1-t1').value = '175';
    U.$('t1-t2').value = '198';
    U.writeCandle('t1', { o: 172, h: 181, l: 165, c: 180 });
    renderPreview();
    renderReading();
    run();
  }

  /* Steps 6–7: pull the analyser output across with the guide's mapping. */
  function importFromAnalyser(which) {
    var a = APP.state.analyser;
    if (!a) return;
    var r = which === 'put' ? a.pe : a.ce;
    setSide(which);
    /* Steps 6–7 of the strategy guide, verbatim:
         Entry field     <- Stop Loss value
         T1 Target field <- Entry Price value
         T2 Target field <- Target 1 value                                   */
    U.$('t1-entry').value = r.stopLoss.toFixed(2);
    U.$('t1-t1').value = r.entry.toFixed(2);
    U.$('t1-t2').value = r.target1.toFixed(2);
    U.showErrors('t1-levels-err', []);
    renderReading();
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
    ['t1-entry', 't1-t1', 't1-t2'].forEach(function (id) {
      U.$(id).addEventListener('input', renderReading);
    });
  }

  APP.t1helper = {
    init: init, run: run, reset: reset, decide: decide,
    importFromAnalyser: importFromAnalyser, renderPreview: renderPreview,
    renderReading: renderReading
  };
})(window.APP);
