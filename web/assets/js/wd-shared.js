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
        'New release: <b>v' + WD.esc(state.latestVersion) + '</b> ' +
        '<a class="wd-about-updateLink" href="' + WD.escAttr(state.latestUrl) + '" target="_blank" rel="noopener">Download &rarr;</a>';
    } else {
      el.className = 'wd-about-updateResult is-current';
      el.innerHTML =
        '<span class="wd-about-updateIcon">&#10003;</span> ' +
        'You’re on the latest release (v' + WD.esc(state.localVersion || state.latestVersion || '?') + ').';
    }
  }

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
        return fetch(WD_API_LATEST, {
          headers: { 'Accept': 'application/vnd.github+json' },
          cache: 'no-store'
        });
      })
      .then(function (r) {
        if (!r) throw { kind: 'network' };
        if (!r.ok) {
          var remaining = r.headers && r.headers.get ? r.headers.get('X-RateLimit-Remaining') : null;
          var reset = r.headers && r.headers.get ? r.headers.get('X-RateLimit-Reset') : null;
          if (r.status === 403 && remaining === '0') {
            throw { kind: 'ratelimit', resetAt: reset ? parseInt(reset, 10) * 1000 : null };
          }
          throw { kind: 'http', status: r.status };
        }
        return r.json();
      })
      .then(function (release) {
        var latest = String(release.tag_name || '').replace(/^v/i, '');
        var url = release.html_url || WD_RELEASES_URL;
        var state = {
          checkedAt: Date.now(),
          localVersion: localVersion,
          latestVersion: latest,
          latestUrl: url,
          isNewer: latest && localVersion ? _cmpVer(latest, localVersion) > 0 : false
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
    if (!state || !state.isNewer) { _removeUpdateBanner(); return; }
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
        '<span class="wd-update-detail"> &middot; You’re running v' + WD.esc(state.localVersion || '?') + '. ' +
        '<a href="#" class="wd-update-openAbout">Open About</a></span>' +
      '</span>' +
      '<a class="wd-update-download" href="' + WD.escAttr(state.latestUrl) + '" target="_blank" rel="noopener">Download</a>' +
      '<button class="wd-update-close" type="button" title="Dismiss until next release">&times;</button>';
    b.querySelector('.wd-update-close').addEventListener('click', function () {
      try { localStorage.setItem(WD_UPDATE_DISMISS_KEY, state.latestVersion); } catch (e) {}
      _removeUpdateBanner();
    });
    b.querySelector('.wd-update-openAbout').addEventListener('click', function (e) {
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

  window.WD = WD;

  window.toggleTheme = WD.toggleTheme;
  window.toast = WD.toast;
  window.showModal = WD.showModal;
  window.closeModal = WD.closeModal;
  window.esc = WD.esc;
  window.escAttr = WD.escAttr;
  window.escJsStr = WD.escJsStr;
  window.safeColor = WD.safeColor;
  window.wdOpenAbout = WD.openAbout;
})();
