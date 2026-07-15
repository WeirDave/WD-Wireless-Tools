/* WD Squirrel (Folder Organizer) — page logic */

/* ── State ── */
let scanData = null;
let currentRoot = null;

/* ── API helper ── */
async function api(action, body = {}) {
  const resp = await fetch('/api/organizer/' + action, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return resp.json();
}

/* ── Hamburger menu ── */
document.getElementById('menuBtn').addEventListener('click', (e) => {
  e.stopPropagation();
  document.getElementById('mainMenu').classList.toggle('open');
});
document.addEventListener('click', () => document.getElementById('mainMenu').classList.remove('open'));

/* ── Screens ── */
function showScreen(id) {
  ['pickScreen', 'previewScreen', 'execScreen', 'resultScreen'].forEach(s =>
    document.getElementById(s).style.display = s === id ? '' : 'none'
  );
}

/* ── Pick Folder ── */
async function pickFolder() {
  document.getElementById('mainMenu').classList.remove('open');
  const r = await api('pick_folder');
  if (!r.ok) { if (r.error !== 'No folder selected') toast(r.error, 'error'); return; }
  currentRoot = r.path;
  await doScan();
}

/* ── Scan ── */
async function doScan() {
  document.getElementById('mainMenu').classList.remove('open');
  if (!currentRoot) { toast('Pick a folder first', 'error'); return; }
  showScreen('previewScreen');
  document.getElementById('rootPath').textContent = currentRoot;
  document.getElementById('siteList').innerHTML = '<div style="text-align:center;padding:40px;"><div class="big-spin"></div><div style="color:var(--text-2);margin-top:8px;">Scanning…</div></div>';
  document.getElementById('summaryBar').innerHTML = '';

  const r = await api('scan', { root: currentRoot });
  if (!r.ok) { toast(r.error, 'error'); return; }
  scanData = r;
  renderPreview();
}

/* ── Render preview ── */
function renderPreview() {
  const d = scanData;
  const t = d.totals;
  const totalMoves = t.images + t.floorplans + t.reports;

  document.getElementById('summaryBar').innerHTML = `
    <div class="summary-chip chip-sites"><span class="num">${d.site_count}</span> site folders</div>
    <div class="summary-chip chip-images"><span class="num">${t.images}</span> → \\images</div>
    <div class="summary-chip chip-plans"><span class="num">${t.floorplans}</span> → \\floorplans</div>
    <div class="summary-chip chip-reports"><span class="num">${t.reports}</span> → \\reports</div>
    <div class="summary-chip chip-staying"><span class="num">${t.skipped}</span> staying</div>
  `;

  if (d.sites.length === 0) {
    document.getElementById('siteList').innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-2);">No site folders with loose files found.</div>';
    return;
  }

  let html = '';
  for (const site of d.sites) {
    const moveCount = site.moves.length;
    const stayCount = site.staying.length;
    html += `<div class="site-group" data-site="${esc(site.folder)}">`;
    html += `<div class="site-header" onclick="this.parentElement.classList.toggle('collapsed')">`;
    html += `<div><span class="site-name">${esc(site.folder)}</span>`;
    if (moveCount) html += `<span class="site-badge">${moveCount} move${moveCount !== 1 ? 's' : ''}</span>`;
    if (stayCount) html += `<span class="site-badge">${stayCount} staying</span>`;
    html += `</div><span class="site-chevron">▾</span></div>`;

    if (site.missing_subs.length > 0 || site.existing_subs.length > 0) {
      html += '<div class="new-subs">';
      for (const sf of ['images', 'floorplans', 'reports']) {
        if (site.missing_subs.includes(sf)) html += `<span class="new-sub-badge">+ \\${sf}</span>`;
        else html += `<span class="new-sub-badge exists">\\${sf} ✓</span>`;
      }
      html += '</div>';
    }

    html += '<div class="site-body">';
    if (moveCount > 0) {
      html += '<table class="file-table"><thead><tr>';
      html += '<th class="chk"><input type="checkbox" checked onchange="toggleSite(this, \'' + esc(site.folder) + '\')"></th>';
      html += '<th>File</th><th class="col-dest">Destination</th><th class="col-size" style="text-align:right">Size</th>';
      html += '</tr></thead><tbody>';
      for (const m of site.moves) {
        const id = site.folder + '::' + m.name;
        html += `<tr>`;
        html += `<td class="chk"><input type="checkbox" checked data-site="${esc(site.folder)}" data-file="${esc(m.name)}" data-id="${esc(id)}"></td>`;
        html += `<td><span class="file-ext">${esc(m.ext)}</span>${esc(m.name)}</td>`;
        html += `<td><select class="dest-select dest-${m.target}" data-site="${esc(site.folder)}" data-file="${esc(m.name)}" data-original="${m.target}" onchange="onDestChange(this)">`;
        for (const opt of ['images', 'floorplans', 'reports']) {
          html += `<option value="${opt}"${opt === m.target ? ' selected' : ''}>\\${opt}</option>`;
        }
        html += `</select>`;
        if (m.renamed_to) html += ` <span class="renamed">(→ ${esc(m.renamed_to)})</span>`;
        html += `</td>`;
        html += `<td style="text-align:right" class="size">${fmtSize(m.size)}</td>`;
        html += '</tr>';
      }
      html += '</tbody></table>';
    }

    if (stayCount > 0) {
      html += '<table class="file-table"><thead><tr><th colspan="3" style="color:var(--text-3)">Staying in root</th></tr></thead><tbody>';
      for (const s of site.staying) {
        html += `<tr class="staying-row">`;
        html += `<td><span class="file-ext">${esc(s.ext)}</span>${esc(s.name)}</td>`;
        html += `<td><span class="staying-label ${s.reason === 'esx' ? 'staying-esx' : 'staying-unknown'}">${s.reason === 'esx' ? '.esx project' : 'unknown type'}</span></td>`;
        html += `<td style="text-align:right" class="size">${fmtSize(s.size)}</td>`;
        html += '</tr>';
      }
      html += '</tbody></table>';
    }
    html += '</div></div>';
  }
  document.getElementById('siteList').innerHTML = html;
}

/* ── Toggle helpers ── */
function toggleAll(checked) {
  document.querySelectorAll('#siteList input[type="checkbox"]').forEach(cb => cb.checked = checked);
}
function toggleSite(headerCb, siteName) {
  document.querySelectorAll(`#siteList input[data-site="${siteName}"]`).forEach(cb => cb.checked = headerCb.checked);
}
function onDestChange(sel) {
  sel.className = 'dest-select dest-' + sel.value;
  if (sel.value !== sel.dataset.original) sel.classList.add('overridden');
}

/* ── Shift-click range select ── */
let _lastChecked = null;
document.addEventListener('click', function(e) {
  const cb = e.target.closest('input[type="checkbox"][data-file]');
  if (!cb) return;
  if (e.shiftKey && _lastChecked && _lastChecked !== cb) {
    const allCbs = Array.from(document.querySelectorAll('#siteList input[data-file]'));
    const start = allCbs.indexOf(_lastChecked);
    const end = allCbs.indexOf(cb);
    const lo = Math.min(start, end), hi = Math.max(start, end);
    for (let i = lo; i <= hi; i++) {
      allCbs[i].checked = cb.checked;
    }
  }
  _lastChecked = cb;
});

/* ── Bulk destination change for checked files ── */
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

/* ── Execute ── */
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
  if (!confirm(`Move ${totalChecked} file${totalChecked !== 1 ? 's' : ''} into their subfolders?${overrideNote}\n\nThis cannot be undone from the UI.`)) return;

  showScreen('execScreen');
  const r = await api('execute', { root: currentRoot, excluded, overrides });
  if (!r.ok) { toast(r.error, 'error'); showScreen('previewScreen'); return; }
  renderResults(r);
}

/* ── Render results ── */
function renderResults(r) {
  showScreen('resultScreen');
  const t = r.totals;
  const totalMoved = t.images + t.floorplans + t.reports;
  let html = '<div class="toolbar"><button class="btn btn-sec" onclick="doScan()">← Back to Preview</button>';
  html += '<button class="btn btn-primary" onclick="pickFolder()">Organize Another Folder</button></div>';
  html += `<div class="summary-bar">
    <div class="summary-chip chip-images"><span class="num">${t.images}</span> → \\images</div>
    <div class="summary-chip chip-plans"><span class="num">${t.floorplans}</span> → \\floorplans</div>
    <div class="summary-chip chip-reports"><span class="num">${t.reports}</span> → \\reports</div>`;
  if (t.skipped) html += `<div class="summary-chip chip-staying"><span class="num">${t.skipped}</span> skipped</div>`;
  if (t.errors) html += `<div class="summary-chip" style="border-color:var(--red)"><span class="num" style="color:var(--red)">${t.errors}</span> errors</div>`;
  html += '</div>';

  if (totalMoved === 0 && t.errors === 0) {
    html += '<div style="text-align:center;padding:40px;color:var(--text-2);">Nothing to move — all files were excluded or already organized.</div>';
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
      if (m.error) html += ` <span style="color:var(--red);font-size:11px;">${esc(m.error)}</span>`;
      html += '</td></tr>';
    }
    html += '</tbody></table></div></div>';
  }
  document.getElementById('resultScreen').innerHTML = html;
  toast(`Done — ${totalMoved} file${totalMoved !== 1 ? 's' : ''} organized`);
}

/* ── Settings ── */
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
  document.getElementById('settingsModal').classList.add('active');
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
  };
  const r = await api('set_config', { config: cfg });
  if (!r.ok) { toast(r.error, 'error'); return; }
  closeModal('settingsModal');
  toast('Settings saved');
  if (currentRoot) doScan();
}
async function resetConfig() {
  if (!confirm('Reset all type mappings to defaults?')) return;
  const r = await api('reset_config');
  if (!r.ok) { toast(r.error, 'error'); return; }
  closeModal('settingsModal');
  toast('Settings reset to defaults');
  if (currentRoot) doScan();
}

/* ── About ── */
function showAbout() {
  document.getElementById('mainMenu').classList.remove('open');
  showModal('aboutModal');
}

/* ── Close modals on overlay click ── */
document.querySelectorAll('.modal-overlay').forEach(ov => {
  ov.addEventListener('click', e => { if (e.target === ov) ov.classList.remove('active'); });
});

/* ── Create Project Folder ── */
function updateCreateFolderRoot() {
  const rootNote = document.getElementById('createFolderRoot');
  const btn = document.getElementById('createFolderBtn');
  if (currentRoot) {
    rootNote.textContent = currentRoot;
    rootNote.style.color = 'var(--text-2)';
    btn.disabled = false;
    btn.style.opacity = '1';
  } else {
    rootNote.innerHTML = '<span style="color:var(--amber);">Click Browse… to select a folder</span>';
    btn.disabled = true;
    btn.style.opacity = '0.5';
  }
}
function showCreateFolder() {
  document.getElementById('mainMenu').classList.remove('open');
  document.getElementById('newFolderName').value = '';
  updateCreateFolderRoot();
  document.getElementById('createFolderModal').classList.add('active');
  if (currentRoot) {
    setTimeout(() => document.getElementById('newFolderName').focus(), 100);
  }
}
async function pickRootForCreate() {
  const r = await api('pick_folder');
  if (!r.ok) { if (r.error !== 'No folder selected') toast(r.error, 'error'); return; }
  currentRoot = r.path;
  updateCreateFolderRoot();
  setTimeout(() => document.getElementById('newFolderName').focus(), 100);
}
async function doCreateFolder() {
  const name = document.getElementById('newFolderName').value.trim();
  if (!name) { toast('Enter a folder name', 'error'); return; }
  if (!currentRoot) { toast('Select a root folder first', 'error'); return; }
  const r = await api('create_project_folder', { name, root: currentRoot });
  if (!r.ok) { toast(r.error, 'error'); return; }
  closeModal('createFolderModal');
  toast(`Created "${r.name}" with ${r.subfolders.join('/, ')}/ subfolders`);
}
document.getElementById('newFolderName').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') { e.preventDefault(); doCreateFolder(); }
});

/* ── Helpers ── */
function fmtSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}
