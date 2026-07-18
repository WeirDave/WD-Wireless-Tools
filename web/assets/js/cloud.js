/* WD Cloud Manager — page logic */

// Local short aliases for the escape helpers used heavily in template literals
function e(s) { return WD.esc(s); }
function a(s) { return WD.escAttr(s); }
// Path-safe attr escape: normalizes Windows backslashes to forward slashes so
// they survive JS string parsing inside onclick="...(...)" attributes.
// Python's pathlib accepts either separator, so this is safe end-to-end.
function p(s) { return a(String(s == null ? '' : s).replace(/\\/g, '/')); }

let currentTab = 'sites';       // 'sites' | 'projects' | 'duplicates'
let data = null;                // current tab's data
let dupData = null;             // duplicates payload (Duplicates tab)
let dupIndex = new Map();       // id-or-path → cluster key (for ≈ badges)
let dupHighlightKey = null;     // set when jumpToCluster kicks over; drives auto-scroll
let activeFilter = 'all';
let filterUnassigned = false;   // column-level "no site / no folder" toggle
let renameTarget = null;
let deleteTarget = null;
let rowData = {};               // key -> action info for every row in current data
let selected = new Set();       // keys of checked rows
let collapsed = new Set();      // collapsed folder names in the Project Files tree
let mergeState = {};            // in-progress folder→folder merge

// Browser suite: route the old pywebview-style calls to the Flask server.
const API_MAP = {
  get_status: ['status', []],
  open_ekahau_login: ['open_login', []],
  get_data: ['get_data', ['kind']],
  rename_cloud: ['rename_cloud', ['kind', 'id', 'name']],
  delete_cloud: ['delete_cloud', ['kind', 'id']],
  create_site: ['create_site', ['name']],
  create_local_folder: ['create_local_folder', ['name']],
  rename_local: ['rename_local', ['path', 'name']],
  delete_local: ['delete_local', ['path']],
  merge_preview: ['merge_preview', ['src', 'dst']],
  merge_execute: ['merge_execute', ['src', 'dst', 'ops']],
  pick_folder: ['pick_folder', []],
  upload_project: ['upload_project', ['path', 'siteId']],
  assign_to_site: ['assign_to_site', ['siteId', 'datasetId']],
  reveal_in_explorer: ['reveal_in_explorer', ['path']],
  get_duplicates: ['get_duplicates', []],
  mark_not_match: ['mark_not_match', ['cloudId', 'localPath', 'cloudName', 'localName']],
  unmark_not_match: ['unmark_not_match', ['cloudId', 'localPath']],
  list_not_matches: ['list_not_matches', []],
};
async function pyApi(method, ...args) {
  const entry = API_MAP[method];
  if (!entry) throw new Error('unknown api: ' + method);
  const [action, keys] = entry;
  const body = {};
  keys.forEach((k, i) => { body[k] = args[i]; });
  const r = await fetch('/api/cloud/' + action, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return await r.json();
}

/* ── Auth / setup ── */
function setAuthState(s) {
  document.getElementById('authChecking').style.display = s === 'checking' ? '' : 'none';
  document.getElementById('authLogin').style.display = s === 'login' ? '' : 'none';
  document.getElementById('authWaiting').style.display = s === 'waiting' ? '' : 'none';
}
async function startAuth() {
  setAuthState('checking');
  try {
    const s = await pyApi('get_status');
    if (s.connected) { showApp(s.email); return; }
  } catch (e) {}
  setAuthState('login');
}
async function openEkahauLogin() {
  setAuthState('waiting');
  await pyApi('open_ekahau_login');
  const iv = setInterval(async () => {
    try {
      const s = await pyApi('get_status');
      if (s.connected) { clearInterval(iv); showApp(s.email); }
    } catch (e) {}
  }, 3000);
}

async function showApp(email) {
  const status = await pyApi('get_status');
  if (!status.outputDir) {
    document.getElementById('loginScreen').style.display = 'none';
    document.getElementById('setupScreen').style.display = 'block';
    document.getElementById('setupEmail').textContent = email || '';
    return;
  }
  goToDashboard(email);
}
function goToDashboard(email) {
  document.getElementById('loginScreen').style.display = 'none';
  document.getElementById('setupScreen').style.display = 'none';
  document.getElementById('appScreen').style.display = 'flex';
  document.getElementById('userEmail').textContent = email || 'Connected';
  syncOwnerToggle();
  // Ensure the owner filter's initial visibility matches currentTab
  // (starts on 'sites' — the toggle should be hidden until Projects).
  const ownerEl = document.getElementById('ownerToggle');
  if (ownerEl) ownerEl.style.display = (currentTab === 'projects') ? '' : 'none';
  refreshData();
  if (liveWanted()) startLive();
}

/* ── Live auto-refresh with countdown ── */
function liveMs() { try { return parseInt(localStorage.getItem('wd-live-ms')) || 30000; } catch (e) { return 30000; } }
let liveTimer = null;
let liveCountdown = 0;
// Live is default-ON. A user who explicitly toggled it off has 'off' stored;
// anything else (never set, or 'on') → on. Multi-user cloud environments
// mean stale data is worse than a periodic refetch — hence default-on.
function liveWanted() { try { return localStorage.getItem('wd-live') !== 'off'; } catch (e) { return true; } }
function applyLiveUI() {
  const b = document.getElementById('liveBtn');
  if (!b) return;
  const on = liveTimer !== null;
  if (on) {
    b.textContent = `Live ● ${liveCountdown}s`;
  } else {
    b.textContent = 'Live';
  }
  b.classList.toggle('live-on', on);
}
function startLive() {
  if (!liveTimer) {
    liveCountdown = liveMs() / 1000;
    liveTimer = setInterval(liveTick, 1000);
  }
  applyLiveUI();
}
function stopLive() { if (liveTimer) { clearInterval(liveTimer); liveTimer = null; } applyLiveUI(); }
function restartLive() { if (liveTimer) { stopLive(); startLive(); } }
function toggleLive() {
  if (liveTimer) {
    stopLive(); try { localStorage.setItem('wd-live', 'off'); } catch (e) {}
  } else {
    startLive(); try { localStorage.setItem('wd-live', 'on'); } catch (e) {}
    toast(`Live on — re-pulls from Ekahau Cloud every ${liveMs()/1000}s while idle`, 'info');
  }
}
function liveBusy() {
  if (document.querySelector('.modal-overlay.active')) return true;
  if (selected.size > 0) return true;
  const sb = document.getElementById('searchBox');
  if (sb && document.activeElement === sb && sb.value) return true;
  return false;
}
function liveTick() {
  liveCountdown--;
  if (liveCountdown <= 0) {
    liveCountdown = liveMs() / 1000;
    if (!liveBusy()) refreshData(true);
  }
  applyLiveUI();
}
async function setupPickFolder() {
  try {
    const r = await pyApi('pick_folder');
    if (r.path) {
      document.getElementById('setupFolderPath').textContent = r.path;
      document.getElementById('setupFolderPath').style.display = '';
      document.getElementById('setupContinueBtn').style.display = '';
    }
  } catch (err) { toast(err.message, 'error'); }
}
async function setupContinue() { const s = await pyApi('get_status'); goToDashboard(s.email); }
function setupSkip() { goToDashboard(document.getElementById('setupEmail').textContent); }

/* ── Tabs ── */
function switchTab(kind) {
  if (kind === currentTab) return;
  currentTab = kind;
  document.getElementById('tabSites').classList.toggle('active', kind === 'sites');
  document.getElementById('tabProjects').classList.toggle('active', kind === 'projects');
  document.getElementById('tabDuplicates').classList.toggle('active', kind === 'duplicates');
  document.getElementById('addNewBtn').style.display = kind === 'sites' ? '' : 'none';
  const ownerEl = document.getElementById('ownerToggle');
  if (ownerEl) ownerEl.style.display = (kind === 'projects') ? '' : 'none';
  // Toolbar-centered "Delete all N extras" only makes sense on Duplicates.
  const dupTbBtn = document.getElementById('dupDeleteAllToolbarBtn');
  if (dupTbBtn && kind !== 'duplicates') dupTbBtn.style.display = 'none';
  document.querySelectorAll('.dash-card').forEach(c => c.classList.toggle('active', c.dataset.filter === activeFilter));
  refreshData();
}

/* ── Data ── */
function refreshData(silent) {
  if (!silent) {
    clearSelection();
    document.getElementById('rowsContainer').innerHTML = '<div class="empty-msg">Loading…</div>';
  }
  const tab = currentTab;
  if (tab === 'duplicates') {
    pyApi('get_duplicates')
      .then(d => onDuplicates(tab, JSON.stringify(d)))
      .catch(err => { if (!silent) toast('Load failed: ' + err.message, 'error'); });
  } else {
    pyApi('get_data', tab)
      .then(d => onData(tab, JSON.stringify(d)))
      .catch(err => { if (!silent) toast('Load failed: ' + err.message, 'error'); });
    // In parallel, fetch duplicates data for the ≈ badge cross-reference.
    refreshDupIndex();
  }
}

function onData(kind, jsonStr) {
  if (kind !== currentTab) return;
  try {
    data = JSON.parse(jsonStr);
  } catch (err) { toast('Bad data payload', 'error'); return; }
  if (data.error) {
    document.getElementById('rowsContainer').innerHTML = '<div class="empty-msg">' + e(data.error) + '</div>';
    toast(data.error, 'error'); return;
  }
  indexRowData();
  updateDashboard(); renderRows();
}

function onDuplicates(kind, jsonStr) {
  if (kind !== currentTab) return;
  let d;
  try { d = JSON.parse(jsonStr); }
  catch (err) { toast('Bad data payload', 'error'); return; }
  if (d.error) {
    document.getElementById('rowsContainer').innerHTML = '<div class="empty-msg">' + e(d.error) + '</div>';
    toast(d.error, 'error'); return;
  }
  dupData = d;
  // Also refresh the shared dupIndex (used by ≈ badges on other tabs).
  buildDupIndexFromData(d);
  updateDashboard();
  renderDuplicates();
}

function indexRowData() {
  rowData = {};
  (data.matched || []).forEach(p => {
    rowData['p:' + p.cloud.id] = { kind: 'pair', cloudId: p.cloud.id, cloudName: p.cloud.name, localName: p.local.name, localPath: p.local.path, mismatch: p.namesDiffer };
  });
  (data.cloudOnly || []).forEach(s => { rowData['c:' + s.id] = { kind: 'cloud', id: s.id, name: s.name }; });
  (data.localOnly || []).forEach(f => { rowData['l:' + f.path] = { kind: 'local', path: f.path, name: f.name, isDir: f.isDir }; });
}
function updateDashboard() {
  const isDup = currentTab === 'duplicates';
  const isProj = currentTab === 'projects';
  // Standard match/orphan cards visible only on Sites/Projects tabs.
  const stdCards = ['allcard', 'mismatches', 'orphans', 'cloud-only', 'local-only', 'matched'];
  stdCards.forEach(cls => {
    document.querySelectorAll('.dash-card.' + cls).forEach(el => {
      el.style.display = isDup ? 'none' : '';
    });
  });
  // Duplicate cards visible only on Duplicates tab.
  ['dDupAllCard', 'dDupMixedCard', 'dDupLocalCard', 'dDupCloudCard'].forEach(id => {
    document.getElementById(id).style.display = isDup ? '' : 'none';
  });

  if (isDup) {
    const s = (dupData && dupData.summary) || { total: 0, mixed: 0, localOnly: 0, cloudOnly: 0 };
    document.getElementById('dDupAll').textContent = s.total;
    document.getElementById('dDupMixed').textContent = s.mixed;
    document.getElementById('dDupLocal').textContent = s.localOnly;
    document.getElementById('dDupCloud').textContent = s.cloudOnly;
  } else if (data && data.summary) {
    const s = data.summary;
    document.getElementById('dAll').textContent = s.matched + s.cloudOnly + s.localOnly;
    document.getElementById('dMismatches').textContent = s.mismatches;
    document.getElementById('dOrphans').textContent = s.cloudOnly + s.localOnly;
    document.getElementById('dCloudOnly').textContent = s.cloudOnly;
    document.getElementById('dLocalOnly').textContent = s.localOnly;
    document.getElementById('dSynced').textContent = s.matched - s.mismatches;
  }

  const uCard = document.getElementById('dUnassignedCard');
  uCard.style.display = isProj ? '' : 'none';
  if (isProj && data) {
    let noSite = 0;
    (data.matched || []).forEach(p => { if (p.cloud && !p.cloud.hasSite) noSite++; });
    (data.cloudOnly || []).forEach(c => { if (!c.hasSite) noSite++; });
    document.getElementById('dUnassigned').textContent = noSite;
  }
  if (!isProj && activeFilter === 'unassigned') { activeFilter = 'all'; }
  document.querySelectorAll('.dash-card').forEach(c => c.classList.toggle('active', c.dataset.filter === activeFilter));
}
function setFilter(f) {
  activeFilter = activeFilter === f ? 'all' : f;
  document.querySelectorAll('.dash-card').forEach(c => c.classList.toggle('active', c.dataset.filter === activeFilter));
  renderRows();
}

/* ── Character-level diff ── */
function charDiff(a, b) {
  if (a === b) return { a: e(a), b: e(b) };
  if (!a) return { a: '', b: '<mark>' + e(b) + '</mark>' };
  if (!b) return { a: '<mark>' + e(a) + '</mark>', b: '' };
  const m = a.length, n = b.length, dp = [];
  for (let i = 0; i <= m; i++) dp[i] = new Uint16Array(n + 1);
  for (let i = 1; i <= m; i++) for (let j = 1; j <= n; j++)
    dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1] + 1 : Math.max(dp[i-1][j], dp[i][j-1]);
  const aK = new Uint8Array(m), bK = new Uint8Array(n);
  let i = m, j = n;
  while (i > 0 && j > 0) {
    if (a[i-1] === b[j-1]) { aK[i-1] = 1; bK[j-1] = 1; i--; j--; }
    else if (dp[i-1][j] >= dp[i][j-1]) i--; else j--;
  }
  const toH = (s, k) => {
    let o = '', d = false;
    for (let x = 0; x < s.length; x++) {
      if (!k[x] && !d) { o += '<mark>'; d = true; }
      if (k[x] && d) { o += '</mark>'; d = false; }
      const c = s[x]; o += c === '<' ? '&lt;' : c === '>' ? '&gt;' : c === '&' ? '&amp;' : c;
    }
    if (d) o += '</mark>'; return o;
  };
  return { a: toH(a, aK), b: toH(b, bK) };
}

/* ── Render ── */
function renderRows() {
  if (currentTab === 'duplicates') { renderDuplicates(); return; }
  lastChkIndex = null;
  const el = document.getElementById('rowsContainer');
  const q = document.getElementById('searchBox').value.toLowerCase();
  const hit = n => !q || (n || '').toLowerCase().includes(q);

  const legend = document.querySelector('.col-legend');
  if (legend) legend.style.display = 'none';
  el.innerHTML = renderLedger(hit);
  updateBulkBar(); refreshSelAll();
}

/* ── Duplicates: index (for ≈ badges on Sites/Projects) ── */
function refreshDupIndex() {
  // Fire-and-forget parallel fetch. Populates dupIndex so cell renderers can
  // stamp a ≈ hint on any row that appears in a duplicate cluster.
  pyApi('get_duplicates')
    .then(d => {
      if (!d || d.error) return;
      buildDupIndexFromData(d);
      // Re-render the current ledger so newly-known badges appear.
      if (currentTab !== 'duplicates') renderRows();
    })
    .catch(() => {});
}

function buildDupIndexFromData(d) {
  dupIndex = new Map();
  (d.clusters || []).forEach(cl => {
    cl.items.forEach(item => {
      const k = item.id || item.path;
      if (k) dupIndex.set(k, cl.key);
    });
  });
}

function dupHintFor(idOrPath) {
  if (!idOrPath) return '';
  const key = dupIndex.get(idOrPath);
  if (!key) return '';
  return ` <span class="dup-hint" title="Part of a duplicate cluster — click to inspect" onclick="event.stopPropagation();jumpToCluster('${a(key)}')">&#8776;</span>`;
}

function jumpToCluster(clusterKey) {
  dupHighlightKey = clusterKey;
  if (currentTab === 'duplicates') {
    // Already here — just scroll + pulse.
    scrollToCluster(clusterKey);
  } else {
    switchTab('duplicates');
    // renderDuplicates() will honor dupHighlightKey after data loads.
  }
}

function scrollToCluster(key) {
  const el = document.querySelector(`.dup-cluster[data-key="${cssEscape(key)}"]`);
  if (!el) return;
  el.classList.add('expanded');
  el.classList.add('dup-highlight');
  el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  setTimeout(() => el.classList.remove('dup-highlight'), 1500);
}
function cssEscape(s) {
  return String(s).replace(/["\\]/g, '\\$&');
}

/* ── Duplicates: render ── */
function renderDuplicates() {
  const el = document.getElementById('rowsContainer');
  const legend = document.querySelector('.col-legend');
  if (legend) legend.style.display = 'none';

  const clusters = (dupData && dupData.clusters) || [];
  // Apply active filter (dup-mixed / dup-local / dup-cloud / dup-all/all).
  let filtered = clusters;
  if (activeFilter === 'dup-mixed')      filtered = clusters.filter(c => c.shape === 'mixed');
  else if (activeFilter === 'dup-local') filtered = clusters.filter(c => c.shape === 'local-only');
  else if (activeFilter === 'dup-cloud') filtered = clusters.filter(c => c.shape === 'cloud-only');

  // Apply search box (matches any item name in the cluster).
  const q = (document.getElementById('searchBox').value || '').toLowerCase();
  if (q) {
    filtered = filtered.filter(c => c.items.some(i => (i.name || '').toLowerCase().includes(q))
                                  || (c.key || '').includes(q));
  }

  if (!filtered.length) {
    el.innerHTML = `<div class="dup-empty">
      <div class="dup-empty-icon">&#128193;</div>
      <div class="dup-empty-title">${clusters.length ? 'No duplicates match this filter' : 'No duplicates found'}</div>
      <div class="dup-empty-sub">${clusters.length
        ? 'Clear the search or pick a different filter to see other clusters.'
        : 'Every project has a unique normalized name across the cloud and your local folder. Nice.'}</div>
    </div>`;
    return;
  }

  // Count all unmatched extras across all currently-filtered clusters so the
  // toolbar-centered "Delete all N extras" button can label its count.
  const totalExtras = filtered.reduce(
    (n, cl) => n + cl.items.filter(i => !i.matched).length, 0);
  const tbBtn = document.getElementById('dupDeleteAllToolbarBtn');
  const tbCount = document.getElementById('dupDeleteAllToolbarCount');
  if (tbBtn) tbBtn.style.display = totalExtras > 0 ? '' : 'none';
  if (tbCount) tbCount.textContent = totalExtras;

  let h = `<div class="dup-explain">
    <div class="dup-explain-title">What am I looking at?</div>
    <div class="dup-explain-body">
      Clusters of files that share a <b>normalized name</b> <span class="dup-explain-hint">(punctuation, spacing, and case ignored — so <code>SNAN2-3030-Baseline</code> matches <code>SNAN2 3030 Baseline</code>)</span> AND have <b>at least one extra copy beyond the normal cloud↔local pair</b>.
      Within each cluster, <b>faded</b> items are already paired; <b>amber-outlined</b> items are the extras worth deleting or merging.
    </div>
    <div class="dup-explain-legend">
      <span class="dup-explain-tag mixed">Mixed</span> — matched pair PLUS at least one extra copy on one side &nbsp;·&nbsp;
      <span class="dup-explain-tag local-only">Local only</span> — same file saved in <b>multiple local folders</b> &nbsp;·&nbsp;
      <span class="dup-explain-tag cloud-only">Cloud only</span> — same project uploaded to Ekahau <b>more than once</b>
    </div>
  </div>
  <div id="dupBulkBar" class="dup-bulk-bar" style="display:none;">
    <label class="dup-bulk-selall"><input type="checkbox" id="dupBulkSelAll" onchange="dupBulkSelectAll(this.checked)"> Select all across clusters</label>
    <span class="spacer"></span>
    <span id="dupBulkCount" class="dup-bulk-count">0 selected</span>
    <button class="btn btn-red btn-sm" onclick="dupBulkDelete()">Delete checked</button>
  </div>
  <div class="dup-container">`;
  filtered.forEach(cl => h += renderCluster(cl));
  h += '</div>';
  el.innerHTML = h;
  updateDupBulkBar();

  // If we arrived here via jumpToCluster, scroll to and pulse the target.
  if (dupHighlightKey) {
    const target = dupHighlightKey;
    dupHighlightKey = null;
    requestAnimationFrame(() => scrollToCluster(target));
  }
}

function renderCluster(cl) {
  const kAttr = a(cl.key);
  const shapeLabel = cl.shape === 'mixed' ? 'Mixed' : cl.shape === 'local-only' ? 'Local only' : 'Cloud only';
  let h = `<div class="dup-cluster expanded" data-key="${kAttr}">`;
  h += `<div class="dup-head" onclick="toggleCluster('${kAttr}')">`;
  h += `<span class="dup-chevron">&#9656;</span>`;
  h += `<span class="dup-title">${e(cl.displayName)}</span>`;
  h += `<span class="dup-shape ${cl.shape}">${shapeLabel}</span>`;
  h += `<span class="dup-counts">`;
  if (cl.sides.cloud) h += `<span class="dup-count-pill">&#9729; <b>${cl.sides.cloud}</b> cloud</span>`;
  if (cl.sides.local) h += `<span class="dup-count-pill">&#128187; <b>${cl.sides.local}</b> local</span>`;
  h += `</span></div>`;

  h += `<div class="dup-body">`;
  h += `<div class="dup-actions-bar">`;
  // Action buttons depend on cluster shape:
  //   - Local-only / Cloud-only: every item is a candidate → "Keep newest / largest" is safe.
  //   - Mixed WITH a matched pair: aggressive "Keep..." would break the pair. Offer
  //     "Delete extras (keep the pair)" instead — it only removes unmatched items.
  //   - Mixed with NO matches (rare — content drift or discriminator conflict):
  //     user needs to pick manually; only per-item + Delete-checked are shown.
  const matchedCount = cl.items.filter(i => i.matched).length;
  const extraCount = cl.items.length - matchedCount;
  const hasPair = matchedCount >= 2 && extraCount >= 1;  // pair + at least one extra
  const allExtras = matchedCount === 0;
  h += `<span class="manual-count" id="dupManual-${kAttr}">0 selected</span>`;
  h += `<span class="spacer"></span>`;
  // All action buttons on the right — consistent with the rest of the page.
  if (cl.shape !== 'mixed' && allExtras) {
    // Pure single-side duplicate — safe to offer aggressive picks.
    h += `<button class="btn btn-sec btn-sm" onclick="dupKeep('${kAttr}','newest')">Keep newest — delete rest</button>`;
    h += `<button class="btn btn-sec btn-sm" onclick="dupKeep('${kAttr}','largest')">Keep largest — delete rest</button>`;
  } else if (hasPair) {
    // Mixed cluster with a real pair — pair-preserving action only.
    h += `<button class="btn btn-amber btn-sm" onclick="dupDeleteExtras('${kAttr}')" title="Deletes only the ${extraCount} unmatched extra${extraCount !== 1 ? 's' : ''} — the matched cloud↔local pair stays intact.">&#128465; Delete ${extraCount} extra${extraCount !== 1 ? 's' : ''} (keep the pair)</button>`;
  }
  h += `<button class="btn btn-red btn-sm" onclick="dupDeleteChecked('${kAttr}')">Delete checked</button>`;
  h += `</div>`;

  h += `<div class="dup-items">`;
  cl.items.forEach((it, idx) => {
    const iid = it.id || it.path;
    const isNewest = iid === cl.newestId;
    const isLargest = iid === cl.largestId;
    const sideCls = it.side === 'cloud' ? 'cloud' : 'local';
    const sideIcon = it.side === 'cloud' ? '&#9729;' : '&#128187;';
    const rowCls = ['dup-item', 'side-' + sideCls];
    if (isNewest) rowCls.push('is-newest');
    if (isLargest) rowCls.push('is-largest');
    // Fade items already paired in Sites/Projects — outline the "extras."
    if (it.matched) rowCls.push('is-matched');
    else rowCls.push('is-extra');
    const dateStr = it.mtime ? fmtRelDate(it.mtime) : '—';
    const sizeStr = fmtBytes(it.size);

    h += `<div class="${rowCls.join(' ')}" data-iid="${a(iid)}">`;
    h += `<input type="checkbox" class="dup-item-check" onchange="dupChkChanged('${kAttr}')">`;
    h += `<span class="dup-item-side ${sideCls}">${sideIcon}</span>`;
    // Location + owner on the sub-line so cloud items with "(no site)" still
    // carry enough context (owner email) to judge whether they're safe to delete.
    const loc = it.location || (it.side === 'cloud' ? '(no site)' : '');
    const owner = it.owner ? `<span class="dup-item-owner">· ${e(it.owner)}</span>` : '';
    h += `<div>
      <div class="dup-item-name">${e(it.name)}${it.matched ? '<span class="dup-pill matched">matched</span>' : ''}</div>
      <div class="dup-item-loc">${e(loc)} ${owner}</div>
    </div>`;
    h += `<div class="dup-item-size">${e(sizeStr)}${isLargest ? '<span class="dup-pill largest">largest</span>' : ''}</div>`;
    h += `<div class="dup-item-date">${e(dateStr)}${isNewest ? '<span class="dup-pill newest">newest</span>' : ''}</div>`;
    h += `<div class="dup-item-actions">`;
    if (it.side === 'local') {
      h += `<button class="icon-btn" title="Show in Explorer/Finder" onclick="revealInExplorer('${p(it.path)}')">&#128193;</button>`;
    } else {
      h += `<button class="icon-btn" title="View site contents" onclick="openCloudPeek('${a(it.id)}','${a(it.location)}')">&#128065;</button>`;
    }
    // Delete needs backslash normalization when iid is a local path — a raw
    // Windows path in a JS-string onclick lets \U, \f, etc. be swallowed as
    // JS escape codes, corrupting the value dupDeleteOne receives.
    const iidAttr = it.side === 'local' ? p(iid) : a(iid);
    h += `<button class="icon-btn del" title="Delete" onclick="dupDeleteOne('${kAttr}','${iidAttr}')">&#128465;</button>`;
    h += `</div>`;
    h += `</div>`;
  });
  h += `</div></div></div>`;
  return h;
}

function toggleCluster(key) {
  const el = document.querySelector(`.dup-cluster[data-key="${cssEscape(key)}"]`);
  if (el) el.classList.toggle('expanded');
}
function dupChkChanged(key) {
  const el = document.querySelector(`.dup-cluster[data-key="${cssEscape(key)}"]`);
  if (!el) return;
  const n = el.querySelectorAll('.dup-item-check:checked').length;
  const c = el.querySelector('.manual-count');
  if (c) c.textContent = `${n} selected`;
  updateDupBulkBar();
}

// Cross-cluster bulk selection — a checked item in any cluster surfaces the
// "Delete checked" bar at the top of the Duplicates view so users can
// operate across clusters without having to hit each cluster's own button.
function updateDupBulkBar() {
  const bar = document.getElementById('dupBulkBar');
  if (!bar) return;
  const all = document.querySelectorAll('.dup-item-check');
  const checked = document.querySelectorAll('.dup-item-check:checked');
  bar.style.display = checked.length ? '' : 'none';
  const cnt = document.getElementById('dupBulkCount');
  if (cnt) cnt.textContent = `${checked.length} selected across ${new Set(Array.from(checked).map(cb => cb.closest('.dup-cluster')?.dataset.key)).size} cluster${checked.length === 1 ? '' : 's'}`;
  const selAll = document.getElementById('dupBulkSelAll');
  if (selAll) selAll.checked = all.length > 0 && all.length === checked.length;
}

function dupBulkSelectAll(on) {
  document.querySelectorAll('.dup-item-check').forEach(cb => { cb.checked = !!on; });
  // Refresh each cluster's manual-count too
  document.querySelectorAll('.dup-cluster').forEach(el => {
    const n = el.querySelectorAll('.dup-item-check:checked').length;
    const c = el.querySelector('.manual-count');
    if (c) c.textContent = `${n} selected`;
  });
  updateDupBulkBar();
}

function dupBulkDelete() {
  // Gather checked items across every cluster.
  const items = [];
  document.querySelectorAll('.dup-cluster').forEach(el => {
    const key = el.dataset.key;
    const cl = _findCluster(key);
    if (!cl) return;
    const norm = s => String(s || '').replace(/\\/g, '/').toLowerCase();
    el.querySelectorAll('.dup-item-check:checked').forEach(cb => {
      const row = cb.closest('.dup-item');
      if (!row) return;
      const iid = norm(row.dataset.iid);
      const it = cl.items.find(i => norm(i.id || i.path) === iid);
      if (it) items.push(it);
    });
  });
  if (!items.length) { toast('No items checked', 'info'); return; }
  _bulkDeleteItems(items, null);
}

/* ── Duplicates: actions (delete-based cleanup) ── */
function _findCluster(key) {
  return ((dupData && dupData.clusters) || []).find(c => c.key === key);
}

async function _bulkDeleteItems(items, clusterKey) {
  if (!items.length) return;
  const lines = items.map(it => `• [${it.side}] ${it.name} (${fmtBytes(it.size)})`).join('\n');
  if (!confirm(`Delete these ${items.length} file${items.length !== 1 ? 's' : ''}?\n\n${lines}\n\nThis is permanent.`)) return;
  let ok = 0, fail = 0;
  for (const it of items) {
    try {
      const r = it.side === 'cloud'
        ? await pyApi('delete_cloud', 'projects', it.id)
        : await pyApi('delete_local', it.path);
      if (r && r.error) { fail++; toast(r.error, 'error'); }
      else ok++;
    } catch (err) { fail++; toast(err.message, 'error'); }
  }
  toast(`Deleted ${ok}${fail ? ` — ${fail} failed` : ''}`, fail ? 'error' : 'success');
  refreshData();
}

function dupKeep(key, mode) {
  const cl = _findCluster(key);
  if (!cl) return;
  const keeperId = mode === 'newest' ? cl.newestId : cl.largestId;
  const toDelete = cl.items.filter(it => (it.id || it.path) !== keeperId);
  _bulkDeleteItems(toDelete, key);
}
// Pair-preserving cleanup: delete only items that AREN'T part of a
// Sites/Projects matched pair. Safe default for Mixed clusters that
// contain a normal pair plus extras.
function dupDeleteExtras(key) {
  const cl = _findCluster(key);
  if (!cl) return;
  const toDelete = cl.items.filter(it => !it.matched);
  if (!toDelete.length) { toast('No unmatched extras in this cluster', 'info'); return; }
  _bulkDeleteItems(toDelete, key);
}
// Same logic, but ACROSS every rendered cluster in one click. Only touches
// unmatched items so every matched cloud↔local pair stays intact.
function dupDeleteAllExtras() {
  const clusters = (dupData && dupData.clusters) || [];
  const toDelete = [];
  clusters.forEach(cl => {
    cl.items.forEach(it => { if (!it.matched) toDelete.push(it); });
  });
  if (!toDelete.length) { toast('No unmatched extras across any cluster', 'info'); return; }
  _bulkDeleteItems(toDelete, null);
}
function dupDeleteChecked(key) {
  const el = document.querySelector(`.dup-cluster[data-key="${cssEscape(key)}"]`);
  if (!el) return;
  const cl = _findCluster(key);
  if (!cl) return;
  const checkedIids = new Set();
  el.querySelectorAll('.dup-item-check:checked').forEach(cb => {
    const row = cb.closest('.dup-item');
    if (row) checkedIids.add(row.dataset.iid);
  });
  if (!checkedIids.size) { toast('No files checked in this cluster', 'info'); return; }
  const toDelete = cl.items.filter(it => checkedIids.has(it.id || it.path));
  _bulkDeleteItems(toDelete, key);
}
function dupDeleteOne(key, iid) {
  const cl = _findCluster(key);
  if (!cl) return;
  // Normalize both sides — the onclick passes a forward-slash path for local
  // items, while cl.items[].path from the backend uses backslashes on Windows.
  const norm = s => String(s || '').replace(/\\/g, '/').toLowerCase();
  const target = norm(iid);
  const it = cl.items.find(i => norm(i.id || i.path) === target);
  if (it) _bulkDeleteItems([it], key);
  else toast('Could not locate that item', 'error');
}

/* ── Duplicates: formatting helpers ── */
function fmtBytes(b) {
  if (!b) return '0 B';
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b/1024).toFixed(1) + ' KB';
  if (b < 1073741824) return (b/1048576).toFixed(1) + ' MB';
  return (b/1073741824).toFixed(2) + ' GB';
}
function fmtRelDate(ts) {
  if (!ts) return '—';
  const now = Math.floor(Date.now() / 1000);
  const diff = now - ts;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff/60) + ' min ago';
  if (diff < 86400) return Math.floor(diff/3600) + ' hr ago';
  if (diff < 604800) return Math.floor(diff/86400) + ' days ago';
  // Older than a week — show absolute date
  const d = new Date(ts * 1000);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function chip(code) { return ''; }

/* ── Project Files: collapsible folder tree ── */
function toggleFolder(fn) {
  if (collapsed.has(fn)) collapsed.delete(fn); else collapsed.add(fn);
  renderRows();
}
function statusBadge(st) {
  if (st === 'synced') return `<span class="st ok">synced</span>`;
  if (st === 'mismatch') return `<span class="st warn">mismatch</span>`;
  return `<span class="st orph">orphan</span>`;
}
function renderEsxRow(en, stripe) {
  const item = en.item, status = en.status, pair = en.pair;
  const key = pair ? ('p:' + pair.cloud.id) : ('l:' + item.path);
  const badge = status === 'synced' ? `<span class="st ok">synced</span>`
              : status === 'mismatch' ? `<span class="st warn">mismatch</span>`
              : `<span class="st orph">orphan</span>`;
  let cloudInfo = '';
  if (pair) {
    const c = pair.cloud;
    if (status === 'mismatch') {
      cloudInfo = `<span class="tree-cloud" title="Cloud project: ${a(c.name)}">&#8596; ${e(c.name)}</span>
        <button class="sync-btn" title="Cloud name → local file" onclick="syncRow('to-local','${a(c.id)}','${a(c.name)}','${p(item.path)}')">&#8594;</button>
        <button class="sync-btn" title="Local name → cloud project" onclick="syncRow('to-cloud','${a(c.id)}','${a(item.name)}','${p(item.path)}')">&#8592;</button>`;
    } else {
      cloudInfo = `<span class="tree-cloud ok" title="Matched cloud project">&#10003; in cloud</span>`;
    }
  }
  return `<div class="tree-row${stripe}">
    <input type="checkbox" class="rowchk" data-k="${e(key)}" ${selected.has(key) ? 'checked' : ''}>
    <span class="tree-esx">${e(item.name)}</span>
    ${badge}
    <span class="pair-meta">${e(item.meta)}</span>
    <span class="grow"></span>
    ${cloudInfo}
    <button class="icon-btn" title="Rename .esx file" onclick="startRename('local','${p(item.path)}','${a(item.name)}')">&#9998;</button>
    <button class="icon-btn del" title="Delete .esx file" onclick="startDelete('local','${p(item.path)}','${a(item.name)}',false)">&#128465;</button>
  </div>`;
}

/* ── WinDiff-style aligned ledger (both tabs) ── */
function renderLedger(hit) {
  const isSites = currentTab === 'sites';
  const showSynced = activeFilter === 'all' || activeFilter === 'synced';
  const showMis = activeFilter === 'all' || activeFilter === 'mismatches';
  const showOrph = activeFilter === 'all' || activeFilter === 'orphans';
  const showOrphCloud = activeFilter === 'orphans-cloud';
  const showOrphLocal = activeFilter === 'orphans-local';
  const showUnassigned = activeFilter === 'unassigned';
  const pass = (st, row) => {
    if (showUnassigned) return row && row.cloud && !row.cloud.hasSite;
    if (showOrphCloud) return st === 'orphan' && row && row.cloud && !row.local;
    if (showOrphLocal) return st === 'orphan' && row && row.local && !row.cloud;
    return (st === 'synced' && showSynced) || (st === 'mismatch' && showMis) || (st === 'orphan' && showOrph);
  };
  // Owner filter (Project Files tab only — Sites don't have per-file owners).
  const own = ownerFilter();
  const me = ((data && data.currentUser) || '').toLowerCase();
  const passOwner = (row) => {
    if (isSites || own === 'all' || !me) return true;
    // A row is "mine" if EITHER side is mine (or unknown); "others" if EITHER
    // side is explicitly someone else's email. This surfaces cross-owner pairs
    // (e.g. my local + Andrew's cloud) in the "others" filter too.
    const co = (row.cloud && row.cloud.owner || '').toLowerCase();
    const lo = (row.local && row.local.owner || '').toLowerCase();
    const otherCloud = co && co.indexOf('@') > -1 && co !== me;
    const otherLocal = lo && lo.indexOf('@') > -1 && lo !== me;
    if (own === 'mine')   return !otherCloud && !otherLocal;
    if (own === 'others') return otherCloud || otherLocal;
    return true;
  };

  const rows = [];
  (data.matched || []).forEach(p => rows.push({
    status: p.namesDiffer ? 'mismatch' : 'synced', key: 'p:' + p.cloud.id,
    cloud: p.cloud, local: p.local, sort: (p.cloud.name || p.local.name || '')
  }));
  (data.cloudOnly || []).forEach(s => rows.push({ status: 'orphan', key: 'c:' + s.id, cloud: s, local: null, sort: s.name || '' }));
  (data.localOnly || []).forEach(f => rows.push({ status: 'orphan', key: 'l:' + f.path, cloud: null, local: f, sort: f.name || '' }));

  const cloudCodes = new Set(rows.map(r => r.cloud && r.cloud.code).filter(Boolean));
  const localCodes = new Set(rows.map(r => r.local && r.local.code).filter(Boolean));

  const visible = rows
    .filter(r => pass(r.status, r) && passOwner(r) && (hit(r.cloud && r.cloud.name) || hit(r.local && r.local.name)))
    .sort((x, y) => x.sort.localeCompare(y.sort, undefined, { sensitivity: 'base' }));
  const nCloud = visible.filter(r => r.cloud).length, nLocal = visible.filter(r => r.local).length;

  let h = `<div class="ledger">`;
  h += `<div class="ledger-head"><div class="lh-cell cloud">${isSites ? 'Cloud Sites' : 'Cloud Projects'} (${nCloud})</div><div class="lh-gut"></div><div class="lh-cell local">${isSites ? 'Local Folders' : 'Local .esx'} (${nLocal})</div></div>`;
  if (!visible.length) { h += `<div class="empty-msg">Nothing here for this filter.</div></div>`; return h; }
  const groupOf = (s) => {
    const ch = String(s || '').trim().charAt(0).toUpperCase();
    return (ch >= 'A' && ch <= 'Z') ? ch : '#';
  };
  let z = 0;
  let lastGroup = null;
  visible.forEach(r => {
    const g = groupOf(r.sort);
    if (g !== lastGroup) {
      // Letter appears on both the cloud (left) and local (right) columns so
      // the section is labeled regardless of which side you're scanning.
      h += `<div class="ledger-group-head" role="separator" aria-label="Section ${e(g)}">`
         +   `<span class="glh-letter cloud">${e(g)}</span>`
         +   `<span class="glh-gap"></span>`
         +   `<span class="glh-letter local">${e(g)}</span>`
         + `</div>`;
      lastGroup = g;
      z = 0; // reset stripe alternation per section so it stays readable
    }
    h += `<div class="ledger-row ${r.status}${(z++ % 2) ? ' stripe' : ''}">${cloudCell(r, localCodes)}${gutCell(r)}${localCell(r, cloudCodes)}</div>`;
  });
  h += `</div>`;
  return h;
}
function gutCell(r) {
  if (r.status === 'mismatch') {
    const c = r.cloud, l = r.local;
    return `<div class="lr-gut mis">
      <button class="gut-arrow" title="Apply cloud name onto the local folder" onclick="syncRow('to-local','${a(c.id)}','${a(c.name)}','${p(l.path)}')">&#10145;</button>
      <button class="gut-arrow" title="Apply local name onto the cloud site" onclick="syncRow('to-cloud','${a(c.id)}','${a(l.name)}','${p(l.path)}')">&#11013;</button>
      <button class="gut-arrow nomatch" title="Not a match — never pair these two again" onclick="markNotMatch('${a(c.id)}','${p(l.path)}','${a(c.name)}','${a(l.name)}')">&#8800;</button>
    </div>`;
  }
  if (r.status === 'synced') {
    return `<div class="lr-gut ok"><span class="gut-glyph" title="In sync">=</span></div>`;
  }
  if (r.cloud) {
    const act = currentTab === 'sites'
      ? `onclick="createLocalFolder('${a(r.cloud.name)}')"` : '';
    const title = currentTab === 'sites' ? 'Create the matching local folder →' : 'Cloud only';
    return currentTab === 'sites'
      ? `<div class="lr-gut orph"><button class="gut-arrow orphan" title="${title}" ${act}>&#10145;</button></div>`
      : `<div class="lr-gut orph"><span class="gut-glyph" title="${title}">&#10145;</span></div>`;
  }
  if (currentTab === 'sites') {
    return `<div class="lr-gut orph"><button class="gut-arrow orphan" title="← Create a cloud site from this folder" onclick="createFromLocal('${a(r.local.name)}')">&#11013;</button></div>`;
  }
  return `<div class="lr-gut orph"><button class="gut-arrow orphan" title="← Upload .esx to Ekahau Cloud" onclick="uploadFromLocal('${p(r.local.path)}','${a(r.local.name)}')">&#11013;</button></div>`;
}
function cloudCell(r, localCodes) {
  const isSites = currentTab === 'sites';
  if (!r.cloud) {
    if (isSites) {
      return `<div class="lr-cell cloud empty"><button class="ghost-add" title="Create a cloud site from this folder" onclick="createFromLocal('${a(r.local.name)}')">+ Cloud site</button></div>`;
    }
    return `<div class="lr-cell cloud empty"><button class="ghost-add" title="Upload .esx to Ekahau Cloud" onclick="uploadFromLocal('${p(r.local.path)}','${a(r.local.name)}')">+ Upload</button></div>`;
  }
  const c = r.cloud, isMis = r.status === 'mismatch', thing = isSites ? 'cloud site' : 'cloud project';
  const me = ((data && data.currentUser) || '').toLowerCase();
  const owner = (c.owner || '').toLowerCase();
  const ownerHtml = (!isSites && owner)
    ? ` <span class="owner-tag${owner !== me ? ' other' : ''}" title="Owner (from Ekahau history.createdBy)">(${e(owner)})</span>`
    : '';
  const nameHtml = (isMis ? charDiff(c.name, r.local.name).a : e(c.name)) + (isSites ? '' : '.esx') + ownerHtml + dupHintFor(c.id);
  const dup = r.status === 'orphan' && c.code && localCodes.has(c.code);
  const dsCount = (c.datasets && c.datasets.length) || 0;
  const cloudPeek = isSites
    ? `<button class="src-badge${dsCount ? ' hasrc' : ''}" title="${dsCount ? dsCount + ' project' + (dsCount > 1 ? 's' : '') : 'No projects yet'} — click to view" onclick="event.stopPropagation();openCloudPeek('${a(c.id)}','${a(c.name)}')">&#128065;</button>`
    : '';
  return `<div class="lr-cell cloud${dup ? ' dup' : ''}"${dup ? ` title="A local ${isSites ? 'folder' : '.esx'} shares code ${a(c.code)} — likely the same place"` : ''}>
    <input type="checkbox" class="rowchk" data-k="${e(r.key)}" ${selected.has(r.key) ? 'checked' : ''}>
    <span class="cell-name">${nameHtml}</span><span class="cell-meta">${e(c.meta || '')}</span>
    <span class="cell-actions">${cloudPeek}
      ${!isSites ? `<button class="icon-btn" title="Move to a site" onclick="startMoveToSite('${a(c.id)}','${a(c.name)}')">&#8618;</button>` : ''}
      <button class="icon-btn" title="Rename ${thing}" onclick="startRename('cloud','${a(c.id)}','${a(c.name)}')">&#9998;</button>
      <button class="icon-btn del" title="Delete ${thing}" onclick="startDelete('cloud','${a(c.id)}','${a(c.name)}',false)">&#128465;</button>
    </span></div>`;
}
function localCell(r, cloudCodes) {
  const isSites = currentTab === 'sites';
  if (!r.local) {
    return isSites
      ? `<div class="lr-cell local empty"><button class="ghost-add" title="Create a matching local folder" onclick="createLocalFolder('${a(r.cloud.name)}')">+ Local folder</button></div>`
      : `<div class="lr-cell local empty"></div>`;
  }
  const l = r.local, isMis = r.status === 'mismatch', thing = isSites ? 'local folder' : '.esx file';
  const me = ((data && data.currentUser) || '').toLowerCase();
  const owner = (l.owner || '').toLowerCase();
  // "Mine" if the owner is either my email OR a non-email string (display name)
  // that no cloud owner would ever match — we assume local display names are mine.
  const localIsOther = owner && owner.indexOf('@') > -1 && owner !== me;
  const ownerHtml = (!isSites && owner)
    ? ` <span class="owner-tag${localIsOther ? ' other' : ''}" title="Author (from project.history.createdBy)">(${e(owner)})</span>`
    : '';
  const nameHtml = (isMis ? charDiff(r.cloud.name, l.name).b : e(l.name)) + (l.isDir ? '' : '.esx') + ownerHtml + dupHintFor(l.path);
  const dup = r.status === 'orphan' && l.code && cloudCodes.has(l.code);
  const hasSrc = isSites && l.hasSource;
  const hasContents = isSites && l.src && l.src.total > 0;
  const flagged = l.name.charAt(0) === '!';
  const srcUI = hasContents ? previewBadge(l) : '';
  const flagBtn = isSites
    ? `<button class="icon-btn${flagged ? ' flagged' : ''}" title="${flagged ? 'Un-flag (remove the ! prefix)' : 'Flag this folder for review — adds a ! prefix so it sorts to the top here and in Explorer'}" onclick="flagReview('${p(l.path)}','${a(l.name)}')">${flagged ? '&#9873;' : '&#9872;'}</button>`
    : '';
  const revealBtn = `<button class="icon-btn" title="Show in ${navigator.platform.indexOf('Mac') >= 0 ? 'Finder' : 'Explorer'}" onclick="revealInExplorer('${p(l.path)}')">&#128193;</button>`;
  return `<div class="lr-cell local${dup ? ' dup' : ''}"${dup ? ` title="A cloud ${isSites ? 'site' : 'project'} shares code ${a(l.code)} — likely the same place"` : ''}>
    <input type="checkbox" class="rowchk" data-k="${e(r.key)}" ${selected.has(r.key) ? 'checked' : ''}>
    <span class="cell-name">${nameHtml}</span><span class="cell-meta">${e(l.meta || '')}</span>
    <span class="cell-actions">${srcUI}${revealBtn}${flagBtn}
      ${isSites ? `<button class="icon-btn" title="Merge this folder's files into another folder…" onclick="startMerge('${p(l.path)}','${a(l.name)}')">&#8649;</button>` : ''}
      <button class="icon-btn" title="Rename ${thing}" onclick="startRename('local','${p(l.path)}','${a(l.name)}')">&#9998;</button>
      <button class="icon-btn del" title="Delete ${thing}${isSites ? ' and contents' : ''}" onclick="startDelete('local','${p(l.path)}','${a(l.name)}',${l.isDir})">&#128465;</button>
    </span></div>`;
}
// ── Source-file (non-.esx) helpers: badge, peek, review-flag ──
function localByPath(path) {
  // Compare with backslashes normalized to forward slashes — the onclick-safe
  // path (via p()) uses forward slashes while backend paths use backslashes on Windows.
  const norm = s => String(s || '').replace(/\\/g, '/');
  const target = norm(path);
  let item = null;
  (data.matched || []).forEach(pr => { if (pr.local && norm(pr.local.path) === target) item = pr.local; });
  (data.localOnly || []).forEach(f => { if (norm(f.path) === target) item = f; });
  return item;
}
function previewBadge(l) {
  const s = l.src || {};
  if (!s.total) return '';
  let tip, cls = 'src-badge';
  if (s.srcCount) {
    const bits = [];
    if (s.plans) bits.push(s.plans + ' floor plan' + (s.plans > 1 ? 's' : ''));
    if (s.images) bits.push(s.images + ' image' + (s.images > 1 ? 's' : ''));
    if (s.other) bits.push(s.other + ' other');
    tip = `Holds ${s.srcCount} source file${s.srcCount > 1 ? 's' : ''} not on Ekahau Cloud (${bits.join(', ')}, ${s.srcSizeH}) · ${s.esx} .esx — click to view all`;
    cls += ' hasrc';
  } else {
    tip = `${s.esx} Ekahau .esx file${s.esx > 1 ? 's' : ''} — click to view contents`;
  }
  return `<button class="${cls}" title="${a(tip)}" onclick="event.stopPropagation();openPeek('${p(l.path)}')">&#128065;</button>`;
}
function peekFileRow(f, typeClass) {
  const when = f.mtime ? new Date(f.mtime * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' }) : '';
  const ext = (f.name.split('.').pop() || '').toLowerCase();
  const rel = f.rel || f.name;
  // Split rel into subpath + name (handle both / and \)
  const parts = String(rel).replace(/\\/g, '/').split('/');
  const nm = parts.pop();
  const sub = parts.join('/');
  return `<div class="peek-row">
    <span class="peek-type ${typeClass}">${e(ext).slice(0, 4)}</span>
    <div class="peek-info">
      <div class="peek-file">${e(nm)}</div>
      ${sub ? `<div class="peek-sub">${e(sub)}/</div>` : ''}
    </div>
    <div class="peek-meta">
      <div class="peek-date">${e(when)}</div>
      <div class="peek-size">${e(f.sizeH)}</div>
    </div>
  </div>`;
}
function peekSection(label, typeClass, files) {
  if (!files.length) return '';
  const rows = files.map(f => peekFileRow(f, typeClass)).join('');
  return `<div class="peek-section ${typeClass}">
    <div class="peek-sec-head">
      <span class="peek-sec-name">${e(label)}</span>
      <span class="peek-sec-count">${files.length}</span>
    </div>
    <div class="peek-list">${rows}</div>
  </div>`;
}
function openPeek(path) {
  const l = localByPath(path);
  if (!l || !l.src) { toast('No file details available', 'info'); return; }
  const s = l.src, files = s.files || [];
  const byType = {
    esx: files.filter(f => f.type === 'esx'),
    plan: files.filter(f => f.type === 'plan'),
    image: files.filter(f => f.type === 'image'),
    other: files.filter(f => f.type === 'other'),
  };
  const stats = `<div class="peek-stats">
    <span class="peek-stat esx"><span class="dot"></span><b>${byType.esx.length}</b> .esx</span>
    <span class="peek-stat plan"><span class="dot"></span><b>${byType.plan.length}</b> plans</span>
    <span class="peek-stat image"><span class="dot"></span><b>${byType.image.length}</b> images</span>
    <span class="peek-stat other"><span class="dot"></span><b>${byType.other.length}</b> other</span>
  </div>`;
  const note = s.srcCount
    ? `<div class="peek-note"><b>${s.srcCount}</b> source file${s.srcCount > 1 ? 's' : ''} (${e(s.srcSizeH)}) here are <b>not on Ekahau Cloud</b> — this folder is their only home.</div>`
    : `<div class="peek-note">This folder holds only Ekahau <b>.esx</b> files (also backed up to the cloud).</div>`;
  let body = `<div class="peek-hero">${stats}${note}</div>`;
  body += peekSection('Ekahau Projects', 'esx', byType.esx);
  body += peekSection('Floor Plans', 'plan', byType.plan);
  body += peekSection('Images', 'image', byType.image);
  body += peekSection('Other Files', 'other', byType.other);
  if (s.total > files.length) body += `<div class="peek-more">…and ${s.total - files.length} more</div>`;
  document.getElementById('peekTitle').innerHTML = `<span class="peek-title-icon">&#128193;</span>${e(l.name)}<span class="peek-title-sub">Local folder</span>`;
  document.getElementById('peekBody').innerHTML = body;
  showModal('peekModal');
}
function openCloudPeek(siteId, siteName) {
  let datasets = [];
  (data.matched || []).forEach(pr => { if (pr.cloud && pr.cloud.id === siteId) datasets = pr.cloud.datasets || []; });
  (data.cloudOnly || []).forEach(c => { if (c.id === siteId) datasets = c.datasets || []; });
  const stats = `<div class="peek-stats">
    <span class="peek-stat esx"><span class="dot"></span><b>${datasets.length}</b> project${datasets.length !== 1 ? 's' : ''}</span>
  </div>`;
  let body = `<div class="peek-hero">${stats}`;
  if (datasets.length) {
    body += `<div class="peek-note">Hosted on <b>Ekahau Cloud</b> — file sizes and timestamps aren't provided by the cloud API.</div>`;
    body += `</div>`;
    const fmtSize = b => !b ? '' : b < 1024 ? b + ' B' : b < 1048576 ? (b/1024).toFixed(1) + ' KB' : (b/1048576).toFixed(1) + ' MB';
    const rows = datasets.map(d => `<div class="peek-row">
      <span class="peek-type esx">esx</span>
      <div class="peek-info"><div class="peek-file">${e(d.name)}.esx</div></div>
      <div class="peek-meta">
        <div class="peek-date">cloud</div>
        <div class="peek-size">${e(fmtSize(d.size))}</div>
      </div>
    </div>`).join('');
    body += `<div class="peek-section esx">
      <div class="peek-sec-head">
        <span class="peek-sec-name">Cloud Projects</span>
        <span class="peek-sec-count">${datasets.length}</span>
      </div>
      <div class="peek-list">${rows}</div>
    </div>`;
  } else {
    body += `<div class="peek-note">This site exists on <b>Ekahau Cloud</b> but has no projects uploaded to it yet.</div>`;
    body += `</div>`;
    body += `<div class="peek-empty">
      <div class="peek-empty-icon">&#128230;</div>
      <div class="peek-empty-title">No projects yet</div>
      <div class="peek-empty-sub">Upload a matching local <code>.esx</code> from the right side to populate this site.</div>
    </div>`;
  }
  document.getElementById('peekTitle').innerHTML = `<span class="peek-title-icon">&#9729;</span>${e(siteName)}<span class="peek-title-sub">Ekahau Cloud site</span>`;
  document.getElementById('peekBody').innerHTML = body;
  showModal('peekModal');
}
async function revealInExplorer(path) {
  const r = await pyApi('reveal_in_explorer', path);
  if (r.error) toast(r.error, 'error');
}
// ── Compare: side-by-side contents of the selected local folders ──
function selectedLocalFolders() {
  const seen = new Set(), out = [];
  selected.forEach(k => {
    const d = rowData[k]; if (!d) return;
    const p = d.kind === 'pair' ? d.localPath : d.kind === 'local' ? d.path : null;
    if (p && !seen.has(p)) { seen.add(p); const it = localByPath(p); if (it) out.push(it); }
  });
  return out;
}
function openCompare() {
  const folders = selectedLocalFolders();
  if (folders.length < 2) { toast('Select 2 or more local folders to compare', 'info'); return; }
  const freq = {};
  folders.forEach(f => {
    new Set(((f.src && f.src.files) || []).map(x => x.name.toLowerCase()))
      .forEach(n => { freq[n] = (freq[n] || 0) + 1; });
  });
  let cols = '';
  folders.forEach(f => {
    const s = f.src || {};
    const files = ((s.files) || []).slice().sort((x, y) => x.name.localeCompare(y.name));
    let rows = '';
    files.forEach(x => {
      const common = (freq[x.name.toLowerCase()] || 0) > 1;
      const when = x.mtime ? new Date(x.mtime * 1000).toLocaleString() : '';
      rows += `<div class="cmp-file${common ? ' common' : ''}" title="${a(x.rel || x.name)}"><span class="cmp-n">${e(x.name)}</span><span class="cmp-meta">${e(when)}${when ? ' · ' : ''}${e(x.sizeH)}</span></div>`;
    });
    if (!files.length) rows = `<div class="cmp-empty">empty</div>`;
    const sub = `${s.total || 0} file${(s.total || 0) !== 1 ? 's' : ''} · ${s.esx || 0} .esx${s.srcCount ? ` · ${s.srcCount} source` : ''}`;
    cols += `<div class="cmp-col">
      <div class="cmp-head"><div class="cmp-title" title="${a(f.name)}">${e(f.name)}</div><div class="cmp-sub">${sub}</div></div>
      <div class="cmp-list">${rows}</div></div>`;
  });
  document.getElementById('compareTitle').textContent = `Compare ${folders.length} folders`;
  document.getElementById('compareBody').innerHTML = cols;
  showModal('compareModal');
}
async function flagReview(path, name) {
  const flagged = name.charAt(0) === '!';
  const newName = flagged ? name.replace(/^!+\s*/, '') : '!' + name;
  try {
    const r = await pyApi('rename_local', path, newName);
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast(flagged ? 'Un-flagged' : 'Flagged for review (!)', 'success');
    refreshData();
  } catch (e) { toast('Flag failed: ' + e.message, 'error'); }
}

// ── Not-a-match: user says "these two should never be paired" ──
async function markNotMatch(cloudId, localPath, cloudName, localName) {
  if (!confirm(`Mark as NOT a match?\n\nCloud:  ${cloudName}\nLocal:  ${localName}\n\nThey'll be split into orphans and never auto-paired again. You can undo this from the menu → Manage Not-a-Match.`)) return;
  try {
    const r = await pyApi('mark_not_match', cloudId, localPath, cloudName, localName);
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast('Marked as not a match', 'success');
    refreshData();
  } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function openNotMatchManager() {
  const r = await pyApi('list_not_matches');
  if (r && r.error) { toast(r.error, 'error'); return; }
  const pairs = (r && r.pairs) || [];
  const body = document.getElementById('nmBody');
  if (!pairs.length) {
    body.innerHTML = `<div class="peek-empty" style="padding:24px 0">
      <div class="peek-empty-icon">&#8800;</div>
      <div class="peek-empty-title">No not-a-match pairs</div>
      <div class="peek-empty-sub">Click the &ne; button on a mismatched row to add one.</div>
    </div>`;
  } else {
    const rows = pairs.map(pr => {
      const when = pr.addedAt ? new Date(pr.addedAt * 1000).toLocaleDateString() : '';
      return `<div class="nm-row">
        <div class="nm-cells">
          <div class="nm-cell cloud"><span class="nm-tag">CLOUD</span>${e(pr.cloudName || pr.cloudId)}</div>
          <div class="nm-sep">&#8800;</div>
          <div class="nm-cell local"><span class="nm-tag">LOCAL</span>${e(pr.localName || pr.localPath)}</div>
        </div>
        <div class="nm-meta">${e(when)}</div>
        <button class="btn btn-secondary nm-undo" title="Un-mark — let matching consider this pair again"
                onclick="undoNotMatch('${a(pr.cloudId)}','${p(pr.localPath)}')">Un-mark</button>
      </div>`;
    }).join('');
    body.innerHTML = `<div class="nm-list">${rows}</div>
      <div class="nm-foot">Stored in <code>${e(r.file || '')}</code></div>`;
  }
  showModal('notMatchModal');
}

async function undoNotMatch(cloudId, localPath) {
  try {
    const r = await pyApi('unmark_not_match', cloudId, localPath);
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast('Un-marked', 'success');
    openNotMatchManager();
    refreshData();
  } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

// ── Merge folder → folder (targeted consolidation) ──
function mergeRule() { try { return localStorage.getItem('wd-merge-rule') || 'ask'; } catch (e) { return 'ask'; } }
function setMergeRule(v) { try { localStorage.setItem('wd-merge-rule', v); } catch (e) {} }
function localFolders() {
  const out = [];
  (data.matched || []).forEach(p => { if (p.local) out.push(p.local); });
  (data.localOnly || []).forEach(f => out.push(f));
  return out;
}
function startMerge(path, name) {
  const src = localByPath(path);
  mergeState = { srcPath: path, srcName: name, srcCode: src && src.code };
  document.getElementById('mergeDestTitle').innerHTML = `Merge "${e(name)}" into…`;
  document.getElementById('mergeDestSearch').value = '';
  renderMergeDests();
  showModal('mergeDestModal');
}
function renderMergeDests() {
  const q = (document.getElementById('mergeDestSearch').value || '').toLowerCase();
  const code = mergeState.srcCode;
  const list = localFolders()
    .filter(f => f.path !== mergeState.srcPath && (!q || f.name.toLowerCase().includes(q)))
    .sort((x, y) => {
      const xc = code && x.code === code ? 0 : 1, yc = code && y.code === code ? 0 : 1;
      return (xc - yc) || x.name.localeCompare(y.name);
    });
  let h = list.length ? '' : `<div class="peek-more">No other folders to merge into.</div>`;
  list.forEach(f => {
    const same = code && f.code === code;
    h += `<div class="peek-row pick" onclick="chooseMergeDest('${p(f.path)}')">
      <span class="pk-name">${same ? '<b class="amber">★</b> ' : ''}${e(f.name)}</span>
      <span class="pk-size">${e(f.meta || '')}</span></div>`;
  });
  document.getElementById('mergeDestList').innerHTML = h;
}
function chooseMergeDest(dstPath) {
  const dst = localByPath(dstPath);
  mergeState.dstPath = dstPath;
  mergeState.dstName = dst ? dst.name : dstPath;
  closeModal('mergeDestModal');
  runMergePreview();
}
async function runMergePreview() {
  let prev;
  try { prev = await pyApi('merge_preview', mergeState.srcPath, mergeState.dstPath); }
  catch (e) { toast('Preview failed: ' + e.message, 'error'); return; }
  if (prev.error) { toast(prev.error, 'error'); return; }
  mergeState.preview = prev;
  showMergeModal(prev);
}
function mtimeCmp(f) {
  const s = new Date(f.srcMtime * 1000).toLocaleString();
  const d = new Date(f.dstMtime * 1000).toLocaleString();
  const badge = f.newer === 'src' ? '<span class="amber">incoming is newer</span>'
              : f.newer === 'dst' ? '<span>existing is newer</span>' : '<span>same time</span>';
  return `incoming ${s} (${e(f.srcSizeH)}) · existing ${d} (${e(f.dstSizeH)}) — ${badge}`;
}
function showMergeModal(prev) {
  document.getElementById('mergeTitle').innerHTML = `Merge "${e(mergeState.srcName)}" → "${e(mergeState.dstName)}"`;
  const wrap = document.getElementById('mergeConflictWrap');
  const btn = document.getElementById('mergeBtn');
  const listEl = document.getElementById('mergeFileList');
  if (!prev.files.length) {
    document.getElementById('mergeSummary').textContent = 'Nothing to move — the source folder has no files.';
    wrap.style.display = 'none'; listEl.innerHTML = ''; btn.disabled = true; showModal('mergeModal'); return;
  }
  btn.disabled = false;
  document.getElementById('mergeSummary').innerHTML =
    `Moving into <b>${e(mergeState.dstName)}</b>: <b>${prev.nClean}</b> new` +
    (prev.nConflicts ? `, <b>${prev.nConflicts}</b> already exist. ` : `. `) +
    `Untick any file you don't want to move — it stays put in the source folder.`;
  if (prev.nConflicts) {
    wrap.style.display = '';
    const saved = mergeRule();
    const preset = saved === 'ask' ? 'newer' : saved;
    document.querySelectorAll('input[name="mrule"]').forEach(r => { r.checked = (r.value === preset); });
    document.getElementById('mergeRemember').checked = false;
  } else {
    wrap.style.display = 'none';
  }
  let h = '';
  prev.files.forEach((f, i) => {
    const status = f.conflict
      ? `<span class="mfile-badge conflict">conflict</span><span class="mfile-cmp">${mtimeCmp(f)}</span>`
      : `<span class="mfile-badge new">new</span><span class="mfile-cmp">${e(f.srcSizeH || '')}</span>`;
    h += `<label class="mfile"><input type="checkbox" class="mfile-chk" data-i="${i}" checked>
      <span class="mfile-name">${e(f.rel)}</span>${status}</label>`;
  });
  listEl.innerHTML = h;
  showModal('mergeModal');
}
async function confirmMerge() {
  const prev = mergeState.preview;
  if (!prev) { closeModal('mergeModal'); return; }
  let rule = 'newer';
  if (prev.nConflicts) {
    rule = (document.querySelector('input[name="mrule"]:checked') || {}).value || 'newer';
    if (document.getElementById('mergeRemember').checked) setMergeRule(rule);
  }
  const included = new Set();
  document.querySelectorAll('#mergeFileList .mfile-chk').forEach(chk => {
    if (chk.checked) included.add(parseInt(chk.dataset.i, 10));
  });
  const ops = prev.files.map((f, i) => {
    if (!included.has(i)) return { rel: f.rel, action: 'skip' };
    if (!f.conflict) return { rel: f.rel, action: 'move' };
    if (rule === 'both') return { rel: f.rel, action: 'keepboth' };
    if (rule === 'skip') return { rel: f.rel, action: 'skip' };
    return { rel: f.rel, action: f.newer === 'src' ? 'overwrite' : 'skip' };
  });
  const btn = document.getElementById('mergeBtn'); btn.disabled = true;
  let res;
  try { res = await pyApi('merge_execute', mergeState.srcPath, mergeState.dstPath, ops); }
  catch (e) { toast('Merge failed: ' + e.message, 'error'); btn.disabled = false; return; }
  if (res.error) { toast(res.error, 'error'); btn.disabled = false; return; }
  closeModal('mergeModal');
  const parts = [];
  if (res.moved) parts.push(res.moved + ' moved');
  if (res.overwritten) parts.push(res.overwritten + ' overwritten');
  if (res.keptboth) parts.push(res.keptboth + ' kept both');
  if (res.skipped) parts.push(res.skipped + ' skipped');
  const nerr = (res.errors || []).length;
  toast('Merged: ' + (parts.join(', ') || 'nothing') + (nerr ? ` · ${nerr} error(s)` : ''), nerr ? 'error' : 'success');
  refreshData();
  if (res.srcEmpty) setTimeout(() => startDelete('local', res.srcPath, res.srcName, true), 450);
}
// ── Main hamburger menu ──
function toggleMainMenu(ev) {
  WD.toggleMenu(ev, 'mainMenu');
}
function openAbout() { showModal('aboutModal'); }
function openSettings() {
  const cur = mergeRule();
  document.querySelectorAll('input[name="setrule"]').forEach(r => { r.checked = (r.value === cur); });
  document.getElementById('setLiveInterval').value = String(liveMs());
  showModal('settingsModal');
}
function saveSettings() {
  const v = (document.querySelector('input[name="setrule"]:checked') || {}).value || 'ask';
  setMergeRule(v);
  const ms = document.getElementById('setLiveInterval').value;
  try { localStorage.setItem('wd-live-ms', ms); } catch (e) {}
  restartLive();
  toast('Settings saved', 'success');
  closeModal('settingsModal');
}

// ── Ownership filter (persisted): 'all' | 'mine' | 'others' ──
function ownerFilter() {
  try { return localStorage.getItem('wd-owner-filter') || 'all'; } catch (e) { return 'all'; }
}
function setOwnerFilter(v) {
  try { localStorage.setItem('wd-owner-filter', v); } catch (e) {}
}
// Toolbar three-way toggle. Applies the filter, syncs the active-button
// highlight, re-renders. Called from onclick on the toolbar buttons.
function setOwnerFilterUI(v) {
  setOwnerFilter(v);
  syncOwnerToggle();
  renderRows();
}
function syncOwnerToggle() {
  const cur = ownerFilter();
  document.querySelectorAll('#ownerToggle .owner-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.owner === cur);
  });
}

/* ── Bulk selection ── */
let lastChkIndex = null;
function onRowChkClick(ev) {
  const el = ev.target;
  if (!el || !el.classList || !el.classList.contains('rowchk')) return;
  const boxes = Array.from(document.querySelectorAll('#rowsContainer .rowchk'));
  const idx = boxes.indexOf(el);
  if (idx === -1) return;
  if (ev.shiftKey && lastChkIndex !== null && lastChkIndex < boxes.length && lastChkIndex !== idx) {
    const state = el.checked;
    const lo = Math.min(lastChkIndex, idx), hi = Math.max(lastChkIndex, idx);
    for (let i = lo; i <= hi; i++) {
      const k = boxes[i].dataset.k;
      if (state) selected.add(k); else selected.delete(k);
    }
  } else {
    const k = el.dataset.k;
    if (el.checked) selected.add(k); else selected.delete(k);
  }
  boxes.forEach(b => { b.checked = selected.has(b.dataset.k); });
  lastChkIndex = idx;
  updateBulkBar(); refreshSelAll();
}
function toggleSelectAll() {
  const on = document.getElementById('selAll').checked;
  document.querySelectorAll('.rowchk').forEach(b => {
    b.checked = on;
    if (on) selected.add(b.dataset.k); else selected.delete(b.dataset.k);
  });
  updateBulkBar();
}
function refreshSelAll() {
  const boxes = document.querySelectorAll('.rowchk');
  const sa = document.getElementById('selAll');
  if (sa) sa.checked = boxes.length > 0 && [...boxes].every(b => b.checked);
}
function clearSelection() {
  selected.clear();
  lastChkIndex = null;
  const sa = document.getElementById('selAll'); if (sa) sa.checked = false;
  updateBulkBar();
}
function updateBulkBar() {
  const n = selected.size;
  document.getElementById('selCount').textContent = n ? n + ' selected' : '';
  let anyPair = false, anyDeletable = false, localFolderCount = 0;
  selected.forEach(k => {
    const d = rowData[k]; if (!d) return;
    if (d.kind === 'pair') { anyPair = true; localFolderCount++; }
    if (d.kind === 'cloud' || d.kind === 'local') anyDeletable = true;
    if (d.kind === 'local') localFolderCount++;
  });
  document.getElementById('bulkSyncTo').style.display = anyPair ? '' : 'none';
  document.getElementById('bulkSyncFrom').style.display = anyPair ? '' : 'none';
  document.getElementById('bulkDeleteBtn').style.display = anyDeletable ? '' : 'none';
  document.getElementById('compareBtn').style.display = (currentTab === 'sites' && localFolderCount >= 2) ? '' : 'none';
}
async function bulkSync(dir) {
  const pairs = [...selected].map(k => rowData[k]).filter(d => d && d.kind === 'pair');
  if (!pairs.length) { toast('Select some matched rows first', 'info'); return; }
  let ok = 0, fail = 0;
  for (const d of pairs) {
    try {
      let r;
      if (dir === 'to-local') r = await pyApi('rename_local', d.localPath, d.cloudName);
      else r = await pyApi('rename_cloud', currentTab, d.cloudId, d.localName);
      if (r && r.error) fail++; else ok++;
    } catch (e) { fail++; }
  }
  toast(`Synced ${ok}${fail ? ' · ' + fail + ' failed' : ''}`, fail ? 'error' : 'success');
  clearSelection(); refreshData();
}
function bulkDelete() {
  const items = [...selected].map(k => rowData[k]).filter(d => d && (d.kind === 'cloud' || d.kind === 'local'));
  if (!items.length) { toast('Bulk delete only applies to cloud-only or local-only rows', 'info'); return; }
  const nCloud = items.filter(d => d.kind === 'cloud').length;
  const nLocal = items.filter(d => d.kind === 'local').length;
  const parts = [];
  if (nCloud) parts.push(`<b>${nCloud}</b> cloud ${currentTab === 'sites' ? 'site(s)' : 'project(s)'}`);
  if (nLocal) parts.push(`<b>${nLocal}</b> local ${currentTab === 'sites' ? 'folder(s) and all their contents' : '.esx file(s)'}`);
  deleteTarget = { bulk: items };
  document.getElementById('deleteTitle').textContent = 'Delete selected?';
  document.getElementById('deleteSub').innerHTML = `Permanently delete ${parts.join(' and ')}. This cannot be undone.`;
  showModal('deleteModal');
}

document.getElementById('searchBox').addEventListener('input', renderRows);
function clearSearch() {
  const sb = document.getElementById('searchBox');
  if (sb.value) { sb.value = ''; renderRows(); }
  sb.focus();
}

/* ── Sync ── */
async function syncRow(dir, cloudId, name, localPath) {
  try {
    let r;
    if (dir === 'to-local') r = await pyApi('rename_local', localPath, name);
    else r = await pyApi('rename_cloud', currentTab, cloudId, name);
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast('Synced', 'success'); refreshData();
  } catch (err) { toast('Sync failed: ' + err.message, 'error'); }
}

/* ── Rename ── */
function startRename(side, idOrPath, name) {
  renameTarget = { side, idOrPath };
  const noun = side === 'cloud'
    ? (currentTab === 'sites' ? 'Cloud Site' : 'Cloud Project')
    : (currentTab === 'sites' ? 'Local Folder' : 'Local .esx File');
  document.getElementById('renameTitle').textContent = 'Rename ' + noun;
  document.getElementById('renameSub').textContent = 'Current: ' + name;
  document.getElementById('renameInput').value = name;
  showModal('renameModal'); document.getElementById('renameInput').select();
}
async function confirmRename() {
  const n = document.getElementById('renameInput').value.trim();
  if (!n || !renameTarget) { closeModal('renameModal'); return; }
  const btn = document.getElementById('renameBtn');
  // Guard: if the button is already in-flight, ignore the click entirely.
  // Prevents rapid double-clicks from firing two concurrent PUTs to Ekahau
  // (which can race and confuse the API even when the first one succeeds).
  if (btn && btn.dataset.busy === '1') return;
  const orig = btn ? btn.textContent : null;
  if (btn) {
    btn.dataset.busy = '1';
    btn.disabled = true;
    btn.textContent = 'Renaming…';
  }
  try {
    let r;
    if (renameTarget.side === 'cloud') r = await pyApi('rename_cloud', currentTab, renameTarget.idOrPath, n);
    else r = await pyApi('rename_local', renameTarget.idOrPath, n);
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast('Renamed', 'success'); closeModal('renameModal'); refreshData();
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    if (btn) {
      btn.dataset.busy = '';
      btn.disabled = false;
      if (orig != null) btn.textContent = orig;
    }
  }
}

/* ── Delete ── */
function startDelete(side, idOrPath, name, isDir) {
  deleteTarget = { side, idOrPath };
  let warn;
  if (side === 'cloud') {
    warn = currentTab === 'sites'
      ? `Permanently delete the cloud site <b>"${e(name)}"</b> from Ekahau Cloud. Projects inside it are not deleted.`
      : `Permanently delete the cloud project <b>"${e(name)}"</b> from Ekahau Cloud. This cannot be undone.`;
  } else {
    warn = isDir
      ? `Delete the local folder <b>"${e(name)}"</b> and <b>everything inside it</b> from disk. This cannot be undone.`
      : `Delete the local file <b>"${e(name)}.esx"</b> from disk. This cannot be undone.`;
    if (isDir) {
      const l = localByPath(idOrPath), s = l && l.src;
      if (s && s.srcCount) {
        const bits = [];
        if (s.plans) bits.push(`${s.plans} floor plan${s.plans > 1 ? 's' : ''}`);
        if (s.images) bits.push(`${s.images} image${s.images > 1 ? 's' : ''}`);
        if (s.other) bits.push(`${s.other} other file${s.other > 1 ? 's' : ''}`);
        warn += `<div class="del-warn">&#9888; This folder holds <b>${s.srcCount} source file${s.srcCount > 1 ? 's' : ''}</b> (${bits.join(', ')} · ${e(s.srcSizeH)}) that are <b>not on Ekahau Cloud</b>. Deleting removes the only copy.</div>`;
      }
    }
  }
  document.getElementById('deleteTitle').textContent = 'Delete?';
  document.getElementById('deleteSub').innerHTML = warn;
  showModal('deleteModal');
}
async function confirmDelete() {
  if (!deleteTarget) { closeModal('deleteModal'); return; }
  try {
    if (deleteTarget.bulk) {
      let ok = 0, fail = 0;
      for (const d of deleteTarget.bulk) {
        try {
          let r;
          if (d.kind === 'cloud') r = await pyApi('delete_cloud', currentTab, d.id);
          else r = await pyApi('delete_local', d.path);
          if (r && r.error) fail++; else ok++;
        } catch (e) { fail++; }
      }
      toast(`Deleted ${ok}${fail ? ' · ' + fail + ' failed' : ''}`, fail ? 'error' : 'success');
      closeModal('deleteModal'); clearSelection(); refreshData();
      return;
    }
    let r;
    if (deleteTarget.side === 'cloud') r = await pyApi('delete_cloud', currentTab, deleteTarget.idOrPath);
    else r = await pyApi('delete_local', deleteTarget.idOrPath);
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast('Deleted', 'success'); closeModal('deleteModal'); refreshData();
  } catch (err) { toast(err.message, 'error'); }
}

/* ── Create ── */
async function createSite() {
  const n = document.getElementById('newSiteName').value.trim();
  if (!n) return;
  const doCloud = document.getElementById('createCloud').checked;
  const doLocal = document.getElementById('createLocal').checked;
  if (!doCloud && !doLocal) { toast('Select at least one destination', 'error'); return; }
  try {
    const results = [];
    if (doCloud) {
      const r = await pyApi('create_site', n);
      if (r && r.error) { toast('Cloud: ' + r.error, 'error'); return; }
      results.push('cloud');
    }
    if (doLocal) {
      const r = await pyApi('create_local_folder', n);
      if (r && r.error) { toast('Local: ' + r.error, 'error'); return; }
      results.push('local');
    }
    const where = results.join(' + ');
    toast('Created "' + n + '" (' + where + ')', 'success'); closeModal('createModal');
    document.getElementById('newSiteName').value = '';
    document.getElementById('createCloud').checked = true;
    document.getElementById('createLocal').checked = true;
    refreshData();
  } catch (err) { toast(err.message, 'error'); }
}
async function createFromLocal(name) {
  try {
    const r = await pyApi('create_site', name);
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast('Created cloud site', 'success'); refreshData();
  } catch (err) { toast(err.message, 'error'); }
}
async function uploadFromLocal(path, name, siteId) {
  const msg = siteId
    ? `Upload "${name}.esx" to Ekahau Cloud and assign to site?`
    : `Upload "${name}.esx" to Ekahau Cloud?`;
  if (!confirm(msg)) return;
  try {
    const r = await pyApi('upload_project', path, siteId || undefined);
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast('Uploaded "' + name + '.esx"', 'success');
    refreshData();
  } catch (err) { toast(err.message, 'error'); }
}

/* ── Folder picker ── */
async function pickFolder() {
  const r = await pyApi('pick_folder');
  if (!r || r.error) { if (r && r.error !== 'No folder selected') toast(r.error, 'error'); return; }
  refreshData();
}

/* ── Create local folder from cloud name ── */
async function createLocalFolder(name) {
  try {
    const r = await pyApi('create_local_folder', name);
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast('Created local folder "' + name + '"', 'success');
    refreshData();
  } catch (err) { toast(err.message, 'error'); }
}

/* ── Move to Site ── */
let _moveToSiteProjectId = null;
async function startMoveToSite(projectId, projectName) {
  _moveToSiteProjectId = projectId;
  document.getElementById('moveToSiteLabel').textContent = 'Project: ' + projectName;
  const sel = document.getElementById('moveToSiteSelect');
  sel.innerHTML = '<option value="">Loading sites…</option>';
  showModal('moveToSiteModal');
  try {
    const d = await pyApi('get_data', 'sites');
    let html = '<option value="">— Select a site —</option>';
    const sites = (d.matched || []).map(p => p.cloud).concat(d.cloudOnly || []);
    sites.sort((x,y) => (x.name||'').localeCompare(y.name||''));
    sites.forEach(s => { html += '<option value="' + a(s.id) + '">' + e(s.name) + '</option>'; });
    html += '<option value="__new__">+ Create new site…</option>';
    sel.innerHTML = html;
  } catch (err) { toast('Could not load sites', 'error'); }
  document.getElementById('moveToSiteNewName').style.display = 'none';
}
function toggleNewSiteInput() {
  const sel = document.getElementById('moveToSiteSelect');
  const inp = document.getElementById('moveToSiteNewName');
  inp.style.display = sel.value === '__new__' ? '' : 'none';
  if (sel.value === '__new__') inp.focus();
}
async function confirmMoveToSite() {
  const sel = document.getElementById('moveToSiteSelect');
  let siteId = sel.value;
  if (siteId === '__new__') {
    const newName = document.getElementById('moveToSiteNewName').value.trim();
    if (!newName) { toast('Enter a site name', 'error'); return; }
    try {
      const r = await pyApi('create_site', newName);
      if (r && r.error) { toast(r.error, 'error'); return; }
      siteId = r.id || r.siteId;
    } catch (err) { toast(err.message, 'error'); return; }
  }
  if (!siteId) { toast('Select a site', 'error'); return; }
  try {
    const r = await pyApi('assign_to_site', siteId, _moveToSiteProjectId);
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast('Moved to site', 'success');
    closeModal('moveToSiteModal');
    refreshData();
  } catch (err) { toast(err.message, 'error'); }
}

// ── Init ──
startAuth();
