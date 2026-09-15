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
      openHashSection();
    });
  }

  function openHashSection() {
    var hash = location.hash.replace('#', '');
    if (!hash) return;
    var sec = document.getElementById('sec-' + hash);
    if (sec) sec.open = true;
  }

  function populate() {
    var g = settings.global || {};
    var o = settings.organizer || {};
    var c = settings.cloud || {};

    document.getElementById('sOutputDir').value = g.output_dir || '';
    document.getElementById('sBackupKeep').value =
      String(g.backup_keep == null ? 3 : g.backup_keep);
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

    // Read by walls.js after a save. It had no control anywhere until now,
    // so the only way to turn it off was editing settings.json by hand.
    var w = settings.walls || {};
    document.getElementById('sWallsReveal').checked = w.reveal_source_after_save !== false;
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
        '<input type="text" value="' + esc(name) + '" onchange="SP._updateSf(' + i + ', this.value)">' +
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
        '<label>Folder name<input type="text" class="cd-name" value="' + esc(c.name || '') + '"></label>' +
        '<label>Extensions<input type="text" class="cd-exts" value="' + esc((c.exts || []).join(', ')) + '"></label>' +
        '<label>PDF keywords<input type="text" class="cd-pdfkw" value="' + esc((c.pdf_keywords || []).join(', ')) + '"></label>' +
        '<label>JSON keywords<input type="text" class="cd-jsonkw" value="' + esc((c.json_keywords || []).join(', ')) + '"></label>' +
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

  SP.pickFolder = function () {
    API('cloud/pick_folder', {}).then(function (r) {
      if (r.path) document.getElementById('sOutputDir').value = r.path;
    });
  };

  /* Backups, with the number attached.

     "Delete backups" on its own tells nobody whether it is worth doing, so
     nothing is offered until the size is on screen. The button that removes
     them only appears once he has seen what they cost. */
  SP.scanBackups = function () {
    var out = document.getElementById('sBackupUsage');
    var purge = document.getElementById('sBackupPurgeBtn');
    out.hidden = false;
    out.textContent = 'Checking…';
    API('backups/scan', {}).then(function (r) {
      if (r.error) { out.textContent = r.error; return; }
      if (!r.count) {
        out.textContent = 'No backup copies found.';
        purge.hidden = true;
        return;
      }
      var where = r.roots && r.roots.length ? ' under ' + r.roots.join(', ') : '';
      out.innerHTML = '<b>' + r.count + '</b> backup cop' +
        (r.count === 1 ? 'y' : 'ies') + ' using <b>' + r.human + '</b>' +
        WD.esc(where) + '.' +
        (r.installCount ? ' ' + r.installCount + ' of those are previous ' +
          'installs kept for rolling an update back; those are only removed ' +
          'if you ask.' : '');
      purge.hidden = false;
    }).catch(function () { out.textContent = 'Could not check.'; });
  };

  SP.purgeBackups = function () {
    var keep = parseInt(document.getElementById('sBackupKeep').value, 10) || 0;
    var msg = keep
      ? 'Delete every backup copy except the newest ' + keep + ' of each project?'
      : 'Delete every backup copy?';
    if (!confirm(msg + '\n\nThe projects themselves are not touched.')) return;
    var out = document.getElementById('sBackupUsage');
    out.hidden = false;
    out.textContent = 'Cleaning up…';
    API('backups/purge', { keep: keep }).then(function (r) {
      if (r.error) { out.textContent = r.error; return; }
      out.innerHTML = 'Removed <b>' + r.count + '</b> cop' +
        (r.count === 1 ? 'y' : 'ies') + ', freeing <b>' + r.human + '</b>.';
      document.getElementById('sBackupPurgeBtn').hidden = true;
    }).catch(function () { out.textContent = 'Could not clean up.'; });
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

    var mergeRule = 'ask';
    var radios = document.querySelectorAll('input[name="mergeRule"]');
    for (var i = 0; i < radios.length; i++) {
      if (radios[i].checked) { mergeRule = radios[i].value; break; }
    }

    var patch = {
      global: {
        output_dir: document.getElementById('sOutputDir').value,
        backup_keep: parseInt(document.getElementById('sBackupKeep').value, 10) || 0,
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
        live_interval_ms: parseInt(document.getElementById('sLiveMs').value, 10) || 30000
      },
      walls: {
        reveal_source_after_save: document.getElementById('sWallsReveal').checked
      }
    };

    API('settings/update', { patch: patch }).then(function (r) {
      if (r.ok) {
        settings = r.settings;
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

  init();
})();
