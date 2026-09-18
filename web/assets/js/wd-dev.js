/* ============================================================
   WD Wireless Tools - wd-dev.js

   **This is WaxFrame Professional's dev-toolbar method, ported.**
   Not an interpretation of it. An earlier version of this file
   reshaped the toolbar into a vertical list of named actions and
   dropped the password gate, both for defensible reasons, and both
   were wrong to decide here: he has two products and wants them to
   work the same way. What WaxFrame does is what this does.

   The method, and where each part came from
   ----------------------------------------
   * The gate is `localStorage['wd_dev'] === '1'`, set by a SHA-256
     password modal - `waxframe_dev` and `DEV_PW_HASH` in app.js. A
     wrong password closes the modal and says nothing, exactly as
     WaxFrame's does.
   * The modal is opened from a nav item under an **Advanced**
     heading, and a second nav item - hidden until dev mode is on -
     exits it. WaxFrame: `#navDevSection`, `.active` to reveal.
   * The toolbar is **one horizontal strip**: a `⚙ DEV` label that
     is also the drag handle, buttons carrying an emoji, a short
     label and a `title`, `|` separators grouping them, and a hover
     flyout for a cluster of related actions.
   * It is **dragged by its label**, and the position is remembered
     in `localStorage['wd_dev_toolbar_pos']`. WaxFrame:
     `attachDevToolbarDrag`, `waxframe_dev_toolbar_pos`.
   * Actions are registered **declaratively in markup** and run by a
     single delegated click listener:
     `data-action="call" data-fn="WD.Dev.someHandler"`. The name is
     resolved by walking a dotted path over `window` - a lookup, not
     `eval`, so it is safe under a strict CSP. WaxFrame:
     `callAction` / `resolveDotted` in helper-handlers.js.
   * A toggle button carries `.active` for its state, and a button
     that is not yet safe to press carries `disabled`.

   The one thing that could not carry over
   ---------------------------------------
   **WaxFrame is one page and this suite is nineteen.** WaxFrame
   writes the toolbar, the modal and the nav entries straight into
   `index.html`. Copying that here would mean the same block
   duplicated across nineteen files, drifting the moment one is
   edited. So the *identical markup* is injected once from here -
   same elements, same classes, same data attributes, same
   dispatcher. The method is unchanged; only where the string lives
   differs, because there is no single page to put it on and this
   suite has no server-side include.

   What is his rather than WaxFrame's, and is kept
   ----------------------------------------------
   `--pink` and `--lime` instead of WaxFrame's amber accent; `?dev=1`
   with deliberately no key chord, because he was explicit about
   never landing in this by accident; and the two-stage dry run on
   any action that writes.
   ============================================================ */
(function () {
  'use strict';

  var WD = window.WD = window.WD || {};
  var Dev = WD.Dev = WD.Dev || {};

  /* WaxFrame: `waxframe_dev` / `waxframe_dev_toolbar_pos`. */
  var LS_DEV = 'wd_dev';
  var LS_POS = 'wd_dev_toolbar_pos';

  /* SHA-256 of the dev password, the same shape as WaxFrame's
     DEV_PW_HASH. **This repository is public, and so is WaxFrame's**, so
     this is obfuscation rather than security in both - it keeps a curious
     user out of a maintenance surface, and nothing more. It guards a
     toolbar on a server bound to localhost, which is the only reason that
     trade is acceptable.

     To change it: `python -c "import hashlib;
     print(hashlib.sha256(b'NEW').hexdigest())"` and paste the result here. */
  var DEV_PW_HASH =
    'b62953849ec2565da27c080a91ea2dfdf351580b7a059f5447ad372bae393385';

  function read(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function write(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* private mode */ }
  }
  function drop(key) {
    try { localStorage.removeItem(key); } catch (e) { /* private mode */ }
  }

  /* ── the gate ────────────────────────────────────────────────
     WaxFrame: hashString / showDevModal / hideDevModal /
     submitDevPassword / exitDevMode, in app.js. */

  function hashString(str) {
    return crypto.subtle
      .digest('SHA-256', new TextEncoder().encode(str))
      .then(function (buf) {
        return Array.prototype.map
          .call(new Uint8Array(buf),
                function (b) { return b.toString(16).padStart(2, '0'); })
          .join('');
      });
  }

  Dev.isOn = function () { return read(LS_DEV) === '1'; };

  Dev.showDevModal = function () {
    var modal = document.getElementById('devModal');
    var input = document.getElementById('devPwInput');
    if (modal) modal.classList.add('active');
    setTimeout(function () { if (input) input.focus(); }, 100);
  };

  Dev.hideDevModal = function () {
    var modal = document.getElementById('devModal');
    var input = document.getElementById('devPwInput');
    if (modal) modal.classList.remove('active');
    if (input) input.value = '';
  };

  Dev.submitDevPassword = function () {
    var input = document.getElementById('devPwInput');
    var val = (input && input.value) || '';
    return hashString(val).then(function (hash) {
      if (hash !== DEV_PW_HASH) {
        // WaxFrame says nothing on a wrong password - it just closes.
        // Telling a guesser they were close is worse than saying nothing.
        Dev.hideDevModal();
        return false;
      }
      write(LS_DEV, '1');
      Dev.hideDevModal();
      Dev.mount();
      if (WD.toast) WD.toast('Dev mode enabled', 'ok');
      return true;
    });
  };

  Dev.exitDevMode = function () {
    drop(LS_DEV);
    drop(LS_POS);
    var tb = document.getElementById('devToolbar');
    if (tb) tb.classList.add('is-hidden');
    setNavActive(false);
    document.documentElement.removeAttribute('data-wd-dev');
    if (WD.toast) WD.toast('Dev mode disabled');
  };

  /* ── the delegated dispatcher ────────────────────────────────
     WaxFrame: helper-handlers.js. Scoped to the dev toolbar and its
     modals here rather than migrated across the whole suite - the
     rest of this app wires controls with inline `onclick`, and
     converting all of it is a separate job with its own risk. */

  function resolveDotted(name) {
    if (!name) return undefined;
    var parts = String(name).split('.');
    var parent = null;
    var cur = window;
    for (var i = 0; i < parts.length; i++) {
      if (cur == null) return undefined;
      parent = cur;
      cur = cur[parts[i]];
    }
    // Bound, so `WD.Dev.foo` keeps its `this`. Not eval: this only ever
    // looks a name up in a known scope.
    if (typeof cur === 'function' && parts.length > 1) return cur.bind(parent);
    return cur;
  }
  Dev._resolveDotted = resolveDotted;

  function callAction(el, e) {
    var fn = resolveDotted(el.dataset.fn);
    if (typeof fn !== 'function') return;
    if (e && el.dataset.prevent === '1') e.preventDefault();
    if (el.dataset.argValue === '1') fn(el.value);
    else if (el.dataset.argThis === '1') fn(el);
    else if (el.dataset.argEvent === '1') fn(e);
    else if ('arg' in el.dataset) fn(el.dataset.arg);
    else fn();
    if (e && el.dataset.stop === '1') e.stopPropagation();
  }

  var ACTIONS = {
    'call': callAction,
    'call-chain': function (el) {
      var names = (el.dataset.fn || '').split(',')
        .map(function (s) { return s.trim(); })
        .filter(Boolean);
      for (var i = 0; i < names.length; i++) {
        var fn = resolveDotted(names[i]);
        if (typeof fn === 'function') fn(el);
      }
    },
    'backdrop-call': function (el, e) {
      if (e.target !== el) return;
      var fn = resolveDotted(el.dataset.fn);
      if (typeof fn === 'function') fn();
    },
    'noop': function (_, e) { if (e) e.stopPropagation(); }
  };

  var KEY_ACTIONS = {
    'enter-call': function (el, e) {
      if (e.key !== 'Enter') return;
      var fn = resolveDotted(el.dataset.fn);
      if (typeof fn === 'function') fn();
    }
  };

  /* One listener, walking up from the target to the nearest
     [data-action] - WaxFrame's shape exactly. Scoped to `#wdDevRoot`
     so it can never pick up a click meant for a tool's own control. */
  document.addEventListener('click', function (e) {
    var node = e.target;
    while (node && node !== document) {
      if (node.dataset && node.dataset.action && _isOurs(node)) {
        var fn = ACTIONS[node.dataset.action];
        if (fn) fn(node, e);
        return;
      }
      node = node.parentNode;
    }
  });

  document.addEventListener('keydown', function (e) {
    var el = e.target;
    if (!el || !el.dataset || !el.dataset.keyAction) return;
    if (!_isOurs(el)) return;
    var fn = KEY_ACTIONS[el.dataset.keyAction];
    if (fn) fn(el, e);
  });

  function _isOurs(node) {
    return !!(node.closest && node.closest('#wdDevRoot'));
  }

  /* ── the markup ──────────────────────────────────────────────
     Identical in shape to WaxFrame's `#devToolbar`, `#devModal` and
     the Advanced nav block; injected because this suite has no single
     page to write it on. */

  function toolbarHtml() {
    var inner = (typeof Dev.toolbarInnerHtml === 'function')
      ? Dev.toolbarInnerHtml()
      : '<span class="dev-toolbar-empty">No actions are registered.</span>';
    return '' +
      '<div class="dev-toolbar is-hidden" id="devToolbar">' +
        '<span class="dev-toolbar-label" title="Drag to move this toolbar">' +
          '⚙ DEV</span>' +
        inner +
      '</div>';
  }

  function modalHtml() {
    return '' +
      '<div class="modal-overlay dev-pw-overlay" id="devModal" ' +
           'data-action="backdrop-call" data-fn="WD.Dev.hideDevModal">' +
        '<div class="modal dev-pw-modal">' +
          '<h3 class="modal-title">Dev Tools</h3>' +
          '<input class="dev-pw-input" id="devPwInput" type="password" ' +
                 'placeholder="Password" autocomplete="off" ' +
                 'data-key-action="enter-call" ' +
                 'data-fn="WD.Dev.submitDevPassword">' +
          '<div class="modal-actions">' +
            '<button type="button" class="btn" ' +
                    'title="Close without entering dev mode" ' +
                    'data-action="call" data-fn="WD.Dev.hideDevModal">' +
              '✕ Cancel</button>' +
            '<button type="button" class="btn btn-primary" ' +
                    'title="Submit dev password to enter Dev Mode" ' +
                    'data-action="call" data-fn="WD.Dev.submitDevPassword">' +
              'Unlock</button>' +
          '</div>' +
        '</div>' +
      '</div>' +
      /* Where an action's report is shown. WaxFrame renders detail in a
         modal too - the Troubleshooting Card - rather than growing the
         strip into a panel. */
      '<div class="modal-overlay dev-result-overlay" id="devResultModal" ' +
           'data-action="backdrop-call" data-fn="WD.Dev.closeResult">' +
        '<div class="modal dev-result-modal">' +
          '<h3 class="modal-title" id="devResultTitle">Result</h3>' +
          '<div class="dev-result-body" id="devResultBody"></div>' +
          '<div class="modal-actions">' +
            '<button type="button" class="btn" title="Close this report" ' +
                    'data-action="call" data-fn="WD.Dev.closeResult">' +
              '✕ Close</button>' +
          '</div>' +
        '</div>' +
      '</div>';
  }

  /* WaxFrame's Advanced nav section: one item to open the modal, and one
     hidden until dev mode is on that leaves it.

     **Every nav menu on the page, not one id.** The first version looked for
     `#mainMenu`, which is what Cloud Manager calls its hamburger menu - and
     only three of the nineteen pages use that id. Home calls it `homeMenu`,
     Scale `scaleMenu`, each guide its own, and the drop-zone tools have two
     menus apiece (`dzMenu` before a file is loaded, `helpMenu` after). So on
     sixteen pages the entry silently never appeared, and that is exactly what
     he reported: "I see no link in nav hamburger menu."

     The *classes* are the stable thing. `WD.toggleMenu` in wd-shared.js
     already treats `.main-menu`, `.help-menu` and `.wd-menu` as the set of
     menus on a page, so this uses the same set rather than inventing a fourth
     opinion about what a menu is. */
  var MENU_SELECTOR = '.main-menu, .help-menu, .wd-menu';

  function navMenus() {
    return Array.prototype.slice.call(document.querySelectorAll(MENU_SELECTOR));
  }

  function closeAllMenus() {
    /* Generic, because the closer is page-specific: Cloud Manager has
       `closeMainMenu`, Quick Walls has `toggleDzMenu` and `toggleHelpMenu`,
       and most pages have neither. `open` is the class all of them use. */
    navMenus().forEach(function (m) { m.classList.remove('open'); });
  }

  function injectNavItems() {
    navMenus().forEach(function (menu) {
      if (menu.querySelector('.nav-item-dev')) return;
      /* The drop-zone tools style their rows `help-menu-item`; everything else
         uses `menu-item`. Matching the menu we are in keeps the entry looking
         like the rows above it rather than like a stray button. */
      var itemClass = menu.classList.contains('help-menu')
        ? 'help-menu-item' : 'menu-item';

      var sep = document.createElement('div');
      sep.className = 'menu-sep';
      var head = document.createElement('div');
      head.className = 'menu-section';
      head.innerHTML = '▸ Advanced';

      var open = document.createElement('button');
      open.type = 'button';
      open.className = itemClass + ' nav-item-dev';
      open.title = 'Open Developer Tools — for testing and maintenance';
      open.textContent = '· 🛠 Dev Tools';
      open.addEventListener('click', function () {
        closeAllMenus();
        Dev.showDevModal();
      });

      /* A class, not an id: a page can carry two menus, and two elements
         sharing an id is how the second one stops being findable. */
      var wrap = document.createElement('div');
      wrap.className = 'nav-dev-section';
      var exit = document.createElement('button');
      exit.type = 'button';
      exit.className = itemClass + ' nav-item-exit-dev';
      exit.title = 'Exit Dev Mode and return to normal use';
      exit.textContent = '· 🚪 Exit Dev Mode';
      exit.addEventListener('click', function () {
        closeAllMenus();
        Dev.exitDevMode();
      });
      wrap.appendChild(exit);

      menu.appendChild(sep);
      menu.appendChild(head);
      menu.appendChild(open);
      menu.appendChild(wrap);
    });
  }

  function setNavActive(on) {
    document.querySelectorAll('.nav-dev-section').forEach(function (el) {
      el.classList.toggle('active', !!on);
    });
  }

  /* ── drag, WaxFrame's attachDevToolbarDrag ───────────────────── */

  function attachDevToolbarDrag() {
    var tb = document.getElementById('devToolbar');
    if (!tb || tb.dataset.dragAttached === '1') return;
    var label = tb.querySelector('.dev-toolbar-label');
    if (!label) return;
    tb.dataset.dragAttached = '1';
    label.addEventListener('mousedown', function (e) {
      e.preventDefault();
      // Convert a right-anchored position to explicit left/top first:
      // Chrome and Edge both fight the drag if `right` is still set.
      var rect = tb.getBoundingClientRect();
      tb.style.right = 'auto';
      tb.style.bottom = 'auto';
      tb.style.left = rect.left + 'px';
      tb.style.top = rect.top + 'px';
      var offX = e.clientX - rect.left;
      var offY = e.clientY - rect.top;
      function onMove(ev) {
        var l = Math.max(0, Math.min(window.innerWidth - tb.offsetWidth,
                                     ev.clientX - offX));
        var t = Math.max(0, Math.min(window.innerHeight - tb.offsetHeight,
                                     ev.clientY - offY));
        tb.style.left = l + 'px';
        tb.style.top = t + 'px';
      }
      function onUp() {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        write(LS_POS, JSON.stringify({
          top: parseInt(tb.style.top, 10), left: parseInt(tb.style.left, 10)
        }));
      }
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }

  function restorePosition(tb) {
    var saved = null;
    try { saved = JSON.parse(read(LS_POS) || 'null'); } catch (e) { saved = null; }
    if (!saved) return;
    // Clamped on restore as well as on drag: a position saved on a wider
    // monitor must not put the toolbar off the screen he is using now.
    var l = Math.max(0, Math.min(window.innerWidth - 80, saved.left));
    var t = Math.max(0, Math.min(window.innerHeight - 40, saved.top));
    tb.style.right = 'auto';
    tb.style.bottom = 'auto';
    tb.style.left = l + 'px';
    tb.style.top = t + 'px';
  }

  /* ── result modal ────────────────────────────────────────────── */

  Dev.showResult = function (title, html) {
    var t = document.getElementById('devResultTitle');
    var b = document.getElementById('devResultBody');
    var m = document.getElementById('devResultModal');
    if (t) t.textContent = title;
    if (b) b.innerHTML = html;
    if (m) m.classList.add('active');
  };

  Dev.closeResult = function () {
    var m = document.getElementById('devResultModal');
    if (m) m.classList.remove('active');
  };

  /* Enable or disable a toolbar button by its id. This is how the
     two-stage dry run is expressed in WaxFrame's idiom: the live button
     is rendered `disabled` and only its own preview turns it on. */
  Dev.setEnabled = function (id, on) {
    var btn = document.getElementById(id);
    if (btn) btn.disabled = !on;
  };

  Dev.setActive = function (id, on) {
    var btn = document.getElementById(id);
    if (btn) btn.classList.toggle('active', !!on);
  };

  /* ── mount ───────────────────────────────────────────────────── */

  Dev.mount = function () {
    var root = document.getElementById('wdDevRoot');
    if (!root) {
      root = document.createElement('div');
      root.id = 'wdDevRoot';
      document.body.appendChild(root);
    }
    if (!document.getElementById('devToolbar')) {
      root.innerHTML = toolbarHtml() + modalHtml();
    }
    injectNavItems();

    var tb = document.getElementById('devToolbar');
    if (!Dev.isOn()) {
      if (tb) tb.classList.add('is-hidden');
      setNavActive(false);
      document.documentElement.removeAttribute('data-wd-dev');
      return;
    }
    document.documentElement.setAttribute('data-wd-dev', 'on');
    setNavActive(true);
    if (tb) {
      tb.classList.remove('is-hidden');
      restorePosition(tb);
      attachDevToolbarDrag();
    }
    if (typeof Dev.onMounted === 'function') Dev.onMounted();
  };

  /* `?dev=1` unlocks without the password, `?dev=0` locks. His, not
     WaxFrame's: he asked for a way in that he could never hit by
     accident, and was explicit that it must not be a key chord. The
     password modal is the WaxFrame route and both are deliberate. */
  function readUrl() {
    var value;
    try {
      value = new URLSearchParams(window.location.search).get('dev');
    } catch (e) { return; }
    if (value === '1') write(LS_DEV, '1');
    else if (value === '0') { drop(LS_DEV); drop(LS_POS); }
  }

  document.addEventListener('DOMContentLoaded', function () {
    readUrl();
    Dev.mount();
  });
})();
