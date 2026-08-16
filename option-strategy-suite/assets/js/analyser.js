/* Tool 1 — Options Analyser (Phases 1–2).

   Input : the 09:15–09:20 candle of the ATM call and the ATM put.
   Output: which side to buy and how confidently, the entry price, three
           targets with position management, the stop loss, the pre-entry
           condition checklist and the rules to follow.

   The level model reproduces the original tool exactly — all twenty values
   across the four reference legs (24300 CE/PE and 24400 CE/PE):

     entry = close × 1.005
     step  = max(0.8 × range, 16)
     T1 / T2 / T3 = entry + step × {1, 2, 3.5}
     stop  = low − 0.3 × range

   The close drives the entry, which is why the original marks that field
   "CLOSE ★ (FIXED)". */
(function (APP) {
  'use strict';

  var U = APP.util;
  function t(key, vars) { return APP.i18n.t(key, vars); }
  function money(n) { return '₹' + U.fmt(n); }

  /* toFixed, not Math.round: 121 × 1.005 is 121.60499… in binary floating
     point, and the original shows 121.60 — the same rounding JS gives here. */
  function round2(n) { return Number(n.toFixed(2)); }

  /* ---------- ATM strike ----------
     The guide's own example rounds 23670 down to 23600, so the strike is the
     100-multiple at or below the open, not the arithmetically nearest one. */
  function atmStrike(spotOpen, stepSize) {
    var step = stepSize || 100;
    if (!isFinite(spotOpen) || spotOpen <= 0) return NaN;
    return Math.floor(spotOpen / step) * step;
  }

  /* ---------- one leg ---------- */
  function analyseSide(candle, cfg) {
    var s = U.candleStats(candle);
    var range = s.range;

    var entry = round2(candle.c * (1 + cfg.entryPremiumPct / 100));
    var step = Math.max(cfg.targetStepMult * range, cfg.minTargetStep);
    var target1 = round2(entry + step);
    var target2 = round2(entry + cfg.t2Mult * step);
    var target3 = round2(entry + cfg.t3Mult * step);
    var stopLoss = round2(candle.l - cfg.slRangeMult * range);

    /* Confidence: direction 20, body 40, close position 40. Reproduces the
       original's 80% on the 24400 put leg (bullish, 75% body, 75% close). */
    var confidence = U.clamp(
      20 * (s.bullish ? 1 : 0) + 40 * s.bodyRatio + 40 * s.closePos, 0, 100
    );

    return {
      candle: candle,
      stats: s,
      range: range,
      step: step,
      entry: entry,
      target1: target1,
      target2: target2,
      target3: target3,
      stopLoss: stopLoss,
      risk: entry - stopLoss,
      confidence: confidence,
      targets: [
        { key: 't1', level: target1, action: 'book', pct: cfg.bookT1Pct },
        { key: 't2', level: target2, action: 'book', pct: cfg.bookT2Pct },
        { key: 't3', level: target3, action: 'hold', pct: cfg.holdT3Pct }
      ]
    };
  }

  /* ---------- both legs, and the call ---------- */
  function analyse(ceCandle, peCandle, cfg) {
    var ce = analyseSide(ceCandle, cfg);
    var pe = analyseSide(peCandle, cfg);

    var side = ce.confidence >= pe.confidence ? 'call' : 'put';
    var chosen = side === 'call' ? ce : pe;
    var pcr = ceCandle.c > 0 ? peCandle.c / ceCandle.c : NaN;
    var pcrBias = pcr >= 1.2 ? 'bearish' : (pcr <= 0.8 ? 'bullish' : 'neutral');

    return {
      ce: ce, pe: pe,
      side: side,
      chosen: chosen,
      confidence: chosen.confidence,
      verdict: chosen.confidence >= cfg.takeConfidence ? 'yes' : 'no',
      pcr: pcr,
      pcrBias: pcrBias,
      conditions: conditions(ce, pe, pcr, pcrBias, side)
    };
  }

  /* ---------- pre-entry condition checklist ---------- */
  function conditions(ce, pe, pcr, pcrBias, side) {
    var list = [];
    function add(name, state, detail) { list.push({ name: name, state: state, detail: detail }); }

    add(t('an.cond.closed'), U.$('an-closed').checked ? 'pass' : 'fail',
        t(U.$('an-closed').checked ? 'an.cond.closedYes' : 'an.cond.closedNo'));

    [['call', ce], ['put', pe]].forEach(function (pair) {
      var key = pair[0], leg = pair[1];
      var wanted = key === side;
      add(t('an.cond.direction', { side: t('f.' + key + 'Short') }),
          leg.stats.bullish ? 'pass' : (wanted ? 'fail' : 'info'),
          t(leg.stats.bullish ? 'an.cond.bullish' : 'an.cond.bearish',
            { o: U.fmt(leg.candle.o), c: U.fmt(leg.candle.c) }));
    });

    [['call', ce], ['put', pe]].forEach(function (pair) {
      var key = pair[0], leg = pair[1];
      add(t('an.cond.body', { side: t('f.' + key + 'Short') }),
          leg.stats.bodyRatio >= 0.6 ? 'pass' : (key === side ? 'fail' : 'info'),
          U.pct(leg.stats.bodyRatio));
    });

    [['call', ce], ['put', pe]].forEach(function (pair) {
      var key = pair[0], leg = pair[1];
      add(t('an.cond.closePos', { side: t('f.' + key + 'Short') }),
          leg.stats.closePos >= 0.6 ? 'pass' : (key === side ? 'fail' : 'info'),
          U.pct(leg.stats.closePos));
    });

    add(t('an.cond.pcr'), pcrBias === 'neutral' ? 'warn' : 'pass',
        U.fmt(pcr, 2) + ' — ' + t('an.pcr.' + pcrBias));

    return list;
  }

  /* ---------- rendering ---------- */
  var STATE_ICON = { pass: '✓', fail: '✕', warn: '⚠', info: '·' };

  function renderVerdict(r, cfg) {
    var isCall = r.side === 'call';
    var leg = r.chosen;
    var buyLabel = t(isCall ? 'an.buyCall' : 'an.buyPut');
    var yes = r.verdict === 'yes';

    U.$('an-verdict').className = 'card verdict-card an-verdict ' + (yes ? 'is-yes' : 'is-no');
    U.$('an-verdict').innerHTML = '' +
      '<div class="an-verdict-top">' +
        '<div class="verdict-badge ' + (isCall ? 'v-hold' : 'v-put') + '">' +
          (yes ? '✅ ' : '⚠ ') + U.escapeHtml(yes ? t('an.yes', { buy: buyLabel }) : t('an.noClear')) +
        '</div>' +
        '<div class="an-confidence"><b>' + U.fmt(r.confidence, 0) + '%</b>' +
          '<span>' + U.escapeHtml(t('an.confidence')) + '</span></div>' +
      '</div>' +
      '<p class="verdict-sub">' + U.escapeHtml(t('an.reason', {
        side: t(isCall ? 'f.call' : 'f.put'),
        dir: t(leg.stats.bullish ? 'an.cond.bullishWord' : 'an.cond.bearishWord'),
        body: U.pct(leg.stats.bodyRatio),
        close: U.pct(leg.stats.closePos),
        pcr: U.fmt(r.pcr, 2),
        pcrBias: t('an.pcr.' + r.pcrBias)
      })) + '</p>' +
      '<div class="entry-strip">' +
        '<span class="entry-label">' + U.escapeHtml(t('an.entryPrice')) + '</span>' +
        '<span class="entry-value">' + money(leg.entry) + '</span>' +
        '<span class="entry-side ' + (isCall ? 'is-call' : 'is-put') + '">' + U.escapeHtml(buyLabel) + '</span>' +
      '</div>';
  }

  function renderConditions(r) {
    U.$('an-conditions').innerHTML = r.conditions.map(function (c) {
      return '<li class="check ' + c.state + '">' +
        '<span class="check-icon" aria-hidden="true">' + STATE_ICON[c.state] + '</span>' +
        '<span class="check-body"><span class="check-name">' + U.escapeHtml(c.name) + '</span></span>' +
        '<span class="check-verdict">' + U.escapeHtml(c.detail) + '</span>' +
      '</li>';
    }).join('');
  }

  function targetTable(leg, isPut, isChosen) {
    function row(label, level, delta, badge, cls) {
      return '<tr class="' + cls + '">' +
        '<td class="tgt-label">' + U.escapeHtml(label) + '</td>' +
        '<td class="tgt-level">' + money(level) + '</td>' +
        '<td class="tgt-pts">' + (delta >= 0 ? '+' : '−') + U.fmt(Math.abs(delta), 0) + t('an.pts') + '</td>' +
        '<td class="tgt-action">' + (badge ? '<span class="tgt-badge ' + cls + '">' + U.escapeHtml(badge) + '</span>' : '') + '</td>' +
      '</tr>';
    }
    return '' +
      '<article class="card target-card ' + (isPut ? 'side-put' : 'side-call') + (isChosen ? ' is-chosen' : '') + '">' +
        '<h3 class="target-title"><span class="dot ' + (isPut ? 'dot-put' : 'dot-call') + '"></span>' +
          U.escapeHtml(t(isPut ? 'an.putTargets' : 'an.callTargets')) +
          (isChosen ? '<span class="badge-primary">' + U.escapeHtml(t('an.tradeThis')) + '</span>' : '') +
        '</h3>' +
        '<div class="table-scroll"><table class="targets"><tbody>' +
          row(t('an.entry'), leg.entry, 0, '', 'row-entry').replace('<td class="tgt-pts">+0' + t('an.pts') + '</td>', '<td class="tgt-pts"></td>') +
          row(t('an.target1'), leg.target1, leg.target1 - leg.entry, t('an.book', { pct: 40 }), 'row-t1') +
          row(t('an.target2'), leg.target2, leg.target2 - leg.entry, t('an.book', { pct: 40 }), 'row-t2') +
          row(t('an.target3'), leg.target3, leg.target3 - leg.entry, t('an.hold', { pct: 20 }), 'row-t3') +
          row(t('an.stopLoss'), leg.stopLoss, leg.stopLoss - leg.entry, t('an.exitAll'), 'row-sl') +
        '</tbody></table></div>' +
      '</article>';
  }

  function renderTargets(r) {
    U.$('an-targets').innerHTML =
      targetTable(r.ce, false, r.side === 'call') +
      targetTable(r.pe, true, r.side === 'put');
  }

  function renderRules(r) {
    var leg = r.chosen;
    var buy = t(r.side === 'call' ? 'an.buyCall' : 'an.buyPut');
    var vars = {
      buy: buy, entry: money(leg.entry), sl: money(leg.stopLoss),
      t1: money(leg.target1), t2: money(leg.target2), t3: money(leg.target3)
    };
    var rules = [1, 2, 3, 4, 5, 6].map(function (n) { return t('an.rule' + n, vars); });
    U.$('an-rules').innerHTML =
      '<div class="card-head"><h3>' + U.escapeHtml(t('an.rulesTitle')) + '</h3>' +
      '<p class="muted">' + U.escapeHtml(t('an.rulesDesc')) + '</p></div>' +
      '<ol class="action-plan">' +
        rules.map(function (x) { return '<li>' + U.escapeHtml(x) + '</li>'; }).join('') +
      '</ol>';
  }

  function render(result, cfg) {
    renderVerdict(result, cfg);
    renderConditions(result);
    renderTargets(result);
    renderRules(result);
    U.$('analyser-output').hidden = false;
  }

  function renderAtm() {
    var el = U.$('atm-result');
    var open = U.num(U.$('atm-open').value);
    if (!isFinite(open) || open <= 0) {
      el.innerHTML = '<span class="muted small">' + U.escapeHtml(t('an.atmHint')) + '</span>';
      return;
    }
    var strike = atmStrike(open);
    el.innerHTML = '' +
      '<div>' +
        '<div class="atm-strike">' + U.fmt(strike, 0) + '</div>' +
        '<div class="atm-legs">' +
          '<span class="leg leg-call">' + U.fmt(strike, 0) + ' CE</span>' +
          '<span class="leg leg-put">' + U.fmt(strike, 0) + ' PE</span>' +
        '</div>' +
        '<div class="muted small" style="margin-top:6px">' +
          U.escapeHtml(t('an.atmRounded', { open: U.fmt(open) })) + '</div>' +
      '</div>';
  }

  /* ---------- controller ---------- */
  function run() {
    var cfg = APP.config.get();
    var ce = U.readCandle('an-ce');
    var pe = U.readCandle('an-pe');

    var ceErrors = U.validateCandle(ce, t('v.call'), 'an-ce');
    var peErrors = U.validateCandle(pe, t('v.put'), 'an-pe');
    U.showErrors('an-ce-err', ceErrors);
    U.showErrors('an-pe-err', peErrors);

    if (ceErrors.length || peErrors.length) {
      U.$('analyser-output').hidden = true;
      APP.state.analyser = null;
      return null;
    }

    var result = analyse(ce, pe, cfg);
    APP.state.analyser = result;
    render(result, cfg);
    return result;
  }

  function reset() {
    U.clearCandle('an-ce');
    U.clearCandle('an-pe');
    U.$('atm-open').value = '';
    U.$('an-closed').checked = true;
    U.showErrors('an-ce-err', []);
    U.showErrors('an-pe-err', []);
    U.$('analyser-output').hidden = true;
    APP.state.analyser = null;
    renderAtm();
  }

  function loadSample() {
    U.$('atm-open').value = '24400';
    U.writeCandle('an-ce', { o: 143, h: 143, l: 110, c: 110 });
    U.writeCandle('an-pe', { o: 94, h: 130, l: 94, c: 121 });
    U.$('an-closed').checked = true;
    renderAtm();
    run();
  }

  function init() {
    U.$('btn-analyse').addEventListener('click', run);
    U.$('btn-analyser-reset').addEventListener('click', reset);
    U.$('btn-analyser-sample').addEventListener('click', loadSample);
    U.$('atm-open').addEventListener('input', renderAtm);
    U.$('an-closed').addEventListener('change', function () { if (APP.state.analyser) run(); });

    U.$$('#panel-analyser .candle-box input').forEach(function (input) {
      input.addEventListener('keydown', function (e) { if (e.key === 'Enter') run(); });
    });

    /* Hand-off buttons are rendered with the results, so delegate. */
    U.$('analyser-output').addEventListener('click', function (e) {
      var btn = e.target.closest && e.target.closest('[data-send-t1]');
      if (btn) APP.t1helper.importFromAnalyser(btn.getAttribute('data-send-t1'));
    });
  }

  APP.analyser = {
    init: init, run: run, reset: reset,
    analyse: analyse, analyseSide: analyseSide,
    atmStrike: atmStrike, renderAtm: renderAtm
  };
})(window.APP);
