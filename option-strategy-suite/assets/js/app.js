/* Bootstrap: shared state, tab routing, settings drawer, formula reference. */
(function (APP) {
  'use strict';

  APP.state = APP.state || { analyser: null, t1: null, pullback: null };

  var U = APP.util;

  /* ---------- tabs ---------- */
  var tabs = {
    show: function (name) {
      U.$$('.tab').forEach(function (tab) {
        var active = tab.getAttribute('data-panel') === name;
        tab.classList.toggle('is-active', active);
        tab.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      U.$$('.panel').forEach(function (panel) {
        var active = panel.id === 'panel-' + name;
        panel.classList.toggle('is-active', active);
        panel.hidden = !active;
      });
      if (window.location.hash !== '#' + name) {
        try { history.replaceState(null, '', '#' + name); } catch (e) { /* file:// */ }
      }
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };
  APP.tabs = tabs;

  function initTabs() {
    U.$$('.tab').forEach(function (tab) {
      tab.addEventListener('click', function () { tabs.show(tab.getAttribute('data-panel')); });
    });
    var hash = (window.location.hash || '').replace('#', '');
    if (['analyser', 't1', 'pullback', 'guide'].indexOf(hash) !== -1) tabs.show(hash);
  }

  /* ---------- settings drawer ---------- */
  var CFG_FIELDS = Object.keys(APP.config.DEFAULTS);

  function fillSettingsInputs() {
    var cfg = APP.config.get();
    CFG_FIELDS.forEach(function (key) {
      var el = U.$('cfg-' + key);
      if (el) el.value = String(cfg[key]);
    });
  }

  function readSettingsInputs() {
    var patch = {};
    CFG_FIELDS.forEach(function (key) {
      var el = U.$('cfg-' + key);
      if (el) patch[key] = U.num(el.value);
    });
    return patch;
  }

  function flash(message) {
    var el = U.$('settings-flash');
    el.textContent = message;
    window.setTimeout(function () { el.textContent = ''; }, 2200);
  }

  /* Re-run whichever tools already have results so edited coefficients show up. */
  function recomputeAll() {
    if (APP.state.analyser) APP.analyser.run();
    if (APP.state.t1) APP.t1helper.run();
    if (APP.state.pullback) APP.pullback.run();
    renderFormulas();
  }

  function initSettings() {
    var drawer = U.$('settings-drawer');
    var toggle = U.$('btn-settings');

    toggle.addEventListener('click', function () {
      var open = drawer.hidden;
      drawer.hidden = !open;
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) fillSettingsInputs();
    });

    U.$('btn-settings-save').addEventListener('click', function () {
      APP.config.save(readSettingsInputs());
      fillSettingsInputs();
      recomputeAll();
      flash('Saved.');
    });

    U.$('btn-settings-reset').addEventListener('click', function () {
      APP.config.reset();
      fillSettingsInputs();
      recomputeAll();
      flash('Defaults restored.');
    });

    fillSettingsInputs();
  }

  /* ---------- formula reference (guide tab) ---------- */
  function renderFormulas() {
    var cfg = APP.config.get();
    var entryTerm = cfg.entryBufferPct ? ' + ' + cfg.entryBufferPct + '% × range' : '';
    var slTerm = cfg.slBufferPct ? ' − ' + cfg.slBufferPct + '% × range' : '';

    var items = [
      {
        title: 'Option Analyser — entry, Target 1, stop loss',
        code:
          'range     = high − low\n' +
          'entry     = high' + entryTerm + '\n' +
          'stop loss = low' + slTerm + '\n' +
          'Target 1  = entry + ' + cfg.t1Multiplier + ' × range\n' +
          'confirm   = a 5-min close ≥ entry + ' + cfg.tickSize,
        note: 'The first candle\'s high is the breakout level and its low is the invalidation level, ' +
              'so risk equals the candle range and Target 1 is a measured move of that same range.'
      },
      {
        title: 'Option Analyser — first-candle strength',
        code: 'strength = 50% × close position + 30% × body ÷ range + 20% × (close > open)',
        note: 'Only used to flag which side to watch first. It never replaces the confirmation close.'
      },
      {
        title: 'T1 Decision Helper — momentum score and gate',
        code:
          'check 1 (40) direction — candle closed up' +
            (cfg.sideAwareDirection >= 1 ? ' (down on a put trade)' : '') + '\n' +
          'check 2 (30) body strength — body ÷ range ≥ ' + cfg.minBodyRatio + '\n' +
          'check 3 (30) close position — close ≥ ' + cfg.minClosePos + ' of range\n' +
          'momentum = sum of the weights that passed\n' +
          '\n' +
          'check 4 (gate) T1 breakout — close > T1 level   ← decisive\n' +
          '\n' +
          'verdict = WAIT if check 4 failed, else\n' +
          '          HOLD → T2 at momentum ≥ ' + cfg.holdThreshold + ',\n' +
          '          PARTIAL BOOK at ≥ ' + cfg.partialThreshold + ', otherwise BOOK NOW\n' +
          'reward ratio = (T2 − T1) ÷ (T1 − entry)',
        note: 'Check 4 sits outside the momentum score: it asks whether the breakout above T1 actually ' +
              'happened, and it is the pre-trade gate the guide requires at step 10.'
      },
      {
        title: 'Stoploss Pullback Entry — side and zones',
        code:
          'liquidity score = 45% × close position + 30% × body ÷ range\n' +
          '                + 15% × (close > open) + 10% × share of combined range\n' +
          'side    = whichever of CE / PE scores higher\n' +
          'zone 1  = low + ' + cfg.zone1Retrace + ' × range\n' +
          'zone 2  = low + ' + cfg.zone2Retrace + ' × range\n' +
          'Target 1 = high + ' + cfg.pullbackTargetMult + ' × range',
        note: 'Entries sit inside the first-candle range rather than above it — the setup buys the ' +
              'pullback into liquidity, which is why no stop loss is placed.'
      }
    ];

    U.$('formula-list').innerHTML = items.map(function (item) {
      return '<div class="formula"><h4>' + U.escapeHtml(item.title) + '</h4>' +
             '<code>' + U.escapeHtml(item.code) + '</code>' +
             '<p>' + U.escapeHtml(item.note) + '</p></div>';
    }).join('');
  }

  /* ---------- clear everything ---------- */
  function initClearAll() {
    U.$('btn-clear-all').addEventListener('click', function () {
      APP.analyser.reset();
      APP.t1helper.reset();
      APP.pullback.reset();
      APP.tabs.show('analyser');
    });
  }

  function init() {
    APP.config.load();
    initTabs();
    initSettings();
    initClearAll();
    APP.analyser.init();
    APP.t1helper.init();
    APP.pullback.init();
    renderFormulas();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window.APP);
