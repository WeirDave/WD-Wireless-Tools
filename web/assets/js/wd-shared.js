(function () {
  'use strict';

  var _scriptSrc = document.currentScript && document.currentScript.src;

  var WD = {};

  WD.toggleTheme = function () {
    var cur = document.documentElement.getAttribute('data-theme') || 'dark';
    var next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('wd-theme', next); } catch (e) {}
    WD.syncThemeUI();
  };

  WD.syncFavicon = function () {
    if (!window.matchMedia) return;
    var dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.querySelectorAll('link[rel~="icon"]').forEach(function (link) {
      if ((link.getAttribute('rel') || '').indexOf('apple-touch-icon') !== -1) return;
      var href = link.getAttribute('href');
      if (!href) return;
      var next = href.replace(
        /wd-wireless-tools-v8\.0-(?:white-)?(multi-size\.ico|32x32\.png)(?=(?:[?#]|$))/,
        'wd-wireless-tools-v8.0-' + (dark ? 'white-' : '') + '$1'
      );
      if (next === href) return;
      var replacement = link.cloneNode(false);
      replacement.setAttribute('href', next);
      link.parentNode.replaceChild(replacement, link);
    });
  };

  if (window.matchMedia) {
    var mq = window.matchMedia('(prefers-color-scheme: dark)');
    if (mq.addEventListener) mq.addEventListener('change', WD.syncFavicon);
    else if (mq.addListener) mq.addListener(WD.syncFavicon);
  }

  WD.syncThemeUI = function () {
    var dark = (document.documentElement.getAttribute('data-theme') || 'dark') === 'dark';
    var icoTxt = dark ? '\u{1F319}' : '☀️';
    var lblTxt = dark ? 'Dark' : 'Light';
    document.querySelectorAll('.theme-toggle').forEach(function (el) {
      var ico = el.querySelector('.ico');
      var txt = el.querySelector('.txt');
      if (ico) ico.textContent = icoTxt;
      if (txt) txt.textContent = lblTxt;
      if (!ico && !txt) el.textContent = icoTxt + ' ' + lblTxt;
    });
    var btn = document.getElementById('themeBtn');
    if (btn) btn.textContent = icoTxt + ' ' + lblTxt;
    document.querySelectorAll('.theme-toggle-btn').forEach(function (b) {
      b.textContent = icoTxt;
    });
    WD.syncFavicon();
  };

  WD.esc = function (s) {
    if (s == null) return '';
    var d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
  };

  WD.escAttr = function (s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/'/g, '&#39;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  };

  WD.escJsStr = function (s) {
    if (s == null) return '';
    var js = String(s)
      .replace(/\\/g, '\\\\')
      .replace(/'/g, "\\'")
      .replace(/</g, '\\x3c')
      .replace(/\r/g, '\\r')
      .replace(/\n/g, '\\n');
    return js
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;');
  };

  WD.safeColor = function (c) {
    if (typeof c !== 'string') return '#888';
    return /^#[0-9a-fA-F]{3,8}$|^rgba?\([^)]+\)$|^hsla?\([^)]+\)$/.test(c) ? c : '#888';
  };

  /* ── The Ekahau AP palette ───────────────────────────────────────
     The ten colours Ekahau offers in its Mark menu, plus CLEAR (no colour).

     An .esx stores whichever the project used: the palette name ("GREEN") or
     the hex Ekahau paints it with ("#00FF00"). Anything drawing an AP has to
     cope with both, so the map lives here rather than in the one tool that
     happened to need it first. The Report drew names straight into SVG
     `fill=`, where a browser reads them as CSS keywords - and CSS green is
     #008000, a different colour from Ekahau's. It also handed the name to the
     contrast helper below, which cannot parse a word, so every marked AP in a
     printed report came out with white lettering regardless of its fill. */
  WD.EKAHAU_COLORS = {
    yellow:  '#FFE600', orange: '#FF8500', red:     '#FF0000',
    magenta: '#FF00FF', purple: '#C297FF', blue:    '#0068FF',
    gray:    '#6D6D6D', green:  '#00FF00', brown:   '#C97700',
    cyan:    '#00FFCE'
  };

  /* Other hexes that are the same swatch.

     Gray is the one that bit. The first version of this table had #6D6D6D,
     which is what a real project actually contains; a later pass "corrected"
     it to #6B6B6B by reading the colour off the picker on screen, and from
     then on every grey AP fell through to Custom #6D6D6D. Eyeballing a
     rendered swatch is not the same as knowing what gets written to the file.

     So both are accepted. Add to this rather than replacing a value whenever
     a project turns up carrying a hex we do not recognise - the observed one
     is the truth, and swapping the canonical value out would just move the
     bug to whoever had the other one. */
  WD.EKAHAU_HEX_ALIASES = {
    '#6B6B6B': 'gray'
  };
  WD.EKAHAU_COLOR_ORDER = [
    'yellow', 'orange', 'red', 'magenta', 'purple', 'blue',
    'gray', 'green', 'brown', 'cyan'
  ];

  /* What Ekahau calls them in its own Mark menu, which is not what this code
     called them. The hex values were checked against the picker; the names
     were ours, and three of them were wrong: Ekahau says Pink, Violet and
     Mint where this said magenta, purple and cyan.

     He reads our list against theirs, so the label has to be their word. The
     keys stay as they are - they are internal, and renaming them would break
     a saved colour sequence - and both spellings are accepted coming in,
     because no local project has ever stored an AP colour as a name and
     there is no evidence of which form Ekahau writes. */
  WD.EKAHAU_COLOR_NAMES = {
    yellow: 'Yellow', orange: 'Orange', red: 'Red', magenta: 'Pink',
    purple: 'Violet', blue: 'Blue', gray: 'Gray', green: 'Green',
    brown: 'Brown', cyan: 'Mint'
  };
  WD.EKAHAU_COLOR_ALIASES = {
    pink: 'magenta', violet: 'purple', mint: 'cyan',
    grey: 'gray', teal: 'cyan'
  };

  /* CLEAR is the first entry in Ekahau's menu and it is a choice, not a gap -
     but what it writes is no colour at all, so an AP set to Clear and an AP
     never marked are the same thing in the file. They are therefore one row
     here, named the way Ekahau names it. */
  WD.CLEAR_KEY = '__none';
  WD.CLEAR_HEX = '#FFFFFF';

  // An AP's stored colour as a hex this suite can measure and paint.
  // Null for an unmarked AP; anything unrecognised is passed through, because
  // a colour we have not seen is still better drawn than dropped.
  WD.resolveApColor = function (c) {
    if (!c) return null;
    var lc = String(c).toLowerCase().trim();
    if (WD.EKAHAU_COLOR_ALIASES[lc]) lc = WD.EKAHAU_COLOR_ALIASES[lc];
    if (WD.EKAHAU_COLORS[lc]) return WD.EKAHAU_COLORS[lc];
    if (/^#[0-9a-f]{6}$/i.test(lc)) return lc.toUpperCase();
    return c;
  };

  /* One key per colour, whichever way the project spells it.

     An .esx stores a hex. Ekahau's menu shows a name. Anything that puts a
     colour in front of the reader has to get from one to the other, and this
     is the only place that conversion happens - the Report was printing
     "#6B6B6B" as a section heading while the Labeler said "Gray", which is
     what two implementations of one mapping looks like from the outside. */
  WD.ekahauColorKey = function (value) {
    if (!value) return WD.CLEAR_KEY;
    var lc = String(value).toLowerCase().trim();
    if (WD.EKAHAU_COLOR_ALIASES[lc]) lc = WD.EKAHAU_COLOR_ALIASES[lc];
    if (WD.EKAHAU_COLORS[lc]) return lc;
    var up = lc.charAt(0) === '#' ? lc.toUpperCase() : '#' + lc.toUpperCase();
    for (var i = 0; i < WD.EKAHAU_COLOR_ORDER.length; i++) {
      if (WD.EKAHAU_COLORS[WD.EKAHAU_COLOR_ORDER[i]] === up) {
        return WD.EKAHAU_COLOR_ORDER[i];
      }
    }
    if (WD.EKAHAU_HEX_ALIASES[up]) return WD.EKAHAU_HEX_ALIASES[up];
    return lc;                 // unknown: kept as-is, drawn and labelled
  };

  // Ekahau's word for a colour. Falls back to the key capitalised, so a
  // swatch nobody has seen before still gets a readable label.
  WD.ekahauColorName = function (key) {
    if (!key || key === WD.CLEAR_KEY) return 'Clear';
    var k = String(key).toLowerCase().trim();
    if (WD.EKAHAU_COLOR_ALIASES[k]) k = WD.EKAHAU_COLOR_ALIASES[k];
    if (WD.EKAHAU_COLOR_NAMES[k]) return WD.EKAHAU_COLOR_NAMES[k];
    if (/^#?[0-9a-f]{6}$/i.test(k)) {
      return 'Custom ' + (k.charAt(0) === '#' ? k.toUpperCase() : '#' + k.toUpperCase());
    }
    return k.charAt(0).toUpperCase() + k.slice(1);
  };

  /* ── Legibility on a user-chosen colour ──────────────────────────
     Every tool that paints text or a glyph on a colour somebody picked in
     Ekahau has the same problem, so it is answered once, here.

     This used a Rec.601 brightness over 180, and two other copies elsewhere in
     the suite used their own thresholds. They disagreed about exactly the
     colours that matter: Ekahau green (#00FF00) scores 150 and cyan (#00FFCE)
     173, so all three put white text on both - a contrast ratio of about 1.4,
     which is a number that is drawn and cannot be read.

     Relative luminance and a real contrast ratio instead. It is computed rather
     than listed because Ekahau can add a swatch and a user can type a custom
     hex; a list of "colours that need black" would be silently wrong the first
     time either happens. */
  function _hexBytes(hex) {
    if (!hex || typeof hex !== 'string') return null;
    var h = hex.trim().replace('#', '');
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
    return [parseInt(h.substr(0, 2), 16),
            parseInt(h.substr(2, 2), 16),
            parseInt(h.substr(4, 2), 16)];
  }

  WD.relLuminance = function (hex) {
    var rgb = _hexBytes(hex);
    if (!rgb) return null;
    var c = rgb.map(function (v) {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };

  WD.contrastRatio = function (a, b) {
    var la = typeof a === 'number' ? a : WD.relLuminance(a);
    var lb = typeof b === 'number' ? b : WD.relLuminance(b);
    if (la == null || lb == null) return 1;
    var hi = Math.max(la, lb), lo = Math.min(la, lb);
    return (hi + 0.05) / (lo + 0.05);
  };

  WD.DARK_INK = '#111111';
  WD.LIGHT_INK = '#ffffff';

  // True when near-black reads better on this fill than white does.
  WD.needsDarkText = function (hex) {
    var lum = WD.relLuminance(hex);
    if (lum == null) return false;
    return WD.contrastRatio(lum, WD.relLuminance(WD.DARK_INK)) >
           WD.contrastRatio(lum, WD.relLuminance(WD.LIGHT_INK));
  };

  // The ink to actually use on `hex`.
  WD.readableOn = function (hex) {
    return WD.needsDarkText(hex) ? WD.DARK_INK : WD.LIGHT_INK;
  };

  /* A ring that keeps a shape visible on the paper behind it.

     A pale AP colour on a white CAD plan is the bug that already shipped once,
     where markers were drawn white on white and were simply not there. The
     ring gets firmer as the fill approaches the background, so a near-white
     marker still has an edge.

     This is for shapes on a light background - a floor plan, a printed sheet -
     because the ring it returns is always black. `against` only says how light
     that background is, so it can tune the firmness; it does not make the ring
     work on a dark panel. For a swatch on the app's own (dark by default)
     chrome, use WD.needsDarkText() and ring the pale ones.

     A colour it cannot parse scores 1 and takes the firmest ring, which is the
     safe way to be wrong: an unnecessary outline is visible, a missing one is
     an AP the installer never sees. */
  WD.outlineOn = function (hex, against) {
    var ratio = WD.contrastRatio(hex, against || '#ffffff');
    if (ratio < 1.6) return 'rgba(0,0,0,.72)';   // all but invisible on paper
    if (ratio < 3)   return 'rgba(0,0,0,.5)';    // pale
    return 'rgba(0,0,0,.28)';                    // holds its own
  };

  WD.toast = function (msg, type) {
    var container = document.getElementById('toasts');
    if (container) {
      var t = document.createElement('div');
      t.className = 'toast' + (type ? ' ' + type : '');
      t.textContent = msg;
      container.appendChild(t);
      setTimeout(function () {
        t.classList.add('fading');
        setTimeout(function () { t.remove(); }, 300);
      }, 4000);
      return;
    }
    var el = document.getElementById('toast');
    if (el) {
      el.textContent = msg;
      el.className = 'toast' + (type ? ' ' + type : '');
      requestAnimationFrame(function () {
        el.classList.add('visible');
        el.classList.add('show');
      });
      clearTimeout(el._timer);
      el._timer = setTimeout(function () {
        el.classList.remove('visible');
        el.classList.remove('show');
      }, 6000);
    }
  };

  WD.showModal = function (id) {
    document.getElementById(id).classList.add('active');
  };

  WD.closeModal = function (id) {
    document.getElementById(id || 'modal').classList.remove('active');
  };

  WD.toggleMenu = function (ev, menuId) {
    if (ev) ev.stopPropagation();
    var menu = document.getElementById(menuId);
    if (!menu) return;
    var wasOpen = menu.classList.contains('open');
    document.querySelectorAll('.main-menu.open, .help-menu.open, .wd-menu.open')
      .forEach(function (m) { m.classList.remove('open'); });
    if (!wasOpen) {
      menu.classList.add('open');
      setTimeout(function () {
        document.addEventListener('click', function handler(e) {
          if (!e.target.closest('.menu-wrap, .help-menu-wrap')) {
            menu.classList.remove('open');
          }
          document.removeEventListener('click', handler);
        }, { once: true });
      }, 0);
    }
  };

  WD.applyVersions = function () {
    var els = document.querySelectorAll('[data-ver]');
    if (!els.length) return;
    var url = _scriptSrc ? _scriptSrc.replace(/js\/wd-shared\.js.*$/, 'versions.json') : '/assets/versions.json';
    fetch(url, { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (versions) {
        els.forEach(function (el) {
          var v = versions[el.getAttribute('data-ver')];
          if (v) el.textContent = 'v' + v;
        });
      })
      .catch(function () {});
  };

  var _staleCheckInFlight = false;
  var _staleCheckLast = 0;
  WD.checkServerVersion = function () {
    if (_staleCheckInFlight) return;
    var now = Date.now();
    if (now - _staleCheckLast < 5000) return;
    _staleCheckLast = now;
    _staleCheckInFlight = true;

    var diskUrl = _scriptSrc ? _scriptSrc.replace(/js\/wd-shared\.js.*$/, 'versions.json') : '/assets/versions.json';
    Promise.all([
      fetch(diskUrl, { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }),
      fetch('/api/version', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }),
    ]).then(function (results) {
      _staleCheckInFlight = false;
      var disk = results[0];
      var server = results[1];
      if (!disk || !server || !server.versions) return;
      var mismatched = [];
      Object.keys(disk).forEach(function (k) {
        if (server.versions[k] && server.versions[k] !== disk[k]) {
          mismatched.push({ key: k, server: server.versions[k], disk: disk[k] });
        }
      });
      if (mismatched.length) _renderStaleBanner(mismatched, server.startedAt);
      else _removeStaleBanner();
    }).catch(function () { _staleCheckInFlight = false; });
  };

  function _renderStaleBanner(mismatched, serverStartedAt) {
    var existing = document.getElementById('wdStaleBanner');
    if (existing) existing.remove();
    var b = document.createElement('div');
    b.id = 'wdStaleBanner';
    b.className = 'wd-stale-banner';
    b.dataset.startedAt = serverStartedAt || '';
    var label = mismatched.map(function (m) {
      return m.key + ': running v' + m.server + ' → latest v' + m.disk;
    }).join(' · ');
    b.innerHTML =
      '<span class="wd-stale-icon">&#9888;</span>' +
      '<span class="wd-stale-msg">' +
        '<b>Server is running old code.</b> ' +
        'Click <b>Restart now</b> to load the latest build.' +
        '<span class="wd-stale-detail">' + WD.esc(label) + '</span>' +
      '</span>' +
      '<button class="wd-stale-restart" type="button">Restart now</button>' +
      '<button class="wd-stale-close" type="button" title="Hide until next reload">&times;</button>';
    b.querySelector('.wd-stale-close').addEventListener('click', _removeStaleBanner);
    b.querySelector('.wd-stale-restart').addEventListener('click', _restartServer);
    document.body.appendChild(b);
    document.body.classList.add('wd-has-stale-banner');
  }

  function _removeStaleBanner() {
    var el = document.getElementById('wdStaleBanner');
    if (el) el.remove();
    document.body.classList.remove('wd-has-stale-banner');
  }

  function _restartServer() {
    var banner = document.getElementById('wdStaleBanner');
    if (!banner) return;
    var oldStartedAt = banner.dataset.startedAt || '';
    var btn = banner.querySelector('.wd-stale-restart');
    var msg = banner.querySelector('.wd-stale-msg');
    if (btn) { btn.disabled = true; btn.textContent = 'Restarting…'; }
    if (msg) msg.innerHTML = '<b>Restarting server…</b> <span class="wd-stale-detail">Reloading as soon as the fresh build is ready.</span>';

    fetch('/api/restart', {
      method: 'POST',
      cache: 'no-store',
      headers: { 'X-WD-Wireless-Tools': '1' }
    })
      .catch(function () {})
      .then(function () {
        var deadline = Date.now() + 20000;
        var startedPolling = Date.now();
        var pollDelay = 400;
        (function poll() {
          if (Date.now() > deadline) {
            _restartFailed('Server didn\'t come back. If you launched it without "Start WD Wireless Tools.bat", close and reopen the app manually.');
            return;
          }
          fetch('/api/version', { cache: 'no-store' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (j) {
              if (j && j.startedAt && j.startedAt !== oldStartedAt) {
                setTimeout(function () { window.location.reload(); }, 200);
              } else {
                setTimeout(poll, pollDelay);
              }
            })
            .catch(function () {
              if (Date.now() - startedPolling > 1000) pollDelay = 700;
              setTimeout(poll, pollDelay);
            });
        })();
      });
  }

  function _restartFailed(text) {
    var banner = document.getElementById('wdStaleBanner');
    if (!banner) return;
    var btn = banner.querySelector('.wd-stale-restart');
    var msg = banner.querySelector('.wd-stale-msg');
    if (btn) { btn.disabled = false; btn.textContent = 'Try again'; }
    if (msg) msg.innerHTML = '<b>Restart didn\'t complete.</b> <span class="wd-stale-detail">' + WD.esc(text) + '</span>';
  }

  window.addEventListener('focus', function () { WD.checkServerVersion(); });

  var WD_REPO = 'WeirDave/WD-Wireless-Tools';
  var WD_RELEASES_URL = 'https://github.com/' + WD_REPO + '/releases/latest';
  // Kept for reference only - the browser no longer calls GitHub directly; see
  // the update check below, which goes through /api/update/status.
  var WD_API_LATEST = 'https://api.github.com/repos/' + WD_REPO + '/releases/latest';
  var WD_UPDATE_CACHE_KEY = 'wd-update-check';
  var WD_UPDATE_DISMISS_KEY = 'wd-update-dismissed';
  var WD_UPDATE_TTL_MS = 24 * 60 * 60 * 1000;
  var WD_ABOUT_ID = 'wdAboutModal';

  function _readUpdateCache() {
    try {
      var raw = localStorage.getItem(WD_UPDATE_CACHE_KEY);
      if (!raw) return null;
      var v = JSON.parse(raw);
      if (!v || typeof v.checkedAt !== 'number') return null;
      var age = Date.now() - v.checkedAt;
      if (v.error) {
        if (v.kind === 'ratelimit' && v.resetAt) {
          if (Date.now() >= v.resetAt + 30 * 1000) return null;
        } else if (age > 30 * 60 * 1000) {
          return null;
        }
      } else if (age > WD_UPDATE_TTL_MS) {
        return null;
      }
      return v;
    } catch (e) { return null; }
  }

  function _writeUpdateCache(v) {
    try { localStorage.setItem(WD_UPDATE_CACHE_KEY, JSON.stringify(v)); } catch (e) {}
  }

  function _cmpVer(a, b) {
    var ap = String(a || '').replace(/^v/i, '').split('.').map(function (n) { return parseInt(n, 10) || 0; });
    var bp = String(b || '').replace(/^v/i, '').split('.').map(function (n) { return parseInt(n, 10) || 0; });
    var len = Math.max(ap.length, bp.length);
    for (var i = 0; i < len; i++) {
      var av = ap[i] || 0, bv = bp[i] || 0;
      if (av > bv) return 1;
      if (av < bv) return -1;
    }
    return 0;
  }

  function _ensureAboutModal() {
    if (document.getElementById(WD_ABOUT_ID)) return;
    var overlay = document.createElement('div');
    overlay.id = WD_ABOUT_ID;
    overlay.className = 'modal-overlay wd-about-overlay';
    overlay.innerHTML =
      '<div class="modal wd-about-modal">' +
        '<div class="modal-header">' +
          '<h3>About &mdash; WD Wireless Tools</h3>' +
          '<button class="btn btn-icon btn-sm wd-about-close" type="button" title="Close">&times;</button>' +
        '</div>' +
        '<div class="modal-body">' +
          '<div class="wd-about-hero">' +
            '<img class="wd-about-logo" src="/assets/wd-wireless-tools-v8.0-720x720.png" alt="">' +
            '<div class="wd-about-heroText">' +
              '<div class="wd-about-name">WD Wireless Tools</div>' +
              '<div class="wd-about-tagline">A suite of Ekahau workflow tools.</div>' +
              '<div class="wd-about-version">Installed: <b data-ver="suite">v&hellip;</b></div>' +
            '</div>' +
          '</div>' +
          '<div class="wd-about-updateRow">' +
            '<button class="btn wd-about-checkBtn" type="button">' +
              '<span class="wd-about-checkSpinner" aria-hidden="true" hidden></span>' +
              '<span class="wd-about-checkLabel">Check for updates</span>' +
            '</button>' +
            '<div class="wd-about-updateResult" role="status" aria-live="polite"></div>' +
          '</div>' +
          '<div class="wd-update-panel" hidden></div>' +
          '<div class="wd-about-section">' +
            '<div class="wd-about-sectionTitle">Links</div>' +
            '<div class="wd-about-links">' +
              '<a href="https://github.com/WeirDave?tab=repositories" target="_blank" rel="noopener">GitHub repository</a>' +
              '<a href="https://weirdave.com" target="_blank" rel="noopener">weirdave.com &mdash; personal site</a>' +
              '<a href="' + WD_RELEASES_URL.replace('/latest', '') + '" target="_blank" rel="noopener">All releases &amp; changelogs</a>' +
            '</div>' +
          '</div>' +
          '<div class="wd-about-credit">Built with signal strength and caffeine by <a href="https://github.com/WeirDave" target="_blank" rel="noopener">WeirDave</a>. MIT licensed.</div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) WD.closeAbout();
    });
    overlay.querySelector('.wd-about-close').addEventListener('click', WD.closeAbout);
    overlay.querySelector('.wd-about-checkBtn').addEventListener('click', function () {
      WD.checkForUpdates({ force: true });
    });
    WD.applyVersions();
  }

  WD.openAbout = function () {
    _ensureAboutModal();
    document.querySelectorAll('.main-menu.open, .help-menu.open, .wd-menu.open')
      .forEach(function (m) { m.classList.remove('open'); });
    var cached = _readUpdateCache();
    if (cached) {
      if (cached.error) _renderUpdateError(cached);
      else _renderUpdateResult(cached);
    }
    document.getElementById(WD_ABOUT_ID).classList.add('active');
  };

  WD.closeAbout = function () {
    var m = document.getElementById(WD_ABOUT_ID);
    if (m) m.classList.remove('active');
  };

  function _setUpdateBusy(busy) {
    var modal = document.getElementById(WD_ABOUT_ID);
    if (!modal) return;
    var btn = modal.querySelector('.wd-about-checkBtn');
    var spinner = modal.querySelector('.wd-about-checkSpinner');
    var label = modal.querySelector('.wd-about-checkLabel');
    if (btn) btn.disabled = busy;
    if (spinner) spinner.hidden = !busy;
    if (label) label.textContent = busy ? 'Checking…' : 'Check for updates';
  }

  function _renderUpdateResult(state) {
    var modal = document.getElementById(WD_ABOUT_ID);
    if (!modal) return;
    var el = modal.querySelector('.wd-about-updateResult');
    if (!el) return;
    if (state.isNewer) {
      el.className = 'wd-about-updateResult is-newer';
      el.innerHTML =
        '<span class="wd-about-updateIcon">&#8681;</span> ' +
        'New release: <b>v' + WD.esc(state.latestVersion) + '</b>';
      var panel = modal.querySelector('.wd-update-panel');
      if (panel) WD.Updater.mount(panel, state);
    } else {
      el.className = 'wd-about-updateResult is-current';
      el.innerHTML =
        '<span class="wd-about-updateIcon">&#10003;</span> ' +
        'You’re on the latest release (v' + WD.esc(state.localVersion || state.latestVersion || '?') + ').';
      WD.Updater.unmount();
    }
  }

  // ---- WD.Updater ---------------------------------------------------------
  // Self-contained update UI. Portable across the app family: it renders into
  // whatever element you hand mount(), talks only to the endpoints in config,
  // and knows nothing about the About modal that currently hosts it. To reuse
  // in another app, copy this block plus tools/updater.py and edit `config`.
  //
  // The app knows whether this is a git or ZIP install, so it leads with the
  // one action that fits and files the rest under "Other ways". Asking a user
  // to choose between `git pull` and a ZIP on every update would be more
  // friction than the manual download this replaces. The alternatives open on
  // their own when the primary path fails — that's when a choice is useful.
  WD.Updater = (function () {
    var config = {
      repo: WD_REPO,
      releasesUrl: WD_RELEASES_URL,
      bootstrapCommand:
        'irm https://raw.githubusercontent.com/' + WD_REPO + '/main/install.ps1 | iex',
      endpoints: {
        status: '/api/update/status',
        run: '/api/update',
        version: '/api/version',
        restart: '/api/restart'
      }
    };

    var host = null;        // element we render into
    var state = null;       // {localVersion, latestVersion, latestUrl}
    var info = null;        // /api/update/status .install
    var infoTried = false;

    function esc(s) { return WD.esc(s); }
    function escAttr(s) { return WD.escAttr(s); }

    function fetchInfo() {
      if (infoTried) return Promise.resolve(info);
      infoTried = true;
      return fetch(config.endpoints.status, { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) { info = j && j.install ? j.install : null; return info; })
        .catch(function () { return null; });
    }

    function render(html) {
      if (host) host.innerHTML = '<div class="wd-update-body' +
        (html.cls ? ' ' + html.cls : '') + '">' + html.body + '</div>';
    }

    function stepsHtml(steps) {
      if (!steps || !steps.length) return '';
      return '<ul class="wd-update-steps">' +
        steps.map(function (s) { return '<li>' + esc(s) + '</li>'; }).join('') +
        '</ul>';
    }

    // Conversion is a one-time, in-place adoption of the install by git. It is
    // gated behind an explicit confirm because it rewrites the folder's
    // tracked files, even though a backup is taken first and user data lives
    // outside the tree.
    function convertLabel() {
      if (info && info.gitInstall && info.gitInstall.needed) {
        return 'Switch to git updates (installs Git first)';
      }
      return 'Switch to git updates';
    }

    function alternativesHtml(open) {
      var canConvert = info && info.canConvertToGit;
      var gitNote = '';
      if (canConvert && info.gitInstall && info.gitInstall.needed) {
        gitNote = '<span class="wd-update-altNote">' + esc(info.gitInstall.message) + '</span>';
      }
      return '' +
        '<details class="wd-update-alts"' + (open ? ' open' : '') + '>' +
          '<summary>Other ways to update</summary>' +
          '<div class="wd-update-altBody">' +
            (canConvert
              ? '<div class="wd-update-alt">' +
                  '<button class="btn btn-sm wd-update-convertBtn" type="button">' +
                    esc(convertLabel()) +
                  '</button>' +
                  '<span class="wd-update-altNote">One-time change. Future updates ' +
                  'become a fast pull instead of a full download.</span>' +
                  gitNote +
                '</div>'
              : '') +
            '<div class="wd-update-alt">' +
              '<div class="wd-update-altNote">Run from PowerShell — installs or ' +
              'updates anywhere, including a machine without this folder:</div>' +
              '<div class="wd-update-cmdRow">' +
                '<code class="wd-update-cmd">' + esc(config.bootstrapCommand) + '</code>' +
                '<button class="btn btn-sm wd-update-copyBtn" type="button">Copy</button>' +
              '</div>' +
            '</div>' +
            '<div class="wd-update-alt">' +
              '<a class="wd-about-updateLink" href="' + escAttr(config.releasesUrl) + '" ' +
                'target="_blank" rel="noopener">Download the ZIP manually &rarr;</a>' +
            '</div>' +
          '</div>' +
        '</details>';
    }

    function primaryLabel() {
      if (info && info.method === 'zip') return 'Download and install update';
      return 'Update now';
    }

    function wire() {
      if (!host) return;
      var go = host.querySelector('.wd-update-goBtn');
      if (go) go.addEventListener('click', function () { run(null); });

      var conv = host.querySelector('.wd-update-convertBtn');
      if (conv) conv.addEventListener('click', showConvertConfirm);

      var confirmBtn = host.querySelector('.wd-update-convertConfirm');
      if (confirmBtn) {
        confirmBtn.addEventListener('click', function () {
          run('convert', { installGit: true });
        });
      }
      var cancel = host.querySelector('.wd-update-convertCancel');
      if (cancel) cancel.addEventListener('click', function () { showPrimary(); });

      var restart = host.querySelector('.wd-update-restartBtn');
      if (restart) restart.addEventListener('click', function () { doRestart(restart); });

      var copy = host.querySelector('.wd-update-copyBtn');
      if (copy) {
        copy.addEventListener('click', function () {
          var done = function () {
            copy.textContent = 'Copied';
            setTimeout(function () { copy.textContent = 'Copy'; }, 1600);
          };
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(config.bootstrapCommand).then(done, function () {});
          } else {
            var ta = document.createElement('textarea');
            ta.value = config.bootstrapCommand;
            document.body.appendChild(ta); ta.select();
            try { document.execCommand('copy'); done(); } catch (e) {}
            document.body.removeChild(ta);
          }
        });
      }
    }

    function showConvertConfirm() {
      var needsGit = info && info.gitInstall && info.gitInstall.needed;
      render({
        cls: 'is-confirm',
        body:
          '<div class="wd-update-headline">Switch this install to git updates?</div>' +
          '<ul class="wd-update-facts">' +
            (needsGit ? '<li>Git will be installed first (about a minute).</li>' : '') +
            '<li>This folder becomes a tracked checkout of ' + esc(config.repo) + '.</li>' +
            '<li>You stay on the version you have now — this doesn’t update you.</li>' +
            '<li>A dated backup of the folder is made first.</li>' +
            '<li>Your settings and templates are untouched — they live outside ' +
              'this folder.</li>' +
          '</ul>' +
          '<div class="wd-update-primaryRow">' +
            '<button class="btn btn-primary wd-update-convertConfirm" type="button">' +
              (needsGit ? 'Install Git and switch' : 'Switch to git updates') +
            '</button>' +
            '<button class="btn btn-sm wd-update-convertCancel" type="button">Cancel</button>' +
          '</div>'
      });
      wire();
    }

    function showPrimary() {
      if (!host || !state) return;

      if (!info) {
        // No server behind this page, or the endpoint is unavailable.
        render({ body:
          '<a class="btn btn-primary" href="' +
            escAttr(state.latestUrl || config.releasesUrl) + '" target="_blank" ' +
            'rel="noopener">Get v' + esc(state.latestVersion) + ' &rarr;</a>' });
        return;
      }

      if (info.method === 'dev') {
        render({ body:
          '<div class="wd-update-note">This is a development checkout — update it ' +
          'with git so your work isn’t checked out from under you.</div>' });
        return;
      }

      if (info.method === 'manual') {
        render({ body:
          '<div class="wd-update-note">' + esc(info.reason) + '</div>' +
          alternativesHtml(true) });
        wire();
        return;
      }

      render({ body:
        '<div class="wd-update-primaryRow">' +
          '<button class="btn btn-primary wd-update-goBtn" type="button">' +
            esc(primaryLabel()) +
          '</button>' +
          '<span class="wd-update-target">v' +
            esc(state.localVersion || info.currentVersion) +
            ' &rarr; v' + esc(state.latestVersion) + '</span>' +
        '</div>' +
        '<div class="wd-update-note">' + esc(info.reason) + '</div>' +
        alternativesHtml(false) });
      wire();
    }

    function run(mode, opts) {
      opts = opts || {};
      render({ cls: 'is-busy', body:
        '<div class="wd-update-primaryRow">' +
          '<span class="wd-about-checkSpinner" aria-hidden="true"></span>' +
          '<b>' + (mode === 'convert' ? 'Switching to git updates…' : 'Updating…') + '</b>' +
        '</div>' +
        '<div class="wd-update-note">Progress is also printed in the terminal ' +
        'window the app is running in.</div>' });

      fetch(config.endpoints.run, {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
        body: JSON.stringify({ mode: mode || null, installGit: !!opts.installGit })
      })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res || !res.ok) throw res || {};
          infoTried = false;   // install type may have changed
          renderDone(res, mode);
        })
        .catch(function (res) { renderFailed(res || {}); });
    }

    function renderDone(res, mode) {
      try { localStorage.removeItem(WD_UPDATE_CACHE_KEY); } catch (e) {}
      _removeUpdateBanner();

      if (mode === 'convert') {
        render({ cls: 'is-done', body:
          '<div class="wd-update-headline"><span class="wd-update-tick">&#10003;</span> ' +
            'This install now updates through git.</div>' +
          '<div class="wd-update-note">You’re still on v' + esc(res.newVersion || '') +
            '. Updates from here are an incremental pull.</div>' +
          (res.backup ? '<div class="wd-update-note">Backup: ' + esc(res.backup) +
            '</div>' : '') +
          stepsHtml(res.steps) });
        return;
      }

      if (res.changed === false) {
        render({ cls: 'is-done', body:
          '<div class="wd-update-headline">Already up to date (v' +
            esc(res.newVersion || '') + ').</div>' + stepsHtml(res.steps) });
        return;
      }

      var from = res.previousVersion || (state && state.localVersion) || '';
      var to = res.newVersion || (state && state.latestVersion) || '';
      render({ cls: 'is-done', body:
        '<div class="wd-update-headline">' +
          '<span class="wd-update-tick">&#10003;</span> Updated' +
          (from && to ? ' <b>v' + esc(from) + '</b> &rarr; <b>v' + esc(to) + '</b>' : '') +
        '</div>' +
        (res.rescuedTemplates && res.rescuedTemplates.length
          ? '<div class="wd-update-note">Your edits to ' +
            esc(res.rescuedTemplates.join(', ')) + ' were kept as personal copies.</div>'
          : '') +
        (res.backup ? '<div class="wd-update-note">Previous copy saved to ' +
          esc(res.backup) + '</div>' : '') +
        stepsHtml(res.steps) +
        '<div class="wd-update-primaryRow">' +
          '<button class="btn btn-primary wd-update-restartBtn" type="button">' +
            'Restart to finish</button>' +
          '<span class="wd-update-target">The new version loads after the restart.</span>' +
        '</div>' });
      wire();
    }

    function renderFailed(res) {
      var msg = res.error || 'The update could not be completed.';
      var was = (state && state.localVersion) || (info && info.currentVersion) || '';
      render({ cls: 'is-error', body:
        '<div class="wd-update-headline">' +
          '<span class="wd-update-warn">&#9888;</span> Update didn’t complete</div>' +
        '<div class="wd-update-note">' + esc(msg) + '</div>' +
        '<div class="wd-update-note">Nothing was left half-installed' +
          (was ? ' — you’re still on v' + esc(was) + '.' : '.') + '</div>' +
        stepsHtml(res.steps) +
        alternativesHtml(true) });
      wire();
    }

    function doRestart(btn) {
      btn.disabled = true;
      btn.textContent = 'Restarting…';
      var oldStartedAt = '';
      fetch(config.endpoints.version, { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) { oldStartedAt = (j && j.startedAt) || ''; })
        .catch(function () {})
        .then(function () {
          return fetch(config.endpoints.restart, {
            method: 'POST', cache: 'no-store',
            headers: { 'X-WD-Wireless-Tools': '1' }
          }).catch(function () {});
        })
        .then(function () {
          var deadline = Date.now() + 30000;
          (function poll() {
            if (Date.now() > deadline) {
              btn.disabled = false;
              btn.textContent = 'Try restart again';
              return;
            }
            fetch(config.endpoints.version, { cache: 'no-store' })
              .then(function (r) { return r.ok ? r.json() : null; })
              .then(function (j) {
                if (j && j.startedAt && j.startedAt !== oldStartedAt) {
                  setTimeout(function () { window.location.reload(); }, 200);
                } else { setTimeout(poll, 500); }
              })
              .catch(function () { setTimeout(poll, 700); });
          })();
        });
    }

    function mount(el, updateState) {
      host = el;
      state = updateState;
      if (!host) return;
      host.hidden = false;
      host.innerHTML = '<div class="wd-update-loading">Checking this install…</div>';
      fetchInfo().then(showPrimary);
    }

    function unmount() {
      if (host) { host.hidden = true; host.innerHTML = ''; }
      host = null;
    }

    return {
      config: config,
      mount: mount,
      unmount: unmount,
      run: run
    };
  })();

  // Kept for callers that used the old entry point.
  WD.runUpdate = function (mode) { WD.Updater.run(mode); };

  function _renderUpdateError(state) {
    var modal = document.getElementById(WD_ABOUT_ID);
    if (!modal) return;
    var el = modal.querySelector('.wd-about-updateResult');
    if (!el) return;
    el.className = 'wd-about-updateResult is-error';
    var msg;
    if (state && state.kind === 'ratelimit') {
      var mins = state.resetAt ? Math.max(1, Math.ceil((state.resetAt - Date.now()) / 60000)) : null;
      var when = mins ? ('~' + mins + ' min') : 'a bit';
      msg = 'GitHub’s update check is temporarily rate-limited (retry in ' + when + '). ' +
            'Not a problem with your install.';
    } else {
      msg = 'Couldn’t reach GitHub right now — check your connection or try again in a few minutes.';
    }
    el.innerHTML =
      '<span class="wd-about-updateIcon">&#9888;</span> ' + msg + ' ' +
      '<a class="wd-about-updateLink" href="' + WD_RELEASES_URL + '" target="_blank" rel="noopener">Browse releases &rarr;</a>';
  }

  WD.checkForUpdates = function (opts) {
    opts = opts || {};
    if (!opts.force) {
      var cached = _readUpdateCache();
      if (cached) {
        if (cached.error) {
          _renderUpdateError(cached);
        } else {
          _renderUpdateResult(cached);
          _maybeShowUpdateBanner(cached);
        }
        return Promise.resolve(cached);
      }
    } else {
      var rlCached = _readUpdateCache();
      if (rlCached && rlCached.error && rlCached.kind === 'ratelimit' &&
          rlCached.resetAt && Date.now() < rlCached.resetAt) {
        _renderUpdateError(rlCached);
        return Promise.resolve(rlCached);
      }
    }
    _setUpdateBusy(true);
    var versionsUrl = _scriptSrc ? _scriptSrc.replace(/js\/wd-shared\.js.*$/, 'versions.json') : '/assets/versions.json';
    var localVersion = null;
    return fetch(versionsUrl, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (versions) {
        localVersion = versions && versions.suite ? versions.suite : null;
        // Ask our own server, not api.github.com directly. The browser used to
        // make this call itself, with no timeout on it, so on a network that
        // blocks api.github.com - which a corporate one routinely does while
        // leaving git alone - opening About sat there and then said it could
        // not reach GitHub. The server answers the same question from git where
        // it can, over a route already known to work on that machine.
        return fetch('/api/update/status', { cache: 'no-store' });
      })
      .then(function (r) {
        if (!r) throw { kind: 'network' };
        if (!r.ok) throw { kind: 'http', status: r.status };
        return r.json();
      })
      .then(function (payload) {
        if (!payload || !payload.latest) {
          var why = (payload && payload.latestError) || '';
          // A rate limit is not a broken install, and saying so is the whole
          // point of telling them apart.
          throw /rate.?limit/i.test(why) ? { kind: 'ratelimit', resetAt: null }
                                         : { kind: 'network' };
        }
        var latest = String(payload.latest.version || '');
        var url = payload.latest.url || WD_RELEASES_URL;
        var state = {
          checkedAt: Date.now(),
          localVersion: localVersion,
          latestVersion: latest,
          latestUrl: url,
          isNewer: typeof payload.updateAvailable === 'boolean'
            ? payload.updateAvailable
            : (latest && localVersion ? _cmpVer(latest, localVersion) > 0 : false)
        };
        _writeUpdateCache(state);
        _renderUpdateResult(state);
        _maybeShowUpdateBanner(state);
        return state;
      })
      .catch(function (err) {
        var errState = {
          checkedAt: Date.now(),
          error: true,
          kind: (err && err.kind) || 'network',
          resetAt: (err && err.resetAt) || null
        };
        _writeUpdateCache(errState);
        _renderUpdateError(errState);
        return errState;
      })
      .then(function (res) {
        _setUpdateBusy(false);
        return res;
      });
  };

  function _maybeShowUpdateBanner(state) {
    if (!state || !state.isNewer) { _removeUpdateBanner(); _removeUpdateBadge(); return; }
    _renderUpdateBadge(state);
    try {
      var hidden = localStorage.getItem(WD_UPDATE_DISMISS_KEY);
      if (hidden === state.latestVersion) return;
    } catch (e) {}
    _renderUpdateBanner(state);
  }

  function _renderUpdateBanner(state) {
    if (document.getElementById('wdUpdateBanner')) return;
    var b = document.createElement('div');
    b.id = 'wdUpdateBanner';
    b.className = 'wd-update-banner';
    b.innerHTML =
      '<span class="wd-update-icon">&#8681;</span>' +
      '<span class="wd-update-msg">' +
        '<b>Update available: v' + WD.esc(state.latestVersion) + '</b>' +
        '<span class="wd-update-detail"> &middot; You’re running v' + WD.esc(state.localVersion || '?') + '.' +
        '</span>' +
      '</span>' +
      '<button class="wd-update-download" type="button">Update</button>' +
      '<button class="wd-update-close" type="button" title="Dismiss until next release">&times;</button>';
    b.querySelector('.wd-update-close').addEventListener('click', function () {
      try { localStorage.setItem(WD_UPDATE_DISMISS_KEY, state.latestVersion); } catch (e) {}
      _removeUpdateBanner();
    });
    // Opens the About panel rather than linking out to GitHub — the panel is
    // where the install is detected and the update actually runs.
    b.querySelector('.wd-update-download').addEventListener('click', function (e) {
      e.preventDefault();
      WD.openAbout();
    });
    document.body.appendChild(b);
    document.body.classList.add('wd-has-update-banner');
  }

  function _removeUpdateBanner() {
    var el = document.getElementById('wdUpdateBanner');
    if (el) el.remove();
    document.body.classList.remove('wd-has-update-banner');
  }

  function _renderUpdateBadge(state) {
    if (document.getElementById('wdUpdateBadge')) return;
    var b = document.createElement('button');
    b.id = 'wdUpdateBadge';
    b.className = 'wd-update-badge';
    b.type = 'button';
    b.title = 'Update available — click for details';
    // textContent, so no escaping - WD.esc here would render the entities literally.
    b.textContent = '⬆ v' + state.latestVersion;
    b.addEventListener('click', function () { WD.openAbout(); });
    document.body.appendChild(b);
  }

  function _removeUpdateBadge() {
    var el = document.getElementById('wdUpdateBadge');
    if (el) el.remove();
  }

  WD.api = function (action, body) {
    return fetch('/api/' + action, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
      body: JSON.stringify(body || {})
    }).then(function (r) { return r.json(); });
  };

  WD.checkSetup = function () {
    if (window.location.pathname === '/setup') return;
    WD.api('settings/needs_setup').then(function (r) {
      if (r && r.needed) window.location.href = '/setup';
    }).catch(function () {});
  };

  document.addEventListener('DOMContentLoaded', function () {
    WD.syncThemeUI();
    WD.syncFavicon();
    WD.applyVersions();
    WD.checkServerVersion();
    WD.checkForUpdates({ force: false });
    WD.checkSetup();
  });

  WD.copyDiagnostics = function () {
    var versionsUrl = _scriptSrc ? _scriptSrc.replace(/js\/wd-shared\.js.*$/, 'versions.json') : '/assets/versions.json';
    fetch(versionsUrl, { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (versions) {
        var lines = [];
        lines.push('WD Wireless Tools v' + (versions.suite || 'unknown'));
        Object.keys(versions).forEach(function (k) {
          if (k !== 'suite') lines.push('  ' + k + ' : v' + versions[k]);
        });
        lines.push('Browser    : ' + navigator.userAgent);
        lines.push('Platform   : ' + (navigator.platform || 'unknown'));
        lines.push('Screen     : ' + screen.width + 'x' + screen.height);
        lines.push('Viewport   : ' + window.innerWidth + 'x' + window.innerHeight);
        lines.push('Running    : ' + (location.protocol === 'file:' ? 'Local file' : location.origin));
        lines.push('Page       : ' + location.pathname);
        var text = lines.join('\n');
        navigator.clipboard.writeText(text).then(function () {
          WD.toast('Diagnostics copied to clipboard');
        }).catch(function () {
          WD.toast('Copy failed — open dev tools console and try again', 'error');
        });
      })
      .catch(function () {
        var fallback = [
          'WD Wireless Tools',
          'Browser    : ' + navigator.userAgent,
          'Platform   : ' + (navigator.platform || 'unknown'),
          'Running    : ' + location.origin,
          'Page       : ' + location.pathname,
        ].join('\n');
        navigator.clipboard.writeText(fallback).then(function () {
          WD.toast('Basic diagnostics copied (version file unavailable)');
        });
      });
  };

  function checkServerVersion() {
    fetch('/api/version', { cache: 'no-store' }).then(function (r) {
      return r.ok ? r.json() : null;
    }).then(function (info) {
      if (!info) return;
      var existing = document.getElementById('wdStaleBanner');
      if (!info.restartReady) { if (existing) existing.remove(); return; }
      if (existing) return;
      var b = document.createElement('div');
      b.id = 'wdStaleBanner';
      b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;'
        + 'display:flex;align-items:center;gap:10px;padding:8px 16px;'
        + 'background:#b45309;color:#fff;font:13px/1.4 system-ui,sans-serif;';
      b.innerHTML = '<span style="font-size:16px">⚠</span>'
        + '<span id="wdStaleMsg"><b>Server is running v' + WD.esc(info.version)
        + '</b> but v' + WD.esc(info.onDiskVersion)
        + ' is on disk. Click <b>Restart</b> to load it.</span>'
        + '<button type="button" id="wdStaleRestart" style="margin-left:auto;'
        + 'padding:4px 12px;border:1px solid rgba(255,255,255,.5);border-radius:4px;'
        + 'background:transparent;color:#fff;cursor:pointer;font:inherit">Restart now</button>'
        + '<button type="button" style="background:none;border:none;color:#fff;'
        + 'cursor:pointer;font-size:18px;padding:0 4px" title="Dismiss">&times;</button>';
      b.querySelector('[title="Dismiss"]').onclick = function () { b.remove(); };
      b.querySelector('#wdStaleRestart').onclick = function () {
        var btn = b.querySelector('#wdStaleRestart');
        var msg = b.querySelector('#wdStaleMsg');
        btn.disabled = true; btn.textContent = 'Restarting…';
        msg.innerHTML = '<b>Restarting server…</b> Page will reload when ready.';
        var oldStarted = info.startedAt;
        fetch('/api/restart', { method: 'POST' }).catch(function () {});
        var deadline = Date.now() + 20000;
        (function poll() {
          if (Date.now() > deadline) { msg.innerHTML = '<b>Server did not restart.</b> Close and reopen manually.'; return; }
          fetch('/api/version', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (j) {
            if (j && j.startedAt && j.startedAt !== oldStarted) setTimeout(function () { location.reload(); }, 200);
            else setTimeout(poll, 500);
          }).catch(function () { setTimeout(poll, 700); });
        })();
      };
      document.body.prepend(b);
    }).catch(function () {});
  }
  checkServerVersion();
  setInterval(checkServerVersion, 30000);

  // ── Space-to-pan, shared by every pannable canvas ─────────────────────────
  // Ekahau pans on hold-Space-and-drag, and that is the reflex the user brings
  // to this suite, so Quick Walls and Report have to answer to the same key.
  // The state lives here rather than in each tool because a held Space is a
  // property of the window, not of one canvas: the keyup can land anywhere,
  // including on a page element the canvas never sees.
  WD.PanZoom = (function () {
    var held = false;
    var subs = [];

    // Space belongs to the focused control whenever the control already means
    // something by it. Text boxes and selects are the obvious cases -- Report
    // has Client and Prepared by, Quick Walls has the wall-type and template
    // name boxes -- but a checkbox, a radio and a <summary> are toggled by
    // Space too, and taking that away from a keyboard user to serve a mouse
    // gesture is a straight accessibility regression.
    //
    // Buttons are the deliberate exception. Their Space is an activation, they
    // hold focus after a click, and a toolbar button quietly eating the pan is
    // exactly the failure this guard exists to prevent.
    var SPACE_IS_NATIVE_ROLE = { checkbox: 1, radio: 1, switch: 1, menuitemcheckbox: 1, menuitemradio: 1 };
    var SPACE_IS_ACTIVATION_TYPE = { button: 1, submit: 1, reset: 1, file: 1, image: 1 };

    function isTypingTarget(el) {
      if (!el) return false;
      if (el.isContentEditable) return true;
      var role = (el.getAttribute && el.getAttribute('role') || '').toLowerCase();
      if (SPACE_IS_NATIVE_ROLE[role]) return true;
      if (role === 'button') return false;
      var tag = el.tagName;
      if (tag === 'TEXTAREA' || tag === 'SELECT' || tag === 'SUMMARY') return true;
      if (tag === 'BUTTON') return false;
      if (tag !== 'INPUT') return false;
      var t = (el.type || 'text').toLowerCase();
      return !SPACE_IS_ACTIVATION_TYPE[t];
    }

    function notify() {
      for (var i = 0; i < subs.length; i++) {
        try { subs[i](held); } catch (e) {}
      }
    }

    function setHeld(next) {
      if (held === next) return;
      held = next;
      notify();
    }

    document.addEventListener('keydown', function (e) {
      if (e.key !== ' ' && e.key !== 'Spacebar') return;
      if (e.repeat) { if (subs.length) e.preventDefault(); return; }
      if (isTypingTarget(e.target)) return;
      if (!subs.length) return;      // nothing on this page pans; leave Space alone
      // Swallowed so the page does not scroll and a focused button does not fire.
      e.preventDefault();
      setHeld(true);
    });

    document.addEventListener('keyup', function (e) {
      if (e.key !== ' ' && e.key !== 'Spacebar') return;
      if (!held) return;
      e.preventDefault();
      setHeld(false);
    });

    // A Space held while the window loses focus never delivers its keyup, which
    // would otherwise leave the canvas stuck in pan mode until the next press.
    window.addEventListener('blur', function () { setHeld(false); });
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) setHeld(false);
    });

    return {
      isHeld: function () { return held; },
      isTypingTarget: isTypingTarget,
      // Registering makes this page one that cares about Space; returns an
      // unsubscribe so a closed modal stops claiming the key.
      onChange: function (fn) {
        subs.push(fn);
        return function () {
          var i = subs.indexOf(fn);
          if (i >= 0) subs.splice(i, 1);
          if (!subs.length) setHeld(false);
        };
      },
      // True when a mousedown should pan rather than do the tool's own job:
      // Space held, middle button, or right button -- the three ways Ekahau
      // lets you grab the map without changing tool.
      isPanGesture: function (e) {
        return held || e.button === 1 || e.button === 2;
      },
    };
  })();

  window.WD = WD;

  window.toggleTheme = WD.toggleTheme;
  window.toast = WD.toast;
  window.showModal = WD.showModal;
  window.closeModal = WD.closeModal;
  window.esc = WD.esc;
  window.escAttr = WD.escAttr;
  /* ── resizable side panel ────────────────────────────────────────
     Lifted out of Visual Wall Swap so the AP Labeler uses the same thing
     rather than a second copy. Behaviour is unchanged from what shipped
     there: drag the splitter, double-click to reset, arrow keys nudge, the
     width persists per key, and the applied width is always re-derived from
     the remembered preference rather than read back out of the DOM — opening
     a panel before layout settles otherwise clamps it to the minimum and it
     never recovers.

     mount({ splitter, panel, container, key, min, def, maxRatio, onResize })
     returns { reflow, set, get }. */
  /* Foldable side panels, Paint Shop Pro style.

     Folding a section away is how a narrow sidebar gives the part you are
     actually using the whole column. Written here rather than in one tool
     because Quick Walls and the AP Labeler both need it, and two copies of a
     thing that writes to localStorage is two chances to disagree about the
     key.

     Which sections are folded is a view preference, not project data, so
     localStorage is right - and unlike a hidden filter it is plainly visible
     on screen, so persisting it cannot hide anything from anyone. */
  /* Drag a row to reorder a list.

     Quick Walls already taught this gesture with its hotkey slots: grab the
     row itself, drop it where you want it, with the row you are dragging
     faded and the one you are over highlighted. Anything else in the suite
     that reorders a list should feel the same, so the gesture lives here
     rather than being re-invented per tool.

     Quick Walls' own handlers are not reusable as they stand - they swap a
     shortcut into a numbered slot, which is a different operation from moving
     an item to a position - so this is the interaction lifted out, not that
     code moved. Its classes match, so the two look and feel identical.

     `onMove(from, to)` does the actual reordering and re-render; this only
     works out which index went where. */
  WD.mountDragReorder = function (opts) {
    var container = typeof opts.container === 'string'
      ? document.getElementById(opts.container) : opts.container;
    if (!container) return;
    var sel = opts.itemSelector;
    var onMove = opts.onMove;
    var attr = opts.indexAttr || 'data-i';

    function indexOf(el) { return parseInt(el.getAttribute(attr), 10); }
    function clear() {
      container.querySelectorAll(sel).forEach(function (r) {
        r.classList.remove('dragging', 'dragover');
      });
    }

    container.querySelectorAll(sel).forEach(function (row) {
      row.setAttribute('draggable', 'true');
      row.addEventListener('dragstart', function (e) {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', String(indexOf(row)));
        row.classList.add('dragging');
      });
      row.addEventListener('dragend', clear);
      row.addEventListener('dragover', function (e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        // Show where it would land. Without this you are dragging blind,
        // which is most of what makes a drag feel fiddly.
        if (!row.classList.contains('dragging')) row.classList.add('dragover');
      });
      row.addEventListener('dragleave', function () {
        row.classList.remove('dragover');
      });
      row.addEventListener('drop', function (e) {
        e.preventDefault();
        var from = parseInt(e.dataTransfer.getData('text/plain'), 10);
        var to = indexOf(row);
        clear();
        if (!isNaN(from) && !isNaN(to) && from !== to) onMove(from, to);
      });
    });
  };

  WD.mountFolds = function (opts) {
    var selector = opts.selector;
    var KEY = opts.key;
    var onChange = opts.onChange || function () {};

    function read() {
      try {
        var raw = localStorage.getItem(KEY);
        return raw ? new Set(JSON.parse(raw)) : new Set();
      } catch (e) { return new Set(); }
    }
    function write(set) {
      // Array.from, not [].slice.call: a Set has no length, so slice returns
      // an empty array and every fold would persist as "nothing folded".
      try { localStorage.setItem(KEY, JSON.stringify(Array.from(set))); }
      catch (e) { /* private mode */ }
    }
    function apply() {
      var folded = read();
      document.querySelectorAll(selector).forEach(function (el) {
        var on = folded.has(el.dataset.fold);
        el.classList.toggle('is-folded', on);
        var head = el.querySelector('[data-fold-toggle]');
        if (head) head.setAttribute('aria-expanded', on ? 'false' : 'true');
      });
      onChange();
    }
    function toggle(k) {
      var folded = read();
      if (folded.has(k)) folded.delete(k); else folded.add(k);
      write(folded);
      apply();
    }

    document.querySelectorAll(selector).forEach(function (el) {
      var head = el.querySelector('[data-fold-toggle]');
      if (!head) return;
      head.addEventListener('click', function () { toggle(el.dataset.fold); });
      head.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault(); toggle(el.dataset.fold);
        }
      });
    });
    apply();
    return { apply: apply, toggle: toggle };
  };

  WD.mountSplitter = function (opts) {
    var splitter = typeof opts.splitter === 'string'
      ? document.getElementById(opts.splitter) : opts.splitter;
    var panel = typeof opts.panel === 'string'
      ? document.getElementById(opts.panel) : opts.panel;
    var container = typeof opts.container === 'string'
      ? document.querySelector(opts.container) : opts.container;
    if (!splitter || !panel || !container) return null;

    var KEY = opts.key;
    var MIN = opts.min || 260;
    var DEF = opts.def || 320;
    var RATIO = opts.maxRatio || 0.6;
    var onResize = opts.onResize || function () {};
    var pref = DEF;

    function maxWidth() {
      var w = container.clientWidth || window.innerWidth;
      return Math.max(MIN, Math.round(w * RATIO));
    }

    function stored() {
      try {
        var raw = localStorage.getItem(KEY);
        var v = raw == null ? NaN : parseInt(raw, 10);
        return isFinite(v) ? v : null;
      } catch (e) { return null; }
    }

    function reflow() {
      var w = Math.max(MIN, Math.min(maxWidth(), pref));
      if (panel.style.width !== w + 'px') panel.style.width = w + 'px';
      onResize(w);
    }

    function set(px, persist) {
      pref = Math.max(MIN, Math.round(px));
      if (persist) {
        try { localStorage.setItem(KEY, String(pref)); } catch (e) { /* private mode */ }
      }
      reflow();
    }

    if (!splitter._wdBound) {
      splitter._wdBound = true;
      var dragging = false;
      var widthFor = function (clientX) {
        return container.getBoundingClientRect().right - clientX;
      };
      var move = function (ev) {
        if (!dragging) return;
        ev.preventDefault();
        set(widthFor(ev.touches ? ev.touches[0].clientX : ev.clientX), false);
      };
      var up = function () {
        if (!dragging) return;
        dragging = false;
        document.body.classList.remove('wd-resizing');
        set(pref, true);
        window.removeEventListener('mousemove', move);
        window.removeEventListener('mouseup', up);
        window.removeEventListener('touchmove', move);
        window.removeEventListener('touchend', up);
      };
      var down = function (ev) {
        dragging = true;
        document.body.classList.add('wd-resizing');
        window.addEventListener('mousemove', move);
        window.addEventListener('mouseup', up);
        window.addEventListener('touchmove', move, { passive: false });
        window.addEventListener('touchend', up);
        ev.preventDefault();
      };
      splitter.addEventListener('mousedown', down);
      splitter.addEventListener('touchstart', down, { passive: false });
      splitter.addEventListener('dblclick', function () { set(DEF, true); });
      splitter.addEventListener('keydown', function (ev) {
        if (ev.key === 'ArrowLeft')  { set(pref + 24, true); ev.preventDefault(); }
        if (ev.key === 'ArrowRight') { set(pref - 24, true); ev.preventDefault(); }
      });
      window.addEventListener('resize', reflow);
    }

    pref = stored() || DEF;
    reflow();
    // The container can still be mid-layout on first paint.
    requestAnimationFrame(reflow);
    setTimeout(reflow, 80);

    return { reflow: reflow, set: set, get: function () { return pref; } };
  };

  window.escJsStr = WD.escJsStr;
  window.safeColor = WD.safeColor;
  window.wdOpenAbout = WD.openAbout;
})();
