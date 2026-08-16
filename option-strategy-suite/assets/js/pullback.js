/* Tool 3 — Stoploss Pullback Entry (Phase 4, steps 11–13).

   Input : the original 09:15–09:20 call and put candles.
   Output: the side to trade (call buy / put buy), zone 1 as the entry price
           and Target 1. No stop loss is produced — the setup is structural. */
(function (APP) {
  'use strict';

  var U = APP.util;
  function t(key, vars) { return APP.i18n.t(key, vars); }

  /* The original qualifies each leg on three things before it will trade it,
     and says so on its detail tab: direction, body strength, close position.
     A near-bodiless candle is called out as a doji and refused outright. */
  function qualify(candle, cfg) {
    var s = U.candleStats(candle);
    var doji = s.bodyRatio < cfg.pbDojiBody;
    var checks = [
      { key: 'direction', pass: s.bullish,
        detail: t(s.bullish ? 'pb.d.bullish' : 'pb.d.bearish') },
      { key: 'body', pass: s.bodyRatio >= cfg.pbStrongBody,
        detail: t(doji ? 'pb.d.doji' : (s.bodyRatio >= cfg.pbStrongBody ? 'pb.d.bodyStrong' : 'pb.d.bodyWeak'),
                  { pct: U.pct(s.bodyRatio) }) },
      { key: 'close', pass: s.closePos > cfg.pbMinClosePos,
        detail: t(s.closePos > cfg.pbMinClosePos ? 'pb.d.closeUp' : 'pb.d.closeDown',
                  { pct: U.pct(s.closePos) }) }
    ];
    var passed = checks.filter(function (c) { return c.pass; }).length;
    return {
      checks: checks, passed: passed, doji: doji,
      verdict: doji ? 'doji' : (passed === checks.length ? 'good' : 'notrade')
    };
  }

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

  /* Reproduces the original tool on the reference leg (O61 H97 L61 C86):
     zones 70 / 74.7 / 79, stop 58, targets 104.7 / 124.7 / 154.7. */
  function levelsFor(candle, cfg) {
    var range = candle.h - candle.l;
    var zone2 = candle.l + cfg.pbZone2 * range;
    var step = cfg.pbTargetRound || 10;
    var roundStep = function (mult) { return Math.round((mult * range) / step) * step; };

    var t1Step = roundStep(cfg.pbT1Mult);
    var t2Step = roundStep(cfg.pbT2Mult);
    var t3Step = roundStep(cfg.pbT3Mult);

    return {
      range: range,
      zone1: candle.l + cfg.pbZone1 * range,
      zone2: zone2,
      zone3: candle.l + cfg.pbZone3 * range,
      stopLoss: Math.round(candle.l * (1 - cfg.pbSlPct / 100)),
      targets: [
        { level: zone2 + t1Step, step: t1Step },
        { level: zone2 + t2Step, step: t2Step },
        { level: zone2 + t3Step, step: t3Step }
      ]
    };
  }

  function analyse(ceCandle, peCandle, cfg) {
    var combined = (ceCandle.h - ceCandle.l) + (peCandle.h - peCandle.l);
    var ce = scoreSide(ceCandle, combined);
    var pe = scoreSide(peCandle, combined);

    ce.qual = qualify(ceCandle, cfg);
    pe.qual = qualify(peCandle, cfg);

    /* Neither leg qualifying is a real outcome, not a fallback: the original
       answers "WAIT — No Signal" rather than picking the least bad side. */
    var ceOk = ce.qual.verdict === 'good';
    var peOk = pe.qual.verdict === 'good';
    var side;
    if (ceOk && peOk) side = ce.score >= pe.score ? 'call' : 'put';
    else if (ceOk) side = 'call';
    else if (peOk) side = 'put';
    else side = null;

    if (!side) {
      return { side: null, wait: true, ce: ce, pe: pe, ceCandle: ceCandle, peCandle: peCandle };
    }

    var chosenCandle = side === 'call' ? ceCandle : peCandle;
    var margin = Math.abs(ce.score - pe.score);

    return {
      side: side,
      wait: false,
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

  /* The original prints one decimal with a trailing .0 trimmed. */
  function px(n) {
    if (!isFinite(n)) return '—';
    var s1 = (Math.round(n * 10) / 10).toFixed(1);
    return '₹' + (s1.endsWith('.0') ? s1.slice(0, -2) : s1);
  }

  function sideDetail(label, q, isPut) {
    var badge = q.verdict === 'good' ? t('pb.badgeGood')
              : (q.doji ? t('pb.badgeDoji') : t('pb.badgeNoTrade'));
    return '<div class="leg-detail ' + (isPut ? 'side-put' : 'side-call') + '">' +
      '<div class="leg-head"><span class="dot ' + (isPut ? 'dot-put' : 'dot-call') + '"></span>' +
        U.escapeHtml(label) +
        '<span class="leg-badge is-' + q.verdict + '">' + U.escapeHtml(badge) + '</span></div>' +
      '<ul class="leg-checks">' +
        q.checks.map(function (c) {
          return '<li class="' + (c.pass ? 'pass' : 'fail') + '">' +
            '<span aria-hidden="true">' + (c.pass ? '✓' : '✕') + '</span>' +
            U.escapeHtml(c.detail) + '</li>';
        }).join('') +
      '</ul></div>';
  }

  function renderDetail(result) {
    U.$('pb-detail').innerHTML =
      '<div class="card-head"><h3>' + U.escapeHtml(t('pb.detailTitle')) + '</h3>' +
      '<p class="muted">' + U.escapeHtml(t('pb.detailDesc')) + '</p></div>' +
      '<div class="leg-grid">' +
        sideDetail(t('f.call'), result.ce.qual, false) +
        sideDetail(t('f.put'), result.pe.qual, true) +
      '</div>';
  }

  /* ---------- rendering ---------- */
  function render(result) {
    if (result.wait) {
      U.$('pb-verdict').innerHTML =
        '<div class="muted small" style="margin-bottom:12px">' + U.escapeHtml(t('pb.decision')) + '</div>' +
        '<div class="pb-side pb-wait">' + U.escapeHtml(t('pb.wait')) + '</div>' +
        '<p class="verdict-sub">' + U.escapeHtml(t('pb.waitText')) + '</p>';
      U.$('pb-levels').innerHTML = '';
      U.$('pb-rules').innerHTML = '';
      renderDetail(result);
      U.$('pullback-output').hidden = false;
      return;
    }

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

    var L = result.levels;
    function zone(cls, label, value, note) {
      return '<div class="zone ' + cls + '"><div class="zone-label">' + U.escapeHtml(label) + '</div>' +
             '<div class="zone-value">' + px(value) + '</div>' +
             '<div class="zone-note">' + U.escapeHtml(note) + '</div></div>';
    }
    function trow(label, value, pts, cls, badge) {
      return '<tr class="' + cls + '">' +
        '<td class="tgt-label">' + U.escapeHtml(label) + '</td>' +
        '<td class="tgt-level">' + px(value) + '</td>' +
        '<td class="tgt-pts">' + pts + '</td>' +
        '<td class="tgt-action"><span class="tgt-badge ' + cls + '">' + U.escapeHtml(badge) + '</span></td></tr>';
    }

    U.$('pb-levels').innerHTML = '' +
      '<div class="card-head"><h3><span class="step-pill">' + U.escapeHtml(t('pb.step13')) + '</span> ' +
        U.escapeHtml(t('pb.zonesTitle')) + '</h3>' +
      '<p class="muted">' + U.escapeHtml(t('pb.zonesDesc')) + '</p></div>' +
      '<div class="zone-grid">' +
        zone('zone-1', t('pb.zone1'), L.zone1, t('pb.zone1Note')) +
        zone('zone-2 is-best', t('pb.zone2'), L.zone2, t('pb.zone2Note')) +
        zone('zone-3', t('pb.zone3'), L.zone3, t('pb.zone3Note')) +
      '</div>' +
      '<div class="table-scroll" style="margin-top:16px"><table class="targets"><tbody>' +
        trow(t('pb.stopLoss'), L.stopLoss, '−' + U.fmt(L.zone2 - L.stopLoss, 1) + t('an.pts'), 'row-sl', t('an.exitAll')) +
        trow(t('an.target1'), L.targets[0].level, '+' + L.targets[0].step + t('an.pts'), 'row-t1', t('an.book', { pct: 40 })) +
        trow(t('an.target2'), L.targets[1].level, '+' + L.targets[1].step + t('an.pts'), 'row-t2', t('an.book', { pct: 40 })) +
        trow(t('an.target3'), L.targets[2].level, '+' + L.targets[2].step + t('an.pts'), 'row-t3', t('an.hold', { pct: 20 })) +
      '</tbody></table></div>' +
      '<p class="muted small" style="margin-top:10px">' + U.escapeHtml(t('pb.fromZone2')) + '</p>';

    U.$('pb-rules').innerHTML =
      '<div class="card-head"><h3>' + U.escapeHtml(t('pb.rulesTitle')) + '</h3></div>' +
      '<ol class="action-plan">' +
        [1, 2, 3, 4, 5].map(function (n) {
          return '<li>' + U.escapeHtml(t('pb.rule' + n, {
            side: t(isCall ? 'an.buyCall' : 'an.buyPut'),
            zone1: px(L.zone1), zone2: px(L.zone2), zone3: px(L.zone3),
            sl: px(L.stopLoss), t1: px(L.targets[0].level),
            t2: px(L.targets[1].level), t3: px(L.targets[2].level)
          })) + '</li>';
        }).join('') +
      '</ol>';

    renderDetail(result);

    function row(name, ceVal, peVal, ceWins) {
      return '<tr><td>' + U.escapeHtml(name) + '</td>' +
        '<td class="' + (ceWins === true ? 'win' : '') + '">' + ceVal + '</td>' +
        '<td class="' + (ceWins === false ? 'win' : '') + '">' + peVal + '</td></tr>';
    }
    var c = result.ce, p = result.pe;

    U.$('pb-compare').innerHTML = '' +
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
