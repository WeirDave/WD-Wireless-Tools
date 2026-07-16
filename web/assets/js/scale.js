/* WD Scale — feet/inches ↔ meters/mm converter.
   No backend. All math runs in the browser. */
(function () {
  'use strict';

  var MM_PER_INCH = 25.4;
  var IN_PER_FT = 12;

  /* ────────── Parsers ────────── */

  // Parse imperial input. Accepts:
  //   536, 536', 536ft, 536 ft, 536 feet
  //   536'4", 536' 4", 536ft 4in, 536 ft 4 inches
  //   4-1/2", 4 1/2", 1/2"
  //   536'4-1/2", 536' 4 1/2"
  //   536.333' — decimal feet
  //   6436"    — inches only
  //   a bare number is FEET (matches how architects/planners talk)
  // Returns total inches as a Number, or null if unparseable.
  function parseImperial(raw) {
    if (raw == null) return null;
    var s = String(raw).trim().toLowerCase()
      .replace(/[′’]/g, "'")   // fancy primes → '
      .replace(/[″”]/g, '"');  // fancy double primes → "
    if (!s) return null;

    // Bare number → feet.
    if (/^-?\d+(?:\.\d+)?$/.test(s)) {
      return parseFloat(s) * IN_PER_FT;
    }

    var totalIn = 0;
    var matched = false;

    // Feet portion.  Match "N'", "N ft", "N feet".
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
      // Mixed number with fraction: "4-1/2" or "4 1/2" (optional " suffix)
      var mixRe = /^(-?\d+)[\s-]+(\d+)\s*\/\s*(\d+)\s*(?:"|in\b|inch\b|inches\b)?/;
      var m = rest.match(mixRe);
      if (m) {
        totalIn += parseInt(m[1], 10) + parseInt(m[2], 10) / parseInt(m[3], 10);
        matched = true;
      } else {
        // Bare fraction: "1/2""
        var fracRe = /^(-?\d+)\s*\/\s*(\d+)\s*(?:"|in\b|inch\b|inches\b)?/;
        m = rest.match(fracRe);
        if (m) {
          totalIn += parseInt(m[1], 10) / parseInt(m[2], 10);
          matched = true;
        } else {
          // Plain inches: "4"", "4.5"", "4 in"
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

  // Parse metric input. Accepts:
  //   163.475, 163.475m, 12 m
  //   12m 500mm, 12 m 500 mm
  //   163475mm, 500mm
  //   1250cm
  // Returns millimeters as a Number, or null if unparseable.
  function parseMetric(raw) {
    if (raw == null) return null;
    var s = String(raw).trim().toLowerCase().replace(/,/g, '.');
    if (!s) return null;

    // Bare number → meters.
    if (/^-?\d+(?:\.\d+)?$/.test(s)) {
      return parseFloat(s) * 1000;
    }

    var totalMM = 0;
    var matched = false;

    // Match mm FIRST so it doesn't get eaten by the m regex.
    var mmRe = /(-?\d+(?:\.\d+)?)\s*(?:mm\b|millimet(?:er|re)s?\b)/g;
    s = s.replace(mmRe, function (_, num) {
      totalMM += parseFloat(num);
      matched = true;
      return ' ';
    });

    // Centimeters.
    var cmRe = /(-?\d+(?:\.\d+)?)\s*(?:cm\b|centimet(?:er|re)s?\b)/g;
    s = s.replace(cmRe, function (_, num) {
      totalMM += parseFloat(num) * 10;
      matched = true;
      return ' ';
    });

    // Meters (what's left).
    var mRe = /(-?\d+(?:\.\d+)?)\s*(?:m\b|meters?\b|metres?\b)/g;
    s = s.replace(mRe, function (_, num) {
      totalMM += parseFloat(num) * 1000;
      matched = true;
      return ' ';
    });

    return matched ? totalMM : null;
  }

  /* ────────── Formatters ────────── */

  // Trim a decimal to at most `n` places, without trailing zeros.
  function trim(n, places) {
    var s = Number(n).toFixed(places);
    if (s.indexOf('.') >= 0) s = s.replace(/0+$/, '').replace(/\.$/, '');
    return s;
  }

  // "536' 4-1/2\"" — nearest 1/16 inch. Whole inches get no fraction.
  function formatFeetInches(totalInches) {
    var neg = totalInches < 0;
    var abs = Math.abs(totalInches);
    // Work in sixteenths so rollover from "15/16 + rounding" is arithmetic,
    // not conditional. 16 sixteenths in an inch, 12 inches in a foot.
    var totalSixteenths = Math.round(abs * 16);
    var ft = Math.floor(totalSixteenths / (16 * IN_PER_FT));
    var remSixteenths = totalSixteenths - ft * 16 * IN_PER_FT;
    var whole = Math.floor(remSixteenths / 16);
    var frac16 = remSixteenths - whole * 16;

    // Reduce the fraction.
    function reduce(num, den) {
      function gcd(a, b) { return b === 0 ? a : gcd(b, a % b); }
      var g = gcd(num, den);
      return [num / g, den / g];
    }

    var parts = [];
    if (ft) parts.push(ft + "'");

    if (frac16 === 0) {
      if (whole || !ft) parts.push(whole + '"');
    } else {
      var r = reduce(frac16, 16);
      if (whole) parts.push(whole + '-' + r[0] + '/' + r[1] + '"');
      else parts.push(r[0] + '/' + r[1] + '"');
    }
    if (!parts.length) parts.push('0"');
    return (neg ? '-' : '') + parts.join(' ');
  }

  // "12 m 500 mm" — split meters and mm cleanly.
  function formatMetersMM(totalMM) {
    var neg = totalMM < 0;
    var abs = Math.abs(totalMM);
    var m = Math.floor(abs / 1000);
    var mm = Math.round((abs - m * 1000) * 10) / 10;  // 1 dp of mm
    if (mm >= 1000) { m += 1; mm = 0; }
    var parts = [];
    if (m) parts.push(m + ' m');
    if (mm || !m) parts.push(trim(mm, 1) + ' mm');
    return (neg ? '-' : '') + parts.join(' ');
  }

  /* ────────── UI wiring ────────── */

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

  // Ekahau's scale field only accepts xx.xx, so every output stops at 2 dp.
  // trim() strips trailing zeros so "163.47" doesn't become "163.470".
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
    // Mirror into metric input as decimal meters, without triggering its handler
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
    // Mirror into imperial input as decimal feet
    els.impInput.value = trim(inches / IN_PER_FT, 2);
    els.impErr.textContent = '';
  }

  els.impInput.addEventListener('input', onImp);
  els.metInput.addEventListener('input', onMet);

  // Copy buttons.
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
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(ta);
  }

  // Autofocus the imperial input on load — that's the one the user reached for.
  window.addEventListener('DOMContentLoaded', function () {
    els.impInput.focus();
  });

  // Expose for console debugging / future extensions.
  window.WDScale = {
    parseImperial: parseImperial,
    parseMetric: parseMetric,
    formatFeetInches: formatFeetInches,
    formatMetersMM: formatMetersMM,
  };
})();
