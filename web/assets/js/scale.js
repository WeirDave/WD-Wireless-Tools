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

    // The whole text has to be one dimension. Reading only the parts a
    // pattern recognised gave a confident wrong answer instead of an error:
    // `5ft6in` came out as 5 inches (no word boundary between `ft` and `6`),
    // and `4 1/2'` as 24 inches (the `1/2` was taken for inches and the 4
    // for feet). A number is a decimal, a fraction, or a whole number and a
    // fraction joined by a space or a dash; a unit is not followed by a
    // letter, so `5ft6in` still splits.
    var NUM = '(\\d+[\\s-]+\\d+\\s*/\\s*\\d+|\\d+\\s*/\\s*\\d+|\\d+(?:\\.\\d+)?|\\.\\d+)';
    var FT = "(?:'|feet|foot|ft)(?![a-z])";
    var IN = '("|inches|inch|in)(?![a-z])';
    var m = new RegExp('^(-)?\\s*(?:' + NUM + '\\s*' + FT + ')?\\s*(-\\s*)?(?:' +
                       NUM + '\\s*(?:' + IN + ')?)?$').exec(s);
    if (!m || (m[2] == null && m[4] == null)) return null;
    // In 4'-6" the dash joins feet to inches; it is not a sign. Read as one,
    // 4'-6" came out as 42 inches instead of 54. Without feet before it, a
    // dash there is a second minus sign and nothing a drawing writes.
    if (m[3] && m[2] == null) return null;

    function value(t) {
      var mix = /^(\d+)[\s-]+(\d+)\s*\/\s*(\d+)$/.exec(t);
      if (mix) return parseInt(mix[1], 10) + parseInt(mix[2], 10) / parseInt(mix[3], 10);
      var frac = /^(\d+)\s*\/\s*(\d+)$/.exec(t);
      if (frac) return parseInt(frac[1], 10) / parseInt(frac[2], 10);
      return parseFloat(t);
    }

    var totalIn = 0;
    if (m[2] != null) totalIn += value(m[2]) * IN_PER_FT;
    if (m[4] != null) {
      // A number with no unit and no feet before it is feet, as a bare number
      // is: `1 1/2` is a foot and a half. After feet it is the inches.
      totalIn += value(m[4]) * (m[2] == null && !m[5] ? IN_PER_FT : 1);
    }
    if (!isFinite(totalIn)) return null;
    // -4'-6" is minus four and a half feet, not minus four plus six inches.
    return m[1] ? -totalIn : totalIn;
  }

  function parseMetric(raw) {
    if (raw == null) return null;
    // A comma followed by exactly three digits and no more is a thousands
    // separator - `1,500 mm` is fifteen hundred millimetres, and reading it as
    // a decimal point gave 1.5. Any other comma is the decimal point.
    var s = String(raw).trim().toLowerCase()
      .replace(/(\d),(?=\d{3}(?!\d))/g, '$1')
      .replace(/,/g, '.');
    if (!s) return null;

    if (/^-?\d+(?:\.\d+)?$/.test(s)) {
      return parseFloat(s) * 1000;
    }

    var totalMM = 0;
    var matched = false;

    // A unit is not followed by a letter; `\b` there missed `12m500mm`.
    var mmRe = /(-?\d+(?:\.\d+)?)\s*(?:millimet(?:er|re)s?|mm)(?![a-z])/g;
    s = s.replace(mmRe, function (_, num) {
      totalMM += parseFloat(num);
      matched = true;
      return ' ';
    });

    var cmRe = /(-?\d+(?:\.\d+)?)\s*(?:centimet(?:er|re)s?|cm)(?![a-z])/g;
    s = s.replace(cmRe, function (_, num) {
      totalMM += parseFloat(num) * 10;
      matched = true;
      return ' ';
    });

    var mRe = /(-?\d+(?:\.\d+)?)\s*(?:meters?|metres?|m)(?![a-z])/g;
    s = s.replace(mRe, function (_, num) {
      totalMM += parseFloat(num) * 1000;
      matched = true;
      return ' ';
    });

    // Anything left over was not read, so the answer would describe only part
    // of what was typed: `12 m abc` is not 12 metres, and `3m50` is not 3.
    if (s.trim()) return null;
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
