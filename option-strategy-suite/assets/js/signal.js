/* Tool 4 — Trade Signal (market-standard confluence, win estimate, expected
   profit and the full metric set).

   Everything here is computed from values you type. The app has no market
   data feed, so the indicator readings come from your chart: leave any of
   them blank and that check is skipped rather than guessed at. */
(function (APP) {
  'use strict';

  var U = APP.util;
  var side = 'call';

  function t(key, vars) { return APP.i18n.t(key, vars); }
  function money(n) { return '₹' + U.fmt(n); }
  function money0(n) { return '₹' + U.fmt(n, 0); }

  /* ---------- confluence: the market-standard filters ---------- */
  function confluence(inp, cfg, isCall) {
    var checks = [];

    function add(id, name, weight, state, detail) {
      checks.push({ id: id, name: name, weight: weight, state: state, detail: detail });
    }

    /* 1. Price vs VWAP — the intraday fair-value line. */
    if (isFinite(inp.spot) && isFinite(inp.vwap)) {
      var vwapOk = isCall ? inp.spot > inp.vwap : inp.spot < inp.vwap;
      add('vwap', t('sg.c.vwap'), 20, vwapOk ? 'pass' : 'fail',
        t(vwapOk ? 'sg.c.vwapOk' : 'sg.c.vwapNo', {
          spot: U.fmt(inp.spot, 2), vwap: U.fmt(inp.vwap, 2),
          gap: U.fmt(Math.abs(inp.spot - inp.vwap), 2)
        }));
    } else {
      add('vwap', t('sg.c.vwap'), 20, 'skip', t('sg.c.skip'));
    }

    /* 2. Moving-average alignment. */
    if (isFinite(inp.spot) && isFinite(inp.ema20)) {
      var emaOk = isCall ? inp.spot > inp.ema20 : inp.spot < inp.ema20;
      if (isFinite(inp.ema50)) {
        emaOk = emaOk && (isCall ? inp.ema20 >= inp.ema50 : inp.ema20 <= inp.ema50);
      }
      add('ema', t('sg.c.ema'), 15, emaOk ? 'pass' : 'fail',
        t(emaOk ? 'sg.c.emaOk' : 'sg.c.emaNo', {
          spot: U.fmt(inp.spot, 2), ema20: U.fmt(inp.ema20, 2),
          ema50: isFinite(inp.ema50) ? U.fmt(inp.ema50, 2) : '—'
        }));
    } else {
      add('ema', t('sg.c.ema'), 15, 'skip', t('sg.c.skip'));
    }

    /* 3. RSI regime — momentum present, but not already exhausted. */
    if (isFinite(inp.rsi)) {
      var lo = isCall ? cfg.rsiMin : 100 - cfg.rsiMax;
      var hi = isCall ? cfg.rsiMax : 100 - cfg.rsiMin;
      var rsiOk = inp.rsi >= lo && inp.rsi <= hi;
      add('rsi', t('sg.c.rsi'), 15, rsiOk ? 'pass' : 'fail',
        t(rsiOk ? 'sg.c.rsiOk' : 'sg.c.rsiNo', {
          rsi: U.fmt(inp.rsi, 1), lo: U.fmt(lo, 0), hi: U.fmt(hi, 0)
        }));
    } else {
      add('rsi', t('sg.c.rsi'), 15, 'skip', t('sg.c.skip'));
    }

    /* 4. Volume confirmation on the breakout candle. */
    if (isFinite(inp.volRatio)) {
      var volOk = inp.volRatio >= cfg.volumeMin;
      add('volume', t('sg.c.volume'), 10, volOk ? 'pass' : 'fail',
        t(volOk ? 'sg.c.volumeOk' : 'sg.c.volumeNo', {
          ratio: U.fmt(inp.volRatio, 2), min: U.fmt(cfg.volumeMin, 2)
        }));
    } else {
      add('volume', t('sg.c.volume'), 10, 'skip', t('sg.c.skip'));
    }

    /* 5. Volatility regime — India VIX. */
    if (isFinite(inp.vix)) {
      var vixOk = inp.vix <= cfg.vixMax;
      add('vix', t('sg.c.vix'), 10, vixOk ? 'pass' : 'fail',
        t(vixOk ? 'sg.c.vixOk' : 'sg.c.vixNo', { vix: U.fmt(inp.vix, 2), max: U.fmt(cfg.vixMax, 0) }));
    } else {
      add('vix', t('sg.c.vix'), 10, 'skip', t('sg.c.skip'));
    }

    /* 6. Is the target actually reachable in the day's range? */
    if (isFinite(inp.refRange) && inp.refRange > 0 && isFinite(inp.t2) && isFinite(inp.entry)) {
      var reach = (inp.t2 - inp.entry) / inp.refRange;
      var reachOk = reach <= cfg.atrReachMax;
      add('reach', t('sg.c.reach'), 15, reachOk ? 'pass' : 'fail',
        t(reachOk ? 'sg.c.reachOk' : 'sg.c.reachNo', {
          reach: U.fmt(reach, 2), max: U.fmt(cfg.atrReachMax, 2), range: U.fmt(inp.refRange)
        }));
    } else {
      add('reach', t('sg.c.reach'), 15, 'skip', t('sg.c.skip'));
    }

    /* 7. Risk:reward gate. */
    var risk = inp.entry - inp.sl;
    var reward = inp.t2 - inp.entry;
    if (risk > 0 && reward > 0) {
      var rr = reward / risk;
      var rrOk = rr >= cfg.minRR;
      add('rr', t('sg.c.rr'), 15, rrOk ? 'pass' : 'fail',
        t(rrOk ? 'sg.c.rrOk' : 'sg.c.rrNo', { rr: U.fmt(rr, 2), min: U.fmt(cfg.minRR, 2) }));
    } else {
      add('rr', t('sg.c.rr'), 15, 'skip', t('sg.c.skip'));
    }

    /* 8. Time of day — avoid the midday chop and the closing scramble. */
    if (isFinite(inp.minuteOfDay)) {
      var m = inp.minuteOfDay;
      var early = m < 9 * 60 + 20;
      var chop = m >= 11 * 60 + 30 && m < 13 * 60;
      var late = m > 14 * 60 + 45;
      var timeOk = !early && !chop && !late;
      add('time', t('sg.c.time'), 10, timeOk ? 'pass' : 'fail',
        t(timeOk ? 'sg.c.timeOk' : (early ? 'sg.c.timeEarly' : (chop ? 'sg.c.timeChop' : 'sg.c.timeLate')),
          { time: inp.timeText }));
    } else {
      add('time', t('sg.c.time'), 10, 'skip', t('sg.c.skip'));
    }

    /* 9. The T1 Decision Helper's own read, when one has been run. */
    if (APP.state.t1) {
      var mom = APP.state.t1.momentum;
      var momOk = mom >= cfg.holdThreshold;
      add('helper', t('sg.c.helper'), 20, momOk ? 'pass' : 'fail',
        t(momOk ? 'sg.c.helperOk' : 'sg.c.helperNo', { momentum: mom, min: cfg.holdThreshold }));
    } else {
      add('helper', t('sg.c.helper'), 20, 'skip', t('sg.c.skipHelper'));
    }

    var earned = 0, available = 0, total = 0, used = 0;
    checks.forEach(function (c) {
      total += c.weight;
      if (c.state === 'skip') return;
      available += c.weight;
      used += 1;
      if (c.state === 'pass') earned += c.weight;
    });

    return {
      checks: checks,
      score: available > 0 ? (earned / available) * 100 : NaN,
      used: used,
      count: checks.length,
      coverage: total > 0 ? available / total : 0
    };
  }

  /* ---------- money, risk and expectancy ---------- */
  function metrics(inp, cfg, winPct) {
    var qty = inp.lots * cfg.lotSize;
    var costs = inp.lots * cfg.costPerLot;

    var riskPts = inp.entry - inp.sl;
    var rewardPts = inp.t2 - inp.entry;
    var rewardT1Pts = inp.t1 - inp.entry;

    var capital = inp.entry * qty;
    var maxLoss = riskPts * qty + costs;
    var profitT1 = rewardT1Pts * qty - costs;
    var profitT2 = rewardPts * qty - costs;

    /* The honest benchmark: below this win rate the setup loses money
       however good the story around it sounds. */
    var breakeven = (riskPts + rewardPts) > 0 ? riskPts / (riskPts + rewardPts) * 100 : NaN;

    var p = winPct / 100;
    var ev = p * profitT2 - (1 - p) * maxLoss;
    var evPerRisk = maxLoss > 0 ? ev / maxLoss : NaN;

    /* Kelly on the net payoff ratio, reported at quarter size — full Kelly is
       far too aggressive for a single intraday setup. */
    var payoff = maxLoss > 0 ? profitT2 / maxLoss : NaN;
    var kelly = isFinite(payoff) && payoff > 0 ? (p * payoff - (1 - p)) / payoff : NaN;

    var riskPerLot = riskPts * cfg.lotSize + cfg.costPerLot;
    var allowedRisk = isFinite(inp.account) ? inp.account * (cfg.riskPctOfAccount / 100) : NaN;
    var suggestedLots = isFinite(allowedRisk) && riskPerLot > 0
      ? Math.max(0, Math.floor(allowedRisk / riskPerLot)) : NaN;

    return {
      qty: qty, costs: costs, capital: capital,
      riskPts: riskPts, rewardPts: rewardPts, rewardT1Pts: rewardT1Pts,
      maxLoss: maxLoss, profitT1: profitT1, profitT2: profitT2,
      rr: riskPts > 0 ? rewardPts / riskPts : NaN,
      rrT1: riskPts > 0 ? rewardT1Pts / riskPts : NaN,
      breakeven: breakeven,
      ev: ev, evPerRisk: evPerRisk,
      kellyQuarter: isFinite(kelly) ? U.clamp(kelly / 4, 0, 0.25) : NaN,
      riskOfAccount: isFinite(inp.account) && inp.account > 0 ? maxLoss / inp.account * 100 : NaN,
      suggestedLots: suggestedLots
    };
  }

  function evaluate(inp, cfg, tradeSide) {
    var isCall = tradeSide === 'call';
    var conf = confluence(inp, cfg, isCall);

    /* The win estimate is your own base rate nudged by how much confluence
       lined up — not a backtested probability. */
    var score = isFinite(conf.score) ? conf.score : 50;
    var winPct = U.clamp(
      cfg.baseWinRate + (score - 50) * cfg.winSensitivity,
      cfg.winFloor, cfg.winCeiling
    );

    var m = metrics(inp, cfg, winPct);

    var verdict, headline;
    if (!(m.ev > 0) || !(winPct > m.breakeven)) {
      verdict = 'skip';
      headline = t('sg.skip');
    } else if (score >= cfg.takeThreshold) {
      verdict = 'take';
      headline = t('sg.take');
    } else {
      verdict = 'caution';
      headline = t('sg.caution');
    }

    return {
      side: tradeSide, inputs: inp, conf: conf, score: score,
      winPct: winPct, m: m, verdict: verdict, headline: headline,
      edge: winPct - m.breakeven
    };
  }

  /* ---------- rendering ---------- */
  var VERDICT_CLASS = { take: 'v-hold', caution: 'v-partial', skip: 'v-book' };
  var STATE_ICON = { pass: '✓', fail: '✕', skip: '–' };

  function tile(label, value, cls) {
    return '<div class="metric-tile ' + (cls || '') + '">' +
      '<div class="tile-label">' + U.escapeHtml(label) + '</div>' +
      '<div class="tile-value">' + value + '</div></div>';
  }

  function render(r) {
    var m = r.m;
    var sideLabel = t(r.side === 'put' ? 'sg.putTrade' : 'sg.callTrade');

    U.$('sg-verdict').innerHTML = '' +
      '<div class="muted small" style="margin-bottom:12px">' + U.escapeHtml(sideLabel) + '</div>' +
      '<div class="verdict-badge ' + VERDICT_CLASS[r.verdict] + '">' + U.escapeHtml(r.headline) + '</div>' +
      '<p class="verdict-sub">' + U.escapeHtml(t('sg.' + r.verdict + 'Text', {
        score: U.fmt(r.score, 0),
        win: U.fmt(r.winPct, 0),
        breakeven: U.fmt(m.breakeven, 0),
        ev: money0(m.ev)
      })) + '</p>';

    U.$('sg-tiles').innerHTML = '' +
      '<div class="tile-grid">' +
        tile(t('sg.winEstimate'), U.fmt(r.winPct, 0) + '%', 'tile-primary') +
        tile(t('sg.expectedProfit'), money0(m.profitT2), m.profitT2 > 0 ? 'tile-good' : 'tile-bad') +
        tile(t('sg.expectedValue'), money0(m.ev), m.ev > 0 ? 'tile-good' : 'tile-bad') +
        tile(t('sg.breakevenWin'), U.fmt(m.breakeven, 0) + '%', '') +
      '</div>' +
      '<p class="edge-note ' + (r.edge > 0 ? 'is-good' : 'is-bad') + '">' +
        U.escapeHtml(t(r.edge > 0 ? 'sg.edgeGood' : 'sg.edgeBad', {
          edge: U.fmt(Math.abs(r.edge), 1)
        })) + '</p>';

    U.$('sg-checks').innerHTML = r.conf.checks.map(function (c) {
      return '<li class="check ' + c.state + '">' +
        '<span class="check-icon" aria-hidden="true">' + STATE_ICON[c.state] + '</span>' +
        '<span class="check-body">' +
          '<span class="check-name">' + U.escapeHtml(c.name) +
            '<span class="weight-tag">' + c.weight + '</span></span>' +
          '<span class="check-detail">' + U.escapeHtml(c.detail) + '</span>' +
        '</span>' +
        '<span class="check-verdict">' + U.escapeHtml(t('sg.state.' + c.state)) + '</span>' +
      '</li>';
    }).join('');

    U.$('sg-conf-head').innerHTML = '' +
      '<div class="signal-num"><span>' + U.escapeHtml(t('sg.confluence')) + '</span><b>' +
        U.fmt(r.score, 0) + '%</b></div>' +
      '<div class="bar"><i style="width:' + U.clamp(r.score, 0, 100) + '%"></i></div>' +
      '<p class="muted small" style="margin-top:8px">' +
        U.escapeHtml(t('sg.coverage', { used: r.conf.used, total: r.conf.count })) + '</p>';

    function row(label, value) {
      return '<tr><td>' + U.escapeHtml(label) + '</td><td>' + value + '</td></tr>';
    }
    U.$('sg-metrics').innerHTML = '' +
      '<div class="card-head"><h3>' + U.escapeHtml(t('sg.metrics')) + '</h3></div>' +
      '<div class="table-scroll"><table class="compare metrics-table"><tbody>' +
        row(t('sg.m.qty'), U.fmt(m.qty, 0)) +
        row(t('sg.m.capital'), money0(m.capital)) +
        row(t('sg.m.riskPts'), U.fmt(m.riskPts) + ' / ' + U.fmt(m.rewardPts)) +
        row(t('sg.m.maxLoss'), '<span class="neg">' + money0(m.maxLoss) + '</span>') +
        row(t('sg.m.profitT1'), money0(m.profitT1)) +
        row(t('sg.m.profitT2'), '<span class="pos">' + money0(m.profitT2) + '</span>') +
        row(t('sg.m.rr'), '1 : ' + U.fmt(m.rr, 2) + '  (T1 1 : ' + U.fmt(m.rrT1, 2) + ')') +
        row(t('sg.m.costs'), money0(m.costs)) +
        row(t('sg.m.evPerRisk'), U.fmt(m.evPerRisk, 2) + '×') +
        row(t('sg.m.riskOfAccount'), isFinite(m.riskOfAccount) ? U.fmt(m.riskOfAccount, 2) + '%' : '—') +
        row(t('sg.m.suggestedLots'), isFinite(m.suggestedLots) ? U.fmt(m.suggestedLots, 0) : '—') +
        row(t('sg.m.kelly'), isFinite(m.kellyQuarter) ? U.pct(m.kellyQuarter, 1) : '—') +
      '</tbody></table></div>' +
      '<p class="muted small" style="margin-top:10px">' + U.escapeHtml(t('sg.metricsNote')) + '</p>';

    U.$('signal-output').hidden = false;
  }

  /* ---------- controller ---------- */
  function setSide(next) {
    side = next === 'put' ? 'put' : 'call';
    U.$$('#panel-signal .side-btn').forEach(function (btn) {
      var active = btn.getAttribute('data-side') === side;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-checked', active ? 'true' : 'false');
    });
  }

  function readInputs() {
    var timeText = U.$('sg-time').value;
    var minuteOfDay = NaN;
    if (/^\d{1,2}:\d{2}/.test(timeText)) {
      var parts = timeText.split(':');
      minuteOfDay = Number(parts[0]) * 60 + Number(parts[1]);
    }
    return {
      entry: U.num(U.$('sg-entry').value),
      sl: U.num(U.$('sg-sl').value),
      t1: U.num(U.$('sg-t1').value),
      t2: U.num(U.$('sg-t2').value),
      spot: U.num(U.$('sg-spot').value),
      vwap: U.num(U.$('sg-vwap').value),
      ema20: U.num(U.$('sg-ema20').value),
      ema50: U.num(U.$('sg-ema50').value),
      rsi: U.num(U.$('sg-rsi').value),
      volRatio: U.num(U.$('sg-vol').value),
      vix: U.num(U.$('sg-vix').value),
      refRange: U.num(U.$('sg-range').value),
      lots: Math.max(1, Math.round(U.num(U.$('sg-lots').value)) || 1),
      account: U.num(U.$('sg-account').value),
      timeText: timeText,
      minuteOfDay: minuteOfDay
    };
  }

  function run() {
    var cfg = APP.config.get();
    var inp = readInputs();

    var errors = [];
    [['entry', 'sg.entry'], ['sl', 'sg.sl'], ['t1', 'sg.t1'], ['t2', 'sg.t2']].forEach(function (pair) {
      if (!isFinite(inp[pair[0]]) || inp[pair[0]] <= 0) {
        errors.push(t('t1.err.required', { field: t(pair[1]) }));
      }
    });
    if (!errors.length && !(inp.sl < inp.entry && inp.entry < inp.t1 && inp.t1 <= inp.t2)) {
      errors.push(t('sg.err.ladder'));
    }
    U.showErrors('sg-err', errors);
    if (errors.length) {
      U.$('signal-output').hidden = true;
      APP.state.signal = null;
      return null;
    }

    var result = evaluate(inp, cfg, side);
    APP.state.signal = result;
    render(result);
    APP.alerts.onSignal(result);
    return result;
  }

  function reset() {
    ['sg-entry', 'sg-sl', 'sg-t1', 'sg-t2', 'sg-spot', 'sg-vwap', 'sg-ema20',
     'sg-ema50', 'sg-rsi', 'sg-vol', 'sg-vix', 'sg-range', 'sg-account'
    ].forEach(function (id) { U.$(id).value = ''; });
    U.$('sg-lots').value = '1';
    U.showErrors('sg-err', []);
    U.$('signal-output').hidden = true;
    APP.state.signal = null;
  }

  /* Carry the levels across: the analyser gives entry/SL/T1, and the T1 helper
     ladder gives T2. Falls back to the analyser's own Target 1 for T2. */
  function importLevels(which) {
    var a = APP.state.analyser;
    if (!a) return;
    var r = which === 'put' ? a.pe : a.ce;
    setSide(which);
    U.$('sg-entry').value = r.entry.toFixed(2);
    U.$('sg-sl').value = r.stopLoss.toFixed(2);
    U.$('sg-t1').value = r.target1.toFixed(2);
    U.$('sg-t2').value = r.target2.toFixed(2);
    U.$('sg-range').value = r.range.toFixed(2);
    U.showErrors('sg-err', []);
  }

  function fillTimeNow() {
    var now = new Date();
    U.$('sg-time').value =
      String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0');
  }

  function loadSample() {
    setSide('call');
    U.$('sg-entry').value = '162.75';
    U.$('sg-sl').value = '141.20';
    U.$('sg-t1').value = '184.30';
    U.$('sg-t2').value = '205.85';
    U.$('sg-range').value = '21.55';
    U.$('sg-spot').value = '23712.40';
    U.$('sg-vwap').value = '23680.10';
    U.$('sg-ema20').value = '23668.75';
    U.$('sg-ema50').value = '23640.00';
    U.$('sg-rsi').value = '63.4';
    U.$('sg-vol').value = '1.65';
    U.$('sg-vix').value = '13.8';
    U.$('sg-lots').value = '2';
    U.$('sg-account').value = '200000';
    U.$('sg-time').value = '09:35';
    run();
  }

  function init() {
    U.$$('#panel-signal .side-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setSide(btn.getAttribute('data-side'));
        if (APP.state.signal) run();
      });
    });
    U.$('btn-signal').addEventListener('click', run);
    U.$('btn-sg-reset').addEventListener('click', reset);
    U.$('btn-sg-sample').addEventListener('click', loadSample);
    U.$('btn-sg-now').addEventListener('click', fillTimeNow);
    U.$('btn-sg-import-call').addEventListener('click', function () { importLevels('call'); });
    U.$('btn-sg-import-put').addEventListener('click', function () { importLevels('put'); });
    U.$$('#panel-signal input').forEach(function (input) {
      input.addEventListener('keydown', function (e) { if (e.key === 'Enter') run(); });
    });
  }

  APP.signal = {
    init: init, run: run, reset: reset,
    evaluate: evaluate, confluence: confluence, metrics: metrics
  };
})(window.APP);
