let scanData = null;
let currentRoot = null;
let undoAvailable = false;
let undoCount = 0;
let pendingGroupSuggestion = null;
let cachedConfig = null;
const PROJECT_DIR_STORAGE_KEY = 'wd-project-directory';
const ORG_ADVANCED_KEY = 'wd-organizer-advanced';

function advancedOn() { try { return localStorage.getItem(ORG_ADVANCED_KEY) === '1'; } catch (e) { return false; } }
function toggleAdvanced() {
  try { localStorage.setItem(ORG_ADVANCED_KEY, advancedOn() ? '0' : '1'); } catch (e) {}
  renderPreview();
}
function applyAdvancedUI() {
  const on = advancedOn();
  const btn = document.getElementById('advancedToggleBtn');
  if (btn) { btn.classList.toggle('active', on); btn.textContent = on ? '✓ Advanced' : 'Advanced'; }
  const label = document.getElementById('bulkDestLabel');
  const row = document.getElementById('bulkDestRow');
  const hint = document.getElementById('orgDestHint');
  if (label) label.hidden = !on;
  if (row) row.hidden = !on;
  if (hint) hint.hidden = !on;
}

const ORG_DETAILS_KEY = 'wd-organizer-details';

function detailsOn() { try { return localStorage.getItem(ORG_DETAILS_KEY) === '1'; } catch (e) { return false; } }
function toggleDetails() {
  try { localStorage.setItem(ORG_DETAILS_KEY, detailsOn() ? '0' : '1'); } catch (e) {}
  applyDetailsUI();
}
function applyDetailsUI() {
  const on = detailsOn();
  const btn = document.getElementById('detailsToggleBtn');
  if (btn) btn.textContent = on ? 'Hide File Details' : 'Show File Details';
  const toolbar = document.getElementById('orgDetailsToolbar');
  const list = document.getElementById('siteList');
  const hint = document.getElementById('orgDetailsHint');
  if (toolbar) toolbar.hidden = !on;
  if (list) list.hidden = !on;
  if (hint) hint.hidden = on;
}

function rememberProjectDirectory(path) {
  if (!path) return;
  try { localStorage.setItem(PROJECT_DIR_STORAGE_KEY, path); } catch (e) {}
}

async function restoreProjectDirectory() {



  showScreen('pickScreen');
  let path = '';
  try { path = localStorage.getItem(PROJECT_DIR_STORAGE_KEY) || ''; } catch (e) {}
  if (!path) return;
  const hint = document.getElementById('lastFolderHint');
  const pathEl = document.getElementById('lastFolderPath');
  if (hint && pathEl) {
    pathEl.textContent = path;
    hint.hidden = false;
  }
}

async function _restoreCurrentRootSilently() {
  if (currentRoot) return true;
  let path = '';
  try { path = localStorage.getItem(PROJECT_DIR_STORAGE_KEY) || ''; } catch (e) {}
  if (!path) return false;
  try {
    const r = await api('set_folder', { path });
    if (r && r.ok) { currentRoot = r.path; return true; }
  } catch (e) {}
  return false;
}

async function continueLastFolder() {
  let path = '';
  try { path = localStorage.getItem(PROJECT_DIR_STORAGE_KEY) || ''; } catch (e) {}
  if (!path) return;
  try {
    const r = await api('set_folder', { path });
    if (!r.ok) {
      try { localStorage.removeItem(PROJECT_DIR_STORAGE_KEY); } catch (e) {}
      const hint = document.getElementById('lastFolderHint');
      if (hint) hint.hidden = true;
      toast(r.error || 'That folder is no longer available', 'error');
      return;
    }
    currentRoot = r.path;
    await refreshUndoState();
    await doScan();
  } catch (e) {}
}

async function refreshConfig() {
  try {
    const r = await api('get_config');
    if (r.ok) cachedConfig = r.config;
  } catch (e) {}
}

async function api(action, body = {}) {
  const resp = await fetch('/api/organizer/' + action, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-WD-Wireless-Tools': '1',
    },
    body: JSON.stringify(body),
  });
  return resp.json();
}

function setUndoState(available, count) {
  undoAvailable = !!available;
  undoCount = count || 0;
  const menuBtn = document.getElementById('menuUndo');
  if (menuBtn) menuBtn.hidden = !undoAvailable;
}

async function refreshUndoState() {
  if (!currentRoot) { setUndoState(false, 0); return; }
  try {
    const r = await api('has_undo', { root: currentRoot });
    setUndoState(r.available, r.count);
  } catch (e) {
    setUndoState(false, 0);
  }
}

document.getElementById('menuBtn').addEventListener('click', (e) => {
  e.stopPropagation();
  document.getElementById('mainMenu').classList.toggle('open');
});
document.addEventListener('click', () => document.getElementById('mainMenu').classList.remove('open'));

function showScreen(id) {
  ['loadingScreen', 'pickScreen', 'previewScreen', 'execScreen', 'resultScreen'].forEach(s =>
    document.getElementById(s).hidden = s !== id
  );
}

async function pickFolder() {
  document.getElementById('mainMenu').classList.remove('open');
  const r = await api('pick_folder');
  if (!r.ok) { if (r.error !== 'No folder selected') toast(r.error, 'error'); return; }
  currentRoot = r.path;
  rememberProjectDirectory(currentRoot);
  await refreshUndoState();
  await doScan();
}

async function doScan() {
  document.getElementById('mainMenu').classList.remove('open');
  if (!currentRoot) { toast('Pick a folder first', 'error'); return; }
  showScreen('previewScreen');
  document.getElementById('rootPath').textContent = currentRoot;
  document.getElementById('siteList').innerHTML = '<div class="org-loading"><div class="big-spin"></div><div class="org-loading-msg">Scanning…</div></div>';
  document.getElementById('summaryBar').innerHTML = '';

  await refreshConfig();
  const r = await api('scan', { root: currentRoot });
  if (!r.ok) { toast(r.error, 'error'); return; }
  scanData = r;
  await maybeSuggestGrouping();
  renderPreview();
}

async function maybeSuggestGrouping() {
  pendingGroupSuggestion = null;
  if (!scanData || !scanData.sites || scanData.sites.length !== 1) return;
  const only = scanData.sites[0];
  if (!only.is_root) return;
  try {
    const r = await api('suggest_groups', { root: currentRoot });
    if (r.ok && r.candidates && r.candidates.length > 0) {
      pendingGroupSuggestion = r;
    }
  } catch (e) {

  }
}

function renderPreview() {
  _lastChecked = null;
  const d = scanData;
  const t = d.totals;
  const dests = destinationList(cachedConfig);
  const advanced = advancedOn();
  applyAdvancedUI();
  applyDetailsUI();

  const movingCount = dests.reduce((sum, dst) => sum + (t[dst.key] || 0), 0);
  const confirmText = document.getElementById('orgConfirmText');
  if (confirmText) {
    confirmText.innerHTML = d.site_count
      ? `Found <b>${d.site_count}</b> site folder${d.site_count !== 1 ? 's' : ''}. <b>${movingCount}</b> file${movingCount !== 1 ? 's' : ''} will move into ${dests.map(x => esc(x.name)).join(' / ')}. <b>${t.skipped}</b> will stay as-is.`
      : `No site folders with loose files found in this location.`;
  }
  const organizeBtn = document.querySelector('#orgConfirmCard .btn-primary');
  if (organizeBtn) organizeBtn.disabled = movingCount === 0;



  const bulkHost = document.getElementById('bulkDestRow');
  if (bulkHost) {
    bulkHost.innerHTML = advanced ? dests.map(dst => {
      const cls = destinationCssClass(dst.key);
      return `<button class="btn btn-sec btn-sm ${cls}" onclick="bulkSetDest('${escJsStr(dst.key)}')">${esc(dst.name)}</button>`;
    }).join('') : '';
  }

  let summaryHtml = `
    <div class="summary-chip chip-sites"><span class="num">${d.site_count}</span> site folders</div>
    <div class="summary-chip chip-moving"><span class="num">${movingCount}</span> moving</div>
    <div class="summary-chip chip-staying"><span class="num">${t.skipped}</span> staying</div>
  `;
  if (advanced) {
    const renameBits = renameActiveSummary(cachedConfig);
    const renameChip = renameBits.length
      ? `<div class="summary-chip chip-rename" title="Rename patterns active: ${renameBits.join(', ')} — see Settings"><span class="num">${renameBits.length}</span> rename rule${renameBits.length !== 1 ? 's' : ''}</div>`
      : '';
    const dupCount = (d.duplicates || []).length;
    const dupChip = dupCount
      ? `<div class="summary-chip chip-dupes" title="${dupCount} filename${dupCount !== 1 ? 's' : ''} appear in more than one site folder — click to review" onclick="document.getElementById('dupSection')?.scrollIntoView({behavior:'smooth'})"><span class="num">${dupCount}</span> duplicate${dupCount !== 1 ? 's' : ''}</div>`
      : '';
    const unrefCount = d.unreferenced_count || 0;
    const unrefChip = unrefCount
      ? `<div class="summary-chip chip-unref" title="${unrefCount} image${unrefCount !== 1 ? 's' : ''}/plan${unrefCount !== 1 ? 's' : ''} in a site's images/ or floorplans/ folder are not referenced by any .esx in that site — potentially safe to remove"><span class="num">${unrefCount}</span> unreferenced</div>`
      : '';
    const destChips = dests.map(dst => {
      const cls = destinationCssClass(dst.key).replace('dest-', 'chip-');
      return `<div class="summary-chip ${cls}"><span class="num">${t[dst.key] || 0}</span> → ${esc(dst.name)}</div>`;
    }).join('');
    summaryHtml += `${destChips}${dupChip}${unrefChip}${renameChip}`;
  }
  document.getElementById('summaryBar').innerHTML = summaryHtml;

  const suggestBanner = document.getElementById('orgSuggestBanner');
  if (suggestBanner) suggestBanner.innerHTML = renderSuggestBanner();

  if (d.sites.length === 0) {
    document.getElementById('siteList').innerHTML = '<div class="org-empty">No site folders with loose files found.</div>' + (advanced ? renderDupSection() : '');
    return;
  }

  let html = '';
  for (const site of d.sites) {
    const moveCount = site.moves.length;
    const stayCount = site.staying.length;
    html += `<div class="site-group" data-site="${escAttr(site.folder)}">`;
    html += `<div class="site-header" onclick="this.parentElement.classList.toggle('collapsed')">`;
    html += `<div><span class="site-name">${esc(site.folder)}</span>`;
    if (moveCount) html += `<span class="site-badge">${moveCount} move${moveCount !== 1 ? 's' : ''}</span>`;
    if (stayCount) html += `<span class="site-badge">${stayCount} staying</span>`;
    html += `</div><span class="site-chevron">▾</span></div>`;

    if (site.missing_subs.length > 0 || site.existing_subs.length > 0) {
      html += '<div class="new-subs">';
      const allSubs = [...(site.existing_subs || []), ...(site.missing_subs || [])];

      const canonicalOrder = subfolderDisplayOrder(cachedConfig);
      const ordered = canonicalOrder.filter(n => allSubs.includes(n))
        .concat(allSubs.filter(n => !canonicalOrder.includes(n)));
      for (const sf of ordered) {
        if (site.missing_subs.includes(sf)) html += `<span class="new-sub-badge">+ \\${esc(sf)}</span>`;
        else html += `<span class="new-sub-badge exists">\\${esc(sf)} ✓</span>`;
      }
      html += '</div>';
    }

    html += '<div class="site-body">';
    if (moveCount > 0) {
      html += '<table class="file-table"><thead><tr>';
      html += '<th class="chk"><input type="checkbox" checked onchange="toggleSite(this, \'' + escJsStr(site.folder) + '\')"></th>';
      html += '<th>File</th><th class="col-dest">Destination</th><th class="col-size org-size-th">Size</th>';
      html += '</tr></thead><tbody>';
      for (const m of site.moves) {
        const id = site.folder + '::' + m.name;
        const renamedBit = m.renamed_to ? ` <span class="renamed">(→ ${esc(m.renamed_to)})</span>` : '';
        let destCell;
        if (advanced) {
          destCell = `<select class="dest-select ${destinationCssClass(m.target)}" data-site="${escAttr(site.folder)}" data-file="${escAttr(m.name)}" data-original="${m.target}" onchange="onDestChange(this)">`
            + dests.map(dst => `<option value="${escAttr(dst.key)}"${dst.key === m.target ? ' selected' : ''}>${esc(dst.name)}</option>`).join('')
            + `</select>`;
        } else {
          const destName = (dests.find(x => x.key === m.target) || {}).name || m.target;
          destCell = `<span class="dest-label ${destinationCssClass(m.target)}">&#8594; ${esc(destName)}</span>`;
        }
        html += `<tr>`;
        html += `<td class="chk"><input type="checkbox" checked data-site="${escAttr(site.folder)}" data-file="${escAttr(m.name)}" data-id="${escAttr(id)}"></td>`;
        html += `<td><span class="file-ext">${esc(m.ext)}</span>${esc(m.name)}</td>`;
        html += `<td>${destCell}${renamedBit}</td>`;
        html += `<td class="org-size">${fmtSize(m.size)}</td>`;
        html += '</tr>';
      }
      html += '</tbody></table>';
    }

    if (stayCount > 0) {
      html += '<table class="file-table"><thead><tr><th colspan="3" class="org-staying-head">Staying in root</th></tr></thead><tbody>';
      for (const s of site.staying) {
        html += `<tr class="staying-row">`;
        html += `<td><span class="file-ext">${esc(s.ext)}</span>${esc(s.name)}${esxBadges(s)}</td>`;
        html += `<td><span class="staying-label ${s.reason === 'esx' ? 'staying-esx' : 'staying-unknown'}">${s.reason === 'esx' ? '.esx project' : 'unknown type'}</span></td>`;
        html += `<td class="org-size">${fmtSize(s.size)}</td>`;
        html += '</tr>';
      }
      html += '</tbody></table>';
    }
    const unref = advanced ? (site.unreferenced || []) : [];
    if (unref.length) {
      html += `<div class="org-unref-block">`;
      html += `<div class="org-unref-head">Unreferenced in <b>images/</b> and <b>floorplans/</b> <span class="org-unref-sub">(${unref.length} file${unref.length !== 1 ? 's' : ''} — name not found in any .esx's <code>imageName</code>. Advisory only.)</span></div>`;
      html += `<table class="file-table"><tbody>`;
      for (const u of unref) {
        const dot = u.name.lastIndexOf('.');
        const ext = dot > 0 ? u.name.slice(dot) : '';
        html += `<tr class="staying-row"><td>${ext ? `<span class="file-ext">${esc(ext)}</span>` : ''}${esc(u.name)}</td><td><span class="staying-label staying-unknown">${esc(u.folder)}/</span></td><td class="org-size">${esc(u.size_h)}</td></tr>`;
      }
      html += `</tbody></table></div>`;
    }
    html += '</div></div>';
  }
  if (advanced) html += renderDupSection();
  document.getElementById('siteList').innerHTML = html;
}

function renderDupSection() {
  const dupes = (scanData && scanData.duplicates) || [];
  if (!dupes.length) return '';
  const rows = dupes.slice(0, 100).map(g => {
    const locs = g.copies.map(c => `<code class="dup-loc">${esc(c.site)}/${esc(c.rel)}</code>`).join('<br>');
    return `<div class="org-dup-row">
      <div class="org-dup-head">
        <span class="org-dup-name">${esc(g.name)}</span>
        <span class="org-dup-size">${esc(g.size_h)}</span>
        <span class="org-dup-count">${g.copy_count} copies in ${g.site_count} site${g.site_count !== 1 ? 's' : ''}</span>
      </div>
      <div class="org-dup-locs">${locs}</div>
    </div>`;
  }).join('');
  const overflow = dupes.length > 100 ? `<div class="org-dup-overflow">Showing first 100 of ${dupes.length} groups.</div>` : '';
  return `<div id="dupSection" class="org-dup-section">
    <div class="org-dup-section-head">
      <span class="org-dup-section-title">Duplicate filenames across sites</span>
      <span class="org-dup-section-sub">${dupes.length} group${dupes.length !== 1 ? 's' : ''} — same name and size in more than one site folder. Advisory only, nothing gets moved.</span>
    </div>
    ${rows}
    ${overflow}
  </div>`;
}

function renderSuggestBanner() {
  if (!pendingGroupSuggestion) return '';
  const s = pendingGroupSuggestion;
  const nGroups = s.candidates.length;
  const nGrouped = s.candidates.reduce((a, c) => a + c.count, 0);
  let html = `<div class="org-suggest-banner">`;
  html += `<div class="org-suggest-head">`;
  html += `<div><b>Looks like ${nGroups} site${nGroups !== 1 ? 's' : ''} in one folder.</b> `;
  html += `Squirrel found ${nGrouped} file${nGrouped !== 1 ? 's' : ''} sharing common name prefixes — group them into subfolders first? `;
  html += `<span class="org-suggest-sub">${s.unmatched} file${s.unmatched !== 1 ? 's' : ''} with no obvious prefix will stay put.</span></div>`;
  html += `<div class="org-suggest-actions">`;
  html += `<button class="btn btn-sec btn-sm" onclick="dismissGroupSuggestion()">Dismiss</button>`;
  html += `<button class="btn btn-primary btn-sm" onclick="applyGroupSuggestion()">Group into subfolders</button>`;
  html += `</div></div>`;
  html += `<div class="org-suggest-list">`;
  for (const c of s.candidates) {
    html += `<label class="org-suggest-group">`;
    html += `<input type="checkbox" class="org-suggest-chk" checked data-prefix="${escAttr(c.prefix)}">`;
    html += `<span class="org-suggest-prefix">${esc(c.prefix)}</span>`;
    html += `<span class="org-suggest-count">${c.count} file${c.count !== 1 ? 's' : ''}</span>`;
    html += `</label>`;
  }
  html += `</div></div>`;
  return html;
}

function dismissGroupSuggestion() {
  pendingGroupSuggestion = null;
  renderPreview();
}

async function applyGroupSuggestion() {
  if (!pendingGroupSuggestion) return;
  const checkedPrefixes = new Set();
  document.querySelectorAll('.org-suggest-chk:checked').forEach(cb => {
    checkedPrefixes.add(cb.dataset.prefix);
  });
  if (checkedPrefixes.size === 0) {
    toast('Pick at least one group first', 'error');
    return;
  }
  const groups = pendingGroupSuggestion.candidates
    .filter(c => checkedPrefixes.has(c.prefix))
    .map(c => ({
      prefix: c.prefix,
      folder_name: c.prefix,
      files: c.files.map(f => f.name),
    }));
  const totalFiles = groups.reduce((a, g) => a + g.files.length, 0);
  if (!confirm(`Create ${groups.length} subfolder${groups.length !== 1 ? 's' : ''} and move ${totalFiles} file${totalFiles !== 1 ? 's' : ''} into them?\n\nYou can undo this from the Undo button.`)) return;
  const r = await api('apply_grouping', { root: currentRoot, groups });
  if (!r.ok) { toast(r.error, 'error'); return; }
  setUndoState(r.undo_available, r.undo_count);
  pendingGroupSuggestion = null;
  toast(`Grouped ${r.moved} file${r.moved !== 1 ? 's' : ''} into ${groups.length} subfolder${groups.length !== 1 ? 's' : ''}`);
  await doScan();
}

async function doUndo() {
  document.getElementById('mainMenu').classList.remove('open');
  if (!currentRoot || !undoAvailable) return;
  if (!confirm(`Undo the last organize?\n\n${undoCount} file${undoCount !== 1 ? 's' : ''} will be moved back to their original locations. Empty subfolders that Squirrel created will be removed.`)) return;
  const r = await api('undo', { root: currentRoot });
  if (!r.ok) { toast(r.error, 'error'); return; }
  const bits = [];
  if (r.restored) bits.push(`${r.restored} restored`);
  if (r.skipped) bits.push(`${r.skipped} skipped`);
  if (r.errors) bits.push(`${r.errors} error${r.errors !== 1 ? 's' : ''}`);
  toast(`Undo complete — ${bits.join(', ')}`);
  setUndoState(false, 0);
  await doScan();
}

function toggleAll(checked) {
  document.querySelectorAll('#siteList input[type="checkbox"]').forEach(cb => cb.checked = checked);
}
function toggleSite(headerCb, siteName) {
  document.querySelectorAll(`#siteList input[data-site="${CSS.escape(siteName)}"]`).forEach(cb => cb.checked = headerCb.checked);
}
function onDestChange(sel) {
  sel.className = 'dest-select dest-' + sel.value;
  if (sel.value !== sel.dataset.original) sel.classList.add('overridden');
}

let _lastChecked = null;
document.addEventListener('click', function(e) {
  const cb = e.target.closest('input[type="checkbox"][data-file]');
  if (!cb) return;
  if (e.shiftKey && _lastChecked && _lastChecked !== cb) {
    const allCbs = Array.from(document.querySelectorAll('#siteList input[data-file]'));
    if (!_lastChecked || allCbs.indexOf(_lastChecked) < 0) { _lastChecked = cb; return; }
    const start = allCbs.indexOf(_lastChecked);
    const end = allCbs.indexOf(cb);
    const lo = Math.min(start, end), hi = Math.max(start, end);
    for (let i = lo; i <= hi; i++) {
      allCbs[i].checked = cb.checked;
    }
  }
  _lastChecked = cb;
});

function bulkSetDest(target) {
  const checked = document.querySelectorAll('#siteList input[data-file]:checked');
  if (checked.length === 0) { toast('No files selected', 'error'); return; }
  checked.forEach(cb => {
    const row = cb.closest('tr');
    const sel = row.querySelector('select.dest-select');
    if (sel) {
      sel.value = target;
      onDestChange(sel);
    }
  });
  toast(`Set ${checked.length} file${checked.length !== 1 ? 's' : ''} → ${target}/`);
}

async function doExecute() {
  if (!scanData || !currentRoot) return;
  const excluded = [];
  document.querySelectorAll('#siteList input[data-file]').forEach(cb => {
    if (!cb.checked) {
      excluded.push({ folder: cb.dataset.site, name: cb.dataset.file });
    }
  });
  const overrides = [];
  document.querySelectorAll('#siteList select.dest-select').forEach(sel => {
    if (sel.value !== sel.dataset.original) {
      overrides.push({ folder: sel.dataset.site, name: sel.dataset.file, target: sel.value });
    }
  });
  const totalChecked = document.querySelectorAll('#siteList input[data-file]:checked').length;
  if (totalChecked === 0) { toast('No files selected to move', 'error'); return; }
  const overrideNote = overrides.length ? `\n${overrides.length} file${overrides.length !== 1 ? 's' : ''} reassigned to a different folder.` : '';
  if (!confirm(`Move ${totalChecked} file${totalChecked !== 1 ? 's' : ''} into their subfolders?${overrideNote}\n\nUse Undo on the results screen to reverse this.`)) return;

  showScreen('execScreen');
  const r = await api('execute', { root: currentRoot, excluded, overrides });
  if (!r.ok) { toast(r.error, 'error'); showScreen('previewScreen'); return; }
  setUndoState(r.undo_available, r.undo_count);
  renderResults(r);
}

function renderResults(r) {
  showScreen('resultScreen');
  const t = r.totals;
  const dests = destinationList(cachedConfig);
  const totalMoved = dests.reduce((sum, d) => sum + (t[d.key] || 0), 0);
  let html = '<div class="toolbar"><button class="btn btn-sec" onclick="doScan()">← Back to Preview</button>';
  if (undoAvailable) {
    html += `<button class="btn btn-amber" id="resultUndoBtn" onclick="doUndo()" title="Reverse the last organize — moves each file back to its original location">↶ Undo Last Organize (${undoCount})</button>`;
  }
  html += '<button class="btn btn-primary" onclick="pickFolder()">Organize Another Folder</button></div>';
  const destChips = dests.map(dst => {
    const cls = destinationCssClass(dst.key).replace('dest-', 'chip-');
    return `<div class="summary-chip ${cls}"><span class="num">${t[dst.key] || 0}</span> → ${esc(dst.name)}</div>`;
  }).join('');
  html += `<div class="summary-bar">${destChips}`;
  if (t.skipped) html += `<div class="summary-chip chip-staying"><span class="num">${t.skipped}</span> skipped</div>`;
  if (t.errors) html += `<div class="summary-chip chip-errors"><span class="num">${t.errors}</span> errors</div>`;
  html += '</div>';

  if (totalMoved === 0 && t.errors === 0) {
    html += '<div class="org-empty">Nothing to move — all files were excluded or already organized.</div>';
  }

  for (const site of r.sites) {
    html += `<div class="site-group"><div class="site-header" onclick="this.parentElement.classList.toggle('collapsed')">`;
    html += `<span class="site-name">${esc(site.folder)}</span><span class="site-chevron">▾</span></div>`;
    html += '<div class="site-body"><table class="file-table"><thead><tr><th>File</th><th>Destination</th><th>Status</th></tr></thead><tbody>';
    for (const m of site.moves) {
      html += `<tr><td>${esc(m.name)}</td>`;
      html += `<td>${m.target}/`;
      if (m.renamed_to) html += ` <span class="renamed">(→ ${esc(m.renamed_to)})</span>`;
      html += '</td>';
      html += `<td><span class="result-status result-${m.status}">${m.status}</span>`;
      if (m.error) html += ` <span class="org-error-chip">${esc(m.error)}</span>`;
      html += '</td></tr>';
    }
    html += '</tbody></table></div></div>';
  }
  document.getElementById('resultScreen').innerHTML = html;
  toast(`Done — ${totalMoved} file${totalMoved !== 1 ? 's' : ''} organized`);
}

async function showSettings() {
  document.getElementById('mainMenu').classList.remove('open');
  const r = await api('get_config');
  if (!r.ok) { toast(r.error, 'error'); return; }
  const c = r.config;
  document.getElementById('cfgImages').value = c.image_ext.join(', ');
  document.getElementById('cfgPlans').value = c.plan_ext.join(', ');
  document.getElementById('cfgReports').value = c.report_ext.join(', ');
  document.getElementById('cfgPdfKw').value = c.report_keywords.join(', ');
  document.getElementById('cfgJsonKw').value = c.json_report_keywords.join(', ');
  document.getElementById('cfgSkip').value = c.skip_dirs.join(', ');
  const sn = c.subfolder_names || {};
  document.getElementById('cfgSubImages').value = sn.images || 'images';
  document.getElementById('cfgSubPlans').value = sn.floorplans || 'floorplans';
  document.getElementById('cfgSubReports').value = sn.reports || 'reports';
  document.getElementById('cfgCreateTemplate').value = c.create_folder_template || '';
  renderCustomDestinationsEditor(c.custom_destinations || []);
  document.getElementById('settingsModal').classList.add('active');
}


function renderCustomDestinationsEditor(customs) {
  const host = document.getElementById('cfgCustomDestList');
  if (!host) return;
  host.innerHTML = '';
  (customs || []).forEach(c => host.appendChild(buildCustomDestRow(c)));
}

function buildCustomDestRow(c) {
  c = c || {};
  const row = document.createElement('div');
  row.className = 'org-custom-dest-row';
  row.innerHTML = `
    <div class="org-custom-dest-grid">
      <label class="org-custom-dest-field">
        <span>Folder name</span>
        <input type="text" class="org-cd-name" placeholder="e.g. raw-data" value="${escAttr(c.name || '')}">
      </label>
      <label class="org-custom-dest-field">
        <span>Extensions</span>
        <input type="text" class="org-cd-exts" placeholder=".csv, .tsv, .md" value="${escAttr((c.exts || []).join(', '))}">
      </label>
      <label class="org-custom-dest-field">
        <span>PDF keywords <span class="hint-inline">(optional)</span></span>
        <input type="text" class="org-cd-pdfkw" placeholder="manual, spec" value="${escAttr((c.pdf_keywords || []).join(', '))}">
      </label>
      <label class="org-custom-dest-field">
        <span>JSON keywords <span class="hint-inline">(optional)</span></span>
        <input type="text" class="org-cd-jsonkw" placeholder="config, snapshot" value="${escAttr((c.json_keywords || []).join(', '))}">
      </label>
    </div>
    <button type="button" class="btn btn-sec btn-sm org-cd-remove" title="Remove this destination">✕</button>
  `;
  row.querySelector('.org-cd-remove').addEventListener('click', () => row.remove());
  return row;
}

function addCustomDestination() {
  const host = document.getElementById('cfgCustomDestList');
  if (!host) return;
  host.appendChild(buildCustomDestRow({}));
}

function readCustomDestinations() {
  const host = document.getElementById('cfgCustomDestList');
  if (!host) return [];
  const out = [];
  const seen = new Set();
  host.querySelectorAll('.org-custom-dest-row').forEach(row => {
    const name = row.querySelector('.org-cd-name').value.trim();
    if (!name) return;

    const key = name.toLowerCase().replace(/[^a-z0-9_-]/g, '').replace(/^[-_]+|[-_]+$/g, '');
    if (!key || seen.has(key)) return;
    if (key === 'images' || key === 'floorplans' || key === 'reports') return;
    seen.add(key);
    const parse = sel => row.querySelector(sel).value
      .split(',').map(s => s.trim()).filter(Boolean);
    out.push({
      key,
      name,
      exts: parse('.org-cd-exts'),
      pdf_keywords: parse('.org-cd-pdfkw'),
      json_keywords: parse('.org-cd-jsonkw'),
    });
  });
  return out;
}
async function saveConfig() {
  const parse = id => document.getElementById(id).value.split(',').map(s => s.trim()).filter(Boolean);
  const cfg = {
    image_ext: parse('cfgImages'),
    plan_ext: parse('cfgPlans'),
    report_ext: parse('cfgReports'),
    report_keywords: parse('cfgPdfKw'),
    json_report_keywords: parse('cfgJsonKw'),
    skip_dirs: parse('cfgSkip'),
    subfolder_names: {
      images: (document.getElementById('cfgSubImages').value || 'images').trim() || 'images',
      floorplans: (document.getElementById('cfgSubPlans').value || 'floorplans').trim() || 'floorplans',
      reports: (document.getElementById('cfgSubReports').value || 'reports').trim() || 'reports',
    },
    create_folder_template: document.getElementById('cfgCreateTemplate').value.trim(),
    custom_destinations: readCustomDestinations(),
  };
  const r = await api('set_config', { config: cfg });
  if (!r.ok) { toast(r.error, 'error'); return; }
  closeModal('settingsModal');
  toast('Settings saved');
  if (currentRoot) doScan();
}

function subfolderDisplayOrder(cfg) {
  return destinationList(cfg).map(d => d.name);
}


function destinationList(cfg) {
  if (scanData && Array.isArray(scanData.destinations) && scanData.destinations.length) {
    return scanData.destinations.map(d => ({ ...d }));
  }
  cfg = cfg || cachedConfig || {};
  const names = cfg.subfolder_names || {};
  const list = [
    { key: 'images',     name: names.images     || 'images',     builtin: true },
    { key: 'floorplans', name: names.floorplans || 'floorplans', builtin: true },
    { key: 'reports',    name: names.reports    || 'reports',    builtin: true },
  ];
  const seenKeys = new Set(list.map(d => d.key));
  const seenNames = new Set(list.map(d => d.name.toLowerCase()));
  for (const c of (cfg.custom_destinations || [])) {
    if (!c || typeof c !== 'object') continue;
    const rawKey = (c.key || c.name || '').toString();
    const key = rawKey.toLowerCase().replace(/[^a-z0-9_-]/g, '');
    if (!key || seenKeys.has(key)) continue;
    const name = (c.name || key).toString().trim() || key;
    if (seenNames.has(name.toLowerCase())) continue;
    seenKeys.add(key);
    seenNames.add(name.toLowerCase());
    list.push({ key, name, builtin: false });
  }
  return list;
}

function destinationCssClass(key) {


  if (key === 'images' || key === 'floorplans' || key === 'reports') return 'dest-' + key;
  return 'dest-custom';
}

function esxBadges(s) {
  if (!s || s.reason !== 'esx' || !s.esx) return '';
  const x = s.esx;
  const bits = [];
  if (x.floors > 0) bits.push(`<span class="esx-badge esx-badge-floors">${x.floors} floor${x.floors !== 1 ? 's' : ''}</span>`);
  if (x.aps > 0) bits.push(`<span class="esx-badge esx-badge-aps">${x.aps} AP${x.aps !== 1 ? 's' : ''}</span>`);
  if (x.measurements > 0) bits.push(`<span class="esx-badge esx-badge-meas">${x.measurements} measured</span>`);
  if (x.surveys > 0) bits.push(`<span class="esx-badge esx-badge-surveys">${x.surveys} survey${x.surveys !== 1 ? 's' : ''}</span>`);
  if (!bits.length) return '';
  return `<div class="esx-badges">${bits.join('')}</div>`;
}

function renameActiveSummary(cfg) {
  const rn = (cfg && cfg.rename) || {};
  const bits = [];
  if (rn.strip_prefix || rn.strip_suffix) bits.push('remove');
  if (rn.regex_from) bits.push('replace');
  if (rn.separator) bits.push('separators');
  if (rn.case) bits.push('case');
  if (rn.prefix || rn.suffix) bits.push('prefix/suffix');
  return bits;
}
async function resetConfig() {
  if (!confirm('Reset all type mappings to defaults?')) return;
  const r = await api('reset_config');
  if (!r.ok) { toast(r.error, 'error'); return; }
  closeModal('settingsModal');
  toast('Settings reset to defaults');
  if (currentRoot) doScan();
}

async function migrateSubfolders() {
  if (!currentRoot) { toast('Pick a folder first', 'error'); return; }
  const wanted = {
    images: (document.getElementById('cfgSubImages').value || '').trim() || 'images',
    floorplans: (document.getElementById('cfgSubPlans').value || '').trim() || 'floorplans',
    reports: (document.getElementById('cfgSubReports').value || '').trim() || 'reports',
  };
  const renames = {};
  const defaults = { images: 'images', floorplans: 'floorplans', reports: 'reports' };
  for (const key of ['images','floorplans','reports']) {
    if (wanted[key] && wanted[key] !== defaults[key]) {
      renames[defaults[key]] = wanted[key];
    }
  }
  if (!Object.keys(renames).length) {
    toast('No renames to apply — Destination names still match the defaults', 'info');
    return;
  }
  const summary = Object.entries(renames).map(([o, n]) => `${o}/ → ${n}/`).join('\n');
  if (!confirm(`Migrate on-disk subfolders across every site under:\n${currentRoot}\n\n${summary}\n\nExisting target folders are not overwritten — they'll be skipped and reported.`)) return;
  const r = await api('migrate_subfolders', { root: currentRoot, renames });
  if (!r.ok) { toast(r.error, 'error'); return; }
  toast(`Migrated ${r.renamed} folder${r.renamed !== 1 ? 's' : ''}${r.skipped ? ` (${r.skipped} skipped)` : ''}`);
  if (currentRoot) doScan();
}

document.querySelectorAll('.modal-overlay').forEach(ov => {
  ov.addEventListener('click', e => { if (e.target === ov) ov.classList.remove('active'); });
});

function updateCreateFolderRoot() {
  const rootNote = document.getElementById('createFolderRoot');
  const btn = document.getElementById('createFolderBtn');
  if (currentRoot) {
    rootNote.textContent = currentRoot;
    rootNote.classList.remove('org-root-empty');
    btn.disabled = false;
    btn.classList.remove('org-btn-disabled');
  } else {
    rootNote.innerHTML = '<span class="org-root-hint">Click Browse… to select a folder</span>';
    btn.disabled = true;
    btn.classList.add('org-btn-disabled');
  }
}
const CREATE_TOKENS = ['site_code', 'site_name', 'city', 'state', 'zip', 'date'];
const CREATE_TOKEN_LABELS = {
  site_code: 'Site code',
  site_name: 'Site name',
  city: 'City',
  state: 'State',
  zip: 'ZIP',
  date: 'Date (auto)',
};
const _TOKEN_ALIASES = { code: 'site_code', name: 'site_name' };

function _extractTokens(template) {
  const seen = new Set();
  const found = [];
  const re = /\{([a-z_]+)\}/g;
  let m;
  while ((m = re.exec(template))) {
    let t = m[1];
    if (_TOKEN_ALIASES[t]) t = _TOKEN_ALIASES[t];
    if (CREATE_TOKENS.includes(t) && !seen.has(t)) {
      seen.add(t);
      found.push(t);
    }
  }
  return found;
}

function _rememberedToken(token) {
  if (token === 'date') return new Date().toISOString().slice(0, 10);
  try { return localStorage.getItem('wd-create-token-' + token) || ''; }
  catch (e) { return ''; }
}
function _rememberToken(token, value) {
  if (token === 'date') return;
  try { localStorage.setItem('wd-create-token-' + token, value || ''); } catch (e) {}
}

function _composeFolderName(template, tokens) {
  return template.replace(/\{([a-z_]+)\}/g, (_, t) => {
    const key = _TOKEN_ALIASES[t] || t;
    return tokens[key] || '';
  });
}

function _folderMode() {
  const btn = document.getElementById('folderModeExistingBtn');
  return (btn && btn.classList.contains('active')) ? 'existing' : 'new';
}

function setFolderMode(mode) {
  const newBtn = document.getElementById('folderModeNewBtn');
  const existingBtn = document.getElementById('folderModeExistingBtn');
  const nameInput = document.getElementById('newFolderName');
  const select = document.getElementById('existingFolderSelect');
  if (!newBtn || !existingBtn || !nameInput || !select) return;
  newBtn.classList.toggle('active', mode !== 'existing');
  existingBtn.classList.toggle('active', mode === 'existing');
  nameInput.hidden = mode === 'existing';
  select.hidden = mode !== 'existing';
  setTimeout(() => (mode === 'existing' ? select : nameInput).focus(), 50);
  _updateFolderStatus();
}

function _renderTokenFields(template) {
  const tokens = _extractTokens(template);
  const wrap = document.getElementById('newFolderTokenFields');
  const preview = document.getElementById('newFolderPreview');
  const nameInput = document.getElementById('newFolderName');
  const select = document.getElementById('existingFolderSelect');
  const modeToggle = document.getElementById('newFolderModeToggle');
  const label = document.getElementById('newFolderLabel');
  const bulkToggle = document.getElementById('bulkCreateToggle');
  const bulkVaryRow = document.getElementById('bulkVaryRow');
  const bulkVarySelect = document.getElementById('bulkVaryToken');
  const bulkInput = document.getElementById('bulkNamesInput');
  const bulkPreview = document.getElementById('bulkPreview');
  const bulkImportRow = document.getElementById('bulkImportRow');
  const bulk = !!(bulkToggle && bulkToggle.checked);

  if (!bulk) {
    bulkVaryRow.hidden = true;
    bulkInput.hidden = true;
    bulkPreview.hidden = true;
    bulkImportRow.hidden = true;
    bulkInput.oninput = null;

    if (!tokens.length) {
      wrap.hidden = true; preview.hidden = true;
      modeToggle.hidden = false;
      label.textContent = 'Folder name';
      setFolderMode(_folderMode());
      return;
    }
    wrap.hidden = false; preview.hidden = false;
    modeToggle.hidden = true;
    nameInput.hidden = true;
    select.hidden = true;
    label.textContent = 'Fill each token';
    wrap.innerHTML = tokens.map(t => `<div class="org-token-row">
      <label class="org-token-label">${CREATE_TOKEN_LABELS[t] || t}</label>
      <input type="text" class="org-token-input" data-token="${t}" value="${escAttr(_rememberedToken(t))}" ${t === 'date' ? 'readonly' : ''}>
    </div>`).join('');
    wrap.oninput = _updateFolderPreview;
    _updateFolderPreview();
    return;
  }


  modeToggle.hidden = true;
  nameInput.hidden = true;
  select.hidden = true;
  document.getElementById('newFolderStatus').hidden = true;

  if (!tokens.length) {

    wrap.hidden = true; preview.hidden = true;
    bulkVaryRow.hidden = true;
    label.textContent = 'Folder names';
    bulkInput.hidden = false;
    bulkInput.placeholder = 'One folder name per line, e.g.\nBuilding A - 100 Example Ave\nBuilding B - 100 Example Ave';
    bulkInput.oninput = _updateBulkPreview;
    bulkImportRow.hidden = false;
    bulkPreview.hidden = false;
    _updateBulkPreview();
    return;
  }


  label.textContent = 'Shared fields';
  const varyTokens = tokens.filter(t => t !== 'date');
  const prevVary = bulkVarySelect.value;
  bulkVarySelect.innerHTML = varyTokens.map(t => `<option value="${t}">${esc(CREATE_TOKEN_LABELS[t] || t)}</option>`).join('');
  bulkVarySelect.value = varyTokens.includes(prevVary) ? prevVary : varyTokens[0];
  const varyToken = bulkVarySelect.value;
  bulkVaryRow.hidden = varyTokens.length < 2;
  bulkVarySelect.onchange = () => _renderTokenFields(template);

  const sharedTokens = tokens.filter(t => t !== varyToken);
  wrap.hidden = sharedTokens.length === 0;
  preview.hidden = true;
  wrap.innerHTML = sharedTokens.map(t => `<div class="org-token-row">
    <label class="org-token-label">${CREATE_TOKEN_LABELS[t] || t}</label>
    <input type="text" class="org-token-input" data-token="${t}" value="${escAttr(_rememberedToken(t))}" ${t === 'date' ? 'readonly' : ''}>
  </div>`).join('');
  wrap.oninput = _updateBulkPreview;

  bulkInput.hidden = false;
  bulkInput.placeholder = `One ${(CREATE_TOKEN_LABELS[varyToken] || varyToken).toLowerCase()} per line, e.g.\nBuilding A\nBuilding B`;
  bulkInput.oninput = _updateBulkPreview;
  bulkImportRow.hidden = false;
  bulkPreview.hidden = false;
  _updateBulkPreview();
}

function toggleBulkCreate() {
  const template = (cachedConfig && cachedConfig.create_folder_template) || '';
  _renderTokenFields(template);
}

function _updateBulkPreview() {
  const bulkInput = document.getElementById('bulkNamesInput');
  const bulkPreview = document.getElementById('bulkPreview');
  const btn = document.getElementById('createFolderBtn');
  const bulkToggle = document.getElementById('bulkCreateToggle');
  if (!bulkInput || !bulkPreview || !bulkToggle || !bulkToggle.checked) return;
  const lines = bulkInput.value.split('\n').map(s => s.trim()).filter(Boolean);
  const template = (cachedConfig && cachedConfig.create_folder_template) || '';
  const tokens = _extractTokens(template);

  let names;
  if (tokens.length) {
    const varySelect = document.getElementById('bulkVaryToken');
    const varyToken = varySelect ? varySelect.value : '';
    const shared = {};
    document.querySelectorAll('.org-token-input').forEach(i => { shared[i.dataset.token] = i.value.trim(); });
    const missingShared = tokens.filter(t => t !== 'date' && t !== varyToken && !shared[t]);
    if (missingShared.length) {
      bulkPreview.innerHTML = `<span class="org-token-preview-label">Fill in first:</span> ${missingShared.map(t => esc(CREATE_TOKEN_LABELS[t] || t)).join(', ')}`;
      if (btn) btn.disabled = true;
      return;
    }
    names = lines.map(v => _composeFolderName(template, Object.assign({}, shared, { [varyToken]: v })).trim()).filter(Boolean);
  } else {
    names = lines;
  }

  if (!names.length) {
    bulkPreview.innerHTML = `<span class="org-token-preview-label">Enter at least one, one per line</span>`;
    if (btn) btn.disabled = true;
    return;
  }

  const existingCount = names.filter(n => _existingFoldersLower.has(n.toLowerCase())).length;
  const newCount = names.length - existingCount;
  const rows = names.map(n => {
    const exists = _existingFoldersLower.has(n.toLowerCase());
    return `<div class="org-bulk-preview-row${exists ? ' is-topup' : ' is-fresh'}"><code>${esc(n)}</code><span>${exists ? '&#8635; existing' : '+ new'}</span></div>`;
  }).join('');
  const summary = existingCount
    ? `${names.length} folder${names.length !== 1 ? 's' : ''} — ${newCount} new, ${existingCount} existing (missing subfolders only)`
    : `${names.length} folder${names.length !== 1 ? 's' : ''} will be created`;
  bulkPreview.innerHTML = `<div class="org-bulk-preview-summary">${summary}</div>${rows}`;
  if (btn) btn.disabled = false;
}


let _mammothLoaded = false;
let _pdfjsLoaded = false;

function _ensureMammothLoaded() {
  if (_mammothLoaded || window.mammoth) { _mammothLoaded = true; return Promise.resolve(); }
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = '/assets/lib/mammoth.browser.min.js';
    s.onload = () => { _mammothLoaded = true; resolve(); };
    s.onerror = () => reject(new Error('Could not load the .docx reader'));
    document.head.appendChild(s);
  });
}

async function _ensurePdfjsLoaded() {
  if (_pdfjsLoaded || window.pdfjsLib) { _pdfjsLoaded = true; return; }
  const pdfjsLib = await import('/assets/lib/pdf.min.mjs');
  window.pdfjsLib = pdfjsLib;
  window.pdfjsLib.GlobalWorkerOptions.workerSrc = '/assets/lib/pdf.worker.min.mjs';
  _pdfjsLoaded = true;
}

async function _extractTextFromFile(file) {
  const ext = (file.name.split('.').pop() || '').toLowerCase();
  if (ext === 'txt') return await file.text();
  if (ext === 'docx') {
    await _ensureMammothLoaded();
    const arrayBuffer = await file.arrayBuffer();
    const r = await window.mammoth.extractRawText({ arrayBuffer });
    return r.value || '';
  }
  if (ext === 'pdf') {
    await _ensurePdfjsLoaded();
    const arrayBuffer = await file.arrayBuffer();
    const pdf = await window.pdfjsLib.getDocument({ data: arrayBuffer, isEvalSupported: false }).promise;
    let text = '';
    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i);
      const content = await page.getTextContent();
      text += content.items.map(it => it.str).join(' ') + '\n';
    }
    return text;
  }
  throw new Error('Unsupported file type — use .txt, .docx, or .pdf');
}


function _linesFromExtractedText(text) {
  return text.split('\n')
    .map(l => l.replace(/^[\s]*[-•*•]\s+/, '').replace(/^[\s]*\d+[.)]\s+/, '').trim())
    .filter(Boolean);
}

async function handleBulkImportFile(input) {
  const file = input.files && input.files[0];
  input.value = '';
  if (!file) return;
  const bulkInput = document.getElementById('bulkNamesInput');
  toast(`Reading ${file.name}…`, 'info');
  try {
    const text = await _extractTextFromFile(file);
    const lines = _linesFromExtractedText(text);
    if (!lines.length) { toast('No text found in that file', 'error'); return; }
    bulkInput.value = lines.join('\n');
    _updateBulkPreview();
    toast(`Imported ${lines.length} line${lines.length !== 1 ? 's' : ''} from ${file.name}`);
  } catch (e) {
    toast('Could not read that file: ' + (e.message || e), 'error');
  }
}

function _updateFolderPreview() {
  const template = (cachedConfig && cachedConfig.create_folder_template) || '';
  const tokens = {};
  document.querySelectorAll('.org-token-input').forEach(i => {
    tokens[i.dataset.token] = i.value.trim();
  });
  const composed = _composeFolderName(template, tokens);
  const preview = document.getElementById('newFolderPreview');
  preview.innerHTML = composed
    ? `<span class="org-token-preview-label">Preview:</span> <code>${esc(composed)}</code>`
    : `<span class="org-token-preview-label">Fill tokens to see preview</span>`;
  _updateFolderStatus();
}

let _existingFoldersLower = new Set();
async function showCreateFolder() {
  document.getElementById('mainMenu').classList.remove('open');
  document.getElementById('newFolderName').value = '';
  const select = document.getElementById('existingFolderSelect');
  if (select) select.value = '';
  const bulkToggle = document.getElementById('bulkCreateToggle');
  if (bulkToggle) bulkToggle.checked = false;
  const bulkInput = document.getElementById('bulkNamesInput');
  if (bulkInput) bulkInput.value = '';
  setFolderMode('new');
  await _restoreCurrentRootSilently();
  await refreshConfig();
  const template = (cachedConfig && cachedConfig.create_folder_template) || '';
  _renderTokenFields(template);
  _renderSubfolderPicker();
  updateCreateFolderRoot();
  _refreshExistingFolderList();
  _updateFolderStatus();
  document.getElementById('createFolderModal').classList.add('active');
  if (currentRoot) {
    setTimeout(() => {
      const firstInput = document.querySelector('.org-token-input:not([readonly])') || document.getElementById('newFolderName');
      firstInput.focus();
    }, 100);
  }
}

async function _refreshExistingFolderList() {
  const select = document.getElementById('existingFolderSelect');
  if (select) select.innerHTML = '<option value="">Select a folder&hellip;</option>';
  _existingFoldersLower = new Set();
  if (!currentRoot) return;
  const r = await api('list_root_folders', { root: currentRoot });
  if (!r || !r.ok || !Array.isArray(r.folders)) return;
  _existingFoldersLower = new Set(r.folders.map(n => n.toLowerCase()));
  if (select) {
    select.innerHTML = '<option value="">Select a folder&hellip;</option>'
      + r.folders.map(n => `<option value="${escAttr(n)}">${esc(n)}</option>`).join('');
  }
  _updateFolderStatus();
  _updateBulkPreview();
}

function _currentFolderNameForStatus() {
  const template = (cachedConfig && cachedConfig.create_folder_template) || '';
  const tokens = _extractTokens(template);
  if (tokens.length) {
    const values = {};
    document.querySelectorAll('.org-token-input').forEach(i => {
      values[i.dataset.token] = i.value.trim();
    });
    if (tokens.filter(t => t !== 'date' && !values[t]).length) return '';
    return _composeFolderName(template, values).trim();
  }
  if (_folderMode() === 'existing') {
    const select = document.getElementById('existingFolderSelect');
    return select ? select.value.trim() : '';
  }
  const el = document.getElementById('newFolderName');
  return el ? el.value.trim() : '';
}

function _updateFolderStatus() {
  const status = document.getElementById('newFolderStatus');
  if (!status) return;
  const name = _currentFolderNameForStatus();
  if (!name) { status.hidden = true; status.textContent = ''; status.className = 'org-folder-status'; return; }
  const exists = _existingFoldersLower.has(name.toLowerCase());
  status.hidden = false;
  if (exists) {
    status.className = 'org-folder-status is-topup';
    status.innerHTML = `<span class="org-folder-status-dot"></span>&#8623; Existing folder — will add missing subfolders only`;
  } else {
    status.className = 'org-folder-status is-fresh';
    status.innerHTML = `<span class="org-folder-status-dot"></span>&#10010; New folder — will be created`;
  }
}

function _renderSubfolderPicker() {
  const host = document.getElementById('newFolderSubs');
  if (!host) return;
  const dests = destinationList(cachedConfig);
  host.innerHTML = dests.map(d => {
    const cls = destinationCssClass(d.key);
    return `<label class="org-sub-check">`
      + `<input type="checkbox" class="org-sub-cb" checked>`
      + `<span class="org-sub-swatch ${cls}"></span>`
      + `<input type="text" class="org-sub-name-input" value="${escAttr(d.name)}">`
      + (d.builtin ? '' : `<span class="org-sub-tag">custom</span>`)
      + `</label>`;
  }).join('');
}

function addAdHocSubfolder() {
  const host = document.getElementById('newFolderSubs');
  if (!host) return;
  const row = document.createElement('label');
  row.className = 'org-sub-check';
  row.innerHTML = `<input type="checkbox" class="org-sub-cb" checked>`
    + `<span class="org-sub-swatch dest-custom"></span>`
    + `<input type="text" class="org-sub-name-input" placeholder="New subfolder name">`
    + `<span class="org-sub-tag">new</span>`
    + `<button type="button" class="share-remove org-sub-remove" title="Remove">&times;</button>`;
  row.querySelector('.org-sub-remove').addEventListener('click', () => row.remove());
  host.appendChild(row);
  row.querySelector('.org-sub-name-input').focus();
}

function _selectedSubfolderNames() {
  const names = [];
  document.querySelectorAll('#newFolderSubs .org-sub-check').forEach(row => {
    const cb = row.querySelector('.org-sub-cb');
    const inp = row.querySelector('.org-sub-name-input');
    if (cb && cb.checked && inp) {
      const v = inp.value.trim();
      if (v) names.push(v);
    }
  });
  return names;
}
async function pickRootForCreate() {
  const r = await api('pick_folder');
  if (!r.ok) { if (r.error !== 'No folder selected') toast(r.error, 'error'); return; }
  currentRoot = r.path;
  rememberProjectDirectory(currentRoot);
  updateCreateFolderRoot();
  _refreshExistingFolderList();
  setTimeout(() => {
    const el = _folderMode() === 'existing' ? document.getElementById('existingFolderSelect') : document.getElementById('newFolderName');
    el.focus();
  }, 100);
}
async function doCreateFolder() {
  const bulkToggle = document.getElementById('bulkCreateToggle');
  if (bulkToggle && bulkToggle.checked) { await doCreateFolderBulk(); return; }
  let name;
  const template = (cachedConfig && cachedConfig.create_folder_template) || '';
  const tokens = _extractTokens(template);
  if (tokens.length) {
    const values = {};
    document.querySelectorAll('.org-token-input').forEach(i => {
      values[i.dataset.token] = i.value.trim();
    });

    Object.entries(values).forEach(([k, v]) => _rememberToken(k, v));

    const missing = tokens.filter(t => t !== 'date' && !values[t]);
    if (missing.length) {
      toast(`Fill in: ${missing.map(t => CREATE_TOKEN_LABELS[t]).join(', ')}`, 'error');
      return;
    }
    name = _composeFolderName(template, values).trim();
  } else if (_folderMode() === 'existing') {
    name = document.getElementById('existingFolderSelect').value.trim();
    if (!name) { toast('Pick an existing folder', 'error'); return; }
  } else {
    name = document.getElementById('newFolderName').value.trim();
  }
  if (!name) { toast('Enter a folder name', 'error'); return; }
  if (!currentRoot) { toast('Select a root folder first', 'error'); return; }
  const subfolderNames = _selectedSubfolderNames();
  const r = await api('create_project_folder', {
    name,
    root: currentRoot,
    subfolders: subfolderNames,
  });
  if (!r.ok) { toast(r.error, 'error'); return; }
  closeModal('createFolderModal');
  const subs = (r.subfolders || []);
  const added = (r.added || []);
  let msg;
  if (r.existed) {
    msg = added.length
      ? `"${r.name}" already existed — added ${added.length} subfolder${added.length === 1 ? '' : 's'}: ${added.join(', ')}`
      : `"${r.name}" already existed with all subfolders — nothing to add`;
  } else {
    msg = subs.length
      ? `Created "${r.name}" with ${subs.length} subfolder${subs.length === 1 ? '' : 's'}: ${subs.join(', ')}`
      : `Created "${r.name}" (no subfolders)`;
  }
  toast(msg);
}

async function doCreateFolderBulk() {
  if (!currentRoot) { toast('Select a root folder first', 'error'); return; }
  const bulkInput = document.getElementById('bulkNamesInput');
  const lines = bulkInput.value.split('\n').map(s => s.trim()).filter(Boolean);
  if (!lines.length) { toast('Enter at least one folder, one per line', 'error'); return; }

  const template = (cachedConfig && cachedConfig.create_folder_template) || '';
  const tokens = _extractTokens(template);
  let names;
  if (tokens.length) {
    const varyToken = document.getElementById('bulkVaryToken').value;
    const shared = {};
    document.querySelectorAll('.org-token-input').forEach(i => { shared[i.dataset.token] = i.value.trim(); });
    Object.entries(shared).forEach(([k, v]) => _rememberToken(k, v));
    const missing = tokens.filter(t => t !== 'date' && t !== varyToken && !shared[t]);
    if (missing.length) {
      toast(`Fill in: ${missing.map(t => CREATE_TOKEN_LABELS[t]).join(', ')}`, 'error');
      return;
    }
    names = lines.map(v => _composeFolderName(template, Object.assign({}, shared, { [varyToken]: v })).trim()).filter(Boolean);
  } else {
    names = lines;
  }
  if (!names.length) { toast('Enter at least one folder, one per line', 'error'); return; }

  const subfolderNames = _selectedSubfolderNames();
  const btn = document.getElementById('createFolderBtn');
  const originalBtnText = btn ? btn.textContent : 'Create';
  if (btn) btn.disabled = true;

  let okCount = 0, existedCount = 0;
  const failures = [];
  for (let i = 0; i < names.length; i++) {
    const name = names[i];
    if (btn) btn.textContent = `Creating ${i + 1}/${names.length}…`;
    const r = await api('create_project_folder', { name, root: currentRoot, subfolders: subfolderNames });
    if (r && r.ok) { okCount++; if (r.existed) existedCount++; }
    else failures.push(`${name}: ${(r && r.error) || 'unknown error'}`);
  }

  if (btn) { btn.disabled = false; btn.textContent = originalBtnText; }
  await _refreshExistingFolderList();

  if (failures.length) {
    console.error('Bulk create failures:\n' + failures.join('\n'));
    toast(`Created ${okCount} of ${names.length} — ${failures.length} failed (see console)`, 'error');
  } else {
    const freshCount = okCount - existedCount;
    toast(existedCount
      ? `Created ${freshCount} folder${freshCount !== 1 ? 's' : ''}, topped up ${existedCount} existing`
      : `Created ${okCount} folder${okCount !== 1 ? 's' : ''}`);
    closeModal('createFolderModal');
  }
}

document.getElementById('newFolderName').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') { e.preventDefault(); doCreateFolder(); }
});
document.getElementById('newFolderName').addEventListener('input', _updateFolderStatus);
document.getElementById('newFolderName').addEventListener('change', _updateFolderStatus);
document.getElementById('existingFolderSelect').addEventListener('change', _updateFolderStatus);
document.getElementById('existingFolderSelect').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') { e.preventDefault(); doCreateFolder(); }
});
document.getElementById('createFolderModal').addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && e.target.classList && e.target.classList.contains('org-token-input')) {
    e.preventDefault(); doCreateFolder();
  }
});

restoreProjectDirectory();


let _extractState = { esxPath: '', outDir: '', floors: [] };

function showExtractFloorplans() {
  document.getElementById('mainMenu').classList.remove('open');
  _extractState = { esxPath: '', outDir: '', floors: [] };
  document.getElementById('extractSourceLabel').innerHTML = '<span class="org-root-hint">Click Browse… to select an <code>.esx</code></span>';
  document.getElementById('extractOutLabel').innerHTML = '<span class="org-root-hint">Auto — floorplans/ next to the .esx</span>';
  document.getElementById('extractFloorList').innerHTML = '<div class="org-extract-empty">Pick an <code>.esx</code> to list its floors.</div>';
  document.getElementById('extractBtn').disabled = true;
  document.getElementById('extractModal').classList.add('active');
}

async function pickExtractSource() {
  const r = await api('pick_esx_file');
  if (!r.ok) { if (r.error !== 'No file selected') toast(r.error, 'error'); return; }
  _extractState.esxPath = r.path;
  const srcEl = document.getElementById('extractSourceLabel');
  srcEl.textContent = r.path;
  srcEl.title = r.path;

  const list = document.getElementById('extractFloorList');
  list.innerHTML = '<div class="org-loading"><div class="big-spin"></div><div class="org-loading-msg">Reading floorplans…</div></div>';
  const rr = await api('list_floorplans', { path: r.path });
  if (!rr.ok) {
    list.innerHTML = `<div class="org-extract-empty">${esc(rr.error || 'Could not read .esx')}</div>`;
    document.getElementById('extractBtn').disabled = true;
    return;
  }
  _extractState.floors = rr.floors || [];
  _extractState.outDir = rr.default_output || '';
  const outEl = document.getElementById('extractOutLabel');
  outEl.textContent = _extractState.outDir;
  outEl.title = _extractState.outDir;
  _renderExtractFloors();
}

async function pickExtractOutput() {
  const seed = _extractState.outDir || (_extractState.esxPath ? _extractState.esxPath : '');
  const r = await api('pick_output_folder', { default: seed });
  if (!r.ok) { if (r.error !== 'No folder selected') toast(r.error, 'error'); return; }
  _extractState.outDir = r.path;
  const outEl = document.getElementById('extractOutLabel');
  outEl.textContent = r.path;
  outEl.title = r.path;
}

function _sanitizeExtractStem(s) {
  return (s || '').replace(/[<>:"/\\|?*\x00-\x1f]/g, '-').trim().replace(/\.+$/, '');
}

function _extFor(f) {
  const map = { png: '.png', jpeg: '.jpg', gif: '.gif', webp: '.webp', bmp: '.bmp', tiff: '.tif' };
  return map[f.format] || '.png';
}

function _renderExtractFloors() {
  const list = document.getElementById('extractFloorList');
  const floors = _extractState.floors;
  if (!floors.length) {
    list.innerHTML = '<div class="org-extract-empty">No floorplans found in this .esx.</div>';
    document.getElementById('extractBtn').disabled = true;
    return;
  }
  list.innerHTML = floors.map((f, i) => {
    const disabled = !f.available;
    const meta = [];
    if (f.width && f.height) meta.push(`${f.width}×${f.height}`);
    if (f.size_h) meta.push(f.size_h);
    if (!f.available) meta.push('image missing');
    const defaultStem = _sanitizeExtractStem(f.name) || `floor-${i + 1}`;
    return `<div class="org-extract-row${disabled ? ' is-disabled' : ''}">
      <label class="org-extract-cb-wrap"><input type="checkbox" class="org-extract-cb" data-idx="${i}" ${disabled ? 'disabled' : 'checked'}></label>
      <input type="text" class="org-extract-filename" data-idx="${i}" value="${escAttr(defaultStem)}" ${disabled ? 'disabled' : ''} spellcheck="false" title="Filename (extension is added automatically)">
      <span class="org-extract-ext" title="Detected from image bytes">${esc(_extFor(f))}</span>
      <span class="org-extract-meta">${esc(meta.join(' · '))}</span>
    </div>`;
  }).join('');
  document.getElementById('extractBtn').disabled = !floors.some(f => f.available);
}

function toggleExtractAll(checked) {
  document.querySelectorAll('#extractFloorList .org-extract-cb:not(:disabled)').forEach(cb => cb.checked = checked);
}

async function doExtract() {
  if (!_extractState.esxPath) { toast('Pick an .esx first', 'error'); return; }
  const selections = [];
  document.querySelectorAll('#extractFloorList .org-extract-cb:checked').forEach(cb => {
    const idx = parseInt(cb.dataset.idx, 10);
    const f = _extractState.floors[idx];
    if (!f || !f.id) return;
    const input = document.querySelector(`#extractFloorList .org-extract-filename[data-idx="${idx}"]`);
    const custom = input ? _sanitizeExtractStem(input.value) : '';
    selections.push({ id: f.id, name: custom || f.name });
  });
  if (!selections.length) { toast('Check at least one floor', 'error'); return; }

  const btn = document.getElementById('extractBtn');
  btn.disabled = true;
  const originalLabel = btn.textContent;
  btn.textContent = 'Extracting…';
  const r = await api('extract_floorplans', {
    path: _extractState.esxPath,
    selections,
    out_dir: _extractState.outDir || null,
  });
  btn.textContent = originalLabel;
  btn.disabled = false;
  if (!r.ok) { toast(r.error, 'error'); return; }

  closeModal('extractModal');
  const parts = [`Extracted ${r.written_count} floorplan${r.written_count !== 1 ? 's' : ''} → ${r.out_dir}`];
  if (r.error_count) parts.push(`${r.error_count} error${r.error_count !== 1 ? 's' : ''}`);
  parts.push(r.acorn_path ? 'saved Acorn.txt' : 'Acorn.txt not saved');
  toast(parts.join(' · '));
}


let _acornState = { esxPath: '' };

function showAcornNotes() {
  document.getElementById('mainMenu').classList.remove('open');
  _acornState = { esxPath: '' };
  document.getElementById('acornSourceLabel').innerHTML = '<span class="org-root-hint">Click Browse… to select an <code>.esx</code></span>';
  document.getElementById('acornFloorList').innerHTML = '<div class="org-extract-empty">Pick an <code>.esx</code> to list its floors.</div>';
  document.getElementById('acornBtn').disabled = true;
  document.getElementById('acornModal').classList.add('active');
}

async function pickAcornSource() {
  const r = await api('pick_esx_file');
  if (!r.ok) { if (r.error !== 'No file selected') toast(r.error, 'error'); return; }
  _acornState.esxPath = r.path;
  const srcEl = document.getElementById('acornSourceLabel');
  srcEl.textContent = r.path;
  srcEl.title = r.path;

  const list = document.getElementById('acornFloorList');
  list.innerHTML = '<div class="org-loading"><div class="big-spin"></div><div class="org-loading-msg">Reading floorplans…</div></div>';
  const rr = await api('list_floorplans', { path: r.path });
  if (!rr.ok) {
    list.innerHTML = `<div class="org-extract-empty">${esc(rr.error || 'Could not read .esx')}</div>`;
    document.getElementById('acornBtn').disabled = true;
    return;
  }
  const floors = rr.floors || [];
  if (!floors.length) {
    list.innerHTML = '<div class="org-extract-empty">No floorplans found in this .esx.</div>';
  } else {
    list.innerHTML = floors.map((f, i) =>
      `<div class="org-acorn-floor-row"><span class="org-acorn-floor-idx">${i + 1}.</span> ${esc(f.name)}</div>`
    ).join('');
  }
  document.getElementById('acornBtn').disabled = false;
}

async function doSaveAcorn() {
  if (!_acornState.esxPath) { toast('Pick an .esx first', 'error'); return; }
  const btn = document.getElementById('acornBtn');
  btn.disabled = true;
  const originalLabel = btn.textContent;
  btn.textContent = 'Saving…';
  const r = await api('save_esx_info', { path: _acornState.esxPath });
  btn.textContent = originalLabel;
  btn.disabled = false;
  if (!r.ok) { toast(r.error, 'error'); return; }
  closeModal('acornModal');
  toast(`Saved Acorn.txt — ${r.floor_count} floor plan${r.floor_count !== 1 ? 's' : ''} → ${r.path}`);
}


// ── Unified Rename ──────────────────────────────────────────────

let _renameState = { root: '', tab: 'folders', items: [], csvLoaded: false, tokens: [], csvHeaders: [], csvRows: [], csvText: '' };
let _renamePreviewTimer = null;

function renameApi(action, body) {
  return fetch('/api/rename/' + action, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
    body: JSON.stringify(body || {}),
  }).then(r => r.json());
}

async function showRename() {
  document.getElementById('mainMenu').classList.remove('open');
  _renameState = { root: '', tab: 'folders', items: [], csvLoaded: false, tokens: [], csvHeaders: [], csvRows: [], csvText: '' };
  document.getElementById('renameRootLabel').innerHTML = '<span class="org-root-hint">Click Browse… to pick a folder</span>';
  document.getElementById('renamePreviewList').innerHTML = '<div class="org-extract-empty">Pick a folder above to preview.</div>';
  document.getElementById('renamePreviewCount').textContent = '';
  document.getElementById('renameApplyBtn').disabled = true;
  document.getElementById('renameUndoBtn').hidden = true;
  document.getElementById('renameCsvStatus').hidden = true;
  document.getElementById('rnFolderManualFields').hidden = true;

  const r = await api('get_config');
  const rn = (r.ok && r.config.rename) || {};
  document.getElementById('brCase').value = rn.case || '';
  document.getElementById('brSeparator').value = rn.separator || '';
  document.getElementById('brStripPrefix').value = rn.strip_prefix || '';
  document.getElementById('brStripSuffix').value = rn.strip_suffix || '';
  document.getElementById('brRegexFrom').value = rn.regex_from || '';
  document.getElementById('brRegexTo').value = rn.regex_to || '';
  document.getElementById('brPrefix').value = rn.prefix || '';
  document.getElementById('brSuffix').value = rn.suffix || '';

  const settings = await fetch('/api/settings/get', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
    body: '{}',
  }).then(r => r.json());
  const rnSettings = (settings.ok && settings.settings && settings.settings.rename) || {};
  document.getElementById('rnFolderFormat').value = rnSettings.folder_format || '';
  document.getElementById('rnFolderSep').value = rnSettings.separator || ' - ';
  document.getElementById('rnFileFormat').value = rnSettings.file_format || '';
  document.getElementById('rnFileSep').value = rnSettings.separator || ' - ';

  const dir = await renameApi('get_directory');
  _renameState.csvLoaded = !!dir.loaded;
  if (dir.loaded) {
    const status = document.getElementById('renameCsvStatus');
    status.textContent = `CSV loaded: ${dir.site_count || 0} sites`;
    status.hidden = false;
  }

  const tokR = await renameApi('get_tokens');
  _renameState.tokens = tokR.tokens || [];
  _renderTokenBars();
  _updateRenameExample();

  switchRenameTab('folders');
  document.getElementById('renameModal').classList.add('active');
}

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
      tokens.map(t => `<button class="sr-token-btn" onclick="_renameInsertFormatToken('${inputId}','${esc(t.key)}')">{${esc(t.key)}}</button>`).join(' ');
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
    tokens.map(t => `<div class="org-token-row"><label class="org-token-label">{${esc(t)}}</label><input type="text" class="org-folder-input rn-manual-input" data-token="${esc(t)}" oninput="updateRenamePreview()" placeholder="${esc(t)}"></div>`).join('');
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

async function pickRenameRoot() {
  const r = await renameApi('pick_folder');
  if (!r.path) return;
  _renameState.root = r.path;
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
      list.innerHTML = '<div class="org-extract-empty">Enter a folder format above to preview.</div>';
      document.getElementById('renamePreviewCount').textContent = '';
      document.getElementById('renameApplyBtn').disabled = true;
      return;
    }
    const sep = document.getElementById('rnFolderSep').value;
    const body = { root: _renameState.root, format: fmt, separator: sep };
    if (!_renameState.csvLoaded) {
      body.manual_values = _getManualValues();
    }
    r = await renameApi('preview_folder_rename', body);
  } else if (tab === 'files') {
    const fmt = document.getElementById('rnFileFormat').value.trim();
    if (!fmt) {
      list.innerHTML = '<div class="org-extract-empty">Enter a file format above to preview.</div>';
      document.getElementById('renamePreviewCount').textContent = '';
      document.getElementById('renameApplyBtn').disabled = true;
      return;
    }
    r = await renameApi('preview_file_rename', {
      root: _renameState.root,
      format: fmt,
      separator: document.getElementById('rnFileSep').value,
    });
  } else {
    r = await renameApi('preview_bulk_rename', {
      root: _renameState.root,
      rules: _getRuleValues(),
    });
  }

  if (!r.ok && r.error) {
    list.innerHTML = `<div class="org-extract-empty">${esc(r.error)}</div>`;
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
  countEl.textContent = items.length ? `(${items.length})` : '';
  document.getElementById('renameApplyBtn').disabled = items.length === 0;
  if (!items.length) {
    list.innerHTML = '<div class="org-extract-empty">No files change with the current rules.</div>';
    return;
  }
  list.innerHTML = items.map(it => `
    <div class="org-rename-row">
      <span class="org-rename-site">${esc(it.site)}</span>
      <span class="org-rename-old">${esc(it.old_name)}</span>
      <span class="org-rename-arrow">&#8594;</span>
      <span class="org-rename-new">${esc(it.new_name)}</span>
    </div>`).join('');
}

function _renderTokenPreview(tab) {
  const items = _renameState.items;
  const list = document.getElementById('renamePreviewList');
  const countEl = document.getElementById('renamePreviewCount');
  const renameCount = items.filter(x => x.status === 'rename').length;
  const correctCount = items.filter(x => x.status === 'already_correct').length;
  const unmatchedCount = items.filter(x => x.status === 'unmatched').length;
  const parts = [];
  if (renameCount) parts.push(`${renameCount} to rename`);
  if (correctCount) parts.push(`${correctCount} already correct`);
  if (unmatchedCount) parts.push(`${unmatchedCount} unmatched`);
  countEl.textContent = parts.length ? `(${parts.join(', ')})` : '';
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
    return `<div class="org-rename-row ${statusClass}">
      <span class="org-rename-old">${current}</span>
      <span class="org-rename-arrow">&#8594;</span>
      <span class="org-rename-new">${it.new_name ? esc(it.new_name) : '—'}</span>
      ${it.warnings && it.warnings.length ? `<span class="org-rename-warn">${esc(it.warnings.join('; '))}</span>` : ''}
    </div>`;
  }).join('');
}

async function doRename() {
  const tab = _renameState.tab;
  const btn = document.getElementById('renameApplyBtn');
  btn.disabled = true;
  const originalLabel = btn.textContent;
  btn.textContent = 'Renaming…';
  let r;

  if (tab === 'rules') {
    const rn = _getRuleValues();
    await api('set_config', { config: { rename: rn } });
    r = await renameApi('execute_bulk_rename', { items: _renameState.items });
  } else {
    const renames = _renameState.items.filter(x => x.status === 'rename');
    if (!renames.length) { btn.textContent = originalLabel; btn.disabled = false; return; }
    const action = tab === 'folders' ? 'execute_folder_rename' : 'execute_file_rename';
    r = await renameApi(action, { root: _renameState.root, renames });
  }

  btn.textContent = originalLabel;
  if (!r.ok) { toast(r.error, 'error'); btn.disabled = false; return; }

  const parts = [`Renamed ${r.renamed} item${r.renamed !== 1 ? 's' : ''}`];
  if (r.skipped) parts.push(`${r.skipped} skipped`);
  if (r.errors && r.errors.length) parts.push(`${r.errors.length} error${r.errors.length !== 1 ? 's' : ''}`);
  toast(parts.join(' · '));
  document.getElementById('renameUndoBtn').hidden = false;

  await _runRenamePreview();
  if (currentRoot) doScan();
}

async function renameUndo() {
  const type = _renameState.tab === 'folders' ? 'folders' : 'files';
  const r = await renameApi('undo_last', { type });
  if (r.error) { toast(r.error, 'error'); return; }
  toast(`Reverted ${r.reverted || 0} item${(r.reverted || 0) !== 1 ? 's' : ''}`);
  document.getElementById('renameUndoBtn').hidden = true;
  await _runRenamePreview();
}

// ── Rename CSV sub-modal ──

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

function _handleRenameCsvFile(file) {
  const reader = new FileReader();
  reader.onload = e => {
    _renameState.csvText = e.target.result;
    const lines = _renameState.csvText.split(/\r?\n/).filter(l => l.trim());
    if (!lines.length) return;
    const headers = lines[0].split(',').map(h => h.trim().replace(/^"|"$/g, ''));
    _renameState.csvHeaders = headers;
    _renameState.csvRows = [];
    for (let i = 1; i < lines.length; i++) {
      const vals = lines[i].split(',');
      const row = {};
      headers.forEach((h, j) => { row[h] = (vals[j] || '').trim().replace(/^"|"$/g, ''); });
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
  if (rows.length > 8) html += `<tr><td colspan="${headers.length}" class="table-ellipsis">… ${rows.length - 8} more rows</td></tr>`;
  html += '</tbody></table>';
  document.getElementById('renameCsvPreviewWrap').innerHTML = html;

  ['rnMapPrimary', 'rnMapAddress', 'rnMapDeprecated'].forEach(id => {
    const sel = document.getElementById(id);
    sel.innerHTML = id === 'rnMapPrimary' ? '' : '<option value="">(none)</option>';
    headers.forEach(h => { sel.innerHTML += `<option value="${esc(h)}">${esc(h)}</option>`; });
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
  status.textContent = `CSV loaded: ${r.site_count || 0} sites`;
  status.hidden = false;

  const tokR = await renameApi('get_tokens');
  _renameState.tokens = tokR.tokens || [];
  _renderTokenBars();
  _renderManualFields();

  closeModal('renameCsvModal');
  toast(`Loaded ${r.site_count} sites with ${(r.tokens || []).length} token columns`);
  if (_renameState.root) updateRenamePreview();
}

// ── Rename Gap Report ──

async function showRenameGapReport() {
  if (!_renameState.root) { toast('Select a folder first', 'error'); return; }
  document.getElementById('renameGapBody').innerHTML = '<div class="big-spin"></div>';
  document.getElementById('renameGapModal').classList.add('active');

  const r = await renameApi('gap_report', { root: _renameState.root });
  if (r.error) { document.getElementById('renameGapBody').innerHTML = `<p>${esc(r.error)}</p>`; return; }

  let html = '';
  html += `<h3>Has Project Data (${r.has_data.length})</h3>`;
  if (r.has_data.length) {
    html += '<ul>' + r.has_data.map(d => `<li><strong>${esc(d.folder)}</strong> — ${d.file_count} files, ${d.project_files.length} .esx</li>`).join('') + '</ul>';
  } else html += '<p class="sr-hint">None</p>';

  html += `<h3>Empty Folders (${r.empty.length})</h3>`;
  if (r.empty.length) html += '<ul>' + r.empty.map(d => `<li>${esc(d.folder)}</li>`).join('') + '</ul>';
  else html += '<p class="sr-hint">None</p>';

  html += `<h3>Sites Not Started (${r.not_started.length})</h3>`;
  if (r.not_started.length) html += '<ul>' + r.not_started.map(d => `<li>${esc(d.site_id)}</li>`).join('') + '</ul>';
  else html += '<p class="sr-hint">None</p>';

  html += `<h3>Orphan Folders (${r.orphans.length})</h3>`;
  if (r.orphans.length) html += '<ul>' + r.orphans.map(d => `<li>${esc(d.folder)} — ${d.file_count} files</li>`).join('') + '</ul>';
  else html += '<p class="sr-hint">None</p>';

  document.getElementById('renameGapBody').innerHTML = html;
}

// ── Rename Profiles ──

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
    return `<div class="sr-profile-item">
      <div class="sr-profile-name">${esc(name)}</div>
      <div class="sr-profile-detail">Folder: <code>${esc(p.folder_format || '')}</code> · File: <code>${esc(p.file_format || '')}</code> · Sep: <code>${esc(p.separator || '')}</code></div>
      <div class="sr-profile-actions">
        <button class="btn btn-sm" onclick="applyRenameProfile(${JSON.stringify(name).replace(/"/g, '&quot;')})">Apply</button>
        <button class="btn btn-sm btn-danger" onclick="deleteRenameProfile(${JSON.stringify(name).replace(/"/g, '&quot;')})">Delete</button>
      </div></div>`;
  }).join('');
}

async function doSaveRenameProfile() {
  const name = document.getElementById('renameProfileNameInput').value.trim();
  if (!name) { toast('Enter a profile name', 'error'); return; }
  await renameApi('save_profile', {
    name,
    folder_format: document.getElementById('rnFolderFormat').value,
    file_format: document.getElementById('rnFileFormat').value,
    separator: document.getElementById('rnFolderSep').value,
    file_rules: _getRuleValues(),
  });
  document.getElementById('renameProfileNameInput').value = '';
  toast(`Profile "${name}" saved`);
  showRenameProfiles();
}

async function applyRenameProfile(name) {
  const r = await renameApi('list_profiles');
  const p = (r.profiles || {})[name];
  if (!p) return;
  document.getElementById('rnFolderFormat').value = p.folder_format || '';
  document.getElementById('rnFileFormat').value = p.file_format || '';
  document.getElementById('rnFolderSep').value = p.separator || ' - ';
  document.getElementById('rnFileSep').value = p.separator || ' - ';
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
  toast(`Applied profile "${name}"`);
  _renderManualFields();
  if (_renameState.root) updateRenamePreview();
}

async function deleteRenameProfile(name) {
  if (!confirm(`Delete profile "${name}"?`)) return;
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
  toast(`Generated CSV with ${r.folder_count} folder${r.folder_count !== 1 ? 's' : ''}`);
}

function copyCsvHelper() {
  const el = document.getElementById('csvHelperOutput');
  navigator.clipboard.writeText(el.value).then(() => toast('Copied to clipboard'));
}

// backward compat — old showBulkRename calls
function showBulkRename() { showRename(); }

function fmtSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}
