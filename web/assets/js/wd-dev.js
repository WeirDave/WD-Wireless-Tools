/* ============================================================
   WD Wireless Tools - wd-dev.js

   A developer toolbar for the suite. Modelled on WaxFrame
   Professional's `dev-toolbar`, which this suite did not have an
   equivalent of: a surface that is off by default, unlocked
   deliberately, obviously different from the tools when it is on,
   and cheap to add the next action to.

   What was taken from WaxFrame, and what was not
   ----------------------------------------------
   Taken: the gate (a flag in localStorage, hidden until it is set),
   the floating panel dragged by its own label with the position
   remembered, declarative registration rather than hand-written
   markup, and a `title` on every control that says what it does.

   Not taken: its horizontal strip of icon buttons. That shape had
   already needed a hover flyout at nine buttons, and this one is
   built to hold many more than nine. So the actions render as a
   vertical list where each one carries its name, a sentence, and
   the detail - which is also this project's rule that every
   control says what it is, rather than being an emoji you have to
   remember. Its password modal was left out too: this server binds
   localhost and the password protected nothing that reaching the
   machine did not already give you.

   Unlocking
   ---------
   Add `?dev=1` to any page. `?dev=0` locks it again, as does the
   labelled Exit button on the toolbar itself. Nothing else turns
   it on - there is no key chord, deliberately, because the one
   requirement was that he never lands in here by accident while
   working.

   Registering an action
   ---------------------
       WD.Dev.register({
         id:      'cloud-realign',            // unique, stable
         group:   'Cloud Manager',            // heading to sit under
         label:   'Realign renamed projects', // the control's name
         summary: 'One line, shown always.',
         detail:  'The long version, shown always. Say what it '
                + 'will not do as well as what it will.',
         previewLabel: 'Preview - changes nothing',
         runLabel:     'Run for real',
         preview: function () { return Promise -> result },
         run:     function () { return Promise -> result },
         render:  function (result, isPreview) { return html }
       });

   `preview` is mandatory and `run` is optional; an action with no
   `run` is a read-only diagnostic and renders one button. Where
   both exist the live button stays **disabled until a preview has
   been run in this session**, which is how "dry run by default"
   is made structural rather than a habit - see `_renderAction`.
   ============================================================ */
(function () {
  'use strict';

  var WD = window.WD = window.WD || {};
  var KEY = 'wd-dev';
  var POS_KEY = 'wd-dev-pos';

  var actions = [];
  var mounted = false;

  function esc(s) {
    return (WD.esc ? WD.esc(s) : String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;'));
  }

  function read(key, fallback) {
    try { return localStorage.getItem(key); } catch (e) { return fallback; }
  }
  function write(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* private mode */ }
  }
  function drop(key) {
    try { localStorage.removeItem(key); } catch (e) { /* private mode */ }
  }

  var Dev = WD.Dev = {

    /* Is the toolbar unlocked right now? Everything else reads this
       rather than localStorage, so there is one answer. */
    isOn: function () {
      return read(KEY, null) === '1';
    },

    /* Register an action. Returns the action, so a caller can keep a
       handle on it. A duplicate id replaces rather than appends: a
       page loaded twice in a hot-reload should not grow the list. */
    register: function (action) {
      if (!action || !action.id) throw new Error('A dev action needs an id');
      if (typeof action.preview !== 'function') {
        throw new Error('A dev action needs a preview function: ' + action.id);
      }
      var i;
      for (i = 0; i < actions.length; i++) {
        if (actions[i].id === action.id) { actions[i] = action; return action; }
      }
      actions.push(action);
      if (mounted) Dev.refresh();
      return action;
    },

    /* The registered actions, for tests and for anything that wants to
       enumerate them. A copy, so a caller cannot reorder the real list. */
    actions: function () { return actions.slice(); },

    unlock: function () {
      write(KEY, '1');
      Dev.mount();
      if (WD.toast) WD.toast('Dev mode is on. The tools are unchanged.', 'ok');
    },

    lock: function () {
      drop(KEY);
      var root = document.getElementById('wdDev');
      if (root) root.remove();
      mounted = false;
      document.documentElement.removeAttribute('data-wd-dev');
      if (WD.toast) WD.toast('Dev mode is off.');
    },

    /* Build the toolbar if it is unlocked and not already there. Safe to
       call repeatedly - that is how `register` after mount works. */
    mount: function () {
      if (!Dev.isOn()) return;
      document.documentElement.setAttribute('data-wd-dev', 'on');
      if (document.getElementById('wdDev')) { Dev.refresh(); return; }

      var root = document.createElement('div');
      root.id = 'wdDev';
      root.className = 'wd-dev';
      root.setAttribute('role', 'region');
      root.setAttribute('aria-label', 'Developer tools');
      root.innerHTML =
        '<div class="wd-dev-bar">' +
          '<span class="wd-dev-label" id="wdDevDrag" ' +
                'title="Drag to move this toolbar">DEV MODE</span>' +
          '<button type="button" class="wd-dev-btn wd-dev-toggle" id="wdDevToggle" ' +
                  'aria-expanded="false" aria-controls="wdDevPanel" ' +
                  'title="Show or hide the list of developer actions">' +
            'Open Dev Tools</button>' +
          '<button type="button" class="wd-dev-btn wd-dev-exit" id="wdDevExit" ' +
                  'title="Turn dev mode off. Add ?dev=1 to any page to bring it back.">' +
            'Exit Dev Mode</button>' +
        '</div>' +
        '<div class="wd-dev-panel" id="wdDevPanel" hidden>' +
          '<p class="wd-dev-note">These are maintenance actions, not tools. ' +
          'Each one previews first and changes nothing until you run it for real.</p>' +
          '<div class="wd-dev-actions" id="wdDevActions"></div>' +
        '</div>';
      document.body.appendChild(root);

      document.getElementById('wdDevToggle')
        .addEventListener('click', Dev.togglePanel);
      document.getElementById('wdDevExit')
        .addEventListener('click', Dev.lock);
      _attachDrag(root);
      _restorePosition(root);
      Dev.refresh();
      mounted = true;
    },

    togglePanel: function () {
      var panel = document.getElementById('wdDevPanel');
      var btn = document.getElementById('wdDevToggle');
      if (!panel || !btn) return;
      var opening = panel.hasAttribute('hidden');
      if (opening) panel.removeAttribute('hidden'); else panel.setAttribute('hidden', '');
      btn.setAttribute('aria-expanded', opening ? 'true' : 'false');
      btn.textContent = opening ? 'Close Dev Tools' : 'Open Dev Tools';
    },

    /* Re-render the action list from the registry. */
    refresh: function () {
      var host = document.getElementById('wdDevActions');
      if (!host) return;
      if (!actions.length) {
        host.innerHTML = '<p class="wd-dev-empty">No actions are registered on this page.</p>';
        return;
      }
      var groups = [];
      var byGroup = {};
      actions.forEach(function (a) {
        var g = a.group || 'General';
        if (!byGroup[g]) { byGroup[g] = []; groups.push(g); }
        byGroup[g].push(a);
      });
      host.innerHTML = groups.map(function (g) {
        return '<section class="wd-dev-group">' +
          '<h3 class="wd-dev-group-name">' + esc(g) + '</h3>' +
          byGroup[g].map(_renderAction).join('') +
        '</section>';
      }).join('');
      groups.forEach(function (g) {
        byGroup[g].forEach(function (a) { _wire(a); });
      });
    }
  };

  /* One action's card. The live button is rendered disabled and stays
     that way until a preview has run - `_wire` is the only thing that
     enables it, and only from the preview's own success path. */
  function _renderAction(a) {
    var hasRun = typeof a.run === 'function';
    return '<article class="wd-dev-action" data-action-id="' + esc(a.id) + '">' +
      '<h4 class="wd-dev-action-name">' + esc(a.label || a.id) + '</h4>' +
      (a.summary ? '<p class="wd-dev-action-summary">' + esc(a.summary) + '</p>' : '') +
      (a.detail ? '<p class="wd-dev-action-detail">' + esc(a.detail) + '</p>' : '') +
      '<div class="wd-dev-action-controls">' +
        '<button type="button" class="wd-dev-btn wd-dev-preview" ' +
                'data-dev-preview="' + esc(a.id) + '" ' +
                'title="Work out what this would do and report it. Writes nothing.">' +
          esc(a.previewLabel || 'Preview - changes nothing') + '</button>' +
        (hasRun ?
          '<button type="button" class="wd-dev-btn wd-dev-run" disabled ' +
                  'data-dev-run="' + esc(a.id) + '" ' +
                  'title="Preview first. This button turns on once a preview has run.">' +
            esc(a.runLabel || 'Run for real') + '</button>' : '') +
      '</div>' +
      '<div class="wd-dev-result" data-dev-result="' + esc(a.id) + '" hidden></div>' +
    '</article>';
  }

  function _wire(a) {
    var card = document.querySelector('[data-action-id="' + a.id + '"]');
    if (!card) return;
    var previewBtn = card.querySelector('[data-dev-preview]');
    var runBtn = card.querySelector('[data-dev-run]');
    var out = card.querySelector('[data-dev-result]');

    function show(html, cls) {
      out.className = 'wd-dev-result' + (cls ? ' ' + cls : '');
      out.innerHTML = html;
      out.removeAttribute('hidden');
    }

    function busy(btn, on, restore) {
      if (!btn) return;
      btn.disabled = !!on;
      if (on) { btn.dataset.wasLabel = btn.textContent; btn.textContent = 'Working...'; }
      else if (restore !== false && btn.dataset.wasLabel) {
        btn.textContent = btn.dataset.wasLabel;
      }
    }

    function finish(result, isPreview) {
      if (result && result.error) {
        show('<p class="wd-dev-error">' + esc(result.error) + '</p>', 'is-error');
        return false;
      }
      var html = (typeof a.render === 'function')
        ? a.render(result, isPreview)
        : '<pre class="wd-dev-raw">' + esc(JSON.stringify(result, null, 2)) + '</pre>';
      show(html, isPreview ? 'is-preview' : 'is-done');
      return true;
    }

    previewBtn.addEventListener('click', function () {
      busy(previewBtn, true);
      if (runBtn) runBtn.disabled = true;
      Promise.resolve()
        .then(function () { return a.preview(); })
        .then(function (result) {
          var ok = finish(result, true);
          busy(previewBtn, false);
          // The only path that arms the live button, and it needs the
          // preview to have come back clean. A failed preview leaves it
          // disabled, which is the behaviour we want on a bad day.
          if (ok && runBtn) {
            runBtn.disabled = false;
            runBtn.title = a.runTitle ||
              'Apply what the preview listed. This writes to your files.';
          }
        })
        .catch(function (e) {
          show('<p class="wd-dev-error">' + esc(e && e.message || e) + '</p>', 'is-error');
          busy(previewBtn, false);
        });
    });

    if (runBtn) {
      runBtn.addEventListener('click', function () {
        var question = a.confirm ||
          ('This changes files on disk. ' +
           'Run "' + (a.label || a.id) + '" for real?');
        if (!window.confirm(question)) return;
        busy(runBtn, true);
        previewBtn.disabled = true;
        Promise.resolve()
          .then(function () { return a.run(); })
          .then(function (result) {
            finish(result, false);
            busy(runBtn, false);
            previewBtn.disabled = false;
            // Disarm afterwards. The report on screen describes a run that
            // has happened; clicking again should mean deciding again.
            runBtn.disabled = true;
          })
          .catch(function (e) {
            show('<p class="wd-dev-error">' + esc(e && e.message || e) + '</p>', 'is-error');
            busy(runBtn, false);
            previewBtn.disabled = false;
            runBtn.disabled = true;
          });
      });
    }
  }

  /* Dragged by its label, like WaxFrame's. Position is remembered so it
     stays out of the way of whatever page he left it on. */
  function _attachDrag(root) {
    var handle = root.querySelector('.wd-dev-label');
    if (!handle) return;
    handle.addEventListener('mousedown', function (e) {
      e.preventDefault();
      var rect = root.getBoundingClientRect();
      root.style.right = 'auto';
      root.style.bottom = 'auto';
      root.style.left = rect.left + 'px';
      root.style.top = rect.top + 'px';
      var offX = e.clientX - rect.left;
      var offY = e.clientY - rect.top;
      function move(ev) {
        var l = Math.max(0, Math.min(window.innerWidth - root.offsetWidth, ev.clientX - offX));
        var t = Math.max(0, Math.min(window.innerHeight - root.offsetHeight, ev.clientY - offY));
        root.style.left = l + 'px';
        root.style.top = t + 'px';
      }
      function up() {
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', up);
        write(POS_KEY, JSON.stringify({
          left: parseInt(root.style.left, 10), top: parseInt(root.style.top, 10)
        }));
      }
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
    });
  }

  function _restorePosition(root) {
    var saved = null;
    try { saved = JSON.parse(read(POS_KEY, null) || 'null'); } catch (e) { saved = null; }
    if (!saved) return;
    // Clamp on restore as well as on drag: he may have saved a position on a
    // wider monitor than the one he is reading this on.
    var l = Math.max(0, Math.min(window.innerWidth - 60, saved.left));
    var t = Math.max(0, Math.min(window.innerHeight - 40, saved.top));
    root.style.right = 'auto';
    root.style.bottom = 'auto';
    root.style.left = l + 'px';
    root.style.top = t + 'px';
  }

  /* `?dev=1` unlocks, `?dev=0` locks. Reading it before DOMContentLoaded
     would be too early for `document.body`, so both run on the event. */
  function _readUrl() {
    var value;
    try {
      value = new URLSearchParams(window.location.search).get('dev');
    } catch (e) { return; }
    if (value === '1') write(KEY, '1');
    else if (value === '0') { drop(KEY); drop(POS_KEY); }
  }

  document.addEventListener('DOMContentLoaded', function () {
    _readUrl();
    Dev.mount();
  });
})();
