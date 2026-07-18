/**
 * WD Wireless Tools — shared utilities.
 * Loaded by every page before page-specific scripts.
 */
(function () {
  'use strict';

  var WD = {};

  /* ── Theme ── */

  WD.toggleTheme = function () {
    var cur = document.documentElement.getAttribute('data-theme') || 'dark';
    var next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('wd-theme', next); } catch (e) {}
    WD.syncThemeUI();
  };

  WD.syncFavicon = function () {
    var dark = (document.documentElement.getAttribute('data-theme') || 'dark') === 'dark';
    document.querySelectorAll('link[rel~="icon"]').forEach(function (link) {
      var href = link.getAttribute('href');
      if (!href) return;
      link.setAttribute('href', href.replace(
        /wd-wireless-tools-v8\.0-(?:white-)?(multi-size\.ico|32x32\.png)(?=([?#]|$))/,
        'wd-wireless-tools-v8.0-' + (dark ? 'white-' : '') + '$1'
      ));
    });
  };

  WD.syncThemeUI = function () {
    var dark = (document.documentElement.getAttribute('data-theme') || 'dark') === 'dark';
    var icoTxt = dark ? '\u{1F319}' : '☀️';
    var lblTxt = dark ? 'Dark' : 'Light';
    // Pill-style .theme-toggle — every page uses this now; may appear more
    // than once per page (landing dropzone + workspace toolbar on Report/Walls).
    document.querySelectorAll('.theme-toggle').forEach(function (el) {
      var ico = el.querySelector('.ico');
      var txt = el.querySelector('.txt');
      if (ico) ico.textContent = icoTxt;
      if (txt) txt.textContent = lblTxt;
      if (!ico && !txt) el.textContent = icoTxt + ' ' + lblTxt;
    });
    // Legacy variants — kept for any page that hasn't been converted yet.
    var btn = document.getElementById('themeBtn');
    if (btn) btn.textContent = icoTxt + ' ' + lblTxt;
    document.querySelectorAll('.theme-toggle-btn').forEach(function (b) {
      b.textContent = icoTxt;
    });
    WD.syncFavicon();
  };

  /* ── HTML / attribute escaping ── */

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

  /* ── Toast ── */

  WD.toast = function (msg, type) {
    var container = document.getElementById('toasts');
    if (container) {
      var t = document.createElement('div');
      t.className = 'toast' + (type ? ' ' + type : '');
      t.textContent = msg;
      container.appendChild(t);
      setTimeout(function () {
        t.style.opacity = '0';
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

  /* ── Modal helpers ── */

  WD.showModal = function (id) {
    document.getElementById(id).classList.add('active');
  };

  WD.closeModal = function (id) {
    document.getElementById(id || 'modal').classList.remove('active');
  };

  /* ── Menu toggle ── */

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

  /* ── Init ── */

  document.addEventListener('DOMContentLoaded', function () {
    WD.syncThemeUI();
  });

  /* ── Expose ── */

  window.WD = WD;

  // Global aliases for onclick="..." attributes in HTML markup
  window.toggleTheme = WD.toggleTheme;
  window.toast = WD.toast;
  window.showModal = WD.showModal;
  window.closeModal = WD.closeModal;
  window.esc = WD.esc;
})();
