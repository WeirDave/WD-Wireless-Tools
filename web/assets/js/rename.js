/* WD Squirrel — Rename (standalone page JS) */

let _renameState = { root: '', tab: 'folders', items: [], csvLoaded: false, tokens: [], csvHeaders: [], csvRows: [], csvText: '' };
let _renamePreviewTimer = null;

function renameApi(action, body) {
  return fetch('/api/rename/' + action, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
    body: JSON.stringify(body || {}),
  }).then(r => r.json());
}

function closeModal(id) {
  document.getElementById(id).classList.remove('active');
}

// ── Initialization ──

async function initRename() {
  const settings = await fetch('/api/settings/get', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
    body: '{}',
  }).then(r => r.json());
  const rnSettings = (settings.ok && settings.settings && settings.settings.rename) || {};
  document.getElementById('rnFolderFormat').value = rnSettings.folder_format || '';
  document.getElementById('rnFileFormat').value = rnSettings.file_format || '';

  const rn = rnSettings.file_rules || {};
  document.getElementById('brCase').value = rn.case || '';
  document.getElementById('brSeparator').value = rn.separator || '';
  document.getElementById('brStripPrefix').value = rn.strip_prefix || '';
  document.getElementById('brStripSuffix').value = rn.strip_suffix || '';
  document.getElementById('brRegexFrom').value = rn.regex_from || '';
  document.getElementById('brRegexTo').value = rn.regex_to || '';
  document.getElementById('brPrefix').value = rn.prefix || '';
  document.getElementById('brSuffix').value = rn.suffix || '';

  const dir = await renameApi('get_directory');
  _renameState.csvLoaded = !!dir.loaded;
  if (dir.loaded) {
    const status = document.getElementById('renameCsvStatus');
    status.textContent = 'CSV loaded: ' + (dir.site_count || 0) + ' sites';
    status.hidden = false;
  }

  const tokR = await renameApi('get_tokens');
  _renameState.tokens = tokR.tokens || [];
  _renderTokenBars();
  _updateRenameExample();

  const savedRoot = localStorage.getItem('wd-rename-root')
    || localStorage.getItem('wd-project-directory')
    || (await renameApi('get_default_root')).path;
  if (savedRoot) {
    _renameState.root = savedRoot;
    localStorage.setItem('wd-rename-root', savedRoot);
    const el = document.getElementById('renameRootLabel');
    el.textContent = savedRoot;
    el.title = savedRoot;
    updateRenamePreview();
  }
}

document.addEventListener('DOMContentLoaded', initRename);

// ── Token bars ──

function _renderTokenBars() {
  const tokens = _renameState.tokens;
  ['rnFolderTokenBar', 'rnFileTokenBar'].forEach(barId => {
    const bar = document.getElementById(barId);
    if (!tokens.length) {
      bar.innerHTML = '<span class="sr-hint">No tokens available — load a CSV or fill in manually</span>';
      return;
    }
    const inputId = barId === 'rnFolderTokenBar' ? 'rnFolderFormat' : 'rnFileFormat';
    bar.innerHTML = '<span class="sr-hint">Insert:</span> ' +
      tokens.map(t => '<button class="sr-token-btn" onclick="_renameInsertFormatToken(\'' + inputId + '\',\'' + esc(t.key) + '\')">{' + esc(t.key) + '}</button>').join(' ');
  });
}

function _renameInsertFormatToken(inputId, key) {
  const el = document.getElementById(inputId);
  const token = '{' + key + '}';
  const start = el.selectionStart ?? el.value.length;
  const end = el.selectionEnd ?? el.value.length;
  el.value = el.value.slice(0, start) + token + el.value.slice(end);
  el.focus();
  el.selectionStart = el.selectionEnd = start + token.length;
  updateRenamePreview();
}

function _renameInsertToken(fieldId) {
  const el = document.getElementById(fieldId);
  const token = '{folder}';
  const start = el.selectionStart ?? el.value.length;
  const end = el.selectionEnd ?? el.value.length;
  el.value = el.value.slice(0, start) + token + el.value.slice(end);
  el.focus();
  el.selectionStart = el.selectionEnd = start + token.length;
  updateRenamePreview();
  _updateRenameExample();
}

// ── Tabs ──

function switchRenameTab(tab) {
  _renameState.tab = tab;
  document.querySelectorAll('#renameTabs .sr-tab').forEach(el => {
    el.classList.toggle('active', el.getAttribute('data-tab') === tab);
  });
  document.getElementById('renameTabFolders').hidden = tab !== 'folders';
  document.getElementById('renameTabFiles').hidden = tab !== 'files';
  document.getElementById('renameTabRules').hidden = tab !== 'rules';
  _renderManualFields();
  updateRenamePreview();
}

function _renderManualFields() {
  const wrap = document.getElementById('rnFolderManualFields');
  if (_renameState.tab !== 'folders' || _renameState.csvLoaded) {
    wrap.hidden = true;
    return;
  }
  const fmt = document.getElementById('rnFolderFormat').value;
  const re = /\{(\w+)\}/g;
  const tokens = [];
  const seen = new Set();
  let m;
  while ((m = re.exec(fmt))) {
    const k = m[1];
    if (!seen.has(k) && k !== 'date' && k !== 'folder') {
      seen.add(k);
      tokens.push(k);
    }
  }
  if (!tokens.length) { wrap.hidden = true; return; }
  wrap.hidden = false;
  wrap.innerHTML = '<div class="hint mb-8">No CSV loaded — fill in token values manually:</div>' +
    tokens.map(t =>
      '<div class="org-token-row"><label class="org-token-label">{' + esc(t) + '}</label>' +
      '<input type="text" class="org-folder-input rn-manual-input" data-token="' + esc(t) + '" oninput="updateRenamePreview()" placeholder="' + esc(t) + '"></div>'
    ).join('');
}

function _getManualValues() {
  const vals = {};
  document.querySelectorAll('.rn-manual-input').forEach(el => {
    vals[el.dataset.token] = el.value.trim();
  });
  return vals;
}

function _getRuleValues() {
  return {
    case: document.getElementById('brCase').value,
    separator: document.getElementById('brSeparator').value,
    strip_prefix: document.getElementById('brStripPrefix').value.trim(),
    strip_suffix: document.getElementById('brStripSuffix').value.trim(),
    regex_from: document.getElementById('brRegexFrom').value.trim(),
    regex_to: document.getElementById('brRegexTo').value,
    prefix: document.getElementById('brPrefix').value,
    suffix: document.getElementById('brSuffix').value,
  };
}

const _BR_SEPARATOR_CHARS = { underscore: '_', hyphen: '-', space: ' ', spaced_hyphen: ' - ' };

function _updateRenameExample() {
  const el = document.getElementById('brRenameExample');
  if (!el) return;
  const folder = 'Springfield CA';
  let stem = 'photo';
  const sep = _BR_SEPARATOR_CHARS[document.getElementById('brSeparator').value];
  if (sep !== undefined) stem = stem.replace(/[\s_-]+/g, sep);
  const c = document.getElementById('brCase').value;
  if (c === 'lower') stem = stem.toLowerCase();
  else if (c === 'upper') stem = stem.toUpperCase();
  else if (c === 'title') stem = stem.replace(/[A-Za-z]+/g, w => w[0].toUpperCase() + w.slice(1));
  else if (c === 'sentence') {
    stem = stem.toLowerCase();
    const m = stem.match(/[a-z]/);
    if (m) stem = stem.slice(0, m.index) + stem[m.index].toUpperCase() + stem.slice(m.index + 1);
  }
  const prefix = document.getElementById('brPrefix').value.replaceAll('{folder}', folder);
  const suffix = document.getElementById('brSuffix').value.replaceAll('{folder}', folder);
  el.textContent = prefix + stem + suffix + '.jpg';
}

// ── Folder picker ──

async function pickRenameRoot() {
  const r = await renameApi('pick_folder');
  if (!r.path) return;
  _renameState.root = r.path;
  localStorage.setItem('wd-rename-root', r.path);
  const el = document.getElementById('renameRootLabel');
  el.textContent = r.path;
  el.title = r.path;

  if (_renameState.tab === 'rules') {
    const style = await renameApi('detect_rename_style', { root: r.path });
    if (style.ok && style.separator) {
      document.getElementById('brSeparator').value = style.separator;
      _updateRenameExample();
    }
  }
  await updateRenamePreview();
}

// ── Preview ──

function updateRenamePreview() {
  clearTimeout(_renamePreviewTimer);
  return new Promise(resolve => {
    _renamePreviewTimer = setTimeout(async () => {
      await _runRenamePreview();
      resolve();
    }, 300);
  });
}

async function _runRenamePreview() {
  if (!_renameState.root) return;
  const list = document.getElementById('renamePreviewList');
  list.innerHTML = '<div class="org-loading"><div class="big-spin"></div><div class="org-loading-msg">Scanning…</div></div>';
  const tab = _renameState.tab;
  let r;

  if (tab === 'folders') {
    const fmt = document.getElementById('rnFolderFormat').value.trim();
    if (!fmt) {
      list.innerHTML = '<div class="org-extract-empty">Type a format string above using tokens like <b>{site_code} - {site_name}</b>, then the preview appears here.</div>';
      document.getElementById('renamePreviewCount').textContent = '';
      document.getElementById('renameApplyBtn').disabled = true;
      return;
    }
    const body = { root: _renameState.root, format: fmt };
    if (!_renameState.csvLoaded) {
      body.manual_values = _getManualValues();
    }
    r = await renameApi('preview_folder_rename', body);
  } else if (tab === 'files') {
    const fmt = document.getElementById('rnFileFormat').value.trim();
    if (!fmt) {
      list.innerHTML = '<div class="org-extract-empty">Type a format string above using tokens like <b>{site_code} - {original}</b>, then the preview appears here.</div>';
      document.getElementById('renamePreviewCount').textContent = '';
      document.getElementById('renameApplyBtn').disabled = true;
      return;
    }
    r = await renameApi('preview_file_rename', {
      root: _renameState.root,
      format: fmt,
    });
  } else {
    r = await renameApi('preview_bulk_rename', {
      root: _renameState.root,
      rules: _getRuleValues(),
    });
  }

  if (!r.ok && r.error) {
    list.innerHTML = '<div class="org-extract-empty">' + esc(r.error) + '</div>';
    document.getElementById('renamePreviewCount').textContent = '';
    document.getElementById('renameApplyBtn').disabled = true;
    return;
  }

  if (tab === 'rules') {
    _renameState.items = r.items || [];
    _renderRulesPreview();
  } else {
    _renameState.items = r.renames || [];
    _renderTokenPreview(tab);
  }
}

function _renderRulesPreview() {
  const items = _renameState.items;
  const list = document.getElementById('renamePreviewList');
  const countEl = document.getElementById('renamePreviewCount');
  countEl.textContent = items.length ? '(' + items.length + ')' : '';
  document.getElementById('renameApplyBtn').disabled = items.length === 0;
  if (!items.length) {
    list.innerHTML = '<div class="org-extract-empty">No files change with the current rules.</div>';
    return;
  }
  list.innerHTML = items.map(it =>
    '<div class="org-rename-row">' +
      '<span class="org-rename-site">' + esc(it.site) + '</span>' +
      '<span class="org-rename-old">' + esc(it.old_name) + '</span>' +
      '<span class="org-rename-arrow">&#8594;</span>' +
      '<span class="org-rename-new">' + esc(it.new_name) + '</span>' +
    '</div>'
  ).join('');
}

function _renderTokenPreview(tab) {
  const items = _renameState.items;
  const list = document.getElementById('renamePreviewList');
  const countEl = document.getElementById('renamePreviewCount');
  const renameCount = items.filter(x => x.status === 'rename').length;
  const correctCount = items.filter(x => x.status === 'already_correct').length;
  const unmatchedCount = items.filter(x => x.status === 'unmatched').length;
  const collisionCount = items.filter(x => x.status === 'collision').length;
  const parts = [];
  if (renameCount) parts.push(renameCount + ' to rename');
  if (correctCount) parts.push(correctCount + ' already correct');
  if (unmatchedCount) parts.push(unmatchedCount + ' unmatched');
  if (collisionCount) parts.push(collisionCount + ' collision' + (collisionCount !== 1 ? 's' : ''));
  countEl.textContent = parts.length ? '(' + parts.join(', ') + ')' : '';
  document.getElementById('renameApplyBtn').disabled = renameCount === 0;

  if (!items.length) {
    list.innerHTML = '<div class="org-extract-empty">No items found.</div>';
    return;
  }
  list.innerHTML = items.map(it => {
    const statusClass = 'rn-st-' + (it.status || 'unmatched');
    const current = tab === 'files' && it.folder
      ? esc(it.folder) + '/' + esc(it.current)
      : esc(it.current);
    return '<div class="org-rename-row ' + statusClass + '">' +
      '<span class="org-rename-old">' + current + '</span>' +
      '<span class="org-rename-arrow">&#8594;</span>' +
      '<span class="org-rename-new">' + (it.new_name ? esc(it.new_name) : '—') + '</span>' +
      (it.warnings && it.warnings.length ? '<span class="org-rename-warn">' + esc(it.warnings.join('; ')) + '</span>' : '') +
    '</div>';
  }).join('');
}

// ── Execute ──

async function doRename() {
  const tab = _renameState.tab;
  const btn = document.getElementById('renameApplyBtn');
  btn.disabled = true;
  const originalLabel = btn.textContent;
  btn.textContent = 'Renaming…';
  let r;

  if (tab === 'rules') {
    const rn = _getRuleValues();
    await fetch('/api/settings/set', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
      body: JSON.stringify({ settings: { rename: { file_rules: rn } } }),
    });
    r = await renameApi('execute_bulk_rename', { items: _renameState.items });
  } else {
    const renames = _renameState.items.filter(x => x.status === 'rename');
    if (!renames.length) { btn.textContent = originalLabel; btn.disabled = false; return; }
    const action = tab === 'folders' ? 'execute_folder_rename' : 'execute_file_rename';
    r = await renameApi(action, { root: _renameState.root, renames });
  }

  btn.textContent = originalLabel;
  if (!r.ok) { toast(r.error, 'error'); btn.disabled = false; return; }

  const parts = ['Renamed ' + r.renamed + ' item' + (r.renamed !== 1 ? 's' : '')];
  if (r.skipped) parts.push(r.skipped + ' skipped');
  if (r.errors && r.errors.length) parts.push(r.errors.length + ' error' + (r.errors.length !== 1 ? 's' : ''));
  toast(parts.join(' · '));
  document.getElementById('renameUndoBtn').hidden = false;

  await _runRenamePreview();
}

// Bug 8 fix: map tab to correct undo type
async function renameUndo() {
  const typeMap = { folders: 'folders', files: 'files', rules: 'bulk' };
  const type = typeMap[_renameState.tab] || _renameState.tab;
  const r = await renameApi('undo_last', { type });
  if (r.error) { toast(r.error, 'error'); return; }
  toast('Reverted ' + (r.reverted || 0) + ' item' + ((r.reverted || 0) !== 1 ? 's' : ''));
  document.getElementById('renameUndoBtn').hidden = true;
  await _runRenamePreview();
}

// ── CSV sub-modal ──

function showRenameCsvModal() {
  document.getElementById('renameCsvPreview').hidden = true;
  document.getElementById('renameCsvLoadBtn').disabled = true;
  _renameState.csvText = '';
  _renameState.csvHeaders = [];
  _renameState.csvRows = [];
  document.getElementById('renameCsvModal').classList.add('active');

  const zone = document.getElementById('renameCsvDropZone');
  const input = document.getElementById('renameCsvFileInput');
  zone.onclick = () => input.click();
  input.onchange = () => { if (input.files.length) _handleRenameCsvFile(input.files[0]); };
  zone.ondragover = e => { e.preventDefault(); zone.classList.add('drag-over'); };
  zone.ondragleave = () => zone.classList.remove('drag-over');
  zone.ondrop = e => { e.preventDefault(); zone.classList.remove('drag-over'); if (e.dataTransfer.files.length) _handleRenameCsvFile(e.dataTransfer.files[0]); };
}

// Bug 6 fix: RFC 4180 CSV parser that handles quoted commas
function _parseCsvLine(line) {
  const fields = [];
  let i = 0;
  while (i <= line.length) {
    if (i === line.length) { fields.push(''); break; }
    if (line[i] === '"') {
      let val = '';
      i++;
      while (i < line.length) {
        if (line[i] === '"') {
          if (i + 1 < line.length && line[i + 1] === '"') {
            val += '"';
            i += 2;
          } else {
            i++;
            break;
          }
        } else {
          val += line[i];
          i++;
        }
      }
      fields.push(val);
      if (i < line.length && line[i] === ',') i++;
    } else {
      const next = line.indexOf(',', i);
      if (next === -1) {
        fields.push(line.slice(i));
        break;
      }
      fields.push(line.slice(i, next));
      i = next + 1;
    }
  }
  return fields;
}

function _handleRenameCsvFile(file) {
  const reader = new FileReader();
  reader.onload = e => {
    _renameState.csvText = e.target.result;
    const lines = _renameState.csvText.split(/\r?\n/).filter(l => l.trim());
    if (!lines.length) return;
    const headers = _parseCsvLine(lines[0]).map(h => h.trim());
    _renameState.csvHeaders = headers;
    _renameState.csvRows = [];
    for (let i = 1; i < lines.length; i++) {
      const vals = _parseCsvLine(lines[i]);
      const row = {};
      headers.forEach((h, j) => { row[h] = (vals[j] || '').trim(); });
      _renameState.csvRows.push(row);
    }
    _renderRenameCsvPreview();
  };
  reader.readAsText(file);
}

function _renderRenameCsvPreview() {
  const headers = _renameState.csvHeaders;
  const rows = _renameState.csvRows;
  const maxRows = Math.min(rows.length, 8);
  let html = '<table class="sr-table"><thead><tr>';
  headers.forEach(h => { html += '<th>' + esc(h) + '</th>'; });
  html += '</tr></thead><tbody>';
  for (let i = 0; i < maxRows; i++) {
    html += '<tr>';
    headers.forEach(h => { html += '<td>' + esc(rows[i][h] || '') + '</td>'; });
    html += '</tr>';
  }
  if (rows.length > 8) html += '<tr><td colspan="' + headers.length + '" class="table-ellipsis">… ' + (rows.length - 8) + ' more rows</td></tr>';
  html += '</tbody></table>';
  document.getElementById('renameCsvPreviewWrap').innerHTML = html;

  ['rnMapPrimary', 'rnMapAddress', 'rnMapDeprecated'].forEach(id => {
    const sel = document.getElementById(id);
    sel.innerHTML = id === 'rnMapPrimary' ? '' : '<option value="">(none)</option>';
    headers.forEach(h => { sel.innerHTML += '<option value="' + esc(h) + '">' + esc(h) + '</option>'; });
  });
  const lower = headers.map(h => h.toLowerCase());
  const addrIdx = lower.findIndex(h => h.includes('address'));
  if (addrIdx !== -1) document.getElementById('rnMapAddress').value = headers[addrIdx];
  const depIdx = lower.findIndex(h => h.includes('deprecated') || h.includes('old'));
  if (depIdx !== -1) document.getElementById('rnMapDeprecated').value = headers[depIdx];

  document.getElementById('renameCsvPreview').hidden = false;
  document.getElementById('renameCsvLoadBtn').disabled = false;
}

async function doLoadRenameCsv() {
  if (!_renameState.csvText) return;
  const columnMap = {
    primary: document.getElementById('rnMapPrimary').value,
    address: document.getElementById('rnMapAddress').value,
    deprecated: document.getElementById('rnMapDeprecated').value,
  };
  const r = await renameApi('load_directory', { csv_text: _renameState.csvText, column_map: columnMap });
  if (r.error) { toast(r.error, 'error'); return; }

  _renameState.csvLoaded = true;
  const status = document.getElementById('renameCsvStatus');
  status.textContent = 'CSV loaded: ' + (r.site_count || 0) + ' sites';
  status.hidden = false;

  const tokR = await renameApi('get_tokens');
  _renameState.tokens = tokR.tokens || [];
  _renderTokenBars();
  _renderManualFields();

  closeModal('renameCsvModal');
  toast('Loaded ' + r.site_count + ' sites with ' + ((r.tokens || []).length) + ' token columns');
  if (_renameState.root) updateRenamePreview();
}

// ── Gap Report ──

async function showRenameGapReport() {
  if (!_renameState.root) { toast('Select a folder first', 'error'); return; }
  document.getElementById('renameGapBody').innerHTML = '<div class="big-spin"></div>';
  document.getElementById('renameGapModal').classList.add('active');

  const r = await renameApi('gap_report', { root: _renameState.root });
  if (r.error) { document.getElementById('renameGapBody').innerHTML = '<p>' + esc(r.error) + '</p>'; return; }

  let html = '';
  html += '<h3>Has Project Data (' + r.has_data.length + ')</h3>';
  if (r.has_data.length) {
    html += '<ul>' + r.has_data.map(d => '<li><strong>' + esc(d.folder) + '</strong> — ' + d.file_count + ' files, ' + d.project_files.length + ' .esx</li>').join('') + '</ul>';
  } else html += '<p class="sr-hint">None</p>';

  html += '<h3>Empty Folders (' + r.empty.length + ')</h3>';
  if (r.empty.length) html += '<ul>' + r.empty.map(d => '<li>' + esc(d.folder) + '</li>').join('') + '</ul>';
  else html += '<p class="sr-hint">None</p>';

  html += '<h3>Sites Not Started (' + r.not_started.length + ')</h3>';
  if (r.not_started.length) html += '<ul>' + r.not_started.map(d => '<li>' + esc(d.site_id) + '</li>').join('') + '</ul>';
  else html += '<p class="sr-hint">None</p>';

  html += '<h3>Orphan Folders (' + r.orphans.length + ')</h3>';
  if (r.orphans.length) html += '<ul>' + r.orphans.map(d => '<li>' + esc(d.folder) + ' — ' + d.file_count + ' files</li>').join('') + '</ul>';
  else html += '<p class="sr-hint">None</p>';

  document.getElementById('renameGapBody').innerHTML = html;
}

// ── Profiles ──

async function showRenameProfiles() {
  document.getElementById('renameProfilesModal').classList.add('active');
  const r = await renameApi('list_profiles');
  const profiles = r.profiles || {};
  const keys = Object.keys(profiles);
  const list = document.getElementById('renameProfilesList');
  if (!keys.length) {
    list.innerHTML = '<p class="sr-hint">No saved profiles yet.</p>';
    return;
  }
  list.innerHTML = keys.map(name => {
    const p = profiles[name];
    return '<div class="sr-profile-item">' +
      '<div class="sr-profile-name">' + esc(name) + '</div>' +
      '<div class="sr-profile-detail">Folder: <code>' + esc(p.folder_format || '') + '</code> · File: <code>' + esc(p.file_format || '') + '</code></div>' +
      '<div class="sr-profile-actions">' +
        '<button class="btn btn-sm" onclick="applyRenameProfile(' + JSON.stringify(name).replace(/"/g, '&quot;') + ')">Apply</button>' +
        '<button class="btn btn-sm btn-danger" onclick="deleteRenameProfile(' + JSON.stringify(name).replace(/"/g, '&quot;') + ')">Delete</button>' +
      '</div></div>';
  }).join('');
}

async function doSaveRenameProfile() {
  const name = document.getElementById('renameProfileNameInput').value.trim();
  if (!name) { toast('Enter a profile name', 'error'); return; }
  await renameApi('save_profile', {
    name,
    folder_format: document.getElementById('rnFolderFormat').value,
    file_format: document.getElementById('rnFileFormat').value,
    separator: '',
    file_rules: _getRuleValues(),
  });
  document.getElementById('renameProfileNameInput').value = '';
  toast('Profile "' + name + '" saved');
  showRenameProfiles();
}

async function applyRenameProfile(name) {
  const r = await renameApi('list_profiles');
  const p = (r.profiles || {})[name];
  if (!p) return;
  document.getElementById('rnFolderFormat').value = p.folder_format || '';
  document.getElementById('rnFileFormat').value = p.file_format || '';
  if (p.file_rules) {
    document.getElementById('brStripPrefix').value = p.file_rules.strip_prefix || '';
    document.getElementById('brStripSuffix').value = p.file_rules.strip_suffix || '';
    document.getElementById('brRegexFrom').value = p.file_rules.regex_from || '';
    document.getElementById('brRegexTo').value = p.file_rules.regex_to || '';
    document.getElementById('brCase').value = p.file_rules.case || '';
    document.getElementById('brSeparator').value = p.file_rules.separator || '';
    document.getElementById('brPrefix').value = p.file_rules.prefix || '';
    document.getElementById('brSuffix').value = p.file_rules.suffix || '';
  }
  closeModal('renameProfilesModal');
  toast('Applied profile "' + name + '"');
  _renderManualFields();
  if (_renameState.root) updateRenamePreview();
}

async function deleteRenameProfile(name) {
  if (!confirm('Delete profile "' + name + '"?')) return;
  await renameApi('delete_profile', { name });
  showRenameProfiles();
}

// ── CSV Helper ──

function showRenameCsvHelper() {
  document.getElementById('csvHelperResult').hidden = true;
  document.getElementById('renameCsvHelperModal').classList.add('active');
}

async function doCsvHelperTemplate() {
  const fmt = document.getElementById('rnFolderFormat').value || document.getElementById('rnFileFormat').value;
  const r = await renameApi('generate_csv_template', { format: fmt });
  if (!r.ok) { toast(r.error || 'Failed', 'error'); return; }
  document.getElementById('csvHelperOutput').value = r.csv_text;
  document.getElementById('csvHelperResult').hidden = false;
}

async function doCsvHelperPrefill() {
  if (!_renameState.root) { toast('Select a folder first', 'error'); return; }
  const fmt = document.getElementById('rnFolderFormat').value || '';
  const r = await renameApi('prefill_from_folders', { root: _renameState.root, format: fmt });
  if (!r.ok && r.error) { toast(r.error, 'error'); return; }
  document.getElementById('csvHelperOutput').value = r.csv_text;
  document.getElementById('csvHelperResult').hidden = false;
  toast('Generated CSV with ' + r.folder_count + ' folder' + (r.folder_count !== 1 ? 's' : ''));
}

function copyCsvHelper() {
  const el = document.getElementById('csvHelperOutput');
  navigator.clipboard.writeText(el.value).then(() => toast('Copied to clipboard'));
}
