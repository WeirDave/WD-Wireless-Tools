(function () {
  'use strict';

  var SR = {};
  var _root = '';
  var _activeTab = 'folders';
  var _csvText = '';
  var _csvHeaders = [];
  var _csvRows = [];
  var _directory = null;

  async function api(action, body) {
    var resp = await fetch('/api/site-rename/' + action, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
      body: JSON.stringify(body || {}),
    });
    return resp.json();
  }

  SR.pickFolder = async function () {
    var r = await api('pick_folder');
    if (r.path) {
      _root = r.path;
      SR._enterWorkspace();
    }
  };

  SR._enterWorkspace = function () {
    document.getElementById('pickScreen').hidden = true;
    document.getElementById('workspace').hidden = false;
    document.getElementById('folderLabel').textContent = _root;
    SR._refreshTokenBar();
    document.getElementById('previewArea').hidden = true;
  };

  SR._refreshTokenBar = function () {
    var bar = document.getElementById('tokenBar');
    if (!_directory || !_directory.tokens || !_directory.tokens.length) {
      bar.innerHTML = '<span class="sr-hint">Load a CSV to see available tokens</span>';
      return;
    }
    var html = '<span class="sr-hint">Click to insert:</span> ';
    _directory.tokens.forEach(function (t) {
      html += '<button class="sr-token-btn" onclick="SR.insertToken(\'' +
        WD.esc(t) + '\')">{' + WD.esc(t) + '}</button> ';
    });
    bar.innerHTML = html;
  };

  SR.insertToken = function (token) {
    var input = document.getElementById('formatInput');
    var start = input.selectionStart;
    var end = input.selectionEnd;
    var val = input.value;
    var insertion = '{' + token + '}';
    input.value = val.substring(0, start) + insertion + val.substring(end);
    input.selectionStart = input.selectionEnd = start + insertion.length;
    input.focus();
  };

  SR.switchTab = function (tab) {
    _activeTab = tab;
    document.querySelectorAll('.sr-tab').forEach(function (el) {
      el.classList.toggle('active', el.getAttribute('data-tab') === tab);
    });
    document.getElementById('previewArea').hidden = true;
  };

  SR.preview = async function () {
    var fmt = document.getElementById('formatInput').value.trim();
    var sep = document.getElementById('sepInput').value;
    if (!fmt) { alert('Enter a format string first.'); return; }
    if (!_root) { alert('Select a projects folder first.'); return; }

    var action = _activeTab === 'folders' ? 'preview_folder_rename' : 'preview_file_rename';
    var r = await api(action, { root: _root, format: fmt, separator: sep });
    if (r.error) { alert(r.error); return; }

    var tbody = document.getElementById('previewBody');
    var rows = r.renames || [];
    var html = '';
    rows.forEach(function (item) {
      var statusClass = 'sr-st-' + (item.status || 'unmatched');
      var statusLabel = { rename: 'Rename', already_correct: 'OK', unmatched: 'No match' }[item.status] || item.status;
      var warns = (item.warnings || []).join('; ');
      var current = _activeTab === 'files' && item.folder
        ? WD.esc(item.folder) + '/' + WD.esc(item.current)
        : WD.esc(item.current);
      html += '<tr class="' + statusClass + '">'
        + '<td>' + statusLabel + '</td>'
        + '<td>' + current + '</td>'
        + '<td>' + (item.new_name ? WD.esc(item.new_name) : '—') + '</td>'
        + '<td>' + (warns || '') + '</td>'
        + '</tr>';
    });
    tbody.innerHTML = html;

    var renameCount = r.rename_count || 0;
    var stats = renameCount + ' to rename';
    if (r.correct_count) stats += ', ' + r.correct_count + ' already correct';
    if (r.unmatched_count) stats += ', ' + r.unmatched_count + ' unmatched';
    document.getElementById('previewStats').textContent = stats;
    document.getElementById('previewTitle').textContent =
      (_activeTab === 'folders' ? 'Folder' : 'File') + ' Rename Preview';
    document.getElementById('executeBtn').disabled = renameCount === 0;
    document.getElementById('previewArea').hidden = false;
  };

  SR.execute = async function () {
    var tbody = document.getElementById('previewBody');
    var trs = tbody.querySelectorAll('tr.sr-st-rename');
    if (!trs.length) return;

    if (!confirm('Rename ' + trs.length + ' items? This can be undone.')) return;

    var renames = [];
    trs.forEach(function (tr) {
      var cells = tr.querySelectorAll('td');
      var currentCell = cells[1].textContent;
      var newName = cells[2].textContent;
      if (_activeTab === 'files') {
        var parts = currentCell.split('/');
        renames.push({ folder: parts[0], current: parts.slice(1).join('/'), new_name: newName });
      } else {
        renames.push({ current: currentCell, new_name: newName });
      }
    });

    var action = _activeTab === 'folders' ? 'execute_folder_rename' : 'execute_file_rename';
    var r = await api(action, { root: _root, renames: renames });
    if (r.error) { alert(r.error); return; }

    var msg = 'Renamed ' + (r.renamed || 0) + ' items.';
    if (r.errors && r.errors.length) msg += '\n\nErrors:\n' + r.errors.join('\n');
    alert(msg);

    document.getElementById('undoBtn').hidden = false;
    SR.preview();
  };

  SR.undo = async function () {
    var type = _activeTab === 'folders' ? 'folders' : 'files';
    if (!confirm('Undo the last ' + type + ' rename operation?')) return;
    var r = await api('undo_last', { type: type });
    if (r.error) { alert(r.error); return; }
    alert('Reverted ' + (r.reverted || 0) + ' items.');
    document.getElementById('undoBtn').hidden = true;
    SR.preview();
  };

  // ── CSV Modal ──

  SR.showLoadCsv = function () {
    document.getElementById('csvModal').hidden = false;
    document.getElementById('csvPreview').hidden = true;
    document.getElementById('csvLoadBtn').disabled = true;
    _csvText = '';
    _csvHeaders = [];
    _csvRows = [];
  };

  SR.closeCsvModal = function () {
    document.getElementById('csvModal').hidden = true;
  };

  function parseCsv(text) {
    var lines = text.split(/\r?\n/).filter(function (l) { return l.trim(); });
    if (!lines.length) return { headers: [], rows: [] };
    var headers = lines[0].split(',').map(function (h) { return h.trim().replace(/^"|"$/g, ''); });
    var rows = [];
    for (var i = 1; i < lines.length; i++) {
      var vals = lines[i].split(',');
      var row = {};
      headers.forEach(function (h, j) {
        row[h] = (vals[j] || '').trim().replace(/^"|"$/g, '');
      });
      rows.push(row);
    }
    return { headers: headers, rows: rows };
  }

  function renderCsvPreview() {
    var wrap = document.getElementById('csvPreviewWrap');
    var maxRows = Math.min(_csvRows.length, 10);
    var html = '<table class="sr-table"><thead><tr>';
    _csvHeaders.forEach(function (h) { html += '<th>' + WD.esc(h) + '</th>'; });
    html += '</tr></thead><tbody>';
    for (var i = 0; i < maxRows; i++) {
      html += '<tr>';
      _csvHeaders.forEach(function (h) {
        html += '<td>' + WD.esc(_csvRows[i][h] || '') + '</td>';
      });
      html += '</tr>';
    }
    if (_csvRows.length > 10) {
      html += '<tr><td colspan="' + _csvHeaders.length + '" style="text-align:center;opacity:.6">… ' +
        (_csvRows.length - 10) + ' more rows</td></tr>';
    }
    html += '</tbody></table>';
    wrap.innerHTML = html;

    var mapPrimary = document.getElementById('mapPrimary');
    var mapAddress = document.getElementById('mapAddress');
    var mapDeprecated = document.getElementById('mapDeprecated');
    mapPrimary.innerHTML = '';
    mapAddress.innerHTML = '<option value="">(none)</option>';
    mapDeprecated.innerHTML = '<option value="">(none)</option>';
    _csvHeaders.forEach(function (h) {
      mapPrimary.innerHTML += '<option value="' + WD.esc(h) + '">' + WD.esc(h) + '</option>';
      mapAddress.innerHTML += '<option value="' + WD.esc(h) + '">' + WD.esc(h) + '</option>';
      mapDeprecated.innerHTML += '<option value="' + WD.esc(h) + '">' + WD.esc(h) + '</option>';
    });

    var lower = _csvHeaders.map(function (h) { return h.toLowerCase(); });
    var addrIdx = lower.findIndex(function (h) { return h.indexOf('address') !== -1; });
    if (addrIdx !== -1) mapAddress.value = _csvHeaders[addrIdx];
    var depIdx = lower.findIndex(function (h) { return h.indexOf('deprecated') !== -1 || h.indexOf('old') !== -1; });
    if (depIdx !== -1) mapDeprecated.value = _csvHeaders[depIdx];

    document.getElementById('csvPreview').hidden = false;
    document.getElementById('csvLoadBtn').disabled = false;
  }

  function handleCsvFile(file) {
    var reader = new FileReader();
    reader.onload = function (e) {
      _csvText = e.target.result;
      var parsed = parseCsv(_csvText);
      _csvHeaders = parsed.headers;
      _csvRows = parsed.rows;
      renderCsvPreview();
    };
    reader.readAsText(file);
  }

  SR.loadCsv = async function () {
    if (!_csvText) return;
    var columnMap = {
      primary: document.getElementById('mapPrimary').value,
      address: document.getElementById('mapAddress').value,
      deprecated: document.getElementById('mapDeprecated').value,
    };
    var r = await api('load_directory', { csv_text: _csvText, column_map: columnMap });
    if (r.error) { alert(r.error); return; }
    _directory = r;
    SR._refreshTokenBar();
    SR.closeCsvModal();
    var status = document.getElementById('pickStatus');
    if (status) {
      status.textContent = 'Directory loaded: ' + (r.site_count || 0) + ' sites, ' +
        (r.tokens || []).length + ' tokens';
      status.hidden = false;
    }
    if (r.tokens && r.tokens.length && !document.getElementById('formatInput').value) {
      document.getElementById('formatInput').value = '{' + r.tokens[0] + '}';
    }
  };

  // ── Gap Report Modal ──

  SR.showGapReport = async function () {
    if (!_root) { alert('Select a projects folder first.'); return; }
    document.getElementById('gapModal').hidden = false;
    document.getElementById('gapBody').innerHTML = '<div class="big-spin"></div>';

    var r = await api('gap_report', { root: _root });
    if (r.error) { document.getElementById('gapBody').innerHTML = '<p>' + WD.esc(r.error) + '</p>'; return; }

    var html = '';
    html += '<h3>Has Project Data (' + r.has_data.length + ')</h3>';
    if (r.has_data.length) {
      html += '<ul>';
      r.has_data.forEach(function (d) {
        html += '<li><strong>' + WD.esc(d.folder) + '</strong> — ' + d.file_count + ' files, ' +
          d.project_files.length + ' .esx</li>';
      });
      html += '</ul>';
    } else {
      html += '<p class="sr-hint">None</p>';
    }

    html += '<h3>Empty Folders (' + r.empty.length + ')</h3>';
    if (r.empty.length) {
      html += '<ul>';
      r.empty.forEach(function (d) { html += '<li>' + WD.esc(d.folder) + '</li>'; });
      html += '</ul>';
    } else {
      html += '<p class="sr-hint">None</p>';
    }

    html += '<h3>Sites Not Started (' + r.not_started.length + ')</h3>';
    if (r.not_started.length) {
      html += '<ul>';
      r.not_started.forEach(function (d) { html += '<li>' + WD.esc(d.site_id) + '</li>'; });
      html += '</ul>';
    } else {
      html += '<p class="sr-hint">None</p>';
    }

    html += '<h3>Orphan Folders (' + r.orphans.length + ')</h3>';
    if (r.orphans.length) {
      html += '<ul>';
      r.orphans.forEach(function (d) {
        html += '<li>' + WD.esc(d.folder) + ' — ' + d.file_count + ' files</li>';
      });
      html += '</ul>';
    } else {
      html += '<p class="sr-hint">None</p>';
    }

    document.getElementById('gapBody').innerHTML = html;
  };

  SR.closeGapModal = function () {
    document.getElementById('gapModal').hidden = true;
  };

  // ── Profiles Modal ──

  SR.showProfiles = async function () {
    document.getElementById('profilesModal').hidden = false;
    var r = await api('list_profiles');
    var list = document.getElementById('profilesList');
    var profiles = r.profiles || {};
    var keys = Object.keys(profiles);
    if (!keys.length) {
      list.innerHTML = '<p class="sr-hint">No saved profiles yet.</p>';
      return;
    }
    var html = '';
    keys.forEach(function (name) {
      var p = profiles[name];
      html += '<div class="sr-profile-item">'
        + '<div class="sr-profile-name">' + WD.esc(name) + '</div>'
        + '<div class="sr-profile-detail">Folder: <code>' + WD.esc(p.folder_format || '') + '</code>'
        + ' &nbsp; File: <code>' + WD.esc(p.file_format || '') + '</code>'
        + ' &nbsp; Sep: <code>' + WD.esc(p.separator || '') + '</code></div>'
        + '<div class="sr-profile-actions">'
        + '<button class="btn btn-sm" onclick="SR.applyProfile(' + JSON.stringify(name).replace(/"/g, '&quot;') + ')">Apply</button>'
        + '<button class="btn btn-sm btn-danger" onclick="SR.deleteProfile(' + JSON.stringify(name).replace(/"/g, '&quot;') + ')">Delete</button>'
        + '</div></div>';
    });
    list.innerHTML = html;
  };

  SR.closeProfilesModal = function () {
    document.getElementById('profilesModal').hidden = true;
  };

  SR.saveProfile = async function () {
    var name = document.getElementById('profileNameInput').value.trim();
    if (!name) { alert('Enter a profile name.'); return; }
    var fmt = document.getElementById('formatInput').value.trim();
    var sep = document.getElementById('sepInput').value;
    await api('save_profile', { name: name, folder_format: fmt, file_format: fmt, separator: sep });
    document.getElementById('profileNameInput').value = '';
    SR.showProfiles();
  };

  SR.deleteProfile = async function (name) {
    if (!confirm('Delete profile "' + name + '"?')) return;
    await api('delete_profile', { name: name });
    SR.showProfiles();
  };

  SR.applyProfile = function (name) {
    api('list_profiles').then(function (r) {
      var p = (r.profiles || {})[name];
      if (!p) return;
      var fmt = _activeTab === 'folders' ? (p.folder_format || '') : (p.file_format || '');
      document.getElementById('formatInput').value = fmt;
      document.getElementById('sepInput').value = p.separator || ' - ';
      SR.closeProfilesModal();
    });
  };

  // ── Init ──

  function initDropZone() {
    var zone = document.getElementById('csvDropZone');
    var input = document.getElementById('csvFileInput');
    if (!zone || !input) return;
    zone.addEventListener('click', function () { input.click(); });
    input.addEventListener('change', function () {
      if (input.files.length) handleCsvFile(input.files[0]);
    });
    zone.addEventListener('dragover', function (e) { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', function () { zone.classList.remove('drag-over'); });
    zone.addEventListener('drop', function (e) {
      e.preventDefault();
      zone.classList.remove('drag-over');
      if (e.dataTransfer.files.length) handleCsvFile(e.dataTransfer.files[0]);
    });
  }

  async function init() {
    initDropZone();
    var r = await api('get_directory');
    if (r.loaded) {
      _directory = r;
      SR._refreshTokenBar();
      var status = document.getElementById('pickStatus');
      if (status) {
        status.textContent = 'Directory loaded: ' + (r.site_count || 0) + ' sites, ' +
          (r.tokens || []).length + ' tokens';
        status.hidden = false;
      }
    }

    var menuBtn = document.getElementById('menuBtn');
    var mainMenu = document.getElementById('mainMenu');
    if (menuBtn && mainMenu) {
      menuBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        mainMenu.classList.toggle('open');
      });
      document.addEventListener('click', function () { mainMenu.classList.remove('open'); });
    }
  }

  window.SR = SR;
  window.toggleTheme = WD.toggleTheme;
  init();
})();
