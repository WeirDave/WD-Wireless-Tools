/* The project you are working on, in the header of every tool that opens one.

   Each tool used to ask for the .esx on its own, so a project that went through
   Prep, Quick Walls, AP Labeler and Report was picked or dropped four times.
   The chip says which project is current; its menu opens that project in the
   tool you are looking at, checks it (the read-only "Project check"), and keeps
   a short list of recent ones. The server holds the state (tools/current_project.py)
   - this file only shows it and asks for changes.

   A tool takes part by registering how it opens a project:

       WD.Project.setLoader(function () { ... open the current project ... });

   The loader decides the how: Quick Walls and Prep ask the server to read the
   file where it lies; the drop-box tools fetch the bytes with WD.Project.fetchFile().
   A tool that registers nothing still shows the chip and the check, but not
   "Open in this tool" - a control that cannot work is not offered.

   A project dragged in from a folder cannot become current: a browser hands
   over bytes and a name, never a path. The menu says so, and "Choose project"
   uses the file picker so that every tool can open it. */
(function () {
  'use strict';
  var WD = window.WD = window.WD || {};
  var P = WD.Project = {};

  var state = { current: null, recent: [], loader: null, ready: false };
  var wraps = [];

  function esc(s) { return WD.esc ? WD.esc(s) : String(s); }
  function escAttr(s) { return WD.escAttr ? WD.escAttr(s) : String(s); }

  function post(action, body) { return WD.api('project/' + action, body || {}); }

  /* ── what the page can ask ─────────────────────────────────────────────── */

  P.get = function () { return state.current; };
  P.recent = function () { return state.recent.slice(); };
  P.setLoader = function (fn) { state.loader = typeof fn === 'function' ? fn : null; render(); };
  P.canOpenHere = function () {
    return !!(state.loader && state.current && state.current.exists);
  };

  P.refresh = function () {
    return post('current').then(function (r) {
      if (r && r.ok) {
        state.current = r.current || null;
        state.recent = r.recent || [];
      }
      state.ready = true;
      render();
      return state.current;
    }).catch(function () { state.ready = true; render(); return null; });
  };

  function changed(res) {
    return P.refresh().then(function () {
      try { document.dispatchEvent(new CustomEvent('wd-project-change', { detail: state.current })); }
      catch (e) { /* an old browser loses the event, not the project */ }
      return res;
    });
  }

  P.choose = function () {
    closeMenus();
    return post('pick').then(function (res) {
      if (res && res.ok) {
        WD.toast('Current project: ' + res.project.name, 'success');
        return changed(res);
      }
      if (res && res.code === 'picker_unavailable') {
        WD.toast(res.error + ' Drop the project into the tool instead.', 'error');
      } else if (res && res.error && res.code !== 'cancelled') {
        WD.toast(res.error, 'error');
      }
      return res;
    }).catch(function (e) { WD.toast('Could not open the file picker: ' + e, 'error'); });
  };

  P.use = function (path) {
    closeMenus();
    return post('use', { path: path }).then(function (res) {
      if (res && !res.ok) WD.toast(res.error || 'That project could not be used.', 'error');
      return changed(res);
    });
  };

  P.forget = function (path) {
    return post('forget', path ? { path: path } : {}).then(changed);
  };

  P.clear = function () {
    return post('clear').then(function (r) { closeMenus(); return changed(r); });
  };

  P.reveal = function () {
    closeMenus();
    return post('reveal').then(function (r) {
      if (r && r.ok === false && r.error) WD.toast(r.error, 'error');
    });
  };

  /* The current project's bytes as a File, for a tool that takes an upload. */
  P.fetchFile = function () {
    return fetch('/api/project/file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
      body: '{}'
    }).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          throw new Error(j.error || 'The current project could not be read.');
        });
      }
      var name = 'project.esx';
      try { name = decodeURIComponent(r.headers.get('X-WD-File-Name') || '') || name; } catch (e) {}
      return r.blob().then(function (b) { return new File([b], name); });
    });
  };

  P.openHere = function () {
    closeMenus();
    if (!P.canOpenHere()) return Promise.resolve();
    return Promise.resolve(state.loader(state.current)).catch(function (e) {
      WD.toast('Could not open the current project here: ' + (e && e.message || e), 'error');
    });
  };

  /* ── Project check ─────────────────────────────────────────────────────── */

  var PF_ID = 'wdProjectCheck';
  var SEV = { fix: 'Fix', check: 'Check', note: 'Note' };

  function pfModal() {
    var m = document.getElementById(PF_ID);
    if (m) return m;
    m = document.createElement('div');
    m.id = PF_ID;
    m.className = 'modal-overlay wd-pf-overlay';
    m.innerHTML =
      '<div class="modal wd-pf-modal" role="dialog" aria-modal="true" aria-labelledby="wdPfTitle">' +
        '<div class="modal-header">' +
          '<h3 id="wdPfTitle">Project check</h3>' +
          '<button class="btn btn-icon btn-sm wd-pf-close" type="button" title="Close">&times;</button>' +
        '</div>' +
        '<div class="modal-body wd-pf-body" aria-live="polite"></div>' +
        '<div class="wd-pf-foot">' +
          '<button class="btn btn-sm wd-pf-again" type="button">Check again</button>' +
          '<button class="btn btn-sm wd-pf-done" type="button">Close</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(m);
    m.addEventListener('click', function (e) { if (e.target === m) pfClose(); });
    m.querySelector('.wd-pf-close').addEventListener('click', pfClose);
    m.querySelector('.wd-pf-done').addEventListener('click', pfClose);
    m.querySelector('.wd-pf-again').addEventListener('click', function () { P.check(); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') pfClose();
    });
    return m;
  }

  function pfClose() {
    var m = document.getElementById(PF_ID);
    if (m) m.classList.remove('active');
  }

  function renderFinding(f) {
    var sev = SEV[f.severity] ? f.severity : 'check';
    var fix = f.tool
      ? '<a class="wd-pf-fix" href="' + escAttr(f.tool.href) + '">Fix in ' + esc(f.tool.name) + '</a>'
      : (f.fixIn ? '<span class="wd-pf-fix">' + esc(f.fixIn) + '</span>' : '');
    var eg = (f.examples || []).length
      ? '<div class="wd-pf-eg">e.g. ' + f.examples.map(esc).join(', ') +
        (f.count > f.examples.length ? ' &hellip;' : '') + '</div>'
      : '';
    return '<section class="wd-pf-item sev-' + sev + '">' +
      '<div class="wd-pf-head">' +
        '<span class="wd-pf-sev">' + SEV[sev] + '</span>' +
        '<span class="wd-pf-title">' + esc(f.title) + '</span>' +
        '<span class="wd-pf-count">' + esc(String(f.count)) + '</span>' +
      '</div>' +
      '<div class="wd-pf-why">' + esc(f.why) + '</div>' + eg + fix +
    '</section>';
  }

  function renderCheck(res, name) {
    var body = document.getElementById(PF_ID).querySelector('.wd-pf-body');
    if (!res || !res.ok) {
      body.innerHTML = '<p class="wd-pf-error">' +
        esc((res && res.error) || 'The project could not be checked.') + '</p>';
      return;
    }
    var s = res.summary || {};
    var head = '<div class="wd-pf-project">' + esc(name || res.source || '') +
      ' <span class="wd-pf-facts">' + esc(String(res.accessPoints)) + ' access points &middot; ' +
      esc(String(res.floors)) + ' floors</span></div>';
    if (res.clean) {
      body.innerHTML = head + '<p class="wd-pf-clean">Nothing found. Every access point has a name, a model, a floor and a mount height, and the file carries the data its records point to.</p>' + pfScope();
      return;
    }
    var line = [];
    if (s.fix) line.push('<b class="wd-pf-n fix">' + s.fix + ' to fix</b>');
    if (s.check) line.push('<b class="wd-pf-n check">' + s.check + ' to check</b>');
    if (s.note) line.push(s.note + ' for information');
    body.innerHTML = head + '<p class="wd-pf-summary">' + line.join(' &middot; ') + '</p>' +
      (res.findings || []).map(renderFinding).join('') + pfScope();
  }

  function pfScope() {
    return '<p class="wd-pf-scope">This reads what the file records and changes nothing. ' +
      'Channel plans, power and co-channel distance are design choices and are reviewed in ' +
      '<a href="/report">Report</a>.</p>';
  }

  /* *file* (optional) checks a project that was dropped into the page, whose
     path the server never learns; otherwise the current project is read where
     it lies. */
  P.check = function (file) {
    closeMenus();
    var m = pfModal();
    var body = m.querySelector('.wd-pf-body');
    var name = file ? file.name : (state.current && state.current.name) || '';
    m.querySelector('#wdPfTitle').textContent = 'Project check' + (name ? ' — ' + name : '');
    body.innerHTML = '<p class="wd-pf-wait">Reading the project&hellip;</p>';
    m.classList.add('active');
    var req = file
      ? file.arrayBuffer().then(function (buf) {
          return fetch('/api/project/health', {
            method: 'POST',
            headers: { 'Content-Type': 'application/octet-stream', 'X-WD-Wireless-Tools': '1' },
            body: buf
          });
        })
      : fetch('/api/project/health', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
          body: '{}'
        });
    return req.then(function (r) { return r.json(); })
      .then(function (res) { renderCheck(res, name); return res; })
      .catch(function (e) {
        body.innerHTML = '<p class="wd-pf-error">The project could not be checked: ' + esc(e && e.message || e) + '</p>';
      });
  };

  /* ── the chip and its menu ─────────────────────────────────────────────── */

  function closeMenus() {
    wraps.forEach(function (w) {
      var pop = w.querySelector('.wd-project-pop');
      if (pop) pop.classList.remove('open');
      var chip = w.querySelector('.wd-project-chip');
      if (chip) chip.setAttribute('aria-expanded', 'false');
    });
  }

  function popHtml() {
    var cur = state.current;
    var html = '';
    if (cur) {
      html += '<div class="wd-project-sec">' +
        '<div class="wd-project-curname">' + esc(cur.name) + '</div>' +
        '<div class="wd-project-curdir" title="' + escAttr(cur.dir) + '">' + esc(cur.dir) + '</div>' +
        (cur.exists ? '' : '<div class="wd-project-gone">Not where it was. It may have been moved or deleted.</div>') +
      '</div><div class="wd-project-acts">';
      if (state.loader) {
        html += '<button type="button" class="btn btn-sm btn-primary" data-pj="open"' +
          (cur.exists ? '' : ' disabled') + '>Open in this tool</button>';
      }
      html += '<button type="button" class="btn btn-sm" data-pj="check"' + (cur.exists ? '' : ' disabled') + '>Check project</button>' +
        '<button type="button" class="btn btn-sm" data-pj="reveal"' + (cur.exists ? '' : ' disabled') + '>Show folder</button>' +
        '</div>';
    } else {
      html += '<div class="wd-project-sec"><div class="wd-project-curname">No project chosen</div>' +
        '<div class="wd-project-curdir">Choose one and every tool can open it.</div></div>';
    }
    html += '<div class="wd-project-acts">' +
      '<button type="button" class="btn btn-sm" data-pj="choose">' + (cur ? 'Choose another…' : 'Choose project…') + '</button>' +
      (cur ? '<button type="button" class="btn btn-sm" data-pj="stop">Stop using</button>' : '') +
      '</div>';
    var others = state.recent.filter(function (r) { return !cur || r.path !== cur.path; });
    if (others.length) {
      html += '<div class="wd-project-head">Recent</div><ul class="wd-project-recent">' +
        others.map(function (r) {
          return '<li><button type="button" class="wd-project-use' + (r.exists ? '' : ' is-gone') +
            '" data-pj="use" data-path="' + escAttr(r.path) + '" title="' + escAttr(r.path) + '">' +
            '<span class="wd-project-rn">' + esc(r.name) + '</span>' +
            '<span class="wd-project-rd">' + esc(r.exists ? r.dir : 'not where it was') + '</span></button>' +
            '<button type="button" class="wd-project-x" data-pj="drop" data-path="' + escAttr(r.path) +
            '" aria-label="Remove ' + escAttr(r.name) + ' from the list" title="Remove from the list">&times;</button></li>';
        }).join('') + '</ul><div class="wd-project-acts">' +
        '<button type="button" class="btn btn-sm" data-pj="clear">Clear recent projects</button></div>';
    }
    html += '<p class="wd-project-note">A project dragged in from a folder cannot be remembered, ' +
      'because the browser never says where it came from. Choose it here instead.</p>';
    return html;
  }

  function render() {
    wraps.forEach(function (w) {
      var cur = state.current;
      var chip = w.querySelector('.wd-project-chip');
      chip.classList.toggle('has-project', !!cur);
      chip.querySelector('.wd-project-name').textContent = cur ? cur.name : 'No project';
      chip.title = cur ? cur.path : 'No project chosen. Click to choose one.';
      w.querySelector('.wd-project-pop').innerHTML = popHtml();
    });
  }

  function onPopClick(e) {
    var b = e.target.closest('[data-pj]');
    if (!b || b.disabled) return;
    var what = b.getAttribute('data-pj');
    if (what === 'open') P.openHere();
    else if (what === 'check') P.check();
    else if (what === 'reveal') P.reveal();
    else if (what === 'choose') P.choose();
    else if (what === 'stop') { closeMenus(); P.forget(); }
    else if (what === 'use') P.use(b.getAttribute('data-path'));
    else if (what === 'drop') P.forget(b.getAttribute('data-path'));
    else if (what === 'clear') P.clear();
  }

  function newWrap() {
    var w = document.createElement('span');
    w.className = 'wd-project';
    w.innerHTML =
      '<button type="button" class="wd-project-chip" aria-haspopup="true" aria-expanded="false">' +
        '<span class="wd-project-name">No project</span></button>' +
      '<div class="wd-project-pop" role="menu"></div>';
    var chip = w.querySelector('.wd-project-chip');
    chip.addEventListener('click', function (e) {
      e.stopPropagation();
      var pop = w.querySelector('.wd-project-pop');
      var wasOpen = pop.classList.contains('open');
      document.querySelectorAll('.main-menu.open, .help-menu.open, .wd-menu.open')
        .forEach(function (m) { m.classList.remove('open'); });
      closeMenus();
      if (!wasOpen) {
        pop.classList.add('open');
        chip.setAttribute('aria-expanded', 'true');
      }
    });
    w.querySelector('.wd-project-pop').addEventListener('click', onPopClick);
    return w;
  }

  /* One chip beside every theme toggle, as the update pill is, because some
     pages keep two headers and only one shows at a time. */
  function mount() {
    document.querySelectorAll('.theme-toggle').forEach(function (toggle) {
      var anchor = toggle;
      var prev = toggle.previousElementSibling;
      if (prev && prev.classList.contains('wd-project')) return;
      if (prev && prev.classList.contains('wd-update-pill')) {
        anchor = prev;
        var before = prev.previousElementSibling;
        if (before && before.classList.contains('wd-project')) return;
      }
      var w = newWrap();
      anchor.parentNode.insertBefore(w, anchor);
      wraps.push(w);
    });
    render();
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest || !e.target.closest('.wd-project')) closeMenus();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeMenus();
  });

  function start() { mount(); P.refresh(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
  /* The update pill is placed after load; look again so the chip lands in front
     of it rather than behind. */
  window.addEventListener('load', function () { mount(); });
})();
