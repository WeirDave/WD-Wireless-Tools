

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
let _searching = false;
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
  replace_cloud_project: ['replace_cloud_project', ['path', 'cloudId', 'opId']],
  compare_with_cloud: ['compare_with_cloud', ['path', 'cloudId', 'opId']],
  set_internal_project_name: ['set_internal_project_name', ['path', 'name', 'opId']],
  list_shares: ['list_shares', ['projectId']],
  add_share: ['add_share', ['projectId', 'email', 'role']],
  add_shares: ['add_shares', ['projectId', 'emails', 'role']],
  recent_recipients: ['recent_recipients', []],
  forget_recipient: ['forget_recipient', ['email']],
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

    /* His action, so it lands on screen. Quiet - no "Loading…" flash over a
       list he is reading - but not queued behind the bar that exists for polls
       he did not ask for. */
    if (typeof refreshData === 'function') refreshData(true, { background: false });
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
  if (op.status === 'queued') {
    btns.push(`<button class="op-btn" onclick="opCancelQueued('${op.id}')" title="Take this out of the queue before it runs">Remove</button>`);
  }
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
  /* A waiting item says where it is in the line. "Waiting..." on four cards
     at once tells him nothing about which is next; "2 ahead" does, and it
     renumbers itself when something ahead is removed. */
  const ahead = op.status === 'queued' ? _opQueuePosition(op.id) - 1 : 0;
  const waitText = ahead > 0
    ? `Waiting — ${ahead} ahead`
    : (op.status === 'queued' ? 'Waiting — next' : op.stage);
  const stageLine = op.status === 'failed' && op.error
    ? `<div class="op-stage err">${e(op.error)}</div>`
    : (waitText ? `<div class="op-stage">${e(waitText)}</div>` : '');
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
  /* Dismissing something that has not started yet has to take it out of the
     queue, not merely off the screen - otherwise its turn still arrives and it
     runs after he has told it not to. */
  const op = _ops.get(id);
  const pendingIdx = _opPending.indexOf(id);
  if (pendingIdx >= 0) _opPending.splice(pendingIdx, 1);
  if (op && op.status === 'queued' && op._release) {
    op.status = 'cancelled';
    const release = op._release;
    op._release = null;
    release();
  }
  _ops.delete(id);
  const idx = _opOrder.indexOf(id);
  if (idx >= 0) _opOrder.splice(idx, 1);
  _deckRender();
}

/* Cancelling a queued item is the same as dismissing it: it has not started,
   so there is nothing to interrupt and nothing to undo. */
function opCancelQueued(id) { _opRemove(id); }

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

/* One at a time, in the order the clicks arrived.

   `opEnqueue` used to start work the instant it was called, so clicking four
   renames in four seconds sent four concurrent writes to Ekahau Cloud and they
   landed in whatever order the network chose. The deck said "4 running", which
   was true and was not what anybody wanted.

   Concurrency is 1 on purpose. Every operation in this deck writes to a real
   project - rename, replace, delete, upload - and overlapping two of those is
   not throughput, it is a race. Ordered and boring is the requirement.

   Raising this above 1 would also break the ordering guarantee callers already
   rely on: bulk sync enqueues a download and then the rename that follows it,
   and those must not overlap. */
const OP_MAX_CONCURRENT = 1;
const _opPending = [];
let _opActive = 0;

function _opPump() {
  while (_opActive < OP_MAX_CONCURRENT && _opPending.length) {
    const id = _opPending.shift();
    const op = _ops.get(id);
    // Removed, or cancelled, while it sat in the queue. Skip it and take the
    // next: a dismissed item must not come back to life when its turn arrives.
    if (!op || op.status !== 'queued' || !op._release) continue;
    _opActive++;
    /* Flip to running here rather than letting the op do it when its
       continuation is scheduled. Otherwise there is a microtask in which the
       thing that has just been handed the slot still renders as "Waiting -
       next", which is a state that is never true. */
    op.status = 'running';
    op.startedAt = Date.now();
    op.stage = 'Starting…';
    const release = op._release;
    op._release = null;
    release();
    return;
  }
}

/* How many are ahead of this one, for the card to show. Counted off the live
   queue rather than stored, so removing something renumbers the rest. */
function _opQueuePosition(id) {
  const i = _opPending.indexOf(id);
  return i < 0 ? 0 : i + 1;
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
    stage: 'Waiting…',
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
  _opPending.push(id);

  // The gate this op waits behind. `_opPump` releases it when a slot frees.
  let release;
  const myTurn = new Promise(res => { release = res; });
  op._release = release;

  _deckRender();
  _ensureDeckTick();

  const promise = (async () => {
    await myTurn;
    /* Dismissed while it sat in the queue. Settle rather than run, so a caller
       awaiting this op is not left hanging on work that will never happen. */
    if (op.status !== 'running') {
      return { cancelled: true };
    }
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
    } finally {
      /* Always, including the throw above. One failed item must not strand the
         rest of the queue - that is the same mistake as the all-or-nothing
         pass that threw away finished work because a later step refused. */
      _opActive--;
      _opPump();
    }
  })();
  _opPump();
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
async function goToDashboard(email) {
  document.getElementById('loginScreen').style.display = 'none';
  document.getElementById('setupScreen').hidden = true;
  document.getElementById('appScreen').style.display = 'flex';
  document.getElementById('userEmail').textContent = email || 'Connected';
  // Before the first listing is drawn, not after, or the page shows
  // everything and then hides half of it a moment later.
  await loadDefaultOwnerFilter();
  // Same reason: the merge rule and refresh interval have to be the saved ones
  // before anything can act on them.
  await loadCloudPrefs();
  syncOwnerToggle();
  _syncTabUI(currentTab);
  refreshData();
  if (liveWanted()) startLive();
}

// Backed by settings.json, loaded once at login by loadCloudPrefs().
function liveMs() { return _liveMs; }
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
  /* Live means "re-pull from Ekahau". The Backup Folder tab has nothing to
     re-pull: it walks the project folder on disk, which only changes when he
     does something here - and each of those actions refreshes the list
     itself. Polling it would be a recursive scan of every project folder
     every nine seconds, to redraw the same rows. */
  if (currentTab === 'backups') return true;
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
/* The tabs that are not the cloud/local file lists. Both of them hide the
   owner toggle, the site controls and the cloud-shaped filters, so asking the
   question once is what keeps a third tab from being added to four of the six
   places that care and missed by the other two. */
function isLocalOnlyTab(kind) { return kind === 'duplicates' || kind === 'backups'; }

function _syncTabUI(kind) {
  document.getElementById('tabFilesGroup').classList.toggle('active', !isLocalOnlyTab(kind));
  document.getElementById('viewTreeBtn').classList.toggle('active', kind === 'sites');
  document.getElementById('viewFlatBtn').classList.toggle('active', kind === 'projects');
  document.getElementById('tabDuplicates').classList.toggle('active', kind === 'duplicates');
  const bakTab = document.getElementById('tabBackups');
  if (bakTab) bakTab.classList.toggle('active', kind === 'backups');
  document.getElementById('addNewBtn').style.display = kind === 'sites' ? '' : 'none';
  document.getElementById('expandAllBtn').hidden = kind !== 'sites';
  document.getElementById('collapseAllBtn').hidden = kind !== 'sites';
  const ownerEl = document.getElementById('ownerToggle');
  if (ownerEl) ownerEl.hidden = isLocalOnlyTab(kind);
  renderOwnerFilterNotice();

  /* Nothing on the Backup Folder tab talks to Ekahau, so the controls that do
     are taken away rather than left to act on a list he is not looking at.
     `Sync everything` is the one that matters: it works from the ledger data,
     which is still in memory, so pressing it here would start syncing cloud
     projects from a screen showing local file copies. Live goes too - it is
     paused on this tab, and a countdown ticking next to a list it is not
     re-reading says something untrue. */
  ['syncAllBtn', 'liveBtn', 'matchHelpChip', 'selectMenu'].forEach(id => {
    const node = document.getElementById(id);
    if (node) node.hidden = (kind === 'backups');
  });

  /* And the A-Z rail, which indexes site names. Neither of these two tabs
     draws through `renderRows` on the way in - each goes straight to its own
     renderer - so the rail the ledger put up stayed up, twenty-six letters
     over a list that none of them selects. */
  const jump = document.getElementById('jumpNav');
  if (jump && isLocalOnlyTab(kind)) jump.style.display = 'none';

  const dupTbBtn = document.getElementById('dupDeleteAllToolbarBtn');
  if (dupTbBtn && kind !== 'duplicates') dupTbBtn.hidden = true;
  _markActiveFilter();
}
function switchTab(kind) {
  if (kind === currentTab) return;
  currentTab = kind;
  if (kind === 'sites' || kind === 'projects') {
    try { localStorage.setItem('wd-files-kind', kind); } catch (e) {}
  }
  /* A filter chosen on the tab you are leaving does not mean anything on the
     one you are arriving at, and `updateDashboard` hides the chip rather than
     clearing it - so it would go on filtering invisibly. */
  if (activeFilter.indexOf('bak-') === 0 && kind !== 'backups') activeFilter = 'all';
  if (activeFilter.indexOf('dup-') === 0 && kind !== 'duplicates') activeFilter = 'all';
  _syncTabUI(kind);
  refreshData();
}

function expandAllSites() {
  collapsed.clear();
  _treeClosedFor = null;
  renderRows();
}

/* Which data set the sites were last closed for.

   The list opens site-first, so every site starts closed - but only once per
   data set. Closing them again on each background refresh would shut whatever
   he had just opened, every few seconds, while he was reading it. */
let _treeClosedFor = null;

function closeSitesOnFirstSight() {
  if (!data) return;
  const stamp = currentTab + ':' + ((data.matched || []).length + ':'
    + (data.cloudOnly || []).length + ':' + (data.localOnly || []).length);
  if (_treeClosedFor === stamp) return;
  _treeClosedFor = stamp;

  /* A site that wants something opens; a site that is finished stays shut.

     Closing all of them made the page open on a list of names rather than on
     his work - "at least before I understood what was going on even if it was
     ugly" - and the digest line does not make up for it: "2 need a decision"
     says a site is worth opening, not what is inside it.

     Opening all of them is the wall the site-first change was for. So the
     split is by whether there is anything to do: the first thing on screen is
     the work that wants him, and the sites with nothing to say keep quiet.
     Expand all and Collapse all still override this. */
  const wantsHim = (children) => {
    const d = siteDigest(children);
    return !!d && (d.attention > 0 || d.unpaired > 0);
  };
  const shut = (key, children) => {
    if (!wantsHim(children)) collapsed.add(key);
  };
  (data.matched || []).forEach(p => shut('site:' + p.cloud.id,
    (p.cloud && p.cloud.children) || (p.local && p.local.children)));
  (data.cloudOnly || []).forEach(s => shut('site:' + s.id, s.children));
  (data.localOnly || []).forEach(f => shut('folder:' + f.path, f.children));
}
function collapseAllSites() {
  if (!data) return;
  _treeClosedFor = null;
  (data.matched || []).forEach(p => collapsed.add('site:' + p.cloud.id));
  (data.cloudOnly || []).forEach(s => collapsed.add('site:' + s.id));
  (data.localOnly || []).forEach(f => collapsed.add('folder:' + f.path));
  renderRows();
}

/* `silent` means "do not flash Loading…". It has never meant "this is a
   background poll", and since v2.119.0 the difference matters: a background
   poll queues behind the changed-since-drawn bar instead of redrawing.

   An action's own follow-up refresh is not a poll - he pressed the button, and
   the result of pressing it should not need a second click to appear. So the
   two are separate now: `quiet` suppresses the flicker, `background` decides
   whether he is asked. */
function refreshData(silent, opts) {
  const background = opts ? !!opts.background : !!silent;
  if (!silent) {
    clearSelection();
    document.getElementById('rowsContainer').innerHTML = '<div class="empty-msg">Loading…</div>';
  }
  const tab = currentTab;
  if (tab === 'backups') {
    /* Its own call, and not through `pyApi`: nothing on this tab talks to
       Ekahau, so the list still draws when the cloud session has dropped -
       which is exactly when someone comes looking for the copy of a file. */
    bakApi('list')
      .then(d => onBackups(tab, d))
      .catch(err => { if (!silent) toast('Load failed: ' + err.message, 'error'); });
  } else if (tab === 'duplicates') {
    pyApi('get_duplicates')
      .then(d => onDuplicates(tab, JSON.stringify(d)))
      .catch(err => { if (!silent) toast('Load failed: ' + err.message, 'error'); });
  } else {
    pyApi('get_data', tab)
      .then(d => onData(tab, JSON.stringify(d), { background }))
      .catch(err => { if (!silent) toast('Load failed: ' + err.message, 'error'); });

    refreshDupIndex();
  }
}

/* What the last background poll found and has not been allowed to apply. */
let _pendingData = null;

/* Everything the list actually draws from, as one comparable string.

   The whole payload is not usable for this: `get_data` returns fresh
   timestamps and re-derived ids on every call, so comparing it raw reports a
   change every nine seconds and the bar never goes away. What matters is what
   he would see differently. */
function _viewFingerprint(d) {
  if (!d) return '';
  const sig = [];
  const pair = (p) => (p.cloud && p.cloud.id) + '|' + (p.local && p.local.path)
    + '|' + (p.namesDiffer ? 'n' : '') + '|' + (p.staleness || '')
    + '|' + (p.matchType || '');
  const kids = (c) => {
    if (!c) return;
    (c.matched || []).forEach(p => sig.push('m' + pair(p)));
    (c.cloudOnly || []).forEach(x => sig.push('c' + x.id));
    (c.localOnly || []).forEach(x => sig.push('l' + x.path));
    (c.heldBack || []).forEach(h => sig.push('h' + (h.cloud && h.cloud.id)
      + '|' + (h.local && h.local.path)));
  };
  (d.matched || []).forEach(p => { sig.push('M' + pair(p));
    kids((p.cloud && p.cloud.children) || (p.local && p.local.children)); });
  (d.cloudOnly || []).forEach(x => { sig.push('C' + x.id); kids(x.children); });
  (d.localOnly || []).forEach(x => { sig.push('L' + x.path); kids(x.children); });
  kids(d.orphans);
  (d.heldBack || []).forEach(h => sig.push('H' + (h.cloud && h.cloud.id)
    + '|' + (h.local && h.local.path)));
  return sig.join(',');
}

/* Apply what the last poll found, because he asked for it. */
function applyPendingData() {
  if (!_pendingData) return;
  const payload = _pendingData;
  _pendingData = null;
  _showRefreshBar(false);
  onData(currentTab, payload, { force: true });
}

function _showRefreshBar(on, what) {
  const el = document.getElementById('staleDataBar');
  if (!el) return;
  el.hidden = !on;
  if (on) {
    const msg = el.querySelector('.sdb-text');
    if (msg) msg.textContent = what || 'Ekahau Cloud has changed since this list was drawn.';
  }
}

function onData(kind, jsonStr, opts) {
  if (kind !== currentTab) return;
  try {
    data = JSON.parse(jsonStr);
  } catch (err) { toast('Bad data payload', 'error'); return; }
  if (data.error) {
    document.getElementById('rowsContainer').innerHTML = '<div class="empty-msg">' + e(data.error) + '</div>';
    toast(data.error, 'error'); return;
  }
  /* A poll he did not ask for does not rewrite the page.

     It arrives, it is compared against what is drawn, and if it differs it
     waits behind a bar he can press. "I was reading through them and then it
     automatically just had those files go away" is what the other behaviour
     looks like from his side - and the held-back candidates are exactly the
     thing the matcher can recompute differently between two polls. */
  if (opts && opts.background && !(opts && opts.force)) {
    const now = _viewFingerprint(data);
    if (now === _drawnFingerprint) { _pendingData = null; _showRefreshBar(false); return; }
    _pendingData = jsonStr;
    data = _drawnData;          // keep drawing what he is looking at
    _showRefreshBar(true);
    return;
  }

  _drawnData = data;
  _drawnFingerprint = _viewFingerprint(data);
  _pendingData = null;
  _showRefreshBar(false);

  /* Each step on its own, so one of them cannot cost him the others.

     v2.113.0 put a stale element id inside `updateDashboard`, which sits
     between the data arriving and the list being drawn - so a counter he
     barely looks at took the whole tool down, and the page sat on "Loading"
     with a header above it. Four releases. The list is the product; nothing
     decorative above it gets to veto drawing it. */
  _step('indexing the rows', indexRowData);
  _step('the owner filter', reconcileOwnerFilterWithData);
  _step('opening the sites that need you', closeSitesOnFirstSight);
  _step('the counters', updateDashboard);
  _step('the list', renderRows);
}

/* Run one step of the load. A step that throws is reported once and skipped;
   everything after it still runs.

   It is deliberately noisy in the console and quiet on screen: a fault that
   nothing reports is how a broken counter survived four releases, and a fault
   that shouts at him mid-job is how he stops reading them. */
let _stepFailures = new Set();
function _step(what, fn) {
  try {
    fn();
    _stepFailures.delete(what);
  } catch (err) {
    console.error('[wd] Cloud Manager could not finish ' + what + ':', err);
    if (!_stepFailures.has(what)) {
      _stepFailures.add(what);
      try {
        toast('Part of the page (' + what + ') could not be drawn — the rest '
              + 'still works. Details are in the browser console.', 'error');
      } catch (e) { /* a toast is not worth a second failure */ }
    }
  }
}

//: What is on screen, so a poll can tell whether it would change anything.
let _drawnData = null;
let _drawnFingerprint = '';

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
      differenceKind: p.differenceKind || null,
      /* Which side is newer, and both dates, travel with the row you can
         select. They used to exist only on the render row, so Sync - which
         reads rowData - could not see that a pair needed content moved and
         silently did nothing but rename. */
      staleness: p.staleness || null,
      cloudMtime: Number(p.cloud.mtime) || 0,
      localMtime: Number(p.local.mtime) || 0,

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
      // Carried so bulk Sync can create the missing local folder AND move
      // every cloud project already sitting under this site in one shot.
      children: s.children,
    };
  });
  (data.localOnly || []).forEach(f => {
    rowData['l:' + f.path] = {
      kind: 'local', path: f.path, name: f.name, isDir: f.isDir,
      // Same idea in the other direction: create the missing cloud site
      // and upload every local .esx already sitting in this folder.
      children: f.children,
    };
  });

  const indexChildren = (children, parentSite, parentSiteId) => {
    if (!children) return;
    (children.matched || []).forEach(p => {

      rowData['ct:' + p.cloud.id] = {
        kind: 'pair', cloudId: p.cloud.id, cloudName: p.cloud.name,
        localName: p.local.name, localPath: p.local.path,
        mismatch: p.namesDiffer,
        matchType: p.matchType,
        staleness: p.staleness || null,
        cloudMtime: Number(p.cloud.mtime) || 0,
        localMtime: Number(p.local.mtime) || 0,
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
        // Lets a plain (non-site-creating) upload of this file auto-assign
        // to the site whose folder it's already sitting in, instead of
        // landing as a fresh unassigned cloud project every time.
        parentSiteId: parentSiteId || null,
      };
    });
  };
  (data.matched || []).forEach(p => indexChildren(p.cloud && p.cloud.children, p.cloud.name, p.cloud.id));
  (data.cloudOnly || []).forEach(s => indexChildren(s.children, s.name, s.id));
  (data.localOnly || []).forEach(f => indexChildren(f.children, f.name, null));
}

/* Which filter looks like the one in force.

   This was `document.querySelectorAll('.dash-card')`, written twice - once
   here and once in the tab switcher - and the header redesign removed the
   cards. So from v2.113.0 nothing on the page showed which filter was on: he
   could narrow a hundred rows down to seven and have no way to see that he
   had, which is the list telling him something untrue about his account.

   Addressing the control by `data-filter` rather than by the class of the box
   round it means the markup can change shape without this going quiet again -
   and there is one copy of it now, because two copies is how the first attempt
   at this fix went into the wrong one. */
function _markActiveFilter() {
  document.querySelectorAll('[data-filter]').forEach(el => {
    const on = el.dataset.filter === activeFilter;
    el.classList.toggle('active', on);
    if (el.tagName === 'BUTTON') el.setAttribute('aria-pressed', on ? 'true' : 'false');
  });

  /* There used to be a second half here that wrote the chosen filter onto the
     closed "More filters" button, because a filter inside a dropdown is
     invisible the moment it shuts. Every filter is a chip with its count on
     it now, so the highlight is the whole answer and there is nothing left to
     annotate. Code for a control that no longer exists is how `.dash-card`
     went on matching nothing for four releases. */
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


/* Is this pair out of sync? One answer, for the chip and for the list.

   "3 out of sync" over a list of six rows, every one of them wanting an
   action. The chip and the filter were asking different questions:

   * the chip skipped any pair whose comparison came back `!designDiffers`;
   * the filter kept every pair with a `staleness` flag, compared or not.

   Three of his six had been compared and found to hold the same design under
   different names - so they vanished from the number and stayed in the list,
   and the header contradicted the thing it was sitting on top of. This is the
   same shape as "0 unpaired" over two rows, and the same rule applies: a
   count is the length of its own list.

   Which of the two was right? Neither. `designDiffers` is the wrong question,
   because "the design matches, the name inside the file does not" is not
   settled - it is the pair that has a **`Set the name inside the file to
   match`** button on it, and dropping those from the count hid the work rather
   than the noise. `identical` is the settled one: contents, metadata and name
   all agree, and the row itself says "Nothing to do".

   That still answers the complaint this test was written for - renaming a
   fleet of cloud projects used to read 29 out of sync over pure date drift.
   Once each rename is applied the pair is `identical` and drops out. Until
   then it is 29 files wanting one click each, which is a true number. */
function comparisonIsSettled(cmp) {
  /* The one definition of "there is nothing left to do here", shared by the
     chip, the filter, the site digest and the row's own actions.

     It has now been wrong in both directions in two days.

     `!designDiffers` was too generous: it dropped the pairs whose design
     matches but whose *name inside the file* is still the old one, and those
     are precisely the rows carrying a `Set the name inside the file to match`
     button. Three of his six vanished from the count and stayed in the list.

     `identical` was too strict, which is the other end of the same mistake:
     "No design change - only bookkeeping differs (dates, revision history)"
     is not identical, and it is also not a decision - there is no button on
     that row, nothing to click, nothing to choose. Making it count meant a
     site he had just finished comparing still read "1 of 3 files - 1 needs a
     decision", which is the tool asking for something it cannot name.

     Settled is: the design matches, and the name does not need writing. That
     is exactly the test `stalenessBadgeHtml` already used to decide whether to
     offer any action at all, so the badge, the count and the row now agree by
     construction rather than by three people remembering to. */
  return !!(cmp && !cmp.designDiffers && cmp.nameState !== 'internal_only');
}

function isOutOfSync(row) {
  if (!row || !row.staleness) return false;
  const cmp = (row.cloud && row.local)
    ? _compareResults.get(_compareKey(row.cloud.id, row.local.path)) : null;
  return !comparisonIsSettled(cmp);
}


/* Is this cloud project filed under no site in Ekahau?

   "I clicked on not assigned because it says two not assigned, and the whole
   entire list is still just there."

   The filter read `!row.cloud.hasSite`, and `hasSite` is a **project** field:
   `build_sites_data` never puts one on a site, so every site row evaluated
   `!undefined` - true - and the filter selected all ninety-nine of them. The
   chip counted the two projects the backend had actually set aside, so the
   number and the list were answers to different questions again.

   Absence is not evidence here, which is why this tests for the fact rather
   than for the missing field: `unassigned` is set by the backend on a project
   it moved into a site because the local .esx lives there, and `hasSite` is an
   explicit `false` on one it could not file at all. A project that simply has
   neither field - every ordinary child of a site - is assigned. */
function _isUnassignedProject(cloudObj) {
  return !!(cloudObj && (cloudObj.unassigned === true || cloudObj.hasSite === false));
}

/* A site is never unassigned - assignment is something a project has. It is
   listed here when it holds one, the same shape as External. */
/* Does this site hold a project that matches, *and that he can see*?

   Every site-level question in this file is really this one question with a
   different predicate, and each copy of it had the same hole: it walked the
   children and never asked the owner filter, while `renderTreeChildren` draws
   them through `passOwner`. So on Mine, a colleague's project inside one of
   his sites made the site match, made the chip count it, and was then not
   drawn - "it says there's three items, and when I click it there's only two
   ESX files showing", and "local only, which also has a three, and quite
   literally nothing shows".

   One helper, because three copies of a rule is three chances to fix two of
   them. `pred(cloud, local)` is the project-level question. */
function _siteHoldsVisible(cloudObj, localObj, pred) {
  const kids = (cloudObj && cloudObj.children) || (localObj && localObj.children) || null;
  if (!kids) return false;
  const ok = (row) => _passOwnerForCounts(row.cloud, row.local) && pred(row);
  return (kids.matched || []).some(p => ok({
           status: p.namesDiffer ? 'mismatch' : 'synced', cloud: p.cloud,
           local: p.local, matchType: p.matchType,
           staleness: p.staleness || null, namesDiffer: !!p.namesDiffer,
           differenceKind: p.differenceKind || null }))
      || (kids.cloudOnly || []).some(c => ok({
           status: 'orphan', cloud: c, local: null }))
      || (kids.localOnly || []).some(l => ok({
           status: 'orphan', cloud: null, local: l }));
}

function _siteHasUnassigned(cloudObj, localObj) {
  return _siteHoldsVisible(cloudObj, localObj, (r) => _isUnassignedProject(r.cloud));
}

/* Ekahau will not let him change somebody else's project, so nor will this.

   "I was on All when I see those things, so maybe those particular esx files
   are actually someone else's, and I can't assign them to my site - which
   makes sense absolutely. But it also shouldn't try to auto-assign them if
   they're somebody else's files."

   Auto-assign offered three assignments and Ekahau answered `403 Forbidden`
   to all three, because the candidate set was gated on the **owner filter**
   and he had it on All. A filter is a view, not a permission: All is the
   correct thing to be on when you want to see everything, and it must not
   become consent to act on it.

   `''` means allowed; a non-empty string is the reason it is not, shown on
   the control rather than discovered a second later in an error panel.

   The unknown case is deliberately permissive. A project with no owner
   recorded is not evidence that it is someone else's, and refusing on
   missing data is the guard-that-fires-on-his-normal-case failure. */
function ownershipBlock(cloudObj) {
  //: `typeof` because this is sliced out of the file by several probes, and
  //: a bare reference to an undeclared `data` is a ReferenceError rather
  //: than undefined.
  const d = (typeof data !== 'undefined' && data) || null;
  const me = ((d && d.currentUser) || '').toLowerCase();
  const owner = (cloudObj && cloudObj.owner || '').toLowerCase();
  if (!me || !owner || owner.indexOf('@') < 0 || owner === me) return '';
  return 'Owned by ' + (cloudObj.owner || 'someone else')
       + '. Ekahau only lets the owner change a project.';
}

function iOwn(cloudObj) {
  return !ownershipBlock(cloudObj);
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


/* Projects you own that nobody else can see.

   This is an oversight filter, not a browsing convenience: it is for finding
   the survey you finished and never sent, while somebody waits on it. So the
   definition has to be the one that makes that question answerable, and there
   are three cases the obvious version gets wrong.

   `sharedWith` already excludes the OWNER role, so it is "everyone else with
   access". Then:

   - **You have to own it.** A project someone else owns and shared *with you*
     has `sharedWith == [you]`; subtracting yourself would leave it empty and
     call it unshared, which is exactly backwards - it is shared, that is how
     you can see it. It is also not something you could have failed to share.
   - **Shared only with yourself counts as unshared**, because nobody other
     than you has access, which is the thing being asked.
   - **It has to exist in the cloud.** A local-only file is not "unshared", it
     is un-uploaded, and the Local-Only card already answers that. Counting it
     here would make this number mean two different things at once.

   Group shares are covered without special handling: toggling the sharing
   group adds every member as a dataset user, so they arrive in `sharedWith`
   like anyone else. */
function _isUnshared(cloudObj) {
  if (!cloudObj) return false;                 // local-only: a different question
  const me = ((data && data.currentUser) || '').toLowerCase();
  if (!me) return false;                       // cannot tell yours from theirs
  const owner = (cloudObj.owner || '').toLowerCase();
  if (owner && owner !== me) return false;     // theirs, so not yours to have shared
  const others = (cloudObj.sharedWith || [])
    .map(x => String(x || '').toLowerCase())
    .filter(x => x && x !== me);
  return others.length === 0;
}

/* A site is not unshared, because a site is not shared. It survives this
   filter only as somewhere to hang the projects that match. */
function _siteHasUnshared(cloudObj, localObj) {
  return _siteHoldsVisible(cloudObj, localObj, (r) => _isUnshared(r.cloud));
}

/* And a site is not external either.

   "the weird thing about the three external is that the site names are
   exactly that - just site names. So site names should not be external. We
   should only be concerned with projects."

   He is right, and it is the same category error as sharing. Ekahau shares
   *projects*; a site in an account belongs to that account. This used to open
   with `if (_isExternal(cloudObj, localObj)) return true`, which asked a
   project question of a site, and the chip then counted the site as one
   external item - so "3 external" was three sites, a number no list of
   projects could ever add up to. The site survives the filter only as
   somewhere to hang the projects that match. */
function _siteHasExternal(cloudObj, localObj) {
  return _siteHoldsVisible(cloudObj, localObj, (r) => _isExternal(r.cloud, r.local));
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

/* A filter is identified by what it filters, not by the furniture round it.

   These used to be `document.getElementById('dDupAllCard').hidden = ...`, and
   when the header redesign replaced those wrappers the getElementById returned
   null, the assignment threw, and every count below it silently stopped being
   written. Addressing the control by `data-filter` means the markup can change
   shape - card, chip, button, menu item - without the counting code caring, and
   `_setCount` writing through one place means a control that genuinely is not
   on this page costs that one number rather than all twenty-one. */
function _filterEls(key) {
  return document.querySelectorAll('[data-filter="' + key + '"]');
}

function _showFilter(key, visible) {
  _filterEls(key).forEach(el => { el.hidden = !visible; });
}

function _setCount(id, n) {
  const el = document.getElementById(id);
  if (el) el.textContent = n;
}

function updateDashboard() {
  const isDup = currentTab === 'duplicates';
  const isBak = currentTab === 'backups';
  const isProj = currentTab === 'projects';
  //: Every filter on the summary line belongs to exactly one of the three
  //: lists. `cloudy` is the everyday set, and naming it once is what stops a
  //: fourth tab from being added to some of the rules and not the others.
  const cloudy = !isDup && !isBak;

  /* The everyday filters, hidden where they mean nothing.

     This matched `.dash-card`, which the redesign removed, so since v2.113.0
     "items", "name mismatches" and the rest went on being offered on the
     Duplicates tab - where none of them applies. Addressed by what they filter
     now, like everything else. */
  ['all', 'mismatches', 'orphans', 'orphans-cloud', 'orphans-local'].forEach(key => {
    _showFilter(key, cloudy);
  });

  ['dup-all', 'dup-mixed', 'dup-local', 'dup-cloud'].forEach(key => {
    _showFilter(key, isDup);
  });

  ['bak-all', 'bak-project', 'bak-missing', 'bak-install'].forEach(key => {
    _showFilter(key, isBak);
  });

  /* These four are shown from inside the cloud-count branch, which does not
     run on the other two tabs at all - so whatever they last said stayed on
     screen. Arriving at the Backup Folder tab to be told "29 out of sync" is
     a number about a list that is no longer there. */
  if (!cloudy) {
    ['stale', 'external', 'unshared', 'unmatched-sites'].forEach(key => {
      _showFilter(key, false);
    });
  }

  /* The dots between the groups of chips. They are punctuation for a line
     that is not there on these two tabs, and they were reading as "· · ·"
     floating above the list. */
  document.querySelectorAll('.sum-sep').forEach(el => { el.hidden = !cloudy; });

  if (isBak) {
    /* Copies rather than sets. "4 project backups" and a list showing four
       rows agree with each other; counting the files they were taken of would
       put a number on screen that nothing in the list adds up to. */
    const groups = (bakData && bakData.groups) || [];
    const copies = (gs) => gs.reduce((n, g) => n + ((g.items || []).length), 0);
    _setCount('dBakAll', copies(groups));
    _setCount('dBakProject', copies(groups.filter(g => bakIsProject(g))));
    _setCount('dBakMissing', copies(groups.filter(g => g.kind !== 'install' && !g.exists)));
    _setCount('dBakInstall', copies(groups.filter(g => g.kind === 'install')));
    /* The size is the thing he is deciding on, so it is not hidden behind a
       chip that also filters - it is a plain reading on the line. */
    const sizeEl = document.getElementById('dBakSize');
    const sepEl = document.getElementById('dBakSizeSep');
    const total = (bakData && bakData.bytes) || 0;
    if (sizeEl) {
      sizeEl.textContent = (bakData && bakData.human) || fmtBytes(total);
      sizeEl.hidden = !total;
      sizeEl.title = 'What every backup listed on this tab is using on disk.';
    }
    if (sepEl) sepEl.hidden = !total;
    /* A hidden chip still filters. Arriving here holding a `dup-` filter
       would empty the list with nothing on screen explaining why, so anything
       that is not one of this tab's own filters falls back to All. */
    if (activeFilter.indexOf('bak-') !== 0 && activeFilter !== 'all') activeFilter = 'all';
  } else {
    const sizeEl = document.getElementById('dBakSize');
    const sepEl = document.getElementById('dBakSizeSep');
    if (sizeEl) sizeEl.hidden = true;
    if (sepEl) sepEl.hidden = true;
  }

  if (isDup) {
    const s = (dupData && dupData.summary) || { total: 0, mixed: 0, localOnly: 0, cloudOnly: 0 };
    _setCount('dDupAll', s.total);
    _setCount('dDupMixed', s.mixed);
    _setCount('dDupLocal', s.localOnly);
    _setCount('dDupCloud', s.cloudOnly);
  } else if (!isBak && data && data.summary) {

    const ownerVisible = currentTab === 'sites' ? _siteOwnedVisible : _passOwnerForCounts;
    const _countsAsStale = isOutOfSync;

    let matched = 0, mismatches = 0, cloudOnly = 0, localOnly = 0, nameMatches = 0;
    let staleCount = 0;
    let externalCount = 0;

    const typeCount = { Design: 0, Measured: 0, Hybrid: 0 };
    const bumpType = (a, b) => {
      const t = (a && a.projectType) || (b && b.projectType);
      if (t && typeCount[t] !== undefined) typeCount[t]++;
    };





    const isSitesTab = currentTab === 'sites';
    /* On the Sites tab the external count is `kidExternal` - the projects,
       gathered by `walkKids`. A site is never itself external. */
    const rowIsExternal = (c, l) => !isSitesTab && _isExternal(c, l);
    /* On the Sites tab every count is about the projects inside the sites.

       "sites should not be counted in those - we should only have a button for
       unmatched sites." Two of these already walked in and counted files;
       mismatches, cloud-only and local-only counted folders, which is what had
       "cloud only" reading 0 while showing two projects. */
    let kidMismatches = 0, kidCloudOnly = 0, kidLocalOnly = 0;
    let kidExternal = 0;
    /* Through the owner filter, the same as the rows.

       This walked every child of every visible site and counted the lot.
       `renderTreeChildren` draws them through `passOwner`, so on any setting
       but All the chip and the list were counting different sets - which is
       "cloud only says three and two show", and "local only says three and
       nothing shows" for a site whose loose files belong to a colleague. */
    const walkKids = (kids) => {
      if (!kids) return;
      const mine = (c, l) => _passOwnerForCounts(c, l);
      (kids.matched || []).forEach(p => {
        if (!mine(p.cloud, p.local)) return;
        if (p.matchType === 'exact') nameMatches++;
        if (_countsAsStale(p)) staleCount++;
        if (p.namesDiffer) kidMismatches++;
        if (_isExternal(p.cloud, p.local)) kidExternal++;
        bumpType(p.cloud, p.local);
      });
      (kids.cloudOnly || []).forEach(c => {
        if (!mine(c, null)) return;
        kidCloudOnly++;
        if (_isExternal(c, null)) kidExternal++;
        bumpType(c, null);
      });
      (kids.localOnly || []).forEach(l => {
        if (!mine(null, l)) return;
        kidLocalOnly++;
        if (_isExternal(null, l)) kidExternal++;
        bumpType(null, l);
      });
    };
    let externalOrphans = 0;
    (data.matched || []).forEach(p => {
      if (!ownerVisible(p.cloud, p.local)) return;
      matched++;
      if (p.namesDiffer && !isSitesTab) mismatches++;
      if (rowIsExternal(p.cloud, p.local)) externalCount++;
      if (isSitesTab) {
        walkKids((p.cloud && p.cloud.children) || (p.local && p.local.children));
      } else {
        if (p.matchType === 'exact') nameMatches++;
        if (_countsAsStale(p)) staleCount++;
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
    /* A site with nothing on the other side. The only site-level question
       left, and the only chip that asks one. */
    const unmatchedSites = isSitesTab ? (cloudOnly + localOnly) : 0;

    _setCount('dAll', matched + cloudOnly + localOnly);
    _setCount('dMismatches', isSitesTab ? kidMismatches : mismatches);
    _setCount('dUnmatchedSites', unmatchedSites);
    _showFilter('unmatched-sites', isSitesTab);
    _setCount('dStale', staleCount);
    _showFilter('stale', cloudy && staleCount > 0);
    _setCount('dNameMatches', nameMatches);

    _setCount('dOrphans', Math.max(0, cloudOnly + localOnly - externalOrphans));
    /* A cloud project Ekahau has filed under no site is still a cloud project
       with nothing matching it on disk, and the list has always drawn it here.
       The count was the only thing that did not look. */
    /* Cloud-only and local-only are about *projects* here, so they count the
       files inside the sites plus the ones Ekahau filed under no site - not
       the sites themselves, which "unmatched sites" now covers. */
    let looseCloud = 0;
    if (isSitesTab) {
      /* The no-site band holds projects too, and the list draws them under
         every project filter they answer - so they are counted under each
         one as well, not only under cloud-only. */
      ((data.orphans && data.orphans.cloudOnly) || []).forEach(c => {
        if (!_passOwnerForCounts(c, null)) return;
        looseCloud++;
        if (_isExternal(c, null)) kidExternal++;
      });
    }
    _setCount('dCloudOnly', isSitesTab ? (kidCloudOnly + looseCloud) : cloudOnly);
    _setCount('dLocalOnly', isSitesTab ? kidLocalOnly : localOnly);
    _setCount('dExternal', isSitesTab ? kidExternal : externalCount);
    _showFilter('external', cloudy && externalCount > 0);

    // Counted through the owner filter, like every other card, so the number
    // on the card is the number of rows the list will actually show.
    /* Sharing is a property of a project. "you don't actually share sites on
       Ekahau" - and counting a site because something inside it was unshared
       gave him 97, the number of his folders, and then listed folders he
       cannot share. On this tab the rows that answer this question are the
       projects, so those are what is counted. */
    let unsharedCount = 0;
    const countUnshared = (c, l) => {
      if (_isUnshared(c) && _passOwnerForCounts(c, l)) unsharedCount++;
    };
    if (isSitesTab) {
      const walkForShares = (kids) => {
        if (!kids) return;
        (kids.matched || []).forEach(p => countUnshared(p.cloud, p.local));
        (kids.cloudOnly || []).forEach(c => countUnshared(c, null));
      };
      (data.matched || []).forEach(p => walkForShares(
        (p.cloud && p.cloud.children) || (p.local && p.local.children)));
      (data.cloudOnly || []).forEach(c => walkForShares(c.children));
      (data.localOnly || []).forEach(l => walkForShares(l.children));
      ((data.orphans && data.orphans.cloudOnly) || []).forEach(c => countUnshared(c, null));
    } else {
      (data.matched || []).forEach(p => countUnshared(p.cloud, p.local));
      (data.cloudOnly || []).forEach(c => countUnshared(c, null));
    }
    _setCount('dUnshared', unsharedCount);
    // Hidden when there are none to find, and when we do not know who he is -
    // without that, "yours" is unanswerable and the filter would silently
    // mean something else.
    _showFilter('unshared', cloudy && !!((data && data.currentUser) || '')
                         && unsharedCount > 0);
    _setCount('dTypeDesign', typeCount.Design);
    _setCount('dTypeMeasured', typeCount.Measured);
    _setCount('dTypeHybrid', typeCount.Hybrid);
  }

  ['name-matches', 'type-design', 'type-measured', 'type-hybrid'].forEach(key => {
    _showFilter(key, cloudy);
  });
  /* Offered wherever those rows can appear. It was Projects-only, while the
     rows themselves render on the Sites tab - so on the tab where he could see
     them, nothing selected them and the wrong chip did. */
  _showFilter('unassigned', cloudy);
  if (cloudy && data) {
    let noSite = 0;
    if (isProj) {
      (data.matched || []).forEach(p => {
        if (p.cloud && !p.cloud.hasSite && _passOwnerForCounts(p.cloud, p.local)) noSite++;
      });
      (data.cloudOnly || []).forEach(c => {
        if (!c.hasSite && _passOwnerForCounts(c, null)) noSite++;
      });
    } else {
      /* On the Sites tab the same question has a different shape: the backend
         has already set these aside as the projects it could not file under
         any site. Counting the set the list actually draws is what keeps the
         number and the rows agreeing - counting it a second way is how they
         came apart. */
      ((data.orphans && data.orphans.cloudOnly) || []).forEach(c => {
        if (_passOwnerForCounts(c, null)) noSite++;
      });
      /* And the ones the backend filed *inside* a site because their local
         .esx lives in that site's folder - they are still assigned to no site
         in Ekahau, they are what the auto-assign banner offers to fix, and the
         filter shows the sites holding them. Leaving them out of the count was
         the other half of the number disagreeing with the list. */
      const _seenUn = new Set();
      const _walkUn = (kids) => {
        if (!kids) return;
        (kids.matched || []).forEach(pr => {
          if (_isUnassignedProject(pr.cloud) && _passOwnerForCounts(pr.cloud, pr.local)
              && !_seenUn.has(pr.cloud.id)) { _seenUn.add(pr.cloud.id); noSite++; }
        });
        (kids.cloudOnly || []).forEach(c => {
          if (_isUnassignedProject(c) && _passOwnerForCounts(c, null)
              && !_seenUn.has(c.id)) { _seenUn.add(c.id); noSite++; }
        });
      };
      (data.matched || []).forEach(pr => _walkUn(
        (pr.cloud && pr.cloud.children) || (pr.local && pr.local.children)));
      (data.cloudOnly || []).forEach(c => _walkUn(c.children));
      (data.localOnly || []).forEach(l => _walkUn(l.children));
    }
    _setCount('dUnassigned', noSite);
  }
  /* `unassigned` is offered on both cloud tabs, so it is not reset on either.

     This read `!isProj`, and he works on the Sites tab - so every call to
     `updateDashboard` silently put him back on All: "I clicked one and it
     took me out of the filter and put me back to All, which is bad
     behaviour." A filter lasts until he changes it. The guard below stays
     because that one is about a filter whose question cannot be asked at
     all - no signed-in user means no "mine" to compare against. */
  if (activeFilter === 'unshared' && !((data && data.currentUser) || '')) {
    activeFilter = 'all';
  }
  _markActiveFilter();
}
function setFilter(f) {

  if (f === 'synced') f = 'all';
  activeFilter = activeFilter === f ? 'all' : f;
  /* The third copy of this rule, and the one that runs when he clicks.

     It read `.dash-card`, which the v2.113.0 header redesign removed. v2.118.0
     converted the two copies in the tab switcher and in `updateDashboard` and
     missed this one - so the highlight was painted on load and then never
     moved, which is exactly what he reported: "when you click those it doesn't
     highlight that you're on those either."

     One rule, one copy. That was the point of `_markActiveFilter` and it only
     works if every caller uses it. */
  _markActiveFilter();
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
  /* Before the dispatch, not after it. Both of the local-folder tabs return
     early, so the rail was drawn for the ledger and then left standing over a
     list it does not index - twenty-six letters that select nothing. */
  _renderJumpNav();
  if (currentTab === 'backups') { renderBackups(); return; }
  if (currentTab === 'duplicates') { renderDuplicates(); return; }
  /* Rebuilding the list scrolls him back to the top of ninety-eight sites,
     which is its own way of losing his place. */
  const _scroller = document.scrollingElement || document.documentElement;
  const _wasAt = _scroller ? _scroller.scrollTop : 0;
  lastChkIndex = null;
  const el = document.getElementById('rowsContainer');
  const q = document.getElementById('searchBox').value.toLowerCase();
  const hit = n => !q || (n || '').toLowerCase().includes(q);
  /* A closed site would hide its own search hits, which reads as the search
     being broken. Searching opens whatever matched, for as long as the box has
     something in it. */
  _searching = !!q;

  const legend = document.querySelector('.col-legend');
  if (legend) legend.style.display = 'none';
  el.innerHTML = renderLedger(hit);
  updateBulkBar(); refreshSelAll();
  _renderJumpNav();
  if (_scroller && _wasAt) _scroller.scrollTop = _wasAt;
}

let _jumpNavPresentCache = new Set();
function _renderJumpNav() {
  const nav = document.getElementById('jumpNav');
  if (!nav) return;
  if (isLocalOnlyTab(currentTab)) { nav.style.display = 'none'; return; }
  nav.style.display = '';
  const container = document.getElementById('rowsContainer');

  if (!activeLetter) {
    const fresh = new Set();
    //: Every band in the list now has rows under it, so every band is a
    //: letter he has. The `empty-letter` exclusion that used to be here went
    //: with the placeholders it existed to skip.
    container.querySelectorAll('[data-jump-letter]').forEach(el => {
      fresh.add(el.dataset.jumpLetter);
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

      /* Not a reason to redraw the list. This exists to colour duplicate
         hints; on v2.113.0-v2.117.0 it was accidentally the only thing that
         ever rendered the ledger, because `updateDashboard` threw before
         `onData` reached `renderRows()`. Whether the page came up at all then
         depended on which of two parallel requests answered first, which is
         exactly the intermittency he described. */
      if (currentTab !== 'duplicates' && !_pendingData) renderRows();
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
      h += `<button class="icon-btn" title="Show in Explorer/Finder" onclick="revealInExplorer('${pj(it.path)}')">&#128193;<span class="ib-label">Show</span></button>`;
    } else {
      h += `<button class="icon-btn" title="View site contents" onclick="openCloudPeek('${j(it.id)}','${j(it.location)}')">&#128065;<span class="ib-label">View</span></button>`;
    }

    const iidAttr = it.side === 'local' ? pj(iid) : j(iid);
    h += `<button class="icon-btn del" title="Delete" onclick="dupDeleteOne('${kAttr}','${iidAttr}')">&#128465;<span class="ib-label">Delete</span></button>`;
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

/* ── The Backup Folder tab ─────────────────────────────────────────────────

   Six places in this suite copy a file aside before overwriting it, and every
   one of them has been reporting a path into a folder there was no way to open
   from inside the tool: "I know we have no window to it right now."

   So this is the window, and it is a file manager rather than a report. The
   list groups every copy under the file it was taken of, newest first, and
   each row can be put back, shown in Explorer, or deleted. Restoring is the
   whole point of the tab - a backup nobody can reach is not a backup, it is
   disk usage - so it is the first control on the row rather than the last.

   Three things about it that are decisions rather than defaults:

   * **The destination is named before anything is written.** The confirm
     quotes the exact path the restore will land on, taken from the server's
     own `restoreTo`. Five dialogs once told him the wrong place to find a
     file he had just overwritten; a sentence in a test cannot stop that
     happening again, but reading the path out of the same field the write
     uses can.
   * **Restoring keeps what it replaces.** The live file is copied into the
     backups folder first, so a restore of the wrong generation is one more
     restore away from being undone, and the backup being restored is left on
     disk rather than consumed.
   * **Deleting asks once and says what goes.** Unrecoverable earns friction,
     not refusal - a count and a size in a confirm, not a word to type out. */

let bakData = null;
//: What each row's handlers refer to. Paths carry apostrophes, spaces and
//: backslashes, and a Windows path inside a quoted onclick is the exact shape
//: that turns a rendered control into a dead one - so the markup carries the
//: row's position in this array and the path never goes near the attribute.
let bakIndex = [];
//: Group keys that are shut. Groups start open - the generations are the
//: reason to be on the tab, and a list of names would just be a list of names.
let bakClosed = new Set();
let bakChecked = new Set();

function bakApi(action, body) { return WD.api('backups/' + action, body || {}); }

function onBackups(kind, payload) {
  if (kind !== currentTab) return;
  let d = payload;
  if (typeof payload === 'string') {
    try { d = JSON.parse(payload); }
    catch (err) { toast('Bad data payload', 'error'); return; }
  }
  if (!d || d.error) {
    document.getElementById('rowsContainer').innerHTML =
      '<div class="empty-msg">' + e((d && d.error) || 'Could not read the backups folder') + '</div>';
    if (d && d.error) toast(d.error, 'error');
    return;
  }
  bakData = d;
  //: A group that has gone keeps neither its open state nor its ticks, or a
  //: refresh after a delete leaves a checkbox selecting a file that is not
  //: there and "3 selected" over two rows.
  const live = new Set();
  (d.groups || []).forEach(g => (g.items || []).forEach(i => live.add(i.path)));
  Array.from(bakChecked).forEach(p => { if (!live.has(p)) bakChecked.delete(p); });
  updateDashboard();
  renderBackups();
}

function bakRefresh() {
  bakApi('list').then(d => onBackups('backups', d))
    .catch(err => toast('Load failed: ' + err.message, 'error'));
}

/* Every copy on the tab, in the order they are drawn, whatever the filter. */
function bakVisibleGroups() {
  const groups = (bakData && bakData.groups) || [];
  let out = groups;
  if (activeFilter === 'bak-project') out = groups.filter(g => bakIsProject(g));
  else if (activeFilter === 'bak-missing') out = groups.filter(g => g.kind !== 'install' && !g.exists);
  else if (activeFilter === 'bak-install') out = groups.filter(g => g.kind === 'install');

  const q = (document.getElementById('searchBox').value || '').toLowerCase();
  if (q) {
    out = out.filter(g => (g.name || '').toLowerCase().includes(q)
                       || (g.folder || '').toLowerCase().includes(q));
  }
  return out;
}

function bakIsProject(g) {
  return g.kind !== 'install' && /\.esx$/i.test(g.name || '');
}

/* The part of a path worth reading. The project folder is the same forty
   characters on every row, and repeating it pushes the part that differs off
   the end of the column. */
function bakShortPath(path) {
  const roots = (bakData && bakData.roots) || [];
  const norm = s => String(s || '').replace(/\\/g, '/');
  const p = norm(path);
  let best = '';
  roots.forEach(r => {
    const rn = norm(r).replace(/\/+$/, '');
    if (rn && p.toLowerCase().startsWith(rn.toLowerCase() + '/') && rn.length > best.length) best = rn;
  });
  if (!best) return path;
  const rest = p.slice(best.length + 1);
  return rest || path;
}

function renderBackups() {
  const el = document.getElementById('rowsContainer');
  const legend = document.querySelector('.col-legend');
  if (legend) legend.style.display = 'none';
  //: Deleting the eightieth copy in a list and being returned to the top of
  //: it is the same lost place the ledger scrolls around.
  const _scroller = document.scrollingElement || document.documentElement;
  const _wasAt = _scroller ? _scroller.scrollTop : 0;
  const _restoreScroll = () => { if (_scroller && _wasAt) _scroller.scrollTop = _wasAt; };

  const all = (bakData && bakData.groups) || [];
  const groups = bakVisibleGroups();

  bakIndex = [];
  groups.forEach(g => (g.items || []).forEach(it => {
    //: The file's name travels with the row so a delete confirm can say
    //: which project each copy belongs to - the backup's own filename is the
    //: project name plus a timestamp, which reads as noise in a list of eight.
    bakIndex.push(Object.assign({}, it, { groupName: g.name }));
  }));

  let h = bakExplainHtml();

  if (!groups.length) {
    h += `<div class="dup-empty">
      <div class="dup-empty-icon">&#128230;</div>
      <div class="dup-empty-title">${all.length
        ? 'No backups match this filter'
        : 'Nothing has been backed up yet'}</div>
      <div class="dup-empty-sub">${all.length
        ? 'Clear the search or pick a different filter to see the rest.'
        : 'A copy is kept here whenever something in the suite is about to overwrite one of your files &mdash; a sync replacing a local project, a name change written into the .esx, a Prep or Quick Walls run. Nothing has done that yet.'}</div>
    </div>`;
    el.innerHTML = h;
    _restoreScroll();
    return;
  }

  h += bakBulkBarHtml();
  h += '<div class="bak-container">';
  let n = 0;
  groups.forEach(g => { h += bakGroupHtml(g, n); n += (g.items || []).length; });
  h += '</div>';
  el.innerHTML = h;
  bakSyncBulkBar();
  _restoreScroll();
}

function bakExplainHtml() {
  const keep = bakData && bakData.keep != null ? bakData.keep : 3;
  const roots = (bakData && bakData.roots) || [];
  const where = roots.length
    ? `<code>${e(roots[0])}</code>` : 'your project folder';
  const retention = keep > 0
    ? `Settings keeps the newest <b>${keep}</b> of each file and deletes the rest as new ones are taken.`
    : `Retention is off in Settings, so every copy ever taken is kept until you delete it here.`;
  /* A place the scan could not read makes the total a floor rather than the
     answer, so it says so. The count only - never the path: the first report
     of this arrived as a Windows error with a profile SID in it, pasted
     across the page where the list should have been. */
  const blocked = (bakData && bakData.unreadable) || 0;
  const blockedNote = blocked
    ? `<div class="bak-blocked-note">${blocked} ${blocked === 1 ? 'place' : 'places'}
        could not be read, so the total below is at least this much rather than
        all of it. That is usually a cloud-storage folder whose provider is not
        running. The path is in the log &mdash; About &rarr; Diagnostics.</div>`
    : '';
  return `<div class="dup-explain bak-explain">
    <div class="dup-explain-title">What am I looking at?</div>
    ${blockedNote}
    <div class="dup-explain-body">
      Every copy the suite kept before it overwrote one of your files &mdash; a sync
      replacing a local project, a name written into the <code>.esx</code>, a Prep or
      Quick Walls run. They live in a <b>backups</b> folder inside ${where}, which the
      sync deliberately never reads, so nothing here is matched against Ekahau Cloud or
      counted as a duplicate.
      ${retention}
      Previous copies of the app itself are listed too and are <b>never</b> deleted
      automatically &mdash; that folder is the way back from a bad update.
    </div>
    <div class="dup-explain-legend">
      <b>Restore</b> puts a copy back over the original and keeps the file that is
      there now as a fresh backup first, so it can be undone the same way &nbsp;&middot;&nbsp;
      <b>Show</b> opens the folder it sits in &nbsp;&middot;&nbsp;
      <b>Delete</b> removes that one copy, and cannot be undone
    </div>
  </div>`;
}

function bakBulkBarHtml() {
  return `<div id="bakBulkBar" class="dup-bulk-bar bak-bulk-bar">
    <label class="dup-bulk-selall"><input type="checkbox" id="bakSelAll" onchange="bakSelectAll(this.checked)"> Select every copy shown</label>
    <span class="spacer"></span>
    <span id="bakBulkCount" class="dup-bulk-count">0 selected</span>
    <button class="btn btn-red btn-sm" onclick="bakDeleteChecked()">Delete checked</button>
  </div>`;
}

function bakGroupHtml(g, base) {
  const key = g.key;
  const open = !bakClosed.has(key);
  const items = g.items || [];
  const isInstall = g.kind === 'install';
  const where = bakShortPath(g.folder);

  let h = `<div class="bak-group ${open ? 'expanded' : ''}" data-key="${a(key)}">`;
  h += `<div class="bak-head" onclick="bakToggleGroup('${j(key)}')">`;
  h += `<span class="dup-chevron">&#9656;</span>`;
  h += `<span class="bak-title">${e(g.name)}</span>`;
  if (isInstall) h += `<span class="bak-pill install" title="A copy of the whole app folder, kept by the updater. Deleting it removes the way back from a bad update.">previous install</span>`;
  else if (!g.exists) h += `<span class="bak-pill missing" title="Nothing is at that path any more. Restoring one of these puts the file back rather than replacing it.">original gone</span>`;
  h += `<span class="bak-where" title="${a(g.folder)}">${e(where)}</span>`;
  h += `<span class="bak-counts"><b>${items.length}</b> cop${items.length === 1 ? 'y' : 'ies'} &middot; ${e(fmtBytes(g.bytes))}</span>`;
  h += `</div>`;

  h += `<div class="bak-body">`;
  items.forEach((it, idx) => {
    const i = base + idx;
    const checked = bakChecked.has(it.path) ? ' checked' : '';
    h += `<div class="bak-item" data-bid="${i}">`;
    h += `<input type="checkbox" class="bak-item-check" onchange="bakCheck(${i}, this.checked)"${checked}>`;
    h += `<div class="bak-item-when">
            <div class="bak-item-date">${e(fmtExactDate(it.when) || it.stamp)}</div>
            <div class="bak-item-rel">${e(fmtRelDate(it.when))}</div>
          </div>`;
    h += `<div class="bak-item-size">${e(fmtBytes(it.bytes))}</div>`;
    h += `<div class="bak-item-actions">`;
    if (isInstall) {
      h += `<span class="bak-item-note" title="Rolling an install back is done from About &rarr; Update, which knows how to stop the server first.">restore from About</span>`;
    } else {
      h += `<button class="btn btn-blue btn-sm" onclick="bakRestore(${i})" title="Put this copy back at ${a(it.restoreTo)}">&#8630; Restore</button>`;
    }
    h += `<button class="icon-btn" title="Show in Explorer/Finder" onclick="bakReveal(${i})">&#128193;<span class="ib-label">Show</span></button>`;
    h += `<button class="icon-btn danger" title="Delete this copy" onclick="bakDeleteOne(${i})">&#128465;<span class="ib-label">Delete</span></button>`;
    h += `</div></div>`;
  });
  h += `</div></div>`;
  return h;
}

function bakToggleGroup(key) {
  if (bakClosed.has(key)) bakClosed.delete(key); else bakClosed.add(key);
  renderBackups();
}

function bakCheck(i, on) {
  const it = bakIndex[i];
  if (!it) return;
  if (on) bakChecked.add(it.path); else bakChecked.delete(it.path);
  bakSyncBulkBar();
}

function bakSelectAll(on) {
  bakIndex.forEach(it => { if (on) bakChecked.add(it.path); else bakChecked.delete(it.path); });
  document.querySelectorAll('#rowsContainer .bak-item-check').forEach(c => { c.checked = !!on; });
  bakSyncBulkBar();
}

function bakCheckedItems() {
  return bakIndex.filter(it => bakChecked.has(it.path));
}

function bakSyncBulkBar() {
  const items = bakCheckedItems();
  const bytes = items.reduce((n, it) => n + (it.bytes || 0), 0);
  const out = document.getElementById('bakBulkCount');
  if (out) {
    out.textContent = items.length
      ? `${items.length} selected · ${fmtBytes(bytes)}`
      : '0 selected';
  }
  const all = document.getElementById('bakSelAll');
  if (all) all.checked = bakIndex.length > 0 && items.length === bakIndex.length;
}

async function bakRestore(i) {
  const it = bakIndex[i];
  if (!it) { toast('That copy is no longer listed — refresh and try again', 'error'); return; }
  /* The path in the dialog is the one the write will use. It is read off the
     same field the server restores to rather than rebuilt here, because a
     dialog that names the wrong folder is worse than one that names none. */
  const when = fmtExactDate(it.when) || it.stamp;
  const body = it.targetExists
    ? `<p>The copy taken on <b>${e(when)}</b> goes back to:</p>
       <p class="bak-confirm-path">${e(it.restoreTo)}</p>
       <p>The file that is there now is kept: it is copied into the backups folder
          first, under today's date, so this can be undone the same way.</p>`
    : `<p>Nothing is at that path any more, so the copy taken on <b>${e(when)}</b>
          is put back at:</p>
       <p class="bak-confirm-path">${e(it.restoreTo)}</p>
       <p>The folder is recreated if it has gone too. Nothing is overwritten.</p>`;
  const ok = await showConfirmModal('Put this copy back?', body, 'Restore');
  if (!ok) return;

  const r = await bakApi('restore', { path: it.path });
  if (!r || r.error) { toast((r && r.error) || 'The restore did not happen', 'error'); return; }
  toast(r.replaced
    ? `Restored to ${r.restored} — the copy it replaced was kept as a new backup`
    : `Restored to ${r.restored}`, 'success');
  bakRefresh();
}

async function bakReveal(i) {
  const it = bakIndex[i];
  if (!it) { toast('That copy is no longer listed — refresh and try again', 'error'); return; }
  const r = await bakApi('reveal', { path: it.path });
  if (r && r.error) toast(r.error, 'error');
}

function bakDeleteOne(i) {
  const it = bakIndex[i];
  if (!it) { toast('That copy is no longer listed — refresh and try again', 'error'); return; }
  return bakDelete([it]);
}

function bakDeleteChecked() {
  const items = bakCheckedItems();
  if (!items.length) { toast('Tick the copies you want to delete first', 'info'); return; }
  return bakDelete(items);
}

async function bakDelete(items) {
  const bytes = items.reduce((n, it) => n + (it.bytes || 0), 0);
  const installs = items.filter(it => it.kind === 'install');
  const list = items.slice(0, 8).map(it =>
    `<li>${e(it.groupName || it.name)} &mdash; ${e(fmtExactDate(it.when) || it.stamp)} &middot; ${e(fmtBytes(it.bytes))}</li>`).join('');
  const more = items.length > 8 ? `<p>&hellip; and ${items.length - 8} more.</p>` : '';
  const warn = installs.length
    ? `<p class="bak-warn">${installs.length === 1 ? 'One of these is' : installs.length + ' of these are'}
       a previous copy of the app itself. Deleting it removes the way back from a bad update.</p>`
    : '';
  const ok = await showConfirmModal(
    items.length === 1 ? 'Delete this backup copy?' : `Delete ${items.length} backup copies?`,
    `<p>This frees <b>${e(fmtBytes(bytes))}</b> and <b>cannot be undone</b>. The files
        these were taken of are not touched.</p>
     <ul class="bak-confirm-list">${list}</ul>${more}${warn}`,
    items.length === 1 ? 'Delete it' : `Delete ${items.length}`);
  if (!ok) return;

  const r = await bakApi('delete', { paths: items.map(it => it.path) });
  if (!r || r.error) { toast((r && r.error) || 'Nothing was deleted', 'error'); return; }
  items.forEach(it => bakChecked.delete(it.path));
  const skipped = (r.skipped || []).length;
  toast(`Deleted ${r.count} cop${r.count === 1 ? 'y' : 'ies'}, freeing ${r.human}`
        + (skipped ? ` — ${skipped} were left alone because they had already changed` : ''),
        skipped ? 'warn' : 'success');
  bakRefresh();
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

  const showSynced = activeFilter === 'all' || activeFilter === 'stale';
  const showMis = activeFilter === 'all' || activeFilter === 'mismatches' || activeFilter === 'stale';
  /* `orphans` is no longer a filter he can choose - "cloud only" and "local
     only" say which side is missing, and an umbrella over them was a third
     word for the same axis. The value is still accepted so an old bookmark or
     a saved state does not land on an empty list. */
  const showOrph = activeFilter === 'all' || activeFilter === 'orphans';
  const showOrphCloud = activeFilter === 'orphans-cloud';
  const showOrphLocal = activeFilter === 'orphans-local';
  const showUnmatchedSites = activeFilter === 'unmatched-sites';
  const showUnassigned = activeFilter === 'unassigned';
  const showNameMatches = activeFilter === 'name-matches';
  const showExternal = activeFilter === 'external';
  const showUnshared = activeFilter === 'unshared';
  const showStale = activeFilter === 'stale';

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
  //: The same predicate the chip counts with - see `isOutOfSync`. Two
  //: spellings of this is what made the header say three over a list of six.
  const directIsStale = isOutOfSync;

  /* `anyChildMatches` and the three `rowIs…` wrappers that used it are gone.
     Each one existed to let a site answer a project's question, and
     `_siteHoldsVisible` is that idea done once and through the owner
     filter. */
  /* One question about a project, asked of a project.

     "the unit of work in this tool is the project. Sites are how projects are
     organised." Every filter but one is a question about a project, so this
     is that question - and a **site** is visible under it exactly when it
     holds at least one project that answers it and that he can see.

     That single rule replaces a per-filter site clause each of which had its
     own idea of what a site was: three of them let a site answer on its own
     behalf, and none of them asked the owner filter, which is how a chip came
     to count rows the list would not draw. */
  const projPass = (st, row) => {
    if (typeFilter) return directMatchesType(row);
    if (showStale) return directIsStale(row);
    if (showNameMatches) return directIsNameMatch(row);
    if (showUnassigned) return _isUnassignedProject(row && row.cloud);
    if (showUnshared) return _isUnshared(row && row.cloud);
    if (showExternal) return _isExternal(row && row.cloud, row && row.local);
    if (showOrphCloud) return st === 'orphan' && !!(row && row.cloud && !row.local);
    if (showOrphLocal) return st === 'orphan' && !!(row && row.local && !row.cloud);
    if (showMis && st === 'mismatch') return true;
    if (showOrph && st === 'orphan'
        && _isExternal(row && row.cloud, row && row.local)) return false;
    return (st === 'synced' && showSynced) || (st === 'mismatch' && showMis)
        || (st === 'orphan' && showOrph);
  };

  const pass = (st, row) => {
    /* A site with nothing on the other side, either way round. The one chip
       that asks about folders and sites, and it says so in its name. */
    if (showUnmatchedSites) {
      return isSites && !!(row && ((row.cloud && !row.local) || (row.local && !row.cloud)));
    }
    if (!isSites) return projPass(st, row);

    /* Under All a site stands on its own - an empty site is still a site he
       may want to file something into. Under any narrower filter it earns its
       place by holding a matching project. */
    if (activeFilter === 'all') return projPass(st, row);
    return _siteHoldsVisible(row && row.cloud, row && row.local,
                             (kid) => projPass(kid.status, kid));
  };

  const own = ownerFilter();
  const me = ((data && data.currentUser) || '').toLowerCase();
  const passOwner = buildPassOwner(own, me);

  /* `projPass` goes through too. `pass` answers "should this *site* be
     drawn"; the rows inside a site are projects and are filtered by the
     project question itself. Handing the site predicate to the children
     asked each project whether it contained a matching project, which
     nothing does, so every child disappeared. */
  if (isSites) return renderSitesTree(hit, pass, passOwner, own !== 'all' && !!me, projPass);

  const rows = [];
  (data.matched || []).forEach(p => rows.push({
    status: p.namesDiffer ? 'mismatch' : 'synced', key: 'p:' + p.cloud.id, kind: 'projects',
    matchType: p.matchType, staleness: p.staleness || null,
    differenceKind: p.differenceKind || null,
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

  let h = uncomparedBandHtml(collectUncomparedStale(visible));
  h += `<div class="ledger">`;
  h += `<div class="ledger-head"><div class="lh-cell cloud">Cloud Projects (${nCloud})</div><div class="lh-gut"></div><div class="lh-cell local">Local .esx (${nLocal})</div></div>`;
  if (!visible.length) { h += emptyLedgerMessage() + `</div>`; return h; }
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
  const _emitFlatHeader = (g) =>
      `<div class="ledger-group-head" role="separator" data-jump-letter="${e(g)}" aria-label="Section ${e(g)}">`
    +   `<span class="glh-letter cloud">${e(g)}</span>`
    +   `<span class="glh-gap"></span>`
    +   `<span class="glh-letter local">${e(g)}</span>`
    + `</div>`;
  const allFlatLetters = ['#', ...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')];

  const letterFilter = (L) => !activeLetter || L === activeLetter;
  let z = 0;
  allFlatLetters.forEach(letter => {
    if (!letterFilter(letter)) return;
    const groupRows = flatByLetter.get(letter);
    /* A letter with nothing under it emits nothing. It used to emit a faded
       band anyway, and it is the A-Z bar that answers "which letters do I
       have" - that bar already greys the absent ones, and it deliberately
       ignored these placeholders when working out which letters exist, so
       they carried no information at all. What they did carry was length:
       site codes cluster on a handful of first letters, so a real list opens
       on three or four empty bands before its first row and scatters another
       twenty through the rest. */
    if (!groupRows || !groupRows.length) { z = 0; return; }
    h += _emitFlatHeader(letter);
    z = 0;
    groupRows.forEach(r => {
      {
      const _stripe = (z++ % 2) === 1;
      const _det = rowDetailHtml(r, _stripe);
      h += `<div class="ledger-row ${r.status}${_stripe ? ' stripe' : ''}${_verifyFailedClass(r)}${_isExternal(r.cloud, r.local) ? ' is-external' : ''}${_det ? ' has-detail' : ''}">${cloudCell(r, localCodes)}${gutCell(r)}${localCell(r, cloudCodes)}</div>${_det}`;
    }
    });
  });

  /* Outside the ledger, not at the end of it. Appending the band inside
     `<div class="ledger">` made the DOM say these rows were part of the list,
     which is exactly how they were read. */
  h += `</div>`;
  const heldBack = _collectHeldBack(passOwner);
  if (heldBack.length && !activeLetter) h += renderHeldBackSection(heldBack);
  return h;
}

function renderSitesTree(hit, pass, passOwner, ownerFilterActive, projPass) {
  const rows = [];
  (data.matched || []).forEach(p => rows.push({
    status: p.namesDiffer ? 'mismatch' : 'synced', key: 'p:' + p.cloud.id, kind: 'sites',
    matchType: p.matchType, staleness: p.staleness || null,
    differenceKind: p.differenceKind || null,
    cloud: p.cloud, local: p.local, sort: (p.cloud.name || p.local.name || ''),
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





  /* Cloud projects Ekahau has filed under no site.

     These used to be selected by `pass('orphan', ...)`, which is the *pairing*
     test - "this has no counterpart on the other side". They are a different
     thing: they have no **site**, which is Ekahau's own idea and Ekahau's own
     word. Sharing the test meant the "unpaired" chip counted one set and
     displayed another, so it read 0 and then showed two rows.

     They answer to the filter that names them, and to All. */
  /* Those projects are both things at once: filed under no site, and present
     in the cloud with nothing matching on disk. Both filters select them, and
     both counts include them - "which is correct, which means the number
     should actually be 2, not 0". */
  /* A cloud project filed under no site is a project like any other, so it
     answers to the project filter rather than to a list of two filters that
     were remembered. Naming the filters here meant "not shared" counted
     these and then drew none of them, because the band was only rendered for
     `unassigned` and `orphans-cloud`. */
  const orphans = ((data.orphans && data.orphans.cloudOnly) || [])
    .filter(o => hit(o.name) && passOwner({ cloud: o, local: null })
      && (!activeLetter || treeGroupOf(o.name) === activeLetter)
      && (activeFilter === 'all' || !projPass
          || projPass('orphan', { cloud: o, local: null })));

  const nCloud = visible.filter(r => r.cloud).length + orphans.length;
  const nLocal = visible.filter(r => r.local).length;

  /* The same set the Flat view offers, gathered out of the sites - a pair
     asking an unanswered question is the same pair whichever view he is in. */
  const childPairs = [];
  visible.forEach(r => {
    const kids = childrenOf(r);
    if (!kids) return;
    (kids.matched || []).forEach(p => {
      const row = { status: p.namesDiffer ? 'mismatch' : 'synced',
                    cloud: p.cloud, local: p.local, matchType: p.matchType,
                    staleness: p.staleness || null,
                    differenceKind: p.differenceKind || null };
      if (passOwner && !passOwner(row)) return;
      if (activeFilter !== 'all' && !(projPass || pass)(row.status, row)) return;
      childPairs.push(row);
    });
  });

  let h = uncomparedBandHtml(collectUncomparedStale(childPairs));
  h += `<div class="ledger tree">`;

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
  if (!visible.length && !orphans.length) { h += emptyLedgerMessage() + `</div>`; return h; }

  const _emitHeader = (g) =>
      `<div class="ledger-group-head" role="separator" data-jump-letter="${e(g)}" aria-label="Section ${e(g)}">`
    +   `<span class="glh-letter cloud">${e(g)}</span>`
    +   `<span class="glh-gap"></span>`
    +   `<span class="glh-letter local">${e(g)}</span>`
    + `</div>`;
  const allLetters = ['#', ...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')];
  const visibleByLetter = new Map();
  visible.forEach(r => {
    const g = treeGroupOf(r.sort);
    if (!visibleByLetter.has(g)) visibleByLetter.set(g, []);
    visibleByLetter.get(g).push(r);
  });

  const letterFilter = (L) => !activeLetter || L === activeLetter;
  let z = 0;
  allLetters.forEach(letter => {
    if (!letterFilter(letter)) return;
    const groupRows = visibleByLetter.get(letter);
    //: Same as Flat - see the note there. A band with nothing under it is
    //: length rather than information, and the A-Z bar is the index.
    if (!groupRows || !groupRows.length) { z = 0; return; }
    h += _emitHeader(letter);
    z = 0;
    groupRows.forEach(r => {
      const children = childrenOf(r);
      const kids = hasKids(children);
      const siteKey = r.cloud ? ('site:' + r.cloud.id) : ('folder:' + r.local.path);
      const open = (_searching && childHit(children)) || !collapsed.has(siteKey);
      r.toggle = { key: siteKey, open, hasKids: kids };
      /* The digest is computed here because this is where the predicates
         live, and it is given exactly the two `renderTreeChildren` filters
         its rows with - so the header counts the rows underneath it rather
         than the contents of the site. */
      /* `projPass`, not `pass`. The digest counts the rows drawn underneath,
         and those are projects - handing it the site predicate asks each
         project whether it contains a matching project, which reads 0 for
         every site. */
      r.digest = siteDigest(children, {
        passOwner,
        passFilter: activeFilter === 'all' ? null : (projPass || pass),
      });
      {
      const _stripe = (z++ % 2) === 1;
      const _det = rowDetailHtml(r, _stripe);
      /* The whole row opens the site.

         "it seems the only way I can expand a site is to use the chevron,
         which really seems crazy." A 20px target, ninety-eight times, for the
         most frequent action in the layout. The row carries a checkbox for
         selecting, so the row body is free to mean "open this"; the chevron
         stays as the affordance that shows which way it is. */
      h += `<div class="ledger-row tree-parent is-openable ${r.status}${_stripe ? ' stripe' : ''}${_verifyFailedClass(r)}${_isExternal(r.cloud, r.local) ? ' is-external' : ''}${_det ? ' has-detail' : ''}"`
         + ` data-toggle="${a(r.toggle.key)}" role="button" tabindex="0"`
         + ` aria-expanded="${r.toggle.open}"`
         + ` title="${r.toggle.open ? 'Collapse' : 'Expand'} this site \u2014 click anywhere on the row">`
         + `${cloudCell(r, localCodes)}${gutCell(r)}${localCell(r, cloudCodes)}</div>${_det}`;
    }

      /* Does this site match on its own account, or only through its
         children?

         "I'm just seeing 3 folders that don't have projects underneath them."
         A site owned by somebody else matches "external" by itself, and then
         the same test was applied to every project inside it - all of which
         are his - so the row survived and its contents did not.

         Matched by itself: show everything in it. Matched through a child:
         show the children that matched. */
      const siteMatchesAlone = _siteMatchesFilterAlone(r);
      if (open) {
        h += renderTreeChildren(children, hit, passOwner,
                                r.cloud && r.cloud.id, r.cloud && r.cloud.name,
                                siteMatchesAlone ? null : (projPass || pass));
      }
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
      {
      const _stripe = (i % 2) === 1;
      const _det = rowDetailHtml(r, _stripe);
      h += `<div class="ledger-row orphan${_stripe ? ' stripe' : ''}${_isExternal(r.cloud, r.local) ? ' is-external' : ''}${_det ? ' has-detail' : ''}">${cloudCell(r, localCodes)}${gutCell(r)}${localCell(r, cloudCodes)}</div>${_det}`;
    }
    });
  }

  //: Outside the tree - see the note on the same move in renderLedger.
  h += `</div>`;

  const heldBack = _collectHeldBack(passOwner);
  if (heldBack.length && !activeLetter) {
    h += renderHeldBackSection(heldBack);
  }
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

/* One file, its candidates, and the answer that is usually right.

   Grouped by the local file rather than by the pairing, because the pairing is
   not the subject: he is looking at one file and being asked which cloud
   project it is, if any. Five rows repeating the same filename is what made
   this read as five files.

   `heldBack` entries that share a local path are one question. Anything with
   no local side falls back to its own group so nothing is dropped. */
function _groupHeldBack(heldBack) {
  const byLocal = new Map();
  heldBack.forEach(h => {
    const key = (h.local && h.local.path) || ('cloud:' + (h.cloud && h.cloud.id));
    if (!byLocal.has(key)) byLocal.set(key, { local: h.local, kind: h.kind, candidates: [] });
    byLocal.get(key).candidates.push(h);
  });
  return [...byLocal.values()];
}

function renderHeldBackSection(heldBack) {
  const groups = _groupHeldBack(heldBack);
  const nFiles = groups.length;

  const body = groups.map((g, gi) => {
    const l = g.local;
    const label = g.kind === 'sites' ? 'site' : 'project';
    const name = l ? e(l.name) + (l.isDir ? '' : '.esx') : '(no local file)';

    const candidates = g.candidates.map(h => {
      const c = h.cloud;
      return `<li class="hbc-row">
        <span class="hbc-name" title="${a(c.name)}">${e(c.name)}</span>
        <span class="hbc-reason" title="Why WD did not pair these automatically">${e(h.reason)}</span>
        <span class="hbc-actions">
          <button class="btn btn-blue btn-sm" title="Say this cloud ${label} is the same one as ${a(name)}"
                  onclick="markManualMatch('${j(c.id)}','${pj(l && l.path)}','${j(c.name)}','${j(l && l.name)}')">This is the one</button>
          <button class="btn btn-secondary btn-sm" title="Never suggest this pair again"
                  onclick="markNotMatch('${j(c.id)}','${pj(l && l.path)}','${j(c.name)}','${j(l && l.name)}')">Not this one</button>
        </span>
      </li>`;
    }).join('');

    const n = g.candidates.length;
    /* The answer that is usually right, as one button. Every candidate here
       was rejected for a stated reason, so "none of them" is the likely
       truth - and dismissing five rows one at a time to say it is exactly the
       tedium he keeps hitting. */
    const none = (l && n)
      ? `<button class="btn btn-secondary btn-sm hb-none"
                 title="Dismiss all ${n} suggestion${n === 1 ? '' : 's'} for this file. It stays unpaired and WD stops offering ${n === 1 ? 'this one' : 'these'}."
                 onclick="heldBackNoneOfThese('${pj(l.path)}')">None of these</button>`
      : '';

    return `<div class="hb-group${(gi % 2) ? ' stripe' : ''}">
      <div class="hb-file">
        <span class="hb-tag local">LOCAL FILE</span>
        <span class="hb-name" title="${a((l && l.path) || '')}">${name}</span>
        ${none}
      </div>
      <div class="hb-q">WD found <b>${n}</b> possible ${label}${n === 1 ? '' : 's'} in the cloud and was not confident enough to pair ${n === 1 ? 'it' : 'any of them'}. Pick one, or none.</div>
      <ul class="hbc-list">${candidates}</ul>
    </div>`;
  }).join('');

  const isOpen = _heldBackOpen();
  /* Its own region, outside the tree.

     It used to be appended inside `.ledger.tree` immediately after the sites,
     in the ledger's own column shape, which is what made it look like the
     contents of the site above it. Nothing here belongs to a site - these are
     questions about what pairs with what. */
  return `<div class="hb-section${isOpen ? ' open' : ''}">
      <button class="hb-head" onclick="toggleHeldBack()" aria-expanded="${isOpen}">
        <span class="hb-toggle${isOpen ? ' open' : ''}">&#9656;</span>
        <span class="hb-title">Not paired yet \u2014 ${nFiles} local file${nFiles === 1 ? '' : 's'} we could not match on ${nFiles === 1 ? 'its' : 'their'} own</span>
        <span class="hb-sub">These are not part of any site above. Each one is a question: which cloud project is it?</span>
      </button>
      <div class="hb-list"${isOpen ? '' : ' hidden'}>${body}</div>
    </div>`;
}

/* "None of these", once per file.

   Every candidate was already rejected by the matcher for a stated reason, so
   this is the likely answer and it should cost one click rather than five.
   Each dismissal is the same `markNotMatch` the individual button makes - one
   operation, not a second implementation of it. */
async function heldBackNoneOfThese(localPath) {
  const group = _groupHeldBack(_collectHeldBack(buildPassOwner(ownerFilter(),
    (data && data.currentUser) || ''))).find(g => g.local && g.local.path === localPath);
  if (!group || !group.candidates.length) return;

  const n = group.candidates.length;
  const ok = await showConfirmModal(
    'None of these?',
    '<p>Stop suggesting ' + (n === 1 ? 'this pairing' : 'these ' + n + ' pairings')
    + ' for <b>' + e(group.local.name) + '</b>.</p>'
    + '<p class="sub">The file stays where it is and stays unpaired. Nothing is '
    + 'uploaded, downloaded, renamed or deleted. You can undo it from '
    + '<b>Not a match</b> in Settings if you change your mind.</p>',
    'None of these');
  if (!ok) return;

  for (const h of group.candidates) {
    await markNotMatch(h.cloud.id, group.local.path, h.cloud.name, group.local.name,
                       { silent: true });
  }
  toast('Dismissed ' + n + ' suggestion' + (n === 1 ? '' : 's') + ' for "'
        + group.local.name + '"', 'success');
  refreshData(true);
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

/* An empty list has to say what emptied it.

   "Nothing here for this filter" is true and useless when the filter doing
   the emptying is one the page applied by itself at startup: an account with
   no projects of its own opens on Mine, sees nothing, and has no reason to
   suspect a filter. Name it, and offer the way out. */
function emptyLedgerMessage() {
  const cur = ownerFilter();
  if (activeFilter === 'unshared') {
    return '<div class="empty-msg">Everything you own has been shared with '
      + 'someone.<br><button class="btn btn-secondary own-empty-btn" '
      + 'onclick="setFilter(&quot;unshared&quot;)">Show all projects</button></div>';
  }
  if (cur === 'all') return '<div class="empty-msg">Nothing here for this filter.</div>';
  return '<div class="empty-msg">Nothing here owned by '
    + (cur === 'mine' ? 'you' : 'anyone else')
    + ' — the owner filter is on <b>' + e(OWNER_FILTER_LABEL[cur]) + '</b>'
    + (_ownerFilterOverridden ? '' : ', your saved default')
    + '.<br><button class="btn btn-secondary own-empty-btn" '
    + 'onclick="setOwnerFilterUI(\'all\')">Show all owners</button></div>';
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
      /* `iOwn`, as well as the view filter. The view filter was the only
         gate here, so on All the banner proposed three assignments Ekahau
         refused with 403 - "it also shouldn't try to auto-assign them if
         they're somebody else's files". */
      if (p.cloud && p.cloud.unassigned && p.cloud.id && iOwn(p.cloud)
          && pass({ cloud: p.cloud, local: p.local })) {
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
    status: p.namesDiffer ? 'mismatch' : 'synced', matchType: p.matchType, differenceKind: p.differenceKind || null, cloud: p.cloud, local: p.local, sort: (p.cloud.name || p.local.name || '')
  }));
  (data.cloudOnly || []).forEach(s => rows.push({ status: 'orphan', cloud: s, local: null, sort: s.name || '' }));
  (data.localOnly || []).forEach(f => rows.push({ status: 'orphan', cloud: null, local: f, sort: f.name || '' }));
  return rows;
}

/* Whether a site satisfies the active filter without help from its
   contents. Only the filters that can be true of a site itself are asked -
   everything else is a question about a file, and a site can only answer it
   through its children. */
/* Can a site be the answer to this filter, on its own?

   "site names should not be considered projects." For all but one filter the
   answer is no: the unit of work is the project, and a site appears only as
   the heading its matching projects hang under. A site that answered a
   project filter by itself put a row in front of him he could not act on in
   the way the filter implied, and added itself to a count of projects.

   `unmatched-sites` is the exception, deliberately and by name - it is the
   one chip that asks a question about folders and sites. */
function _siteMatchesFilterAlone(r) {
  const c = r && r.cloud, l = r && r.local;
  if (activeFilter === 'unmatched-sites') return !!((c && !l) || (l && !c));
  return false;
}

function renderTreeChildren(children, hit, passOwner, parentSiteId, parentSiteName, passFilter) {
  const rows = [];
  (children.matched || []).forEach(p => rows.push({
    status: p.namesDiffer ? 'mismatch' : 'synced', matchType: p.matchType, staleness: p.staleness || null, differenceKind: p.differenceKind || null, cloud: p.cloud, local: p.local, sort: (p.cloud.name || p.local.name || '')
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
    {
      const _stripe = (i % 2) === 1;
      const _det = rowDetailHtml(r, _stripe);
      h += `<div class="ledger-row tree-child ${r.status}${_stripe ? ' stripe' : ''}${_verifyFailedClass(r)}${_isExternal(r.cloud, r.local) ? ' is-external' : ''}${_det ? ' has-detail' : ''}">${cloudCell(r, localCodes)}${gutCell(r)}${localCell(r, cloudCodes)}</div>${_det}`;
    }
  });
  return h;
}


/* One icon set, drawn on one grid, at one weight.

   What was here before was emoji: ⮕ at 24px next to 12px text, plus a bin,
   a paperclip, an eye, a flag, a pair of people and a link, each of them
   rendered by whatever font the operating system chose. Two of them were
   colour-emoji on Windows and monochrome on macOS. They never shared a stroke
   weight or an optical size with each other or with the type around them,
   which is most of why this list read as something assembled rather than
   designed.

   These are 16-unit paths stroked at 1.5 in `currentColor`, so they inherit
   the colour and the disabled state of whatever they sit in, and they scale
   with the type rather than fighting it.

   **None of them appears alone.** Every one sits beside its own text label or
   inside a menu item that is text - "I forgot what hybrid meant, or external
   for that matter" applies just as much to a glyph with no word next to it.
   The single exception is the row menu's own ⋯, which is the one symbol
   with a settled meaning across every application he uses, and it carries a
   title and an aria-label. */
const ICONS = {
  chevron:   'M6 3.4 10.6 8 6 12.6',
  rename:    'M11.1 2.6a1.65 1.65 0 0 1 2.3 2.3L5.9 12.4 2.8 13.2l.8-3.1z',
  trash:     'M2.8 4.4h10.4M6.3 4.4V2.9h3.4v1.5M4.3 4.4l.6 8.3a1 1 0 0 0 1 .9h4.2a1 1 0 0 0 1-.9l.6-8.3',
  move:      'M2.4 8h8.2M8.1 5.1 11 8l-2.9 2.9M13.4 2.9v10.2',
  share:     'M6 7.4a2 2 0 1 0 0-4 2 2 0 0 0 0 4ZM2.4 13.1c0-2 1.6-3.3 3.6-3.3s3.6 1.3 3.6 3.3M11 4.1a1.7 1.7 0 1 1 0 3.4M12.1 9.8c1.2.3 2 1.2 2 2.5',
  folder:    'M1.9 12.6V3.7h4L7.3 5.5h6.8v7.1z',
  //: A funnel, for the one line that says it is showing a selection.
  filter:    'M2.4 3.2h11.2L9.3 8.1v4.9l-2.6-1.5V8.1z',
  eye:       'M1.5 8S3.8 4.2 8 4.2 14.5 8 14.5 8 12.2 11.8 8 11.8 1.5 8 1.5 8ZM8 9.6a1.6 1.6 0 1 0 0-3.2 1.6 1.6 0 0 0 0 3.2Z',
  flag:      'M3.9 13.6V2.6h8.2l-1.6 2.7 1.6 2.7H3.9',
  merge:     'M3.9 2.6v3.8a3 3 0 0 0 3 3h5.4M9.8 6.5l2.9 2.9-2.9 2.9',
  link:      'M6.4 9.6 9.6 6.4M6.7 4.5 8.3 2.9a2.7 2.7 0 0 1 3.8 3.8l-1.6 1.6M9.3 11.5l-1.6 1.6a2.7 2.7 0 0 1-3.8-3.8l1.6-1.6',
  down:      'M8 2.9v8.2M4.9 8 8 11.1 11.1 8M2.8 13.4h10.4',
  up:        'M8 13.1V4.9M4.9 8 8 4.9 11.1 8M2.8 2.6h10.4',
  plus:      'M8 3.2v9.6M3.2 8h9.6',
  more:      'M4 8h.01M8 8h.01M12 8h.01',
  check:     'M2.9 8.4 6.2 11.7 13.1 4.8',
  alert:     'M8 2.6 14.4 13.4H1.6zM8 6.6v3.1M8 11.6v.01',
  arrowR:    'M2.6 8h10.8M9.9 4.5 13.4 8l-3.5 3.5',
  arrowL:    'M13.4 8H2.6M6.1 4.5 2.6 8l3.5 3.5',
  notEqual:  'M3.2 6.4h9.6M3.2 9.6h9.6M10.4 2.6 5.6 13.4',
  swap:      'M2.6 5.6h9.2L9.3 3.1M13.4 10.4H4.2l2.5 2.5',
};

function ic(name, cls) {
  const d = ICONS[name];
  if (!d) return '';
  return `<svg class="ic${cls ? ' ' + cls : ''}" viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="${d}"/></svg>`;
}

/* Every action a row can take, in one menu, in words.

   Each side of a row carried up to seven circular buttons that appeared on
   hover - and to make room for them the file's date was faded out, so mousing
   down the list swapped content in and out on every line. That flicker was the
   loudest thing on the page.

   One control at rest per side. It opens on a click, never on hover, and every
   item inside it is a labelled word: rename, move, share, delete. `<details>`
   gives that for nothing and is keyboard reachable without a line of script.
   The date stays where it is. */
function rowMenu(items, label) {
  const body = items.filter(Boolean).join('');
  if (!body) return '';
  const l = label || 'More actions';
  return `<details class="row-menu"><summary class="row-menu-btn" title="${a(l)}" aria-label="${a(l)}">${ic('more')}</summary>`
       + `<div class="row-menu-items">${body}</div></details>`;
}

/* `opts.blocked` is a reason the action cannot succeed.

   "technically we should block all items that are not things that you should
   be able to do... I don't want the user to be the bug catcher."

   The item stays on the menu, named and greyed, carrying its reason - rather
   than vanishing, which leaves him hunting for a control he has used before,
   or staying live and returning a 403. It is not `disabled` in the HTML
   sense: a disabled button swallows the click, and the click is how he asks
   why. `_wireDisabledBulkReasons` turns the click into the explanation, the
   same as `rdUnavailable`. */
function menuItem(icon, label, call, opts) {
  const o = opts || {};
  if (o.blocked) {
    return `<button class="row-menu-item is-disabled" aria-disabled="true"`
         + ` title="${a(o.blocked)}">${ic(icon)}<span>${label}</span></button>`;
  }
  return `<button class="row-menu-item${o.danger ? ' danger' : ''}" onclick="event.stopPropagation();${call}"`
       + `${o.title ? ` title="${a(o.title)}"` : ''}>${ic(icon)}<span>${label}</span></button>`;
}

/* An action in the detail row: an icon, a full label, one height, one shape.

   The row underneath used to mix a filled pill, an outlined button and a
   bare-text button side by side, which is what made it look like three
   different features had each added a control and none of them had looked at
   the others. */
/* `opts.writes` is the side this action **changes**, and it decides which
   lane of the band the button is drawn in - see `rowDetailHtml`.

   It is the side written to, never the side the value is read from. "Set the
   name inside the file to match" takes its new name from the cloud project and
   writes it into the local .esx: it reads cloud, it writes local, and it is a
   local action. Getting that backwards is the whole reason the option exists.

   Omitting it means the action changes neither file - a comparison, a pairing,
   a refusal to pair - and those stay with the sentence on the left. */
function rdAction(icon, label, call, opts) {
  const o = opts || {};
  const side = o.writes === 'cloud' || o.writes === 'local' ? o.writes : '';
  return `<button class="rd-btn${o.primary ? ' primary' : ''}${o.danger ? ' danger' : ''}${o.quiet ? ' quiet' : ''}"`
       + `${side ? ` data-writes="${side}"` : ''}`
       + `${o.title ? ` title="${a(o.title)}"` : ''} onclick="event.stopPropagation();${call}">`
       + `${ic(icon)}<span>${label}</span></button>`;
}


/* Split a run of rendered action buttons into the two lanes.

   The marker is on the rendered button (`data-writes`), so the split reads the
   same markup the browser will, and an action added later without a side
   simply stays on the left rather than disappearing. */
function _rdSplitBySide(html) {
  const out = { cloud: '', local: '', neutral: '' };
  const re = /<button class="rd-btn[\s\S]*?<\/button>/g;
  const found = String(html || '').match(re) || [];
  found.forEach(btn => {
    const m = /data-writes="(cloud|local)"/.exec(btn);
    if (m) out[m[1]] += btn; else out.neutral += btn;
  });
  return out;
}


/* What is inside this site, and how much of it wants him.

   "the user doesn't really care about all of the files all at once - they only
   care about individual sites and files", and he works one site at a time. So
   the sites are closed when the page opens and the flat list is an index
   rather than the workspace.

   A closed site has to earn being opened, which means its one line must answer
   "is there anything for me in here". It counts what is inside: a pair whose
   names disagree, or whose dates have moved, or that only exists on one side,
   is something he has to decide about; everything else is done. When there is
   nothing, the line says so quietly and he moves on. */
/* `opts.passFilter` / `opts.passOwner` are the *same* predicates the children
   are drawn with, so the digest describes the rows he can see.

   "at the top it says three files, one needs a decision, and I only see one
   file. So where are the three files?"

   It counted the whole site while the list underneath showed the rows that
   survived the filter, so with "out of sync" applied the header said three and
   the list said one, and the two other files - correctly hidden, because they
   are in sync - existed only as a number he could not reconcile against
   anything. The header was true about the site and false about the screen, and
   the screen is what he is reading.

   Both counts are kept: `shown` is what is on screen and `total` is what is in
   the site, so the line can say "1 of 3" rather than quietly dropping the
   context. */
function siteDigest(children, opts) {
  if (!children) return null;
  const o = opts || {};
  const rows = [];
  (children.matched || []).forEach(p => rows.push({
    status: p.namesDiffer ? 'mismatch' : 'synced', cloud: p.cloud, local: p.local,
    matchType: p.matchType, staleness: p.staleness || null,
    namesDiffer: !!p.namesDiffer, paired: true,
  }));
  (children.cloudOnly || []).forEach(c => rows.push({
    status: 'orphan', cloud: c, local: null, paired: false }));
  (children.localOnly || []).forEach(l => rows.push({
    status: 'orphan', cloud: null, local: l, paired: false }));

  const total = rows.length;
  let visible = o.passOwner ? rows.filter(o.passOwner) : rows;
  if (o.passFilter) visible = visible.filter(r => o.passFilter(r.status, r));

  let attention = 0, unpaired = 0;
  visible.forEach(r => {
    if (!r.paired) unpaired++;
    //: `isOutOfSync` rather than the raw flag, for the same reason the chip
    //: uses it: a pair already compared and settled is not a decision.
    else if (r.namesDiffer || isOutOfSync(r)) attention++;
  });
  const shown = visible.length;
  return { total, shown, narrowed: shown !== total,
           attention, unpaired, ok: shown - attention - unpaired };
}

function siteDigestHtml(r) {
  /* `renderSitesTree` computes this where the filter predicates are in
     scope and hangs it on the row, the same way it hangs `toggle`. Falling
     back to the unfiltered count keeps the function usable on its own. */
  const children = (r.cloud && r.cloud.children) || (r.local && r.local.children) || null;
  const d = r.digest || siteDigest(children);
  if (!d || !d.total) {
    return `<span class="cell-meta site-digest is-empty">empty</span>`;
  }

  const plural = (n) => `${n} file${n === 1 ? '' : 's'}`;
  if (d.narrowed) {
    const title = d.shown
      ? `This site holds ${plural(d.total)}; ${d.shown} of them match the filter you have on.`
      : `This site holds ${plural(d.total)}, none of which match the filter you have on.`;
    const parts = [`${d.shown} of ${plural(d.total)}`];
    if (d.attention) parts.push(`${d.attention} need${d.attention === 1 ? 's' : ''} a decision`);
    if (d.unpaired) parts.push(`${d.unpaired} unpaired`);
    /* No "all in sync" under a filter. That is a claim about the site, and
       what is on screen is a selection from it. */
    return `<span class="cell-meta site-digest ${d.attention + d.unpaired ? 'is-attention' : 'is-filtered'}" title="${a(title)}">`
         + `${ic(d.attention + d.unpaired ? 'alert' : 'filter')}${parts.join(' · ')}</span>`;
  }

  const files = plural(d.total);
  const needs = d.attention + d.unpaired;
  if (!needs) {
    return `<span class="cell-meta site-digest is-clear" title="Every file in this site is paired and up to date on both sides.">`
         + `${ic('check')}${files} · all in sync</span>`;
  }
  const parts = [];
  if (d.attention) parts.push(`${d.attention} need${d.attention === 1 ? 's' : ''} a decision`);
  if (d.unpaired) parts.push(`${d.unpaired} unpaired`);
  return `<span class="cell-meta site-digest is-attention" title="${a('Open this site to deal with ' + (needs === 1 ? 'it' : 'them') + '.')}">`
       + `${ic('alert')}${files} · ${parts.join(' · ')}</span>`;
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
/* The label is words; the coloured dot in front of it is the marker.

   These each carried a glyph of their own - a tick, a tilde, a question mark,
   a star - from when the chip was a filled pill and the glyph was the only
   thing distinguishing one colour from another at a glance. With a dot in
   front of every one of them, the row read "* / Same file". */
/* Each label says what was *determined*, not how sure it feels.

   "instead of 'same file' we should have, you know, exact match." He is right,
   and the same vagueness ran through all of them. "Same file" was the name of
   a *pairing* - the two carry Ekahau's id - and nothing had been compared, so
   it claimed more than was known. `Exact match` is reserved for the finding
   that earns it: a content comparison that came back identical. */
const MATCH_BADGE_SPEC = {
  manual: { cls: 'manual', label: 'You linked it', title: 'You paired these by hand. Click to unlink and go back to auto-matching.' },
  id:     { cls: 'id',     label: 'Same project',  title: 'One project in two places: both .esx files carry the same Ekahau project ID. That is who they are — it does not say the contents match. Use Check what differs for that.' },
  exact:  { cls: 'exact',  label: 'Same name',     title: 'The two names are identical. Nothing else has been checked — no shared Ekahau ID, and the contents have not been compared.' },
  code:   { cls: 'code',   label: 'Same site code', title: 'The site codes match and the names are close. Probably the same project; nothing is proven.' },
  fuzzy:  { cls: 'fuzzy',  label: 'Similar name',  title: 'Some words in common. A guess from the wording alone — worth a look before syncing.' },
};

const MATCH_BADGE_SPEC_SITE_EXACT = {
  cls: 'id',
  label: 'Same name',
  title: 'The two names match. A site has no stronger identity to compare - a folder carries no internal ID - so for a site pair this is as far as matching goes.',
};

/* Which pairings may be overwritten from the cloud.

   An id match is proven - the same Ekahau project id is stamped inside both
   .esx files - and a manual match is one the user made deliberately. A code or
   fuzzy match is only our reading of the names, and overwriting a file on a
   guess is how someone loses the wrong project, so those stay unactionable and
   say so. Confirming such a pair by hand promotes it to manual, which is
   actionable - the gate is something you can satisfy, not a wall. */
const PULLABLE_MATCH_TYPES = new Set(['id', 'manual', 'exact']);

/* Which pairings may be pushed *up* over the cloud copy.

   Narrower than pulling, on purpose. A pull replaces a local file and the one
   it replaced is kept in `backups/<site>/`; if it was the wrong pair, the copy
   is still there. A push deletes the cloud project it replaced, and a cloud
   delete does not come back - so the pair has to be proven rather than
   guessed. An id match is Ekahau's own stamp and a manual match is one he made
   deliberately; a bare name match is neither, and "SITE1 Building 2" matching
   the wrong "SITE1 Building 2" would destroy the wrong project.

   The same asymmetry the delete confirmations already use: recoverable one way,
   not the other, so the friction is not symmetric either.

   **`exact` was excluded at first and that was the bug.** It made the control
   unusable for the case he actually has. A project built locally and uploaded
   gets Ekahau's id stamped into the *cloud* copy; the local file only carries
   it once the project has been downloaded back. So "local is newer and there
   is no shared id" is not an oddity, it is the normal state of a project he
   has worked on since the last download - and it was the one thing refused.

   It is allowed and it asks first, naming the cloud project it will delete.
   Unrecoverable earns friction, not a wall. A `code` or `fuzzy` pairing is
   still refused: there the two names do not even match, so there is nothing
   for him to confirm against. */
const PUSHABLE_MATCH_TYPES = new Set(['id', 'manual', 'exact']);

//: Which of those are proven rather than inferred. The rest get a confirm.
const PROVEN_MATCH_TYPES = new Set(['id', 'manual']);

/* Replacing the cloud copy uploads and then **deletes** the old project, so
   it needs ownership as well as a proven pair. Pulling does not: a download
   writes only to his disk. */
function canPushToCloud(r) {
  return !!(r && r.cloud && r.local && (r.kind || currentTab) !== 'sites'
            && /\.esx$/i.test(String(r.local.path || ''))
            && iOwn(r.cloud)
            && PUSHABLE_MATCH_TYPES.has(r.matchType));
}

function canPullFromCloud(r) {
  return !!(r && r.cloud && r.local && (r.kind || currentTab) !== 'sites'
            && PULLABLE_MATCH_TYPES.has(r.matchType));
}

/* What a comparison found, so the row can show it at rest.

   Keyed by the pair, not the row, because the ledger re-renders constantly and
   an answer he waited on should survive that. Cleared when the pair changes on
   either side, since the answer is then about a file that no longer exists. */
const _compareResults = new Map();
function _compareKey(cloudId, localPath) {
  return String(cloudId || '') + '\u0000' + String(localPath || '').replace(/\\/g, '/').toLowerCase();
}
function compareResultFor(r) {
  if (!r || !r.cloud || !r.local) return null;
  return _compareResults.get(_compareKey(r.cloud.id, r.local.path)) || null;
}

/* Download the cloud copy and diff it against the local file.

   This is the answer to "are we able to actually analyse the contents ...
   kind of like a hashing situation". Hashing the archive cannot work - the
   cloud assembles a ZIP on demand and stores uncompressed while a local .esx
   is deflated - but comparing the contents is straightforward, and it turns
   "the cloud timestamp is later" into "three access points and a floor plan
   image differ", which is a fact rather than an inference.

   It is read-only and writes nothing to disk on either side, so it is safe to
   run across a whole selection before deciding anything. */
/* Rows that are mid-action, so the click is visible the instant it lands. */
const _rowBusy = new Map();

/* Keyed on whichever side exists.

   This used to build the key from both, and `rowIsBusy` returned null unless
   the row had both - so an unpaired row could never say it was working. The
   actions that were still silent are exactly the ones that operate on unpaired
   rows: download a cloud project with no local copy, link a local file with no
   project. The mechanism was excluding its own remaining cases. */
function _rowKey(cloudId, localPath) {
  return _compareKey(cloudId || '', localPath || '');
}

function rowIsBusy(r) {
  if (!r) return null;
  const id = (r.cloud && r.cloud.id) || '';
  const path = (r.local && r.local.path) || '';
  if (!id && !path) return null;
  return _rowBusy.get(_rowKey(id, path)) || null;
}

/* Mark a row for as long as something is running on it.

   Takes the promise the action already has and clears the mark when it
   settles, whichever way it settles. An action that forgets to clear its own
   mark is the stuck spinner, which is the failure this exists to prevent. */
function _busyWhile(cloudId, localPath, label, promise) {
  _setRowBusy(cloudId, localPath, label);
  const done = () => _setRowBusy(cloudId, localPath, null);
  if (promise && typeof promise.then === 'function') {
    promise.then(done, done);
  } else {
    done();
  }
  return promise;
}

/* Long enough that a slow upload is not interrupted, short enough that he is
   never left watching a spinner with nothing behind it. */
const ROW_BUSY_CEILING_MS = 30000;
const _rowBusyTimers = new Map();

function _setRowBusy(cloudId, localPath, what) {
  const k = _rowKey(cloudId, localPath);
  const timer = _rowBusyTimers.get(k);
  if (timer) { clearTimeout(timer); _rowBusyTimers.delete(k); }

  if (what) {
    _rowBusy.set(k, what);
    /* A row that says "Working" forever is the original complaint wearing a
       spinner. If nothing settles it, it stops claiming and says so. */
    _rowBusyTimers.set(k, setTimeout(() => {
      _rowBusyTimers.delete(k);
      if (_rowBusy.get(k) !== what) return;
      _rowBusy.delete(k);
      toast('That is taking longer than expected — the row no longer says it '
            + 'is working. Use Re-check to find out where it got to.', 'error');
      if (typeof renderRows === 'function') renderRows();
    }, ROW_BUSY_CEILING_MS));
  } else {
    _rowBusy.delete(k);
  }
  /* Marking a row must never be able to break the action it is decorating.
     This is decoration on top of an operation; if the list is not there to
     redraw, the operation still runs. */
  if (typeof renderRows === 'function') renderRows();
}

/* Re-evaluate one pair and draw what it now is.

   This is the whole answer to "you don't have any idea if it worked". An
   action owns the state it changed: it re-runs the comparison for its own pair
   - one call, not ninety-eight - and renders the result, so the row he is
   looking at states the outcome of the thing he just did. He never has to
   press Check a second time to find out whether the first one worked, and he
   never waits on a background poll to be told what he already did. */
async function settlePair(cloudId, localPath, opts) {
  const o = opts || {};
  try {
    const r = await pyApi('compare_with_cloud', cloudId, localPath);
    if (r && !r.error) {
      _compareResults.set(_compareKey(cloudId, localPath), r);
      /* A comparison is measured where a date is inferred, so a proven
         identical pair stops being reported as out of sync. Nothing is
         rewritten on disk - this is the tool declining to keep asking a
         question it has just answered. */
      if (!r.designDiffers && r.nameState !== 'internal_only') {
        _clearStaleness(cloudId);
      }
    } else if (r && r.error && !o.quiet) {
      toast('Could not confirm the result: ' + r.error, 'error');
    }
  } catch (err) {
    if (!o.quiet) toast('Could not confirm the result: ' + err.message, 'error');
  } finally {
    _setRowBusy(cloudId, localPath, null);
  }
}

function checkRealDifference(cloudId, localPath, label) {
  const key = _compareKey(cloudId, localPath);
  opEnqueue({
    title: `Comparing "${label}" with the cloud copy`,
    sub: 'Downloading the cloud copy to compare. Nothing is changed.',
    type: 'compare', pollBackend: true, undoable: false,
    run: async (opId) => {
      const r = await pyApi('compare_with_cloud', localPath, cloudId, opId);
      if (r && r.error) throw new Error(r.error);
      _compareResults.set(key, r);
      _scheduleOpRefresh();
      return r;
    },
  });
}

/* Every row on screen that is asking a question nothing has answered.

   "not compared yet" is honest and it is not a place to leave him across
   ninety projects - he has already said he will not recheck things twice, and
   being told the answer is unknown, row after row, is a version of that. So
   the whole set is offered as one action.

   **It is offered rather than done.** A comparison downloads the cloud copy of
   the project to compare it member by member, so running it automatically over
   a list this size would pull tens or hundreds of megabytes off Ekahau, on a
   work network, without being asked. Read-only is not the same as free. The
   band says how many and what it costs; the click is his.

   Filled at render time, because that is when the filter predicates exist and
   it is exactly the set he can see. */
let _uncomparedNow = [];

function collectUncomparedStale(rows) {
  const out = [];
  (rows || []).forEach(r => {
    if (!r || !r.cloud || !r.local || !r.staleness) return;
    if (r.differenceKind === 'renamed') return;   // already classified
    if (compareResultFor(r)) return;              // already answered
    out.push({ cloudId: r.cloud.id, localPath: r.local.path,
               label: r.cloud.name || r.local.name || '' });
  });
  return out;
}

function uncomparedBandHtml(pairs) {
  _uncomparedNow = pairs || [];
  const n = _uncomparedNow.length;
  if (n < 2) return '';   // one row's own button is closer than a banner
  return `<div class="uncompared-bar">`
    + `<span class="ub-icon">${ic('swap')}</span>`
    + `<span class="ub-text"><b>${n} of these have a date difference that has not been checked.</b> `
    + `Whether the design really changed, or something was only renamed, is still unknown on each of them.</span>`
    + `<button class="rd-btn primary" onclick="checkAllUncompared()" `
    + `title="Compares each pair's contents and reports what actually differs. Read-only — nothing is changed on either side. Each one downloads the cloud copy to compare it.">`
    + `${ic('swap')}<span>Check all ${n}</span></button>`
    + `</div>`;
}

async function checkAllUncompared() {
  const pairs = _uncomparedNow.slice();
  if (!pairs.length) { toast('Nothing left to check', 'info'); return; }
  /* Naming the cost, because read-only is not the same as cheap and he works
     on a network he does not control. */
  const ok = await showConfirmModal(
    `Check all ${pairs.length}?`,
    '<p>Compares each pair and reports what actually differs.</p>'
    + '<p class="sub"><b>Nothing is changed</b> on either side — not the cloud, '
    + 'not your local files.</p>'
    + '<p class="sub">Each comparison downloads that project\'s cloud copy to '
    + 'compare it, so ' + pairs.length + ' downloads will run. They are queued '
    + 'and each reports its own result.</p>',
    `Check all ${pairs.length}`);
  if (!ok) return;
  pairs.forEach(p => checkRealDifference(p.cloudId, p.localPath, p.label));
  toast(`Comparing ${pairs.length} file${pairs.length === 1 ? '' : 's'} — nothing will be changed`, 'info');
}

/* His immediate job is sixty of these, so one at a time is not the unit. Each
   file is its own queued operation with its own result - a single aggregate
   "done" across sixty comparisons would hide exactly the one that differs. */
function bulkCheckDifferences() {
  const pairs = selectedSyncItems().filter(
    d => d.kind === 'pair' && /\.esx$/i.test(String(d.localPath || '')));
  if (!pairs.length) {
    toast('Select some matched rows first', 'info');
    return;
  }
  clearSelection();
  pairs.forEach(d => checkRealDifference(
    d.cloudId, d.localPath, d.cloudName || d.localName || ''));
  toast(`Comparing ${pairs.length} file${pairs.length === 1 ? '' : 's'} — nothing will be changed`, 'info');
}

/* Write the cloud's project name into the local .esx.

   The third name, and the invisible one. Renaming a file on disk does not
   touch `project.json`, so after renaming a fleet of projects to a new
   convention every row reports a difference over a field he cannot see - for
   ever, because nothing he can do from the file manager will ever change it.

   The previous file goes to `backups/<site>/` first; if that copy cannot be
   written, nothing is changed. */
/* The action he walked through end to end, and the one that sent him round
   the loop twice. It now finishes by saying what is true. */
function fixInternalName(localPath, cloudName, label, cloudId) {
  //: The click landed. Visibly, now, rather than in nine seconds.
  if (cloudId) _setRowBusy(cloudId, localPath, 'Setting the name inside the file\u2026');
  const { promise } = opEnqueue({
    title: `Setting the project name inside "${label}" to "${cloudName}"`,
    sub: 'Rewrites the name stored in the .esx. The previous file is backed up.',
    type: 'rename', pollBackend: false, undoable: false,
    run: async (opId) => {
      const r = await pyApi('set_internal_project_name', localPath, cloudName, opId);
      if (r && r.error) throw new Error(r.error);
      // The stored comparison is about a file that has just changed.
      _compareResults.delete(_compareKey('', localPath));
      for (const key of Array.from(_compareResults.keys())) {
        if (key.endsWith('\u0000' + String(localPath).replace(/\\/g, '/').toLowerCase())) {
          _compareResults.delete(key);
        }
      }
      _scheduleOpRefresh();
      return r;
    },
  });

  /* The action owns the row it changed. It re-runs the comparison for this one
     pair and renders the answer, so the row states the outcome of what he just
     did - instead of going on asserting the state he changed until a poll
     notices. "I shouldn't have to recheck twice." */
  promise.then(() => {
    if (cloudId) return settlePair(cloudId, localPath);
    _scheduleOpRefresh();
  }).catch(() => {
    if (cloudId) _setRowBusy(cloudId, localPath, null);
  });
}

/* His fleet is in this state, not one file of it: 29 rows out of sync and 97
   local folders. One at a time would be an afternoon, so the selection is the
   unit - and each file is its own queued operation with its own result,
   because a single "done" across 29 writes would hide the one that failed. */
function bulkFixInternalNames() {
  const rows = selectedSyncItems().filter(
    d => d.kind === 'pair' && /\.esx$/i.test(String(d.localPath || ''))
         && (d.cloudName || '').trim());
  if (!rows.length) {
    toast('Select some matched rows first', 'info');
    return;
  }
  clearSelection();
  rows.forEach(d => fixInternalName(
    d.localPath, d.cloudName, d.localName || d.cloudName));
  toast(`Setting the project name inside ${rows.length} file`
    + (rows.length === 1 ? '' : 's') + ' — each is backed up first', 'info');
}

/* Send the local file up over the cloud project it is paired with.

   No confirm dialog for a single row: the button says what it does, and the
   backend's ordering is what makes it safe rather than a prompt. Nothing is
   deleted until the new copy is uploaded *and* verified to be his file.

   Every outcome is reported as itself. The one that matters most is the
   partial: upload succeeded, delete of the old one did not. That leaves two
   projects with the same name, which is precisely the duplicate situation he
   has been bitten by twice, so it is said in words - including which of the
   two is the good one - rather than reported as a bare failure.
*/
/* The operation itself, with no question attached.

   It is split out because the bulk run has already asked - once, in the plan
   dialog, naming every cloud project it will delete - and asking again per
   file would be the Prep pass all over again. Writing a second copy of the
   upload-verify-delete sequence for the bulk path is how this repo grows two
   implementations of one operation, and the row and the planner disagreeing is
   exactly what this commit is fixing. */
function _enqueuePushLocalOverCloud(cloudId, localPath, localName, cloudName) {
  _setRowBusy(cloudId, localPath, 'Uploading your local copy and replacing the cloud project…');
  const handle = opEnqueue({
    title: `Replacing cloud "${cloudName || localName}" with your local copy`,
    sub: 'Uploading, verifying, then removing the old cloud copy.',
    type: 'push', pollBackend: true, undoable: false,
    run: async (opId) => {
      const r = await pyApi('replace_cloud_project', localPath, cloudId, opId);

      if (r && r.error) {
        /* `note` is where the backend says what state the cloud is actually in
           - "nothing was deleted", or "there are now two copies and the new
           one is good". Dropping it would turn the most important sentence
           into a generic failure. */
        const detail = r.note ? (r.error + ' ' + r.note) : r.error;
        if (r.note) toast(detail, 'error');
        throw new Error(detail);
      }

      _clearStaleness(cloudId);
      _scheduleOpRefresh();
      toast(`Cloud copy of "${r && r.name ? r.name : (cloudName || localName)}" replaced`
            + (r && r.deletedOld ? ' — the old one was removed.' : '.'), 'success');
      /* A `note` on a *successful* replace is the consequence he did not ask
         for: the old project's shares went with it, because a share belongs
         to the project id and this makes a new project. Success is not a
         reason to drop the one sentence he has to act on. */
      if (r && r.note) toast(r.note, 'warn');
      return r;
    },
  });

  /* Same contract as the pull: the pair is re-evaluated and the row says what
     is now true, rather than waiting for a poll to notice. */
  handle.promise.then(() => settlePair(cloudId, localPath))
        .catch(() => _setRowBusy(cloudId, localPath, null));
  return handle;
}

async function pushLocalOverCloud(cloudId, localPath, localName, cloudName, matchType) {
  /* No dialog on a proven pair - the ordering is what makes it safe, and he
     performs this constantly. On a name-only pair the question is not whether
     the operation is safe but whether these two are the same project, and that
     is a question only he can answer, so it is asked once and names the
     project that will be deleted. */
  if (matchType && !PROVEN_MATCH_TYPES.has(matchType)) {
    const ok = await showConfirmModal(
      'Replace the cloud copy?',
      '<p>Upload <b>' + e(localName || '') + '</b> and replace the cloud project '
      + '<b>' + e(cloudName || '') + '</b>.</p>'
      + '<p class="sub">These two are paired on their names rather than on '
      + 'Ekahau\'s own id, so the tool cannot prove they are the same project. '
      + 'Check the name above is the one you mean.</p>'
      + '<p class="sub">The new copy is uploaded and checked first; the old '
      + 'cloud project is deleted only after that succeeds. A cloud delete '
      + 'cannot be undone.</p>',
      'Replace it');
    if (!ok) return;
  }
  _enqueuePushLocalOverCloud(cloudId, localPath, localName, cloudName);
}

/* The badge used to be the whole story: it said the cloud copy was newer and
   then offered nothing to do about it. It is the thing being read, so it is
   the thing to click. */
/* The row underneath the file name: what was found, and what to do about it.

   "yes, another row underneath the file name and slightly a different color
   would be really good."

   Everything used to be stacked into the gutter between two name columns, and
   his project names are long, so that lane is a few characters wide - the
   verdict, the staleness action, Check, and Re-check all wrapping over each
   other. The pair identifies the row; the findings and the actions are *about*
   the row, so they get their own full-width line directly beneath it.

   It renders when there is something to say: a comparison has been run, or the
   row is stale and therefore needs an action. A project that matches cleanly
   gets nothing - adding an empty line to all ninety-seven would make the list
   harder to scan, which is the opposite of the point.

   `stripe` is the parent row's banding. The detail takes the same banding and
   lifts it slightly, so it reads as attached to the row above rather than as
   another project. */

function rowDetailHtml(r, stripe) {
  /* The row that needs him, and what he can do about it.

     This band began as somewhere to put a comparison result - "another row
     underneath the file name and slightly a different color would be really
     good" - and it turned out to be the answer to the crowded middle column as
     well. A decision needs a sentence and two or three labelled buttons; there
     is no width for that between two project names, and there is plenty of it
     across the whole row.

     So the two mechanisms are one. Anything that asks something of him renders
     here: names that disagree, a copy that only exists on one side, a date that
     has moved, a comparison he has run. A row with nothing to say has no band
     at all, which is what keeps a list of ninety-seven folders scannable - the
     ones that need him are the ones with a second line. */
  const kind = r.kind || currentTab;
  if (kind === 'sites') return '';

  const cmp = compareResultFor(r);
  const stale = r.staleness;
  const c = r.cloud, l = r.local;
  const sentences = [];
  const acts = [];
  let tone = 'rd-plain', icon = 'alert';

  if (r.status === 'mismatch' && c && l) {
    tone = 'rd-differs'; icon = 'notEqual';
    sentences.push('The names disagree. Pick the one to keep, or say these are not the same project.');
    acts.push(rdAction('arrowR', 'Cloud → Local',
      `syncRow('to-local','${j(c.id)}','${j(c.name)}','${pj(l.path)}','${kind}')`,
      { primary: true, writes: 'local', title: 'Rename the local file so it matches the cloud project.' }));
    acts.push(rdAction('arrowL', 'Local → Cloud',
      `syncRow('to-cloud','${j(c.id)}','${j(l.name)}','${pj(l.path)}','${kind}')`,
      { writes: 'cloud', title: 'Rename the cloud project so it matches your local file.' }));
    acts.push(rdAction('notEqual', 'Not a match',
      `markNotMatch('${j(c.id)}','${pj(l.path)}','${j(c.name)}','${j(l.name)}')`,
      { quiet: true, title: 'Never pair these two again.' }));
  } else if (r.status === 'orphan' && c && !l) {
    icon = 'down';
    sentences.push(kind === 'sites'
      ? 'This cloud site has no matching folder on disk.'
      : 'This cloud project has nothing matching it on disk.');
    acts.push(rdAction('down', 'Download',
      `downloadThenMove('${j(c.id)}','${j(c.name)}')`,
      { primary: true, writes: 'local', title: 'Download the .esx from Ekahau Cloud, then move it into a site folder.' }));
    acts.push(rdAction('link', 'Link to a local file…',
      `openLinkPicker('cloud','${j(c.id)}','${j(c.name)}')`,
      { quiet: true, title: 'Pair this cloud project with a local .esx yourself.' }));
  } else if (r.status === 'orphan' && l && !c) {
    icon = 'up';
    sentences.push('This local file has nothing matching it in Ekahau Cloud.');
    acts.push(rdAction('up', 'Upload',
      `uploadFromLocal('${pj(l.path)}','${j(l.name)}')`,
      { primary: true, writes: 'cloud', title: 'Upload this .esx to Ekahau Cloud as a new project.' }));
    acts.push(rdAction('link', 'Link to a cloud project…',
      `openLinkPicker('local','${pj(l.path)}','${j(l.name)}')`,
      { quiet: true, title: 'Pair this local file with a cloud project yourself.' }));
  }

  /* A measured comparison outranks anything inferred from a date, so it speaks
     first and the download it contradicts is demoted rather than removed. */
  if (cmp) {
    tone = cmp.designDiffers ? 'rd-differs' : 'rd-same';
    icon = cmp.designDiffers ? 'notEqual' : 'check';
    /* Settled, and saying so. A comparison that came back identical in content
       *and* name is the end of the question, so the row states the finding
       rather than describing what was inspected - and the actions that no
       longer apply are not offered. */
    //: The comparison's own verdict - design, metadata and name all the
    //: same. Deriving it from two other fields called "renamed only"
    //: settled, and that is a pair whose rename still has to be applied.
    if (cmp.identical) {
      sentences.push('Exact match — the contents and the name are the same on both sides. Nothing to do.');
    } else if (cmp.summary) {
      sentences.push(cmp.summary);
    }
  } else if (stale === 'cloud_newer') {
    /* "what is the decision? Is that the last line where it says the cloud
       copy has a later date...?"

       He had to ask, and the sentence is why: it described a situation and
       stopped. "Not compared yet, so whether the design actually differs is
       unknown" states an open question without asking it, names no option and
       recommends nothing, while two buttons sat at the far end of the same
       line. So it asks the question and names the answer: the recommended
       action is the read-only one, because it is cheap and it settles the
       thing the row is actually uncertain about. */
    sentences.push(r.differenceKind === 'renamed'
      /* Already classified by the backend, so there is no question left to
         ask and asking one anyway would send him to compare something we
         have told him we know. */
      ? 'The cloud copy was renamed — that is what moved its date, and no '
        + 'design change was detected. Downloading brings the new name across.'
      /* Short, because it repeats down the whole filtered list and the button
         beside it is the rest of the sentence. Measured at his density: the
         long form put the same two lines of prose on seven consecutive rows,
         which is the noise this band exists to avoid. */
      : 'The cloud copy has a later date. A real change, or just a rename?');
  } else if (stale === 'local_newer') {
    sentences.push(r.differenceKind === 'renamed'
      ? 'Your local copy was renamed — that is what moved its date, and no '
        + 'design change was detected.'
      : 'Your local copy has a later date. A real change, or only the name?');
  }

  if (cmp && !cmp.designDiffers && cmp.nameState === 'internal_only' && c && c.name && l) {
    acts.push(rdAction('rename', 'Set the name inside the file to match',
      `fixInternalName('${pj(l.path)}','${j(c.name)}','${j(l.name || '')}','${j(c.id)}')`,
      { primary: true, writes: 'local',
        title: 'Renaming a file on disk does not change the project name stored inside it. This writes the cloud project’s name into your local .esx, and backs the file up first. Nothing on Ekahau Cloud changes.' }));
  }

  /* The staleness control keeps its own wording and its own reasoning - it is
     the one action here that deletes or replaces something. */
  const stalenessAction = stalenessBadgeHtml(r);

  /* Matched on name alone, both sides current: the overwrite that upgrades the
     pair to a proven one. It used to hang off the middle lane. */
  const _settled = !!(cmp && cmp.identical);
  if (!stale && !_settled && r.status === 'synced' && r.matchType === 'exact' && c && l) {
    acts.push(rdAction('down', 'Download over local',
      `verifyReplaceLocal('${j(c.id)}','${pj(l.path)}','${j(c.name)}',${Number(c.mtime) || 0},${Number(l.mtime) || 0})`,
      { quiet: true, writes: 'local',
        title: 'These matched on name alone. Taking the cloud copy over your local file makes them byte-identical, so the pair upgrades to Same file. Your current copy is kept in the backups folder.' }));
    if (!sentences.length) {
      sentences.push('Matched by name only — nothing has proved these are the same file.');
    }
  }

  /* A row with nothing to say gets no band at all, and that is the rule the
     whole list leans on: a second line means this one wants something.

     Comparing is offered on every pair, so adding it here unconditionally gave
     every in-sync row a band holding a warning icon, no sentence and one
     button - which is exactly the noise this band was built to remove. It
     lives in the row menu instead, where it is always reachable, and it joins
     the band only once the band exists for another reason. */
  /* Mid-action, and saying so on the row he is looking at rather than only in
     the ops deck in the corner. */
  const busy = rowIsBusy(r);
  if (busy) {
    //: Same three lanes as the settled band below, so the row does not shift
    //: sideways the moment he clicks something.
    return `<div class="row-detail rd-plain is-busy status-${r.status || ''}">`
      + `<span class="rd-lane cloud">`
      +   `<span class="rd-icon">${ic('swap')}</span>`
      +   `<span class="rd-text">${e(busy)}</span>`
      +   `<span class="rd-actions"><span class="rd-busy">Working</span></span>`
      + `</span>`
      + `<span class="rd-gut"></span>`
      + `<span class="rd-lane local"></span>`
      + `</div>`;
  }

  if (!sentences.length && !stalenessAction && !acts.length) return '';

  /* The recommended answer to the question the row just asked.

     A date difference that has not been compared is the one case where the
     read-only action is strictly better: it is cheap, it changes nothing, and
     it settles whether the other action is even wanted. Presenting it as an
     equal alternative to a download that overwrites his local file was the
     tool declining to have an opinion where it has one.

     Once the comparison exists, or the backend has already classified the
     difference as a rename, the question is answered and Re-check goes back to
     being the quiet one. */
  const asksToCompare = !!(c && l && stale && !cmp && r.differenceKind !== 'renamed');
  if (c && l) {
    acts.push(rdAction('swap', cmp ? 'Re-check' : 'Check what differs',
      `checkRealDifference('${j(c.id)}','${pj(l.path)}','${j(c.name || l.name || '')}')`,
      { primary: asksToCompare, quiet: !asksToCompare,
        title: 'Compare the two files’ contents and report what actually differs. Read-only — nothing is changed on either side.' }));
  }

  /* Order is the recommendation. When the read-only check is the advice it
     comes first, and the action that overwrites something follows it. */
  const actions = asksToCompare
    ? acts.join('') + stalenessAction
    : stalenessAction + acts.join('');

  /* The band lines up with the row it belongs to, and each action sits under
     the side it changes.

     "the blue buttons are all on the left hand side" - and one of them was
     `Set the name inside the file to match`, which writes the cloud project's
     name into his **local** .esx. Drawn under the Cloud column, it read as a
     cloud action; when it then failed on a local file permission, the error
     made no sense against the place the button was sitting. "I think that's
     exactly backwards."

     It was never a cloud lane - the band was one flex row spanning the whole
     width, so everything in it piled up at the left margin and the entire
     right half was empty. That is worse than a wrong label: it looks like a
     column and is not one, so it invites exactly the reading he gave it.

     Three lanes now, on the same widths as the row above (`flex: 1`, a fixed
     140px gutter, `flex: 1`). The sentence and anything read-only stay left,
     because a comparison changes nothing and has no side. Everything that
     writes is drawn beneath the side it writes to. */
  const split = _rdSplitBySide(actions);
  const left = split.cloud + split.neutral;

  return `<div class="row-detail ${tone}${stripe ? ' stripe' : ''} status-${r.status || ''}">`
    + `<span class="rd-lane cloud">`
    +   `<span class="rd-icon">${ic(icon)}</span>`
    +   `<span class="rd-text">${e(sentences.join(' '))}</span>`
    +   `<span class="rd-actions">${left}</span>`
    + `</span>`
    + `<span class="rd-gut"></span>`
    + `<span class="rd-lane local">`
    +   `<span class="rd-actions">${split.local}</span>`
    + `</span>`
    + `</div>`;
}
/* The action that is refused, drawn as itself: named, greyed, and carrying
   its own reason. It is not disabled in the HTML sense - a disabled button
   swallows the click, and the click is how he asks why. It is marked
   unavailable, and `_wireDisabledBulkReasons` turns the click into the
   explanation. */
function rdUnavailable(icon, label, why, writes) {
  //: A control that is unavailable still belongs in the lane it would write
  //: to. Moving when it becomes available would be worse than useless - he
  //: would have to find it twice.
  const side = writes === 'cloud' || writes === 'local' ? ` data-writes="${writes}"` : '';
  return `<button class="rd-btn is-disabled" aria-disabled="true"${side} title="${a(why)}">`
       + `${ic(icon)}<span>${label}</span></button>`;
}

//: And the one control that lifts it, so the key sits beside the lock.
function rdConfirmPair(r, unlocks) {
  return `<button class="rd-btn" title="${a('Say these two really are the same project. That promotes the pair to a match you made yourself, and ' + unlocks + ' becomes available. You can undo it from the badge in the middle column.')}" `
       + `onclick="event.stopPropagation();markManualMatch('${j(r.cloud.id)}','${pj(r.local.path)}','${j(r.cloud.name || '')}','${j(r.local.name || '')}')">`
       + `${ic('link')}<span>Confirm this pair</span></button>`;
}

function stalenessBadgeHtml(r) {
  const s = r.staleness;
  if (!s) return '';

  /* If he has already asked what really differs, that answer outranks
     everything below it - it is measured where the rest is inferred. It goes
     in the row rather than a tooltip, because evidence he has waited for
     should not need hovering to read. */
  const cmp = compareResultFor(r);
  /* The verdict and the actions used to be stacked into the middle column
     between two wide name columns, where his long project names leave a narrow
     lane - "you can see how we're jamming things into these lines". The pair
     identifies the row; the findings and the actions are *about* the row and
     get the full width underneath it. `rowDetailHtml` renders that band; what
     stays here is the short badge for the collapsed case. */
  /* The verdict is the detail row's own text now, in full. Repeating a
     short form inside the action group put "same design" right next to a
     sentence already saying so - visible only by rendering it. */
  const cmpHtml = '';
  /* The check control lives in the detail row now. Leaving a copy here as
     well put two of them side by side, one reading "Check" and one "Check what
     differs" - found by measuring the rendered row, not by reading this. */
  const checkBtn = '';

  /* "Newer" and "renamed" are different statements and used to share one
     label. A rename moves `history.modifiedAt`, so renaming a hundred cloud
     projects produced a hundred rows reading "Cloud newer" - the same words
     the tool uses for somebody having redesigned the thing. That is the
     reason the labels stopped being trusted: one of them was not true.

     The backend classifies the difference now (`differenceKind`), and the
     evidence is in the row at rest rather than in a tooltip. */
  const renamedOnly = r.differenceKind === 'renamed';

  if (s === 'cloud_newer') {
    if (canPullFromCloud(r)) {
      /* If the contents have been compared and found identical, offering
         "download" as the primary action contradicts the finding directly
         above it. The comparison is measured where the date is inferred, so it
         wins: the action is demoted to a quiet secondary. */
      /* Proven identical, name and all: there is nothing to download.

         It used to be demoted to "Download anyway", which he hit three times
         and asked the only sensible question about - "which of those things is
         right?". A quieter wrong option is still a wrong option, and "anyway"
         implies overriding advice nobody gave. A settled row says it is
         settled and offers Recheck. */
      const provenSame = cmp && !cmp.designDiffers;
      const settled = comparisonIsSettled(cmp);
      if (settled) return '';
      const label = provenSame
        ? 'Download anyway'
        : renamedOnly
          ? 'Cloud renamed · download'
          : 'Cloud newer · download';
      const why = renamedOnly
        ? 'The cloud copy was RENAMED, which is why its date moved - the name stored inside your local file is the old one. No design change was detected. Downloading brings the rename across and renames your local file to match. Your current copy is kept in the backups folder.'
        : 'The cloud copy was edited more recently and the names agree, so this is a real change rather than a rename. Downloading replaces your local one. Your current copy is kept in the backups folder.';
      /* Primary only once the question is settled. A date on its own does not
         say the design changed - it is the whole reason Check exists - so
         while nothing has been compared and the backend has not classified
         this as a rename, the emphasis belongs on the read-only action and
         this one is the alternative. Offering an overwrite as the
         recommendation on evidence we have said is inconclusive is the tool
         pushing him at the irreversible option. */
      const answered = renamedOnly || !!cmp;
      const weight = provenSame ? ' quiet is-demoted' : (answered ? ' primary' : ' quiet');
      return cmpHtml
        + `<button class="rd-btn${weight}${renamedOnly ? ' is-renamed' : ''}" data-writes="local" title="${a(provenSame ? 'The contents were compared and match. Downloading would replace your local file with an identical one. ' + why : why)}" onclick="event.stopPropagation();verifyReplaceLocal('${j(r.cloud.id)}','${pj(r.local.path)}','${j(r.cloud.name)}',${Number(r.cloud.mtime) || 0},${Number(r.local.mtime) || 0})">${ic('down')}<span>${label}</span></button>`
        + checkBtn;
    }
    /* Shown and unavailable, never absent - and the thing that lifts the
       refusal sits next to it rather than being described in a tooltip. */
    const noPull = 'The cloud copy was edited more recently, but these two were '
      + 'paired on name similarity rather than a proven match. Downloading over '
      + 'your local file is not offered here because it could overwrite a '
      + 'different project. Confirm the pair and it becomes available.';
    return `<span class="rd-note" title="Your cloud copy was edited more recently than the local one.">${ic('down')}<span>Cloud newer</span></span>`
      + rdUnavailable('down', 'Download over local', noPull, 'local')
      + rdConfirmPair(r, 'the download');
  }

  if (s === 'local_newer') {
    /* A status with no adjacent remedy reads as a broken control.

       He clicked "Local newer" expecting it to do something, then ticked the
       checkbox and pressed Sync and got nothing: "I can't click it to do
       anything... I thought we fixed that." The label was the app stating a
       difference and offering no way out.

       It is a real action now. `replace_cloud_project` landed in v2.104.6 with
       its server route and nothing called it, so this row kept saying "not
       built yet" about code that was sitting right there. It is built: upload,
       verify, then delete the old - in that order, because a delete that runs
       first turns a failed upload into a missing shared project, while a
       delete that runs last turns one into a duplicate that can be removed.

       It is offered only on a proven pair. Replacing the cloud copy deletes
       the old project and cloud deletes do not come back, so a name-only match
       gets the disabled control and an explanation instead. */
    if (canPushToCloud(r)) {
      /* What it will do, in the row, at rest - not only in the tooltip. The
         order is the safety: nothing is removed until the replacement is up
         and checked. */
      const plan = 'Uploads your local file as a new cloud project, checks it '
        + 'landed and is really your file, and only then removes the old cloud '
        + 'copy. If the upload fails nothing is deleted; if the delete fails '
        + 'you are told there are two and which one is good.';
      /* Same reasoning as the download, and more so: this one deletes the old
         cloud project. It is the recommendation once something has actually
         been compared, not on a date alone. */
      const weight = cmp ? ' primary' : ' quiet';
      return cmpHtml
        + `<button class="rd-btn${weight}" data-writes="cloud" title="${a(plan)}" onclick="event.stopPropagation();pushLocalOverCloud('${j(r.cloud.id)}','${pj(r.local.path)}','${j(r.local.name || '')}','${j(r.cloud.name || '')}','${j(r.matchType || '')}')">${ic('up')}<span>Local newer · replace cloud</span></button>`
        + checkBtn;
    }
    /* Only a guessed pairing reaches here now - same site code, or similar
       words. The two names are not the same, so there is nothing to confirm
       against and Link is the honest route. */
    /* Only a guessed pairing reaches here - same site code, or similar
       wording. Replacing the cloud copy deletes the old one and that does not
       come back, so it stays refused; but the control that lifts the refusal
       sits right here rather than being described in a tooltip. The old text
       pointed at a "Link button" that is only ever drawn on an *unpaired* row,
       so on this row it named a control that did not exist. */
    /* Two different reasons reach here and they have different remedies, so
       the row must not offer the wrong one. Confirming the pair lifts a
       guessed pairing; it does nothing about a project belonging to somebody
       else, and offering it there would send him round a loop that ends in
       the 403 anyway. */
    const notMine = ownershipBlock(r.cloud);
    if (notMine) {
      return `<span class="rd-note" title="Your local copy was edited more recently than the cloud one.">${ic('up')}<span>Local newer</span></span>`
        + rdUnavailable('arrowL', 'Local → Cloud',
            notMine + ' Replacing it would delete their project, which Ekahau '
            + 'refuses. Your local copy is yours to keep or rename.', 'cloud');
    }
    const unproven = 'Your local copy is newer, but these two were paired by '
      + 'guesswork - a shared site code or similar wording, not the same name '
      + 'and not Ekahau\'s id. Replacing the cloud copy deletes the old one and '
      + 'that cannot be undone, so it is not offered until you confirm the pair. '
      + 'Confirm this pair, or Link them yourself, and it becomes available.';
    return `<span class="rd-note" title="Your local copy was edited more recently than the cloud one.">${ic('up')}<span>Local newer</span></span>`
      + rdUnavailable('arrowL', 'Local → Cloud', unproven, 'cloud')
      + rdConfirmPair(r, 'replacing the cloud copy');
  }
  return '';
}


function gutCell(r) {
  /* The verdict, and nothing else.

     "the new process flow has a little Check Link in the center column, which
     by the way is getting rather crowded now."

     He was looking at a lane a few characters wide between two long names,
     with up to four controls stacked into it - so a row that needed a decision
     stood three times the height of the ones around it, and the list had a
     ragged edge down its middle that no amount of colour was going to fix.

     Every action moved to the row underneath, which is full width and already
     existed for exactly this purpose. What is left here is the one thing this
     column is for: which kind of match WD thinks this is. One line, every row,
     every state. */
  const kind = r.kind || currentTab;
  if (r.status === 'mismatch' || r.status === 'synced') {
    return `<div class="lr-gut">${matchBadgeHtml(r, kind)}</div>`;
  }
  const side = r.cloud ? 'cloud' : 'local';
  const label = (kind === 'sites')
    ? (r.cloud ? 'Cloud site only' : 'Local folder only')
    : (r.cloud ? 'Cloud only' : 'Local only');
  return `<div class="lr-gut"><span class="match-badge mb-orphan" title="${a(
      r.cloud
        ? 'This exists in Ekahau Cloud with nothing matching it on disk.'
        : 'This exists on disk with nothing matching it in Ekahau Cloud.'
    )}"><span class="mb-dot"></span>${label}</span></div>`;
}

/* Where this project lives, on this side.

   Only the Flat tab shows it, and only because that is what the Flat tab is
   *for*: it pairs a cloud project with a local .esx wherever either one
   happens to be, so the place each one sits is the question rather than a
   detail. On the Tree tab the answer is the row above and repeating it would
   be noise.

   Two icons rather than one word, because the two sides mean different things
   and he has to be able to see that they disagree: a cloud project belongs to
   a **site**, a local file sits in a **folder**. */
/* Do the two sides agree about where this project lives?

   His projects are named after their site, so a tag repeating it is the same
   crowding in a smaller font. What Flat can say that the tree cannot is when
   the two *disagree* - a .esx in the wrong folder, a project assigned to the
   wrong site - so that is when the location is worth the row.

   **The tab decides this, not the row.** It used to read `r.kind`, and
   `renderTreeChildren` sets `kind: 'projects'` on every child so that the row
   menu offers project actions rather than site actions. So the Flat-only tag
   rendered on every row of the Tree as well, and it had nothing true to say
   there: `build_sites_data` gives a tree child a `folder` and no `siteName`,
   because on the Tree the site *is* the row above it. Every child therefore
   compared '' against its folder, disagreed, and drew both halves - the folder
   name again on the local side, and on the cloud side the words **no site**,
   underneath the very site it is filed in. "they weren't assigned to a site on
   the cloud and yet they're listed underneath the site on the cloud side."

   A project genuinely filed under no site still says so, and says it in the
   place that can act on it: the `Not assigned` tag on its name, the
   `Assign to "<site>"` item in its menu, and the auto-assign banner above the
   list. Those are about assignment. This tag was about location, and on the
   Tree the location is not in question. */
function locationDiffers(r) {
  if (currentTab !== 'projects') return false;
  if (!r.cloud || !r.local) return false;
  const site = String((r.cloud && r.cloud.siteName) || '').trim().toLowerCase();
  const folder = String((r.local && r.local.folder) || '').trim().toLowerCase();
  return site !== folder;
}

function locationHtml(where, side) {
  const name = String(where || '').trim();
  if (!name) {
    return `<span class="cell-where is-none" title="${
      side === 'cloud' ? 'Not assigned to a site in Ekahau.'
                       : 'Loose in the project folder, not inside a site folder.'
    }">${side === 'cloud' ? 'no site' : 'no folder'}</span>`;
  }
  return `<span class="cell-where" title="${a(
    side === 'cloud' ? 'The Ekahau site this project is assigned to'
                     : 'The folder this .esx sits in')}">${
    ic(side === 'cloud' ? 'eye' : 'folder')}${e(name)}</span>`;
}

function cloudCell(r, localCodes) {
  const isSites = (r.kind || currentTab) === 'sites';
  const kindAttr = r.kind || currentTab;

  const chkKey = (r.cloudCheckKey && r.cloud) ? r.cloudCheckKey : r.key;
  const chk = r.noCheckbox ? '' : `<input type="checkbox" class="rowchk" data-k="${e(chkKey)}" ${selected.has(chkKey) ? 'checked' : ''}>`;
  const indentCls = r.indent ? ' child-row' : '';
  const chevron = r.toggle
    ? `<button class="tree-chevron${r.toggle.open ? ' open' : ''}" onclick="event.stopPropagation();toggleFolder('${j(r.toggle.key)}')" title="${r.toggle.open ? 'Collapse this site' : 'Expand this site'}" aria-expanded="${r.toggle.open}">${ic('chevron')}</button>`
    : '';
  if (!r.cloud) {
    if (isSites) {
      return `<div class="lr-cell cloud empty${indentCls}">${chevron}<button class="ghost-add" title="Create a cloud site from this folder" onclick="createFromLocal('${j(r.local.name)}')">${ic('plus')}<span>Cloud site</span></button></div>`;
    }
    return `<div class="lr-cell cloud empty${indentCls}">${chevron}<button class="ghost-add" title="Upload .esx to Ekahau Cloud" onclick="uploadFromLocal('${pj(r.local.path)}','${j(r.local.name)}')">${ic('up')}<span>Upload</span></button></div>`;
  }
  const c = r.cloud, isMis = r.status === 'mismatch', thing = isSites ? 'cloud site' : 'cloud project';
  const me = ((data && data.currentUser) || '').toLowerCase();
  const owner = (c.owner || '').toLowerCase();
  const createdBy = (c.createdBy || '').toLowerCase();

  const ownerTitle = createdBy && createdBy !== owner
    ? `Current owner (from Ekahau share list). Originally created by ${createdBy}.`
    : 'Current owner (from Ekahau share list)';
  /* Only when it is not him.

     This rendered on every row that had an owner, and every project he owns
     has one - so a hundred rows each carried the same thirty-character address
     of the person reading them, which at 1366 pushed the file name onto a
     second line. An owner tag is worth the space when the answer is somebody
     else; when the answer is "you", it is the most predictable string on the
     page. The Owner toggle above the list is how he asks the other question. */
  const ownerHtml = (!isSites && owner && owner !== me)
    ? ` <span class="owner-tag other" title="${a(ownerTitle)}">${e(owner)}</span>`
    : '';

  const typeHtml = (!isSites && c.projectType)
    ? ` <span class="ptype-tag pt-${e(c.projectType.toLowerCase().replace(/\s+/g, '-'))}" title="Project type (from Ekahau)">${e(c.projectType)}</span>`
    : '';

  const planHtml = (!isSites && c.planType)
    ? ` <span class="ptype-tag pt-plan" title="Ekahau also has a ${e(c.planType)} dataset under this same name — matched by name, not a guaranteed link">+ ${e(c.planType)}</span>`
    : '';
  const shared = (!isSites && c.sharedWith) || [];
  const sharedHtml = shared.length
    ? ` <span class="shared-tag" title="Also shared with: ${a(shared.join(', '))}">${shared.length} shared</span>`
    : '';

  const iOwnCloud = owner && me && owner === me;
  const unassignedHtml = (!isSites && c.unassigned && iOwnCloud)
    ? ` <span class="ptype-tag pt-unassigned" title="This cloud project has no site parent in Ekahau. Assign it so it lives inside the right site.">Not assigned</span>`
    : '';
  const nameHtml = (isMis ? charDiff(c.name, r.local.name).a : e(c.name)) + (isSites ? '' : '.esx') + typeHtml + planHtml + unassignedHtml + ownerHtml + sharedHtml + dupHintFor(c.id);
  const dup = r.status === 'orphan' && c.code && localCodes.has(c.code);

  /* On a site row the meta is the digest: what is inside, and how much of it
     wants him. That is the whole point of closing the sites by default - the
     line has to answer "is there anything for me in here" without being
     opened. On a file row it stays the date, and it stays put: it used to fade
     out to make room for the hover buttons. */
  /* On Flat, where the project lives is the point of the view, so it is
     shown; on Tree the site is the row above. */
  const where = locationDiffers(r) ? locationHtml(c.siteName, 'cloud') : '';
  const meta = isSites ? siteDigestHtml(r)
    : `${where}<span class="cell-meta">${e(c.meta || '')}</span>`;

  /* Everything below that writes to Ekahau is refused up front on a project
     somebody else owns. `Check what differs` is not - it downloads a copy and
     compares it, and reading someone's project is exactly what being shared
     it allows. */
  const notMine = isSites ? '' : ownershipBlock(c);
  const menu = rowMenu([
    isSites && (c.datasets && c.datasets.length)
      ? menuItem('eye', 'View the projects in this site', `openCloudPeek('${j(c.id)}','${j(c.name)}')`,
          { title: `${c.datasets.length} project${c.datasets.length > 1 ? 's' : ''} in Ekahau Cloud` })
      : '',
    (!isSites && c.unassigned && r.parentSiteId)
      ? menuItem('plus', `Assign to “${e(r.parentSiteName || '')}”`,
          `assignOrphanToSite('${j(c.id)}','${j(r.parentSiteId)}','${j(c.name)}','${j(r.parentSiteName || '')}')`,
          { blocked: notMine })
      : '',
    !isSites ? menuItem('share', `Sharing…${(c.sharedWith || []).length ? ` (${(c.sharedWith || []).length})` : ''}`,
          `openManageShares('${j(c.id)}','${j(c.name)}')`,
          { title: 'Manage who this cloud project is shared with', blocked: notMine }) : '',
    !isSites ? menuItem('move', 'Move to a site…', `startMoveToSite('${j(c.id)}','${j(c.name)}')`,
          { blocked: notMine }) : '',
    (!isSites && r.local) ? menuItem('swap', 'Check what differs…',
        `checkRealDifference('${j(c.id)}','${pj(r.local.path)}','${j(c.name || '')}')`,
        { title: 'Compare this against the local file and report what actually differs. Read-only.' }) : '',
    menuItem('rename', `Rename this ${thing}…`, `startRename('cloud','${j(c.id)}','${j(c.name)}','${kindAttr}')`,
      { blocked: notMine }),
    menuItem('trash', `Delete this ${thing}`, `startDelete('cloud','${j(c.id)}','${j(c.name)}',false,'${kindAttr}')`,
      { danger: true, title: 'A cloud delete cannot be undone.', blocked: notMine }),
  ], `Actions for this ${thing}`);

  return `<div class="lr-cell cloud${dup ? ' dup' : ''}${indentCls}"${dup ? ` title="A local ${isSites ? 'folder' : '.esx'} shares code ${a(c.code)} — likely the same place"` : ''}>`
    + `${chevron}${chk}<span class="cell-name">${nameHtml}</span>${meta}${menu}</div>`;
}

function localCell(r, cloudCodes) {
  const isSites = (r.kind || currentTab) === 'sites';
  const kindAttr = r.kind || currentTab;

  const chkKey = (r.localCheckKey && r.local) ? r.localCheckKey : r.key;
  const chk = r.noCheckbox ? '' : `<input type="checkbox" class="rowchk" data-k="${e(chkKey)}" ${selected.has(chkKey) ? 'checked' : ''}>`;
  const indentCls = r.indent ? ' child-row' : '';
  if (!r.local) {
    return isSites
      ? `<div class="lr-cell local empty${indentCls}"><button class="ghost-add" title="Create a matching local folder" onclick="createLocalFolder('${j(r.cloud.name)}')">${ic('plus')}<span>Local folder</span></button></div>`
      : `<div class="lr-cell local empty${indentCls}"></div>`;
  }
  const l = r.local, isMis = r.status === 'mismatch', thing = isSites ? 'local folder' : '.esx file';
  const me = ((data && data.currentUser) || '').toLowerCase();
  const owner = (l.owner || '').toLowerCase();

  const localIsOther = owner && owner.indexOf('@') > -1 && owner !== me;
  //: Same reasoning as the cloud side: his own name on every row says nothing.
  const ownerHtml = (!isSites && localIsOther)
    ? ` <span class="owner-tag other" title="Author (from project.history.createdBy)">${e(owner)}</span>`
    : '';

  const localTypeHtml = (!isSites && l.projectType)
    ? ` <span class="ptype-tag pt-${e(l.projectType.toLowerCase().replace(/\s+/g, '-'))}" title="Project type (detected from .esx contents)">${e(l.projectType)}</span>`
    : '';
  const nameHtml = (isMis ? charDiff(r.cloud.name, l.name).b : e(l.name)) + (l.isDir ? '' : '.esx') + localTypeHtml + ownerHtml + dupHintFor(l.path);
  const dup = r.status === 'orphan' && l.code && cloudCodes.has(l.code);
  const hasContents = isSites && l.src && l.src.total > 0;
  const flagged = l.name.charAt(0) === '!';
  const srcUI = hasContents ? previewBadge(l) : '';
  const where = locationDiffers(r) ? locationHtml(l.folder, 'local') : '';
  const meta = `${where}<span class="cell-meta">${e(l.meta || '')}</span>`;

  const menu = rowMenu([
    menuItem('folder', `Show in ${navigator.platform.indexOf('Mac') >= 0 ? 'Finder' : 'Explorer'}`, `revealInExplorer('${pj(l.path)}')`),
    isSites ? menuItem('flag', flagged ? 'Remove the review flag' : 'Flag this folder for review',
        `flagReview('${pj(l.path)}','${j(l.name)}')`,
        { title: flagged ? 'Removes the ! prefix' : 'Adds a ! prefix so it sorts to the top here and in Explorer' }) : '',
    (!isSites && !l.isDir) ? menuItem('move', 'Move to another site folder…',
        `startMoveLocalToSite('${pj(l.path)}','${j(l.name)}')`) : '',
    isSites ? menuItem('merge', 'Merge into another folder…', `startMerge('${pj(l.path)}','${j(l.name)}')`) : '',
    menuItem('rename', `Rename this ${thing}…`, `startRename('local','${pj(l.path)}','${j(l.name)}','${kindAttr}')`),
    menuItem('trash', `Delete this ${thing}${isSites ? ' and its contents' : ''}`,
      `startDelete('local','${pj(l.path)}','${j(l.name)}',${l.isDir},'${kindAttr}')`,
      { danger: true, title: 'A local delete can be undone by downloading the cloud copy again.' }),
  ], `Actions for this ${thing}`);

  return `<div class="lr-cell local${dup ? ' dup' : ''}${indentCls}"${dup ? ` title="A cloud ${isSites ? 'site' : 'project'} shares code ${a(l.code)} — likely the same place"` : ''}>`
    + `${chk}<span class="cell-name">${nameHtml}</span>${srcUI}${meta}${menu}</div>`;
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
  return `<button class="${cls}" title="${a(tip)}" onclick="event.stopPropagation();openPeek('${pj(l.path)}')">&#128065;<span class="ib-label">Peek</span></button>`;
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

async function markNotMatch(cloudId, localPath, cloudName, localName, opts) {
  /* `opts.silent` is for "None of these", which is this call five times over.
     It suppresses the asking and the reporting - never the work - so the batch
     can ask once and report once instead of raising five dialogs and five full
     reloads. The request, the error handling and the result are the same. */
  const quiet = !!(opts && opts.silent);
  if (!quiet && !confirm(`Mark as NOT a match?\n\nCloud:  ${cloudName}\nLocal:  ${localName}\n\nThey'll be split into orphans and never auto-paired again. You can undo this from the menu → Manage Not-a-Match.`)) return;
  //: After the question, never before it.
  if (!quiet) _setRowBusy(cloudId, localPath, 'Splitting these two apart…');
  try {
    const r = await pyApi('mark_not_match', cloudId, localPath, cloudName, localName);
    if (r && r.error) { toast(r.error, 'error'); return; }
    if (quiet) return;
    toast('Marked as not a match', 'success');
    refreshData();
  } catch (e) {
    toast('Failed: ' + e.message, 'error');
  } finally {
    if (!quiet) _setRowBusy(cloudId, localPath, null);
  }
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
  _setRowBusy(cloudId, localPath, 'Linking these two…');
  try {
    const r = await pyApi('mark_manual_match', cloudId, localPath, cloudName || '', localName || '');
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast('Linked', 'success');
    refreshData();
  } catch (e) {
    toast('Link failed: ' + e.message, 'error');
  } finally {
    /* `finally`, not the success path: a mark an action can forget to clear
       is the stuck spinner this mechanism exists to prevent. */
    _setRowBusy(cloudId, localPath, null);
  }
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
  document.getElementById('shareRole').value = 'READ_USER';
  _shareChipsReset();
  _shareLoadRecent();
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

/* ---- Recipients: chips, and the people he has shared with before --------

   Two things he asked for, and they are the same problem twice. He was
   retyping colleagues' addresses from memory every time, and he could only
   enter one at a time - so sharing a project with three people meant typing
   three addresses he had to remember, one after another.

   The API always took an array. The limit was this form.

   Addresses become chips rather than staying as text, so removing the one he
   mistyped does not mean editing a string and re-checking the other four. */

let _shareChips = [];
let _shareKnown = [];        // remembered recipients, most recent first
let _shareSuggestIndex = -1;

/* Comma, semicolon, whitespace, newline - and `Name <a@example.com>`, because
   pasting from a mail client is a normal thing to do. Mirrors
   tools/share_recipients.py; the server splits again and is the authority. */
function _shareSplit(text) {
  if (!text) return [];
  const cleaned = String(text).replace(/[^<>]*<([^>]+)>/g, '$1 ');
  const out = [];
  cleaned.split(/[,;\s]+/).forEach(function (chunk) {
    const one = chunk.trim().replace(/^[<>,;]+|[<>,;]+$/g, '').toLowerCase();
    if (one && out.indexOf(one) === -1) out.push(one);
  });
  return out;
}

function _shareLooksLikeEmail(value) {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(value || '').trim());
}

function _shareChipsAdd(text) {
  let added = false;
  _shareSplit(text).forEach(function (one) {
    if (_shareChips.some(function (c) { return c.email === one; })) return;
    _shareChips.push({ email: one, valid: _shareLooksLikeEmail(one) });
    added = true;
  });
  if (added) _shareChipsRender();
  return added;
}

function _shareChipRemove(email) {
  _shareChips = _shareChips.filter(function (c) { return c.email !== email; });
  _shareChipsRender();
  const el = document.getElementById('shareEmail');
  if (el) el.focus();
}

function _shareChipsReset() {
  _shareChips = [];
  _shareSuggestIndex = -1;
  _shareChipsRender();
  const el = document.getElementById('shareEmail');
  if (el) el.value = '';
  _shareSuggestHide();
}

function _shareChipsRender() {
  const host = document.getElementById('shareChips');
  if (!host) return;
  host.innerHTML = _shareChips.map(function (c) {
    // A malformed entry is marked rather than refused. Rejecting the whole
    // field because one address is wrong throws away the four that were right.
    return '<span class="share-chip' + (c.valid ? '' : ' is-bad') + '"'
      + (c.valid ? '' : ' title="That does not look like an email address"')
      + '>' + WD.esc(c.email)
      + '<button type="button" class="share-chip-x" aria-label="Remove '
      + WD.esc(c.email) + '" onclick="event.stopPropagation();_shareChipRemove('
      + JSON.stringify(c.email).replace(/"/g, '&quot;') + ')">&times;</button>'
      + '</span>';
  }).join('');
}

/* ---- typing ------------------------------------------------------------ */

function _shareEmailInput(e) {
  const el = e.target;
  // A separator means "that one is finished" - the same gesture as Enter.
  if (/[,;\s]/.test(el.value)) {
    const trailing = /[,;\s]$/.test(el.value);
    const parts = _shareSplit(el.value);
    const keep = trailing ? '' : (parts.pop() || '');
    if (parts.length) _shareChipsAdd(parts.join(','));
    el.value = keep;
  }
  _shareSuggestShow(el.value);
}

function _shareEmailPaste(e) {
  // Belt and braces. This handler is an optimisation, not the mechanism: a
  // paste also fires `input`, and _shareEmailInput splits on the same
  // separators - so if the clipboard is unreadable here for any reason, the
  // default paste lands in the field and the splitter picks it up anyway.
  let text = '';
  try {
    const data = e.clipboardData || window.clipboardData;
    text = (data && data.getData('text')) || '';
  } catch (err) {
    text = '';
  }
  if (!text || !/[,;\s]/.test(text)) return;     // a single address: let it through
  e.preventDefault();
  _shareChipsAdd(text);
  e.target.value = '';
  _shareSuggestHide();
}

function _shareEmailKey(e) {
  const el = e.target;
  const open = !document.getElementById('shareSuggest').hidden;

  if (open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
    e.preventDefault();
    _shareSuggestMove(e.key === 'ArrowDown' ? 1 : -1);
    return;
  }
  if (e.key === 'Escape' && open) { e.preventDefault(); _shareSuggestHide(); return; }

  if (e.key === 'Enter') {
    e.preventDefault();
    const picked = _shareSuggestCurrent();
    if (picked) { _sharePick(picked); return; }
    if (el.value.trim()) { _shareChipsAdd(el.value); el.value = ''; _shareSuggestHide(); return; }
    _shareAdd();
    return;
  }
  // Backspace on an empty field takes back the last chip, which is what every
  // other chip field does and therefore what the fingers expect.
  if (e.key === 'Backspace' && !el.value && _shareChips.length) {
    e.preventDefault();
    _shareChipRemove(_shareChips[_shareChips.length - 1].email);
  }
}

function _shareEmailBlur() {
  // Delayed, or clicking a suggestion would blur the field and close the list
  // before the click ever lands.
  setTimeout(function () {
    const el = document.getElementById('shareEmail');
    if (el && el.value.trim()) { _shareChipsAdd(el.value); el.value = ''; }
    _shareSuggestHide();
  }, 160);
}

/* ---- suggestions ------------------------------------------------------- */

function _shareSuggestMatches(query) {
  const q = String(query || '').trim().toLowerCase();
  const chosen = _shareChips.map(function (c) { return c.email; });
  return _shareKnown
    .filter(function (r) { return chosen.indexOf(r.email) === -1; })
    .filter(function (r) { return !q || r.email.indexOf(q) !== -1; })
    .slice(0, 6);
}

function _shareSuggestShow(query) {
  const box = document.getElementById('shareSuggest');
  if (!box) return;
  const matches = _shareSuggestMatches(query);
  // With nothing typed the list is only offered once he has a history worth
  // offering; suggesting an empty box on every focus is just noise.
  if (!matches.length) { _shareSuggestHide(); return; }
  _shareSuggestIndex = -1;
  box.innerHTML = matches.map(function (r, i) {
    return '<button type="button" class="share-suggest-item" data-i="' + i + '"'
      + ' onmousedown="event.preventDefault()"'
      + ' onclick="_sharePick(' + JSON.stringify(r.email).replace(/"/g, '&quot;') + ')">'
      + WD.esc(r.email) + '</button>';
  }).join('');
  box.hidden = false;
}

function _shareSuggestHide() {
  const box = document.getElementById('shareSuggest');
  if (box) { box.hidden = true; _shareSuggestIndex = -1; }
}

function _shareSuggestMove(step) {
  const box = document.getElementById('shareSuggest');
  const items = box ? [].slice.call(box.querySelectorAll('.share-suggest-item')) : [];
  if (!items.length) return;
  _shareSuggestIndex = (_shareSuggestIndex + step + items.length) % items.length;
  items.forEach(function (el, i) {
    el.classList.toggle('is-active', i === _shareSuggestIndex);
  });
}

function _shareSuggestCurrent() {
  const box = document.getElementById('shareSuggest');
  if (!box || box.hidden || _shareSuggestIndex < 0) return null;
  const items = [].slice.call(box.querySelectorAll('.share-suggest-item'));
  const el = items[_shareSuggestIndex];
  return el ? el.textContent.trim() : null;
}

function _sharePick(email) {
  _shareChipsAdd(email);
  const el = document.getElementById('shareEmail');
  if (el) { el.value = ''; el.focus(); }
  _shareSuggestHide();
  _shareRecentRender();
}

/* ---- the remembered list ----------------------------------------------- */

async function _shareLoadRecent() {
  try {
    const r = await pyApi('recent_recipients');
    _shareKnown = (r && r.recipients) || [];
  } catch (err) {
    _shareKnown = [];       // a convenience feature never breaks the panel
  }
  _shareRecentRender();
}

function _shareRecentRender() {
  const host = document.getElementById('shareRecent');
  if (!host) return;
  const chosen = _shareChips.map(function (c) { return c.email; });
  const offer = _shareKnown
    .filter(function (r) { return chosen.indexOf(r.email) === -1; })
    .slice(0, 8);
  if (!offer.length) { host.hidden = true; host.innerHTML = ''; return; }
  host.hidden = false;
  host.innerHTML =
    '<div class="share-recent-label">Recent</div>'
    + offer.map(function (r) {
      const safe = JSON.stringify(r.email).replace(/"/g, '&quot;');
      return '<span class="share-recent-item">'
        + '<button type="button" class="share-recent-pick" onclick="_sharePick(' + safe + ')">'
        + WD.esc(r.email) + '</button>'
        + '<button type="button" class="share-recent-x" title="Forget '
        + WD.esc(r.email) + '" aria-label="Forget ' + WD.esc(r.email)
        + '" onclick="_shareForget(' + safe + ')">&times;</button>'
        + '</span>';
    }).join('');
}

async function _shareForget(email) {
  try {
    const r = await pyApi('forget_recipient', email);
    if (r && r.error) { toast(r.error, 'error'); return; }
    _shareKnown = _shareKnown.filter(function (x) { return x.email !== email; });
    _shareRecentRender();
    _shareSuggestHide();
  } catch (err) {
    toast('Could not forget that address', 'error');
  }
}

async function _shareAdd() {
  const ctx = _shareCtx;
  if (!ctx) return;
  const emailEl = document.getElementById('shareEmail');
  const roleEl = document.getElementById('shareRole');
  const role = roleEl.value || 'READ_USER';
  const isBulk = !!(ctx.bulkProjectIds && ctx.bulkProjectIds.length);

  // Anything still half-typed counts. Pressing Add with text in the box and
  // meaning "not that one" is not a thing anybody does.
  if (emailEl.value.trim()) { _shareChipsAdd(emailEl.value); emailEl.value = ''; }
  _shareSuggestHide();

  const bad = _shareChips.filter(function (c) { return !c.valid; });
  if (bad.length) {
    toast(bad.length === 1
      ? bad[0].email + ' is not a valid email address'
      : bad.length + ' entries are not valid email addresses', 'error');
    emailEl.focus();
    return;
  }

  let emails = _shareChips.map(function (c) { return c.email; });
  if (!emails.length) {
    toast('Enter a valid email address', 'error');
    emailEl.focus();
    return;
  }

  // Someone already on the project is dropped rather than sent, and said so -
  // but only the ones that are, so four new people still go through.
  if (!isBulk) {
    const have = (ctx.users || []).map(function (u) {
      return (u.username || '').toLowerCase();
    });
    const already = emails.filter(function (e) { return have.indexOf(e) !== -1; });
    emails = emails.filter(function (e) { return have.indexOf(e) === -1; });
    if (already.length) {
      toast(already.join(', ') + (already.length === 1 ? ' already has' : ' already have')
        + ' access', 'info');
    }
    if (!emails.length) { _shareChipsReset(); return; }
  }

  emailEl.disabled = true; roleEl.disabled = true;
  try {
    let r;
    if (isBulk) {
      r = await pyApi('bulk_share', ctx.bulkProjectIds, emails, role, false, null, '', 'READ_USER');
    } else {
      r = await pyApi('add_shares', ctx.projectId, emails, role);
    }
    if (r && r.error) { toast(r.error, 'error'); return; }

    if (isBulk) {
      const n = r.ownedCount || 0;
      const skipped = (r.skipped || []).length;
      const who = _shareNameList(r.emailsAdded || emails);
      toast(`Shared with ${who} on ${n} project${n === 1 ? '' : 's'}`
            + (skipped ? ` (${skipped} skipped — not owner)` : ''), 'success');
      _shareChipsReset();
    } else {
      // Per recipient, because the request is one call but the outcome is not
      // one answer. Saying "shared" over a list where one address bounced is
      // the kind of false report that gets found out a week later.
      const results = r.results || [];
      const ok = results.filter(function (x) { return x.ok; }).map(function (x) { return x.email; });
      const failed = results.filter(function (x) { return !x.ok; });
      if (ok.length) toast('Shared with ' + _shareNameList(ok), 'success');
      failed.forEach(function (x) {
        toast(x.email + ' — ' + (x.message || 'could not be added'), 'error');
      });
      if (!ok.length && !failed.length) toast('Shared', 'success');

      // Keep the ones that did not work so he can fix a typo in place.
      _shareChips = failed.map(function (x) { return { email: x.email, valid: true }; });
      _shareChipsRender();
      emailEl.value = '';
      await _shareRefresh();
    }

    await _shareLoadRecent();
    _scheduleOpRefresh();
  } catch (err) {
    toast('Add failed: ' + err.message, 'error');
  } finally {
    emailEl.disabled = false; roleEl.disabled = false;
    emailEl.focus();
  }
}

function _shareNameList(list) {
  const items = (list || []).slice();
  if (items.length <= 1) return items[0] || '';
  if (items.length === 2) return items[0] + ' and ' + items[1];
  return items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1];
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

function staleWhen(ts) {
  if (!ts) return 'date unknown';
  return new Date(ts * 1000).toLocaleString(undefined,
    { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
}

/* Download the cloud copy over the local file.

   The confirm names the file and both edit times, because "are you sure" on
   its own does not tell anyone whether they are about to lose something. Those
   times are Ekahau's own, read from project.json inside each .esx - not the
   file dates - so a copy, a restore or an antivirus touch cannot make the
   local file look newer than it is. */
async function verifyReplaceLocal(cloudId, localPath, cloudName, cloudMtime, localMtime) {
  const fileName = String(localPath).split(/[\\/]/).pop() || localPath;
  const lines = [
    `Download the cloud copy of "${cloudName}" over your local file?`,
    '',
    `Local   ${fileName}`,
    `        last edited ${staleWhen(localMtime)}`,
    `Cloud   last edited ${staleWhen(cloudMtime)}`,
    '',
    'Your current local file is kept in the backups folder as a .previous- copy, so this can be undone.',
    'If your local copy turns out to be the newer one, nothing is changed.',
  ];
  if (!confirm(lines.join('\n'))) return;

  /* After the question, never before it: marking the row busy above the
     confirm left it saying "Working" over an action he had just declined. */
  _setRowBusy(cloudId, localPath, 'Taking the cloud copy over your local file…');

  const { promise } = opEnqueue({
    title: `Downloading "${cloudName}" over local`,
    type: 'verify', pollBackend: false, undoable: false,
    run: async () => {
      const r = await pyApi('verify_replace_local', cloudId, localPath);
      if (r && r.error) {
        _markVerifyFailed(cloudId, localPath);
        if (r.error === 'local_newer') {
          throw new Error('Not downloaded — your local copy is the newer one (' + (r.message || 'it would have been overwritten') + ')');
        }
        throw new Error(r.error);
      }
      // The badge goes when the refresh re-reads both sides; clearing the
      // stored row first means the answer to "did that work" is not waiting on
      // a round trip to Ekahau.
      _clearStaleness(cloudId);
      _scheduleOpRefresh();
      const backup = (r && r.backup) ? String(r.backup).split(/[\\/]/).pop() : '';
      if (backup) toast('Local file updated — previous copy kept as ' + backup, 'success');
      return r;
    },
  });

  /* Taking the cloud copy changes what a comparison would say about this pair,
     so the pair is re-evaluated and the row drawn from that - the same
     contract the internal-name fix has. "I shouldn't have to recheck twice." */
  promise.then(() => settlePair(cloudId, localPath))
         .catch(() => _setRowBusy(cloudId, localPath, null));
}
window.verifyReplaceLocal = verifyReplaceLocal;

function _clearStaleness(cloudId) {
  Object.keys(rowData).forEach(k => {
    const d = rowData[k];
    if (d && d.cloudId === cloudId && d.staleness) d.staleness = null;
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

/* Merge rule and live-refresh interval: one store, not two.

   These used to live in localStorage while Suite Settings read and wrote the
   same two keys in settings.json. Nothing connected the pair, so the Settings
   page showed a value that was not in force and saving there changed nothing —
   the control looked like it worked and did not. They are server-side now, and
   this file is the only thing that reads them.

   The old browser copy is the value actually in effect on this machine, so on
   first run it wins and is written through to the server; the local key is only
   deleted once that write has succeeded. Letting the server default win instead
   would quietly undo a deliberate choice — someone who set "skip" would find
   "ask" back. */
const MERGE_RULES = ['ask', 'newer', 'both', 'skip'];
const LEGACY_MERGE_KEY = 'wd-merge-rule';
const LEGACY_LIVE_MS_KEY = 'wd-live-ms';

let _mergeRule = 'ask';
let _liveMs = 30000;

function mergeRule() { return _mergeRule; }

function setMergeRule(v) {
  if (MERGE_RULES.indexOf(v) === -1) return;
  _mergeRule = v;
  _persistCloudPref({ merge_rule: v });
}

function setLiveMs(ms) {
  const n = parseInt(ms, 10);
  if (!(n > 0)) return;
  _liveMs = n;
  _persistCloudPref({ live_interval_ms: n });
}

function _persistCloudPref(patch) {
  if (!window.WD || !WD.api) return Promise.resolve(false);
  return WD.api('settings/update', { patch: { cloud: patch } })
    .then(r => !!(r && r.ok))
    .catch(() => false);
}

function _readLegacy(key) {
  try { return localStorage.getItem(key); } catch (e) { return null; }
}

/* Read both prefs before the first refresh runs, migrating anything still in
   this browser. Runs at login, alongside loadDefaultOwnerFilter. */
async function loadCloudPrefs() {
  const legacyRule = _readLegacy(LEGACY_MERGE_KEY);
  const legacyMs = _readLegacy(LEGACY_LIVE_MS_KEY);

  let cloud = {};
  if (window.WD && WD.api) {
    try {
      const r = await WD.api('settings/get');
      if (r && r.ok && r.settings && r.settings.cloud) cloud = r.settings.cloud;
    } catch (e) { /* no server, or unreadable — fall through to defaults */ }
  }

  const savedRule = MERGE_RULES.indexOf(cloud.merge_rule) > -1 ? cloud.merge_rule : 'ask';
  const savedMs = parseInt(cloud.live_interval_ms, 10) > 0
    ? parseInt(cloud.live_interval_ms, 10) : 30000;

  // The browser copy wins where it exists — it is what this machine was doing.
  _mergeRule = MERGE_RULES.indexOf(legacyRule) > -1 ? legacyRule : savedRule;
  const legacyMsNum = parseInt(legacyMs, 10);
  _liveMs = legacyMsNum > 0 ? legacyMsNum : savedMs;

  const patch = {};
  if (_mergeRule !== savedRule) patch.merge_rule = _mergeRule;
  if (_liveMs !== savedMs) patch.live_interval_ms = _liveMs;

  const nothingToWrite = !Object.keys(patch).length;
  const written = nothingToWrite ? true : await _persistCloudPref(patch);

  // Only drop the browser copy once the server definitely has the value,
  // otherwise a failed write would lose the setting outright.
  if (written) {
    if (legacyRule !== null) { try { localStorage.removeItem(LEGACY_MERGE_KEY); } catch (e) {} }
    if (legacyMs !== null) { try { localStorage.removeItem(LEGACY_LIVE_MS_KEY); } catch (e) {} }
  }
  return { mergeRule: _mergeRule, liveMs: _liveMs, migrated: !nothingToWrite && written };
}
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
  const own = defaultOwnerFilter();
  document.querySelectorAll('input[name="setowner"]').forEach(r => { r.checked = (r.value === own); });
  showModal('settingsModal');
}
async function saveSettings() {
  const v = (document.querySelector('input[name="setrule"]:checked') || {}).value || 'ask';
  setMergeRule(v);
  setLiveMs(document.getElementById('setLiveInterval').value);
  restartLive();

  // The one setting on this page that is not per-browser. It decides what the
  // list opens on, so it belongs with the rest of the suite's settings rather
  // than in whichever browser happened to set it - the old per-browser
  // version of this filter is exactly how one machine ended up showing a
  // different set of sites from another.
  const own = (document.querySelector('input[name="setowner"]:checked') || {}).value || 'all';
  const changed = own !== defaultOwnerFilter();
  let failed = '';
  if (changed) {
    try {
      const r = await WD.api('settings/update', { patch: { cloud: { default_owner_filter: own } } });
      if (!r || !r.ok) throw new Error((r && r.error) || 'the settings file could not be written');
      _ownerFilterDefault = own;
      // Nothing was clicked in the toolbar, so what is on screen follows the
      // new default rather than quietly becoming an override of it.
      if (!_ownerFilterOverridden) {
        setOwnerFilter(own);
        syncOwnerToggle();
        updateDashboard();
        renderRows();
      } else {
        _ownerFilterOverridden = (ownerFilter() !== own);
        renderOwnerFilterNotice();
      }
    } catch (err) { failed = err.message || String(err); }
  }

  closeModal('settingsModal');
  if (failed) toast('Saved, but the default owner view was not: ' + failed, 'error');
  else toast('Settings saved', 'success');
}

/* Which owner filter the Files list opens on, and which one is on screen.
   They are two different things and this is the one place that keeps them
   apart.

   The list opens on whatever Settings says. Clicking the toolbar toggle
   changes what is on screen and nothing else — reload and you are back on
   the default. That asymmetry is deliberate, and it is what closed an old
   bug: this filter used to persist whatever was last clicked, so a stray
   click on "Mine" stuck one machine there permanently while another machine
   still opened on everything. The symptom was a fully-populated Sites tab
   that looked like it held three sites, and it read as missing data rather
   than as a filter, because nothing on screen said a filter was on.

   So the second half of the rule is that anything narrower than All says so,
   on screen, for as long as it is on — see renderOwnerFilterNotice below.
   Persisting this without that notice would rebuild the same trap. */
const OWNER_FILTERS = ['all', 'mine', 'others'];
const OWNER_FILTER_LABEL = { all: 'All', mine: 'Mine', others: 'Others' };

/* Mine, matching the shipped default in `tools/settings.py`. These two
   disagreeing would mean the page opened on All for the moment before the
   settings call came back, which is a flash of other people's projects and,
   on a slow read, a list he might act on. */
let _ownerFilterDefault = 'mine';     // what Settings says to open on
let _ownerFilterState = 'mine';       // what is on screen right now
let _ownerFilterOverridden = false;   // moved off the default by hand
let _ownerFilterForcedReason = '';    // why we put it back to All ourselves

function _validOwnerFilter(v) {
  return OWNER_FILTERS.indexOf(v) > -1 ? v : null;
}

function ownerFilter() {
  return _ownerFilterState;
}
function setOwnerFilter(v) {
  _ownerFilterState = _validOwnerFilter(v) || 'all';
}
function defaultOwnerFilter() {
  return _ownerFilterDefault;
}

/* Read the saved default once, before the first listing is drawn.

   No server, or a settings file we cannot read, means All — showing
   everything is the safe way to be wrong, and it is what this page did
   before the setting existed. */
function loadDefaultOwnerFilter() {
  const apply = (v) => {
    _ownerFilterDefault = _validOwnerFilter(v) || 'all';
    _ownerFilterState = _ownerFilterDefault;
    _ownerFilterOverridden = false;
    _ownerFilterForcedReason = '';
  };
  if (!window.WD || !WD.api) { apply('all'); return Promise.resolve(); }
  return WD.api('settings/get').then(r => {
    apply(r && r.ok && r.settings && r.settings.cloud
      && r.settings.cloud.default_owner_filter);
  }).catch(() => { apply('all'); });
}

function setOwnerFilterUI(v) {
  const want = _validOwnerFilter(v) || 'all';
  setOwnerFilter(want);
  _ownerFilterForcedReason = '';

  /* It sticks now.

     "every time I load a new version on my work computer ... it does not save
     my choice of the owner being on Mine, which is really frustrating."

     It was in-memory on purpose: a per-browser copy had once got stuck on
     "Mine" and looked like missing data. What made that dangerous was that
     nothing said the filter was on - and since v2.51.0 something does.
     `#ownerFilterNotice` names any filter narrower than All, in words, above
     the list. A saved filter cannot be silently stuck while a banner is
     naming it, so the reason for not saving it has gone and the papercut he
     has been re-fixing after every update goes with it. */
  _ownerFilterDefault = want;
  _ownerFilterOverridden = false;
  syncOwnerToggle();
  updateDashboard();
  renderRows();

  /* Through the helper that already writes cloud preferences, not a second
     route of its own. Losing the preference is survivable and losing the page
     is not, so a failure only stops it being remembered - the filter is on
     screen and in force either way, and the notice then says it is just for
     this visit rather than claiming to be saved. */
  _persistCloudPref({ default_owner_filter: want }).then(ok => {
    if (ok) return;
    _ownerFilterOverridden = true;
    syncOwnerToggle();
  });
}

/* Ekahau Cloud tells us who owns a project only when the listing comes back
   with an account attached. Without one, "Mine" and "Others" cannot be
   answered — every row would pass, or every row would fail, depending which
   way the test happened to fall. Showing a filter that is not really
   filtering is the worse of the two, so go back to All and say why.

   This is the case that makes a saved default of "Mine" safe to ship: on a
   listing with no owner information it turns itself off in the open, instead
   of rendering an empty page that looks like an empty cloud account. */
function reconcileOwnerFilterWithData() {
  const cur = ownerFilter();
  if (cur === 'all') { _ownerFilterForcedReason = ''; return; }
  if (((data && data.currentUser) || '').trim()) { _ownerFilterForcedReason = ''; return; }
  _ownerFilterForcedReason = 'Ekahau Cloud did not say which account these '
    + 'projects belong to, so “' + OWNER_FILTER_LABEL[cur] + '” could not '
    + 'be applied and everything is shown.';
  setOwnerFilter('all');
  _ownerFilterOverridden = false;
  syncOwnerToggle();
}

function syncOwnerToggle() {
  const cur = ownerFilter();
  document.querySelectorAll('#ownerToggle .owner-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.owner === cur);
  });
  renderOwnerFilterNotice();
}

/* The visible half of the bargain: a filter that hides rows has to be
   readable without hunting for a highlighted button in the toolbar, and it
   has to say whether it will still be on tomorrow. */
function renderOwnerFilterNotice() {
  const el = document.getElementById('ownerFilterNotice');
  if (!el) return;
  // Duplicates is a different list that this filter does not touch, so a
  // banner about hidden sites would be describing something else entirely.
  if (currentTab === 'duplicates') { el.hidden = true; return; }
  const cur = ownerFilter();

  /* **All** is the state worth explaining now, not Mine.

     Mine is the shipped default, so a banner explaining it would fire on
     every load of the ordinary case - which is how a notice stops being
     read. All is the unusual one, and it is the one with a consequence: the
     list carries other people's projects, and Ekahau will not let him change
     those, so the actions on those rows are unavailable. Saying that once
     above the list beats discovering it per row. */
  if (cur === 'all') {
    el.hidden = false;
    el.className = 'owner-notice is-info';
    el.innerHTML = '<span class="own-note-icon">&#9432;</span>'
      + '<span class="own-note-text">'
      + (_ownerFilterForcedReason
          ? e(_ownerFilterForcedReason) + ' '
          : '<b>Showing every owner.</b> ')
      + 'Projects owned by other people are listed; renaming, deleting, '
      + 'assigning, sharing and replacing are unavailable on those, because '
      + 'Ekahau only lets the owner change a project.</span>'
      + '<button class="btn btn-secondary own-note-btn" onclick="setOwnerFilterUI(\'mine\')">'
      + 'Show only mine</button>';
    return;
  }

  /* Mine is the default, so it only needs saying when he has moved off the
     default himself - and Others always does, being genuinely unusual. */
  if (cur === 'mine' && !_ownerFilterOverridden) {
    el.hidden = true;
    el.innerHTML = '';
    return;
  }

  const where = _ownerFilterOverridden
    ? 'Just for this visit — reopening Cloud Manager goes back to “'
      + OWNER_FILTER_LABEL[_ownerFilterDefault] + '”.'
    : 'This is your saved default, so it will be on again next time. '
      + 'Change it in Settings.';

  el.hidden = false;
  el.className = 'owner-notice';
  el.innerHTML = '<span class="own-note-icon">&#128065;</span>'
    + '<span class="own-note-text"><b>Owner filter: '
    + e(OWNER_FILTER_LABEL[cur]) + '</b> — sites and projects owned by '
    + (cur === 'mine' ? 'other people are hidden. ' : 'you are hidden. ')
    + e(where) + '</span>'
    + '<button class="btn btn-secondary own-note-btn" onclick="setOwnerFilterUI(\'all\')">'
    + 'Show all owners</button>';
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
/* A <details> menu stays open after a click, leaving it covering the row the
   action just ran on. Close it on any activation inside, and on a click
   anywhere else. Escape closes them all. */
document.addEventListener('click', (ev) => {
  const inside = ev.target.closest ? ev.target.closest('.wd-menu') : null;
  document.querySelectorAll('.wd-menu[open]').forEach(m => {
    if (m !== inside) m.open = false;
  });
  if (inside && ev.target.closest('.wd-menu-item')) {
    setTimeout(() => { inside.open = false; }, 0);
  }
});
document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape') {
    document.querySelectorAll('.wd-menu[open]').forEach(m => { m.open = false; });
  }
});

function clearSelection() {
  selected.clear();
  lastChkIndex = null;
  const sa = document.getElementById('selAll'); if (sa) sa.checked = false;
  updateBulkBar();
}
function updateBulkBar() {
  const n = selected.size;
  document.getElementById('selCount').textContent = n ? n + ' selected' : '';

  /* The selection bar is not there until there is a selection. Half the old
     toolbar only meant anything with something ticked, and it was the half
     whose width pushed everything else off a laptop screen. */
  const selBar = document.getElementById('selectionBar');
  if (selBar) selBar.hidden = n === 0;

  let deletableCount = 0, movableCount = 0, localFolderCount = 0;
  let verifyableCount = 0;
  const verifyablePairIds = new Set();

  const ownedCloudIds = new Set();
  const myEmail = ((data && data.currentUser) || '').toLowerCase();
  selected.forEach(k => {
    const d = rowData[k]; if (!d) return;

    const isTreeChild = k.startsWith('ct:');
    if (d.kind === 'pair') {
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
    /* A project, on whichever tab it was selected from. This used to require
       the Projects tab, which hid "Move to site…" entirely on the Sites tab -
       where the nested .esx rows live and where you would naturally select a
       handful of files to move. The tab was standing in for "is this a
       project", because a site row and a project row are both kind 'cloud';
       isProjectSyncItem is that question asked directly, so a site can never
       be handed to assign_to_site as though it were a project. */
    if (movableSidesOf(d).length) movableCount++;

  });
  const syncItems = selectedSyncItems();
  const planToLocal = syncPlan(syncItems, 'to-local');
  const planToCloud = syncPlan(syncItems, 'to-cloud');
  /* Why a bulk button is off has to reach him, and until now none of it did.

     The old version set `el.disabled = true` and stashed the reason in
     `el.dataset.disabledTitle` - which nothing in this file, in the CSS or in
     the tooltip delegation ever read. Six carefully written explanations, none
     of them rendered anywhere. A disabled button emits no pointer events
     either, so even `title` would not have shown; the greyed button was the
     entire message.

     So the button stays enabled to the DOM and is disabled by class and
     aria-disabled instead. It greys the same way, screen readers still
     announce it as unavailable, and it can be hovered and clicked - which is
     what makes the reason reachable. _wireDisabledBulkReasons catches the
     click and says what to select. */
  const setBtn = (id, tabVisible, enabled, disabledTitle, tooltip) => {
    const el = document.getElementById(id); if (!el) return;
    if (el.dataset.baseTitle === undefined) el.dataset.baseTitle = el.title || '';
    el.style.display = tabVisible ? '' : 'none';
    el.disabled = false;
    el.setAttribute('aria-disabled', enabled ? 'false' : 'true');
    el.classList.toggle('is-disabled', !enabled);
    el.title = enabled
      ? (tooltip || el.dataset.baseTitle)
      : (disabledTitle || el.dataset.baseTitle);
  };
  const syncFromTip = currentTab === 'projects'
    ? 'Local → Cloud: renames matched cloud projects to the local name, and uploads local-only .esx files to Ekahau Cloud'
    : 'Local → Cloud: renames matched cloud sites, and creates a cloud site for any local-only site, moving the .esx files inside it up with it';
  const syncToTip = currentTab === 'projects'
    ? 'Cloud → Local: renames matched local files to the cloud name, and downloads cloud-only projects as .esx files'
    : 'Cloud → Local: renames matched local folders, and creates a local folder for any cloud-only site, downloading the projects inside it';
  setBtn('bulkSyncTo', true, planToLocal.total > 0,
    currentTab === 'sites'
      ? 'Sync → needs matched sites, or cloud-only sites to create locally'
      : 'Sync → needs matched rows, cloud-only projects, or a cloud-only site',
    syncToTip);
  setBtn('bulkSyncFrom', true, planToCloud.total > 0,
    currentTab === 'sites'
      ? 'Sync ← needs matched sites, or local-only sites to create in the cloud'
      : 'Sync ← needs matched rows, local-only .esx files, or a local-only site',
    syncFromTip);
  setBtn('bulkVerifyBtn', true, verifyableCount > 0, 'Select one or more Name-matches pairs to verify (download cloud → overwrite local)');
  setBtn('bulkShareBtn', true, ownedCloudIds.size > 0,
    'Select one or more cloud projects you own — Ekahau only lets the owner add shares',
    ownedCloudIds.size > 0
      ? `Share ${ownedCloudIds.size} project${ownedCloudIds.size === 1 ? '' : 's'} with people or your Sharing Group in one action`
      : undefined);

  window._bulkShareOwnedIds = Array.from(ownedCloudIds);
  setBtn('bulkDeleteBtn', true, deletableCount > 0, 'Bulk delete only works on cloud-only or local-only rows');
  setBtn('compareBtn', currentTab === 'sites', localFolderCount >= 2, 'Select 2+ local folders to compare');
  setBtn('bulkMoveBtn', true, movableCount > 0, 'Select cloud projects or local .esx files first');
}

function isProjectSyncItem(d) {
  return !!d && (currentTab === 'projects' || d.entityKind === 'projects');
}

/* Which sides of a selected row can be moved into a site.

   The count and the action both used to ask
   `d.kind === 'cloud' || (d.kind === 'local' && !d.isDir)` - which covers
   every row shape except a matched pair. On the **Projects** tab a matched
   project is a single `pair` row, so "Move to site..." was dead for exactly
   the files the everyday workflow produces: design locally, push up, and the
   two sides match from then on. It worked on the Sites tab only because the
   tree gives each side of a nested pair its own checkbox key (`ct-c:` /
   `ct-l:`) and those rows are plain cloud/local, which is why the feature
   tested fine and still could not be used where it was reached for.

   A pair yields both of its sides, because moving one and not the other would
   file the cloud project under one site and leave the .esx in another folder -
   the pair survives the move only if both ends go. The `.esx` test is what
   keeps a matched *site* out: a site pair's local side is a folder, and
   `assign_to_site` must never be handed one. Same idiom as `isFilePair`. */
function movableSidesOf(d) {
  if (!d || !isProjectSyncItem(d)) return [];
  if (d.kind === 'cloud') {
    return [{ kind: 'cloud', id: d.id, name: d.name, size: d.size, owner: d.owner }];
  }
  if (d.kind === 'local') {
    return d.isDir ? []
      : [{ kind: 'local', path: d.path, name: d.name, size: d.size, owner: d.owner }];
  }
  if (d.kind === 'pair' && /\.esx$/i.test(String(d.localPath || ''))) {
    return [
      { kind: 'cloud', id: d.cloudId, name: d.cloudName, owner: d.cloudOwner },
      { kind: 'local', path: d.localPath, name: d.localName },
    ];
  }
  return [];
}

/* What a Sync in this direction would actually do, given a selection.

   The bulk bar and the Sync action both ask this, because the last two faults
   in this file were a control disagreeing with the thing behind it: the "Cloud
   newer" badge that had no handler, and this one - selecting local sites left
   both Sync buttons dead while bulkSync was perfectly willing to create them.
   Two readings of one question is the bug, so there is one reading now. */
/* What "sync" means here.

   It used to mean reconciling *presence*: matched pairs got their names made
   to agree, and orphans got copied to the side that lacked them. Nothing moved
   *content*. So selecting three files that the badge said were newer on cloud
   and pressing Sync renamed three things and left three stale files on disk -
   the word promised something the feature did not do.

   A matched pair whose two sides differ in age is now a content transfer, in
   the direction of the newer side, and it is planned per file so the confirm
   can show which way each one goes.

   Only cloud-to-local is implemented. Sending a local file up to an existing
   cloud project is not something the API client can do yet: the upload flow
   creates a new project rather than replacing one in place. Rather than
   quietly leave those out of the count, they are collected separately and
   named in the confirm as skipped, with the reason. */
function syncPlan(items, dir) {
  const allPairs = items.filter(d => d.kind === 'pair');

  /* A matched *site* is also kind 'pair', and its local side is a folder.
     verify_replace_local would be handed a directory path. Content transfer
     applies to a file, so that is what is tested for rather than the tab or
     the entity kind - a site row can never satisfy it. */
  const isFilePair = (d) => d.kind === 'pair'
    && /\.esx$/i.test(String(d.localPath || ''));

  /* The same two questions the row asks, asked here.

     They were not, and the two halves of the tool disagreed in both
     directions:

     * **A push the row offers, the planner called blocked.** `syncPlan` tested
       only `staleness === 'local_newer'` and never looked at `matchType`, so a
       pair carrying Ekahau's own id - the pair whose row draws a working
       "Local newer · replace cloud" button - came back as `total: 0,
       blockedPushes: 1`. That is the second half of his report: "I hit the
       checkbox and I can't sync it either."

     * **A pull the row refuses, the planner performed.** `canPullFromCloud`
       requires `PULLABLE_MATCH_TYPES`, so the row will not bring a cloud copy
       down over a local file on a pairing WD merely guessed at. The planner
       had no such test, so ticking that row and pressing Sync overwrote it.
       `verify_replace_local` keeps a backup so nothing was lost, but the
       permissive side of a disagreement about overwriting his work is the
       wrong side to be on.

     One predicate each, shared with the row, so there is one answer to "may
     this pair move in this direction" rather than two. */
  const mayPull = (d) => isFilePair(d) && PULLABLE_MATCH_TYPES.has(d.matchType);
  const mayPush = (d) => isFilePair(d) && PUSHABLE_MATCH_TYPES.has(d.matchType);

  const stale = (d, which) => isFilePair(d) && d.staleness === which;

  // Content first: a pair that is stale is not merely misnamed.
  const contentPulls = dir === 'to-local'
    ? allPairs.filter(d => stale(d, 'cloud_newer') && mayPull(d))
    : [];
  const contentPushes = dir === 'to-cloud'
    ? allPairs.filter(d => stale(d, 'local_newer') && mayPush(d))
    : [];

  /* Refused, and reported as refused. Only a guessed pairing reaches these -
     a shared site code or similar wording, where the two names are not even
     the same - and the refusal is the same one the row makes. */
  const blockedPulls = dir === 'to-local'
    ? allPairs.filter(d => stale(d, 'cloud_newer') && !mayPull(d))
    : [];
  const blockedPushes = dir === 'to-cloud'
    ? allPairs.filter(d => stale(d, 'local_newer') && !mayPush(d))
    : [];

  /* Newer on the side this run is not writing to. Not refused - Sync never
     replaces a newer file with an older one - and now genuinely a matter of
     running the other direction, which is something he can do. */
  const wrongWay = dir === 'to-local'
    ? allPairs.filter(d => stale(d, 'local_newer'))
    : allPairs.filter(d => stale(d, 'cloud_newer'));

  const moving = new Set([...contentPulls, ...contentPushes,
                          ...blockedPulls, ...blockedPushes, ...wrongWay]);

  // What is left of the matched rows is the old behaviour: names only.
  const pairs = allPairs.filter(d => !moving.has(d));

  const uploads = dir === 'to-cloud'
    ? items.filter(d => isProjectSyncItem(d) && d.kind === 'local' && !d.isDir)
    : [];
  const downloads = dir === 'to-local'
    ? items.filter(d => isProjectSyncItem(d) && d.kind === 'cloud')
    : [];
  const handled = new Set([...allPairs, ...uploads, ...downloads]);
  // A whole site with no counterpart: create it on the other side and carry
  // the files already inside it across in the same action. Selecting the site
  // is enough - its children come with it.
  const wantKind = dir === 'to-cloud' ? 'local' : 'cloud';
  const siteCreates = items.filter(d => !handled.has(d) && d.kind === wantKind && d.children);
  const creating = new Set(siteCreates);
  const skipped = items.filter(d => !handled.has(d) && !creating.has(d));
  return {
    pairs: pairs, uploads: uploads, downloads: downloads,
    contentPulls: contentPulls, contentPushes: contentPushes,
    blockedPushes: blockedPushes, blockedPulls: blockedPulls,
    wrongWay: wrongWay,
    siteCreates: siteCreates, skipped: skipped,
    total: pairs.length + uploads.length + downloads.length
         + contentPulls.length + contentPushes.length + siteCreates.length,
  };
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
  const plan = syncPlan(items, dir);
  const pairs = plan.pairs;
  const uploads = plan.uploads;
  const downloads = plan.downloads;
  const siteCreates = plan.siteCreates;
  const contentPulls = plan.contentPulls;
  const contentPushes = plan.contentPushes || [];
  const blockedPushes = plan.blockedPushes || [];
  const blockedPulls = plan.blockedPulls || [];
  const wrongWay = plan.wrongWay || [];
  const stillSkipped = plan.skipped;

  if (!plan.total) {
    toast(dir === 'to-cloud'
      ? 'Select matched rows or local-only .esx files first'
      : 'Select matched rows or cloud-only projects first', 'info');
    return;
  }

  const createdFileCount = siteCreates.reduce((n, d) => {
    const kids = dir === 'to-cloud' ? (d.children.localOnly || []) : (d.children.cloudOnly || []);
    return n + kids.length;
  }, 0);
  const parts = [];
  if (contentPulls.length) parts.push(`Sync <b>${contentPulls.length}</b> file${contentPulls.length === 1 ? '' : 's'} — the newer cloud copy replaces the older local one`);
  if (contentPushes.length) parts.push(`Send <b>${contentPushes.length}</b> newer local file${contentPushes.length === 1 ? '' : 's'} up — each replaces its cloud project`);
  const pullRenames = contentPulls.filter(d => (d.cloudName || '').trim()
    && (d.localName || '').trim() !== (d.cloudName || '').trim());
  if (pullRenames.length) parts.push(`Rename <b>${pullRenames.length}</b> of those local files to match ${pullRenames.length === 1 ? 'its' : 'their'} cloud name${pullRenames.length === 1 ? '' : 's'}`);
  if (pairs.length) parts.push(`Rename <b>${pairs.length}</b> matched item${pairs.length === 1 ? '' : 's'}`);
  if (uploads.length) parts.push(`Upload <b>${uploads.length}</b> local .esx file${uploads.length === 1 ? '' : 's'} to Ekahau Cloud`);
  if (downloads.length) parts.push(`Download <b>${downloads.length}</b> cloud project${downloads.length === 1 ? '' : 's'}`);
  if (siteCreates.length) {
    const noun = dir === 'to-cloud' ? 'cloud site' : 'local folder';
    const fileNote = createdFileCount
      ? ` and move <b>${createdFileCount}</b> file${createdFileCount === 1 ? '' : 's'} into ${siteCreates.length === 1 ? 'it' : 'them'}`
      : '';
    parts.push(`Create <b>${siteCreates.length}</b> new ${noun}${siteCreates.length === 1 ? '' : 's'}${fileNote}`);
  }
  let body = `<ul>${parts.map(t => `<li>${t}</li>`).join('')}</ul>`;

  /* Overwriting a file is not a line item in a summary. Whatever is about to
     be replaced gets named here with both dates, so "3 files" is something you
     can actually check before it happens rather than after. */
  if (contentPulls.length) {
    const rows = contentPulls.map(d => `
      <tr>
        <td class="sync-plan-name">${e(d.cloudName || d.localName || '')}</td>
        <td class="sync-plan-dir">&#11015; cloud &rarr; local</td>
        <td class="sync-plan-when">cloud ${e(fmtRelDate(d.cloudMtime))}<br>
          <span class="sub">local ${e(fmtRelDate(d.localMtime))}</span></td>
      </tr>`).join('');
    body += `
      <p class="sync-plan-lead">Sync — each of these takes the newer side:</p>
      <div class="sync-plan-wrap"><table class="sync-plan">
        <thead><tr><th>File</th><th>Direction</th><th>Last saved</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      <p class="sub">Your current copy of each is kept in the
        <code>backups</code> folder, as
        <code>backups/&lt;site&gt;/&lt;name&gt;.previous-&lt;date&gt;.esx</code>.
        The newest three are kept per file.</p>
      <p class="sub">${contentPulls.filter(d => d.differenceKind === 'renamed').length} of these differ only by a <b>rename</b> — the name inside your local file is the old one and no design change was detected. Those are the low-risk ones.</p>
      <p class="sub warn"><b>Two dates cannot tell you whether both sides
        changed.</b> If you edited one of these locally since it last matched
        the cloud, "cloud is newer" and "we both changed it" look identical
        from here, and your local edit goes into the <code>.previous-</code>
        file rather than into the result.</p>`;
  }

  /* Going up, named one by one.

     This section used to be an apology: "sending local files up is not part of
     a bulk run ... it is one row at a time and deliberate." The row has done
     it since v2.104.6 and only the planner had not caught up, so the sentence
     was describing a limitation in the code rather than a decision about the
     operation - with six of his files waiting behind it.

     Every cloud project that will be deleted is named here, before he presses
     anything. That is the question the row asks per file, asked once for the
     batch, which is the right place for it: he is looking at the whole list. */
  if (contentPushes.length) {
    const rows = contentPushes.map(d => `
      <tr>
        <td class="sync-plan-name">${e(d.localName || d.cloudName || '')}</td>
        <td class="sync-plan-dir">&#11014; up</td>
        <td class="sync-plan-name">${e(d.cloudName || '')}</td>
        <td class="sync-plan-when">local ${e(fmtRelDate(d.localMtime))}<br>
          <span class="sub">cloud ${e(fmtRelDate(d.cloudMtime))}</span></td>
      </tr>`).join('');
    body += `
      <p class="sync-plan-lead">Send <b>${contentPushes.length}</b> newer local
        file${contentPushes.length === 1 ? '' : 's'} up:</p>
      <div class="sync-plan-wrap"><table class="sync-plan">
        <thead><tr><th>Your file</th><th>Direction</th><th>Replaces this cloud project</th><th>Last saved</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
      <p class="sub warn">Each one is uploaded and checked first; the cloud
        project named above is deleted only after that succeeds. <b>A cloud
        delete cannot be undone</b> — read that column before you press Sync.</p>`;
    const unproven = contentPushes.filter(d => !PROVEN_MATCH_TYPES.has(d.matchType));
    if (unproven.length) {
      body += `
      <p class="sub warn"><b>${unproven.length} of these ${unproven.length === 1 ? 'is' : 'are'} paired on ${unproven.length === 1 ? 'its name' : 'their names'}</b> rather than on Ekahau's own id, so the tool cannot prove ${unproven.length === 1 ? 'it is' : 'they are'} the same project:
        ${unproven.map(d => e(d.cloudName || d.localName || '')).join(', ')}.
        Check ${unproven.length === 1 ? 'that name is the one' : 'those names are the ones'} you mean.</p>`;
    }
  }

  /* Refused, and it is the same refusal the row makes. Only a guessed pairing
     reaches here - a shared site code, or similar wording - where the two
     names are not even the same and there is nothing to confirm against. */
  if (blockedPushes.length) {
    const names = blockedPushes
      .map(d => e(d.localName || d.cloudName || '')).join(', ');
    body += `
      <p class="sub warn"><b>${blockedPushes.length} newer local file${blockedPushes.length === 1 ? ' is' : 's are'} not sent up:</b>
        ${names}. These were paired by guesswork — a shared site code or
        similar wording — so replacing the cloud copy would risk deleting a
        project that was never the counterpart, and that cannot be undone.
        Use <b>Confirm this pair</b> on the row, and ${blockedPushes.length === 1 ? 'it joins' : 'they join'} the run.</p>`;
  }

  if (blockedPulls.length) {
    const names = blockedPulls
      .map(d => e(d.localName || d.cloudName || '')).join(', ');
    body += `
      <p class="sub warn"><b>${blockedPulls.length} newer cloud cop${blockedPulls.length === 1 ? 'y is' : 'ies are'} not brought down:</b>
        ${names}. Same reason in the other direction — these were paired by
        guesswork, so downloading over your local file could overwrite a
        different project. Use <b>Confirm this pair</b> on the row.</p>`;
  }

  /* Newer on the other side. Not refused, and no longer a dead end: the other
     direction is a button away and does the whole batch. */
  if (wrongWay.length) {
    const other = dir === 'to-local' ? 'Local → Cloud' : 'Cloud → Local';
    const which = dir === 'to-local' ? 'newer locally' : 'newer in the cloud';
    body += `
      <p class="sub"><b>${wrongWay.length} file${wrongWay.length === 1 ? ' is' : 's are'} ${which}</b>
        and ${wrongWay.length === 1 ? 'is' : 'are'} left exactly as ${wrongWay.length === 1 ? 'it is' : 'they are'} — Sync never overwrites the newer side.
        Run <b>${other}</b> on the same selection to move
        ${wrongWay.length === 1 ? 'it' : 'them'}.</p>`;
  }

  if (stillSkipped.length) {
    body += `<p class="sub">${stillSkipped.length} selected item${stillSkipped.length === 1 ? '' : 's'} will be skipped (already in sync, or nothing to do in this direction).</p>`;
  }
  const ok = await showConfirmModal('Sync selected items?', body, 'Sync');
  if (!ok) return;
  clearSelection();

  // Every step below fires through opEnqueue so it lands as a card in the
  // bottom-right ops deck immediately -- a silent `await` loop here means
  // the user has zero indication anything is happening until the whole
  // batch finishes and the screen suddenly changes underneath them, which
  // for a bulk cloud operation is a real data-loss risk, not just a UX
  // nitpick.
  /* Content before names. verify_replace_local is the same call the per-row
     arrow makes - it backs the local file up, downloads, and replaces
     atomically, and it refuses on its own if the server says local is newer
     than the listing claimed. Writing a second download path here is how this
     repo grows two implementations of one operation. */
  for (const d of contentPulls) {
    opEnqueue({
      title: `Replacing "${d.localName || d.cloudName}" with the cloud copy`,
      type: 'verify', pollBackend: false, undoable: false,
      run: async () => {
        const r = await pyApi('verify_replace_local', d.cloudId, d.localPath);
        if (r && r.error) {
          _markVerifyFailed(d.cloudId, d.localPath);
          if (r.error === 'local_newer') {
            // The listing said cloud was newer and the server disagrees. It
            // wins - it just re-read both - and nothing was written.
            throw new Error('Skipped — the server says local is newer');
          }
          throw new Error(r.error);
        }
        _scheduleOpRefresh();
        return r;
      },
    });
    /* The pull replaces the bytes and keeps the filename - `verify_replace_local`
       ends in os.replace - so a sync that only pulled left every name still
       mismatched and needed a second run to tidy up. Renaming here is the rest
       of the same intention, in the same pass. It is queued separately so a
       rename that cannot land (a name already taken) reports itself without
       calling the download a failure. */
    if ((d.cloudName || '').trim()
        && (d.localName || '').trim() !== (d.cloudName || '').trim()) {
      opEnqueue({
        title: `Renaming local to "${d.cloudName}"`,
        type: 'rename', pollBackend: false, undoable: false,
        run: async () => {
          const r = await pyApi('rename_local', d.localPath, d.cloudName);
          if (r && r.error) throw new Error(r.error);
          _scheduleOpRefresh();
          return r;
        },
      });
    }
  }

  /* Same call the row's button makes, through the same helper, so the two
     paths cannot drift apart again. The confirm has already happened once, in
     the dialog above, where every project it will delete was named. */
  for (const d of contentPushes) {
    _enqueuePushLocalOverCloud(d.cloudId, d.localPath, d.localName, d.cloudName);
  }

  for (const d of pairs) {
    const label = dir === 'to-local'
      ? `Renaming local to "${d.cloudName}"`
      : `Renaming cloud to "${d.localName}"`;
    opEnqueue({
      title: label,
      type: 'rename', pollBackend: false, undoable: false,
      run: async () => {
        const r = (dir === 'to-local')
          ? await pyApi('rename_local', d.localPath, d.cloudName)
          : await pyApi('rename_cloud', d.entityKind || currentTab, d.cloudId, d.localName);
        if (r && r.error) throw new Error(r.error);
        _scheduleOpRefresh();
        return r;
      },
    });
  }

  // Create the missing sites/folders first (sequential -- each is a real
  // Ekahau Cloud write, and later creates' file-move targets depend on the
  // id/path the previous create returned), then feed whatever was inside
  // them into the same uploads/downloads arrays everything else already
  // selected goes through.
  for (const d of siteCreates) {
    const label = dir === 'to-cloud' ? `Creating cloud site "${d.name}"` : `Creating local folder "${d.name}"`;
    const { promise } = opEnqueue({
      title: label,
      type: 'create', pollBackend: false, undoable: false,
      run: async () => {
        const r = dir === 'to-cloud'
          ? await pyApi('create_site', d.name)
          : await pyApi('create_local_folder', d.name);
        if (r && r.error) throw new Error(r.error);
        return r;
      },
    });
    try {
      const r = await promise;
      if (dir === 'to-cloud') {
        const newSiteId = r.id || r.siteId;
        const alreadyQueued = new Set(uploads.map(x => x.path));
        (d.children.localOnly || []).forEach(f => {
          if (!alreadyQueued.has(f.path)) {
            uploads.push({ path: f.path, name: f.name, siteId: newSiteId });
          }
        });
      } else {
        const folderName = String(r.path || '').replace(/\\/g, '/').split('/').filter(Boolean).pop() || d.name;
        const alreadyQueued = new Set(downloads.map(x => x.id));
        (d.children.cloudOnly || []).forEach(c => {
          if (!alreadyQueued.has(c.id)) {
            downloads.push({ id: c.id, name: c.name, siteName: folderName });
          }
        });
      }
    } catch (err) {  }
  }

  for (const d of uploads) {
    opEnqueue({
      title: `Uploading "${d.name}.esx"`,
      type: 'upload', pollBackend: true,

      undoable: false,
      retryFn: async (newId) => pyApi('upload_project', d.path, d.siteId || d.parentSiteId || undefined, newId),
      run: async (opId) => pyApi('upload_project', d.path, d.siteId || d.parentSiteId || undefined, opId),
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
/* Sync, as the round trip the tool exists for.

   Cloud Manager is not a file browser. A site starts as DWGs, becomes a local
   .esx, goes through PlanTrim and Quick Walls and Ekahau, and ends up in the
   cloud. Local is where the work happens and is also the backup of what the
   cloud holds; the cloud is where the finished thing belongs.

   So this does not ask which direction to move. It looks at each file, works
   out which side is newer, and does that - or nothing at all, when the two
   already agree. There is deliberately no "overwrite everything downward"
   control here, because its safety would depend on the person pressing it
   having reasoned correctly about state the tool already knows.

   What it cannot do, it says. A newer local file is not an anomaly - it is
   the normal result of a day's work, and the tool's job is getting it home.
   Until the upload direction exists those are listed as still needing to go
   up, never quietly counted as done: believing you are in sync when you are
   not is worse than the friction of being told you are not. */
function syncEverythingPlan() {
  const down = [], up = [], upBlocked = [], inSync = [], fresh = [];
  const downBlocked = [];
  const seenPair = new Set(), seenCloud = new Set();

  const isFile = (l) => /\.esx$/i.test(String((l && l.path) || ''));

  const takePair = (pr) => {
    if (!pr || !pr.cloud || !pr.local) return;
    const id = pr.cloud.id;
    if (!id || seenPair.has(id)) return;
    seenPair.add(id);
    if (!isFile(pr.local)) return;          // a site is a folder, not a file
    const row = {
      cloudId: id,
      cloudName: pr.cloud.name || '',
      localName: pr.local.name || '',
      localPath: pr.local.path,
      cloudMtime: Number(pr.cloud.mtime) || 0,
      localMtime: Number(pr.local.mtime) || 0,
      /* Without this the whole-account planner could not ask the question the
         row asks, which is how a pair the row happily pushes ended up in a
         list headed "not part of this run". */
      matchType: pr.matchType,
    };
    if (pr.staleness === 'cloud_newer') {
      (PULLABLE_MATCH_TYPES.has(pr.matchType) ? down : downBlocked).push(row);
    } else if (pr.staleness === 'local_newer') {
      (PUSHABLE_MATCH_TYPES.has(pr.matchType) ? up : upBlocked).push(row);
    } else inSync.push(row);
  };

  const takeCloud = (c, siteName) => {
    if (!c || !c.id || seenCloud.has(c.id)) return;
    seenCloud.add(c.id);
    fresh.push({ id: c.id, name: c.name || '', siteName: siteName || c.siteName || '' });
  };

  const walkKids = (kids, siteName) => {
    if (!kids) return;
    (kids.matched || []).forEach(takePair);
    (kids.cloudOnly || []).forEach(c => takeCloud(c, siteName));
  };

  (data.matched || []).forEach(pr => {
    takePair(pr);
    const site = (pr.cloud && pr.cloud.name) || (pr.local && pr.local.name) || '';
    walkKids((pr.cloud && pr.cloud.children) || (pr.local && pr.local.children), site);
  });
  (data.cloudOnly || []).forEach(c => { takeCloud(c); walkKids(c.children, c.name); });
  (data.localOnly || []).forEach(l => walkKids(l.children, l.name));
  if (data.orphans) (data.orphans.cloudOnly || []).forEach(c => takeCloud(c));

  return { down, up, upBlocked, downBlocked, fresh, inSync };
}

function _syncRowsHtml(rows, dir) {
  return rows.map(d => '<tr>'
    + '<td class="sync-plan-name">' + e(d.localName || d.cloudName) + '</td>'
    + '<td class="sync-plan-dir">' + dir + '</td>'
    + '<td class="sync-plan-when">cloud ' + e(fmtRelDate(d.cloudMtime)) + '<br>'
    + '<span class="sub">local ' + e(fmtRelDate(d.localMtime)) + '</span></td>'
    + '</tr>').join('');
}

/* What the content comparison found for this pair, if it has been run.

   The row used to carry two dates and a paragraph explaining that two dates
   cannot tell you whether both sides changed. They cannot - but the comparison
   can, so where an answer exists it goes in the row and replaces the apology.
   A row reading "name only" is one he can tick without thinking; one reading
   "both changed" is one to leave alone. */
function _syncVerdictCell(d) {
  const cmp = _compareResults.get(_compareKey(d.cloudId, d.localPath));
  if (!cmp) return '<td class="sync-plan-verdict sub">not checked</td>';
  const cls = cmp.designDiffers ? 'cmp-differs' : 'cmp-same';
  const text = cmp.designDiffers ? cmp.summary : (cmp.renamedOnly ? 'name only' : 'identical');
  return '<td class="sync-plan-verdict"><span class="' + cls + '">'
    + e(text) + '</span></td>';
}

/* Pickable rows. The checkbox carries the index into the plan array, so the
   confirm reads the DOM rather than keeping a parallel copy of the selection
   that could drift from what is on screen. */
function _syncPickRowsHtml(rows, kind, dir, withVerdict) {
  return rows.map((d, i) => '<tr>'
    + '<td class="sync-plan-pick"><input type="checkbox" class="sync-pick" checked'
    + ' data-kind="' + kind + '" data-idx="' + i + '" onchange="_syncPickUpdate()"></td>'
    + '<td class="sync-plan-name">' + e(d.localName || d.cloudName || d.name) + '</td>'
    + '<td class="sync-plan-dir">' + dir + '</td>'
    + (withVerdict ? _syncVerdictCell(d) : '')
    + '<td class="sync-plan-when">'
    + (d.cloudMtime === undefined ? e(d.siteName || '')
       : 'cloud ' + e(fmtRelDate(d.cloudMtime)) + '<br><span class="sub">local '
         + e(fmtRelDate(d.localMtime)) + '</span>')
    + '</td>'
    + '</tr>').join('');
}

/* The push rows, which need one column the others do not: the name of the
   cloud project that gets deleted. A pull replaces a local file and keeps a
   backup; this does not come back, so the thing being replaced is on screen
   rather than implied. */
function _syncPushRowsHtml(rows) {
  return rows.map((d, i) => '<tr>'
    + '<td class="sync-plan-pick"><input type="checkbox" class="sync-pick"'
    + (PROVEN_MATCH_TYPES.has(d.matchType) ? ' checked' : '')
    + ' data-kind="up" data-idx="' + i + '" onchange="_syncPickUpdate()"></td>'
    + '<td class="sync-plan-name">' + e(d.localName || d.cloudName || '') + '</td>'
    + '<td class="sync-plan-dir">&#11014; up</td>'
    + '<td class="sync-plan-name">' + e(d.cloudName || '')
    + (PROVEN_MATCH_TYPES.has(d.matchType) ? ''
       : ' <span class="sub">(matched by name only)</span>') + '</td>'
    + '<td class="sync-plan-when">local ' + e(fmtRelDate(d.localMtime)) + '<br>'
    + '<span class="sub">cloud ' + e(fmtRelDate(d.cloudMtime)) + '</span></td>'
    + '</tr>').join('');
}

function _syncPickBoxes(kind) {
  const sel = '#confirmActionBody .sync-pick'
    + (kind ? '[data-kind="' + kind + '"]' : '');
  return Array.from(document.querySelectorAll(sel));
}

/* The button says what will happen to how many, and stops offering to do
   nothing. "Sync 51" when he has unticked fifty of them would be the same
   class of lie the rest of this dialog is being fixed for. */
function _syncPickUpdate() {
  const n = _syncPickBoxes().filter(b => b.checked).length;
  const btn = document.getElementById('confirmActionOkBtn');
  if (btn) {
    btn.textContent = n ? ('Sync ' + n) : 'Nothing selected';
    btn.disabled = !n;
  }
  ['down', 'fresh', 'up'].forEach(kind => {
    const boxes = _syncPickBoxes(kind);
    const head = document.getElementById('syncAll-' + kind);
    if (head && boxes.length) {
      const on = boxes.filter(b => b.checked).length;
      head.checked = on === boxes.length;
      head.indeterminate = on > 0 && on < boxes.length;
    }
  });
}

function _syncPickAll(kind, on) {
  _syncPickBoxes(kind).forEach(b => { b.checked = !!on; });
  _syncPickUpdate();
}

function _syncPicked(kind) {
  return _syncPickBoxes(kind).filter(b => b.checked)
    .map(b => Number(b.getAttribute('data-idx')));
}

/* Compare before committing to anything. Closes the dialog because the ops
   deck lives outside it; the answers land on the rows next time it is opened,
   and on the ledger rows in the meantime. */
function _syncCheckFirst() {
  const plan = syncEverythingPlan();
  _resolveConfirmAction(false);
  plan.down.forEach(d => checkRealDifference(
    d.cloudId, d.localPath, d.cloudName || d.localName || ''));
  toast('Comparing ' + plan.down.length + ' file'
    + (plan.down.length === 1 ? '' : 's')
    + ' — nothing is changed. Re-open Sync all when they finish.', 'info');
}

async function syncEverything() {
  if (!data || !data.summary) { toast('Nothing loaded yet', 'info'); return; }
  const plan = syncEverythingPlan();
  const willDo = plan.down.length + plan.fresh.length + plan.up.length;

  if (!willDo) {
    // Still say what is waiting to go up - that is the half of the loop this
    // cannot finish yet, and silence would read as "all done".
    const stuck = plan.upBlocked.length + plan.downBlocked.length;
    toast(stuck
      ? stuck + ' file' + (stuck === 1 ? '' : 's') + ' need' + (stuck === 1 ? 's' : '')
        + ' the pair confirmed before they can move — use Confirm this pair on '
        + 'the row. Nothing else to do.'
      : 'Local and cloud already match', stuck ? 'info' : 'success');
    return;
  }

  /* Two operations, listed separately and picked separately.

     Downloading a project he has no local copy of cannot lose anything.
     Replacing a local file can. Fusing them into one "Sync 51" button forced
     him to accept the second to get the first, which is most of why this
     screen was frightening. */
  let body = '<p class="sub">Tick what you want. Nothing happens to anything '
    + 'you untick, and nothing happens at all until you press the button.</p>';

  if (plan.down.length) {
    body += '<p class="sync-plan-lead">'
      + '<label class="sync-plan-all"><input type="checkbox" id="syncAll-down" checked '
      + 'onchange="_syncPickAll(\'down\', this.checked)"> '
      + 'Replace <b>' + plan.down.length + '</b> local file'
      + (plan.down.length === 1 ? '' : 's') + ' with the cloud copy</label></p>'
      + '<div class="sync-plan-wrap"><table class="sync-plan">'
      + '<thead><tr><th></th><th>File</th><th>Direction</th><th>What differs</th>'
      + '<th>Last saved</th></tr></thead>'
      + '<tbody>' + _syncPickRowsHtml(plan.down, 'down', '&#11015; cloud &rarr; local', true) + '</tbody>'
      + '</table></div>'
      + '<p class="sub">All ' + plan.down.length + ' listed above — scroll the '
      + 'box for the rest. The copy replaced is kept in <code>backups/&lt;site&gt;/'
      + '&lt;name&gt;.previous-&lt;date&gt;.esx</code>. '
      + 'The newest three per file are kept, so an older state stays recoverable.</p>';

    const unchecked = plan.down.filter(
      d => !_compareResults.get(_compareKey(d.cloudId, d.localPath))).length;
    if (unchecked) {
      /* Replaces the paragraph that used to apologise for not knowing. The
         dates cannot tell him whether both sides changed; the comparison can,
         and it is one button away. */
      body += '<p class="sub warn"><b>' + unchecked + ' of these have not been '
        + 'compared.</b> A later cloud date can mean real work, or just a '
        + 'rename — the dates cannot tell them apart. '
        + '<button type="button" class="btn btn-secondary btn-inline" '
        + 'onclick="_syncCheckFirst()">Compare them first</button> '
        + 'Nothing is changed by comparing.</p>';
    }
  }

  if (plan.fresh.length) {
    body += '<p class="sync-plan-lead">'
      + '<label class="sync-plan-all"><input type="checkbox" id="syncAll-fresh" checked '
      + 'onchange="_syncPickAll(\'fresh\', this.checked)"> '
      + 'Download <b>' + plan.fresh.length + '</b> cloud project'
      + (plan.fresh.length === 1 ? '' : 's') + ' you have no local copy of</label></p>'
      + '<div class="sync-plan-wrap"><table class="sync-plan">'
      + '<thead><tr><th></th><th>Project</th><th>Direction</th><th>Into</th></tr></thead>'
      + '<tbody>' + _syncPickRowsHtml(plan.fresh, 'fresh', '&#11015; new', false) + '</tbody>'
      + '</table></div>'
      + '<p class="sub">All ' + plan.fresh.length + ' listed. These replace '
      + 'nothing — there is no local copy to overwrite.</p>';
  }

  /* The half of the loop this could not finish. It can now.

     This section used to be a table of files under the heading "not part of
     this run", followed by a sentence sending him off to press a button on
     each row - with six of them waiting. The operation was built; only the
     planner had not caught up. */
  if (plan.up.length) {
    const unproven = plan.up.filter(d => !PROVEN_MATCH_TYPES.has(d.matchType));
    body += '<p class="sync-plan-lead">'
      + '<label class="sync-plan-all"><input type="checkbox" id="syncAll-up" '
      + (unproven.length === plan.up.length ? '' : 'checked ')
      + 'onchange="_syncPickAll(\'up\', this.checked)"> '
      + 'Send <b>' + plan.up.length + '</b> newer local file'
      + (plan.up.length === 1 ? '' : 's') + ' up</label></p>'
      + '<div class="sync-plan-wrap"><table class="sync-plan">'
      + '<thead><tr><th></th><th>Your file</th><th>Direction</th>'
      + '<th>Replaces this cloud project</th><th>Last saved</th></tr></thead>'
      + '<tbody>' + _syncPushRowsHtml(plan.up) + '</tbody>'
      + '</table></div>'
      + '<p class="sub warn">Each is uploaded and checked first; the cloud '
      + 'project named above is deleted only after that succeeds. '
      + '<b>A cloud delete cannot be undone.</b></p>';
    if (unproven.length) {
      const one = unproven.length === 1;
      body += '<p class="sub warn"><b>' + unproven.length
        + (one ? ' of these is paired on its name' : ' of these are paired on their names')
        + '</b> rather than on Ekahau\'s own id, so the tool cannot prove '
        + (one ? 'it is' : 'they are') + ' the same project. '
        + (one ? 'It arrives' : 'Those arrive') + ' unticked — check the cloud '
        + 'name beside ' + (one ? 'it' : 'each') + ' is the one you mean, then '
        + 'tick it.</p>';
    }
  }

  if (plan.upBlocked.length || plan.downBlocked.length) {
    const n = plan.upBlocked.length + plan.downBlocked.length;
    const names = [...plan.upBlocked, ...plan.downBlocked]
      .map(d => e(d.localName || d.cloudName || '')).join(', ');
    body += '<p class="sub warn"><b>' + n + ' file' + (n === 1 ? '' : 's')
      + ' cannot move either way yet:</b> ' + names + '. These were paired by '
      + 'guesswork — a shared site code or similar wording — so neither side '
      + 'can safely replace the other. Use <b>Confirm this pair</b> on the '
      + 'row and they join the next run.</p>';
  }

  if (plan.inSync.length) {
    body += '<p class="sub"><b>' + plan.inSync.length
      + '</b> already match and are not touched.</p>';
  }

  /* `showConfirmModal` empties the body when it closes, so the selection has
     to be read on the way out rather than after the await. */
  let _pickedDown = [], _pickedFresh = [], _pickedUp = [];
  const _grab = () => {
    _pickedDown = _syncPicked('down');
    _pickedFresh = _syncPicked('fresh');
    _pickedUp = _syncPicked('up');
  };
  const _okBtn = document.getElementById('confirmActionOkBtn');
  if (_okBtn) _okBtn.addEventListener('click', _grab, { once: true });
  const _shown = showConfirmModal('Sync local and cloud?', body, 'Sync ' + willDo);
  // The body is in the DOM by now, so the header checkboxes and the button can
  // be put into agreement with it before he looks at them.
  _syncPickUpdate();
  const ok = await _shown;
  if (_okBtn) _okBtn.removeEventListener('click', _grab);
  if (!ok) return;
  /* Read the ticks back off the dialog before it goes. Anything unticked is
     simply not in the run - it is not skipped, retried or reported, because he
     did not ask for it. */
  const pickedDown = _pickedDown.length ? _pickedDown : [];
  const pickedFresh = _pickedFresh.length ? _pickedFresh : [];
  const pickedUp = _pickedUp.length ? _pickedUp : [];
  const downRows = pickedDown.map(i => plan.down[i]).filter(Boolean);
  const freshRows = pickedFresh.map(i => plan.fresh[i]).filter(Boolean);
  const upRows = pickedUp.map(i => plan.up[i]).filter(Boolean);
  if (!downRows.length && !freshRows.length && !upRows.length) return;
  clearSelection();

  /* verify_replace_local is the same call the per-row arrow makes: it backs
     the local file up, downloads, replaces atomically, and refuses on its own
     if the server disagrees about which side is newer. */
  const results = { done: 0, failed: 0, skipped: 0, backups: [] };
  const waits = [];
  for (const d of downRows) {
    const { promise } = opEnqueue({
      title: 'Updating "' + (d.localName || d.cloudName) + '" from the cloud',
      type: 'verify', pollBackend: false, undoable: false,
      run: async () => {
        const r = await pyApi('verify_replace_local', d.cloudId, d.localPath);
        if (r && r.error) {
          _markVerifyFailed(d.cloudId, d.localPath);
          if (r.error === 'local_newer') {
            throw new Error('Skipped — the server says local is newer');
          }
          throw new Error(r.error);
        }
        _scheduleOpRefresh();
        return r;
      },
    });
    waits.push(promise.then(r => {
      results.done++;
      if (r && r.backup) results.backups.push(r.backup);
    }).catch(err => {
      if (/local is newer/i.test((err && err.message) || '')) results.skipped++;
      else results.failed++;
    }));
  }
  for (const d of freshRows) {
    const destFolder = d.siteName || d.name;
    const { promise } = opEnqueue({
      title: d.siteName ? 'Downloading "' + d.name + '.esx" → ' + d.siteName
                        : 'Downloading "' + d.name + '.esx"',
      type: 'download', pollBackend: true, undoable: false,
      retryFn: async (newId) => pyApi('download_project', d.id, destFolder, newId),
      run: async (opId) => pyApi('download_project', d.id, destFolder, opId),
    });
    waits.push(promise.then(() => { results.done++; })
                      .catch(() => { results.failed++; }));
  }

  /* Same helper the row's button uses. The question it would ask per file was
     asked once, in the dialog, where every project it will delete was named
     and the unproven ones arrived unticked. */
  for (const d of upRows) {
    const { promise } = _enqueuePushLocalOverCloud(
      d.cloudId, d.localPath, d.localName, d.cloudName);
    waits.push(promise.then(() => { results.done++; })
                      .catch(() => { results.failed++; }));
  }

  await Promise.all(waits);
  _scheduleOpRefresh();
  _reportSyncOutcome(results, plan, { pushed: upRows.length });
}

/* What actually happened, not what was planned. "Make sure the two versions
   are in sync" is a step he performs by hand at the end of every site, so a
   run ends by saying where the two sides now stand - not by reporting that
   some downloads succeeded. */
function _reportSyncOutcome(results, plan, ran) {
  const bits = [];
  if (results.done) bits.push(results.done + ' updated');
  if (results.skipped) bits.push(results.skipped + ' skipped');
  if (results.failed) bits.push(results.failed + ' failed');
  if (plan.inSync.length) bits.push(plan.inSync.length + ' already matched');

  let tone = results.failed ? 'error' : 'success';
  let msg = bits.join(', ') || 'Nothing to do';
  /* What is left, and whether anything is left. The old line said "N still to
     go up (one row at a time)" whether or not he had just sent them up, because
     nothing here could. */
  const left = (plan.upBlocked || []).length + (plan.downBlocked || []).length;
  const notPicked = plan.up.length - ((ran && ran.pushed) || 0);
  if (left) {
    if (!results.failed) tone = 'info';
    msg += ' — ' + left + ' still need the pair confirmed';
  } else if (notPicked > 0) {
    if (!results.failed) tone = 'info';
    msg += ' — ' + notPicked + ' left unticked and not sent up';
  } else if (!results.failed && !results.skipped) {
    msg += ' — local and cloud now match';
  }
  toast(msg, tone);

  if (results.backups.length) {
    const folder = results.backups[0].replace(/[^\\/]+$/, '');
    console.info('[wd] previous local copies kept:', results.backups);
    toast(results.backups.length + ' previous local cop'
      + (results.backups.length === 1 ? 'y' : 'ies') + ' kept in ' + folder, 'info');
  }
}
// Guarded: the sync helpers above are sliced out and evaluated in Node by
// tests/test_server_and_assets.py, where there is no window to hang it on.
if (typeof window !== 'undefined') window.syncEverything = syncEverything;

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
  const anyCloud = items.some(d => d.kind === 'cloud');
  document.getElementById('deleteTitle').textContent =
    anyCloud ? 'Delete selected from Ekahau Cloud?' : 'Delete selected?';
  // The permanence sentence used to live on the second gate. There is one
  // dialog now, so it says it here.
  document.getElementById('deleteSub').innerHTML =
    `Permanently delete ${parts.join(' and ')}.`
    + (anyCloud
        ? ` Once this runs, none of the cloud side will exist anymore, for anyone.`
          + ` There is no trash to recover it from. Local copies (if any) are not touched.`
        : ` This cannot be undone.`);
  _setDeleteBtn(anyCloud ? 'Delete from cloud' : 'Delete');
  // A count is not something anyone can check. Name them, since the list they
  // would otherwise be read from is greyed out behind this dialog.
  _setDeleteWhat('deleteWhat', _deleteWhatHtml(items.map(d =>
    d.kind === 'cloud'
      ? _cloudDeleteEntry(d.id, d.name, (d.context || currentTab) === 'sites')
      : { name: d.name, siteName: '', modified: 'on this computer',
          sharedLine: null, isSite: false })));
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

  const noun = side === 'cloud'
    ? (kind === 'sites' ? 'Cloud Site' : 'Cloud Project')
    : (kind === 'sites' ? 'Local Folder' : 'Local .esx File');

  /* Where it lives, because that is what he was trying to read off the
     greyed-out list: "I go to rename something and it's in the correct folder
     so I want to use the folder name as part of the name, and I can't
     remember the exact thing. I click on the pencil to rename it and of
     course it blurs out the background and I can't see what I'm doing."

     Asked which name he meant: "folder / site name". So it is a labelled fact
     of its own here, beside the current name, and one click puts it in the
     field. Part of the name - his .esx names carry the site name and then
     what kind of file it is - which is why the field opens with the caret at
     the end rather than with everything selected. */
  /* The other half of the pair, if this thing has one. "If we're going to
     rename one side or the other then we should ask to rename both at the
     same time ... if they're matching to begin with, then renaming one side
     shouldn't matter to the other side."

     He has just renamed every cloud project to his site convention and is
     working through a hundred local files by hand to match. This is the
     offer that stops that happening a second time. */
  const partner = _renamePartner(side, idOrPath);

  const where = _renameContainerName(side, idOrPath, kind);
  const whereKey = side === 'cloud' ? 'Cloud site' : 'Folder / site name';
  // Name the row after the thing on the other end of it. A cloud project is
  // not a file, and calling it one is the kind of small wrongness that makes
  // a reader stop and wonder which of the two lists they are looking at.
  const currentKey = kind === 'sites'
    ? (side === 'cloud' ? 'Current site name' : 'Current folder name')
    : (side === 'cloud' ? 'Current project name' : 'Current file name');
  const suffix = _renameSuffix(side, kind);
  const fullPath = side === 'local' ? String(idOrPath || '').replace(/\\/g, '/') : '';

  renameTarget = { side, idOrPath, kind, original: name, suffix, partner };

  const row = (key, val, cls) =>
    '<div class="rename-what-row">'
    + '<div class="rename-what-key">' + e(key) + '</div>'
    + '<div class="rename-what-val ' + cls + '">' + e(val) + '</div>'
    + '</div>';

  document.getElementById('renameTitle').textContent = 'Rename ' + noun;
  document.getElementById('renameWhat').innerHTML =
    '<div class="rename-what-label">You are renaming</div>'
    + (where ? row(whereKey, where, 'rename-what-folder') : '')
    + row(currentKey, name + suffix, 'rename-what-name')
    /* The other side is behind the overlay too, so its current name is a row
       here rather than something he is asked to take on trust. */
    + (partner ? row(_renamePartnerKey(partner, kind),
                     partner.name + _renameSuffix(partner.side, kind),
                     'rename-what-partner') : '')
    + (fullPath ? row('Full path', fullPath, 'rename-what-path') : '');
  document.getElementById('renameSub').textContent = '';

  /* Showing him the folder name is half the job; he wanted it *in* the new
     name - "I want to use the folder name as part of the name". One click
     puts it where the cursor is, so the part he cannot remember is the part
     he does not have to type. */
  const insert = document.getElementById('renameInsert');
  if (where) {
    const arg = a(JSON.stringify(where));
    insert.hidden = false;
    insert.innerHTML =
      '<span class="rename-insert-label">' + e(whereKey) + '</span>'
      + '<button type="button" class="rename-insert-btn"'
      + ' title="Add it to the name at the cursor, keeping what is already there"'
      + ' onclick="_renameInsert(' + arg + ')">Insert &ldquo;' + e(where) + '&rdquo;</button>';
  } else {
    insert.hidden = true;
    insert.innerHTML = '';
  }

  /* Default on. Keeping the pair aligned is the entire point of his naming
     convention, so the common case should not need a decision - he can still
     say no. */
  const pair = document.getElementById('renamePair');
  const both = document.getElementById('renamePairBoth');
  if (partner) {
    pair.hidden = false;
    both.checked = true;
    document.getElementById('renamePairLabel').textContent =
      'Also rename the ' + _renamePartnerNoun(partner, kind);
  } else {
    pair.hidden = true;
    both.checked = false;
  }

  const input = document.getElementById('renameInput');
  input.value = name;
  showModal('renameModal');
  /* Caret at the end rather than the whole value selected. What he is doing
     here is adding to a name that is already right as far as it goes - the
     prefix - so the first keystroke has to extend it, not wipe it. Selecting
     everything is the correct opening for "retype this"; this is not that. */
  input.setSelectionRange(input.value.length, input.value.length);
  input.focus();
  _renamePreview();
}

/* The site or folder this thing sits in, from whichever tab is open. */
function _renameContainerName(side, idOrPath, kind) {
  if (kind === 'sites') return '';          // a site is not inside anything
  if (side === 'cloud') {
    const hit = _cloudDetailsById(idOrPath);
    return (hit && hit.siteName) || '';
  }
  const parts = String(idOrPath || '').replace(/\\/g, '/').split('/').filter(Boolean);
  return parts.length >= 2 ? parts[parts.length - 2] : '';
}

/* He renames the file on disk, so the extension is part of both the fact and
   the outcome. One definition, read by the fact block and by the preview. */
function _renameSuffix(side, kind) {
  return (side === 'local' && kind !== 'sites') ? '.esx' : '';
}

/* The matching thing on the other side, or null.

   Only a *matched pair* has one. A local file with no cloud project has
   nothing to keep in sync, and offering to rename a partner that does not
   exist is worse than not offering at all. Read off `data` rather than off
   `rowData`, because `rowData` labels every top-level pair `entityKind:
   'sites'` whichever tab built it, and a wrong kind here would send a project
   rename to the site endpoint.

   A pair is always the same kind on both sides - a cloud project pairs with a
   local .esx, a cloud site with a local folder - so the caller's `kind` is the
   partner's kind too, and nothing has to be guessed. */
function _renamePartner(side, idOrPath) {
  if (!data) return null;
  const norm = s => String(s || '').replace(/\\/g, '/');
  const target = norm(idOrPath);
  let hit = null;
  const consider = (pr) => {
    if (hit || !pr || !pr.cloud || !pr.local) return;
    if (side === 'cloud' && pr.cloud.id === idOrPath) {
      hit = { side: 'local', idOrPath: pr.local.path, name: pr.local.name };
    } else if (side === 'local' && norm(pr.local.path) === target) {
      hit = { side: 'cloud', idOrPath: pr.cloud.id, name: pr.cloud.name };
    }
  };
  (data.matched || []).forEach(pr => {
    consider(pr);
    const kids = (pr.cloud && pr.cloud.children) || (pr.local && pr.local.children);
    if (kids) (kids.matched || []).forEach(consider);
  });
  return hit;
}

function _renamePartnerNoun(partner, kind) {
  if (partner.side === 'cloud') {
    return kind === 'sites' ? 'cloud site' : 'cloud project';
  }
  return kind === 'sites' ? 'local folder' : 'local .esx file';
}

function _renamePartnerKey(partner, kind) {
  return 'Matching ' + _renamePartnerNoun(partner, kind);
}

/* Is the other side already called this? Renaming a mismatched pair to the
   name one half already has is a real case - it is half of what he is doing
   by hand - and asking the cloud to rename something to its own name is a
   round trip that can only fail. */
function _renamePartnerAlreadyNamed(next) {
  const partner = renameTarget && renameTarget.partner;
  return !!partner && partner.name === next;
}

function _renameBothWanted() {
  const both = document.getElementById('renamePairBoth');
  return !!(renameTarget && renameTarget.partner && both && both.checked);
}

function _renameInsert(text) {
  const input = document.getElementById('renameInput');
  if (!input) return;
  const value = input.value;
  let start = input.selectionStart == null ? value.length : input.selectionStart;
  let end = input.selectionEnd == null ? start : input.selectionEnd;

  /* The field opens with everything selected, so he can retype from scratch.
     That made the first version of this button *replace* the name with the
     folder name, which is the opposite of the request - he wants the folder
     name as **part of** the name. A whole-value selection means "I have not
     put the cursor anywhere yet", so append rather than overwrite. */
  const wholeThing = start === 0 && end === value.length && value.length > 0;
  if (wholeThing) { start = end = value.length; }

  // Only when appending onto existing text, and only a single space: enough
  // to keep two words apart, without inventing a separator he did not ask for.
  const needsGap = start === value.length && value.length > 0
    && !/[\s\-_.]$/.test(value);
  const insert = (needsGap ? ' ' : '') + text;

  input.value = value.slice(0, start) + insert + value.slice(end);
  const at = start + insert.length;
  input.focus();
  input.setSelectionRange(at, at);
  _renamePreview();
}

/* "X -> Y", so the outcome is visible before committing rather than after -
   and once there are two sides, both outcomes, each labelled. He should not
   have to work out what will happen to the half he cannot see. */
function _renamePreview() {
  const el = document.getElementById('renamePreview');
  if (!el || !renameTarget) return;
  const input = document.getElementById('renameInput');
  const next = (input.value || '').trim();
  const from = renameTarget.original || '';
  const suffix = renameTarget.suffix || '';
  const partner = renameTarget.partner;
  const kind = renameTarget.kind;

  if (!next) {
    el.innerHTML = '<span class="rename-preview-none">Enter a name</span>';
    return;
  }

  /* Two grid children per line and no more - the label, and one box holding
     the whole "old -> new". Caught by looking at it: as four loose children
     the arrow and the new name fell into the next row of the grid, so a line
     read as a label, a name, and then an arrow hanging under the label. */
  const line = (label, oldName, newName) =>
    '<div class="rename-preview-line">'
    + '<span class="rename-preview-side">' + e(label) + '</span>'
    + '<span class="rename-preview-move">'
    + (oldName === newName
        ? '<span class="rename-preview-none">' + e(newName) + ' &mdash; unchanged</span>'
        : '<span class="rename-preview-from">' + e(oldName) + '</span>'
          + ' <span class="rename-preview-arrow">&#8594;</span> '
          + '<span class="rename-preview-to">' + e(newName) + '</span>')
    + '</span></div>';

  if (!partner) {
    el.innerHTML = next === from
      ? '<span class="rename-preview-none">Unchanged</span>'
      : line('', from + suffix, next + suffix);
    return;
  }

  const mine = _renamePartnerNoun({ side: renameTarget.side }, kind);
  const theirs = _renamePartnerNoun(partner, kind);
  const pSuffix = _renameSuffix(partner.side, kind);

  let html = line(_renameSentenceCase(mine), from + suffix, next + suffix);
  if (_renameBothWanted()) {
    html += line(_renameSentenceCase(theirs), partner.name + pSuffix, next + pSuffix);
  } else {
    /* Declining has a consequence, so the consequence is on screen rather
       than being something he finds out later from a mismatch badge. */
    html += '<div class="rename-preview-line rename-preview-kept">'
      + '<span class="rename-preview-side">' + e(_renameSentenceCase(theirs)) + '</span>'
      + '<span class="rename-preview-move"><span class="rename-preview-none">stays &ldquo;'
      + e(partner.name + pSuffix) + '&rdquo;</span></span></div>';
  }
  el.innerHTML = html;
}

function _renameSentenceCase(s) {
  return String(s || '').charAt(0).toUpperCase() + String(s || '').slice(1);
}
/* One side, one call. The kind only matters to the cloud, which has separate
   endpoints for a project and a site. */
async function _renameOneSide(side, idOrPath, kind, name) {
  return side === 'cloud'
    ? pyApi('rename_cloud', kind || currentTab, idOrPath, name)
    : pyApi('rename_local', idOrPath, name);
}

async function confirmRename() {
  const n = document.getElementById('renameInput').value.trim();
  if (!n || !renameTarget) { closeModal('renameModal'); return; }
  const rt = renameTarget;
  const both = _renameBothWanted();
  const partnerDone = both && _renamePartnerAlreadyNamed(n);
  closeModal('renameModal');

  if (!both || partnerDone) {
    opEnqueue({
      title: `Renaming to "${n}"`,
      sub: partnerDone
        ? `The ${_renamePartnerNoun(rt.partner, rt.kind)} is already called this`
        : '',
      type: 'rename', pollBackend: false, undoable: false,
      run: async () => {
        const r = await _renameOneSide(rt.side, rt.idOrPath, rt.kind, n);
        if (r && r.error) throw new Error(r.error);
        _scheduleOpRefresh();
        return r;
      },
    });
    return;
  }

  /* Both sides, in one queued item rather than two.

     Two reasons it is one. The side he clicked goes first, because that is
     the one he actually asked for; and if it fails, the partner is left
     alone - two independent items would have gone ahead and renamed the
     other half, turning a failure into a pair that disagrees.

     And a half-done pair has to *say so*. "A pair that half-renamed is worse
     than one that didn't, because he'd believe they match." So the failure
     message names which side is which and what each is now called, rather
     than reporting the second error on its own. */
  const mine = _renamePartnerNoun({ side: rt.side }, rt.kind);
  const theirs = _renamePartnerNoun(rt.partner, rt.kind);
  const partner = rt.partner;
  let firstDone = false;

  const renamePartner = async () => {
    const r = await _renameOneSide(partner.side, partner.idOrPath, rt.kind, n);
    _scheduleOpRefresh();
    if (r && r.error) {
      throw new Error(
        `The ${mine} is now "${n}". The ${theirs} is still "${partner.name}" `
        + `— renaming it failed: ${r.error}`);
    }
    return r;
  };

  opEnqueue({
    title: `Renaming both sides to "${n}"`,
    sub: `${_renameSentenceCase(mine)} and ${theirs}`,
    type: 'rename', pollBackend: false, undoable: false,
    run: async () => {
      const first = await _renameOneSide(rt.side, rt.idOrPath, rt.kind, n);
      if (first && first.error) {
        // Nothing has moved. Say that, so a failure here does not read as
        // the dangerous one below.
        throw new Error(`Nothing was renamed — the ${mine} rename failed: ${first.error}`);
      }
      firstDone = true;
      return renamePartner();
    },
    // Retry picks up where it stopped rather than repeating a rename that
    // already landed.
    retryFn: async () => (firstDone
      ? renamePartner()
      : _renameOneSide(rt.side, rt.idOrPath, rt.kind, n).then(r => {
          if (r && r.error) throw new Error(r.error);
          firstDone = true;
          return renamePartner();
        })),
  });
}

function startDelete(side, idOrPath, name, isDir, kind) {
  kind = kind || currentTab;
  deleteTarget = { side, idOrPath, kind, name };
  let warn;
  if (side === 'cloud') {
    // The details go in the dialog, because the list they would otherwise be
    // read from is greyed out behind it.
    _setDeleteWhat('deleteWhat',
      _deleteWhatHtml([_cloudDeleteEntry(idOrPath, name, kind === 'sites')]));
    warn = kind === 'sites'
      ? `This is a <b>whole site</b>. Projects inside it are not deleted. Once this runs it will not exist on Ekahau Cloud anymore, for anyone. There is no trash to recover it from.`
      : `Once this runs it will not exist on Ekahau Cloud anymore, for anyone. There is no trash to recover it from. Your local copy, if you have one, is not touched.`;
  } else {
    _setDeleteWhat('deleteWhat', '');
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
  document.getElementById('deleteTitle').textContent =
    side === 'cloud' ? 'Delete from Ekahau Cloud?' : 'Delete?';
  document.getElementById('deleteSub').innerHTML = warn;
  _setDeleteBtn(side === 'cloud' ? 'Delete from cloud' : 'Delete');
  showModal('deleteModal');
}

/* The red button is the safeguard, and the only one.

   Typing the word DELETE used to be required for every cloud deletion. It
   added no information - it could not tell him *which* project he had
   selected, which is the thing that actually protects him - and he deletes
   routinely: "even Ekahau doesn't do that, they just put up a nice modal that
   has a red delete button." Friction that conveys nothing trains people to
   click through the dialogs that do convey something.

   So: name the thing, say what happens to it, and offer a red button. */
function _setDeleteBtn(label) {
  const btn = document.getElementById('deleteBtn');
  if (btn) btn.textContent = label;
}
/* ---- Saying what is about to be destroyed -------------------------------

   The confirm dialog greys out the list behind it, so the row he was looking
   at is no longer readable - and he was relying on reading it to check he had
   the right one. His report: "it greys the background out so you can't
   remember what it is you're deleting to double check."

   Naming it in the dialog is the fix rather than lightening the backdrop,
   because a backdrop only works when the row happens to be on screen, not
   scrolled away, and not behind the dialog itself. A confirmation for an
   irreversible action should state what it will destroy without the reader
   having to look anywhere else.

   **Size is deliberately not shown**, for the reason `_row_meta` in
   `tools/cloud_manager.py` already gives: cloud projects are stored
   uncompressed and local `.esx` are ZIP-deflated, so the same project reads
   5-10x different. In a dialog whose whole job is "is this the one I mean?",
   a number that disagrees with the local file by a factor of eight is worse
   than no number. The site and the modified date are the discriminators that
   actually answer it, and they cannot mislead. */

function _cloudDetailsById(id) {
  if (!id || !data) return null;
  let found = null;
  const consider = (obj, siteName) => {
    if (found || !obj || obj.id !== id) return;
    found = { obj: obj, siteName: siteName || obj.siteName || '' };
  };
  // On the Projects tab a top-level entry is the project; on the Sites tab it
  // is a site carrying children. One walk covers both.
  const walk = (node) => {
    if (!node) return;
    consider(node, '');
    const kids = node.children;
    if (!kids) return;
    (kids.matched || []).forEach(p => consider(p.cloud, node.name));
    (kids.cloudOnly || []).forEach(c => consider(c, node.name));
  };
  (data.matched || []).forEach(p => walk(p.cloud));
  (data.cloudOnly || []).forEach(walk);
  return found;
}

function _sharedWithLine(cloudObj) {
  const me = ((data && data.currentUser) || '').toLowerCase();
  const others = ((cloudObj && cloudObj.sharedWith) || [])
    .map(x => String(x || '').toLowerCase())
    .filter(x => x && x !== me);
  if (!others.length) return null;
  // Deleting something other people are using is a different decision from
  // deleting something only you can see, so it is called out rather than
  // listed as one detail among several.
  // Every address, not three and a count. Who loses access is the decision,
  // and a decision cannot be made from "and 2 more".
  return 'Shared with ' + e(others.join(', ')) + ' — they will lose access';
}

function _deleteWhatRow(entry) {
  const bits = [];
  if (entry.siteName) bits.push('in ' + e(entry.siteName));
  if (entry.modified) bits.push(e(entry.modified));
  const shared = entry.sharedLine;
  return '<div class="delete-what-item">'
    + '<div class="delete-what-name">' + e(entry.name || 'Untitled') + '</div>'
    + (bits.length ? '<div class="delete-what-meta">' + bits.join(' · ') + '</div>' : '')
    + (shared ? '<div class="delete-what-shared">' + shared + '</div>' : '')
    + '</div>';
}

function _cloudDeleteEntry(id, fallbackName, isSite) {
  const hit = _cloudDetailsById(id);
  const obj = hit && hit.obj;
  return {
    name: (obj && obj.name) || fallbackName || id,
    siteName: isSite ? '' : (hit && hit.siteName) || '',
    // The row's own meta line is already "when it changed", formatted the way
    // the rest of the page formats it - so the dialog and the list agree.
    modified: (obj && obj.meta) || '',
    sharedLine: _sharedWithLine(obj),
    isSite: !!isSite,
  };
}

/* Every item, however many there are.

   This used to show eight and "and 12 more", which hid twelve of the things
   about to be destroyed to save vertical space. His rule: "it would be better
   if it was easily readable and lengthy than if it's brief in order to save
   screen real estate." The block scrolls; nothing is withheld. */
function _deleteWhatHtml(entries) {
  if (!entries || !entries.length) return '';
  return '<div class="delete-what-label">'
    + (entries.length === 1 ? 'You are deleting' : 'You are deleting ' + entries.length + ' items')
    + '</div>'
    + entries.map(_deleteWhatRow).join('');
}

/* Filling the "what you are deleting" block in whichever dialog needs it. */
function _setDeleteWhat(id, whatHtml) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = whatHtml || '';
  el.hidden = !whatHtml;
}

// ── Styled stand-in for window.confirm() ──
// The native dialog can't be styled, doesn't wrap a multi-part bulk-action
// summary cleanly, and vanishes with no trace once dismissed. Bulk actions
// (Sync) that need the user to actually read a breakdown before committing
// use this instead: showConfirmModal(title, bodyHtml, confirmLabel) -> Promise<boolean>.
let _pendingConfirmAction = null;
function showConfirmModal(title, bodyHtml, confirmLabel) {
  return new Promise(resolve => {
    _pendingConfirmAction = resolve;
    document.getElementById('confirmActionTitle').textContent = title;
    document.getElementById('confirmActionBody').innerHTML = bodyHtml;
    document.getElementById('confirmActionOkBtn').textContent = confirmLabel || 'Continue';
    showModal('confirmActionModal');
  });
}
function _resolveConfirmAction(result) {
  const resolve = _pendingConfirmAction;
  _pendingConfirmAction = null;
  closeModal('confirmActionModal');
  if (resolve) resolve(result);
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
      runBulk();
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
  runSingle();
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
    else if (r && r.syncedBack) toast('Uploaded and synced "' + name + '.esx"', 'success');
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
  /* An unpaired cloud project: the row has no local side, which is why this
     could not be marked at all until `_rowKey` stopped requiring both. */
  _setRowBusy(projectId, '', 'Downloading from Ekahau Cloud…');
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
  } catch (err) {
    toast(err.message || 'Download failed', 'error');
  } finally {
    _setRowBusy(projectId, '', null);
  }
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
  const seenSide = new Set();
  const targets = [...selected].flatMap(k => movableSidesOf(rowData[k]))
    .filter(sd => {
      const idk = sd.kind + ':' + (sd.id || sd.path);
      if (seenSide.has(idk)) return false;
      seenSide.add(idk);
      return true;
    })
    .map(sd => ({
      kind: sd.kind, id: sd.id, path: sd.path, name: sd.name,
      size: sd.size, owner: sd.owner,
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

  /* Through the ops deck, the same way auto-assign already queues its moves.

     This used to be a blocking for-await loop with its own tally, which meant
     a bulk move was the one operation in this tool with no card, no stage, no
     retry on a single failure and no cancel - and a second implementation of
     "assign a project to a site" sitting next to the queued one. The deck does
     all of that already.

     Creating a destination site is resolved first and awaited, because the
     moves that land in it need its id. Two rows aimed at the same new site
     create it once. */
  const newSiteByName = new Map();
  const needNew = new Set();
  plans.forEach(({ t, dest }) => {
    if (t.kind === 'cloud' && !dest.siteId && t.destValue === '__new__') {
      const key = (t.destNewName || '').trim();
      if (key) needNew.add(key);
    }
  });

  const createFailed = new Map();
  for (const key of needNew) {
    const { promise } = opEnqueue({
      title: `Creating cloud site "${key}"`,
      type: 'create', pollBackend: false, undoable: false,
      retryFn: async () => pyApi('create_site', key),
      run: async () => pyApi('create_site', key),
    });
    try {
      const r = await promise;
      if (r && r.error) { createFailed.set(key, r.error); continue; }
      newSiteByName.set(key, { id: r.id || r.siteId, folder: key });
    } catch (err) {
      createFailed.set(key, (err && err.message) || 'failed');
    }
  }

  const results = { ok: 0, failed: 0, skipped: 0, firstErr: '' };
  const dests = new Set();
  const waits = [];

  for (const { t, dest } of plans) {
    let siteId = dest.siteId;
    let folder = dest.folder;

    if (t.kind === 'cloud' && !siteId && t.destValue === '__new__') {
      const key = (t.destNewName || '').trim();
      const made = newSiteByName.get(key);
      if (!made) {
        // Its site could not be created, so this move has nowhere to go.
        results.skipped++;
        results.firstErr = results.firstErr
          || `couldn't create "${key}": ${createFailed.get(key) || 'failed'}`;
        continue;
      }
      siteId = made.id;
      folder = made.folder;
    }

    if (t.kind === 'cloud' && !siteId) {
      results.skipped++;
      results.firstErr = results.firstErr || 'destination site has no cloud counterpart';
      continue;
    }

    const label = t.name + (t.isDir ? '' : '.esx');
    const where = folder || dest.folder || 'site';
    const { promise } = opEnqueue({
      title: `Moving "${label}" to ${where}`,
      type: 'op', pollBackend: false, undoable: false,
      retryFn: async () => (t.kind === 'cloud'
        ? pyApi('assign_to_site', siteId, t.id)
        : pyApi('move_local_to_site', t.path, folder)),
      run: async () => (t.kind === 'cloud'
        ? pyApi('assign_to_site', siteId, t.id)
        : pyApi('move_local_to_site', t.path, folder)),
    });
    waits.push(promise.then(r => {
      if (r && r.error) {
        results.failed++;
        results.firstErr = results.firstErr || r.error;
        return;
      }
      results.ok++;
      dests.add(where);
    }).catch(err => {
      results.failed++;
      results.firstErr = results.firstErr || (err && err.message) || 'failed';
    }));
  }

  await Promise.all(waits);
  _reportMoveOutcome(results, dests);
  _scheduleOpRefresh();
}

/* Each move has its own card in the deck; this is the one line that says how
   the batch as a whole went. Three of five moving and the fourth failing must
   not leave him counting cards to work out which. */
function _reportMoveOutcome(results, dests) {
  const bits = [];
  if (results.ok) {
    bits.push(dests.size === 1
      ? `Moved ${results.ok} to ${[...dests][0]}`
      : `Moved ${results.ok} to ${dests.size} sites`);
  }
  if (results.failed) bits.push(`${results.failed} failed`);
  if (results.skipped) bits.push(`${results.skipped} skipped`);

  if (!results.failed && !results.skipped && results.ok) {
    toast(bits.join(' · '), 'success');
    return;
  }
  if (!results.ok) {
    toast(`Move failed: ${results.firstErr || 'nothing could be moved'}`, 'error');
    return;
  }
  toast(`${bits.join(' · ')} (${results.firstErr})`, 'error');
}


/* Clicking a bulk button that is off says what would switch it on.

   The gestures people actually make at a greyed control are hover and click,
   so both have to answer. The click is caught in the capture phase on the
   document, which is what stops the inline onclick underneath from running -
   a capture listener on an ancestor fires before the target's own handlers,
   and stopPropagation there keeps it from reaching them. */
/* The filter cards are divs with an onclick, so nothing but a mouse could
   reach them - and a `title` that only appears on hover is not reachable
   either. They are buttons to the accessibility tree now, and Enter or Space
   activates the one that has focus. */
function _wireFilterCardKeys() {
  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter' && ev.key !== ' ' && ev.key !== 'Spacebar') return;
    /* `.dash-card` again: this has matched nothing since v2.113.0, so the
       keyboard route these were given has been dead for as long as the
       filters have been buttons. A filter is found by what it filters. */
    const card = ev.target && ev.target.closest
      ? ev.target.closest('[data-filter]') : null;
    if (!card || typeof card.click !== 'function') return;
    ev.preventDefault();
    card.click();
  });
}
_wireFilterCardKeys();

/* Opening a site, from anywhere on its row.

   Delegated rather than per-row: the list is rebuilt constantly and
   ninety-eight inline handlers would be ninety-eight things to keep in step.

   What it must not swallow: the checkbox, the row menu, and every button or
   link inside the row. Those already mean something, and a control that
   sometimes does its own job and sometimes opens a site is worse than no
   control. */
function _wireRowToggle() {
  const owns = (target) => {
    if (!target || !target.closest) return null;
    if (target.closest('input, button, a, label, summary, details, .row-menu')) return null;
    const row = target.closest('.ledger-row.is-openable');
    return (row && row.dataset.toggle) ? row : null;
  };

  document.addEventListener('click', (ev) => {
    const row = owns(ev.target);
    if (!row) return;
    ev.preventDefault();
    toggleFolder(row.dataset.toggle);
  });

  /* A single click toggles, so a double click would toggle twice and land
     back where it started - which reads as the row being broken. */
  document.addEventListener('dblclick', (ev) => {
    if (owns(ev.target)) { ev.preventDefault(); ev.stopPropagation(); }
  });

  //: It is the primary control on the page, so it answers the keyboard.
  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter' && ev.key !== ' ' && ev.key !== 'Spacebar') return;
    const row = owns(ev.target);
    if (!row) return;
    ev.preventDefault();
    toggleFolder(row.dataset.toggle);
  });
}
_wireRowToggle();

function _wireDisabledBulkReasons() {
  document.addEventListener('click', (ev) => {
    const btn = ev.target && ev.target.closest
      /* `.rd-btn.is-disabled` joined this when the refused actions moved out
         of the middle lane and into the band under the row. A disabled
         attribute would swallow the click, and the click is how he asks why. */
      ? ev.target.closest('.bulk-btn.is-disabled, .gut-arrow.is-disabled, .rd-btn.is-disabled') : null;
    if (!btn) return;
    ev.preventDefault();
    ev.stopPropagation();
    toast(btn.title || 'Select some rows first', 'info');
  }, true);
}
_wireDisabledBulkReasons();

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
