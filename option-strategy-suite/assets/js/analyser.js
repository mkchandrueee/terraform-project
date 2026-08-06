/* Tool 1 — Option Analyser (Phases 1–2, steps 1–5).

   Input : the 09:15–09:20 candle of the ATM call and the ATM put.
   Output: entry price, Target 1 and stop loss for each side, plus the
           confirmation level that a later 5-minute candle must close above. */
(function (APP) {
  'use strict';

  var U = APP.util;
  function t(key, vars) { return APP.i18n.t(key, vars); }

  /* ---------- ATM strike (step 1) ----------
     The guide's own example rounds 23670 down to 23600, so the strike is the
     100-multiple at or below the open, not the arithmetically nearest one. */
  function atmStrike(spotOpen, stepSize) {
    var step = stepSize || 100;
    if (!isFinite(spotOpen) || spotOpen <= 0) return NaN;
    return Math.floor(spotOpen / step) * step;
  }

  /* ---------- level model (steps 3–4) ---------- */
  function analyseSide(candle, cfg) {
    var s = U.candleStats(candle);
    var range = s.range;

    var entry = U.toTick(candle.h + (cfg.entryBufferPct / 100) * range, cfg.tickSize);
    var stopLoss = U.toTick(candle.l - (cfg.slBufferPct / 100) * range, cfg.tickSize);
    var target1 = U.toTick(entry + cfg.t1Multiplier * range, cfg.tickSize);

    var risk = entry - stopLoss;
    var reward = target1 - entry;

    /* How convincingly the first candle closed — used only to flag which side
       to watch first, never as a trade signal on its own. */
    var strength = U.clamp(
      0.50 * s.closePos + 0.30 * s.bodyRatio + 0.20 * (s.bullish ? 1 : 0),
      0, 1
    );

    return {
      candle: candle,
      stats: s,
      range: range,
      entry: entry,
      target1: target1,
      stopLoss: stopLoss,
      risk: risk,
      reward: reward,
      rr: risk > 0 ? reward / risk : NaN,
      confirmClose: U.toTick(entry + cfg.tickSize, cfg.tickSize),
      riskPctOfEntry: entry > 0 ? risk / entry : NaN,
      strength: strength
    };
  }

  function analyse(ceCandle, peCandle, cfg) {
    var ce = analyseSide(ceCandle, cfg);
    var pe = analyseSide(peCandle, cfg);
    var gap = ce.strength - pe.strength;
    var bias = Math.abs(gap) < 0.05 ? 'flat' : (gap > 0 ? 'call' : 'put');
    return { ce: ce, pe: pe, bias: bias, biasGap: Math.abs(gap) };
  }

  /* ---------- rendering ---------- */
  function levelBlock(r) {
    return '' +
      '<div class="levels">' +
        '<div class="level level-entry"><div class="level-label">' + t('an.entryPrice') + '</div><div class="level-value">' + U.fmt(r.entry) + '</div></div>' +
        '<div class="level level-target"><div class="level-label">' + t('an.target1') + '</div><div class="level-value">' + U.fmt(r.target1) + '</div></div>' +
        '<div class="level level-sl"><div class="level-label">' + t('an.stopLoss') + '</div><div class="level-value">' + U.fmt(r.stopLoss) + '</div></div>' +
      '</div>';
  }

  function metricsBlock(r, isPut) {
    return '' +
      '<div class="metrics">' +
        '<div class="metric"><span>' + t('an.range') + '</span><span>' + U.fmt(r.range) + '</span></div>' +
        '<div class="metric"><span>' + t('an.risk') + '</span><span>' + U.fmt(r.risk) + '</span></div>' +
        '<div class="metric"><span>' + t('an.reward') + '</span><span>' + U.fmt(r.reward) + '</span></div>' +
        '<div class="metric"><span>' + t('an.rr') + '</span><span>' + (isFinite(r.rr) ? '1 : ' + U.fmt(r.rr) : '—') + '</span></div>' +
        '<div class="metric"><span>' + t('an.riskPct') + '</span><span>' + U.pct(r.riskPctOfEntry) + '</span></div>' +
        '<div class="metric"><span>' + t('an.closePos') + '</span><span>' + U.pct(r.stats.closePos) + '</span></div>' +
        '<div class="metric"><span>' + t('an.bodyPct') + '</span><span>' + U.pct(r.stats.bodyRatio) + '</span></div>' +
        '<div class="metric"><span>' + t('an.strength') + '</span><span>' + U.pct(r.strength, 0) + '</span></div>' +
      '</div>' +
      '<div class="bar' + (isPut ? ' bar-put' : '') + '"><i style="width:' + U.fmt(r.strength * 100, 0) + '%"></i></div>';
  }

  function renderSide(elId, title, r, isPut, isPrimary) {
    var el = U.$(elId);
    el.innerHTML = '' +
      '<h3 class="result-title">' + U.escapeHtml(title) +
        (isPrimary ? '<span class="badge-primary">' + U.escapeHtml(t('an.primary')) + '</span>' : '') +
      '</h3>' +
      levelBlock(r) +
      metricsBlock(r, isPut) +
      '<p class="confirm-line">' +
        t('an.confirm', { close: U.fmt(r.confirmClose), entry: U.fmt(r.entry) }) + '</p>' +
      '<div class="row-actions">' +
        '<button type="button" class="btn btn-sm" data-send-t1="' + (isPut ? 'put' : 'call') + '">' +
          U.escapeHtml(t('an.sendT1')) + '</button>' +
      '</div>';
  }

  function renderBias(result) {
    var el = U.$('analyser-bias');
    var tag, text;
    if (result.bias === 'call') {
      tag = '<span class="bias-tag bias-call">' + U.escapeHtml(t('an.biasCall')) + '</span>';
      text = t('an.biasCallText');
    } else if (result.bias === 'put') {
      tag = '<span class="bias-tag bias-put">' + U.escapeHtml(t('an.biasPut')) + '</span>';
      text = t('an.biasPutText');
    } else {
      tag = '<span class="bias-tag bias-flat">' + U.escapeHtml(t('an.biasFlat')) + '</span>';
      text = t('an.biasFlatText');
    }
    el.innerHTML = tag + '<span class="muted small">' + U.escapeHtml(text) + '</span>';
  }

  function render(result) {
    renderSide('res-ce', t('f.call'), result.ce, false, result.bias === 'call');
    renderSide('res-pe', t('f.put'), result.pe, true, result.bias === 'put');
    renderBias(result);
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
    render(result);
    return result;
  }

  function reset() {
    U.clearCandle('an-ce');
    U.clearCandle('an-pe');
    U.$('atm-open').value = '';
    U.showErrors('an-ce-err', []);
    U.showErrors('an-pe-err', []);
    U.$('analyser-output').hidden = true;
    APP.state.analyser = null;
    renderAtm();
  }

  function loadSample() {
    U.$('atm-open').value = '23670';
    U.writeCandle('an-ce', { o: 148.5, h: 162.75, l: 141.2, c: 159.9 });
    U.writeCandle('an-pe', { o: 155.0, h: 158.4, l: 132.6, c: 137.15 });
    renderAtm();
    run();
  }

  function init() {
    U.$('btn-analyse').addEventListener('click', run);
    U.$('btn-analyser-reset').addEventListener('click', reset);
    U.$('btn-analyser-sample').addEventListener('click', loadSample);
    U.$('atm-open').addEventListener('input', renderAtm);

    /* Enter anywhere in the candle inputs runs the analysis. */
    U.$$('#panel-analyser .candle-box input').forEach(function (input) {
      input.addEventListener('keydown', function (e) { if (e.key === 'Enter') run(); });
    });

    /* Hand-off buttons are rendered with the results, so delegate. */
    U.$('analyser-output').addEventListener('click', function (e) {
      var btn = e.target.closest('[data-send-t1]');
      if (btn) APP.t1helper.importFromAnalyser(btn.getAttribute('data-send-t1'));
    });
  }

  APP.analyser = {
    init: init,
    run: run,
    reset: reset,
    analyse: analyse,
    analyseSide: analyseSide,
    atmStrike: atmStrike,
    renderAtm: renderAtm
  };
})(window.APP);
