/* WD Quick Walls — page logic */

// Alias for backward compat with ~40 call sites
const showToast = WD.toast;

// ── State ──
let esxZip = null;
let wallTypes = [];
let fileName = '';
let _originalIdMap = {};

function preserveId(wt) {
  return _originalIdMap[wt.key] || wt.id || crypto.randomUUID();
}
let editingIndex = -1;
let openMenuIndex = -1;

// ── File Loading ──
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');

dropzone.addEventListener('click', () => fileInput.click());
dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('dragover'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
dropzone.addEventListener('drop', e => {
  e.preventDefault();
  dropzone.classList.remove('dragover');
  if (e.dataTransfer.files.length) loadFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', e => { if (e.target.files.length) loadFile(e.target.files[0]); });

function loadNewFile() {
  fileInput.value = '';
  fileInput.click();
}

async function loadFile(file) {
  if (!file.name.endsWith('.esx')) {
    showToast('Not an .esx file');
    return;
  }
  try {
    const data = await file.arrayBuffer();
    esxZip = await JSZip.loadAsync(data);
    fileName = file.name;

    const wtFile = esxZip.file('wallTypes.json');
    if (wtFile) {
      const wtJson = JSON.parse(await wtFile.async('string'));
      wallTypes = wtJson.wallTypes || [];
      _originalIdMap = {};
      wallTypes.forEach(wt => { if (wt.key && wt.id) _originalIdMap[wt.key] = wt.id; });
    } else {
      wallTypes = [];
      try {
        if (!_ekahauDefaults) {
          const r = await tplApi('defaults');
          if (r.ok) _ekahauDefaults = { name: 'Ekahau Defaults', wallTypes: r.wallTypes };
        }
        if (_ekahauDefaults) {
          wallTypes = _ekahauDefaults.wallTypes.map(wt => ({
            ...JSON.parse(JSON.stringify(wt)),
            id: crypto.randomUUID(),
          }));
          showToast('No wall types found — loaded Ekahau Defaults (' + wallTypes.length + ' types)', 'success');
        } else {
          showToast('No wall types in this project — starting empty', 'success');
        }
      } catch (e) {
        console.warn('Could not load Ekahau defaults:', e);
        showToast('No wall types in this project — starting empty', 'success');
      }
    }

    dropzone.style.display = 'none';
    document.getElementById('dzTopbar').style.display = 'none';
    document.getElementById('editor').classList.add('active');
    document.getElementById('fileBadge').textContent = fileName;
    document.getElementById('fileBadge').style.display = 'inline';
    renderAll();
    tryAutoApply();
  } catch (err) {
    showToast('Error reading file: ' + err.message);
    console.error(err);
  }
}

// ── Helpers ──
function getKeybindMap() {
  const map = {};
  wallTypes.forEach(wt => {
    if (wt.keybindNumber >= 1 && wt.keybindNumber <= 9) {
      map[wt.keybindNumber] = wt;
    }
  });
  return map;
}

function assignKeybind(wallIndex, num) {
  if (num) {
    wallTypes.forEach(wt => {
      if (wt.keybindNumber === num) delete wt.keybindNumber;
    });
    wallTypes[wallIndex].keybindNumber = num;
  } else {
    delete wallTypes[wallIndex].keybindNumber;
  }
  renderAll();
}

function clearKeybind(num) {
  wallTypes.forEach(wt => {
    if (wt.keybindNumber === num) delete wt.keybindNumber;
  });
  renderAll();
}

// ── Rendering ──
function renderAll() {
  renderHotkeyPanel();
  renderList();
}

function renderHotkeyPanel() {
  const container = document.getElementById('hotkeySlots');
  const map = getKeybindMap();

  let html = '';
  for (let n = 1; n <= 9; n++) {
    const wt = map[n];
    if (wt) {
      html += `
        <div class="hotkey-slot"
             ondragover="onSlotDragOver(event, ${n})"
             ondragleave="onSlotDragLeave(event)"
             ondrop="onSlotDrop(event, ${n})">
          <span class="hotkey-swatch" style="background:${wt.color || '#666'}"></span>
          <div class="hotkey-num">${n}</div>
          <div class="hotkey-name">${esc(wt.name)}</div>
          <button class="hotkey-clear" onclick="clearKeybind(${n})" title="Remove shortcut">&times;</button>
        </div>`;
    } else {
      html += `
        <div class="hotkey-slot"
             ondragover="onSlotDragOver(event, ${n})"
             ondragleave="onSlotDragLeave(event)"
             ondrop="onSlotDrop(event, ${n})">
          <div class="hotkey-num">${n}</div>
          <div class="hotkey-empty">drag here</div>
          <div></div>
        </div>`;
    }
  }
  container.innerHTML = html;
}

function renderList() {
  const list = document.getElementById('wallList');
  const sorted = [...wallTypes].sort((a, b) => (a.name || '').localeCompare(b.name || '', undefined, { sensitivity: 'base' }));
  document.getElementById('wallCount').textContent = wallTypes.length + ' wall type' + (wallTypes.length !== 1 ? 's' : '');

  let html = '';
  sorted.forEach((wt, _si) => {
    const i = wallTypes.indexOf(wt);
    const bands = wt.propagationProperties || [];
    const getBand = (name) => bands.find(b => b.band === name) || {};
    const two = getBand('TWO');
    const five = getBand('FIVE');
    const six = getBand('SIX');
    const att2 = two.attenuationFactor ?? '—';
    const att5 = five.attenuationFactor ?? '—';
    const att6 = six.attenuationFactor ?? '—';
    const kb = wt.keybindNumber;
    const kbBadge = kb ? `<span class="wall-keybind-badge">[${kb}]</span>` : '';

    html += `
      <div class="wall-card" draggable="true"
           ondragstart="onCardDragStart(event, ${i})"
           ondragend="onCardDragEnd(event)">
        <div class="wall-swatch" style="background:${wt.color || '#666'}"></div>
        <div class="wall-info">
          <div class="wall-name-row">
            <span class="wall-name">${esc(wt.name)}</span>
            ${kbBadge}
          </div>
          <div class="wall-meta">
            <span><span class="label">2.4:</span> ${att2}</span>
            <span><span class="label">5:</span> ${att5}</span>
            <span><span class="label">6:</span> ${att6}</span>
            <span><span class="label">thick:</span> ${wt.thickness}m</span>
          </div>
        </div>
        <div class="wall-actions">
          <button class="btn btn-sm" onclick="showKeybindMenu(event, ${i})" title="Assign shortcut">#</button>
          <button class="btn btn-icon btn-sm" onclick="openEditModal(${i})" title="Edit">&#9998;</button>
          <button class="btn btn-icon btn-sm btn-danger" onclick="deleteWall(${i})" title="Delete">&times;</button>
        </div>
      </div>`;
  });

  list.innerHTML = html;
}

// ── Drag cards to hotkey slots ──
let dragCardIndex = -1;

function onCardDragStart(e, i) {
  dragCardIndex = i;
  e.currentTarget.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', i.toString());
}

function onCardDragEnd(e) {
  dragCardIndex = -1;
  document.querySelectorAll('.wall-card').forEach(c => c.classList.remove('dragging'));
  document.querySelectorAll('.hotkey-slot').forEach(s => s.classList.remove('dragover'));
}

function onSlotDragOver(e, num) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  e.currentTarget.classList.add('dragover');
}

function onSlotDragLeave(e) {
  e.currentTarget.classList.remove('dragover');
}

function onSlotDrop(e, num) {
  e.preventDefault();
  e.currentTarget.classList.remove('dragover');
  if (dragCardIndex >= 0) {
    assignKeybind(dragCardIndex, num);
    showToast(`Assigned [${num}] to ${wallTypes[dragCardIndex].name}`, 'success');
  }
}

// ── Keybind Menu ──
function showKeybindMenu(e, wallIndex) {
  e.stopPropagation();
  closeKeybindMenus();
  const map = getKeybindMap();
  const currentKb = wallTypes[wallIndex].keybindNumber;

  const menu = document.createElement('div');
  menu.className = 'keybind-menu open';
  menu.style.position = 'fixed';
  menu.style.zIndex = '200';

  const rect = e.currentTarget.getBoundingClientRect();
  menu.style.top = (rect.bottom + 4) + 'px';
  menu.style.right = (window.innerWidth - rect.right) + 'px';

  for (let n = 1; n <= 9; n++) {
    const taken = map[n];
    const isCurrent = currentKb === n;
    const btn = document.createElement('button');
    btn.className = 'keybind-option';
    let label = `<span class="num">[${n}]</span>`;
    if (isCurrent) {
      label += ' Current';
    } else if (taken) {
      label += ` <span class="taken">(${esc(taken.name)})</span>`;
    } else {
      label += ' Available';
    }
    btn.innerHTML = label;
    btn.onclick = () => {
      assignKeybind(wallIndex, n);
      closeKeybindMenus();
      showToast(`Assigned [${n}] to ${wallTypes[wallIndex].name}`, 'success');
    };
    menu.appendChild(btn);
  }

  if (currentKb) {
    const sep = document.createElement('div');
    sep.style.borderTop = '1px solid var(--border)';
    sep.style.margin = '4px 0';
    menu.appendChild(sep);
    const clr = document.createElement('button');
    clr.className = 'keybind-option clear-opt';
    clr.textContent = 'Remove shortcut';
    clr.onclick = () => {
      assignKeybind(wallIndex, null);
      closeKeybindMenus();
    };
    menu.appendChild(clr);
  }

  document.body.appendChild(menu);
  openMenuIndex = wallIndex;

  setTimeout(() => {
    document.addEventListener('click', closeKeybindMenus, { once: true });
  }, 0);
}

function closeKeybindMenus() {
  document.querySelectorAll('.keybind-menu').forEach(m => m.remove());
  openMenuIndex = -1;
  const dz = document.getElementById('dzMenu');
  if (dz) dz.classList.remove('open');
}

// ── Delete ──
function deleteWall(i) {
  const name = wallTypes[i].name;
  if (confirm('Remove "' + name + '"?')) {
    wallTypes.splice(i, 1);
    renderAll();
  }
}

// ── Add / Edit Modal ──
function openAddModal() {
  editingIndex = -1;
  document.getElementById('modalTitle').textContent = 'Add Wall Type';
  document.getElementById('modalSaveBtn').textContent = 'Add';
  document.getElementById('fName').value = '';
  document.getElementById('fColor').value = '#808080';
  document.getElementById('fThickness').value = '0.1';
  document.getElementById('fTwoAtt').value = '30';
  document.getElementById('fTwoRef').value = '0.1111';
  document.getElementById('fTwoDif').value = '11';
  document.getElementById('fFiveAtt').value = '30';
  document.getElementById('fFiveRef').value = '0.1111';
  document.getElementById('fFiveDif').value = '11';
  document.getElementById('fSixAtt').value = '30';
  document.getElementById('fSixRef').value = '0.1111';
  document.getElementById('fSixDif').value = '11';
  populateKeybindSelect(null);
  document.getElementById('modal').classList.add('active');
  document.getElementById('fName').focus();
}

function openEditModal(i) {
  editingIndex = i;
  const wt = wallTypes[i];
  document.getElementById('modalTitle').textContent = 'Edit Wall Type';
  document.getElementById('modalSaveBtn').textContent = 'Save';
  document.getElementById('fName').value = wt.name;
  document.getElementById('fColor').value = wt.color || '#808080';
  document.getElementById('fThickness').value = wt.thickness;

  const bands = wt.propagationProperties || [];
  const getBand = (name) => bands.find(b => b.band === name) || {};
  const two = getBand('TWO');
  const five = getBand('FIVE');
  const six = getBand('SIX');

  document.getElementById('fTwoAtt').value = two.attenuationFactor ?? 0;
  document.getElementById('fTwoRef').value = two.reflectionCoefficient ?? 0;
  document.getElementById('fTwoDif').value = two.diffractionCoefficient ?? 0;
  document.getElementById('fFiveAtt').value = five.attenuationFactor ?? 0;
  document.getElementById('fFiveRef').value = five.reflectionCoefficient ?? 0;
  document.getElementById('fFiveDif').value = five.diffractionCoefficient ?? 0;
  document.getElementById('fSixAtt').value = six.attenuationFactor ?? 0;
  document.getElementById('fSixRef').value = six.reflectionCoefficient ?? 0;
  document.getElementById('fSixDif').value = six.diffractionCoefficient ?? 0;

  populateKeybindSelect(wt.keybindNumber || null);
  document.getElementById('modal').classList.add('active');
  document.getElementById('fName').focus();
}

function populateKeybindSelect(current) {
  const sel = document.getElementById('fKeybind');
  const map = getKeybindMap();
  sel.innerHTML = '<option value="">None</option>';
  for (let n = 1; n <= 9; n++) {
    const taken = map[n];
    const isCurrent = current === n;
    let label = `[${n}]`;
    if (isCurrent) label += ' (current)';
    else if (taken) label += ` (${taken.name})`;
    const opt = document.createElement('option');
    opt.value = n;
    opt.textContent = label;
    if (isCurrent) opt.selected = true;
    sel.appendChild(opt);
  }
}

function saveWallType() {
  const name = document.getElementById('fName').value.trim();
  if (!name) { showToast('Name is required'); return; }

  const keybindVal = document.getElementById('fKeybind').value;
  const keybindNum = keybindVal ? parseInt(keybindVal) : null;

  const existing = editingIndex >= 0 ? wallTypes[editingIndex] : {};
  const wt = {
    ...existing,
    name: name,
    key: existing.key || name.replace(/[^a-zA-Z0-9]/g, ''),
    color: document.getElementById('fColor').value,
    thickness: parseFloat(document.getElementById('fThickness').value) || 0.1,
    lowerEdge: existing.lowerEdge ?? 0.0,
    id: existing.id || crypto.randomUUID(),
    status: existing.status || 'CREATED',
    propagationProperties: [
      {
        band: 'FIVE',
        attenuationFactor: parseFloat(document.getElementById('fFiveAtt').value) || 0,
        reflectionCoefficient: parseFloat(document.getElementById('fFiveRef').value) || 0,
        diffractionCoefficient: parseFloat(document.getElementById('fFiveDif').value) || 0,
      },
      {
        band: 'SIX',
        attenuationFactor: parseFloat(document.getElementById('fSixAtt').value) || 0,
        reflectionCoefficient: parseFloat(document.getElementById('fSixRef').value) || 0,
        diffractionCoefficient: parseFloat(document.getElementById('fSixDif').value) || 0,
      },
      {
        band: 'TWO',
        attenuationFactor: parseFloat(document.getElementById('fTwoAtt').value) || 0,
        reflectionCoefficient: parseFloat(document.getElementById('fTwoRef').value) || 0,
        diffractionCoefficient: parseFloat(document.getElementById('fTwoDif').value) || 0,
      },
    ],
  };

  if (keybindNum) {
    wallTypes.forEach(w => {
      if (w.keybindNumber === keybindNum && w !== existing) delete w.keybindNumber;
    });
    wt.keybindNumber = keybindNum;
  } else {
    delete wt.keybindNumber;
  }

  if (editingIndex >= 0) {
    wallTypes[editingIndex] = wt;
  } else {
    wallTypes.push(wt);
  }

  closeModal();
  renderAll();
  showToast(editingIndex >= 0 ? 'Updated' : 'Added "' + name + '"', 'success');
}

// ── Save .esx (with native file picker when available) ──
async function nativeSave(blob, suggestedName, description, acceptTypes) {
  if (window.showSaveFilePicker) {
    try {
      const handle = await window.showSaveFilePicker({
        suggestedName,
        types: [{ description, accept: acceptTypes }],
      });
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
      return 'saved';
    } catch (err) {
      if (err.name === 'AbortError') return 'cancelled';
      console.warn('Save picker failed, falling back:', err);
    }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = suggestedName;
  document.body.appendChild(a);
  a.click();
  a.remove();

  await new Promise(resolve => {
    let blurred = false;
    const onBlur = () => { blurred = true; };
    const onFocus = () => {
      if (blurred) {
        window.removeEventListener('blur', onBlur);
        window.removeEventListener('focus', onFocus);
        clearTimeout(timeout);
        resolve();
      }
    };
    window.addEventListener('blur', onBlur);
    window.addEventListener('focus', onFocus);
    const timeout = setTimeout(() => {
      window.removeEventListener('blur', onBlur);
      window.removeEventListener('focus', onFocus);
      resolve();
    }, 2000);
  });

  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return 'downloaded';
}

async function saveEsx() {
  if (!esxZip) return;

  const saveTypes = wallTypes.map(wt => {
    const copy = { ...wt };
    if (!(copy.keybindNumber >= 1 && copy.keybindNumber <= 9)) {
      delete copy.keybindNumber;
    }
    return copy;
  });
  const wtJson = JSON.stringify({ wallTypes: saveTypes }, null, 2);
  esxZip.file('wallTypes.json', wtJson);

  const blob = await esxZip.generateAsync({ type: 'blob', compression: 'DEFLATE' });
  const defaultName = fileName.replace('.esx', '_modified.esx');
  const result = await nativeSave(blob, defaultName, 'Ekahau Project File', { 'application/octet-stream': ['.esx'] });
  if (result === 'saved') {
    showToast('Saved ' + defaultName, 'success');
  } else if (result === 'downloaded') {
    showToast('Downloading ' + defaultName + ' — check your browser downloads', 'success');
  }
}

// ── Templates (server-backed on desktop; localStorage-backed when hosted) ──

let _tplCache = [];

// window.WD_HOSTED is set by the GitHub Pages build (see .github/workflows/pages.yml).
// It swaps the server round-trip for a localStorage-backed shim so the tool works
// standalone in someone else's browser with zero install.
const HOSTED = typeof window !== 'undefined' && !!window.WD_HOSTED;

async function tplApi(action, data = {}) {
  if (HOSTED) return _hostedTplApi(action, data);
  const r = await fetch(`/api/templates/${action}`, {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data)
  });
  return r.json();
}

async function _hostedTplApi(action, data) {
  const KEY = 'wd-hosted-templates';
  const loadAll = () => {
    try { return JSON.parse(localStorage.getItem(KEY)) || []; }
    catch (e) { return []; }
  };
  const saveAll = ts => localStorage.setItem(KEY, JSON.stringify(ts));

  if (action === 'scan') {
    let ts = loadAll();
    if (!ts.length) {
      // First run — seed with "Recommended by WD" so users see something useful.
      try {
        const r = await fetch('../templates/Recommended%20by%20WD_walltemplate.json');
        if (r.ok) { ts = [await r.json()]; saveAll(ts); }
      } catch (e) { /* seed is best-effort */ }
    }
    return { ok: true, templates: ts };
  }
  if (action === 'defaults') {
    try {
      const r = await fetch('../templates/ekahau_defaults.json');
      const d = await r.json();
      return { ok: true, wallTypes: d.wallTypes || d };
    } catch (e) { return { ok: false, error: 'Could not load Ekahau defaults' }; }
  }
  if (action === 'save') {
    const ts = loadAll();
    const rec = { name: data.name, wallTypes: data.wallTypes,
                  created: new Date().toISOString() };
    const i = ts.findIndex(t => t.name === data.name);
    if (i >= 0) ts[i] = rec; else ts.push(rec);
    saveAll(ts);
    return { ok: true };
  }
  if (action === 'delete') {
    const ts = loadAll().filter(t => t.name !== data.name);
    saveAll(ts);
    return { ok: true };
  }
  if (action === 'get_folder') {
    return { ok: true, folder: 'browser localStorage (hosted)', exists: true };
  }
  return { ok: false, error: 'unknown action: ' + action };
}

async function loadTemplatesFromServer() {
  try {
    const r = await tplApi('scan');
    if (r.ok) { _tplCache = r.templates || []; }
    return _tplCache;
  } catch { return _tplCache; }
}

function getTemplates() {
  return _tplCache;
}

function saveAsTemplate() {
  if (!wallTypes.length) { showToast('No wall types to save'); return; }
  document.getElementById('tplSaveCount').textContent = wallTypes.length;
  document.getElementById('tplSaveName').value = '';
  document.getElementById('saveTplModal').classList.add('active');
  document.getElementById('tplSaveName').focus();
}

function closeSaveTplModal() {
  document.getElementById('saveTplModal').classList.remove('active');
}

async function confirmSaveTemplate() {
  const name = document.getElementById('tplSaveName').value.trim();
  if (!name) { showToast('Name is required'); return; }

  const existing = _tplCache.find(t => t.name === name);
  if (existing) {
    if (!confirm(`Template "${name}" already exists. Overwrite?`)) return;
  }

  const r = await tplApi('save', {
    name: name,
    wallTypes: JSON.parse(JSON.stringify(wallTypes)),
  });

  if (!r.ok) { showToast('Save failed: ' + (r.error || 'unknown error')); return; }

  closeSaveTplModal();
  await loadTemplatesFromServer();
  refreshTemplateBar();
  showToast(`Template "${name}" saved to templates folder (${wallTypes.length} types)`, 'success');
}

async function openTemplateModal() {
  const info = await tplApi('get_folder');
  const el = document.getElementById('tplFolderInfo');
  if (info.ok) {
    el.innerHTML = `<strong>Folder:</strong> ${esc(info.folder)}${info.exists ? '' : ' <em>(will be created on first save)</em>'}`;
  }
  const sel = document.getElementById('templateSelect');
  document.getElementById('tplExportBtn').disabled = !sel.value;
  document.getElementById('tplModal').classList.add('active');
}

async function exportSelectedTemplate() {
  const sel = document.getElementById('templateSelect');
  const name = sel.value;
  if (!name) { showToast('Select a template from the dropdown first'); return; }
  const tpl = _tplCache.find(t => t.name === name);
  if (!tpl) { showToast('Template not found'); return; }

  const exportData = { name: tpl.name, created: tpl.created, wallTypes: tpl.wallTypes };
  const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
  const suggestedName = tpl.name.replace(/[^a-zA-Z0-9_-]/g, '_') + '_walltemplate.json';
  await nativeSave(blob, suggestedName, 'Wall Template', { 'application/json': ['.json'] });
  showToast(`Exported "${tpl.name}"`, 'success');
}

function closeTplModal() {
  document.getElementById('tplModal').classList.remove('active');
  refreshTemplateBar();
}

document.getElementById('tplImportInput').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    const text = await file.text();
    const tpl = JSON.parse(text);
    if (!tpl.name || !Array.isArray(tpl.wallTypes)) {
      showToast('Invalid template file — must have "name" and "wallTypes"');
      return;
    }
    const r = await tplApi('save', { name: tpl.name, wallTypes: tpl.wallTypes });
    if (!r.ok) { showToast('Import failed: ' + (r.error || 'unknown')); return; }

    await loadTemplatesFromServer();
    refreshTemplateBar();
    showToast(`Imported "${tpl.name}" (${tpl.wallTypes.length} types)`, 'success');
  } catch (err) {
    showToast('Error importing: ' + err.message);
  }
  e.target.value = '';
});

// ── Landing Menu ──
function toggleDzMenu(e) {
  WD.toggleMenu(e, 'dzMenu');
}

// ── Help Menu ──
function toggleHelpMenu(e) {
  WD.toggleMenu(e, 'helpMenu');
}

// ── About Modal ──
function openAboutModal() {
  document.getElementById('helpMenu').classList.remove('open');
  showModal('aboutModal');
}
function closeAboutModal() {
  closeModal('aboutModal');
}

// ── Template Bar (dropdown selector + auto-apply) ──
const DEFAULT_TPL_KEY = 'ekahau-default-template';
const AUTO_APPLY_KEY = 'ekahau-auto-apply';

function getDefaultTemplate() {
  try { return JSON.parse(localStorage.getItem(DEFAULT_TPL_KEY)); }
  catch { return null; }
}
function setDefaultTemplate(nameOrIndex) {
  let name = nameOrIndex;
  if (typeof nameOrIndex === 'number') {
    const tpls = getTemplates();
    name = tpls[nameOrIndex]?.name || null;
  }
  if (name) localStorage.setItem(DEFAULT_TPL_KEY, JSON.stringify(name));
  else localStorage.removeItem(DEFAULT_TPL_KEY);
  refreshTemplateBar();
  if (name) showToast(`"${name}" set as default template`, 'success');
}
function getLastTemplate() { return getDefaultTemplate(); }
function setLastTemplate(name) {
  localStorage.setItem(DEFAULT_TPL_KEY, JSON.stringify(name));
  refreshTemplateBar();
}

function getAutoApply() {
  return localStorage.getItem(AUTO_APPLY_KEY) === 'true';
}
function toggleAutoApply() {
  const checked = document.getElementById('autoApplyCheck').checked;
  localStorage.setItem(AUTO_APPLY_KEY, checked ? 'true' : 'false');
  if (checked) showToast('Template will auto-apply on next file open', 'success');
}

let _ekahauDefaults = null;

async function refreshTemplateBar() {
  await loadTemplatesFromServer();

  if (!_ekahauDefaults) {
    const r = await tplApi('defaults');
    if (r.ok) _ekahauDefaults = { name: 'Ekahau Defaults', wallTypes: r.wallTypes };
  }

  const sel = document.getElementById('templateSelect');
  const tpls = _tplCache;
  const def = getDefaultTemplate() || 'Recommended by WD';

  let html = '';

  const wd = tpls.find(t => t.name === 'Recommended by WD');
  if (wd) {
    const selected = def === wd.name ? ' selected' : '';
    html += `<option value="${esc(wd.name)}"${selected}>${esc(wd.name)} (${wd.wallTypes.length} types) ⭐</option>`;
  }

  if (_ekahauDefaults) {
    const selected = def === 'Ekahau Defaults' ? ' selected' : '';
    html += `<option value="Ekahau Defaults"${selected}>Ekahau Defaults (${_ekahauDefaults.wallTypes.length} types)</option>`;
  }

  const userTpls = tpls.filter(t => t.name !== 'Recommended by WD');
  if (userTpls.length > 0) {
    html += '<option disabled>───────────────</option>';
    userTpls.forEach(t => {
      const selected = t.name === def ? ' selected' : '';
      html += `<option value="${esc(t.name)}"${selected}>${esc(t.name)} (${t.wallTypes.length} types)</option>`;
    });
  }

  sel.innerHTML = html;

  document.getElementById('autoApplyCheck').checked = getAutoApply();

  const selected = sel.value;
  const applyBtn = document.getElementById('tplApplyBtn');
  applyBtn.disabled = !selected || selected === '';
}

async function applySelectedTemplate() {
  const sel = document.getElementById('templateSelect');
  const name = sel.value;
  if (!name) return;

  let newTypes = null;

  if (name === 'Ekahau Defaults') {
    if (!_ekahauDefaults) {
      showToast('Ekahau defaults not loaded');
      return;
    }
    newTypes = _ekahauDefaults.wallTypes;
  } else {
    const tpls = getTemplates();
    const tpl = tpls.find(t => t.name === name);
    if (!tpl) { showToast('Template not found'); return; }
    newTypes = tpl.wallTypes;
  }

  if (!newTypes || !newTypes.length) {
    showToast('Template has no wall types');
    return;
  }

  wallTypes = newTypes.map(wt => ({
    ...JSON.parse(JSON.stringify(wt)),
    id: preserveId(wt)
  }));

  renderAll();
  showToast(`Applied "${name}" (${wallTypes.length} types)`, 'success');
  setLastTemplate(name);
}

async function tryAutoApply() {
  await refreshTemplateBar();

  if (!getAutoApply()) return;

  const def = getDefaultTemplate();
  if (!def) return;

  const tpls = getTemplates();
  let newTypes = null;

  if (def === 'Ekahau Defaults') {
    if (_ekahauDefaults) newTypes = _ekahauDefaults.wallTypes;
  } else {
    const tpl = tpls.find(t => t.name === def);
    if (tpl) newTypes = tpl.wallTypes;
  }

  if (!newTypes || !newTypes.length) return;

  wallTypes = newTypes.map(wt => ({
    ...JSON.parse(JSON.stringify(wt)),
    id: preserveId(wt)
  }));

  renderAll();
  showToast(`Auto-applied "${def}" (${wallTypes.length} types)`, 'success');
}

function resetToEkahauDefaults() {
  if (!_ekahauDefaults) {
    showToast('Ekahau defaults not loaded yet');
    return;
  }
  if (!confirm('Reset all wall types to Ekahau factory defaults? This will replace your current wall types.')) return;

  wallTypes = _ekahauDefaults.wallTypes.map(wt => ({
    ...JSON.parse(JSON.stringify(wt)),
    id: preserveId(wt)
  }));

  renderAll();
  showToast(`Reset to Ekahau defaults (${wallTypes.length} types)`, 'success');
}

function onTemplateSelectChange() {
  const sel = document.getElementById('templateSelect');
  const applyBtn = document.getElementById('tplApplyBtn');
  applyBtn.disabled = !sel.value || sel.value === '';
}
