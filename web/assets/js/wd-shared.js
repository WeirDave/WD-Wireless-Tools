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
  /* Distances. The .esx is metric and he works in feet, so anything that puts
     a distance on screen shows both rather than picking one and leaving the
     reader to convert. That is not decoration: the trim presets were stored as
     3 / 6 / 10 metres and labelled 10, 20 and 33 ft, and read as numbers
     somebody had invented. They are round in feet now, and the metres are
     shown beside them so the metric equivalent is never a surprise. */
  WD.METRES_PER_FOOT = 0.3048;
  WD.FEET_PER_METRE = 3.280839895013123;
  WD.DEFAULT_CUSTOM_MARGIN_FT = 200;

  /* Metres in, "84 ft (26 m)" out. One decimal under 10, none above, because
     "25.6 ft" of clearance is false precision on a scanned drawing. */
  WD.metresAsFeet = function (m) {
    if (m == null || isNaN(m)) return '';
    var ft = m * WD.FEET_PER_METRE;
    var f = ft < 10 ? ft.toFixed(1) : String(Math.round(ft));
    var mm = m < 10 ? m.toFixed(1) : String(Math.round(m));
    return f + ' ft (' + mm + ' m)';
  };

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

  /* Put the Navigation block of every menu in alphabetical order.

     Sorted here rather than in the markup because the markup is seventeen
     pages, most of them carrying the menu twice. Hand-ordering that is a
     standing invitation to drift - the same duplication had already let one
     tool go missing from most of the menus - and it means whoever adds the
     next tool has to insert it in the right slot in thirty-odd places. Sorting
     what is there at load puts a new entry where it belongs wherever it was
     pasted in.

     Home is pinned rather than sorted. It is where the list starts, not a tool
     competing for a place in it, and alphabetically it would land in the
     middle. The Tools and Help sections below are separate blocks and are left
     as their authors arranged them.

     The menu is display:none until it is opened, so this never shows as a
     reshuffle. */
  /* Which wall template is his, which is the fallback, and which one a tool
     opens on. One copy, because Prep and Quick Walls disagreed.

     They listed the same two templates and picked different ones. Quick Walls
     pinned his first and honoured the saved default; Prep rendered whatever
     order the server returned - alphabetical, so "Ekahau Default" sorted
     first - set no `selected` at all, and the browser therefore chose the
     first option. Preparing a project applied Ekahau's stock types unless he
     noticed and changed the dropdown.

     His words: "the default should end up being whatever the customer
     creates. Ekahau should always be the fallback, not the primary."

     So the rule is here rather than in either tool: his own templates sort
     first and one of them is selected; Ekahau's is last and is only chosen
     when there is nothing of his to choose. */
  WD.EKAHAU_TEMPLATE = 'Ekahau Default';

  /* The synthetic entry Quick Walls used to build out of `ekahau_defaults.json`
     before that file became a real template. A saved default may still name
     it. */
  WD.LEGACY_EKAHAU_TEMPLATE = 'Ekahau Defaults';

  WD.isEkahauTemplate = function (name) {
    return name === WD.EKAHAU_TEMPLATE || name === WD.LEGACY_EKAHAU_TEMPLATE;
  };

  /* His first, Ekahau last. Stable within each group, so a list that arrives
     alphabetical stays alphabetical apart from the one move. */
  WD.wallTemplateOrder = function (list) {
    var mine = [], fallback = [];
    (list || []).forEach(function (t) {
      (WD.isEkahauTemplate(t && t.name) ? fallback : mine).push(t);
    });
    return mine.concat(fallback);
  };

  /* The template a tool should open on:
       1. the saved default, if it is still on disk
       2. otherwise the first of his
       3. otherwise Ekahau's, which is what "fallback" means
     Returns the template object, or null when the list is empty. */
  WD.chooseWallTemplate = function (list, savedName) {
    var ordered = WD.wallTemplateOrder(list);
    if (!ordered.length) return null;
    if (savedName) {
      var exact = ordered.filter(function (t) { return t.name === savedName; })[0];
      if (exact) return exact;
      // A default saved under the old synthetic name still means Ekahau's.
      if (savedName === WD.LEGACY_EKAHAU_TEMPLATE) {
        var eka = ordered.filter(function (t) {
          return WD.isEkahauTemplate(t.name);
        })[0];
        if (eka) return eka;
      }
    }
    return ordered[0];
  };

  /* "WD Template — yours · 26 types". The suffix is the point: "Ekahau
     Default" and a template of his own were two rows that did not say which
     was which, and he could not tell them apart. */
  WD.wallTemplateLabel = function (tpl) {
    if (!tpl) return '';
    var n = (tpl.wallTypes ? tpl.wallTypes.length : tpl.count) || 0;
    var role = WD.isEkahauTemplate(tpl.name) ? 'fallback' : 'yours';
    return tpl.name + ' — ' + role + ' · ' + n + ' type' + (n === 1 ? '' : 's');
  };

  /* The saved default's name, or '' - read through the server so both tools
     get the same answer. Never throws; no server means no saved default. */
  WD.savedWallTemplateName = function () {
    if (!WD.api) return Promise.resolve('');
    return WD.api('settings/get').then(function (r) {
      var w = r && r.ok && r.settings && r.settings.walls;
      return (w && typeof w.default_template === 'string') ? w.default_template : '';
    }).catch(function () { return ''; });
  };

  WD.sortNavMenus = function (root) {
    var scope = root || document;
    var heads = scope.querySelectorAll('.menu-section');
    for (var i = 0; i < heads.length; i++) {
      var head = heads[i];
      if (!/Navigation/i.test(head.textContent || '')) continue;

      // Everything up to the next divider or section heading belongs to this
      // block; anything after it is somebody else's list.
      var items = [], node = head.nextElementSibling;
      while (node && !node.classList.contains('menu-section')
             && !/menu-sep$/.test(node.className || '')) {
        if (node.tagName === 'A') items.push(node);
        node = node.nextElementSibling;
      }
      if (items.length < 2) continue;

      var label = function (a) {
        // Strip the leading bullet or home glyph so "· Report" sorts as Report.
        return (a.textContent || '').replace(/^[\s·⌂▸*.-]+/, '').trim();
      };
      var pinned = items.filter(function (a) {
        return (a.getAttribute('href') || '') === '/';
      });
      var rest = items.filter(function (a) { return pinned.indexOf(a) === -1; });

      rest.sort(function (a, b) {
        return label(a).localeCompare(label(b), undefined,
                                      { sensitivity: 'base', numeric: true });
      });

      var parent = head.parentNode;
      var after = head;
      pinned.concat(rest).forEach(function (a) {
        parent.insertBefore(a, after.nextSibling);
        after = a;
      });
    }
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
          var key = el.getAttribute('data-ver');
          var v = versions[key];
          if (!v) return;
          el.textContent = 'v' + v;
          /* The number on this page and the number on a release are two
             different numbers, and not knowing that has cost real time: a fix
             announced for suite 2.103.7 is unrecognisable to someone looking
             at "v2.60.11" in the corner of the Report page, so they pull,
             see the old behaviour and conclude nothing was fixed. The header
             chip carries both, and every version on the page says which
             suite build it came from. */
          if (key !== 'suite' && versions.suite) {
            el.title = 'This tool is v' + v + ', in suite v' + versions.suite
              + '. Release notes are written against the suite version.';
            if (el.classList.contains('ver')) {
              var tag = document.createElement('span');
              tag.className = 'ver-suite';
              tag.textContent = 'suite v' + versions.suite;
              el.appendChild(tag);
            }
          }
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
    /* The files on disk just changed, so any cached "you are N commits behind"
       is now a lie - he has almost certainly only just pulled them. Drop the
       cached answer and take the update banner down, so the two do not sit
       there contradicting each other: one saying to pull, the other saying the
       pull already happened and to reload.

       Once per detection, not on every poll: checkServerVersion runs every few
       seconds while the mismatch lasts. */
    if (!existing) {
      try { localStorage.removeItem(WD_UPDATE_CACHE_KEY); } catch (e) {}
      _removeUpdateBanner();
      _removeUpdateBadge();
    }
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
  // A day was the right number while every check spent one of GitHub's 60
  // anonymous API calls an hour, shared by everyone behind the same address.
  // Since v2.98.1 a git install is answered by `git ls-remote` through our own
  // server, which has no such limit, and the server caches the API for the ZIP
  // path - so the background check can be current instead of merely cheap. At
  // an hour, a page refresh means something again.
  var WD_UPDATE_TTL_MS = 60 * 60 * 1000;
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
              '<div class="wd-about-version">Installed: <b data-ver="suite">v&hellip;</b>' +
                '<span class="wd-about-tracking" id="wdAboutTracking"></span></div>' +
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
            '<div class="wd-about-sectionTitle">Diagnostics</div>' +
            '<div class="wd-about-logRow">' +
              '<span class="wd-about-logLabel">Log file</span>' +
              '<code class="wd-about-logPath" id="wdAboutLogPath">—</code>' +
              '<button class="btn btn-sm wd-about-logOpen" type="button" ' +
                'id="wdAboutLogOpen">Open folder</button>' +
              '<button class="btn btn-sm wd-about-logCopy" type="button" ' +
                'id="wdAboutLogCopy" hidden>Copy path</button>' +
            '</div>' +
            '<div class="wd-about-logHint" id="wdAboutLogHint">Errors are ' +
              'written here, including ones that only appear in the terminal ' +
              'window. It stays on this computer.</div>' +
          '</div>' +
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
    // Show what we knew, so the panel is never blank...
    var cached = _readUpdateCache();
    if (cached) {
      if (cached.error) _renderUpdateError(cached);
      else _renderUpdateResult(cached);
    }
    document.getElementById(WD_ABOUT_ID).classList.add('active');

    // ...then find out whether it is still true. Opening About is the act of
    // asking, so answering from a cache and saying "you have the latest
    // version" was an assertion this panel had not earned: a release could
    // have landed since, and one had - pressing Check right afterwards found
    // it. The check is fast and rate-limit-free for a git install now, so
    // there is nothing left to save by not doing it.
    WD.checkForUpdates({ force: true });
    _renderLogPath();
  };

  /* Where the log is, shown in the panel he already opens to read the version.

     The reason this is on screen at all: a fault appeared in his terminal,
     the window was closed, and the text was gone for good. A path he can read
     off his phone turns the next one into "send me the log". */
  function _renderLogPath() {
    var el = document.getElementById('wdAboutLogPath');
    if (!el) return;
    fetch('/api/version', { headers: { 'X-WD-Wireless-Tools': '1' } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.logPath) return;
        el.textContent = d.logPath;

        var hint = document.getElementById('wdAboutLogHint');
        if (hint && d.logRetentionDays) {
          var mb = Math.round((d.logMaxBytes || 0) / 1000000);
          hint.textContent =
            'Errors are written here, including ones that only appear in the ' +
            'terminal window — it is kept across restarts. The last ' +
            d.logRetentionDays + ' days are retained' +
            (mb ? ', never more than ' + mb + ' MB in total' : '') +
            '. It stays on this computer.';
        }

        var open = document.getElementById('wdAboutLogOpen');
        if (open) {
          open.onclick = function () {
            fetch('/api/logs/reveal', {
              method: 'POST',
              headers: { 'X-WD-Wireless-Tools': '1',
                         'Content-Type': 'application/json' },
              body: '{}'
            }).then(function (r) { return r.json(); })
              .then(function (res) {
                if (res && res.error) WD.toast('Could not open the folder: ' + res.error);
              })
              .catch(function () { WD.toast('Could not open the folder.'); });
          };
        }

        var btn = document.getElementById('wdAboutLogCopy');
        if (!btn || !navigator.clipboard) return;
        btn.hidden = false;
        btn.onclick = function () {
          navigator.clipboard.writeText(d.logPath).then(function () {
            btn.textContent = 'Copied';
            setTimeout(function () { btn.textContent = 'Copy path'; }, 1500);
          });
        };
      })
      .catch(function () { /* the panel is still useful without it */ });
  }

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

  /* "tracking main" or "tracking releases", beside the version.

     Not knowing which question the check was asking is what made this
     confusing for a week: he pulls main, so his version is routinely ahead of
     the newest tag, and a check comparing against tags could only ever say
     "up to date". One line removes the whole class of confusion. */
  function _renderTracking(state) {
    var el = document.getElementById('wdAboutTracking');
    if (!el) return;
    if (!state || !state.tracking) { el.textContent = ''; return; }
    el.textContent = ' · ' + state.tracking;
  }

  function _renderUpdateResult(state) {
    _renderTracking(state);
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

      /* Named, not a bare run(). perform_update() still refuses an unqualified
         update on a development checkout - "dev_pull" is the only mode it
         accepts there, and asking for it explicitly is what keeps a future
         "just update" from quietly detaching HEAD on a working copy. */
      var pullBtn = host.querySelector('.wd-update-pullBtn');
      if (pullBtn) pullBtn.addEventListener('click', function () { run('dev_pull'); });

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

      /* Copies the command shown beside it, not a fixed string. There is more
         than one command in this panel now - the bootstrap line and, on a
         development checkout, the pull - and a button that always copied the
         bootstrap command would hand over the wrong one while reading as the
         right one. Falls back to the bootstrap command if it cannot find a
         code element, which is the shape it had before. */
      host.querySelectorAll('.wd-update-copyBtn').forEach(function (copy) {
        copy.addEventListener('click', function () {
          var row = copy.closest('.wd-update-cmdRow');
          var code = row && row.querySelector('.wd-update-cmd');
          var text = (code && code.textContent) || config.bootstrapCommand;
          var done = function () {
            copy.textContent = 'Copied';
            setTimeout(function () { copy.textContent = 'Copy'; }, 1600);
          };
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(done, function () {});
          } else {
            var ta = document.createElement('textarea');
            ta.value = text;
            document.body.appendChild(ta); ta.select();
            try { document.execCommand('copy'); done(); } catch (e) {}
            document.body.removeChild(ta);
          }
        });
      });
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
        /* "Pull now" is not the Update button, and the difference is the whole
           reason this case exists.

           Update checks out a release *tag*, which on a working copy means
           landing on a detached HEAD with your branch left behind - that is
           what is_dev_checkout() blocks and it still does. Pull moves the
           branch you are already on, and only forward: the server runs
           `git pull --ff-only` and refuses on a dirty tree, a detached HEAD,
           or anything that is not a fast-forward, naming the files each time.

           The typed command stays underneath. A refusal has to leave him
           somewhere to go, and the shell is where he can see what git says and
           decide what to do about it. */
        var pull = 'git -C "' + (info.root || '.') + '" pull';
        render({ body:
          '<div class="wd-update-primaryRow">' +
            '<button class="btn btn-primary wd-update-pullBtn" type="button">' +
              'Pull now' +
            '</button>' +
            '<span class="wd-update-target">v' +
              esc(state.localVersion || info.currentVersion) +
              ' &rarr; v' + esc(state.latestVersion) + '</span>' +
          '</div>' +
          '<div class="wd-update-note">This is a development checkout, so ' +
          'updating the normal way would check out a release tag over your ' +
          'work and detach HEAD. <b>Pull now</b> fast-forwards the branch you ' +
          'are on instead, and stops without changing anything if you have ' +
          'uncommitted work.</div>' +
          '<details class="wd-update-alts"><summary>Or run it yourself</summary>' +
            '<div class="wd-update-altBody">' +
              '<div class="wd-update-alt">' +
                '<div class="wd-update-cmdRow">' +
                  '<code class="wd-update-cmd">' + esc(pull) + '</code>' +
                  '<button class="btn btn-sm wd-update-copyBtn" type="button">Copy</button>' +
                '</div>' +
                '<div class="wd-update-altNote">Or just <code>git pull</code> ' +
                'if you are already in that folder.</div>' +
              '</div>' +
            '</div>' +
          '</details>' });
        wire();
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
          '<b>' + (mode === 'convert' ? 'Switching to git updates…'
                 : mode === 'dev_pull' ? 'Pulling…' : 'Updating…') + '</b>' +
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

      /* Something arrived but the version did not move - a pull that brought
         commits nothing in which bumped versions.json. "Updated v2.99.8 →
         v2.99.8" is what that rendered as before, which reads as a bug in the
         thing that just worked. Say what actually happened instead. */
      var sameVersion = from && to && from === to;
      var headline;
      if (sameVersion) {
        var n = res.commits || 0;
        headline = '<span class="wd-update-tick">&#10003;</span> Pulled' +
          (n ? ' <b>' + esc(String(n)) + '</b> commit' + (n === 1 ? '' : 's') : '') +
          ' &mdash; still on <b>v' + esc(to) + '</b>';
      } else {
        headline = '<span class="wd-update-tick">&#10003;</span> Updated' +
          (from && to ? ' <b>v' + esc(from) + '</b> &rarr; <b>v' + esc(to) + '</b>' : '');
      }

      render({ cls: 'is-done', body:
        '<div class="wd-update-headline">' + headline + '</div>' +
        (sameVersion ? '<div class="wd-update-note">The version number only ' +
          'moves when a release bumps it, so this is normal.</div>' : '') +
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

  /* Set the moment the page starts going away, so a request cancelled by that
     navigation is not mistaken for the network being down. `pagehide` fires
     for a reload, a link and a back/forward; `beforeunload` covers the rest. */
  var _navigatingAway = false;
  window.addEventListener('pagehide', function () { _navigatingAway = true; });
  window.addEventListener('beforeunload', function () { _navigatingAway = true; });

  /* Only a real abort. A cancelled fetch and a genuinely unreachable network
     produce the same message in every engine - "NetworkError when attempting
     to fetch resource" in Firefox, "Failed to fetch" in Chrome and Edge - so
     matching on the text would swallow the real failure too, and About would
     stop being able to say GitHub was unreachable. `_navigatingAway` is the
     signal that actually distinguishes them, and it is set before the
     rejection arrives. */
  function _isAbortError(err) {
    return !!err && err.name === 'AbortError';
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
            : (latest && localVersion ? _cmpVer(latest, localVersion) > 0 : false),
          // Set when the update is "the branch you follow has moved" rather
          // than "there is a newer release". Saying "Update available:
          // v2.100.19" to someone already on 2.100.20 reads as nonsense, and
          // he is the person this case exists for.
          tracking: payload.trackingLabel || null,
          branch: (payload.branch && payload.branch.behind)
            ? payload.branch.branch : null,
          behindBy: (payload.branch && payload.branch.behindBy) || 0,
          branchAt: (payload.branch && payload.branch.behind)
            ? payload.branch.remote : null
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
        /* Leaving the page cancels the request, and a cancelled request is not
           a failed one.

           This is why he refreshed the home page repeatedly and was never
           offered an update. The check starts on DOMContentLoaded and takes
           about 600ms; navigating inside that window - a refresh, or clicking
           through to a tool, which every page does - rejects the fetch, and
           the rejection used to be written to the cache as `kind: network`.
           A cached error suppresses the check for thirty minutes, and every
           page load after it returned that error instead of asking. One
           mistimed click bought half an hour of silence.

           Measured at roughly one load in five before this guard. */
        if (_navigatingAway || _isAbortError(err)) {
          _setUpdateBusy(false);
          return null;
        }
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
    /* Dismiss until the next one - and for a branch update "the next one" is
       a different commit, not a different version. The version does not move
       between branch pushes, so keying on it would have meant one dismissal
       silencing the banner for good. */
    var token = state.branch ? ('branch:' + state.branchAt) : state.latestVersion;
    try {
      if (localStorage.getItem(WD_UPDATE_DISMISS_KEY) === token) return;
    } catch (e) {}
    _renderUpdateBanner(state);
  }

  function _renderUpdateBanner(state) {
    if (document.getElementById('wdUpdateBanner')) return;
    var b = document.createElement('div');
    b.id = 'wdUpdateBanner';
    b.className = 'wd-update-banner';
    var n = state.behindBy || 0;
    var headline = state.branch
      ? '<b>' + (n ? n + ' new commit' + (n === 1 ? '' : 's') + ' on '
                   : 'New commits on ') + WD.esc(state.branch) + '</b>'
      : '<b>Update available: v' + WD.esc(state.latestVersion) + '</b>';
    var detail = state.branch
      ? ' &middot; Your checkout is behind the branch it follows. You’re on v'
        + WD.esc(state.localVersion || '?') + '.'
      : ' &middot; You’re running v' + WD.esc(state.localVersion || '?') + '.';
    b.innerHTML =
      '<span class="wd-update-icon">&#8681;</span>' +
      '<span class="wd-update-msg">' + headline +
        '<span class="wd-update-detail">' + detail + '</span>' +
      '</span>' +
      '<button class="wd-update-download" type="button">Update</button>' +
      '<button class="wd-update-close" type="button" title="Dismiss until next release">&times;</button>';
    b.querySelector('.wd-update-close').addEventListener('click', function () {
      var token = state.branch ? ('branch:' + state.branchAt) : state.latestVersion;
      try { localStorage.setItem(WD_UPDATE_DISMISS_KEY, token); } catch (e) {}
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


  /* ── Settings, without leaving the tool ───────────────────────────────────
     "When you go to Report and you go to run the report and then you realise
     you want to change some defaults, it takes you to the Settings screen but
     it doesn't allow you to go back."

     Measured before this existed, on the Antenna Aim Sheet with a project open
     and the Configure step filled in: clicking through to Settings and pressing
     Back returned to the drop zone. **The project was gone** - not only the
     options, the `.esx` itself, because a dropped file lives in the page's
     memory and navigating away unloads it. So the cost of changing one default
     was opening the file again and redoing the configure step.

     That was survivable while almost every setting had a control on the tool.
     It stopped being survivable in v2.149.0 - v2.152.0, which moved sixteen of
     them onto the Settings page: consolidating the settings made every one of
     them a reason to leave the tool, so the return path had to stop being the
     Back button.

     The settings page opens *over* the tool in an iframe instead. Nothing is
     unloaded, so there is nothing to restore - his project, his stage and his
     options are all still there when it closes, because they never went
     anywhere.

     An iframe rather than a copy of the controls: one settings page, one set of
     save logic, and a tool page that cannot accidentally disagree with it. The
     page is same-origin, so `postMessage` back to the host is checked against
     `location.origin` and nothing else can talk to it.

     `/settings` is the only document the server allows to be framed, and only
     by this origin - see `_allow_same_origin_framing` in `server.py`. */
  var SETTINGS_OVERLAY_ID = 'wdSettingsOverlay';
  var _settingsOnClose = null;

  /* What a tool does when settings change underneath it. Without this the
     overlay is worse than the navigation it replaces: he changes the units,
     closes it, and the report still renders in feet because the page read that
     value once at load. Each tool registers the one call that re-reads its
     settings and repaints. */
  WD.onSettingsChanged = function (fn) { _settingsOnClose = fn; };

  /* The two pages a tool is consulted from and returned to. Going to another
     *tool* is a departure and still navigates - this is for the ones that are
     a detour from the job in hand. The User Guide is the second of them and
     had exactly the same cost: open a project, check how something works,
     come back to the drop zone. */
  var PANELLED = {
    '/settings': 'Suite Settings',
    '/manual':   'User Guide'
  };

  WD.openSettings = function (section) { WD.openPanel('/settings', section); };
  WD.openManual = function (section) { WD.openPanel('/manual', section); };

  WD.openPanel = function (path, section) {
    if (document.getElementById(SETTINGS_OVERLAY_ID)) return;
    if (!Object.prototype.hasOwnProperty.call(PANELLED, path)) return;
    var hash = section ? ('#' + String(section).replace(/^#/, '')) : '';
    var wrap = document.createElement('div');
    wrap.id = SETTINGS_OVERLAY_ID;
    wrap.className = 'wd-settings-overlay';
    wrap.setAttribute('role', 'dialog');
    wrap.setAttribute('aria-modal', 'true');
    wrap.setAttribute('aria-label', PANELLED[path]);
    wrap.innerHTML =
      '<div class="wd-settings-panel">'
      + '<div class="wd-settings-head">'
      +   '<span class="wd-settings-title">' + WD.esc(PANELLED[path]) + '</span>'
      +   '<span class="wd-settings-note">This tool is still open behind this '
      +     'panel. Closing comes straight back to it.</span>'
      +   '<button type="button" class="wd-settings-close" '
      +     'aria-label="Close">Close</button>'
      + '</div>'
      + '<iframe class="wd-settings-frame" title="' + WD.escAttr(PANELLED[path]) + '" '
      +   'src="' + WD.escAttr(path + hash) + '"></iframe>'
      + '</div>';
    document.body.appendChild(wrap);
    document.body.classList.add('wd-settings-open');

    wrap.querySelector('.wd-settings-close')
        .addEventListener('click', function () { WD.closeSettings(); });
    // Clicking the dimmed area behind the panel, which is what a modal in this
    // suite already does everywhere else.
    wrap.addEventListener('mousedown', function (e) {
      if (e.target === wrap) WD.closeSettings();
    });
    /* The framed page's own top bar would be a second set of chrome inside
       the panel, and its Home link would navigate the panel rather than the
       app. `settings.html` hides it for itself the moment it loads, which
       avoids a flash; this covers any other page the panel is pointed at. */
    var frame = wrap.querySelector('.wd-settings-frame');
    frame.addEventListener('load', function () {
      try { frame.contentDocument.body.classList.add('wd-embedded'); }
      catch (e) { /* not same-origin, which PANELLED does not allow anyway */ }
    });
    document.addEventListener('keydown', _settingsEsc, true);
    // Focus the panel rather than the page behind it, so Tab and Esc land here.
    var btn = wrap.querySelector('.wd-settings-close');
    if (btn && btn.focus) { try { btn.focus(); } catch (e) {} }
  };

  function _settingsEsc(e) {
    if (e.key === 'Escape' || e.keyCode === 27) {
      e.stopPropagation();
      WD.closeSettings();
    }
  }

  WD.closeSettings = function () {
    var wrap = document.getElementById(SETTINGS_OVERLAY_ID);
    if (!wrap) return;
    document.removeEventListener('keydown', _settingsEsc, true);
    wrap.parentNode.removeChild(wrap);
    document.body.classList.remove('wd-settings-open');
    /* Always, not only when a save was seen. A save the page made through some
       path this does not know about would otherwise leave the tool reading a
       stale value, and re-reading settings is cheap next to being wrong. */
    if (typeof _settingsOnClose === 'function') {
      try { _settingsOnClose(); } catch (e) { /* a tool that cannot refresh
        still gets its page back, which is the point of the panel */ }
    }
  };

  WD.settingsOverlayOpen = function () {
    return !!document.getElementById(SETTINGS_OVERLAY_ID);
  };

  /* The settings page tells us when it has saved, so a tool can pick the value
     up without waiting for the panel to close - Report's preview is the case
     that wants it. Same-origin only; anything else is ignored. */
  window.addEventListener('message', function (e) {
    if (e.origin !== window.location.origin) return;
    var d = e.data;
    if (!d || d.wd !== 'settings-saved') return;
    if (typeof _settingsOnClose === 'function') {
      try { _settingsOnClose(); } catch (err) {}
    }
  });

  /* Every "Suite Settings" link in every menu, and the in-tool ones Report,
     Cloud Manager and Quick Walls added when their controls moved. The href is
     left exactly as it was and still works: with no JavaScript, or on the
     Settings page itself, it is an ordinary link. This only intercepts the
     click. */
  WD.wireSettingsLinks = function (root) {
    if (window.top !== window.self) return;      // already inside the panel
    if (PANELLED[window.location.pathname]) return;   // this IS one of them
    var scope = root || document;
    scope.addEventListener('click', function (e) {
      var a = e.target && e.target.closest
            ? e.target.closest('a[href^="/settings"], a[href^="/manual"]') : null;
      if (!a) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
      if (a.target && a.target !== '' && a.target !== '_self') return;
      var href = a.getAttribute('href') || '';
      var i = href.indexOf('#');
      var path = i > -1 ? href.slice(0, i) : href;
      if (!PANELLED[path]) return;               // an ordinary link, left alone
      e.preventDefault();
      WD.openPanel(path, i > -1 ? href.slice(i + 1) : '');
    }, true);
  };

  document.addEventListener('DOMContentLoaded', function () {
    try { WD.sortNavMenus(); } catch (e) { /* an unsorted menu still works */ }
    WD.syncThemeUI();
    WD.syncFavicon();
    WD.applyVersions();
    WD.checkServerVersion();
    WD.checkForUpdates({ force: false });
    WD.checkSetup();
    WD.wireSettingsLinks();
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

  /* ── delegated actions, so a page can forbid inline script ──────────
     Backlog item 10. Every control in this suite was wired with an inline
     `onclick`, and that is exactly what a Content-Security-Policy worth
     having forbids: without `'unsafe-inline'` in `script-src`, injected
     script does not run even when an escaper is missed - and nine of the
     fourteen findings in the 2026-09-21 sweep were a value reaching markup
     without the right escaper. There are 264 `innerHTML` assignments in this
     suite and, until now, nothing behind them.

     This is the dev toolbar's dispatcher generalised. `wd-dev.js` keeps its
     own: it is scoped to `#wdDevRoot` on purpose, because a document-wide
     walk would eventually pick up a click meant for a tool. This one *is* the
     document-wide walk, so the two must not both handle the same element -
     hence the `#wdDevRoot` skip below.

     A control is written as:

         <button data-action="call" data-fn="WD.doTheThing">

     The name is resolved by walking a dotted path over `window` and binding
     the result. **A lookup, not `eval`** - which is the point, since a policy
     without 'unsafe-inline' also forbids `eval`, and a dispatcher built on it
     would be no better than the attribute it replaced.

     `data-arg` passes a string, `data-arg-this` the element, `data-arg-event`
     the event, `data-arg-value` the element's value. `data-prevent` and
     `data-stop` call the matching method. An event other than click is asked
     for by name: `data-action-change="call"`.

     A handler that cannot be found warns and does nothing, rather than
     throwing: a dead control that says so in the console is easier to find
     than a page that stopped at the first bad name. */
  WD.actions = (function () {
    function resolveDotted(name) {
      var parts = String(name || '').split('.').filter(Boolean);
      if (!parts.length) return null;
      var ctx = window, obj = window;
      for (var i = 0; i < parts.length; i++) {
        if (obj === null || obj === undefined) return null;
        ctx = obj;
        obj = obj[parts[i]];
      }
      return typeof obj === 'function' ? obj.bind(ctx) : obj;
    }

    /* The arguments a handler is called with, built in one fixed order:

           data-arg / data-arg-json,  data-arg2,  event,  element,  value

       **One declared order rather than a convention per call site.** Several
       handlers take two - `gridRefLabelChanged('a', this)` and
       `_taKey(event, this)` - and inventing a rule for each is how an argument
       order becomes something nobody can remember. This covers both by saying
       which slots are filled:

           data-arg="a" data-arg-this="1"        -> fn('a', el)
           data-arg-event="1" data-arg-this="1"  -> fn(event, el)

       `data-arg` is always a string, because an attribute is. A handler that
       wants a real boolean or number - `toggleAll(true)`, `adjustGridCols(-1)`
       - takes `data-arg-json`, which is parsed. Passing the string "false"
       where a boolean is expected works right up until somebody writes
       `if (arg)`. */
    function argsFor(el, e) {
      var args = [];
      if ('argJson' in el.dataset) {
        try {
          args.push(JSON.parse(el.dataset.argJson));
        } catch (err) {
          args.push(el.dataset.argJson);
        }
      } else if ('arg' in el.dataset) {
        args.push(el.dataset.arg);
      }
      /* A second positional string, for the handful of handlers that take
         two - `_renameInsertFormatToken(inputId, key)`. Named rather than
         packed into `data-arg` with a separator, because a separator is a
         format, and a format inside an attribute is the thing that needs
         escaping rules of its own. */
      if ('arg2' in el.dataset) args.push(el.dataset.arg2);
      if (el.dataset.argEvent === '1') args.push(e);
      if (el.dataset.argThis === '1') args.push(el);
      if (el.dataset.argValue === '1') args.push(el.value);
      return args;
    }

    function call(el, e) {
      var fn = resolveDotted(el.dataset.fn);
      if (typeof fn !== 'function') {
        if (window.console) {
          console.warn('WD.actions: no handler named', el.dataset.fn, el);
        }
        return;
      }
      if (e && el.dataset.prevent === '1') e.preventDefault();
      fn.apply(null, argsFor(el, e));
      if (e && el.dataset.stop === '1') e.stopPropagation();
    }

    var HANDLERS = {
      'call': call,
      'call-chain': function (el, e) {
        var names = String(el.dataset.fn || '').split(',');
        for (var i = 0; i < names.length; i++) {
          var fn = resolveDotted(names[i].trim());
          if (typeof fn === 'function') fn.apply(null, argsFor(el, e));
        }
      },
      /* Only when the click landed on the backdrop itself, never on the
         dialog sitting on top of it. */
      'backdrop-call': function (el, e) {
        if (e.target !== el) return;
        var fn = resolveDotted(el.dataset.fn);
        if (typeof fn === 'function') fn();
      },
      /* `WD.toggleMenu(event, 'helpMenu')` is on the hamburger of all
         nineteen pages, and it is the only two-argument handler the markup
         needs. A named action reads better at the call site than a generic
         way of passing an event *and* a string would, and it keeps the
         dispatcher from growing an argument-order convention nobody would
         remember. */
      'menu': function (el, e) {
        if (WD.toggleMenu) WD.toggleMenu(e, el.dataset.menu);
      },
      /* `document.getElementById('x').click()` - how every hidden file input
         in this suite is opened from a visible button. The element is named
         rather than the call written out, so the markup says what it points
         at and a missing target is a warning rather than a thrown error on
         `null`. */
      'click-target': function (el) {
        var target = document.getElementById(el.dataset.target);
        if (target) target.click();
        else if (window.console) {
          console.warn('WD.actions: no element id', el.dataset.target, el);
        }
      },
      'focus-target': function (el) {
        var target = document.getElementById(el.dataset.target);
        if (target) target.focus();
      },
      'scroll-target': function (el) {
        var target = document.getElementById(el.dataset.target);
        if (target) target.scrollIntoView({ behavior: 'smooth' });
      },
      /* Collapsing a section by toggling a class on an ancestor. The markup
         used to say `this.parentElement.classList.toggle('collapsed')`, which
         is a DOM expression in an attribute - the exact thing a policy
         without 'unsafe-inline' forbids.

         `data-closest` names an ancestor selector; without it the parent is
         used, which is what every existing caller wants. */
      'toggle-class': function (el) {
        var target = el.dataset.closest
          ? el.closest(el.dataset.closest) : el.parentElement;
        if (target && el.dataset.class) {
          target.classList.toggle(el.dataset.class);
        }
      },
      'noop': function (_el, e) { if (e) e.stopPropagation(); }
    };

    function attrFor(type) {
      return 'action' + type.charAt(0).toUpperCase() + type.slice(1);
    }

    function dispatch(type) {
      var selector = type === 'click'
        ? '[data-action], [data-action-click]'
        : '[data-action-' + type + ']';
      return function (e) {
        var el = e.target && e.target.closest ? e.target.closest(selector) : null;
        if (!el) return;
        /* The dev toolbar has its own scoped dispatcher and would otherwise
           run this one as well, firing every handler twice. */
        if (el.closest('#wdDevRoot')) return;
        var name = el.dataset[attrFor(type)]
          || (type === 'click' ? el.dataset.action : null);
        if (!name) return;
        var fn = HANDLERS[name];
        if (fn) fn(el, e);
      };
    }

    var EVENTS = ['click', 'change', 'input', 'submit', 'keyup', 'keydown',
                  'dblclick', 'blur', 'focus', 'contextmenu', 'wheel',
                  'dragstart', 'dragend', 'dragover', 'dragleave', 'drop', 'paste',
                  'mouseenter', 'mouseleave', 'mousedown'];

    function mount() {
      for (var i = 0; i < EVENTS.length; i++) {
        /* Capture for `blur` and `focus`, which do not bubble. */
        var capture = EVENTS[i] === 'blur' || EVENTS[i] === 'focus'
          || EVENTS[i] === 'mouseenter' || EVENTS[i] === 'mouseleave';
        document.addEventListener(EVENTS[i], dispatch(EVENTS[i]), capture);
      }
    }

    return {
      mount: mount,
      _resolveDotted: resolveDotted,
      _handlers: HANDLERS
    };
  })();

  WD.actions.mount();

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
