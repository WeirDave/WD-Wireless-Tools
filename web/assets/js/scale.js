(function () {
  'use strict';

  var MM_PER_INCH = 25.4;
  var IN_PER_FT = 12;

  function parseImperial(raw) {
    if (raw == null) return null;
    var s = String(raw).trim().toLowerCase()
      .replace(/[′’]/g, "'")
      .replace(/[″”]/g, '"');
    if (!s) return null;

    if (/^-?\d+(?:\.\d+)?$/.test(s)) {
      return parseFloat(s) * IN_PER_FT;
    }

    var totalIn = 0;
    var matched = false;

    var ftRe = /(-?\d+(?:\.\d+)?)\s*(?:'|ft\b|feet\b|foot\b)/;
    var ftMatch = s.match(ftRe);
    var rest = s;
    if (ftMatch) {
      totalIn += parseFloat(ftMatch[1]) * IN_PER_FT;
      rest = s.slice(ftMatch.index + ftMatch[0].length);
      matched = true;
    }

    rest = rest.trim();
    if (rest) {
      var mixRe = /^(-?\d+)[\s-]+(\d+)\s*\/\s*(\d+)\s*(?:"|in\b|inch\b|inches\b)?/;
      var m = rest.match(mixRe);
      if (m) {
        totalIn += parseInt(m[1], 10) + parseInt(m[2], 10) / parseInt(m[3], 10);
        matched = true;
      } else {
        var fracRe = /^(-?\d+)\s*\/\s*(\d+)\s*(?:"|in\b|inch\b|inches\b)?/;
        m = rest.match(fracRe);
        if (m) {
          totalIn += parseInt(m[1], 10) / parseInt(m[2], 10);
          matched = true;
        } else {
          var inRe = /^(-?\d+(?:\.\d+)?)\s*(?:"|in\b|inch\b|inches\b)?/;
          m = rest.match(inRe);
          if (m && m[0].length > 0) {
            totalIn += parseFloat(m[1]);
            matched = true;
          }
        }
      }
    }

    return matched ? totalIn : null;
  }

  function parseMetric(raw) {
    if (raw == null) return null;
    var s = String(raw).trim().toLowerCase().replace(/,/g, '.');
    if (!s) return null;

    if (/^-?\d+(?:\.\d+)?$/.test(s)) {
      return parseFloat(s) * 1000;
    }

    var totalMM = 0;
    var matched = false;

    var mmRe = /(-?\d+(?:\.\d+)?)\s*(?:mm\b|millimet(?:er|re)s?\b)/g;
    s = s.replace(mmRe, function (_, num) {
      totalMM += parseFloat(num);
      matched = true;
      return ' ';
    });

    var cmRe = /(-?\d+(?:\.\d+)?)\s*(?:cm\b|centimet(?:er|re)s?\b)/g;
    s = s.replace(cmRe, function (_, num) {
      totalMM += parseFloat(num) * 10;
      matched = true;
      return ' ';
    });

    var mRe = /(-?\d+(?:\.\d+)?)\s*(?:m\b|meters?\b|metres?\b)/g;
    s = s.replace(mRe, function (_, num) {
      totalMM += parseFloat(num) * 1000;
      matched = true;
      return ' ';
    });

    return matched ? totalMM : null;
  }

  function trim(n, places) {
    var s = Number(n).toFixed(places);
    if (s.indexOf('.') >= 0) s = s.replace(/0+$/, '').replace(/\.$/, '');
    return s;
  }

  var els = {};
  ['impInput', 'metInput', 'impErr', 'metErr',
   'outDecFt', 'outTotalIn',
   'outDecM', 'outTotalMM'].forEach(function (id) {
    els[id] = document.getElementById(id);
  });

  function clearOutputs() {
    ['outDecFt', 'outTotalIn', 'outDecM', 'outTotalMM']
      .forEach(function (id) { els[id].textContent = '—'; });
  }

  function renderFromInches(inches) {
    var mm = inches * MM_PER_INCH;
    els.outDecFt.textContent = trim(inches / IN_PER_FT, 2);
    els.outTotalIn.textContent = trim(inches, 2);
    els.outDecM.textContent = trim(mm / 1000, 2);
    els.outTotalMM.textContent = trim(mm, 2);
  }

  function onImp() {
    var raw = els.impInput.value;
    if (!raw.trim()) { clearOutputs(); els.impErr.textContent = ''; els.metInput.value = ''; return; }
    var inches = parseImperial(raw);
    if (inches == null) {
      els.impErr.textContent = "Couldn't parse — try 536'4\" or 4' 6-1/2\"";
      clearOutputs();
      els.metInput.value = '';
      return;
    }
    els.impErr.textContent = '';
    renderFromInches(inches);
    var mm = inches * MM_PER_INCH;
    els.metInput.value = trim(mm / 1000, 2);
    els.metErr.textContent = '';
  }

  function onMet() {
    var raw = els.metInput.value;
    if (!raw.trim()) { clearOutputs(); els.metErr.textContent = ''; els.impInput.value = ''; return; }
    var mm = parseMetric(raw);
    if (mm == null) {
      els.metErr.textContent = "Couldn't parse — try 12m 500mm or 163.475";
      clearOutputs();
      els.impInput.value = '';
      return;
    }
    els.metErr.textContent = '';
    var inches = mm / MM_PER_INCH;
    renderFromInches(inches);
    els.impInput.value = trim(inches / IN_PER_FT, 2);
    els.impErr.textContent = '';
  }

  els.impInput.addEventListener('input', onImp);
  els.metInput.addEventListener('input', onMet);

  document.querySelectorAll('.scale-copy').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var id = btn.getAttribute('data-target');
      var val = document.getElementById(id).textContent;
      if (!val || val === '—') return;
      var done = function () {
        btn.classList.add('copied');
        WD.toast('Copied: ' + val, 'success');
        setTimeout(function () { btn.classList.remove('copied'); }, 900);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(val).then(done, function () {
          fallbackCopy(val); done();
        });
      } else {
        fallbackCopy(val); done();
      }
    });
  });

  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.className = 'scale-copy-buffer';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(ta);
  }

  window.addEventListener('DOMContentLoaded', function () {
    els.impInput.focus();
  });

  window.WDScale = {
    parseImperial: parseImperial,
    parseMetric: parseMetric,
  };
})();
