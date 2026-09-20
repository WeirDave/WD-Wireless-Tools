(function () {
  'use strict';

  var API = WD.api;
  var settings = {};

  window.SP = {};

  function init() {
    API('settings/get', {}).then(function (r) {
      if (!r.ok) return;
      settings = r.settings;
      showLastExport((r.settings.global || {}).last_settings_export);
      populate();
      checkCloud();
      loadOverviews();
      openHashSection();
    });
  }

  /* Arriving from a tool's gear button, e.g. Cloud Manager sends
     `/settings#cloud`. Opening the section is not enough on its own: this
     page is eight sections long, so a section that opens below the fold
     leaves the person who clicked the gear looking at the top of the page,
     hunting for the control they just asked for. Scroll to it as well. */
  function openHashSection() {
    var hash = location.hash.replace('#', '');
    if (!hash) return;
    var sec = document.getElementById('sec-' + hash);
    if (!sec) return;
    sec.open = true;
    sec.scrollIntoView({ block: 'start' });
  }


  function populate() {
    var g = settings.global || {};
    var o = settings.organizer || {};
    var c = settings.cloud || {};

    document.getElementById('sOutputDir').value = g.output_dir || '';
    renderSubfolders(g.subfolders || [], g.subfolder_names || {});
    renderCustomDests(g.custom_destinations || []);

    document.getElementById('sImageExt').value = (o.image_ext || []).join(', ');
    document.getElementById('sPlanExt').value = (o.plan_ext || []).join(', ');
    document.getElementById('sReportExt').value = (o.report_ext || []).join(', ');
    document.getElementById('sPdfKw').value = (o.report_keywords || []).join(', ');
    document.getElementById('sJsonKw').value = (o.json_report_keywords || []).join(', ');
    document.getElementById('sSkipDirs').value = (o.skip_dirs || []).join(', ');
    document.getElementById('sCreateTpl').value = o.create_folder_template || '';

    var rule = c.merge_rule || 'ask';
    var radios = document.querySelectorAll('input[name="mergeRule"]');
    for (var i = 0; i < radios.length; i++) {
      radios[i].checked = radios[i].value === rule;
    }
    document.getElementById('sLiveMs').value = String(c.live_interval_ms || 30000);
    var own = c.default_owner_filter || 'mine';
    document.querySelectorAll('input[name="setowner"]').forEach(function (r) {
      r.checked = (r.value === own);
    });

    // Read by walls.js after a save. It had no control anywhere until now,
    // so the only way to turn it off was editing settings.json by hand.
    var w = settings.walls || {};
    document.getElementById('sWallsReveal').checked = w.reveal_source_after_save !== false;

    /* The four report identity defaults and the file-name switch. They used to
       be reachable only from a modal inside Report, which is a long way from
       where anyone looks for something they saved. A single report can still
       override them in Report's Configure step - that is the per-run control
       and it has not moved. */
    var rp = settings.report || {};
    document.getElementById('sRepClient').value = rp.client_name || '';
    document.getElementById('sRepPreparedBy').value = rp.prepared_by || '';
    document.getElementById('sRepProjectRef').value = rp.project_ref || '';
    document.getElementById('sRepRevision').value = rp.revision || '';
    document.getElementById('sRepIncludeRev').checked =
      rp.include_revision_in_filename !== false;
  }

  var _subfolders = [];
  var _subfolderNames = {};

  function renderSubfolders(keys, names) {
    if (keys) { _subfolders = keys.slice(); _subfolderNames = Object.assign({}, names); }
    var list = document.getElementById('sSfList');
    var effectiveNames = _subfolders.map(function (k) { return _subfolderNames[k] || k; });
    list.innerHTML = effectiveNames.map(function (name, i) {
      return '<li class="sf-item" data-idx="' + i + '">' +
        '<span class="sf-handle">&#9776;</span>' +
        '<input type="text" value="' + escAttr(name) + '" onchange="SP._updateSf(' + i + ', this.value)">' +
        (effectiveNames.length > 1 ? '<button class="sf-remove" onclick="SP._removeSf(' + i + ')">&times;</button>' : '') +
        '</li>';
    }).join('');
  }

  SP._updateSf = function (i, val) {
    _subfolderNames[_subfolders[i]] = val.trim() || _subfolders[i];
  };

  SP._removeSf = function (i) {
    var key = _subfolders.splice(i, 1)[0];
    delete _subfolderNames[key];
    renderSubfolders();
  };

  SP.addSubfolder = function () {
    var base = 'subfolder', key = base, n = 1;
    while (_subfolders.indexOf(key) !== -1) { key = base + n; n++; }
    _subfolders.push(key);
    _subfolderNames[key] = '';
    renderSubfolders();
    var items = document.querySelectorAll('#sSfList .sf-item input[type="text"]');
    var last = items[items.length - 1];
    if (last) { last.focus(); last.select(); }
  };

  function renderCustomDests(customs) {
    var host = document.getElementById('sCdList');
    host.innerHTML = '';
    (customs || []).forEach(function (c) { host.appendChild(buildCdRow(c)); });
  }

  function buildCdRow(c) {
    c = c || {};
    var row = document.createElement('div');
    row.className = 's-cd-row';
    row.innerHTML =
      '<div class="s-cd-grid">' +
        '<label>Folder name<input type="text" class="cd-name" value="' + escAttr(c.name || '') + '"></label>' +
        '<label>Extensions<input type="text" class="cd-exts" value="' + escAttr((c.exts || []).join(', ')) + '"></label>' +
        '<label>PDF keywords<input type="text" class="cd-pdfkw" value="' + escAttr((c.pdf_keywords || []).join(', ')) + '"></label>' +
        '<label>JSON keywords<input type="text" class="cd-jsonkw" value="' + escAttr((c.json_keywords || []).join(', ')) + '"></label>' +
      '</div>' +
      '<button class="s-cd-remove" title="Remove">&times;</button>';
    row.querySelector('.s-cd-remove').addEventListener('click', function () { row.remove(); });
    return row;
  }

  SP.addCustomDest = function () {
    document.getElementById('sCdList').appendChild(buildCdRow({}));
  };

  function collectCustomDests() {
    var rows = document.querySelectorAll('#sCdList .s-cd-row');
    var out = [];
    for (var i = 0; i < rows.length; i++) {
      var name = rows[i].querySelector('.cd-name').value.trim();
      if (!name) continue;
      out.push({
        name: name,
        exts: splitComma(rows[i].querySelector('.cd-exts').value),
        pdf_keywords: splitComma(rows[i].querySelector('.cd-pdfkw').value),
        json_keywords: splitComma(rows[i].querySelector('.cd-jsonkw').value)
      });
    }
    return out;
  }

  function splitComma(s) {
    return (s || '').split(',').map(function (x) { return x.trim(); }).filter(Boolean);
  }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function escAttr(s) { return WD.escAttr(s); }

  SP.pickFolder = function () {
    API('cloud/pick_folder', {}).then(function (r) {
      if (r.path) document.getElementById('sOutputDir').value = r.path;
    });
  };

  SP.clearFolder = function () {
    document.getElementById('sOutputDir').value = '';
  };

  function checkCloud() {
    API('cloud/status', {}).then(function (r) {
      var el = document.getElementById('sCloudStatus');
      var txt = document.getElementById('sCloudStatusText');
      if (r.connected) {
        el.classList.add('connected');
        txt.textContent = 'Connected' + (r.email ? ' as ' + r.email : '');
      } else {
        el.classList.remove('connected');
        txt.textContent = 'Not connected';
      }
    });
  }

  SP.forgetLogin = function () {
    API('cloud/forget_login', {}).then(function () {
      WD.toast('Login forgotten', 'ok');
      checkCloud();
    });
  };

  SP.resetOrganizer = function () {
    if (!confirm('Reset all Squirrel settings to factory defaults?')) return;
    API('settings/get', {}).then(function (r) {
      var defaults = {
        image_ext: [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".svg", ".webp", ".heic"],
        plan_ext: [".dwg", ".dxf", ".vsd", ".vsdx", ".pcp"],
        report_ext: [".docx", ".doc", ".xlsx", ".xls", ".xlsm", ".csv", ".pptx", ".ppt", ".html", ".htm", ".txt", ".rtf"],
        report_keywords: ["report", "audit", "coverage", "validation", "bom", "as-built", "asbuilt", "summary"],
        json_report_keywords: ["waxframe", "checkpoint", "assessment", "report"],
        skip_dirs: ["backups", "backup", "output", "outputs", "archive", "archives", ".git", "images", "floorplans", "reports"],
        create_folder_template: "",
        rename: { strip_prefix: "", strip_suffix: "", regex_from: "", regex_to: "", separator: "", case: "", prefix: "", suffix: "" }
      };
      API('settings/update', { patch: { organizer: defaults } }).then(function (r2) {
        if (r2.ok) { settings = r2.settings; populate(); WD.toast('Organizer reset to defaults', 'ok'); }
      });
    });
  };

  SP.rerunSetup = function () {
    API('settings/reset_setup', {}).then(function () {
      window.location.href = '/setup';
    });
  };

  SP.save = function () {
    var cleanNames = {};
    var cleanKeys = _subfolders.filter(function (key) {
      var name = (_subfolderNames[key] || '').trim();
      if (!name) return false;
      cleanNames[key] = name;
      return true;
    });

    /* Fall back to what is saved, not to 'ask'.

       This page offered ask / skip / overwrite while the tool implements
       ask / newer / both / skip. Two of his four legal values could not be
       shown here, so nothing was checked - and this loop then wrote 'ask',
       which meant saving the Settings page for any reason at all silently
       reset a merge rule of "Keep newer" or "Keep both". `overwrite` was not
       a legal value either: cloud.js rejects anything outside MERGE_RULES and
       falls back to 'ask', so choosing it here did nothing and said it had.
       The radios above are the tool's four now; this keeps the saved value
       when none is checked rather than inventing one. */
    var mergeRule = (settings.cloud || {}).merge_rule || 'ask';
    var radios = document.querySelectorAll('input[name="mergeRule"]');
    for (var i = 0; i < radios.length; i++) {
      if (radios[i].checked) { mergeRule = radios[i].value; break; }
    }
    var ownerFilter = (settings.cloud || {}).default_owner_filter || 'mine';
    var owners = document.querySelectorAll('input[name="setowner"]');
    for (var j = 0; j < owners.length; j++) {
      if (owners[j].checked) { ownerFilter = owners[j].value; break; }
    }

    var patch = {
      global: {
        output_dir: document.getElementById('sOutputDir').value,
        subfolders: cleanKeys,
        subfolder_names: cleanNames,
        custom_destinations: collectCustomDests()
      },
      organizer: {
        image_ext: splitComma(document.getElementById('sImageExt').value),
        plan_ext: splitComma(document.getElementById('sPlanExt').value),
        report_ext: splitComma(document.getElementById('sReportExt').value),
        report_keywords: splitComma(document.getElementById('sPdfKw').value),
        json_report_keywords: splitComma(document.getElementById('sJsonKw').value),
        skip_dirs: splitComma(document.getElementById('sSkipDirs').value),
        create_folder_template: document.getElementById('sCreateTpl').value
      },
      cloud: {
        merge_rule: mergeRule,
        default_owner_filter: ownerFilter,
        live_interval_ms: parseInt(document.getElementById('sLiveMs').value, 10) || 30000,
      },
      walls: {
        reveal_source_after_save: document.getElementById('sWallsReveal').checked
      },
      report: {
        client_name: document.getElementById('sRepClient').value.trim(),
        prepared_by: document.getElementById('sRepPreparedBy').value.trim(),
        project_ref: document.getElementById('sRepProjectRef').value.trim(),
        revision: document.getElementById('sRepRevision').value.trim(),
        include_revision_in_filename: document.getElementById('sRepIncludeRev').checked
      }
    };

    API('settings/update', { patch: patch }).then(function (r) {
      if (r.ok) {
        settings = r.settings;
        loadOverviews();          // the values below the controls move too
        WD.toast('Settings saved', 'ok');
      } else {
        WD.toast(r.error || 'Save failed', 'error');
      }
    });
  };

  /* ── backup and restore ──────────────────────────────────────────────
     Written after a night of testing overwrote his live settings. His Quick
     Walls defaults went, his wall-type colours went, and the keyboard
     shortcuts survived only because he had typed them into OneNote.

     localStorage is collected here rather than on the server because the
     server cannot see it. It goes into the bundle so a restore is complete,
     and comes back out on import for the page to write. */
  function readBrowserState() {
    var out = {};
    try {
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (k) out[k] = localStorage.getItem(k);
      }
    } catch (e) { /* private window, blocked storage - a partial bundle
                     beats refusing to make one */ }
    return out;
  }

  function showLastExport(when) {
    var el = document.getElementById('sLastExport');
    if (!el) return;
    if (!when) { el.innerHTML = '<b>No export taken yet.</b>'; return; }
    var then = new Date(when);
    var days = Math.floor((Date.now() - then.getTime()) / 86400000);
    var ago = days <= 0 ? 'today' : days === 1 ? 'yesterday' : days + ' days ago';
    el.innerHTML = 'Last exported <b>' + WD.esc(ago) + '</b> — '
      + WD.esc(then.toLocaleString());
  }

  SP.exportSettings = function () {
    var note = document.getElementById('sExportResult');
    API('settings/export', { browser: readBrowserState() }).then(function (r) {
      if (!r || !r.ok) {
        WD.toast((r && r.error) || 'Export failed', 'error');
        return;
      }
      var text = JSON.stringify(r.bundle, null, 2);
      var blob = new Blob([text], { type: 'application/json' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = r.filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 2000);

      var files = Object.keys(r.bundle.files || {}).length;
      var browser = Object.keys(r.bundle.browser || {}).length;
      if (note) {
        note.hidden = false;
        note.innerHTML = 'Saved <b>' + WD.esc(r.filename) + '</b> — your settings, '
          + files + ' file' + (files === 1 ? '' : 's') + ' (templates and report '
          + 'details), and ' + browser + ' per-browser value'
          + (browser === 1 ? '' : 's') + '. Keep it somewhere that is not this '
          + 'machine.';
      }
      showLastExport(r.takenAt || new Date().toISOString());
      WD.toast('Settings exported', 'ok');
    });
  };

  var _pendingBundle = null;

  SP.chooseImport = function (input) {
    var file = input && input.files && input.files[0];
    input.value = '';                    // so the same file can be picked twice
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function () {
      var bundle;
      try {
        bundle = JSON.parse(String(reader.result));
      } catch (e) {
        WD.toast('That file is not readable JSON', 'error');
        return;
      }
      _pendingBundle = bundle;
      API('settings/import_preview',
          { bundle: bundle, browser: readBrowserState() }).then(showImportPreview);
    };
    reader.onerror = function () { WD.toast('Could not read that file', 'error'); };
    reader.readAsText(file);
  };

  function line(entry, kind) {
    var k = WD.esc(String(entry.key));
    if (kind === 'change') {
      return '<div class="s-imp s-imp-change"><code>' + k + '</code>'
        + '<span class="s-imp-old">' + WD.esc(short(entry.old)) + '</span>'
        + '<span class="s-imp-arrow">&rarr;</span>'
        + '<span class="s-imp-new">' + WD.esc(short(entry.new)) + '</span></div>';
    }
    return '<div class="s-imp s-imp-' + kind + '"><code>' + k + '</code>'
      + '<span class="s-imp-new">' + WD.esc(short(entry.new)) + '</span></div>';
  }

  function short(v) {
    if (v === null || v === undefined) return '(not set)';
    if (typeof v === 'object') return JSON.stringify(v).slice(0, 70);
    var s = String(v);
    return s === '' ? '(empty)' : s.slice(0, 70);
  }

  function showImportPreview(p) {
    if (!p || !p.ok) {
      WD.toast((p && p.error) || 'That file could not be read as a settings export',
               'error');
      return;
    }
    document.getElementById('sImportFrom').textContent =
      'Exported ' + (p.from.exportedAt || 'at an unknown time')
      + ' from version ' + (p.from.appVersion || 'unknown') + '.';

    var c = p.counts, parts = [], detail = '';
    ['settings', 'files', 'browser'].forEach(function (section) {
      var n = c[section];
      if (!n.add && !n.change && !n.unknown) return;
      parts.push(n.add + ' added, ' + n.change + ' changed in ' + section);
    });

    var summary = document.getElementById('sImportSummary');
    if (!p.willChangeAnything) {
      summary.innerHTML = '<div class="s-imp-none">Everything in this file '
        + 'already matches what you have. Importing would change nothing.</div>';
    } else {
      summary.innerHTML = '<div class="s-imp-sum">' + WD.esc(parts.join(' · '))
        + '</div>';
    }

    if (p.schemaNotes && p.schemaNotes.length) {
      detail += '<div class="s-imp-warn">' + WD.esc(p.schemaNotes.join(' ')) + '</div>';
    }
    (p.machineSpecific || []).forEach(function (m) {
      if (m.existsHere) return;
      detail += '<div class="s-imp-warn"><b>' + WD.esc(m.key) + '</b> is a folder '
        + 'from another machine and does not exist here: <code>'
        + WD.esc(short(m.new)) + '</code>. Importing it will point the suite at '
        + 'a folder that is not there, and you can set it again afterwards.</div>';
    });

    ['settings', 'files', 'browser'].forEach(function (section) {
      var block = p[section] || {};
      var rows = '';
      (block.change || []).forEach(function (e) { rows += line(e, 'change'); });
      (block.add || []).forEach(function (e) { rows += line(e, 'add'); });
      (block.unknown || []).forEach(function (e) { rows += line(e, 'unknown'); });
      if (!rows) return;
      var same = (block.same || []).length;
      detail += '<div class="s-imp-group"><div class="s-imp-head">' + section
        + (same ? ' <span class="s-imp-same">' + same + ' already identical</span>' : '')
        + '</div>' + rows + '</div>';
    });
    document.getElementById('sImportDetail').innerHTML = detail;
    document.getElementById('sImportApplyBtn').disabled = !p.willChangeAnything;
    WD.showModal('importModal');
  }

  SP.cancelImport = function () {
    _pendingBundle = null;
    WD.closeModal('importModal');
  };

  SP.applyImport = function () {
    if (!_pendingBundle) return;
    var btn = document.getElementById('sImportApplyBtn');
    btn.disabled = true;
    btn.textContent = 'Importing…';
    API('settings/import_apply', {
      bundle: _pendingBundle,
      sections: ['settings', 'files', 'browser'],
    }).then(function (r) {
      btn.textContent = 'Import these changes';
      if (!r || !r.ok) {
        btn.disabled = false;
        WD.toast((r && r.error) || 'Import failed', 'error');
        return;
      }
      // localStorage is the page's to write, so the server hands the keys back.
      var wrote = 0;
      try {
        Object.keys(r.browser || {}).forEach(function (k) {
          localStorage.setItem(k, r.browser[k]);
          wrote++;
        });
      } catch (e) { /* blocked storage - the server-side settings still landed */ }

      WD.closeModal('importModal');
      _pendingBundle = null;
      var files = (r.applied && r.applied.files || []).length;
      var skipped = (r.browserSkipped || []).length;
      if (skipped) {
        var note = document.getElementById('sExportResult');
        if (note) {
          note.hidden = false;
          note.innerHTML = skipped + ' per-browser value'
            + (skipped === 1 ? ' was' : 's were') + ' left alone — panel '
            + 'widths and folded sections belong to the browser you set them in.';
        }
      }
      WD.toast('Imported ' + (r.applied && r.applied.settings || 0) + ' settings, '
               + files + ' file' + (files === 1 ? '' : 's') + ' and ' + wrote
               + ' browser value' + (wrote === 1 ? '' : 's')
               + (r.backup ? ' — your previous settings were saved first' : ''),
               'ok');
      setTimeout(function () { location.reload(); }, 1400);
    });
  };

  /* ── The per-tool overview ────────────────────────────────────────────────
     "We need an overview of the settings for each of the tools." This is it,
     and it is rendered from `web/assets/settings-registry.json` rather than
     written out by hand, because a hand-written list is a list that goes
     stale. Adding a setting to the registry is already compulsory, so a
     registered setting appears here without anyone remembering to add it.

     Three things per row: what the setting is, what it is set to right now,
     and - only when its control is not on this page - which of the tool's own
     controls owns it. A setting whose control is here needs no signpost; the
     control is a few lines above.

     `key_prefix` entries stand for a whole family (every saved rename
     pattern, say). They cannot show one value, so they show how many are
     saved, which is the useful number. */
  var WHERE = {
    'cloud-modal':  'Cloud Manager',
    'report-modal': 'Report',
    'report-tool':  'Report',
    'walls-tool':   'Quick Walls',
    'plantrim-tool': 'PlanTrim',
    'organizer-tool': 'Squirrel',
    'rename-tool':  'Rename',
    'aprename-tool': 'AP Labeler'
  };

  function valueAt(key) {
    var parts = key.split('.');
    var node = settings;
    for (var i = 0; i < parts.length; i++) {
      if (node === null || typeof node !== 'object' || !(parts[i] in node)) return undefined;
      node = node[parts[i]];
    }
    return node;
  }

  function describe(v) {
    if (v === undefined || v === null || v === '') return null;
    if (v === true) return 'On';
    if (v === false) return 'Off';
    if (Array.isArray(v)) return v.length ? v.join(', ') : null;
    if (typeof v === 'object') {
      var n = Object.keys(v).length;
      return n ? n + (n === 1 ? ' saved' : ' saved') : null;
    }
    return String(v);
  }

  function familyCount(prefix) {
    // `organizer.rename.` means "everything under organizer.rename".
    var node = valueAt(prefix.replace(/\.$/, ''));
    if (!node || typeof node !== 'object') return null;
    var n = Array.isArray(node) ? node.length : Object.keys(node).length;
    return n ? n + (n === 1 ? ' item saved' : ' items saved') : null;
  }

  function renderOverviews(registry) {
    var rows = (registry && registry.settings) || [];
    var hosts = document.querySelectorAll('.s-overview');
    for (var h = 0; h < hosts.length; h++) {
      var host = hosts[h];
      var want = (host.getAttribute('data-section') || '').split(',');
      var mine = rows.filter(function (r) {
        return want.indexOf(r.section) !== -1;
      });
      if (!mine.length) { host.innerHTML = ''; continue; }
      var html = '<div class="s-ov-title">What is saved</div>';
      mine.forEach(function (r) {
        var isFamily = !r.key && r.key_prefix;
        var shown = isFamily ? familyCount(r.key_prefix) : describe(valueAt(r.key));
        var where = (r.home && r.home !== 'settings') ? WHERE[r.home] : null;
        html += '<div class="s-ov-row">'
          + '<span class="s-ov-label">' + WD.esc(r.label || r.key || r.key_prefix) + '</span>'
          + (shown === null
              ? '<span class="s-ov-val is-empty">Not set</span>'
              : '<span class="s-ov-val">' + WD.esc(shown) + '</span>')
          + (where
              ? '<span class="s-ov-where">Changed in ' + WD.esc(where) + '.</span>'
              : '')
          + '</div>';
      });
      host.innerHTML = html;
    }
  }

  function loadOverviews() {
    // A failure here must not take the page with it: the controls above are
    // the point and this is a summary of them.
    fetch('/assets/settings-registry.json')
      .then(function (r) { return r.json(); })
      .then(renderOverviews)
      .catch(function () {});
  }

  init();
})();
