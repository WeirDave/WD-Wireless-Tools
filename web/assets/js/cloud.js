

function e(s) { return WD.esc(s); }
function a(s) { return WD.escAttr(s); }

function j(s) { return WD.escJsStr(s); }

function p(s) { return a(String(s == null ? '' : s).replace(/\\/g, '/')); }

function pj(s) { return j(String(s == null ? '' : s).replace(/\\/g, '/')); }

let currentTab = lastFilesKind();
let data = null;
let _outputDir = '';
let dupData = null;
let dupIndex = new Map();
let dupHighlightKey = null;
let activeFilter = 'all';
let activeLetter = null;
let filterUnassigned = false;
let renameTarget = null;
let deleteTarget = null;
let rowData = {};
let selected = new Set();
let collapsed = new Set();
let mergeState = {};
const PROJECT_DIR_STORAGE_KEY = 'wd-project-directory';

const API_MAP = {
  get_status: ['status', []],
  open_ekahau_login: ['open_login', []],
  forget_login: ['forget_login', []],
  get_data: ['get_data', ['kind']],
  rename_cloud: ['rename_cloud', ['kind', 'id', 'name']],
  delete_cloud: ['delete_cloud', ['kind', 'id']],
  create_site: ['create_site', ['name']],
  create_local_folder: ['create_local_folder', ['name']],
  move_local_to_site: ['move_local_to_site', ['path', 'folder']],
  rename_local: ['rename_local', ['path', 'name']],
  delete_local: ['delete_local', ['path']],
  merge_preview: ['merge_preview', ['src', 'dst']],
  merge_execute: ['merge_execute', ['src', 'dst', 'ops']],
  pick_folder: ['pick_folder', []],
  set_folder: ['set_folder', ['path']],
  upload_project: ['upload_project', ['path', 'siteId', 'opId']],
  download_project: ['download_project', ['projectId', 'folder', 'opId']],
  assign_to_site: ['assign_to_site', ['siteId', 'datasetId']],
  reveal_in_explorer: ['reveal_in_explorer', ['path']],
  get_duplicates: ['get_duplicates', []],
  mark_not_match: ['mark_not_match', ['cloudId', 'localPath', 'cloudName', 'localName']],
  unmark_not_match: ['unmark_not_match', ['cloudId', 'localPath']],
  list_not_matches: ['list_not_matches', []],
  mark_manual_match: ['mark_manual_match', ['cloudId', 'localPath', 'cloudName', 'localName']],
  unmark_manual_match: ['unmark_manual_match', ['cloudId', 'localPath']],
  list_manual_matches: ['list_manual_matches', []],
  verify_replace_local: ['verify_replace_local', ['cloudId', 'localPath']],
  list_shares: ['list_shares', ['projectId']],
  add_share: ['add_share', ['projectId', 'email', 'role']],
  remove_share: ['remove_share', ['projectId', 'email']],
  change_share_role: ['change_share_role', ['projectId', 'email', 'role']],
  toggle_group_share: ['toggle_group_share', ['projectId', 'groupId', 'groupName', 'role', 'enable']],
  transfer_ownership: ['transfer_ownership', ['projectId', 'newOwnerEmail']],
  bulk_share: ['bulk_share', ['projectIds', 'emails', 'role', 'shareWithGroup', 'groupId', 'groupName', 'groupRole']],
  get_my_group: ['get_my_group', ['groupName']],
  add_group_member: ['add_group_member', ['email', 'groupName']],
  remove_group_member: ['remove_group_member', ['email', 'groupName']],
  refresh_group_shares: ['refresh_group_shares', ['groupName', 'dryRun', 'projectIds']],
};
async function pyApi(method, ...args) {
  const entry = API_MAP[method];
  if (!entry) throw new Error('unknown api: ' + method);
  const [action, keys] = entry;
  const body = {};
  keys.forEach((k, i) => { body[k] = args[i]; });
  const r = await fetch('/api/cloud/' + action, {
    method: 'POST', headers: {
      'Content-Type': 'application/json',
      'X-WD-Wireless-Tools': '1',
    },
    body: JSON.stringify(body),
  });
  return await r.json();
}

const _ops = new Map();
const _opOrder = [];
let _deckPollTimer = null;
let _deckTickTimer = null;
let _postOpRefreshTimer = null;
const _UNDO_WINDOW_MS = 60_000;
const _DONE_LINGER_MS = 8_000;
const _POST_OP_REFRESH_MS = 400;

function _scheduleOpRefresh() {
  if (_postOpRefreshTimer) clearTimeout(_postOpRefreshTimer);
  _postOpRefreshTimer = setTimeout(() => {
    _postOpRefreshTimer = null;

    if (typeof refreshData === 'function') refreshData(true);
  }, _POST_OP_REFRESH_MS);
}

function newOpId() {
  return 'op-' + Math.random().toString(36).slice(2, 12);
}

function _deckEl() { return document.getElementById('opsDeck'); }
function _deckBody() { return document.getElementById('opsDeckBody'); }

function _opIcon(op) {
  if (op.status === 'running')   return '↻';
  if (op.status === 'done')      return '✓';
  if (op.status === 'failed')    return '⚠';
  if (op.status === 'cancelled') return '⊘';
  return '⏸';
}
function _opActionsHtml(op) {
  const btns = [];
  if (op.status === 'running' && op.cancelable !== false) {
    btns.push(`<button class="op-btn" onclick="opCancel('${op.id}')">Cancel</button>`);
  }
  if (op.status === 'failed' && op.retryFn) {
    btns.push(`<button class="op-btn primary" onclick="opRetry('${op.id}')">Retry</button>`);
  }
  if (op.status === 'done' && op.undoable && op.undoFn && Date.now() < op.undoExpiresAt) {
    const secLeft = Math.max(0, Math.ceil((op.undoExpiresAt - Date.now()) / 1000));
    btns.push(`<button class="op-btn primary" onclick="opUndo('${op.id}')">Undo</button><span class="op-undo-timer">${secLeft}s</span>`);
  }
  if (op.status === 'done' || op.status === 'failed' || op.status === 'cancelled') {
    btns.push(`<button class="op-btn" onclick="_opRemove('${op.id}')" title="Dismiss">&times;</button>`);
  }
  return btns.join('');
}

function _titleForStatus(op) {
  const t = op.title || 'Working…';
  if (op.status === 'running' || op.status === 'queued') return t;
  const inflections = [
    [/^Renaming /, 'Renamed '],
    [/^Moving /, 'Moved '],
    [/^Downloading /, 'Downloaded '],
    [/^Uploading /, 'Uploaded '],
    [/^Deleting /, 'Deleted '],
    [/^Merging /, 'Merged '],
    [/^Creating /, 'Created '],
    [/^Undo: /, 'Undid: '],
  ];
  if (op.status === 'done') {
    for (const [re, sub] of inflections) if (re.test(t)) return t.replace(re, sub);
    return t;
  }
  if (op.status === 'failed') {

    const failMap = [
      [/^Renaming /, 'Failed to rename '],
      [/^Moving /,   'Failed to move '],
      [/^Downloading /, 'Failed to download '],
      [/^Uploading /,   'Failed to upload '],
      [/^Deleting /, 'Failed to delete '],
      [/^Merging /,  'Failed to merge '],
      [/^Creating /, 'Failed to create '],
      [/^Undo: /,    'Undo failed: '],
    ];
    for (const [re, sub] of failMap) if (re.test(t)) return t.replace(re, sub);
    return 'Failed: ' + t;
  }
  if (op.status === 'cancelled') {
    const cancelMap = [
      [/^Renaming /, 'Cancelled rename: '],
      [/^Moving /,   'Cancelled move: '],
      [/^Downloading /, 'Cancelled download: '],
      [/^Uploading /,   'Cancelled upload: '],
    ];
    for (const [re, sub] of cancelMap) if (re.test(t)) return t.replace(re, sub);
    return 'Cancelled: ' + t;
  }
  return t;
}
function _opCardHtml(op) {
  const isIndeterminate = op.status === 'running' && (op.progress == null || op.progress === 0);
  const pct = Math.max(0, Math.min(100, op.progress || 0));
  const showBar = op.status === 'running' || op.status === 'queued';
  const stageLine = op.status === 'failed' && op.error
    ? `<div class="op-stage err">${e(op.error)}</div>`
    : (op.stage ? `<div class="op-stage">${e(op.stage)}</div>` : '');
  return `
    <div class="op-card status-${op.status}" data-op-id="${op.id}">
      <span class="op-icon">${_opIcon(op)}</span>
      <div class="op-mid">
        <div class="op-title">${e(_titleForStatus(op))}</div>
        ${stageLine}
        ${showBar ? `<div class="op-bar"><div class="op-bar-fill${isIndeterminate ? ' indeterminate' : ''}"${isIndeterminate ? '' : ` style="--op-progress:${pct}%"`}></div></div>` : ''}
      </div>
      <div class="op-actions">${_opActionsHtml(op)}</div>
    </div>`;
}
function _deckRender() {
  const deck = _deckEl();
  const body = _deckBody();
  if (!deck || !body) return;
  const ops = _opOrder.map(id => _ops.get(id)).filter(Boolean);
  if (!ops.length) {
    deck.dataset.state = 'hidden';
    return;
  }

  if (deck.dataset.state === 'hidden') deck.dataset.state = 'expanded';

  const running = ops.filter(o => o.status === 'running').length;
  const queued  = ops.filter(o => o.status === 'queued').length;
  const done    = ops.filter(o => o.status === 'done').length;
  const failed  = ops.filter(o => o.status === 'failed').length;
  const parts = [];
  if (running) parts.push(`${running} running`);
  if (queued)  parts.push(`${queued} queued`);
  if (done)    parts.push(`✓ ${done}`);
  if (failed)  parts.push(`⚠ ${failed}`);
  document.getElementById('opsDeckSummary').textContent =
    parts.length ? parts.join(' · ') : `${ops.length} operations`;

  body.innerHTML = ops.slice().reverse().map(_opCardHtml).join('');
}
function _deckToggle() {
  const deck = _deckEl();
  if (!deck) return;
  if (deck.dataset.state === 'hidden') return;
  deck.dataset.state = deck.dataset.state === 'collapsed' ? 'expanded' : 'collapsed';
}
function _deckHide() {
  const deck = _deckEl();
  if (deck) deck.dataset.state = 'hidden';
}
function _deckClearDone() {
  for (const id of [..._opOrder]) {
    const op = _ops.get(id);
    if (!op) continue;
    if (op.status === 'done' || op.status === 'failed' || op.status === 'cancelled') {
      _opRemove(id);
    }
  }

  if (_verifyFailedPairs.size) {
    _verifyFailedPairs.clear();
    if (typeof renderRows === 'function') renderRows();
  }
}

const _verifyFailedPairs = new Set();

function _verifyFailedKey(cloudId, localPath) {
  return String(cloudId || '') + '||' + String(localPath || '').replace(/\\/g, '/');
}
function _verifyFailedClass(r) {
  if (!r || !r.cloud || !r.local) return '';
  return _verifyFailedPairs.has(_verifyFailedKey(r.cloud.id, r.local.path)) ? ' verify-failed' : '';
}
function _opRemove(id) {
  _ops.delete(id);
  const idx = _opOrder.indexOf(id);
  if (idx >= 0) _opOrder.splice(idx, 1);
  _deckRender();
}

function _ensureDeckTick() {
  if (_deckTickTimer) return;
  _deckTickTimer = setInterval(() => {
    let changed = false;
    const now = Date.now();
    for (const [id, op] of [..._ops.entries()]) {
      if (op.status === 'done') {
        if (op.undoable && op.undoFn) {
          if (now >= op.undoExpiresAt) {

            op.undoable = false;
            op.undoFn = null;
            op.finishedAt = op.finishedAt || now;
            changed = true;
          } else changed = true;
        } else if (op.finishedAt && now - op.finishedAt > _DONE_LINGER_MS) {
          _opRemove(id);
          changed = true;
        }
      }
    }
    if (changed) _deckRender();
    if (_ops.size === 0) {
      clearInterval(_deckTickTimer);
      _deckTickTimer = null;
    }
  }, 1000);
}

function _ensureDeckPoll() {
  if (_deckPollTimer) return;
  _deckPollTimer = setInterval(async () => {
    const running = _opOrder
      .map(id => _ops.get(id))
      .filter(o => o && o.status === 'running' && o.pollBackend);
    if (!running.length) {
      clearInterval(_deckPollTimer);
      _deckPollTimer = null;
      return;
    }
    let changed = false;
    for (const op of running) {
      try {
        const r = await fetch('/api/cloud/progress?id=' + encodeURIComponent(op.id));
        const p = await r.json();
        if (p && typeof p.current === 'number' && p.total) {
          const pct = Math.round(100 * p.current / p.total);
          if (pct !== op.progress) { op.progress = pct; changed = true; }
        }
        if (p && p.message && p.message !== op.stage) {
          op.stage = p.message; changed = true;
        }
      } catch (e) {  }
    }
    if (changed) _deckRender();
  }, 250);
}

function opEnqueue(spec) {
  const id = newOpId();
  const op = {
    id,
    title: spec.title || 'Working…',
    sub: spec.sub || '',
    type: spec.type || 'op',
    status: 'queued',
    progress: null,
    stage: 'Queued…',
    error: null,
    undoable: !!spec.undoable,
    undoFn: spec.undoFn || null,
    retryFn: spec.retryFn || null,
    pollBackend: spec.pollBackend !== false,
    cancelable: spec.cancelable !== false,
    cancelFlag: { aborted: false },
    startedAt: null,
    finishedAt: null,
    undoExpiresAt: 0,
    _run: spec.run,
  };
  _ops.set(id, op);
  _opOrder.push(id);
  _deckRender();
  _ensureDeckTick();

  const promise = (async () => {
    op.status = 'running';
    op.startedAt = Date.now();
    op.stage = 'Starting…';
    if (op.pollBackend) _ensureDeckPoll();
    _deckRender();
    try {
      const result = await spec.run(id, op.cancelFlag);

      if (result && result.error) {
        op.status = 'failed';
        op.error = result.error;
        op.finishedAt = Date.now();
        _deckRender();
        _scheduleOpRefresh();
        return result;
      }
      op.status = op.cancelFlag.aborted ? 'cancelled' : 'done';
      op.progress = 100;
      op.stage = op.cancelFlag.aborted ? 'Cancelled' : 'Done';
      op.finishedAt = Date.now();
      if (op.undoable && op.undoFn && op.status === 'done') {
        op.undoExpiresAt = Date.now() + _UNDO_WINDOW_MS;
      }
      _deckRender();
      _scheduleOpRefresh();
      return result;
    } catch (err) {
      op.status = 'failed';
      op.error = (err && err.message) || String(err) || 'Failed';
      op.finishedAt = Date.now();
      _deckRender();
      _scheduleOpRefresh();
      throw err;
    }
  })();
  return { id, promise };
}

function opCancel(id) {
  const op = _ops.get(id);
  if (!op || op.status !== 'running') return;
  op.cancelFlag.aborted = true;
  op.stage = 'Cancelling…';
  _deckRender();
}

async function opUndo(id) {
  const op = _ops.get(id);
  if (!op || !op.undoable || !op.undoFn) return;
  const fn = op.undoFn;
  const title = 'Undo: ' + op.title;

  op.undoable = false;
  op.undoFn = null;
  _deckRender();
  opEnqueue({ title, type: 'undo', undoable: false, pollBackend: false, run: async () => fn() });
}

async function opRetry(id) {
  const op = _ops.get(id);
  if (!op || !op.retryFn) return;
  const fn = op.retryFn;
  const title = op.title;
  _opRemove(id);
  opEnqueue({ title, type: op.type, run: async (newId, flag) => fn(newId, flag) });
}

async function runWithProgress(opts, fn) {
  const { promise } = opEnqueue({
    title: opts.title,
    sub: opts.subtitle,
    type: opts.type || 'work',
    pollBackend: true,
    run: (opId) => fn(opId),
  });
  return promise;
}

function setAuthState(s) {
  document.getElementById('authChecking').style.display = s === 'checking' ? '' : 'none';
  document.getElementById('authLogin').hidden = s !== 'login';
  document.getElementById('authWaiting').hidden = s !== 'waiting';
}
async function startAuth() {
  setAuthState('checking');
  try {
    let s = await pyApi('get_status');
    const remembered = rememberedProjectDirectory();
    if (remembered && remembered !== s.outputDir) {
      const restored = await pyApi('set_folder', remembered);
      if (restored && restored.path) s = { ...s, outputDir: restored.path };
      else forgetRememberedProjectDirectory();
    } else if (!remembered && s.outputDir) {
      rememberProjectDirectory(s.outputDir);
    }
    if (s.connected) { showApp(s.email); return; }
  } catch (e) {}
  setAuthState('login');
}

function rememberedProjectDirectory() {
  try { return localStorage.getItem(PROJECT_DIR_STORAGE_KEY) || ''; } catch (e) { return ''; }
}
function rememberProjectDirectory(path) {
  if (!path) return;
  try { localStorage.setItem(PROJECT_DIR_STORAGE_KEY, path); } catch (e) {}
}
function forgetRememberedProjectDirectory() {
  try { localStorage.removeItem(PROJECT_DIR_STORAGE_KEY); } catch (e) {}
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

async function forgetCloudLogin() {
  if (!confirm('Forget the saved Ekahau Cloud login on this computer?\n\nYou can reconnect at any time using your browser.')) return;
  const result = await pyApi('forget_login');
  if (result.error) {
    toast(result.error, 'error');
    return;
  }
  stopLive();
  data = null;
  dupData = null;
  document.getElementById('appScreen').style.display = 'none';
  document.getElementById('setupScreen').hidden = true;
  document.getElementById('loginScreen').style.display = '';
  setAuthState('login');
}

async function showApp(email) {
  const status = await pyApi('get_status');
  _outputDir = status.outputDir || '';
  rememberProjectDirectory(_outputDir);
  if (!status.outputDir) {
    document.getElementById('loginScreen').style.display = 'none';
    document.getElementById('setupScreen').hidden = false;
    document.getElementById('setupEmail').textContent = email || '';
    return;
  }
  goToDashboard(email);
}
function goToDashboard(email) {
  document.getElementById('loginScreen').style.display = 'none';
  document.getElementById('setupScreen').hidden = true;
  document.getElementById('appScreen').style.display = 'flex';
  document.getElementById('userEmail').textContent = email || 'Connected';
  syncOwnerToggle();
  _syncTabUI(currentTab);
  refreshData();
  if (liveWanted()) startLive();
}

function liveMs() { try { return parseInt(localStorage.getItem('wd-live-ms')) || 30000; } catch (e) { return 30000; } }
let liveTimer = null;
let liveCountdown = 0;

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
      document.getElementById('setupFolderPath').hidden = false;
      document.getElementById('setupContinueBtn').hidden = false;
    }
  } catch (err) { toast(err.message, 'error'); }
}
async function setupContinue() { const s = await pyApi('get_status'); goToDashboard(s.email); }
function setupSkip() { goToDashboard(document.getElementById('setupEmail').textContent); }

function lastFilesKind() {
  try { return localStorage.getItem('wd-files-kind') || 'sites'; } catch (e) { return 'sites'; }
}
function _syncTabUI(kind) {
  document.getElementById('tabFilesGroup').classList.toggle('active', kind !== 'duplicates');
  document.getElementById('viewTreeBtn').classList.toggle('active', kind === 'sites');
  document.getElementById('viewFlatBtn').classList.toggle('active', kind === 'projects');
  document.getElementById('tabDuplicates').classList.toggle('active', kind === 'duplicates');
  document.getElementById('addNewBtn').style.display = kind === 'sites' ? '' : 'none';
  document.getElementById('expandAllBtn').hidden = kind !== 'sites';
  document.getElementById('collapseAllBtn').hidden = kind !== 'sites';
  const ownerEl = document.getElementById('ownerToggle');
  if (ownerEl) ownerEl.hidden = (kind === 'duplicates');

  const dupTbBtn = document.getElementById('dupDeleteAllToolbarBtn');
  if (dupTbBtn && kind !== 'duplicates') dupTbBtn.hidden = true;
  document.querySelectorAll('.dash-card').forEach(c => c.classList.toggle('active', c.dataset.filter === activeFilter));
}
function switchTab(kind) {
  if (kind === currentTab) return;
  currentTab = kind;
  if (kind === 'sites' || kind === 'projects') {
    try { localStorage.setItem('wd-files-kind', kind); } catch (e) {}
  }
  _syncTabUI(kind);
  refreshData();
}

function expandAllSites() {
  collapsed.clear();
  renderRows();
}
function collapseAllSites() {
  if (!data) return;
  (data.matched || []).forEach(p => collapsed.add('site:' + p.cloud.id));
  (data.cloudOnly || []).forEach(s => collapsed.add('site:' + s.id));
  (data.localOnly || []).forEach(f => collapsed.add('folder:' + f.path));
  renderRows();
}

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

  buildDupIndexFromData(d);
  updateDashboard();
  renderDuplicates();
}

function indexRowData() {
  rowData = {};
  (data.matched || []).forEach(p => {
    rowData['p:' + p.cloud.id] = {
      kind: 'pair', cloudId: p.cloud.id, cloudName: p.cloud.name,
      localName: p.local.name, localPath: p.local.path,
      mismatch: p.namesDiffer,
      matchType: p.matchType,

      cloudOwner: (p.cloud.owner || ''),
      siteName: p.cloud.siteName || '',
      entityKind: 'sites',
    };
    // Independent per-side entries — same pattern as the ct-c:/ct-l: keys
    // nested project rows already use — so a matched site's cloud side and
    // local side can be selected (and bulk deleted) independently instead
    // of only as a single all-or-nothing pair.
    rowData['s-c:' + p.cloud.id] = {
      kind: 'cloud', id: p.cloud.id, name: p.cloud.name,
      cloudOwner: (p.cloud.owner || ''),
      siteName: p.cloud.siteName || '',
      entityKind: 'sites',
    };
    rowData['s-l:' + p.local.path] = {
      kind: 'local', path: p.local.path, name: p.local.name, isDir: true,
      entityKind: 'sites',
    };
  });
  (data.cloudOnly || []).forEach(s => {
    rowData['c:' + s.id] = {
      kind: 'cloud', id: s.id, name: s.name,
      cloudOwner: (s.owner || ''),

      siteName: s.siteName || '',
    };
  });
  (data.localOnly || []).forEach(f => { rowData['l:' + f.path] = { kind: 'local', path: f.path, name: f.name, isDir: f.isDir }; });

  const indexChildren = (children, parentSite) => {
    if (!children) return;
    (children.matched || []).forEach(p => {

      rowData['ct:' + p.cloud.id] = {
        kind: 'pair', cloudId: p.cloud.id, cloudName: p.cloud.name,
        localName: p.local.name, localPath: p.local.path,
        mismatch: p.namesDiffer,
        matchType: p.matchType,
        cloudOwner: (p.cloud.owner || ''),
        siteName: parentSite || p.cloud.siteName || '',
        entityKind: 'projects',
      };
      rowData['ct-c:' + p.cloud.id] = {
        kind: 'cloud', id: p.cloud.id, name: p.cloud.name,
        cloudOwner: (p.cloud.owner || ''),
        siteName: parentSite || p.cloud.siteName || '',
        entityKind: 'projects',
      };
      rowData['ct-l:' + p.local.path] = {
        kind: 'local', path: p.local.path, name: p.local.name, isDir: false,
        entityKind: 'projects',
      };
    });
    (children.cloudOnly || []).forEach(c => {
      rowData['ct:' + c.id] = {
        kind: 'cloud', id: c.id, name: c.name,
        cloudOwner: (c.owner || ''),
        siteName: parentSite || c.siteName || '',
        entityKind: 'projects',
      };
    });
    (children.localOnly || []).forEach(l => {
      rowData['ct:' + l.path] = {
        kind: 'local', path: l.path, name: l.name, isDir: !!l.isDir,
        entityKind: 'projects',
      };
    });
  };
  (data.matched || []).forEach(p => indexChildren(p.cloud && p.cloud.children, p.cloud.name));
  (data.cloudOnly || []).forEach(s => indexChildren(s.children, s.name));
  (data.localOnly || []).forEach(f => indexChildren(f.children, f.name));
}

function _passOwnerForCounts(cloudObj, localObj) {
  const own = ownerFilter();
  if (own === 'all') return true;
  const me = ((data && data.currentUser) || '').toLowerCase();
  if (!me) return true;
  const co = (cloudObj && cloudObj.owner || '').toLowerCase();
  const lo = (localObj && localObj.owner || '').toLowerCase();
  const otherCloud = co && co.indexOf('@') > -1 && co !== me;
  const otherLocal = lo && lo.indexOf('@') > -1 && lo !== me;
  if (own === 'mine')   return !otherCloud && !otherLocal;
  if (own === 'others') return otherCloud || otherLocal;
  return true;
}


function _isExternal(cloudObj, localObj) {
  const me = ((data && data.currentUser) || '').toLowerCase();
  if (!me) return false;
  const co = (cloudObj && cloudObj.owner || '').toLowerCase();
  const lo = (localObj && localObj.owner || '').toLowerCase();
  const otherCloud = co && co.indexOf('@') > -1 && co !== me;
  const otherLocal = lo && lo.indexOf('@') > -1 && lo !== me;
  return !!(otherCloud || otherLocal);
}


function _siteHasExternal(cloudObj, localObj) {
  if (_isExternal(cloudObj, localObj)) return true;
  const kids = (cloudObj && cloudObj.children) || (localObj && localObj.children) || null;
  if (!kids) return false;
  return (kids.matched || []).some(p => _isExternal(p.cloud, p.local))
      || (kids.cloudOnly || []).some(c => _isExternal(c, null))
      || (kids.localOnly || []).some(l => _isExternal(null, l));
}

function _siteOwnedVisible(cloudObj, localObj) {
  const children = (cloudObj && cloudObj.children) || (localObj && localObj.children) || null;
  const own = ownerFilter();
  const hasKids = !!children && (children.matched.length || children.cloudOnly.length || children.localOnly.length);
  if (!hasKids) return own !== 'others';
  return (children.matched || []).some(p => _passOwnerForCounts(p.cloud, p.local))
      || (children.cloudOnly || []).some(c => _passOwnerForCounts(c, null))
      || (children.localOnly || []).some(l => _passOwnerForCounts(null, l));
}

function updateDashboard() {
  const isDup = currentTab === 'duplicates';
  const isProj = currentTab === 'projects';

  const stdCards = ['allcard', 'mismatches', 'orphans', 'cloud-only', 'local-only'];
  stdCards.forEach(cls => {
    document.querySelectorAll('.dash-card.' + cls).forEach(el => {
      el.style.display = isDup ? 'none' : '';
    });
  });

  ['dDupAllCard', 'dDupMixedCard', 'dDupLocalCard', 'dDupCloudCard'].forEach(id => {
    document.getElementById(id).hidden = !isDup;
  });

  if (isDup) {
    const s = (dupData && dupData.summary) || { total: 0, mixed: 0, localOnly: 0, cloudOnly: 0 };
    document.getElementById('dDupAll').textContent = s.total;
    document.getElementById('dDupMixed').textContent = s.mixed;
    document.getElementById('dDupLocal').textContent = s.localOnly;
    document.getElementById('dDupCloud').textContent = s.cloudOnly;
  } else if (data && data.summary) {

    const ownerVisible = currentTab === 'sites' ? _siteOwnedVisible : _passOwnerForCounts;
    let matched = 0, mismatches = 0, cloudOnly = 0, localOnly = 0, nameMatches = 0;
    let externalCount = 0;

    const typeCount = { Design: 0, Measured: 0, Hybrid: 0 };
    const bumpType = (a, b) => {
      const t = (a && a.projectType) || (b && b.projectType);
      if (t && typeCount[t] !== undefined) typeCount[t]++;
    };





    const isSitesTab = currentTab === 'sites';
    const rowIsExternal = (c, l) => isSitesTab ? _siteHasExternal(c, l) : _isExternal(c, l);
    const walkKids = (kids) => {
      if (!kids) return;
      (kids.matched || []).forEach(p => {
        if (p.matchType === 'exact') nameMatches++;
        bumpType(p.cloud, p.local);
      });
      (kids.cloudOnly || []).forEach(c => { bumpType(c, null); });
      (kids.localOnly || []).forEach(l => { bumpType(null, l); });
    };
    let externalOrphans = 0;
    (data.matched || []).forEach(p => {
      if (!ownerVisible(p.cloud, p.local)) return;
      matched++;
      if (p.namesDiffer) mismatches++;
      if (rowIsExternal(p.cloud, p.local)) externalCount++;
      if (isSitesTab) {
        walkKids((p.cloud && p.cloud.children) || (p.local && p.local.children));
      } else {
        if (p.matchType === 'exact') nameMatches++;
        bumpType(p.cloud, p.local);
      }
    });
    (data.cloudOnly || []).forEach(c => {
      if (!ownerVisible(c, null)) return;
      cloudOnly++;
      if (rowIsExternal(c, null)) { externalCount++; externalOrphans++; }
      if (isSitesTab) walkKids(c.children);
      else bumpType(c, null);
    });
    (data.localOnly || []).forEach(l => {
      if (!ownerVisible(null, l)) return;
      localOnly++;
      if (rowIsExternal(null, l)) { externalCount++; externalOrphans++; }
      if (isSitesTab) walkKids(l.children);
      else bumpType(null, l);
    });
    document.getElementById('dAll').textContent = matched + cloudOnly + localOnly;
    document.getElementById('dMismatches').textContent = mismatches;
    document.getElementById('dNameMatches').textContent = nameMatches;


    document.getElementById('dOrphans').textContent = Math.max(0, cloudOnly + localOnly - externalOrphans);
    document.getElementById('dCloudOnly').textContent = cloudOnly;
    document.getElementById('dLocalOnly').textContent = localOnly;
    const dExt = document.getElementById('dExternal');
    if (dExt) dExt.textContent = externalCount;
    const dExtCard = document.getElementById('dExternalCard');
    if (dExtCard) dExtCard.hidden = isDup || externalCount === 0;
    document.getElementById('dTypeDesign').textContent = typeCount.Design;
    document.getElementById('dTypeMeasured').textContent = typeCount.Measured;
    document.getElementById('dTypeHybrid').textContent = typeCount.Hybrid;
  }

  ['dNameMatchesCard', 'dTypeDesignCard', 'dTypeMeasuredCard', 'dTypeHybridCard'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.hidden = isDup;
  });
  const uCard = document.getElementById('dUnassignedCard');
  uCard.hidden = !isProj;
  if (isProj && data) {
    let noSite = 0;
    (data.matched || []).forEach(p => {
      if (p.cloud && !p.cloud.hasSite && _passOwnerForCounts(p.cloud, p.local)) noSite++;
    });
    (data.cloudOnly || []).forEach(c => {
      if (!c.hasSite && _passOwnerForCounts(c, null)) noSite++;
    });
    document.getElementById('dUnassigned').textContent = noSite;
  }
  if (!isProj && activeFilter === 'unassigned') { activeFilter = 'all'; }
  document.querySelectorAll('.dash-card').forEach(c => c.classList.toggle('active', c.dataset.filter === activeFilter));
}
function setFilter(f) {

  if (f === 'synced') f = 'all';
  activeFilter = activeFilter === f ? 'all' : f;
  document.querySelectorAll('.dash-card').forEach(c => c.classList.toggle('active', c.dataset.filter === activeFilter));
  renderRows();
}

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
  _renderJumpNav();
}

let _jumpNavPresentCache = new Set();
function _renderJumpNav() {
  const nav = document.getElementById('jumpNav');
  if (!nav) return;
  if (currentTab === 'duplicates') { nav.style.display = 'none'; return; }
  nav.style.display = '';
  const container = document.getElementById('rowsContainer');

  if (!activeLetter) {
    const fresh = new Set();
    container.querySelectorAll('[data-jump-letter]').forEach(el => {

      if (!el.classList.contains('empty-letter')) fresh.add(el.dataset.jumpLetter);
    });
    if (fresh.size) _jumpNavPresentCache = fresh;
  }
  const present = new Set(_jumpNavPresentCache);

  if (activeLetter) present.add(activeLetter);
  const letters = ['#', ...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')];

  const allActive = activeLetter === null;
  const allChip = `<button class="jump-letter jump-all${allActive ? ' active' : ''}"
                           onclick="_clearJumpLetter()"
                           title="${allActive ? 'Showing all letters' : 'Clear letter filter — show all'}">All</button>`;
  const letterChips = letters.map(L => {
    const enabled = present.has(L);
    const isActive = activeLetter === L;
    const cls = 'jump-letter'
      + (enabled ? '' : ' disabled')
      + (isActive ? ' active' : '');
    const title = isActive
      ? 'Showing only ' + L + ' — click to clear'
      : (enabled ? 'Show only ' + L : 'No sites here');
    return `<button class="${cls}" data-letter="${e(L)}"
                    ${enabled ? `onclick="_jumpToLetter('${e(L)}')"` : 'disabled tabindex="-1"'}
                    title="${title}">${e(L)}</button>`;
  }).join('');
  nav.innerHTML = allChip + letterChips;
}
function _clearJumpLetter() {
  if (activeLetter === null) return;
  activeLetter = null;
  renderRows();
  const rc = document.getElementById('rowsContainer');
  if (rc) rc.scrollTop = 0;
}

function _jumpToLetter(L) {
  activeLetter = (activeLetter === L) ? null : L;
  renderRows();

  const rc = document.getElementById('rowsContainer');
  if (rc) rc.scrollTop = 0;
}

function refreshDupIndex() {

  pyApi('get_duplicates')
    .then(d => {
      if (!d || d.error) return;
      buildDupIndexFromData(d);

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
  return ` <span class="dup-hint" title="Part of a duplicate cluster — click to inspect" onclick="event.stopPropagation();jumpToCluster('${j(key)}')">&#8776;</span>`;
}

function jumpToCluster(clusterKey) {
  dupHighlightKey = clusterKey;
  if (currentTab === 'duplicates') {

    scrollToCluster(clusterKey);
  } else {
    switchTab('duplicates');

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

function renderDuplicates() {
  const el = document.getElementById('rowsContainer');
  const legend = document.querySelector('.col-legend');
  if (legend) legend.style.display = 'none';

  const clusters = (dupData && dupData.clusters) || [];

  let filtered = clusters;
  if (activeFilter === 'dup-mixed')      filtered = clusters.filter(c => c.shape === 'mixed');
  else if (activeFilter === 'dup-local') filtered = clusters.filter(c => c.shape === 'local-only');
  else if (activeFilter === 'dup-cloud') filtered = clusters.filter(c => c.shape === 'cloud-only');

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

  const totalExtras = filtered.reduce(
    (n, cl) => n + cl.items.filter(i => !i.matched).length, 0);
  const tbBtn = document.getElementById('dupDeleteAllToolbarBtn');
  const tbCount = document.getElementById('dupDeleteAllToolbarCount');
  if (tbBtn) tbBtn.hidden = totalExtras <= 0;
  if (tbCount) tbCount.textContent = totalExtras;

  let h = `<div class="dup-explain">
    <div class="dup-explain-title">What am I looking at?</div>
    <div class="dup-explain-body">
    Clusters of files that share a <b>normalized name</b> <span class="dup-explain-hint">(punctuation, spacing, and case ignored — so <code>SITE1-100-Baseline</code> matches <code>SITE1 100 Baseline</code>)</span> AND have <b>at least one extra copy beyond the normal cloud↔local pair</b>.
      Every row is bookended in <b class="blue">blue</b> (cloud) or <b class="green">green</b> (local). Rows tagged <span class="dup-pill matched">matched</span> are the cloud↔local pair you should keep. Rows with an <b class="amber">amber outline</b> are the extras — those are the ones to delete or merge.
    </div>
    <div class="dup-explain-legend">
      <span class="dup-explain-tag mixed">Mixed</span> — matched pair PLUS at least one extra copy on one side &nbsp;·&nbsp;
      <span class="dup-explain-tag local-only">Local only</span> — same file saved in <b>multiple local folders</b> &nbsp;·&nbsp;
      <span class="dup-explain-tag cloud-only">Cloud only</span> — same project uploaded to Ekahau <b>more than once</b>
    </div>
  </div>
  <div id="dupBulkBar" class="dup-bulk-bar">
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

  if (dupHighlightKey) {
    const target = dupHighlightKey;
    dupHighlightKey = null;
    requestAnimationFrame(() => scrollToCluster(target));
  }
}

function renderCluster(cl) {
  const kAttr = j(cl.key);
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

  const matchedCount = cl.items.filter(i => i.matched).length;
  const extraCount = cl.items.length - matchedCount;
  const hasPair = matchedCount >= 2 && extraCount >= 1;
  const allExtras = matchedCount === 0;
  h += `<span class="manual-count" id="dupManual-${kAttr}">0 selected</span>`;
  h += `<span class="spacer"></span>`;

  if (cl.shape !== 'mixed' && allExtras) {

    h += `<button class="btn btn-sec btn-sm" onclick="dupKeep('${kAttr}','newest')">Keep newest — delete rest</button>`;
    h += `<button class="btn btn-sec btn-sm" onclick="dupKeep('${kAttr}','largest')">Keep largest — delete rest</button>`;
  } else if (hasPair) {

    h += `<button class="btn btn-amber btn-sm" onclick="dupDeleteExtras('${kAttr}')" title="Deletes only the ${extraCount} unmatched extra${extraCount !== 1 ? 's' : ''} — the matched cloud↔local pair stays intact.">&#128465; Delete ${extraCount} extra${extraCount !== 1 ? 's' : ''} (keep the pair)</button>`;
  }
  h += `<button class="btn btn-red btn-sm" onclick="dupDeleteChecked('${kAttr}')">Delete checked</button>`;
  h += `</div>`;

  h += `<div class="dup-items">`;
  cl.items.forEach((it, idx) => {
    const iid = it.id || it.path;
    const sideCls = it.side === 'cloud' ? 'cloud' : 'local';
    const sideIcon = it.side === 'cloud' ? '&#9729;' : '&#128187;';
    const rowCls = ['dup-item', 'side-' + sideCls];

    if (it.matched) rowCls.push('is-matched');
    else rowCls.push('is-extra');
    const dateStr = it.mtime ? `${fmtExactDate(it.mtime)} · ${fmtRelDate(it.mtime)}` : '—';
    const sizeStr = fmtBytes(it.size);

    h += `<div class="${rowCls.join(' ')}" data-iid="${a(iid)}">`;
    h += `<input type="checkbox" class="dup-item-check" onchange="dupChkChanged('${kAttr}')">`;
    h += `<span class="dup-item-side ${sideCls}">${sideIcon}</span>`;

    const loc = it.location || (it.side === 'cloud' ? '(no site)' : '');
    const owner = it.owner ? `<span class="dup-item-owner">· ${e(it.owner)}</span>` : '';
    const matchedPill = it.matched ? '<span class="dup-pill matched">matched</span>' : '';
    h += `<div>
      <div class="dup-item-name">${e(it.name)}${matchedPill}</div>
      <div class="dup-item-loc">${e(loc)} ${owner}</div>
    </div>`;
    h += `<div class="dup-item-size">${e(sizeStr)}</div>`;
    h += `<div class="dup-item-date">${e(dateStr)}</div>`;
    h += `<div class="dup-item-actions">`;
    if (it.side === 'local') {
      h += `<button class="icon-btn" title="Show in Explorer/Finder" onclick="revealInExplorer('${pj(it.path)}')">&#128193;</button>`;
    } else {
      h += `<button class="icon-btn" title="View site contents" onclick="openCloudPeek('${j(it.id)}','${j(it.location)}')">&#128065;</button>`;
    }

    const iidAttr = it.side === 'local' ? pj(iid) : j(iid);
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

  document.querySelectorAll('.dup-cluster').forEach(el => {
    const n = el.querySelectorAll('.dup-item-check:checked').length;
    const c = el.querySelector('.manual-count');
    if (c) c.textContent = `${n} selected`;
  });
  updateDupBulkBar();
}

function dupBulkDelete() {

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

function dupDeleteExtras(key) {
  const cl = _findCluster(key);
  if (!cl) return;
  const toDelete = cl.items.filter(it => !it.matched);
  if (!toDelete.length) { toast('No unmatched extras in this cluster', 'info'); return; }
  _bulkDeleteItems(toDelete, key);
}

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

  const norm = s => String(s || '').replace(/\\/g, '/').toLowerCase();
  const target = norm(iid);
  const it = cl.items.find(i => norm(i.id || i.path) === target);
  if (it) _bulkDeleteItems([it], key);
  else toast('Could not locate that item', 'error');
}

function fmtBytes(b) {

  if (!b) return 'size unknown';
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

  const d = new Date(ts * 1000);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function fmtExactDate(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return d.toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' })
    + ' at ' + d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

function toggleFolder(fn) {
  if (collapsed.has(fn)) collapsed.delete(fn); else collapsed.add(fn);
  renderRows();
}
function renderLedger(hit) {
  const isSites = currentTab === 'sites';

  const showSynced = activeFilter === 'all';
  const showMis = activeFilter === 'all' || activeFilter === 'mismatches';
  const showOrph = activeFilter === 'all' || activeFilter === 'orphans';
  const showOrphCloud = activeFilter === 'orphans-cloud';
  const showOrphLocal = activeFilter === 'orphans-local';
  const showUnassigned = activeFilter === 'unassigned';
  const showNameMatches = activeFilter === 'name-matches';
  const showExternal = activeFilter === 'external';

  const typeFilter = /^type-(design|measured|hybrid)$/.test(activeFilter)
    ? activeFilter.slice(5).replace(/^./, c => c.toUpperCase())
    : null;

  const directMatchesType = (row) => {
    if (!typeFilter) return false;
    const t = (row && row.cloud && row.cloud.projectType) || (row && row.local && row.local.projectType);
    return t === typeFilter;
  };
  const directIsNameMatch = (row) =>
    !!(row && row.cloud && row.local && row.matchType === 'exact');

  const anyChildMatches = (row, predicate) => {
    const kids = (row && row.cloud && row.cloud.children)
              || (row && row.local && row.local.children) || null;
    if (!kids) return false;
    const check = (arr) => (arr || []).some(p => predicate({
      cloud: p.cloud, local: p.local, matchType: p.matchType,
    }));
    return check(kids.matched) || check(kids.cloudOnly) || check(kids.localOnly);
  };
  const rowMatchesType = (row) =>
    directMatchesType(row) || anyChildMatches(row, directMatchesType);

  const hasKids = (row) =>
    !!((row && row.cloud && row.cloud.children) || (row && row.local && row.local.children));
  const rowIsNameMatch = (row) => {
    if (!hasKids(row)) return directIsNameMatch(row);
    return anyChildMatches(row, directIsNameMatch);
  };
  const pass = (st, row) => {
    if (typeFilter) return rowMatchesType(row);
    if (showNameMatches) return rowIsNameMatch(row);
    if (showUnassigned) return row && row.cloud && !row.cloud.hasSite;
    if (showExternal) {


      return isSites
        ? _siteHasExternal(row && row.cloud, row && row.local)
        : _isExternal(row && row.cloud, row && row.local);
    }
    if (showOrphCloud) return st === 'orphan' && row && row.cloud && !row.local;
    if (showOrphLocal) return st === 'orphan' && row && row.local && !row.cloud;


    if (showOrph && st === 'orphan' && _isExternal(row && row.cloud, row && row.local)) return false;
    return (st === 'synced' && showSynced) || (st === 'mismatch' && showMis) || (st === 'orphan' && showOrph);
  };

  const own = ownerFilter();
  const me = ((data && data.currentUser) || '').toLowerCase();
  const passOwner = buildPassOwner(own, me);

  if (isSites) return renderSitesTree(hit, pass, passOwner, own !== 'all' && !!me);

  const rows = [];
  (data.matched || []).forEach(p => rows.push({
    status: p.namesDiffer ? 'mismatch' : 'synced', key: 'p:' + p.cloud.id, kind: 'projects',
    matchType: p.matchType,
    cloud: p.cloud, local: p.local, sort: (p.cloud.name || p.local.name || '')
  }));
  (data.cloudOnly || []).forEach(s => rows.push({ status: 'orphan', key: 'c:' + s.id, kind: 'projects', cloud: s, local: null, sort: s.name || '' }));
  (data.localOnly || []).forEach(f => rows.push({ status: 'orphan', key: 'l:' + f.path, kind: 'projects', cloud: null, local: f, sort: f.name || '' }));

  const cloudCodes = new Set(rows.map(r => r.cloud && r.cloud.code).filter(Boolean));
  const localCodes = new Set(rows.map(r => r.local && r.local.code).filter(Boolean));

  const visible = rows
    .filter(r => pass(r.status, r) && passOwner(r) && (hit(r.cloud && r.cloud.name) || hit(r.local && r.local.name)))
    .sort((x, y) => x.sort.localeCompare(y.sort, undefined, { sensitivity: 'base' }));
  const nCloud = visible.filter(r => r.cloud).length, nLocal = visible.filter(r => r.local).length;

  let h = `<div class="ledger">`;
  h += `<div class="ledger-head"><div class="lh-cell cloud">Cloud Projects (${nCloud})</div><div class="lh-gut"></div><div class="lh-cell local">Local .esx (${nLocal})</div></div>`;
  if (!visible.length) { h += `<div class="empty-msg">Nothing here for this filter.</div></div>`; return h; }
  const groupOf = (s) => {
    const ch = String(s || '').trim().charAt(0).toUpperCase();
    return (ch >= 'A' && ch <= 'Z') ? ch : '#';
  };

  const flatByLetter = new Map();
  visible.forEach(r => {
    const g = groupOf(r.sort);
    if (!flatByLetter.has(g)) flatByLetter.set(g, []);
    flatByLetter.get(g).push(r);
  });
  const _emitFlatHeader = (g, isEmpty) => {
    const cls = 'ledger-group-head' + (isEmpty ? ' empty-letter' : '');
    return `<div class="${cls}" role="separator" data-jump-letter="${e(g)}" aria-label="Section ${e(g)}${isEmpty ? ' (empty)' : ''}">`
         +   `<span class="glh-letter cloud">${e(g)}</span>`
         +   `<span class="glh-gap"></span>`
         +   `<span class="glh-letter local">${e(g)}</span>`
         + `</div>`;
  };
  const allFlatLetters = ['#', ...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')];

  const showEmptyPlaceholders = activeFilter === 'all' && !activeLetter;

  const letterFilter = (L) => !activeLetter || L === activeLetter;
  let z = 0;
  allFlatLetters.forEach(letter => {
    if (!letterFilter(letter)) return;
    const groupRows = flatByLetter.get(letter);
    if (!groupRows || !groupRows.length) {
      if (showEmptyPlaceholders) h += _emitFlatHeader(letter, true);
      z = 0;
      return;
    }
    h += _emitFlatHeader(letter, false);
    z = 0;
    groupRows.forEach(r => {
      h += `<div class="ledger-row ${r.status}${(z++ % 2) ? ' stripe' : ''}${_verifyFailedClass(r)}${_isExternal(r.cloud, r.local) ? ' is-external' : ''}">${cloudCell(r, localCodes)}${gutCell(r)}${localCell(r, cloudCodes)}</div>`;
    });
  });

  const heldBack = _collectHeldBack(passOwner);
  if (heldBack.length && !activeLetter) h += renderHeldBackSection(heldBack);
  h += `</div>`;
  return h;
}

function renderSitesTree(hit, pass, passOwner, ownerFilterActive) {
  const rows = [];
  (data.matched || []).forEach(p => rows.push({
    status: p.namesDiffer ? 'mismatch' : 'synced', key: 'p:' + p.cloud.id, kind: 'sites',
    matchType: p.matchType,
    cloud: p.cloud, local: p.local, sort: (p.cloud.name || p.local.name || ''),
    // Independent per-side checkboxes (see indexRowData's s-c:/s-l: entries)
    // so "select all local" can grab a whole site's local folder without
    // also grabbing its cloud counterpart, and vice versa.
    cloudCheckKey: 's-c:' + p.cloud.id, localCheckKey: 's-l:' + p.local.path,
  }));
  (data.cloudOnly || []).forEach(s => rows.push({ status: 'orphan', key: 'c:' + s.id, kind: 'sites', cloud: s, local: null, sort: s.name || '' }));
  (data.localOnly || []).forEach(f => rows.push({ status: 'orphan', key: 'l:' + f.path, kind: 'sites', cloud: null, local: f, sort: f.name || '' }));

  const cloudCodes = new Set(rows.map(r => r.cloud && r.cloud.code).filter(Boolean));
  const localCodes = new Set(rows.map(r => r.local && r.local.code).filter(Boolean));

  const nameHit = (o) => o && hit(o.name);
  const childHit = (children) => !!children && (
    (children.matched || []).some(m => nameHit(m.cloud) || nameHit(m.local)) ||
    (children.cloudOnly || []).some(nameHit) ||
    (children.localOnly || []).some(nameHit)
  );
  const childrenOf = (r) => (r.cloud && r.cloud.children) || (r.local && r.local.children) || null;
  const hasKids = (children) => !!(children && (children.matched.length || children.cloudOnly.length || children.localOnly.length));

  const childOwnerHit = (children) => {

    if (!hasKids(children)) return ownerFilter() !== 'others';
    return (children.matched || []).some(p => passOwner({ cloud: p.cloud, local: p.local }))
        || (children.cloudOnly || []).some(c => passOwner({ cloud: c, local: null }))
        || (children.localOnly || []).some(l => passOwner({ cloud: null, local: l }));
  };

  const visible = rows
    .filter(r => pass(r.status, r)
      && (hit(r.cloud && r.cloud.name) || hit(r.local && r.local.name) || childHit(childrenOf(r)))
      && childOwnerHit(childrenOf(r)))
    .sort((x, y) => x.sort.localeCompare(y.sort, undefined, { sensitivity: 'base' }));

  const treeGroupOf = (s) => {
    const ch = String(s || '').trim().charAt(0).toUpperCase();
    return (ch >= 'A' && ch <= 'Z') ? ch : '#';
  };





  const orphans = ((data.orphans && data.orphans.cloudOnly) || [])
    .filter(o => pass('orphan', { cloud: o, local: null }) && hit(o.name) && passOwner({ cloud: o, local: null })
      && (!activeLetter || treeGroupOf(o.name) === activeLetter));

  const nCloud = visible.filter(r => r.cloud).length + orphans.length;
  const nLocal = visible.filter(r => r.local).length;

  let h = `<div class="ledger tree">`;

  const autoAssignable = _collectAutoAssignable(visible, passOwner);
  if (autoAssignable.length) {

    const n = autoAssignable.length;
    const verb = n === 1 ? 'matches a local file/folder but is' : 'match local files/folders but are';

    const autoOpen = _autoAssignDetailsOpen();
    const detailRows = autoAssignable.map(it =>
      `<div class="aab-detail-row"><span class="aab-project">${e(it.projectName)}.esx</span><span class="aab-destination">&#8594; ${e(it.siteName)}</span></div>`
    ).join('');
    h += `<div class="auto-assign-row" role="status">`
       +   `<div class="auto-assign-banner">`
       +     `<button class="aab-chevron${autoOpen ? ' open' : ''}" onclick="toggleAutoAssignDetails()" title="${autoOpen ? 'Hide' : 'Show'} projects and destinations" aria-expanded="${autoOpen}"><span class="aab-chevron-icon">&#9656;</span>${autoOpen ? 'Hide' : 'Show'} list</button>`
       +     `<button class="btn btn-blue aab-btn" onclick="autoAssignAllMatched()" title="Assign each of these to the site its local .esx already lives in"><span class="aab-btn-icon">&#128206;</span> Auto-assign ${n}</button>`
       +     `<span class="aab-text"><b>${n}</b> unassigned cloud project${n === 1 ? '' : 's'} ${verb} not assigned to a site. Do you want to automatically assign ${n === 1 ? 'it' : 'them'} to a site?</span>`
       +   `</div>`
       +   `<div class="aab-details"${autoOpen ? '' : ' hidden'}>${detailRows}</div>`
       + `</div>`;
  }
  const localPath = _outputDir ? ` <span class="lh-path">- ${e(_outputDir)}</span>` : '';
  h += `<div class="ledger-head"><div class="lh-cell cloud">Cloud Sites (${nCloud})</div><div class="lh-gut"></div><div class="lh-cell local"${_outputDir ? ` title="${a(_outputDir)}"` : ''}>Local Folders (${nLocal})${localPath}</div></div>`;
  if (!visible.length && !orphans.length) { h += `<div class="empty-msg">Nothing here for this filter.</div></div>`; return h; }

  const populatedLetters = new Set(visible.map(r => treeGroupOf(r.sort)));
  const _emitHeader = (g, isEmpty) => {
    const cls = 'ledger-group-head' + (isEmpty ? ' empty-letter' : '');
    return `<div class="${cls}" role="separator" data-jump-letter="${e(g)}" aria-label="Section ${e(g)}${isEmpty ? ' (empty)' : ''}">`
         +   `<span class="glh-letter cloud">${e(g)}</span>`
         +   `<span class="glh-gap"></span>`
         +   `<span class="glh-letter local">${e(g)}</span>`
         + `</div>`;
  };
  const allLetters = ['#', ...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')];
  const visibleByLetter = new Map();
  visible.forEach(r => {
    const g = treeGroupOf(r.sort);
    if (!visibleByLetter.has(g)) visibleByLetter.set(g, []);
    visibleByLetter.get(g).push(r);
  });

  const showEmptyPlaceholders = activeFilter === 'all' && !activeLetter;
  const letterFilter = (L) => !activeLetter || L === activeLetter;
  let z = 0;
  allLetters.forEach(letter => {
    if (!letterFilter(letter)) return;
    const groupRows = visibleByLetter.get(letter);
    if (!groupRows || !groupRows.length) {
      if (showEmptyPlaceholders) h += _emitHeader(letter, true);
      z = 0;
      return;
    }
    h += _emitHeader(letter, false);
    z = 0;
    groupRows.forEach(r => {
      const children = childrenOf(r);
      const kids = hasKids(children);
      const siteKey = r.cloud ? ('site:' + r.cloud.id) : ('folder:' + r.local.path);
      const open = !collapsed.has(siteKey);
      r.toggle = { key: siteKey, open, hasKids: kids };
      h += `<div class="ledger-row tree-parent ${r.status}${(z++ % 2) ? ' stripe' : ''}${_verifyFailedClass(r)}${_isExternal(r.cloud, r.local) ? ' is-external' : ''}">${cloudCell(r, localCodes)}${gutCell(r)}${localCell(r, cloudCodes)}</div>`;

      if (open) h += renderTreeChildren(children, hit, passOwner, r.cloud && r.cloud.id, r.cloud && r.cloud.name, pass);
    });
  });

  if (orphans.length) {

    h += `<div class="ledger-group-head tree-orphan-head" role="separator" aria-label="Unassigned projects — no site">`
       +   `<span class="glh-letter cloud">&#9888; Unassigned Projects — no site (${orphans.length})</span>`
       +   `<span class="glh-gap"></span>`
       +   `<span class="glh-letter local"></span>`
       + `</div>`;
    orphans.forEach((o, i) => {
      const r = { status: 'orphan', key: 'op:' + o.id, kind: 'projects', noCheckbox: true, cloud: o, local: null };
      h += `<div class="ledger-row orphan${(i % 2) ? ' stripe' : ''}${_isExternal(r.cloud, r.local) ? ' is-external' : ''}">${cloudCell(r, localCodes)}${gutCell(r)}${localCell(r, cloudCodes)}</div>`;
    });
  }

  const heldBack = _collectHeldBack(passOwner);
  if (heldBack.length && !activeLetter) {
    h += renderHeldBackSection(heldBack);
  }

  h += `</div>`;
  return h;
}

function _collectHeldBack(passOwner) {
  const pass = passOwner || (() => true);
  const seen = new Set();
  const out = [];
  const push = (h, kind) => {
    const key = (h.cloud && h.cloud.id) + '||' + (h.local && h.local.path);
    if (seen.has(key)) return;
    seen.add(key);
    if (!pass({ cloud: h.cloud, local: h.local })) return;
    out.push({ ...h, kind });
  };
  (data.heldBack || []).forEach(h => push(h, 'sites'));
  (data.matched || []).forEach(p => {
    ((p.cloud && p.cloud.children && p.cloud.children.heldBack) || [])
      .forEach(h => push(h, 'projects'));
  });
  (data.cloudOnly || []).forEach(s => {
    ((s.children && s.children.heldBack) || []).forEach(h => push(h, 'projects'));
  });
  (data.localOnly || []).forEach(f => {
    ((f.children && f.children.heldBack) || []).forEach(h => push(h, 'projects'));
  });
  ((data.orphans && data.orphans.heldBack) || []).forEach(h => push(h, 'projects'));
  return out;
}

function renderHeldBackSection(heldBack) {
  const rows = heldBack.map((h, i) => {
    const c = h.cloud, l = h.local;
    const label = h.kind === 'sites' ? 'site' : 'project';
    return `<div class="hb-row${(i % 2) ? ' stripe' : ''}">
      <div class="hb-side hb-cloud">
        <span class="hb-tag cloud">CLOUD</span>
        <span class="hb-name">${e(c.name)}</span>
      </div>
      <div class="hb-mid">
        <div class="hb-reason" title="${a(h.reason)}">${e(h.reason)}</div>
        <div class="hb-actions">
          <button class="btn btn-blue btn-sm" title="Link these two as the same ${label}"
                  onclick="markManualMatch('${j(c.id)}','${pj(l.path)}','${j(c.name)}','${j(l.name)}')">Link anyway</button>
          <button class="btn btn-secondary btn-sm" title="Never suggest this pair again"
                  onclick="markNotMatch('${j(c.id)}','${pj(l.path)}','${j(c.name)}','${j(l.name)}')">Not a match</button>
        </div>
      </div>
      <div class="hb-side hb-local">
        <span class="hb-tag local">LOCAL</span>
        <span class="hb-name">${e(l.name)}${l.isDir ? '' : '.esx'}</span>
      </div>
    </div>`;
  }).join('');
  const isOpen = _heldBackOpen();
  return `<div class="ledger-group-head hb-head" role="separator" aria-label="Held back — pairs we didn't auto-match"
               onclick="toggleHeldBack()">
      <span class="glh-letter hb-toggle${isOpen ? ' open' : ''}">&#9656;</span>
      <span class="glh-letter hb-title">&#9888; Held back — pairs we didn't auto-match (${heldBack.length})</span>
      <span class="glh-gap"></span>
      <span class="glh-letter"></span>
    </div>
    <div class="hb-list"${isOpen ? '' : ' hidden'}>${rows}</div>`;
}
function _heldBackOpen() {
  try { return localStorage.getItem('wd-heldback-open') !== '0'; } catch (e) { return true; }
}

function _autoAssignDetailsOpen() {
  try { return localStorage.getItem('wd-auto-assign-open') === '1'; } catch (e) { return false; }
}
function toggleAutoAssignDetails() {
  try { localStorage.setItem('wd-auto-assign-open', _autoAssignDetailsOpen() ? '0' : '1'); } catch (e) {}
  renderRows();
}
function toggleHeldBack() {
  const now = _heldBackOpen() ? '0' : '1';
  try { localStorage.setItem('wd-heldback-open', now); } catch (e) {}
  renderRows();
}

function buildPassOwner(own, me) {
  return (row) => {
    if (own === 'all' || !me) return true;

    const co = (row.cloud && row.cloud.owner || '').toLowerCase();
    const lo = (row.local && row.local.owner || '').toLowerCase();
    const otherCloud = co && co.indexOf('@') > -1 && co !== me;
    const otherLocal = lo && lo.indexOf('@') > -1 && lo !== me;
    if (own === 'mine')   return !otherCloud && !otherLocal;
    if (own === 'others') return otherCloud || otherLocal;
    return true;
  };
}

function _collectAutoAssignable(visibleSiteRows, passOwner) {
  const out = [];
  const pass = passOwner || (() => true);
  (visibleSiteRows || []).forEach(r => {
    const siteId = r.cloud && r.cloud.id;
    const siteName = r.cloud && r.cloud.name;
    if (!siteId) return;
    const children = (r.cloud && r.cloud.children) || (r.local && r.local.children);
    if (!children || !children.matched) return;
    children.matched.forEach(p => {
      if (p.cloud && p.cloud.unassigned && p.cloud.id && pass({ cloud: p.cloud, local: p.local })) {
        out.push({ projectId: p.cloud.id, projectName: p.cloud.name || '', siteId, siteName: siteName || '' });
      }
    });
  });
  return out;
}

async function autoAssignAllMatched() {

  const own = ownerFilter();
  const me = ((data && data.currentUser) || '').toLowerCase();
  const passOwner = buildPassOwner(own, me);
  const visible = _visibleSiteRowsForBatch();
  const items = _collectAutoAssignable(visible, passOwner);
  if (!items.length) { toast('Nothing to auto-assign', 'info'); return; }
  toast(`Assigning ${items.length} project${items.length === 1 ? '' : 's'}…`, 'info');
  for (const it of items) {
    opEnqueue({
      title: `Assigning "${it.projectName}" to ${it.siteName}`,
      type: 'op', pollBackend: false, undoable: false,
      retryFn: async () => pyApi('assign_to_site', it.siteId, it.projectId),
      run: async () => pyApi('assign_to_site', it.siteId, it.projectId),
    });
  }
}

function _visibleSiteRowsForBatch() {
  const rows = [];
  (data.matched || []).forEach(p => rows.push({
    status: p.namesDiffer ? 'mismatch' : 'synced', matchType: p.matchType, cloud: p.cloud, local: p.local, sort: (p.cloud.name || p.local.name || '')
  }));
  (data.cloudOnly || []).forEach(s => rows.push({ status: 'orphan', cloud: s, local: null, sort: s.name || '' }));
  (data.localOnly || []).forEach(f => rows.push({ status: 'orphan', cloud: null, local: f, sort: f.name || '' }));
  return rows;
}

function renderTreeChildren(children, hit, passOwner, parentSiteId, parentSiteName, passFilter) {
  const rows = [];
  (children.matched || []).forEach(p => rows.push({
    status: p.namesDiffer ? 'mismatch' : 'synced', matchType: p.matchType, cloud: p.cloud, local: p.local, sort: (p.cloud.name || p.local.name || '')
  }));
  (children.cloudOnly || []).forEach(c => rows.push({ status: 'orphan', cloud: c, local: null, sort: c.name || '' }));
  (children.localOnly || []).forEach(l => rows.push({ status: 'orphan', cloud: null, local: l, sort: l.name || '' }));
  const totalBeforeOwner = rows.length;
  const rows2 = passOwner ? rows.filter(passOwner) : rows;

  const rows3 = (passFilter && activeFilter !== 'all')
    ? rows2.filter(r => passFilter(r.status, r))
    : rows2;
  if (!rows3.length) {
    let msg;
    if (rows2.length && !rows3.length) msg = 'No projects here match this filter.';
    else if (totalBeforeOwner) msg = 'No projects match the owner filter.';
    else msg = 'No projects here yet.';
    return `<div class="ledger-row tree-child-empty"><div class="lr-cell child-row empty-child">${msg}</div></div>`;
  }
  rows3.sort((x, y) => x.sort.localeCompare(y.sort, undefined, { sensitivity: 'base' }));
  const cloudCodes = new Set(rows3.map(r => r.cloud && r.cloud.code).filter(Boolean));
  const localCodes = new Set(rows3.map(r => r.local && r.local.code).filter(Boolean));
  let h = '';
  rows3.forEach((r, i) => {

    r.kind = 'projects'; r.indent = true;
    r.key = 'ct:' + (r.cloud ? r.cloud.id : r.local.path);
    if (r.cloud && r.local) {
      r.cloudCheckKey = 'ct-c:' + r.cloud.id;
      r.localCheckKey = 'ct-l:' + r.local.path;
    }
    r.parentSiteId = parentSiteId;
    r.parentSiteName = parentSiteName;
    h += `<div class="ledger-row tree-child ${r.status}${(i % 2) ? ' stripe' : ''}${_verifyFailedClass(r)}${_isExternal(r.cloud, r.local) ? ' is-external' : ''}">${cloudCell(r, localCodes)}${gutCell(r)}${localCell(r, cloudCodes)}</div>`;
  });
  return h;
}

function matchBadgeHtml(r, kind) {

  const rowKind = kind || r.kind;
  const isSite = rowKind === 'sites';
  const spec = (isSite && r.matchType === 'exact')
    ? MATCH_BADGE_SPEC_SITE_EXACT
    : (MATCH_BADGE_SPEC[r.matchType] || MATCH_BADGE_SPEC.exact);
  const c = r.cloud, l = r.local;
  const isManual = r.matchType === 'manual';
  const onclick = isManual
    ? `onclick="unmarkManualMatch('${j(c && c.id || '')}','${pj(l && l.path || '')}','${j(c && c.name || '')}','${j(l && l.name || '')}')"`
    : '';
  const cursor = isManual ? ' clickable' : '';
  return `<span class="match-badge mb-${spec.cls}${cursor}" title="${a(spec.title)}"${onclick ? ' ' + onclick : ''}>${spec.label}</span>`;
}
const MATCH_BADGE_SPEC = {
  manual: { cls: 'manual', label: '★ You matched', title: 'You linked these manually. Click to unlink and go back to auto-matching.' },
  id:     { cls: 'id',     label: '✓ Same file',   title: 'Same Ekahau project — proven by a hidden ID stamped inside both .esx files. This is one project, just stored in two places.' },
  exact:  { cls: 'exact',  label: '✓ Name matches', title: 'Both files have the exact same name, but no hidden-ID link — very likely the same project, not proven.' },
  code:   { cls: 'code',   label: '~ Same site',   title: 'Same site code plus similar names. Probably the same project.' },
  fuzzy:  { cls: 'fuzzy',  label: '? Similar name', title: 'Some words in common. Our best guess — worth a look before syncing.' },
};

const MATCH_BADGE_SPEC_SITE_EXACT = {
  cls: 'id',
  label: '✓ Same site',
  title: 'Both sites share the same name. Sites don\'t have a stronger identity to compare (folders have no internal ID), so this is as matched as a site pair gets.',
};

function gutCell(r) {
  const kind = r.kind || currentTab;
  if (r.status === 'mismatch') {
    const c = r.cloud, l = r.local;
    return `<div class="lr-gut mis">
      ${matchBadgeHtml(r, kind)}
      <button class="gut-arrow" title="Apply cloud name onto the local folder" onclick="syncRow('to-local','${j(c.id)}','${j(c.name)}','${pj(l.path)}','${kind}')">&#10145;</button>
      <button class="gut-arrow" title="Apply local name onto the cloud site" onclick="syncRow('to-cloud','${j(c.id)}','${j(l.name)}','${pj(l.path)}','${kind}')">&#11013;</button>
      <button class="gut-arrow nomatch" title="Not a match — never pair these two again" onclick="markNotMatch('${j(c.id)}','${pj(l.path)}','${j(c.name)}','${j(l.name)}')">&#8800;</button>
    </div>`;
  }
  if (r.status === 'synced') {

    const isNameMatch = r.matchType === 'exact' && r.cloud && r.local && kind !== 'sites';
    const verifyBtn = isNameMatch
      ? `<button class="gut-arrow verify-btn" title="Download cloud copy and overwrite local — makes them byte-identical so the badge upgrades to Same file" onclick="verifyReplaceLocal('${j(r.cloud.id)}','${pj(r.local.path)}','${j(r.cloud.name)}')">&#8681;</button>`
      : '';
    return `<div class="lr-gut ok">${matchBadgeHtml(r, kind)}${verifyBtn}</div>`;
  }
  if (r.cloud) {

    const linkBtn = (kind === 'projects')
      ? `<button class="gut-arrow link-btn" title="Link this cloud project to a specific local .esx" onclick="openLinkPicker('cloud','${j(r.cloud.id)}','${j(r.cloud.name)}')">&#128279;</button>`
      : '';
    if (kind === 'sites') {
      return `<div class="lr-gut orph"><button class="gut-arrow orphan" title="Create the matching local folder &#8594;" onclick="createLocalFolder('${j(r.cloud.name)}')">&#10145;</button></div>`;
    }
    return `<div class="lr-gut orph">
      <button class="gut-arrow orphan" title="Download .esx from Ekahau Cloud &#8594; then move into a site folder" onclick="downloadThenMove('${j(r.cloud.id)}','${j(r.cloud.name)}')">&#10145;</button>
      ${linkBtn}
    </div>`;
  }
  if (kind === 'sites') {
    return `<div class="lr-gut orph"><button class="gut-arrow orphan" title="← Create a cloud site from this folder" onclick="createFromLocal('${j(r.local.name)}')">&#11013;</button></div>`;
  }
  return `<div class="lr-gut orph">
    <button class="gut-arrow orphan" title="← Upload .esx to Ekahau Cloud" onclick="uploadFromLocal('${pj(r.local.path)}','${j(r.local.name)}')">&#11013;</button>
    <button class="gut-arrow link-btn" title="Link this local .esx to a specific cloud project" onclick="openLinkPicker('local','${pj(r.local.path)}','${j(r.local.name)}')">&#128279;</button>
  </div>`;
}
function cloudCell(r, localCodes) {
  const isSites = (r.kind || currentTab) === 'sites';
  const kindAttr = r.kind || currentTab;

  const chkKey = (r.cloudCheckKey && r.cloud) ? r.cloudCheckKey : r.key;
  const chk = r.noCheckbox ? '' : `<input type="checkbox" class="rowchk" data-k="${e(chkKey)}" ${selected.has(chkKey) ? 'checked' : ''}>`;
  const indentCls = r.indent ? ' child-row' : '';
  const chevron = r.toggle
    ? `<button class="tree-chevron${r.toggle.open ? ' open' : ''}" onclick="event.stopPropagation();toggleFolder('${j(r.toggle.key)}')" title="${r.toggle.open ? 'Collapse' : 'Expand'}">&#9656;</button>`
    : '';
  if (!r.cloud) {
    if (isSites) {
      return `<div class="lr-cell cloud empty${indentCls}">${chevron}<button class="ghost-add" title="Create a cloud site from this folder" onclick="createFromLocal('${j(r.local.name)}')">+ Cloud site</button></div>`;
    }
    return `<div class="lr-cell cloud empty${indentCls}">${chevron}<button class="ghost-add" title="Upload .esx to Ekahau Cloud" onclick="uploadFromLocal('${pj(r.local.path)}','${j(r.local.name)}')">+ Upload</button></div>`;
  }
  const c = r.cloud, isMis = r.status === 'mismatch', thing = isSites ? 'cloud site' : 'cloud project';
  const me = ((data && data.currentUser) || '').toLowerCase();
  const owner = (c.owner || '').toLowerCase();
  const createdBy = (c.createdBy || '').toLowerCase();

  const ownerTitle = createdBy && createdBy !== owner
    ? `Current owner (from Ekahau share list). Originally created by ${createdBy}.`
    : 'Current owner (from Ekahau share list)';
  const ownerHtml = (!isSites && owner)
    ? ` <span class="owner-tag${owner !== me ? ' other' : ''}" title="${a(ownerTitle)}">(${e(owner)})</span>`
    : '';

  const typeHtml = (!isSites && c.projectType)
    ? ` <span class="ptype-tag pt-${e(c.projectType.toLowerCase().replace(/\s+/g, '-'))}" title="Project type (from Ekahau)">${e(c.projectType)}</span>`
    : '';

  const planHtml = (!isSites && c.planType)
    ? ` <span class="ptype-tag pt-plan" title="Ekahau also has a ${e(c.planType)} dataset under this same name — matched by name, not a guaranteed link">+ ${e(c.planType)}</span>`
    : '';
  const shared = (!isSites && c.sharedWith) || [];
  const sharedHtml = shared.length
    ? ` <span class="shared-tag" title="Also shared with: ${a(shared.join(', '))}">+${shared.length} shared</span>`
    : '';

  const iOwnCloud = owner && me && owner === me;
  const unassignedHtml = (!isSites && c.unassigned && iOwnCloud)
    ? ` <span class="ptype-tag pt-unassigned" title="This cloud project has no site parent in Ekahau. Assign it so it lives inside the right site.">Not assigned</span>`
    : '';
  const nameHtml = (isMis ? charDiff(c.name, r.local.name).a : e(c.name)) + (isSites ? '' : '.esx') + typeHtml + planHtml + unassignedHtml + ownerHtml + sharedHtml + dupHintFor(c.id);
  const dup = r.status === 'orphan' && c.code && localCodes.has(c.code);
  const dsCount = (c.datasets && c.datasets.length) || 0;
  const cloudPeek = isSites
    ? `<button class="src-badge${dsCount ? ' hasrc' : ''}" title="${dsCount ? dsCount + ' project' + (dsCount > 1 ? 's' : '') : 'No projects yet'} — click to view" onclick="event.stopPropagation();openCloudPeek('${j(c.id)}','${j(c.name)}')">&#128065;</button>`
    : '';
  const assignBtn = (!isSites && c.unassigned && r.parentSiteId)
    ? `<button class="icon-btn assign-btn" title="Assign to &quot;${a(r.parentSiteName || '')}&quot;" onclick="assignOrphanToSite('${j(c.id)}','${j(r.parentSiteId)}','${j(c.name)}','${j(r.parentSiteName || '')}')">&#128206;</button>`
    : '';

  const shareCount = (c.sharedWith || []).length;
  const shareBtn = !isSites
    ? `<button class="icon-btn share-btn" title="Manage sharing (${shareCount} user${shareCount === 1 ? '' : 's'})" onclick="openManageShares('${j(c.id)}','${j(c.name)}')">&#128101;${shareCount ? `<span class="share-badge-count">${shareCount}</span>` : ''}</button>`
    : '';
  return `<div class="lr-cell cloud${dup ? ' dup' : ''}${indentCls}"${dup ? ` title="A local ${isSites ? 'folder' : '.esx'} shares code ${a(c.code)} — likely the same place"` : ''}>
    ${chevron}${chk}
    <span class="cell-name">${nameHtml}</span><span class="cell-meta">${e(c.meta || '')}</span>
    <span class="cell-actions">${cloudPeek}${assignBtn}
      ${shareBtn}
      ${!isSites ? `<button class="icon-btn" title="Move to a site" onclick="startMoveToSite('${j(c.id)}','${j(c.name)}')">&#8618;</button>` : ''}
      <button class="icon-btn" title="Rename ${thing}" onclick="startRename('cloud','${j(c.id)}','${j(c.name)}','${kindAttr}')">&#9998;</button>
      <button class="icon-btn del" title="Delete ${thing}" onclick="startDelete('cloud','${j(c.id)}','${j(c.name)}',false,'${kindAttr}')">&#128465;</button>
    </span></div>`;
}
function localCell(r, cloudCodes) {
  const isSites = (r.kind || currentTab) === 'sites';
  const kindAttr = r.kind || currentTab;

  const chkKey = (r.localCheckKey && r.local) ? r.localCheckKey : r.key;
  const chk = r.noCheckbox ? '' : `<input type="checkbox" class="rowchk" data-k="${e(chkKey)}" ${selected.has(chkKey) ? 'checked' : ''}>`;
  const indentCls = r.indent ? ' child-row' : '';
  if (!r.local) {
    return isSites
      ? `<div class="lr-cell local empty${indentCls}"><button class="ghost-add" title="Create a matching local folder" onclick="createLocalFolder('${j(r.cloud.name)}')">+ Local folder</button></div>`
      : `<div class="lr-cell local empty${indentCls}"></div>`;
  }
  const l = r.local, isMis = r.status === 'mismatch', thing = isSites ? 'local folder' : '.esx file';
  const me = ((data && data.currentUser) || '').toLowerCase();
  const owner = (l.owner || '').toLowerCase();

  const localIsOther = owner && owner.indexOf('@') > -1 && owner !== me;
  const ownerHtml = (!isSites && owner)
    ? ` <span class="owner-tag${localIsOther ? ' other' : ''}" title="Author (from project.history.createdBy)">(${e(owner)})</span>`
    : '';

  const localTypeHtml = (!isSites && l.projectType)
    ? ` <span class="ptype-tag pt-${e(l.projectType.toLowerCase().replace(/\s+/g, '-'))}" title="Project type (detected from .esx contents)">${e(l.projectType)}</span>`
    : '';
  const nameHtml = (isMis ? charDiff(r.cloud.name, l.name).b : e(l.name)) + (l.isDir ? '' : '.esx') + localTypeHtml + ownerHtml + dupHintFor(l.path);
  const dup = r.status === 'orphan' && l.code && cloudCodes.has(l.code);
  const hasSrc = isSites && l.hasSource;
  const hasContents = isSites && l.src && l.src.total > 0;
  const flagged = l.name.charAt(0) === '!';
  const srcUI = hasContents ? previewBadge(l) : '';
  const flagBtn = isSites
    ? `<button class="icon-btn${flagged ? ' flagged' : ''}" title="${flagged ? 'Un-flag (remove the ! prefix)' : 'Flag this folder for review — adds a ! prefix so it sorts to the top here and in Explorer'}" onclick="flagReview('${pj(l.path)}','${j(l.name)}')">${flagged ? '&#9873;' : '&#9872;'}</button>`
    : '';
  const revealBtn = `<button class="icon-btn" title="Show in ${navigator.platform.indexOf('Mac') >= 0 ? 'Finder' : 'Explorer'}" onclick="revealInExplorer('${pj(l.path)}')">&#128193;</button>`;

  const moveBtn = (!isSites && !l.isDir)
    ? `<button class="icon-btn" title="Move this .esx to another site folder" onclick="startMoveLocalToSite('${pj(l.path)}','${j(l.name)}')">&#8618;</button>`
    : '';
  return `<div class="lr-cell local${dup ? ' dup' : ''}${indentCls}"${dup ? ` title="A cloud ${isSites ? 'site' : 'project'} shares code ${a(l.code)} — likely the same place"` : ''}>
    ${chk}
    <span class="cell-name">${nameHtml}</span><span class="cell-meta">${e(l.meta || '')}</span>
    <span class="cell-actions">${srcUI}${revealBtn}${flagBtn}
      ${moveBtn}
      ${isSites ? `<button class="icon-btn" title="Merge this folder's files into another folder…" onclick="startMerge('${pj(l.path)}','${j(l.name)}')">&#8649;</button>` : ''}
      <button class="icon-btn" title="Rename ${thing}" onclick="startRename('local','${pj(l.path)}','${j(l.name)}','${kindAttr}')">&#9998;</button>
      <button class="icon-btn del" title="Delete ${thing}${isSites ? ' and contents' : ''}" onclick="startDelete('local','${pj(l.path)}','${j(l.name)}',${l.isDir},'${kindAttr}')">&#128465;</button>
    </span></div>`;
}

function localByPath(path) {

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
  return `<button class="${cls}" title="${a(tip)}" onclick="event.stopPropagation();openPeek('${pj(l.path)}')">&#128065;</button>`;
}
function peekFileRow(f, typeClass) {
  const when = f.mtime ? new Date(f.mtime * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' }) : '';
  const ext = (f.name.split('.').pop() || '').toLowerCase();
  const rel = f.rel || f.name;

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
    body.innerHTML = `<div class="peek-empty cloud-peek-empty-tight">
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
                onclick="undoNotMatch('${j(pr.cloudId)}','${pj(pr.localPath)}')">Un-mark</button>
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

async function markManualMatch(cloudId, localPath, cloudName, localName) {
  try {
    const r = await pyApi('mark_manual_match', cloudId, localPath, cloudName || '', localName || '');
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast('Linked', 'success');
    refreshData();
  } catch (e) { toast('Link failed: ' + e.message, 'error'); }
}

const SHARE_ROLE_LABEL = {
  OWNER:           'Owner',
  WRITE_SHARE_USER: 'Full access',
  WRITE_USER:      'Edit rights',
  READ_USER:       'View only',
};

const SHARE_ROLE_DESC = {
  OWNER:           'Owns the project — can transfer ownership to any current member',
  WRITE_SHARE_USER: 'Complete control over project and settings',
  WRITE_USER:      'Collaborative access without sharing privileges',
  READ_USER:       'Read-only access with option to create a copy',
};

function _roleOption(value, currentValue) {
  const label = SHARE_ROLE_LABEL[value] || value;
  const desc = SHARE_ROLE_DESC[value] || '';
  const sel = value === currentValue ? ' selected' : '';
  return `<option value="${value}"${sel} title="${e(desc)}">${e(label)}</option>`;
}
let _shareCtx = null;

function _sharingGroupGet() {
  try {
    const raw = localStorage.getItem('wd-sharing-group');
    return raw ? JSON.parse(raw) : null;
  } catch (e) { return null; }
}
function _sharingGroupSet(id, name) {
  if (!id) return;
  try {
    localStorage.setItem('wd-sharing-group', JSON.stringify({ id, name: name || 'My Sharing Group' }));
  } catch (e) {}
}

function _sharingGroupLearnFromUsers(users) {
  for (const u of (users || [])) {
    if (u.groupId) {
      _sharingGroupSet(u.groupId, u.groupName || 'My Sharing Group');
      return;
    }
  }
}

async function _fetchGroupIntoCtx() {
  if (!_shareCtx) return;
  try {
    const r = await pyApi('get_my_group', 'My Sharing Group');
    if (r && r.ok && r.group) {
      _shareCtx.group = r.group;
      _sharingGroupSet(r.group.groupId, r.group.groupName);
    } else {
      _shareCtx.group = null;
    }
  } catch (e) {

    _shareCtx.group = null;
  }
}

async function openManageShares(projectId, projectName, bulkProjectIds) {
  const isBulk = Array.isArray(bulkProjectIds) && bulkProjectIds.length > 0;
  _shareCtx = {
    projectId: isBulk ? null : projectId,
    projectName: isBulk ? null : projectName,
    bulkProjectIds: isBulk ? bulkProjectIds.slice() : null,
    users: [],
    group: null,
    groupPanelOpen: false,
  };
  const titleEl = document.getElementById('shareModalTitle');
  if (titleEl) {
    if (isBulk) {
      const n = bulkProjectIds.length;
      titleEl.textContent = `Sharing ${n} project${n === 1 ? '' : 's'}`;
    } else {
      titleEl.textContent = projectName
        ? `Manage Sharing — ${projectName}`
        : 'Manage Sharing';
    }
  }
  document.getElementById('shareSub').textContent = isBulk
    ? 'Add people, enable your Sharing Group, or both — applies to every selected project.'
    : 'Loading current shares…';
  document.getElementById('shareList').innerHTML = '';
  document.getElementById('shareEmail').value = '';
  document.getElementById('shareRole').value = 'READ_USER';
  showModal('shareModal');
  if (isBulk) {

    await _fetchGroupIntoCtx();
  } else {

    await Promise.all([_shareRefresh(), _fetchGroupIntoCtx()]);
  }
  _shareRender();
  setTimeout(() => document.getElementById('shareEmail').focus(), 60);
}

async function _shareRefresh() {
  if (!_shareCtx) return;
  try {
    const r = await pyApi('list_shares', _shareCtx.projectId);
    if (r && r.error) { toast(r.error, 'error'); return; }
    _shareCtx.users = (r && r.users) || [];

    _sharingGroupLearnFromUsers(_shareCtx.users);

    const cachedGroup = _sharingGroupGet();
    const groupMember = cachedGroup
      ? _shareCtx.users.find(u => u.groupId === cachedGroup.id)
      : null;
    _shareCtx.groupEnabled = !!groupMember;
    _shareCtx.groupRole = groupMember ? groupMember.role : 'READ_USER';

    const myEmail = (document.getElementById('userEmail')?.textContent || '').trim().toLowerCase();
    const owner = _shareCtx.users.find(u => (u.role || '').toUpperCase() === 'OWNER');
    _shareCtx.iAmOwner = !!(myEmail && owner && (owner.username || '').toLowerCase() === myEmail);
    _shareRender();
  } catch (err) {
    toast('Could not load shares: ' + err.message, 'error');
  }
}

function _shareRender() {
  const ctx = _shareCtx;
  if (!ctx) return;
  const listEl = document.getElementById('shareList');
  const isBulk = !!(ctx.bulkProjectIds && ctx.bulkProjectIds.length);
  if (isBulk) {

    listEl.innerHTML = '';
    listEl.style.display = 'none';
  } else {
    listEl.style.display = '';
  }
  const others = ctx.users.filter(u => u.role !== 'OWNER');
  const owner  = ctx.users.find(u => u.role === 'OWNER');
  if (!isBulk) {
    document.getElementById('shareSub').innerHTML =
      `Currently shared with <b>${others.length}</b> user${others.length === 1 ? '' : 's'}`
      + (owner ? ` (plus you, the owner)` : '');
    if (!ctx.users.length) {
      listEl.innerHTML = `<div class="share-empty">No one has access yet.</div>`;

    }
  }

  if (!isBulk) {
  const rowHtml = (u) => {
    const isOwner = u.role === 'OWNER';
    const name = ((u.firstName || '') + ' ' + (u.lastName || '')).trim();
    const roleLabel = SHARE_ROLE_LABEL[u.role] || u.role;

    const roleControl = isOwner
      ? `<span class="share-role-pill owner" title="${e(SHARE_ROLE_DESC.OWNER)}">${e(roleLabel)}</span>`
      : `<select class="share-role-sel" data-email="${a(u.username)}"
                 title="${e(SHARE_ROLE_DESC[u.role] || '')}"
                 onchange="_shareChangeRoleFromSelect(this)">
           ${_roleOption('READ_USER', u.role)}
           ${_roleOption('WRITE_USER', u.role)}
           ${_roleOption('WRITE_SHARE_USER', u.role)}
         </select>`;
    const removeBtn = isOwner
      ? ''
      : `<button class="share-remove" title="Remove access" onclick="_shareRemove('${j(u.username)}')">&times;</button>`;
    return `<div class="share-row${isOwner ? ' is-owner' : ''}">
      <div class="share-who">
        <div class="share-name">${e(name || u.username)}</div>
        <div class="share-email">${e(u.username)}</div>
      </div>
      <div class="share-role">${roleControl}</div>
      <div class="share-actions">${removeBtn}</div>
    </div>`;
  };

  const sorted = [owner, ...others.sort((a, b) =>
    (a.username || '').localeCompare(b.username || ''))].filter(Boolean);

  const q = (ctx.shareFilter || '').trim().toLowerCase();
  const visible = q
    ? sorted.filter(u => {
        if (u.role === 'OWNER') return true;
        const hay = ((u.firstName || '') + ' ' + (u.lastName || '') + ' ' + (u.username || '')).toLowerCase();
        return hay.includes(q);
      })
    : sorted;

  const filterHtml = others.length > 6
    ? `<input type="text" class="share-list-filter" id="shareListFilter"
              placeholder="Filter by name or email…" value="${e(ctx.shareFilter || '')}"
              oninput="_shareFilterChange(this.value)">`
    : '';
  const listBody = visible.length
    ? visible.map(rowHtml).join('')
    : `<div class="share-empty">No shares match "${e(q)}".</div>`;
  listEl.innerHTML = `${filterHtml}<div class="share-list-body">${listBody}</div>`;

  if (q) {
    const f = document.getElementById('shareListFilter');
    if (f) {
      f.focus();

      const len = f.value.length;
      f.setSelectionRange(len, len);
    }
  }
  }

  const groupSlot = document.getElementById('shareGroupSlot');

  const fetchedGroup = ctx.group;
  const cachedGroup = fetchedGroup
    ? { id: fetchedGroup.groupId, name: fetchedGroup.groupName }
    : _sharingGroupGet();
  if (cachedGroup && cachedGroup.id) {
    const enabled = !!ctx.groupEnabled;
    const currentRole = enabled ? (ctx.groupRole || 'READ_USER') : 'READ_USER';
    const memberCount = fetchedGroup ? (fetchedGroup.members || []).length : null;

    const manageChip = fetchedGroup
      ? `<button class="btn btn-sm btn-secondary" onclick="_toggleGroupMembersPanel()"
                 title="Add or remove people from this group">
           Manage members${memberCount !== null ? ` (${memberCount})` : ''}
           <span class="share-group-manage-caret">${ctx.groupPanelOpen ? '▾' : '▸'}</span>
         </button>
         <button class="btn btn-sm btn-secondary" id="syncGroupSharesBtn" onclick="_refreshGroupShares()"
                 title="Ekahau doesn't push new members to projects you've already shared with the group. This finds every project you own that currently shares this group and re-syncs the membership on all of them in one action.">
           &#x21bb; Sync group shares
         </button>`
      : '';
    groupSlot.style.display = '';
    groupSlot.innerHTML =
      `<label class="share-group-toggle-label">Share with your Sharing Group</label>
       <div class="share-group-row">
         <div class="share-group-name">${e(cachedGroup.name || 'My Sharing Group')}</div>
         <select class="share-role-sel" id="shareGroupRole" ${enabled ? '' : 'disabled'}
                 title="${e(SHARE_ROLE_DESC[currentRole] || '')}"
                 onchange="_shareGroupRoleChange(this)">
           ${_roleOption('READ_USER', currentRole)}
           ${_roleOption('WRITE_USER', currentRole)}
           ${_roleOption('WRITE_SHARE_USER', currentRole)}
         </select>
         <label class="share-group-switch" title="${enabled ? 'Group is currently shared — click to remove' : 'Click to share this project with the whole group'}">
           <input type="checkbox" ${enabled ? 'checked' : ''} onchange="_shareGroupToggle(this)">
           <span class="share-group-slider"></span>
         </label>
       </div>
       ${manageChip ? `<div class="share-group-manage-row">${manageChip}</div>` : ''}
       ${ctx.groupPanelOpen && fetchedGroup ? _renderGroupMembersPanel(fetchedGroup) : ''}`;
  } else {
    groupSlot.style.display = 'none';
    groupSlot.innerHTML = '';
  }

  const dangerSlot = document.getElementById('shareDangerSlot');
  if (dangerSlot) {

    if (isBulk) {
      dangerSlot.hidden = true;
      dangerSlot.innerHTML = '';
    } else if (ctx.iAmOwner) {
      const state = ctx.transferState || {};
      const stage = state.stage || 'idle';

      const seen = new Set();
      const candidates = ctx.users
        .filter(u => (u.role || '').toUpperCase() !== 'OWNER')
        .filter(u => u.username && !seen.has(u.username.toLowerCase()) && seen.add(u.username.toLowerCase()))
        .sort((a, b) => (a.username || '').localeCompare(b.username || ''));
      dangerSlot.hidden = false;

      dangerSlot.classList.toggle('is-armed', stage === 'confirm');
      if (stage === 'confirm') {
        dangerSlot.innerHTML =
          `<label class="share-danger-label">Confirm ownership transfer</label>
           <div class="share-danger-warning">
             <b>${e(state.newOwner)}</b> will become the new owner.
             You'll be demoted to <b>View only</b>. Any group-shared members
             will remain as individual shares (their group link breaks). This
             action cannot be undone unless the new owner transfers it back.
           </div>
           <div class="share-danger-confirm-row">
             <button class="btn btn-red" onclick="_transferOwnershipCommit()">
               Transfer to ${e(state.newOwner)}
             </button>
             <button class="btn btn-secondary" onclick="_transferOwnershipCancel()">Cancel</button>
           </div>`;
      } else if (!candidates.length) {

        dangerSlot.innerHTML =
          `<label class="share-danger-label-quiet">Transfer ownership</label>
           <div class="share-danger-hint-quiet">
             Ekahau only lets you transfer to someone who already has access.
             Share this project with them first, then come back here.
           </div>`;
      } else {
        const options = candidates.map(u => {
          const name = ((u.firstName || '') + ' ' + (u.lastName || '')).trim();
          const label = name ? `${name} (${u.username})` : u.username;
          return `<option value="${a(u.username)}">${e(label)}</option>`;
        }).join('');

        dangerSlot.innerHTML =
          `<div class="share-danger-form">
             <label class="share-danger-label-quiet" for="transferOwnerSelect">
               Transfer ownership to
             </label>
             <select id="transferOwnerSelect" class="share-role-sel">
               <option value="">Choose recipient…</option>
               ${options}
             </select>
             <button class="btn btn-danger" onclick="_transferOwnershipStart()">Transfer&hellip;</button>
           </div>`;
      }
    } else {
      dangerSlot.hidden = true;
      dangerSlot.innerHTML = '';
    }
  }
}

function _renderGroupMembersPanel(group) {
  const members = (group.members || []).slice().sort((a, b) =>
    (a.email || '').localeCompare(b.email || ''));
  const rows = members.length
    ? members.map(m => {
        const name = ((m.firstName || '') + ' ' + (m.lastName || '')).trim();
        return `<div class="share-group-member-row">
          <div class="share-who">
            <div class="share-name">${e(name || m.email)}</div>
            <div class="share-email">${e(m.email)}</div>
          </div>
          <button class="share-remove" title="Remove from group"
                  onclick="_groupRemoveMember('${j(m.email)}')">&times;</button>
        </div>`;
      }).join('')
    : `<div class="share-group-member-empty">No members yet.</div>`;
  return `<div class="share-group-members-panel">
    <div class="share-group-members-hint">
      Anyone in this group can be added to any project in one click via the toggle above.
      Changes here affect the group globally, across all your projects.
    </div>
    <div class="share-group-members-list">${rows}</div>
    <div class="share-add-row share-group-add-row">
      <input type="email" id="groupMemberEmail" placeholder="add-someone@company.com"
             onkeydown="if(event.key==='Enter'){event.preventDefault();_groupAddMember()}">
      <span></span>
      <button class="btn btn-primary" onclick="_groupAddMember()">Add to group</button>
    </div>
  </div>`;
}

let _syncGroupCtx = null;

async function _refreshGroupShares() {

  const btn = document.getElementById('syncGroupSharesBtn');
  const restoreBtn = () => {
    if (btn) { btn.disabled = false; btn.innerHTML = '&#x21bb; Sync group shares'; }
  };
  if (btn) { btn.disabled = true; btn.innerHTML = '&#x21bb; Checking…'; }
  toast('Checking which projects share the group…', 'info');
  try {
    const dry = await pyApi('refresh_group_shares', 'My Sharing Group', true);
    restoreBtn();
    if (dry && dry.error) { toast(dry.error, 'error'); return; }
    const count = dry.count || 0;
    if (count === 0) {
      toast('No projects currently share this group — nothing to refresh', 'info');
      return;
    }

    _syncGroupOpenPicker(dry);
  } catch (err) {
    restoreBtn();
    toast('Refresh failed: ' + err.message, 'error');
  }
}

function _syncGroupOpenPicker(dry) {
  const ids = dry.projectIds || [];
  const groupName = dry.groupName || 'My Sharing Group';

  const nameByCloudId = {};
  const collect = (n) => {
    if (!n) return;

    if (n.id && n.name) nameByCloudId[n.id] = n.name;

    if (n.cloud) {
      if (n.cloud.id && n.cloud.name) nameByCloudId[n.cloud.id] = n.cloud.name;

      if (n.cloud.children) {
        ['matched', 'cloudOnly'].forEach(k => (n.cloud.children[k] || []).forEach(collect));
      }
    }

    if (n.children) {
      ['matched', 'cloudOnly'].forEach(k => (n.children[k] || []).forEach(collect));
    }
  };

  if (typeof data !== 'undefined' && data) {
    (data.matched || []).forEach(collect);
    (data.cloudOnly || []).forEach(collect);
    (data.localOnly || []).forEach(collect);
    (data.orphans && data.orphans.matched || []).forEach(collect);
    (data.orphans && data.orphans.cloudOnly || []).forEach(collect);
  }
  const memberCount = ((_shareCtx && _shareCtx.group && _shareCtx.group.members) || []).length;
  _syncGroupCtx = {
    groupName,
    projectIds: ids,
    selected: new Set(ids),
    nameByCloudId,
    memberCount,
  };
  document.getElementById('syncGroupTitle').textContent =
    `Sync "${groupName}" — ${ids.length} project${ids.length === 1 ? '' : 's'}`;
  const memberLine = memberCount
    ? `Your group has <b>${memberCount}</b> member${memberCount === 1 ? '' : 's'}. `
    : '';
  document.getElementById('syncGroupSub').innerHTML =
    `${memberLine}These are all the projects you own that currently share the group. Uncheck any you want to skip.`;
  _syncGroupRender();
  showModal('syncGroupModal');
}

function _syncGroupRender() {
  const ctx = _syncGroupCtx;
  if (!ctx) return;
  const listEl = document.getElementById('syncGroupList');
  const rows = ctx.projectIds.map(pid => {
    const name = ctx.nameByCloudId[pid] || `(${pid.slice(0, 8)}…)`;
    const isChecked = ctx.selected.has(pid);
    return `<label class="sync-group-row">
      <input type="checkbox" ${isChecked ? 'checked' : ''}
             onchange="_syncGroupTogglePid('${j(pid)}', this.checked)">
      <span class="sync-group-name">${e(name)}</span>
    </label>`;
  }).join('');
  listEl.innerHTML = `<div class="share-list-body">${rows}</div>`;
  _syncGroupUpdateCount();
}

function _syncGroupTogglePid(pid, on) {
  const ctx = _syncGroupCtx;
  if (!ctx) return;
  if (on) ctx.selected.add(pid);
  else ctx.selected.delete(pid);
  _syncGroupUpdateCount();
}

function _syncGroupToggleAll(on) {
  const ctx = _syncGroupCtx;
  if (!ctx) return;
  ctx.selected = new Set(on ? ctx.projectIds : []);
  _syncGroupRender();
}

function _syncGroupUpdateCount() {
  const ctx = _syncGroupCtx;
  if (!ctx) return;
  const n = ctx.selected.size, total = ctx.projectIds.length;
  document.getElementById('syncGroupCount').textContent = `${n} of ${total} selected`;
  const applyBtn = document.getElementById('syncGroupApplyBtn');
  applyBtn.disabled = n === 0;
  applyBtn.textContent = n === total ? `Sync all ${total}` : `Sync ${n} selected`;
}

async function _syncGroupApply() {
  const ctx = _syncGroupCtx;
  if (!ctx || !ctx.selected.size) return;
  const ids = Array.from(ctx.selected);
  const applyBtn = document.getElementById('syncGroupApplyBtn');
  applyBtn.disabled = true;
  const originalText = applyBtn.textContent;
  applyBtn.textContent = 'Syncing…';
  toast(`Syncing ${ids.length} projects — this takes a few seconds…`, 'info');
  try {
    const r = await pyApi('refresh_group_shares', ctx.groupName, false, ids);
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast(r.message || `Refreshed ${r.count} projects`, 'success');
    closeModal('syncGroupModal');
    _scheduleOpRefresh();
  } catch (err) {
    toast('Sync failed: ' + err.message, 'error');
  } finally {
    applyBtn.disabled = false;
    applyBtn.textContent = originalText;
  }
}

function _shareFilterChange(v) {
  if (!_shareCtx) return;
  _shareCtx.shareFilter = v || '';
  _shareRender();
}

function _toggleGroupMembersPanel() {
  if (!_shareCtx) return;
  _shareCtx.groupPanelOpen = !_shareCtx.groupPanelOpen;
  _shareRender();
  if (_shareCtx.groupPanelOpen) {
    setTimeout(() => {
      const el = document.getElementById('groupMemberEmail');
      if (el) el.focus();
    }, 60);
  }
}

async function _groupAddMember() {
  const ctx = _shareCtx;
  if (!ctx) return;
  const input = document.getElementById('groupMemberEmail');
  if (!input) return;
  const email = (input.value || '').trim();
  if (!email || !email.includes('@')) {
    toast('Enter a valid email address', 'error');
    input.focus();
    return;
  }
  input.disabled = true;
  try {
    const r = await pyApi('add_group_member', email, 'My Sharing Group');
    if (r && r.error) { toast(r.error, 'error'); return; }
    if (r && r.already) {
      toast(`${email} is already in the group`, 'info');
    } else {
      toast(`Added ${email} to the group`, 'success');
    }
    input.value = '';

    await _fetchGroupIntoCtx();
    await _shareRefresh();
    _scheduleOpRefresh();
  } catch (err) {
    toast('Add failed: ' + err.message, 'error');
  } finally {
    input.disabled = false;
    const el = document.getElementById('groupMemberEmail');
    if (el) el.focus();
  }
}

async function _groupRemoveMember(email) {
  const ctx = _shareCtx;
  if (!ctx) return;
  if (!confirm(`Remove ${email} from your Sharing Group?\n\nThey'll lose access to every project the group is shared with.`)) return;
  try {
    const r = await pyApi('remove_group_member', email, 'My Sharing Group');
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast(`Removed ${email} from the group`, 'success');
    await _fetchGroupIntoCtx();
    await _shareRefresh();
    _scheduleOpRefresh();
  } catch (err) {
    toast('Remove failed: ' + err.message, 'error');
  }
}

let _bulkShareCtx = null;

async function openBulkShare() {
  const ids = (window._bulkShareOwnedIds || []).slice();
  if (!ids.length) {
    toast('Select cloud projects you own first', 'info');
    return;
  }
  await openManageShares(null, null, ids);
}

function _transferOwnershipStart() {
  const ctx = _shareCtx;
  if (!ctx) return;
  const sel = document.getElementById('transferOwnerSelect');
  const email = (sel?.value || '').trim().toLowerCase();
  if (!email) {
    toast('Choose a new owner from the dropdown', 'error');
    sel?.focus();
    return;
  }

  const myEmail = (document.getElementById('userEmail')?.textContent || '').trim().toLowerCase();
  if (email === myEmail) {
    toast('You are already the owner', 'info');
    return;
  }
  ctx.transferState = { stage: 'confirm', newOwner: email };
  _shareRender();
}

function _transferOwnershipCancel() {
  const ctx = _shareCtx;
  if (!ctx) return;
  ctx.transferState = null;
  _shareRender();
}

async function _transferOwnershipCommit() {
  const ctx = _shareCtx;
  if (!ctx || !ctx.transferState) return;
  const recipient = ctx.transferState.newOwner;
  try {
    const r = await pyApi('transfer_ownership', ctx.projectId, recipient);
    if (r && r.error) {
      toast(r.error, 'error');
      return;
    }
    toast(r.message || `Ownership transferred to ${recipient}`, 'success');

    ctx.transferState = null;
    closeModal('shareModal');
    _scheduleOpRefresh();
    refreshData();
  } catch (err) {
    toast('Transfer failed: ' + err.message, 'error');
  }
}

async function _shareAdd() {
  const ctx = _shareCtx;
  if (!ctx) return;
  const emailEl = document.getElementById('shareEmail');
  const roleEl = document.getElementById('shareRole');
  const email = (emailEl.value || '').trim();
  const role = roleEl.value || 'READ_USER';
  const isBulk = !!(ctx.bulkProjectIds && ctx.bulkProjectIds.length);
  if (!email || !email.includes('@')) {
    toast('Enter a valid email address', 'error');
    emailEl.focus();
    return;
  }

  if (!isBulk && ctx.users.some(u => (u.username || '').toLowerCase() === email.toLowerCase())) {
    toast(email + ' already has access', 'info');
    return;
  }
  emailEl.disabled = true; roleEl.disabled = true;
  try {
    let r;
    if (isBulk) {

      r = await pyApi('bulk_share', ctx.bulkProjectIds, [email], role, false, null, '', 'READ_USER');
    } else {
      r = await pyApi('add_share', ctx.projectId, email, role);
    }
    if (r && r.error) { toast(r.error, 'error'); return; }
    emailEl.value = '';
    if (isBulk) {
      const n = r.ownedCount || 0;
      const skipped = (r.skipped || []).length;
      const msg = `Shared with ${email} on ${n} project${n === 1 ? '' : 's'}`
                + (skipped ? ` (${skipped} skipped — not owner)` : '');
      toast(msg, 'success');
    } else {
      toast(r.message || `Shared with ${email}`, 'success');
      await _shareRefresh();
    }

    _scheduleOpRefresh();
  } catch (err) {
    toast('Add failed: ' + err.message, 'error');
  } finally {
    emailEl.disabled = false; roleEl.disabled = false;
    emailEl.focus();
  }
}

async function _shareRemove(email) {
  const ctx = _shareCtx;
  if (!ctx) return;
  if (!confirm(`Remove ${email} from this project's shares?`)) return;
  try {
    const r = await pyApi('remove_share', ctx.projectId, email);
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast('Removed ' + email, 'success');
    await _shareRefresh();
    _scheduleOpRefresh();
  } catch (err) {
    toast('Remove failed: ' + err.message, 'error');
  }
}

async function _shareGroupToggle(chk) {
  const ctx = _shareCtx;
  const cachedGroup = _sharingGroupGet();
  if (!ctx || !cachedGroup) return;
  const enable = !!chk.checked;
  const isBulk = !!(ctx.bulkProjectIds && ctx.bulkProjectIds.length);
  const roleSel = document.getElementById('shareGroupRole');
  const role = (roleSel && roleSel.value) || 'READ_USER';
  chk.disabled = true;
  try {
    let r;
    if (isBulk) {

      r = await pyApi('bulk_share', ctx.bulkProjectIds, [], role,
                       enable, cachedGroup.id, cachedGroup.name, role);
    } else {
      r = await pyApi('toggle_group_share', ctx.projectId,
                       cachedGroup.id, cachedGroup.name, role, enable);
    }
    if (r && r.error) { toast(r.error, 'error'); chk.checked = !enable; return; }
    if (isBulk) {
      const n = r.ownedCount || 0;
      toast(enable
        ? `Shared ${cachedGroup.name} with ${n} project${n === 1 ? '' : 's'}`
        : `Removed ${cachedGroup.name} from ${n} project${n === 1 ? '' : 's'}`, 'success');
    } else {
      toast(enable ? `Shared with ${cachedGroup.name}` : `Removed ${cachedGroup.name} from shares`, 'success');
      await _shareRefresh();
    }
    _scheduleOpRefresh();
  } catch (err) {
    toast('Group toggle failed: ' + err.message, 'error');
    chk.checked = !enable;
  } finally {
    chk.disabled = false;
  }
}

async function _shareGroupRoleChange(sel) {
  const ctx = _shareCtx;
  const cachedGroup = _sharingGroupGet();
  if (!ctx || !cachedGroup || !ctx.groupEnabled) return;
  const newRole = sel.value;
  sel.disabled = true;
  try {

    const r = await pyApi('toggle_group_share', ctx.projectId,
                          cachedGroup.id, cachedGroup.name, newRole, true);
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast(`Group is now ${SHARE_ROLE_LABEL[newRole] || newRole}`, 'success');
    await _shareRefresh();
    _scheduleOpRefresh();
  } catch (err) {
    toast('Role change failed: ' + err.message, 'error');
  } finally {
    sel.disabled = false;
  }
}

async function _shareChangeRoleFromSelect(sel) {
  const ctx = _shareCtx;
  if (!ctx) return;
  const email = sel.dataset.email;
  const newRole = sel.value;
  sel.disabled = true;
  try {
    const r = await pyApi('change_share_role', ctx.projectId, email, newRole);
    if (r && r.error) { toast(r.error, 'error'); await _shareRefresh(); return; }
    toast(`${email} is now ${SHARE_ROLE_LABEL[newRole] || newRole}`, 'success');
    await _shareRefresh();
    _scheduleOpRefresh();
  } catch (err) {
    toast('Role change failed: ' + err.message, 'error');
    await _shareRefresh();
  } finally {
    sel.disabled = false;
  }
}

async function verifyReplaceLocal(cloudId, localPath, cloudName) {
  if (!confirm(`Verify pair: "${cloudName}"\n\nDownload the cloud copy and overwrite the local file. They'll be byte-identical afterward and the pair will show as ✓ Same file.\n\nIf local is newer than cloud, this will be skipped — no data loss.`)) return;
  opEnqueue({
    title: `Verifying "${cloudName}"`,
    type: 'verify', pollBackend: false, undoable: false,
    run: async () => {
      const r = await pyApi('verify_replace_local', cloudId, localPath);
      if (r && r.error) {
        _markVerifyFailed(cloudId, localPath);
        if (r.error === 'local_newer') {
          throw new Error('Skipped — local is newer than cloud (' + (r.message || 'would lose local edits') + ')');
        }
        throw new Error(r.error);
      }
      _scheduleOpRefresh();
      return r;
    },
  });
}

function _markVerifyFailed(cloudId, localPath) {
  _verifyFailedPairs.add(_verifyFailedKey(cloudId, localPath));
  if (typeof renderRows === 'function') renderRows();
}

async function bulkVerifyNameMatches() {
  const targets = [];
  const seen = new Set();
  const pushIfPair = (pair) => {
    if (!pair || pair.kind !== 'pair' || pair.matchType !== 'exact') return;
    if (seen.has(pair.cloudId)) return;
    seen.add(pair.cloudId);
    targets.push(pair);
  };
  selected.forEach(k => {
    const d = rowData[k]; if (!d) return;
    if (d.kind === 'pair') { pushIfPair(d); return; }

    if (k.startsWith('ct-c:')) {
      pushIfPair(rowData['ct:' + k.slice('ct-c:'.length)]);
    } else if (k.startsWith('ct-l:')) {

      for (const rk in rowData) {
        if (!rk.startsWith('ct:')) continue;
        const rd = rowData[rk];
        if (rd.kind === 'pair' && rd.localPath === d.path) { pushIfPair(rd); break; }
      }
    }
  });
  if (!targets.length) {
    toast('Select some "Name matches" pairs first', 'info');
    return;
  }
  if (!confirm(`Verify ${targets.length} pair${targets.length === 1 ? '' : 's'}?\n\nEach one downloads the cloud copy and overwrites the local file. Pairs where local is newer than cloud are skipped automatically.`)) return;
  clearSelection();
  for (const d of targets) {
    opEnqueue({
      title: `Verifying "${d.cloudName}"`,
      type: 'verify', pollBackend: false, undoable: false,
      run: async () => {
        const r = await pyApi('verify_replace_local', d.cloudId, d.localPath);
        if (r && r.error) {
          _markVerifyFailed(d.cloudId, d.localPath);
          if (r.error === 'local_newer') {
            throw new Error('Skipped — local is newer than cloud');
          }
          throw new Error(r.error);
        }
        _scheduleOpRefresh();
        return r;
      },
    });
  }
}

async function unmarkManualMatch(cloudId, localPath, cloudName, localName) {
  if (!confirm(`Unlink these?\n\nCloud:  ${cloudName || cloudId}\nLocal:  ${localName || localPath}\n\nWD will go back to auto-matching them.`)) return;
  try {
    const r = await pyApi('unmark_manual_match', cloudId, localPath);
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast('Unlinked', 'success');
    refreshData();
  } catch (e) { toast('Unlink failed: ' + e.message, 'error'); }
}

let _linkPickerCtx = null;
function _collectOrphansOfKind(kind, side) {

  const out = [];
  const seen = new Set();
  const push = (item, extra) => {
    const k = side === 'cloud' ? item.id : item.path;
    if (seen.has(k)) return;
    seen.add(k);
    out.push({ ...item, ...(extra || {}) });
  };
  if (kind === 'projects') {
    if (side === 'cloud') {
      (data.cloudOnly || []).forEach(x => push(x));
      (data.orphans && data.orphans.cloudOnly || []).forEach(x => push(x));
      (data.matched || []).forEach(p => {
        ((p.cloud && p.cloud.children && p.cloud.children.cloudOnly) || []).forEach(x => push(x, { _parentSite: p.cloud.name }));
      });
      (data.localOnly || []).forEach(f => {
        ((f.children && f.children.cloudOnly) || []).forEach(x => push(x));
      });
    } else {
      (data.localOnly || []).forEach(x => push(x));
      (data.matched || []).forEach(p => {
        ((p.cloud && p.cloud.children && p.cloud.children.localOnly) || []).forEach(x => push(x, { _parentSite: p.cloud.name }));
      });
      (data.cloudOnly || []).forEach(s => {
        ((s.children && s.children.localOnly) || []).forEach(x => push(x));
      });
    }
  }
  return out;
}

function openLinkPicker(sourceSide, sourceId, sourceName) {
  const oppositeSide = sourceSide === 'cloud' ? 'local' : 'cloud';
  const code = (sourceName.match(/^([A-Z]{2,}[0-9]+)/) || [])[1] || '';
  _linkPickerCtx = { sourceSide, sourceId, sourceName, code, oppositeSide };

  const candidates = _collectOrphansOfKind('projects', oppositeSide);

  candidates.sort((a, b) => {
    const ac = a.code === code ? 0 : 1;
    const bc = b.code === code ? 0 : 1;
    if (ac !== bc) return ac - bc;
    return (a.name || '').localeCompare(b.name || '', undefined, { sensitivity: 'base' });
  });
  _linkPickerCtx.allCandidates = candidates;

  const sourceLabel = sourceSide === 'cloud' ? 'CLOUD' : 'LOCAL';
  const oppositeLabel = oppositeSide === 'cloud' ? 'CLOUD' : 'LOCAL';
  document.getElementById('linkPickerTitle').textContent = `Link to a ${oppositeSide} counterpart`;
  document.getElementById('linkPickerSub').textContent =
    `Pick the ${oppositeSide} file to link with this ${sourceSide} orphan. Overrides all auto-matching.`;
  document.getElementById('linkPickerSource').innerHTML =
    `<div class="lp-source-inner">
       <span class="hb-tag ${sourceSide}">${sourceLabel}</span>
       <span class="lp-source-name">${e(sourceName)}</span>
     </div>
     <div class="lp-arrow">&#10233;</div>
     <div class="lp-target-hint">
       <span class="hb-tag ${oppositeSide}">${oppositeLabel}</span>
       <span class="lp-target-hint-txt">Pick one below</span>
     </div>`;
  document.getElementById('linkPickerSearch').value = '';
  _lpFilter('');
  showModal('linkPickerModal');
  setTimeout(() => document.getElementById('linkPickerSearch').focus(), 50);
}

function _lpFilter(q) {
  const ctx = _linkPickerCtx;
  if (!ctx) return;
  const query = (q || '').trim().toLowerCase();
  const filtered = query
    ? ctx.allCandidates.filter(c => (c.name || '').toLowerCase().includes(query))
    : ctx.allCandidates;
  const list = document.getElementById('linkPickerList');
  const emptyEl = document.getElementById('linkPickerEmpty');
  if (!filtered.length) {
    list.innerHTML = '';
    emptyEl.hidden = false;
    return;
  }
  emptyEl.hidden = true;
  list.innerHTML = filtered.map(c => {
    const isSameCode = ctx.code && c.code === ctx.code;
    const idOrPath = ctx.oppositeSide === 'cloud' ? c.id : c.path;
    const subtitle = ctx.oppositeSide === 'cloud'
      ? (c.siteName || c._parentSite || '')
      : (c.folder || c._parentSite || '');
    return `<div class="lp-item${isSameCode ? ' same-site' : ''}"
                 onclick="_lpPick('${j(idOrPath)}','${j(c.name || '')}')">
      <div class="lp-item-main">
        <span class="lp-item-name">${e(c.name || '')}</span>
        ${isSameCode ? '<span class="lp-item-tag">same site</span>' : ''}
      </div>
      ${subtitle ? `<div class="lp-item-sub">${e(subtitle)}</div>` : ''}
    </div>`;
  }).join('');
}

function openMatchHelp() {
  showModal('matchHelpModal');
  try { localStorage.setItem('wd-match-help-seen', '1'); } catch (e) {}
  const hint = document.getElementById('matchHelpHint');
  if (hint) hint.style.display = 'none';
}
function _lpPick(oppIdOrPath, oppName) {
  const ctx = _linkPickerCtx;
  if (!ctx) return;
  const cloudId = ctx.sourceSide === 'cloud' ? ctx.sourceId : oppIdOrPath;
  const localPath = ctx.sourceSide === 'local' ? ctx.sourceId : oppIdOrPath;
  const cloudName = ctx.sourceSide === 'cloud' ? ctx.sourceName : oppName;
  const localName = ctx.sourceSide === 'local' ? ctx.sourceName : oppName;
  closeModal('linkPickerModal');
  markManualMatch(cloudId, localPath, cloudName, localName);
}

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

function _mergeMatchScore(dst) {
  if (!dst) return 0;
  let score = _fuzzySim(mergeState.srcName, dst.name);
  const srcCode = mergeState.srcCode || _extractSiteCode(mergeState.srcName);
  const dstCode = dst.code || _extractSiteCode(dst.name);
  if (srcCode && dstCode && srcCode === dstCode) score += 1.0;
  return score;
}
function renderMergeDests() {
  const q = (document.getElementById('mergeDestSearch').value || '').toLowerCase();
  const list = localFolders()
    .filter(f => f.path !== mergeState.srcPath && (!q || f.name.toLowerCase().includes(q)))
    .map(f => ({ f, score: _mergeMatchScore(f) }))
    .sort((a, b) => (b.score - a.score) || a.f.name.localeCompare(b.f.name));
  let h = list.length ? '' : `<div class="peek-more">No other folders to merge into.</div>`;
  list.forEach(({ f, score }) => {
    const isMatch = score >= 0.5;
    h += `<div class="peek-row pick" onclick="chooseMergeDest('${pj(f.path)}')">
      <span class="pk-name">${isMatch ? '<b class="amber">★</b> ' : ''}${e(f.name)}</span>
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
    wrap.hidden = true; listEl.innerHTML = ''; btn.disabled = true; showModal('mergeModal'); return;
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

  const autoDelete = (document.getElementById('mergeDeleteSrc') || {}).checked;
  if (res.srcEmpty && autoDelete) {
    opEnqueue({
      title: `Cleaning up empty "${res.srcName || mergeState.srcName}"`,
      type: 'delete', pollBackend: false, undoable: false,
      run: async () => {
        const r = await pyApi('delete_local', res.srcPath || mergeState.srcPath);
        if (r && r.error) throw new Error(r.error);
        _scheduleOpRefresh();
        return r;
      },
    });
  } else if (res.srcEmpty) {

    setTimeout(() => startDelete('local', res.srcPath, res.srcName, true), 450);
  }
}

function toggleMainMenu(ev) {
  WD.toggleMenu(ev, 'mainMenu');
}

function closeMainMenu() {
  var m = document.getElementById('mainMenu');
  if (m) m.classList.remove('open');
}
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

// Deliberately in-memory only, NOT persisted to localStorage. It used to
// survive across page loads/sessions, which meant switching to Mine/Others
// once silently stuck it there forever with no obvious reminder — that's
// exactly what made a fully-populated Sites tab look like it only had 3
// sites on a different machine. Every fresh load now starts at "all";
// switching mid-session still works normally.
let _ownerFilterState = 'all';
function ownerFilter() {
  return _ownerFilterState;
}
function setOwnerFilter(v) {
  _ownerFilterState = v;
}

function setOwnerFilterUI(v) {
  setOwnerFilter(v);
  syncOwnerToggle();
  updateDashboard();
  renderRows();
}
function syncOwnerToggle() {
  const cur = ownerFilter();
  document.querySelectorAll('#ownerToggle .owner-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.owner === cur);
  });
}

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
  // Every rendered .rowchk carries a key rowData actually understands
  // (site-level and nested-file rows alike, each side independently since
  // the s-c:/s-l:/ct-c:/ct-l: split) — "All" means all of them, full stop.
  document.querySelectorAll('.rowchk').forEach(b => {
    const k = b.dataset.k || '';
    b.checked = on;
    if (on) selected.add(k); else selected.delete(k);
  });
  updateBulkBar();
}
// Replaces the current selection with just one side — every cloud site AND
// cloud project, or every local folder AND local file, across the whole
// tree — so pushing a renamed-everything-locally naming convention up to
// the cloud (or vice versa) is a two-click "select side, then Sync" instead
// of hand-picking rows one at a time.
function selectAllSide(side) {
  document.querySelectorAll('.rowchk').forEach(b => {
    const k = b.dataset.k || '';
    const d = rowData[k];
    const on = !!(d && d.kind === side);
    b.checked = on;
    if (on) selected.add(k); else selected.delete(k);
  });
  const sa = document.getElementById('selAll'); if (sa) sa.checked = false;
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

  let pairCount = 0, deletableCount = 0, movableCount = 0, localFolderCount = 0, uploadableCount = 0, downloadableCount = 0;
  let verifyableCount = 0;
  const verifyablePairIds = new Set();

  const ownedCloudIds = new Set();
  const myEmail = ((data && data.currentUser) || '').toLowerCase();
  selected.forEach(k => {
    const d = rowData[k]; if (!d) return;

    const isTreeChild = k.startsWith('ct:');
    if (d.kind === 'pair') {
      pairCount++;
      localFolderCount++;
      if (currentTab === 'projects' || isTreeChild) deletableCount++;

      if (d.matchType === 'exact' && (currentTab === 'projects' || isTreeChild)) {
        if (!verifyablePairIds.has(d.cloudId)) {
          verifyablePairIds.add(d.cloudId);
          verifyableCount++;
        }
      }
    }

    if (k.startsWith('ct-c:')) {
      const cloudId = k.slice('ct-c:'.length);
      const pair = rowData['ct:' + cloudId];
      if (pair && pair.kind === 'pair' && pair.matchType === 'exact' && !verifyablePairIds.has(cloudId)) {
        verifyablePairIds.add(cloudId);
        verifyableCount++;
      }
    } else if (k.startsWith('ct-l:')) {

      for (const rk in rowData) {
        if (!rk.startsWith('ct:')) continue;
        const rd = rowData[rk];
        if (rd.kind === 'pair' && rd.localPath === d.path
            && rd.matchType === 'exact'
            && !verifyablePairIds.has(rd.cloudId)) {
          verifyablePairIds.add(rd.cloudId);
          verifyableCount++;
          break;
        }
      }
    }

    const cloudIdOfRow = d.cloudId || (d.kind === 'cloud' ? d.id : null);
    if ((d.kind === 'pair' || d.kind === 'cloud') && cloudIdOfRow) {
      const ownerOf = (d.cloudOwner || '').toLowerCase();
      if (myEmail && ownerOf === myEmail) ownedCloudIds.add(cloudIdOfRow);
    }
    if (d.kind === 'cloud' || d.kind === 'local') deletableCount++;
    if (d.kind === 'local') localFolderCount++;
    if (currentTab === 'projects' && (d.kind === 'cloud' || (d.kind === 'local' && !d.isDir))) {
      movableCount++;
    }

    if (currentTab === 'projects' && d.kind === 'local' && !d.isDir) uploadableCount++;

    if (currentTab === 'projects' && d.kind === 'cloud') downloadableCount++;
  });
  const syncItems = selectedSyncItems();
  const syncPairCount = syncItems.filter(d => d.kind === 'pair').length;
  const syncUploadCount = syncItems.filter(d => isProjectSyncItem(d) && d.kind === 'local' && !d.isDir).length;
  const syncDownloadCount = syncItems.filter(d => isProjectSyncItem(d) && d.kind === 'cloud').length;
  const setBtn = (id, tabVisible, enabled, disabledTitle, tooltip) => {
    const el = document.getElementById(id); if (!el) return;
    el.style.display = tabVisible ? '' : 'none';
    el.disabled = !enabled;
    el.classList.toggle('is-disabled', !enabled);
    if (!enabled && disabledTitle) el.dataset.disabledTitle = disabledTitle;
    if (tooltip) el.title = tooltip;
  };
  const syncFromTip = currentTab === 'projects'
    ? 'Push local → cloud: renames matched cloud projects to the local name, and uploads local-only .esx files to Ekahau Cloud'
    : 'Copy local names onto matched cloud';
  const syncToTip = currentTab === 'projects'
    ? 'Pull cloud → local: renames matched local files to the cloud name, and downloads cloud-only projects as .esx files'
    : 'Copy cloud names onto matched local';
  setBtn('bulkSyncTo', true, syncPairCount + syncDownloadCount > 0, 'Sync → needs matched rows or cloud-only projects', syncToTip);
  setBtn('bulkSyncFrom', true, syncPairCount + syncUploadCount > 0, 'Sync ← needs matched rows or local-only .esx files', syncFromTip);
  setBtn('bulkVerifyBtn', true, verifyableCount > 0, 'Select one or more Name-matches pairs to verify (download cloud → overwrite local)');
  setBtn('bulkShareBtn', true, ownedCloudIds.size > 0,
    'Select one or more cloud projects you own — Ekahau only lets the owner add shares',
    ownedCloudIds.size > 0
      ? `Share ${ownedCloudIds.size} project${ownedCloudIds.size === 1 ? '' : 's'} with people or your Sharing Group in one action`
      : undefined);

  window._bulkShareOwnedIds = Array.from(ownedCloudIds);
  setBtn('bulkDeleteBtn', true, deletableCount > 0, 'Bulk delete only works on cloud-only or local-only rows');
  setBtn('compareBtn', currentTab === 'sites', localFolderCount >= 2, 'Select 2+ local folders to compare');
  setBtn('bulkMoveBtn', currentTab === 'projects', movableCount > 0, 'Select cloud projects or local .esx files first');
}

function isProjectSyncItem(d) {
  return !!d && (currentTab === 'projects' || d.entityKind === 'projects');
}

function selectedSyncItems() {
  const byIdentity = new Map();
  [...selected].forEach(k => {
    let d = rowData[k];
    if (!d) return;
    if (k.startsWith('ct-c:')) {
      d = rowData['ct:' + k.slice('ct-c:'.length)] || d;
    } else if (k.startsWith('ct-l:')) {
      const localPath = d.path;
      d = Object.entries(rowData)
        .filter(([rk]) => rk.startsWith('ct:'))
        .map(([, rd]) => rd)
        .find(rd => rd.kind === 'pair' && rd.localPath === localPath) || d;
    } else if (k.startsWith('s-c:')) {
      d = rowData['p:' + k.slice('s-c:'.length)] || d;
    } else if (k.startsWith('s-l:')) {
      const localPath = d.path;
      d = Object.entries(rowData)
        .filter(([rk]) => rk.startsWith('p:'))
        .map(([, rd]) => rd)
        .find(rd => rd.kind === 'pair' && rd.localPath === localPath) || d;
    }
    const identity = d.kind === 'pair' ? `pair:${d.cloudId}`
      : d.kind === 'cloud' ? `cloud:${d.id}` : `local:${d.path}`;
    byIdentity.set(identity, d);
  });
  return [...byIdentity.values()];
}

async function bulkSync(dir) {
  const items = selectedSyncItems();
  const pairs = items.filter(d => d.kind === 'pair');
  const uploads = dir === 'to-cloud'
    ? items.filter(d => isProjectSyncItem(d) && d.kind === 'local' && !d.isDir)
    : [];
  const downloads = dir === 'to-local'
    ? items.filter(d => isProjectSyncItem(d) && d.kind === 'cloud')
    : [];
  if (!pairs.length && !uploads.length && !downloads.length) {
    toast(dir === 'to-cloud'
      ? 'Select matched rows or local-only .esx files first'
      : 'Select matched rows or cloud-only projects first', 'info');
    return;
  }
  if (uploads.length) {
    const msg = uploads.length === 1
      ? `Upload "${uploads[0].name}.esx" to Ekahau Cloud?`
      : `Upload ${uploads.length} local .esx files to Ekahau Cloud?`;
    if (!confirm(msg)) return;
  }
  if (downloads.length) {
    const msg = downloads.length === 1
      ? `Download "${downloads[0].name}" from Ekahau Cloud? It will land in a folder named after the project.`
      : `Download ${downloads.length} projects from Ekahau Cloud? Each will land in its own folder.`;
    if (!confirm(msg)) return;
  }
  clearSelection();

  if (pairs.length) {
    let ok = 0, fail = 0, firstErr = '';
    for (const d of pairs) {
      try {
        const r = (dir === 'to-local')
          ? await pyApi('rename_local', d.localPath, d.cloudName)
          : await pyApi('rename_cloud', d.entityKind || currentTab, d.cloudId, d.localName);
        if (r && r.error) { fail++; firstErr = firstErr || r.error; }
        else ok++;
      } catch (err) { fail++; firstErr = firstErr || (err.message || 'failed'); }
    }
    if (fail === 0) toast(`Renamed ${ok} file${ok === 1 ? '' : 's'}`, 'success');
    else if (ok === 0) toast(`Rename failed: ${firstErr}`, 'error');
    else toast(`Renamed ${ok} · ${fail} failed (${firstErr})`, 'error');
    _scheduleOpRefresh();
  }

  for (const d of uploads) {
    opEnqueue({
      title: `Uploading "${d.name}.esx"`,
      type: 'upload', pollBackend: true,

      undoable: false,
      retryFn: async (newId) => pyApi('upload_project', d.path, undefined, newId),
      run: async (opId) => pyApi('upload_project', d.path, undefined, opId),
    });
  }
  for (const d of downloads) {

    const destFolder = d.siteName || d.name;
    const title = d.siteName
      ? `Downloading "${d.name}.esx" → ${d.siteName}`
      : `Downloading "${d.name}.esx"`;
    opEnqueue({
      title,
      type: 'download', pollBackend: true,
      undoable: false,
      retryFn: async (newId) => pyApi('download_project', d.id, destFolder, newId),
      run: async (opId) => pyApi('download_project', d.id, destFolder, opId),
    });
  }

}
function bulkDelete() {

  const contextForKey = (k) => (k.startsWith('ct') ? 'projects' : currentTab);
  const entries = [...selected].map(k => ({ k, d: rowData[k] })).filter(x => x.d);
  const items = [];
  let nPair = 0;
  for (const { k, d } of entries) {
    const ctx = contextForKey(k);
    if (d.kind === 'cloud' || d.kind === 'local') {
      items.push({ ...d, context: ctx });
    } else if (d.kind === 'pair') {

      const isTreeChild = k.startsWith('ct:');
      if (currentTab === 'sites' && !isTreeChild) continue;
      nPair++;
      items.push({ kind: 'cloud', id: d.cloudId, name: d.cloudName, context: ctx });
      items.push({ kind: 'local', path: d.localPath, name: d.localName, isDir: false, context: ctx });
    }
  }
  if (!items.length) {
    toast('Nothing to delete. Select a cloud or local checkbox on one or more rows first.', 'info');
    return;
  }
  const nCloud = items.filter(d => d.kind === 'cloud').length;
  const nLocal = items.filter(d => d.kind === 'local').length;

  const isSiteish = (d) => (d.context || currentTab) === 'sites';
  const cloudItems = items.filter(d => d.kind === 'cloud');
  const localItems = items.filter(d => d.kind === 'local');
  const nCloudSite = cloudItems.filter(isSiteish).length;
  const nCloudProject = cloudItems.length - nCloudSite;
  const nLocalFolder = localItems.filter(isSiteish).length;
  const nLocalFile = localItems.length - nLocalFolder;
  const parts = [];
  if (nPair) parts.push(`<b>${nPair}</b> matched pair${nPair === 1 ? '' : 's'} (both cloud and local sides)`);
  const cloudUnpaired = nCloud - nPair;
  const localUnpaired = nLocal - nPair;
  if (cloudUnpaired) {

    const noun = nCloudSite && !nCloudProject ? 'site(s)'
               : nCloudProject && !nCloudSite ? 'project(s)'
               : 'cloud item(s)';
    parts.push(`<b>${cloudUnpaired}</b> cloud ${noun}`.replace('cloud cloud', 'cloud'));
  }
  if (localUnpaired) {
    const noun = nLocalFolder && !nLocalFile ? 'folder(s) and all their contents'
               : nLocalFile && !nLocalFolder ? '.esx file(s)'
               : 'local item(s)';
    parts.push(`<b>${localUnpaired}</b> local ${noun}`.replace('local local', 'local'));
  }
  deleteTarget = { bulk: items };
  document.getElementById('deleteTitle').textContent = 'Delete selected?';
  document.getElementById('deleteSub').innerHTML = `Permanently delete ${parts.join(' and ')}. This cannot be undone.`;
  showModal('deleteModal');
}

document.getElementById('searchBox').addEventListener('input', renderRows);

document.getElementById('rowsContainer').addEventListener('click', onRowChkClick);
function clearSearch() {
  const sb = document.getElementById('searchBox');
  if (sb.value) { sb.value = ''; renderRows(); }
  sb.focus();
}

async function syncRow(dir, cloudId, name, localPath, kind) {
  kind = kind || currentTab;

  const label = dir === 'to-local'
    ? `Renaming local to "${name}"`
    : `Renaming cloud to "${name}"`;
  opEnqueue({
    title: label,
    type: 'rename', pollBackend: false, undoable: false,
    run: async () => {
      const r = (dir === 'to-local')
        ? await pyApi('rename_local', localPath, name)
        : await pyApi('rename_cloud', kind, cloudId, name);
      if (r && r.error) throw new Error(r.error);
      _scheduleOpRefresh();
      return r;
    },
  });
}

function startRename(side, idOrPath, name, kind) {
  kind = kind || currentTab;
  renameTarget = { side, idOrPath, kind };
  const noun = side === 'cloud'
    ? (kind === 'sites' ? 'Cloud Site' : 'Cloud Project')
    : (kind === 'sites' ? 'Local Folder' : 'Local .esx File');
  document.getElementById('renameTitle').textContent = 'Rename ' + noun;
  document.getElementById('renameSub').textContent = 'Current: ' + name;
  document.getElementById('renameInput').value = name;
  showModal('renameModal'); document.getElementById('renameInput').select();
}
async function confirmRename() {
  const n = document.getElementById('renameInput').value.trim();
  if (!n || !renameTarget) { closeModal('renameModal'); return; }
  const rt = renameTarget;
  closeModal('renameModal');

  opEnqueue({
    title: `Renaming to "${n}"`,
    type: 'rename', pollBackend: false, undoable: false,
    run: async () => {
      const r = rt.side === 'cloud'
        ? await pyApi('rename_cloud', rt.kind || currentTab, rt.idOrPath, n)
        : await pyApi('rename_local', rt.idOrPath, n);
      if (r && r.error) throw new Error(r.error);
      _scheduleOpRefresh();
      return r;
    },
  });
}

function startDelete(side, idOrPath, name, isDir, kind) {
  kind = kind || currentTab;
  deleteTarget = { side, idOrPath, kind };
  let warn;
  if (side === 'cloud') {
    warn = kind === 'sites'
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
// ── Cloud-delete second confirmation ──
// Local deletes stay one confirm, same as always — the cloud copy (if any)
// is untouched, so it's recoverable by re-downloading. Cloud deletes are
// not recoverable, so ANY cloud deletion (single or bulk) gets a second,
// harder-to-click-through gate: restate exactly what's being destroyed and
// require literally typing DELETE before the button even enables.
let _pendingCloudDelete = null;
function _updateCloudDeleteConfirmBtn() {
  const ok = (document.getElementById('cloudDeleteConfirmInput').value || '').trim().toUpperCase() === 'DELETE';
  document.getElementById('cloudDeleteConfirmBtn').disabled = !ok;
}
function _cancelCloudDeleteStage2() {
  _pendingCloudDelete = null;
  document.getElementById('cloudDeleteConfirmInput').value = '';
  document.getElementById('cloudDeleteConfirmBtn').disabled = true;
  closeModal('cloudDeleteConfirmModal');
}
function _confirmCloudDeleteStage2() {
  const fn = _pendingCloudDelete;
  _pendingCloudDelete = null;
  document.getElementById('cloudDeleteConfirmInput').value = '';
  document.getElementById('cloudDeleteConfirmBtn').disabled = true;
  closeModal('cloudDeleteConfirmModal');
  if (fn) fn();
}
function _requireCloudDeleteConfirm(summaryHtml, runFn) {
  _pendingCloudDelete = runFn;
  document.getElementById('cloudDeleteConfirmSub').innerHTML = summaryHtml;
  document.getElementById('cloudDeleteConfirmInput').value = '';
  document.getElementById('cloudDeleteConfirmBtn').disabled = true;
  showModal('cloudDeleteConfirmModal');
  document.getElementById('cloudDeleteConfirmInput').focus();
}

async function confirmDelete() {
  if (!deleteTarget) { closeModal('deleteModal'); return; }
  closeModal('deleteModal');

  if (deleteTarget.bulk) {
    const items = deleteTarget.bulk;
    const runBulk = () => {
      clearSelection();
      for (const d of items) {
        const label = d.kind === 'cloud'
          ? `Deleting cloud "${d.name || d.id}"`
          : `Deleting local "${d.name || d.path}"`;
        opEnqueue({
          title: label,
          type: 'delete', pollBackend: false, undoable: false,
          run: async () => {
            const kind = d.context || currentTab;
            const r = d.kind === 'cloud'
              ? await pyApi('delete_cloud', kind, d.id)
              : await pyApi('delete_local', d.path);
            if (r && r.error) throw new Error(r.error);
            _scheduleOpRefresh();
            return r;
          },
        });
      }
    };
    const cloudItems = items.filter(d => d.kind === 'cloud');
    if (cloudItems.length) {
      const nCloudSite = cloudItems.filter(d => (d.context || currentTab) === 'sites').length;
      const nCloudProject = cloudItems.length - nCloudSite;
      const bits = [];
      if (nCloudSite) bits.push(`<b>${nCloudSite}</b> whole site${nCloudSite === 1 ? '' : 's'} — every project inside ${nCloudSite === 1 ? 'it' : 'them'} goes too`);
      if (nCloudProject) bits.push(`<b>${nCloudProject}</b> project${nCloudProject === 1 ? '' : 's'}`);
      const summary = `You're about to permanently delete ${bits.join(' and ')} from Ekahau Cloud. `
        + `Once this runs, none of it will exist on the cloud anymore — for anyone. Local copies (if any) are not touched.`;
      _requireCloudDeleteConfirm(summary, runBulk);
    } else {
      runBulk();
    }
    return;
  }
  const single = deleteTarget;
  const runSingle = () => {
    const label = single.side === 'cloud'
      ? `Deleting cloud ${(single.kind || currentTab) === 'sites' ? 'site' : 'project'}`
      : 'Deleting local file';
    opEnqueue({
      title: label,
      type: 'delete', pollBackend: false, undoable: false,
      run: async () => {
        const r = single.side === 'cloud'
          ? await pyApi('delete_cloud', single.kind || currentTab, single.idOrPath)
          : await pyApi('delete_local', single.idOrPath);
        if (r && r.error) throw new Error(r.error);
        _scheduleOpRefresh();
        return r;
      },
    });
  };
  if (single.side === 'cloud') {
    const isSite = (single.kind || currentTab) === 'sites';
    const summary = isSite
      ? `You're about to permanently delete this <b>whole site</b> from Ekahau Cloud — every project inside it goes too. Once this runs, none of it will exist on the cloud anymore. Local copies (if any) are not touched.`
      : `You're about to permanently delete this <b>project</b> from Ekahau Cloud. Once this runs, it will not exist on the cloud anymore. Local copies (if any) are not touched.`;
    _requireCloudDeleteConfirm(summary, runSingle);
  } else {
    runSingle();
  }
}

async function createSite() {
  const n = document.getElementById('newSiteName').value.trim();
  if (!n) return;
  const doCloud = document.getElementById('createCloud').checked;
  const doLocal = document.getElementById('createLocal').checked;
  if (!doCloud && !doLocal) { toast('Select at least one destination', 'error'); return; }
  try {
    const results = [];
    let localSubfolders = [];
    if (doCloud) {
      const r = await pyApi('create_site', n);
      if (r && r.error) { toast('Cloud: ' + r.error, 'error'); return; }
      results.push('cloud');
    }
    if (doLocal) {
      const r = await pyApi('create_local_folder', n);
      if (r && r.error) { toast('Local: ' + r.error, 'error'); return; }
      localSubfolders = (r && r.subfolders) || [];
      results.push('local');
    }
    const where = results.join(' + ');
    const suffix = localSubfolders.length ? ' — local side got ' + localSubfolders.join('/') + ' subfolders' : '';
    toast('Created "' + n + '" (' + where + ')' + suffix, 'success'); closeModal('createModal');
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
    const r = await runWithProgress(
      { title: `Uploading "${name}.esx"`,
        subtitle: 'Sending to Ekahau Cloud — larger projects take longer.' },
      (opId) => pyApi('upload_project', path, siteId || undefined, opId)
    );
    if (r && r.error) { toast(r.error, 'error'); return; }
    if (r && r.warning) toast(r.warning, 'warn');
    else toast('Uploaded "' + name + '.esx"', 'success');

    refreshData();
  } catch (err) { toast(err.message, 'error'); }
}

async function downloadThenMove(projectId, projectName) {

  const rd = rowData['ct:' + projectId] || rowData['c:' + projectId] || rowData['p:' + projectId];
  const siteName = rd && (rd.siteName || (rd.cloud && rd.cloud.siteName)) || '';
  const destFolder = siteName || projectName;
  const skipPicker = !!siteName;
  const promptMsg = skipPicker
    ? `Download "${projectName}" into local folder "${siteName}"?`
    : `Download "${projectName}" from Ekahau Cloud? You'll pick a site folder next.`;
  if (!confirm(promptMsg)) return;
  try {
    const r = await runWithProgress(
      { title: `Downloading "${projectName}"`,
        subtitle: skipPicker
          ? `Landing in ${siteName} — the project's site folder.`
          : 'Fetching from Ekahau Cloud — floor plan images can take a moment.' },
      (opId) => pyApi('download_project', projectId, destFolder, opId)
    );
    if (r && r.error) { toast(r.error, 'error'); return; }
    if (skipPicker) {
      toast(`Downloaded "${r.name || projectName}" into ${siteName}`, 'success');
      _scheduleOpRefresh();
    } else {
      toast(`Downloaded "${r.name || projectName}" — pick a site to sort it under`, 'success');
      _moveToSiteTargets = [{ kind: 'local', path: r.path, name: r.name || projectName }];
      await _openMoveToSitePicker();
    }
  } catch (err) { toast(err.message || 'Download failed', 'error'); }
}

async function pickFolder() {
  const r = await pyApi('pick_folder');
  if (!r || r.error) { if (r && r.error !== 'No folder selected') toast(r.error, 'error'); return; }
  if (r.path) {
    _outputDir = r.path;
    rememberProjectDirectory(r.path);
  }
  refreshData();
}

async function createLocalFolder(name) {
  try {
    const r = await pyApi('create_local_folder', name);
    if (r && r.error) { toast(r.error, 'error'); return; }
    const sf = (r && r.subfolders) || [];
    const suffix = sf.length ? ' with ' + sf.join('/') + ' subfolders' : '';
    toast('Created local folder "' + name + '"' + suffix, 'success');
    refreshData();
  } catch (err) { toast(err.message, 'error'); }
}

let _moveToSiteTargets = [];
let _moveToSiteSites = [];

function _fmtSize(n) {
  if (!n && n !== 0) return '';
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  return (n / (1024 * 1024)).toFixed(1) + ' MB';
}

function _extractSiteCode(name) {
  const m = ((name || '').trim()).match(/^([A-Z]{2,}\d+)/);
  return m ? m[1] : null;
}

function _fuzzySim(a, b) {
  const words = s => new Set(((s || '').toLowerCase().match(/[a-z0-9]+/g)) || []);
  const aw = words(a), bw = words(b);
  if (!aw.size || !bw.size) return 0;

  let inter = 0;
  aw.forEach(w => { if (bw.has(w)) inter++; });
  const uni = aw.size + bw.size - inter;
  const jaccard = uni > 0 ? inter / uni : 0;

  const meanA = new Set([...aw].filter(w => w.length > 2));
  const meanB = new Set([...bw].filter(w => w.length > 2));
  let meanInter = 0;
  meanA.forEach(w => { if (meanB.has(w)) meanInter++; });
  const minMean = Math.min(meanA.size, meanB.size);
  const containment = (meanInter >= 2 && minMean > 0) ? meanInter / minMean : 0;

  return Math.max(jaccard, containment);
}

function _suggestSiteFor(itemName, sites, t) {
  if (!itemName || !sites || !sites.length) return null;

  if (t && t.kind === 'local' && t.path) {
    const parts = (t.path || '').split(/[\\/]/);
    const parentFolder = parts.length >= 2 ? parts[parts.length - 2] : '';
    const looksLikeAutoFolder = parentFolder && (parentFolder === itemName || parentFolder === (t.name || ''));
    if (parentFolder && !looksLikeAutoFolder) {
      const idx = sites.findIndex(s =>
        (s.localFolder || s.name || '') === parentFolder);
      if (idx >= 0) return { idx, score: 2.0 };
    }
  }

  const itemCode = _extractSiteCode(itemName);
  let bestIdx = -1, bestScore = 0;
  for (let i = 0; i < sites.length; i++) {
    const s = sites[i];
    if (!s || !s.name) continue;
    let score = _fuzzySim(itemName, s.name);
    const siteCode = _extractSiteCode(s.name);
    if (itemCode && siteCode && itemCode === siteCode) score += 1.0;
    if (score > bestScore) { bestScore = score; bestIdx = i; }
  }

  return bestScore >= 0.5 ? { idx: bestIdx, score: bestScore } : null;
}

async function assignOrphanToSite(projectId, siteId, projectName, siteName) {
  if (!projectId || !siteId) return;
  try {
    const r = await pyApi('assign_to_site', siteId, projectId);
    if (r && r.error) { toast('Assign failed: ' + r.error, 'error'); return; }
    toast(`Assigned "${projectName}" to ${siteName}`, 'success');
    refreshData();
  } catch (err) {
    toast('Assign failed: ' + (err.message || 'unknown'), 'error');
  }
}

async function startMoveToSite(projectId, projectName) {
  const key = 'c:' + projectId;
  const d = rowData[key];
  _moveToSiteTargets = [{
    kind: 'cloud', id: projectId, name: projectName,
    size: d && d.size, owner: d && d.owner,
    destValue: '', destNewName: '', destAuto: false,
  }];
  await _openMoveToSitePicker();
}

async function startMoveLocalToSite(path, name) {
  const key = 'l:' + path;
  const ct = 'ct-l:' + path;
  const d = rowData[key] || rowData[ct];
  _moveToSiteTargets = [{
    kind: 'local', path, name,
    size: d && d.size, owner: d && d.owner,
    destValue: '', destNewName: '', destAuto: false,
  }];
  await _openMoveToSitePicker();
}
async function bulkMoveToSite() {
  const targets = [...selected].map(k => rowData[k]).filter(d => d && (d.kind === 'cloud' || (d.kind === 'local' && !d.isDir)))
    .map(d => ({
      kind: d.kind, id: d.id, path: d.path, name: d.name,
      size: d.size, owner: d.owner,
      destValue: '', destNewName: '', destAuto: false,
    }));
  if (!targets.length) { toast('Select cloud projects or local .esx files first', 'info'); return; }
  _moveToSiteTargets = targets;
  await _openMoveToSitePicker();
}

async function _openMoveToSitePicker() {
  const n = _moveToSiteTargets.length;
  const isBulk = n > 1;

  document.getElementById('moveToSiteTitle').textContent =
    isBulk ? `Move ${n} items to Site`
           : `Move "${_moveToSiteTargets[0].name}${_moveToSiteTargets[0].isDir ? '' : '.esx'}" to Site`;
  document.getElementById('moveToSiteLabel').textContent =
    isBulk ? `Confirm each destination — auto-picked when we recognize the site, otherwise pick manually.`
           : `Confirm the file and destination — then click Move.`;

  document.getElementById('moveToSiteSource').innerHTML = '';
  const globalInput = _taGetInput('global');
  const globalList = _taGetList('global');
  if (globalInput) globalInput.value = '';
  if (globalList) { globalList.innerHTML = ''; globalList.hidden = true; }
  _setDestPreview(null);

  const intoLabel = document.querySelector('.mv-into-label');
  if (intoLabel) {
    intoLabel.textContent = isBulk ? 'Apply one site to all (optional)' : 'Into site';
  }
  if (globalInput) {
    globalInput.placeholder = isBulk
      ? 'Optional — type a site to stamp on every row above'
      : 'Type to search sites, or pick from the list…';
  }

  showModal('moveToSiteModal');
  try {
    const d = await pyApi('get_data', 'sites');
    const rows = [];
    (d.matched || []).forEach(p => rows.push({
      id: p.cloud.id, name: p.cloud.name, localFolder: p.local && p.local.name || '',
    }));
    (d.cloudOnly || []).forEach(s => rows.push({ id: s.id, name: s.name, localFolder: '' }));
    (d.localOnly || []).forEach(f => rows.push({ id: '', name: f.name, localFolder: f.name }));
    rows.sort((x,y) => (x.name||'').localeCompare(y.name||''));
    _moveToSiteSites = rows;

    _moveToSiteTargets.forEach(t => {
      const guess = _suggestSiteFor(t.name, rows, t);
      if (guess) { t.destValue = 'i:' + guess.idx; t.destAuto = true; }
    });

    _renderMoveSource();

    if (globalInput && !isBulk) {
      globalInput.value = _taDisplayText(_moveToSiteTargets[0]);
    }
    _refreshPathPreview();
  } catch (err) { toast('Could not load sites', 'error'); }
}

function _renderMoveSource() {
  const container = document.getElementById('moveToSiteSource');
  const isBulk = _moveToSiteTargets.length > 1;
  if (!isBulk) {
    const t = _moveToSiteTargets[0];
    container.innerHTML = _sourceItemHtml(t, 0, false);
    return;
  }
  container.innerHTML = _moveToSiteTargets.map((t, i) => _sourceItemHtml(t, i, true)).join('');
}
function _sourceItemHtml(t, i, includePicker) {
  const isCloud = t.kind === 'cloud';
  const icon = isCloud ? '☁' : '📁';
  const badge = isCloud ? 'Cloud' : 'Local';
  const badgeClass = isCloud ? 'cloud' : 'local';
  const meta = [t.size ? _fmtSize(t.size) : '', t.owner || ''].filter(Boolean).join(' · ');
  const picker = includePicker ? `
    <div class="mv-item-dest-row">
      <label>Into:</label>
      <div class="mv-ta mv-item-ta" data-idx="${i}">
        <input type="text" class="mv-ta-input" data-idx="${i}"
               value="${a(_taDisplayText(t))}"
               placeholder="Type to search sites…"
               autocomplete="off"
               onfocus="_taShow(this)" oninput="_taFilter(this)"
               onblur="_taBlur(this)" onkeydown="_taKey(event, this)">
        <button type="button" class="mv-ta-clear" data-idx="${i}" onclick="_taClear(${i})" title="Clear" tabindex="-1">&times;</button>
        <div class="mv-ta-list" hidden></div>
      </div>
      ${t.destAuto && t.destValue.startsWith('i:') ? '<span class="mv-item-auto" title="Auto-matched by site code or filename similarity">auto</span>' : ''}
    </div>` : '';
  return `
    <div class="mv-source-item${includePicker ? ' bulk' : ''}" data-idx="${i}">
      <span class="mv-source-icon">${icon}</span>
      <span class="mv-source-mid">
        <div class="mv-source-name">${e(t.name)}${t.isDir ? '' : '.esx'}</div>
        ${meta ? `<div class="mv-source-meta">${e(meta)}</div>` : ''}
        ${picker}
      </span>
      <span class="mv-source-badge ${badgeClass}">${badge}</span>
    </div>`;
}

const _TA_MAX_RESULTS = 100;
let _taHighlight = -1;

function _taDisplayText(t) {
  if (!t || !t.destValue) return '';
  if (t.destValue === '__new__') return '+ new: ' + (t.destNewName || '');
  const i = parseInt(t.destValue.slice(2), 10);
  return _moveToSiteSites[i] ? _moveToSiteSites[i].name : '';
}
function _taGetContainer(idx) {
  return document.querySelector(`.mv-ta[data-idx="${idx}"]`);
}
function _taGetList(idx) {
  const c = _taGetContainer(idx);
  return c ? c.querySelector('.mv-ta-list') : null;
}
function _taGetInput(idx) {
  const c = _taGetContainer(idx);
  return c ? c.querySelector('.mv-ta-input') : null;
}
function _taTargetFor(idx) {

  if (idx === 'global') return _moveToSiteTargets.length === 1 ? _moveToSiteTargets[0] : null;
  return _moveToSiteTargets[parseInt(idx, 10)] || null;
}

function _taRenderList(idx, query) {
  const q = (query || '').toLowerCase().trim();
  const scored = _moveToSiteSites.map((s, i) => {
    const nameLower = (s.name || '').toLowerCase();
    let score = 0;
    if (!q) score = 1;
    else if (nameLower.includes(q)) score = 2;
    else score = _fuzzySim(q, s.name);
    return { s, i, score };
  }).filter(m => m.score >= (q ? 0.3 : 0.5))
    .sort((a, b) => (b.score - a.score) || a.s.name.localeCompare(b.s.name))
    .slice(0, _TA_MAX_RESULTS);

  if (!q) {
    scored.length = 0;
    _moveToSiteSites.forEach((s, i) => scored.push({ s, i, score: 1 }));
    scored.sort((a, b) => a.s.name.localeCompare(b.s.name));
  }

  const target = _taTargetFor(idx);
  const currentValue = target ? target.destValue : '';

  const rows = [];
  scored.forEach(({ s, i }) => {
    const val = 'i:' + i;
    const tag = !s.id ? ' <span class="mv-ta-tag">local only</span>'
              : (!s.localFolder ? ' <span class="mv-ta-tag">cloud only</span>' : '');
    const active = val === currentValue ? ' active' : '';
    rows.push(`<div class="mv-ta-item${active}" data-val="${val}"
                    onmousedown="event.preventDefault();_taPick('${idx}','${val}')">${e(s.name)}${tag}</div>`);
  });

  const exact = scored.some(m => (m.s.name || '').toLowerCase() === q);
  if (q && !exact) {
    const active = currentValue === '__new__' ? ' active' : '';
    rows.push(`<div class="mv-ta-item mv-ta-newop${active}" data-val="__new__" data-query="${a(query)}"
                    onmousedown="event.preventDefault();_taPickNew(this, '${j(String(idx))}')">+ Create new site: "${e(query)}"</div>`);
  }
  if (!rows.length) {
    return '<div class="mv-ta-empty">No matching sites. Keep typing to create a new one.</div>';
  }
  return rows.join('');
}

function _taShow(input) {
  const idx = input.dataset.idx;
  const list = _taGetList(idx);
  if (!list) return;
  list.innerHTML = _taRenderList(idx, input.value);
  list.hidden = false;
  _taHighlight = -1;
  input.select();
}
function _taBlur(input) {

  const idx = input.dataset.idx;
  setTimeout(() => {
    const list = _taGetList(idx);
    if (list) list.hidden = true;
    const target = _taTargetFor(idx);
    if (target) input.value = _taDisplayText(target);
  }, 150);
}
function _taFilter(input) {
  const idx = input.dataset.idx;
  const list = _taGetList(idx);
  if (!list) return;
  list.innerHTML = _taRenderList(idx, input.value);
  list.hidden = false;
  _taHighlight = -1;
}
function _taKey(ev, input) {
  const idx = input.dataset.idx;
  const list = _taGetList(idx);
  if (!list) return;
  const items = list.querySelectorAll('.mv-ta-item');
  if (ev.key === 'ArrowDown') {
    ev.preventDefault();
    _taHighlight = Math.min(items.length - 1, _taHighlight + 1);
    _taApplyHighlight(items);
  } else if (ev.key === 'ArrowUp') {
    ev.preventDefault();
    _taHighlight = Math.max(0, _taHighlight - 1);
    _taApplyHighlight(items);
  } else if (ev.key === 'Enter') {
    ev.preventDefault();
    const cur = items[_taHighlight] || items[0];
    if (!cur) return;
    const val = cur.dataset.val;
    if (val === '__new__') _taPickNew(idx, input.value);
    else _taPick(idx, val);
  } else if (ev.key === 'Escape') {
    input.blur();
  }
}
function _taApplyHighlight(items) {
  items.forEach((it, i) => it.classList.toggle('hl', i === _taHighlight));
  const hl = items[_taHighlight];
  if (hl) hl.scrollIntoView({ block: 'nearest' });
}

function _taPick(idx, val) {
  if (idx === 'global') {
    _moveToSiteTargets.forEach(t => { t.destValue = val; t.destAuto = false; });
    if (_moveToSiteTargets.length > 1) _renderMoveSource();
  } else {
    const t = _moveToSiteTargets[parseInt(idx, 10)];
    if (!t) return;
    t.destValue = val;
    t.destAuto = false;
  }
  const list = _taGetList(idx);
  if (list) list.hidden = true;
  const input = _taGetInput(idx);
  const target = _taTargetFor(idx) || _moveToSiteTargets[0];
  if (input && target) input.value = _taDisplayText(target);

  if (idx !== 'global') {
    const row = document.querySelector(`.mv-source-item[data-idx="${idx}"] .mv-item-auto`);
    if (row) row.remove();
  }
  _refreshPathPreview();
}
function _taPickNew(idxOrEl, maybeIdx) {
  let idx, query;
  if (idxOrEl && typeof idxOrEl === 'object' && idxOrEl.dataset) {
    idx = maybeIdx;
    query = idxOrEl.dataset.query || '';
  } else {
    idx = idxOrEl;
    query = maybeIdx;
  }
  const name = (query || '').trim();
  if (!name) return;
  if (idx === 'global') {
    _moveToSiteTargets.forEach(t => { t.destValue = '__new__'; t.destNewName = name; t.destAuto = false; });
    if (_moveToSiteTargets.length > 1) _renderMoveSource();
  } else {
    const t = _moveToSiteTargets[parseInt(idx, 10)];
    if (!t) return;
    t.destValue = '__new__';
    t.destNewName = name;
    t.destAuto = false;
  }
  const list = _taGetList(idx);
  if (list) list.hidden = true;
  const input = _taGetInput(idx);
  if (input) input.value = '+ new: ' + name;
  if (idx !== 'global') {
    const row = document.querySelector(`.mv-source-item[data-idx="${idx}"] .mv-item-auto`);
    if (row) row.remove();
  }
  _refreshPathPreview();
}
function _taClear(idx) {
  if (idx === 'global') {

    if (_moveToSiteTargets.length === 1) {
      _moveToSiteTargets[0].destValue = '';
      _moveToSiteTargets[0].destNewName = '';
      _moveToSiteTargets[0].destAuto = false;
    }
  } else {
    const t = _moveToSiteTargets[parseInt(idx, 10)];
    if (!t) return;
    t.destValue = '';
    t.destNewName = '';
    t.destAuto = false;
  }
  const input = _taGetInput(idx);
  if (input) input.value = '';
  _refreshPathPreview();
}

function _outputDirPrefix() { return _outputDir || '<local folder>'; }
function _setDestPreview(html, isEmpty) {
  const el = document.getElementById('moveToSitePreview');
  el.className = 'mv-dest-preview' + (isEmpty ? ' empty' : '');
  if (isEmpty) el.textContent = html;
  else el.innerHTML = html;
}

function _resolveDest(t) {
  if (t.destValue === '__new__') {
    const nn = (t.destNewName || '').trim();
    if (!nn) return { ready: false };
    return { ready: true, folder: nn, siteName: nn + ' (new)', siteId: null };
  }
  if (t.destValue && t.destValue.startsWith('i:')) {
    const s = _moveToSiteSites[parseInt(t.destValue.slice(2), 10)];
    if (!s) return { ready: false };
    return {
      ready: true,
      folder: s.localFolder || s.name,
      siteName: s.name,
      siteId: s.id || null,
    };
  }
  return { ready: false };
}

function _refreshPathPreview() {
  const n = _moveToSiteTargets.length;
  const sep = _outputDirPrefix().includes('\\') ? '\\' : '/';
  const prefix = _outputDirPrefix();
  const resolved = _moveToSiteTargets.map(_resolveDest);
  const readyCount = resolved.filter(r => r.ready).length;
  const btn = document.querySelector('#moveToSiteModal .btn-blue');
  if (btn) btn.disabled = readyCount === 0;

  if (n === 1) {
    const r = resolved[0];
    if (!r.ready) {
      _setDestPreview('Pick a destination site to see the final path.', true);
      return;
    }
    const t = _moveToSiteTargets[0];
    const fname = t.name + (t.isDir ? '' : '.esx');
    _setDestPreview(`<span class="arrow">&#10145;</span>${e(prefix + sep + r.folder + sep + fname)}`);
    return;
  }

  const uniqueFolders = new Set(resolved.filter(r => r.ready).map(r => r.folder));
  const missing = n - readyCount;
  if (readyCount === 0) {
    _setDestPreview(`Pick a destination for each of the ${n} items to see the final paths.`, true);
    return;
  }
  const missTag = missing ? ` <span class="mv-miss">· ${missing} still unassigned</span>` : '';
  if (uniqueFolders.size === 1) {
    const folder = [...uniqueFolders][0];
    _setDestPreview(`<span class="arrow">&#10145;</span>${e(prefix + sep + folder + sep)} <span class="mv-dest-count">— ${readyCount} file${readyCount === 1 ? '' : 's'}</span>${missTag}`);
  } else {
    _setDestPreview(`<span class="arrow">&#10145;</span>${readyCount} file${readyCount === 1 ? '' : 's'} to <b>${uniqueFolders.size}</b> different sites${missTag}`);
  }
}

async function confirmMoveToSite() {
  const n = _moveToSiteTargets.length;
  const plans = _moveToSiteTargets.map(t => ({ t, dest: _resolveDest(t) }));
  const notReady = plans.filter(p => !p.dest.ready);
  if (notReady.length) {
    toast(notReady.length === n
      ? 'Pick a destination site first'
      : `Still ${notReady.length} unassigned — pick a destination for every row`,
      'error');
    return;
  }
  closeModal('moveToSiteModal');
  clearSelection();

  const newSiteByName = new Map();
  let ok = 0, fail = 0, firstErr = '';
  const dests = new Set();
  for (const { t, dest } of plans) {
    let siteId = dest.siteId;
    let folder = dest.folder;

    if (t.kind === 'cloud' && !siteId && t.destValue === '__new__') {
      const key = (t.destNewName || '').trim();
      if (newSiteByName.has(key)) {
        siteId = newSiteByName.get(key).id;
        folder = newSiteByName.get(key).folder;
      } else {
        try {
          const r = await pyApi('create_site', key);
          if (r && r.error) { fail++; firstErr = firstErr || `couldn't create "${key}": ${r.error}`; continue; }
          siteId = r.id || r.siteId;
          folder = key;
          newSiteByName.set(key, { id: siteId, folder });
        } catch (err) { fail++; firstErr = firstErr || (err.message || 'failed'); continue; }
      }
    }
    try {
      let r;
      if (t.kind === 'cloud') {
        if (!siteId) { fail++; firstErr = firstErr || 'destination site has no cloud counterpart'; continue; }
        r = await pyApi('assign_to_site', siteId, t.id);
      } else {
        r = await pyApi('move_local_to_site', t.path, folder);
      }
      if (r && r.error) { fail++; firstErr = firstErr || r.error; }
      else { ok++; dests.add(folder); }
    } catch (err) { fail++; firstErr = firstErr || (err.message || 'failed'); }
  }
  if (fail === 0 && ok > 0) {
    toast(dests.size === 1
      ? `Moved ${ok} to ${[...dests][0]}`
      : `Moved ${ok} to ${dests.size} sites`,
      'success');
  } else if (ok === 0) {
    toast(`Move failed: ${firstErr}`, 'error');
  } else {
    toast(`Moved ${ok} · ${fail} failed (${firstErr})`, 'error');
  }
  _scheduleOpRefresh();
}


function _wireIconTipDelegation() {
  const migrate = (target) => {
    const btn = target.closest ? target.closest('.lr-cell .cell-actions [title], .lr-gut [title]') : null;
    if (!btn || btn.hasAttribute('data-tip')) return;
    const tip = btn.getAttribute('title');
    if (!tip) return;
    btn.setAttribute('data-tip', tip);
    if (!btn.hasAttribute('aria-label')) btn.setAttribute('aria-label', tip);
    btn.removeAttribute('title');
  };
  document.addEventListener('mouseover', (ev) => migrate(ev.target), true);
  document.addEventListener('focusin', (ev) => migrate(ev.target), true);
}
_wireIconTipDelegation();

startAuth();
