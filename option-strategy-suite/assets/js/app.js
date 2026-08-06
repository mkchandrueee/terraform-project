/* Bootstrap: shared state, tab routing, language toggle, settings drawer and
   the generated guide / formula reference. */
(function (APP) {
  'use strict';

  APP.state = APP.state || { analyser: null, t1: null, pullback: null };

  var U = APP.util;
  function t(key, vars) { return APP.i18n.t(key, vars); }

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

  /* Re-run whichever tools already have results so edits show up immediately. */
  function recomputeAll() {
    if (APP.state.analyser) APP.analyser.run();
    if (APP.state.t1) APP.t1helper.run();
    if (APP.state.pullback) APP.pullback.run();
    APP.t1helper.renderPreview();
    renderGuide();
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
      flash(t('cfg.saved'));
    });

    U.$('btn-settings-reset').addEventListener('click', function () {
      APP.config.reset();
      fillSettingsInputs();
      recomputeAll();
      flash(t('cfg.restored'));
    });

    fillSettingsInputs();
  }

  /* ---------- language ---------- */
  function initLanguage() {
    APP.i18n.init();
    U.$('btn-lang').addEventListener('click', function () {
      APP.i18n.set(APP.i18n.get() === 'ta' ? 'en' : 'ta');
    });
    /* Generated markup is not covered by data-i18n, so redraw it on switch. */
    APP.i18n.onChange(function () {
      APP.analyser.renderAtm();
      recomputeAll();
    });
  }

  /* ---------- guide tab ---------- */
  var PHASES = [
    { title: 'g.p1', steps: ['g.p1s1', 'g.p1s2'], start: 1 },
    { title: 'g.p2', steps: ['g.p2s3', 'g.p2s4', 'g.p2s5'], start: 3 },
    { title: 'g.p3', steps: ['g.p3s6', 'g.p3s7', 'g.p3s8', 'g.p3s9', 'g.p3s10'], start: 6 },
    { title: 'g.p4', steps: ['g.p4s11', 'g.p4s12', 'g.p4s13'], start: 11 }
  ];

  function formulaItems(cfg) {
    var entryTerm = cfg.entryBufferPct ? ' + ' + cfg.entryBufferPct + '% × range' : '';
    var slTerm = cfg.slBufferPct ? ' − ' + cfg.slBufferPct + '% × range' : '';
    return [
      {
        title: 'g.f1', note: 'g.f1n',
        code:
          'range     = high − low\n' +
          'entry     = high' + entryTerm + '\n' +
          'stop loss = low' + slTerm + '\n' +
          'Target 1  = entry + ' + cfg.t1Multiplier + ' × range\n' +
          'confirm   = a 5-min close ≥ entry + ' + cfg.tickSize
      },
      {
        title: 'g.f2', note: 'g.f2n',
        code: 'strength = 50% × close position + 30% × body ÷ range + 20% × (close > open)'
      },
      {
        title: 'g.f3', note: 'g.f3n',
        code:
          'check 1 (40)   direction — candle closed up' +
            (cfg.sideAwareDirection >= 1 ? ' (down on a put trade)' : '') + '\n' +
          'check 2 (15)   body strength — body ÷ range ≥ ' + cfg.bodyStrong + '\n' +
          '        (7.5)   partial credit from ' + cfg.bodyModerate + ' to ' + cfg.bodyStrong + '\n' +
          'check 3 (40)   close position — close ≥ ' + cfg.minClosePos + ' of range\n' +
          'momentum = floor(sum of the weights earned)\n' +
          '\n' +
          'check 4 (gate) T1 breakout — close > T1 level   ← decisive\n' +
          '\n' +
          'verdict = WAIT if check 4 failed, else\n' +
          '          HOLD → T2 at momentum ≥ ' + cfg.holdThreshold + ',\n' +
          '          PARTIAL BOOK at ≥ ' + cfg.partialThreshold + ', otherwise BOOK NOW\n' +
          'reward ratio = (T2 − T1) ÷ (T1 − entry)'
      },
      {
        title: 'g.f4', note: 'g.f4n',
        code:
          'liquidity score = 45% × close position + 30% × body ÷ range\n' +
          '                + 15% × (close > open) + 10% × share of combined range\n' +
          'side     = whichever of CE / PE scores higher\n' +
          'zone 1   = low + ' + cfg.zone1Retrace + ' × range\n' +
          'zone 2   = low + ' + cfg.zone2Retrace + ' × range\n' +
          'Target 1 = high + ' + cfg.pullbackTargetMult + ' × range'
      }
    ];
  }

  function renderGuide() {
    var cfg = APP.config.get();
    var html = PHASES.map(function (phase) {
      var steps = phase.steps.map(function (key) { return '<li>' + t(key) + '</li>'; }).join('');
      return '<h3 class="phase">' + U.escapeHtml(t(phase.title)) + '</h3>' +
             '<ol class="sop" start="' + phase.start + '">' + steps + '</ol>';
    }).join('');

    html += '<h3 class="phase">' + U.escapeHtml(t('g.formulas')) + '</h3>' +
            '<p class="muted small">' + U.escapeHtml(t('g.formulasDesc')) + '</p>' +
            '<div class="formula-list">' +
              formulaItems(cfg).map(function (item) {
                return '<div class="formula"><h4>' + U.escapeHtml(t(item.title)) + '</h4>' +
                       '<code>' + U.escapeHtml(item.code) + '</code>' +
                       '<p>' + U.escapeHtml(t(item.note)) + '</p></div>';
              }).join('') +
            '</div>';

    U.$('guide-body').innerHTML = html;
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
    initLanguage();
    initTabs();
    initSettings();
    initClearAll();
    APP.analyser.init();
    APP.t1helper.init();
    APP.pullback.init();
    APP.analyser.renderAtm();
    renderGuide();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window.APP);
