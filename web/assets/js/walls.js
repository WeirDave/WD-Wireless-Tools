const showToast = WD.toast;

const M_TO_IN = 39.3700787;
function detectDefaultUnits() {
  try {
    const lang = (navigator.language || 'en-US').toLowerCase();
    return lang.startsWith('en-us') ? 'imperial' : 'metric';
  } catch (e) { return 'metric'; }
}
/* Quick Walls preferences: units, default template, auto-apply.

   These were per-browser, because Quick Walls also ran hosted on GitHub Pages
   with no server to save to. Hosted mode is retired, so the fallback is gone
   and all three live in settings.json like every other preference - the same
   whichever browser you open, and untouched by an update.

   The browser copy is the value this machine was actually using, so on first
   run it wins over the saved default and is written through; the local key is
   deleted only once that write has succeeded. */
const LEGACY_UNITS_KEY = 'wd-walls-units';
const LEGACY_DEFAULT_TPL_KEY = 'ekahau-default-template';
const LEGACY_AUTO_APPLY_KEY = 'ekahau-auto-apply';

let _wallUnits = null;          // null until the settings file has been read
let _defaultTemplate = null;
let _autoApply = false;

function _readLegacy(key) {
  try { return localStorage.getItem(key); } catch (e) { return null; }
}

function _persistWallsPref(patch) {
  if (!window.WD || !WD.api) return Promise.resolve(false);
  return WD.api('settings/update', { patch: { walls: patch } })
    .then(r => !!(r && r.ok))
    .catch(() => false);
}

async function loadWallsPrefs() {
  const legacyUnits = _readLegacy(LEGACY_UNITS_KEY);
  const legacyTpl = _readLegacy(LEGACY_DEFAULT_TPL_KEY);
  const legacyAuto = _readLegacy(LEGACY_AUTO_APPLY_KEY);

  let saved = {};
  if (window.WD && WD.api) {
    try {
      const r = await WD.api('settings/get');
      if (r && r.ok && r.settings && r.settings.walls) saved = r.settings.walls;
    } catch (e) { /* no server or unreadable - fall through to defaults */ }
  }

  const savedUnits = (saved.units === 'imperial' || saved.units === 'metric') ? saved.units : '';
  const savedTpl = typeof saved.default_template === 'string' ? saved.default_template : '';
  const savedAuto = saved.auto_apply_template === true;

  // The browser copy wins where it exists.
  const legacyUnitsValid = (legacyUnits === 'imperial' || legacyUnits === 'metric');
  _wallUnits = legacyUnitsValid ? legacyUnits : (savedUnits || null);

  let legacyTplName = null;
  if (legacyTpl !== null) {
    try {
      const v = JSON.parse(legacyTpl);
      if (typeof v === 'string' && v) legacyTplName = (v === 'Recommended by WD') ? 'WD Template' : v;
    } catch (e) { /* unparseable - treat as absent */ }
  }
  _defaultTemplate = legacyTplName || savedTpl || null;
  _autoApply = legacyAuto !== null ? (legacyAuto === 'true') : savedAuto;

  const patch = {};
  if ((_wallUnits || '') !== savedUnits) patch.units = _wallUnits || '';
  if ((_defaultTemplate || '') !== savedTpl) patch.default_template = _defaultTemplate || '';
  if (_autoApply !== savedAuto) patch.auto_apply_template = _autoApply;

  const nothingToWrite = !Object.keys(patch).length;
  const written = nothingToWrite ? true : await _persistWallsPref(patch);

  if (written) {
    for (const k of [LEGACY_UNITS_KEY, LEGACY_DEFAULT_TPL_KEY, LEGACY_AUTO_APPLY_KEY]) {
      try { localStorage.removeItem(k); } catch (e) {}
    }
  }

  try { syncUnitToggleUI(); } catch (e) {}
  return { units: _wallUnits, defaultTemplate: _defaultTemplate,
           autoApply: _autoApply, migrated: !nothingToWrite && written };
}

function wallUnits() {
  return _wallUnits || detectDefaultUnits();
}
function mToDisplay(m) {
  return wallUnits() === 'imperial' ? (m * M_TO_IN) : m;
}
function displayToM(v) {
  const n = parseFloat(v);
  if (!Number.isFinite(n)) return 0.1;
  return wallUnits() === 'imperial' ? (n / M_TO_IN) : n;
}
window.setWallUnits = function (units) {
  if (units !== 'imperial' && units !== 'metric') return;
  const inp = document.getElementById('fThickness');
  const isOpen = document.getElementById('modal')?.classList.contains('active');
  let currentMeters = null;
  // Heights are held in metres across the switch too, or toggling in/m mid-edit
  // would reinterpret 12 ft as 12 m.
  const topEl = document.getElementById('fUpperEdge');
  const lowEl = document.getElementById('fLowerEdge');
  let topM = null, lowM = null;
  if (isOpen && inp) currentMeters = displayToM(inp.value);
  if (isOpen && topEl && topEl.value !== '') topM = heightToM(topEl.value);
  if (isOpen && lowEl && lowEl.value !== '') lowM = heightToM(lowEl.value);
  _wallUnits = units;
  _persistWallsPref({ units: units });
  syncUnitToggleUI();
  if (isOpen && inp && currentMeters != null) {
    inp.value = fmtThickness(mToDisplay(currentMeters));
  }
  if (isOpen && topEl && topM != null) topEl.value = fmtHeight(mToHeight(topM));
  if (isOpen && lowEl && lowM != null) lowEl.value = fmtHeight(mToHeight(lowM));
  if (isOpen) updateVertSummary();
  renderList();
};
function syncUnitToggleUI() {
  const u = wallUnits();
  document.querySelectorAll('.unit-btn').forEach(b => {
    const on = (u === 'imperial' && b.dataset.unit === 'in') ||
               (u === 'metric'   && b.dataset.unit === 'm');
    b.classList.toggle('active', on);
  });
}
function fmtThickness(n) {
  if (!Number.isFinite(n)) return '';
  return wallUnits() === 'imperial' ? n.toFixed(2) : n.toFixed(3);
}
function unitLabel() { return wallUnits() === 'imperial' ? 'in' : 'm'; }

// Heights are entered in feet, not the inches used for thickness. A wall is
// millimetres thick and metres tall, and mixing the two in one modal is how you
// get a 12 ft rack entered as 12 in.
const M_TO_FT = 3.280839895;
function mToHeight(m) {
  return wallUnits() === 'imperial' ? (m * M_TO_FT) : m;
}
function heightToM(v) {
  const n = parseFloat(v);
  if (!Number.isFinite(n)) return null;
  return wallUnits() === 'imperial' ? (n / M_TO_FT) : n;
}
function heightUnitLabel() { return wallUnits() === 'imperial' ? 'ft' : 'm'; }
function fmtHeight(n) {
  if (!Number.isFinite(n)) return '';
  return String(Math.round(n * 100) / 100);
}

// Segment counts per wall type id, read from the open project. A height is a
// property of the *type*, so the honest thing to show before saving one is how
// many drawn segments the change is about to move.
let _segmentCounts = {};

async function loadSegmentCounts() {
  _segmentCounts = {};
  try {
    const f = esxZip && esxZip.file('wallSegments.json');
    if (!f) return;
    const doc = JSON.parse(await f.async('string'));
    for (const seg of doc.wallSegments || []) {
      const id = seg.wallTypeId;
      if (id) _segmentCounts[id] = (_segmentCounts[id] || 0) + 1;
    }
  } catch (e) {
    _segmentCounts = {};
  }
}

function segmentsUsing(wt) {
  return (wt && wt.id && _segmentCounts[wt.id]) || 0;
}

let esxZip = null;
let wallTypes = [];
let fileName = '';
let _originalIdMap = {};

Object.defineProperty(window, 'esxZip',    { get: () => esxZip });
Object.defineProperty(window, 'wallTypes', { get: () => wallTypes });
Object.defineProperty(window, 'fileName',  { get: () => fileName });

function preserveId(wt) {
  return _originalIdMap[wt.key] || wt.id || crypto.randomUUID();
}

// How a template type is matched to one already in the project: Ekahau's own
// key where there is one, otherwise the name with punctuation and case thrown
// away, so "Dry Wall" and "Drywall" are the same type.
function matchKey(wt) {
  const k = (wt && wt.key ? String(wt.key) : '').trim();
  if (k) return 'k:' + k;
  return 'n:' + String((wt && wt.name) || '').toLowerCase().replace(/[^a-z0-9]/g, '');
}

// Is this one of the wall types Ekahau itself ships?
//
// Matched the same way everything else here is matched, so a type Ekahau has
// renamed between releases still counts as the same type.
function isStockType(wt) {
  const src = (typeof _ekahauDefaults !== 'undefined' && _ekahauDefaults)
    ? _ekahauDefaults.wallTypes : null;
  if (!src) return false;
  const key = matchKey(wt);
  return src.some(d => matchKey(d) === key);
}

// The fields a template can carry that would show up in Ekahau. `id`, `key`
// and `status` are identity and are never compared.
const TEMPLATE_FIELDS = ['name', 'color', 'attenuationFactor', 'thickness',
                         'upperEdge', 'lowerEdge', 'keybindNumber'];

function templateWouldChange(have, want) {
  return TEMPLATE_FIELDS.some(f => {
    const a = have[f] === undefined ? null : have[f];
    const b = want[f] === undefined ? null : want[f];
    return a !== b;
  });
}

// Apply a template by adding to the list, never by replacing it.
//
// Replacing is what this used to do, and it deleted every wall type the
// template had no counterpart for. That is fine until a project uses one: 92
// segments drawn with "Retail Shelf" were left pointing at a wall type that
// was no longer in the file, and nothing said so. Measured across 70 local
// projects with walls drawn, the old behaviour would have stranded walls in 11
// of them.
//
// So: a type the template carries is added, or updated in place if the project
// already has it - keeping the id the project already uses, so walls drawn with
// it still resolve. A type the template says nothing about is left exactly as
// it is. Nothing is ever removed here; "Ekahau Defaults" is the button that
// deliberately starts over, and it asks first.
//
// **A wall type Ekahau ships is updated from the template like any other, and
// that is deliberate again.** v2.100.5 made this skip stock types, on my
// reading of "I just want to add in the walls that we added, not change
// anything from the defaults". That reading was wrong: the three colours it
// was protecting Ekahau's greys from - Door Steel Fire/Exit, Elevator Shaft,
// Window Thick - are *his*, chosen so similar types can be told apart, and the
// Quick Walls guide had documented them as a feature for as long as they
// existed. He asked for them back: "get them back to where they were for my
// template."
//
// Leaving the guard in would have made that restoration cosmetic. Every Ekahau
// project already contains those three types, so the guard would skip them on
// every project he applied the template to and his colours would never land.
//
// The reporting machinery below (`kept`, `keptPhrase`) is left in place on
// purpose: if he does want the standard set protected again, re-adding the
// skip is one line and the message that explains it is already written.
function mergeTemplateTypes(newTypes, opts) {
  const fromDefaults = !!(opts && opts.fromDefaults);
  const where = new Map();
  wallTypes.forEach((wt, i) => where.set(matchKey(wt), i));

  let added = 0, updated = 0;
  const kept = [];
  const claimed = [];
  (newTypes || []).forEach(src => {
    const copy = JSON.parse(JSON.stringify(src));
    const key = matchKey(copy);
    const at = where.get(key);
    if (at === undefined) {
      copy.id = preserveId(src);
      wallTypes.push(copy);
      where.set(key, wallTypes.length - 1);
      added++;
    } else {
      const have = wallTypes[at];
      copy.id = have.id;
      wallTypes[at] = copy;
      updated++;
    }
    if (copy.keybindNumber >= 1 && copy.keybindNumber <= 9) {
      claimed.push([copy.keybindNumber, matchKey(copy)]);
    }
  });

  // A shortcut can only belong to one type. Where the template claims a number
  // an untouched type was holding, the template wins and the old one loses the
  // binding rather than the two silently colliding.
  claimed.forEach(([num, key]) => {
    wallTypes.forEach(wt => {
      if (wt.keybindNumber === num && matchKey(wt) !== key) delete wt.keybindNumber;
    });
  });

  return { added, updated, kept };
}
let editingIndex = -1;
let openMenuIndex = -1;

// Read the saved preferences once, and migrate anything still in this browser.
// Nothing is rendered until a project is opened, so the brief window before
// this resolves costs nothing; syncUnitToggleUI() runs again when it lands.
loadWallsPrefs();

const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');

dropzone.addEventListener('click', () => fileInput.click());
dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('dragover'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
dropzone.addEventListener('drop', e => {
  e.preventDefault();
  dropzone.classList.remove('dragover');
  // Dropped and browsed files carry no path, so any folder the server was
  // remembering no longer describes this project.
  _openedFromDisk = false;
  if (e.dataTransfer.files.length) loadFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', e => {
  _openedFromDisk = false;
  if (e.target.files.length) loadFile(e.target.files[0]);
});

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
    _auditAccepted = new Set();
    fileName = file.name;

    await ensureEkahauDefaultsLoaded();
    await loadSegmentCounts();

    const wtFile = esxZip.file('wallTypes.json');
    if (wtFile) {
      const wtJson = JSON.parse(await wtFile.async('string'));
      wallTypes = wtJson.wallTypes || [];
      _originalIdMap = {};
      wallTypes.forEach(wt => { if (wt.key && wt.id) _originalIdMap[wt.key] = wt.id; });
    } else {
      wallTypes = [];
      if (_ekahauDefaults) {
        wallTypes = _ekahauDefaults.wallTypes.map(wt => ({
          ...JSON.parse(JSON.stringify(wt)),
          id: crypto.randomUUID(),
        }));
        showToast('No wall types found — loaded Ekahau Defaults (' + wallTypes.length + ' types)', 'success');
      } else {
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

// ---------------------------------------------------------------- audit ---
// Wall types whose name states a height the file does not carry.
//
// This started out reporting anything that stands on the floor and was modelled
// to the ceiling, and it was wrong twice over. Auto is the correct default and
// an explicit height is the exception he sets deliberately - so Auto is never
// the finding. And Ekahau ships "Shelf, Warehouse" on Auto, so every freshly
// imported project was asked about it on the way in: the shipped state, queried
// as though someone had chosen it.
//
// What is left is a contradiction rather than an assumption. A type called
// "Warehouse Rack Wall - 16ft" with no upperEdge has a name asserting something
// the data does not back up, and one of the two is wrong. That is worth a line.
// Being on Auto is not.
//
// The rule lives in tools/wall_audit.py and is reached over /api/walls/audit,
// rather than being written a second time in JavaScript. One implementation is
// the whole point: a wall-type rule that existed twice in this codebase once
// had the Report printing a hex code where the Labeler printed a colour name,
// and only one of them got fixed.
let _auditFindings = [];
// Wall types he has told us really do run to the deck. Held for this project
// only: the answer is about a building, so opening another one asks again.
let _auditAccepted = new Set();

async function refreshWallAudit() {
  const panel = document.getElementById('wallAudit');
  if (!panel) return;
  if (!esxZip || !wallTypes.length) {
    _auditFindings = [];
    panel.hidden = true;
    return;
  }
  try {
    const r = await fetch('/api/walls/audit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
      body: JSON.stringify({ wallTypes, segmentCounts: _segmentCounts })
    });
    const d = await r.json();
    _auditFindings = (d && d.findings) || [];
  } catch (e) {
    _auditFindings = [];          // never block the editor on the check
  }
  renderWallAudit();
}

function renderWallAudit() {
  const panel = document.getElementById('wallAudit');
  if (!panel) return;
  const shown = _auditFindings.filter(f => !_auditAccepted.has(f.wallTypeId));
  if (!shown.length) { panel.hidden = true; panel.innerHTML = ''; return; }

  const n = shown.length;
  panel.hidden = false;
  // What is left to report is a contradiction, not a question about the
  // building, so this states what it found rather than asking him to adjudicate.
  panel.innerHTML =
    `<div class="wall-audit-head">${n === 1
        ? 'A wall type names a height it does not have'
        : `${n} wall types name a height they do not have`}</div>`
    + `<div class="wall-audit-why">Auto is the default and is usually right — `
    + `it models a type floor to ceiling, and nothing here is flagged for being `
    + `on it. ${n === 1 ? 'This one is' : 'These are'} flagged because the name `
    + `states a height the file does not carry, so the two disagree. Setting it `
    + `uses the height the name already gives.</div>`
    + shown.map(f => {
        const i = wallTypes.findIndex(w => w.id === f.wallTypeId);
        const ft = f.suggestedFt;
        return `<div class="wall-audit-row">`
          + `<span class="wall-audit-name">${esc(f.wallType)}</span>`
          + `<span class="wall-audit-detail">${f.segments} segment${f.segments === 1 ? '' : 's'}`
          + ` &middot; name says ${ft ? ft + ' ft' : 'a height'} &middot; none set</span>`
          + `<span class="wall-audit-spacer"></span>`
          + (ft ? `<button class="btn btn-sm btn-primary" onclick="applyAuditHeight('${f.wallTypeId}')"`
                  + ` title="${esc(f.why)}">Set to ${ft} ft</button>` : '')
          + (i >= 0 ? `<button class="btn btn-sm" onclick="openEditModal(${i})">Edit&hellip;</button>` : '')
          + `<button class="btn btn-sm" onclick="dismissAuditFinding('${f.wallTypeId}')"`
          + ` title="Leave it on Auto and stop mentioning it">Leave as is</button>`
          + `</div>`;
      }).join('');
}

// "Leave as is" is a real answer, not a way of hiding the question. The type
// stays on Auto and the row goes away for as long as this project is open.
// Nothing is written to the file, because there is nothing to write: Auto is
// already what it says, and the name is his to keep or rename.
function dismissAuditFinding(wallTypeId) {
  _auditAccepted.add(wallTypeId);
  const f = _auditFindings.find(x => x.wallTypeId === wallTypeId);
  if (f) showToast(`${f.wallType} left on Auto`, 'success');
  renderWallAudit();
}

// Applying the suggestion writes the height onto the type, the same field the
// editor writes. Nothing is saved to disk here - it lands in the .esx when he
// saves, like every other change on this page.
function applyAuditHeight(wallTypeId) {
  const f = _auditFindings.find(x => x.wallTypeId === wallTypeId);
  const i = wallTypes.findIndex(w => w.id === wallTypeId);
  if (!f || i < 0 || !f.suggestedM) return;
  wallTypes[i].lowerEdge = wallTypes[i].lowerEdge || 0;
  wallTypes[i].upperEdge = f.suggestedM;
  showToast(`${wallTypes[i].name} now stops at ${f.suggestedFt} ft `
            + `(${f.segments} segment${f.segments === 1 ? '' : 's'}) — save to keep it`,
            'success');
  renderAll();
}

function renderAll() {
  renderHotkeyPanel();
  renderList();
  refreshWallAudit();
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
             style="--slot-color:${safeColor(wt.color)}"
             draggable="true"
             title="Drag to move this shortcut to another slot"
             ondragstart="onSlotDragStart(event, ${n})"
             ondragend="onSlotDragEnd(event)"
             ondragover="onSlotDragOver(event, ${n})"
             ondragleave="onSlotDragLeave(event)"
             ondrop="onSlotDrop(event, ${n})">
          <span class="hotkey-swatch"></span>
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

function heightBadge(wt) {
  const upper = parseFloat(wt && wt.upperEdge);
  if (!Number.isFinite(upper) || upper <= 0) {
    return '<span class="wall-height-badge" title="Modelled floor to ceiling">Auto</span>';
  }
  const lower = parseFloat(wt.lowerEdge) || 0;
  const u = heightUnitLabel();
  const range = lower > 0
    ? `${fmtHeight(mToHeight(lower))}–${fmtHeight(mToHeight(upper))}`
    : `${fmtHeight(mToHeight(upper))}`;
  return `<span class="wall-height-badge is-limited" title="Stops short of the ceiling">` +
         `${esc(range)} ${esc(u)}</span>`;
}

function renderWallCard(wt, i) {
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

  return `
    <div class="wall-card" draggable="true"
         style="--wall-color:${safeColor(wt.color)}"
         ondragstart="onCardDragStart(event, ${i})"
         ondragend="onCardDragEnd(event)">
      <div class="wall-swatch"></div>
      <div class="wall-info">
        <div class="wall-name-row">
          <span class="wall-name">${esc(wt.name)}</span>
          ${kbBadge}
        </div>
        <div class="wall-meta">
          <span><span class="label">2.4:</span> ${esc(att2)}</span>
          <span><span class="label">5:</span> ${esc(att5)}</span>
          <span><span class="label">6:</span> ${esc(att6)}</span>
          <span><span class="label">thick:</span> ${esc(fmtThickness(mToDisplay(parseFloat(wt.thickness) || 0)))}${unitLabel()}</span>
          ${heightBadge(wt)}
        </div>
      </div>
      <div class="wall-actions">
        <button class="btn btn-icon btn-sm" onclick="showKeybindMenu(event, ${i})" title="Assign shortcut">#</button>
        <button class="btn btn-icon btn-sm" onclick="openEditModal(${i})" title="Edit">&#9998;</button>
        <button class="btn btn-icon btn-sm" onclick="cloneWall(${i})" title="Clone — duplicate as a new wall type to tweak"><svg viewBox="0 0 14 14" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" aria-hidden="true"><rect x="1.5" y="1.5" width="7" height="8"/><rect x="5.5" y="4.5" width="7" height="8"/></svg></button>
        <button class="btn btn-icon btn-sm btn-danger" onclick="deleteWall(${i})" title="Delete">&times;</button>
      </div>
    </div>`;
}

function renderList() {
  const list = document.getElementById('wallList');
  const sorted = [...wallTypes].sort((a, b) => (a.name || '').localeCompare(b.name || '', undefined, { sensitivity: 'base' }));
  document.getElementById('wallCount').textContent = wallTypes.length + ' wall type' + (wallTypes.length !== 1 ? 's' : '');

  if (!_ekahauDefaultKeys) {


    list.innerHTML = sorted.map(wt => renderWallCard(wt, wallTypes.indexOf(wt))).join('');
    ensureEkahauDefaultsLoaded().then(() => { if (_ekahauDefaultKeys) renderList(); });
    return;
  }

  const standard = sorted.filter(wt => _ekahauDefaultKeys.has(wt.key));
  const custom = sorted.filter(wt => !_ekahauDefaultKeys.has(wt.key));

  let html = '';
  if (standard.length) {
    html += `<div class="wall-group-header">Standard Ekahau</div>`;
    html += standard.map(wt => renderWallCard(wt, wallTypes.indexOf(wt))).join('');
  }
  if (custom.length) {
    html += `<div class="wall-group-header">Custom Walls</div>`;
    html += custom.map(wt => renderWallCard(wt, wallTypes.indexOf(wt))).join('');
  }

  list.innerHTML = html;
}

let dragCardIndex = -1;
let dragSlotNum = -1;

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

function onSlotDragStart(e, num) {
  dragSlotNum = num;
  e.currentTarget.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', 'slot:' + num);
}

function onSlotDragEnd(e) {
  dragSlotNum = -1;
  document.querySelectorAll('.hotkey-slot').forEach(s => s.classList.remove('dragging', 'dragover'));
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
  if (dragSlotNum >= 0) {
    if (dragSlotNum !== num) swapKeybinds(dragSlotNum, num);
    return;
  }
  if (dragCardIndex >= 0) {
    assignKeybind(dragCardIndex, num);
    showToast(`Assigned [${num}] to ${wallTypes[dragCardIndex].name}`, 'success');
  }
}

function swapKeybinds(numA, numB) {
  const map = getKeybindMap();
  const wtA = map[numA];
  const wtB = map[numB];
  if (wtA) wtA.keybindNumber = numB;
  if (wtB) wtB.keybindNumber = numA;
  renderAll();
  if (wtA && wtB) showToast(`Swapped [${numA}] ${wtA.name} ↔ [${numB}] ${wtB.name}`, 'success');
  else if (wtA) showToast(`Moved ${wtA.name} to [${numB}]`, 'success');
}

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

function deleteWall(i) {
  const name = wallTypes[i].name;
  if (confirm('Remove "' + name + '"?')) {
    wallTypes.splice(i, 1);
    renderAll();
  }
}

function openAddModal() {
  editingIndex = -1;
  document.getElementById('modalTitle').textContent = 'Add Wall Type';
  document.getElementById('modalSaveBtn').textContent = 'Add';
  document.getElementById('fName').value = '';
  document.getElementById('fColor').value = '#808080';
  document.getElementById('fThickness').value = fmtThickness(mToDisplay(0.1));
  populateVertFields(null);
  syncUnitToggleUI();
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

function cloneWall(sourceIndex) {
  const src = wallTypes[sourceIndex];
  if (!src) return;
  editingIndex = -1;
  document.getElementById('modalTitle').textContent = 'Clone Wall Type';
  document.getElementById('modalSaveBtn').textContent = 'Add';
  document.getElementById('fName').value = (src.name || '') + ' (Copy)';
  document.getElementById('fColor').value = src.color || '#808080';
  document.getElementById('fThickness').value = fmtThickness(mToDisplay(parseFloat(src.thickness) || 0));
  populateVertFields(src);
  syncUnitToggleUI();

  const bands = src.propagationProperties || [];
  const getBand = (name) => bands.find(b => b.band === name) || {};
  const two = getBand('TWO');
  const five = getBand('FIVE');
  const six = getBand('SIX');
  document.getElementById('fTwoAtt').value  = two.attenuationFactor    ?? 0;
  document.getElementById('fTwoRef').value  = two.reflectionCoefficient ?? 0;
  document.getElementById('fTwoDif').value  = two.diffractionCoefficient?? 0;
  document.getElementById('fFiveAtt').value = five.attenuationFactor    ?? 0;
  document.getElementById('fFiveRef').value = five.reflectionCoefficient ?? 0;
  document.getElementById('fFiveDif').value = five.diffractionCoefficient?? 0;
  document.getElementById('fSixAtt').value  = six.attenuationFactor    ?? 0;
  document.getElementById('fSixRef').value  = six.reflectionCoefficient ?? 0;
  document.getElementById('fSixDif').value  = six.diffractionCoefficient?? 0;

  populateKeybindSelect(null);
  document.getElementById('modal').classList.add('active');
  document.getElementById('fName').focus();
  document.getElementById('fName').setSelectionRange(0, 999);
}

function openEditModal(i) {
  editingIndex = i;
  const wt = wallTypes[i];
  document.getElementById('modalTitle').textContent = 'Edit Wall Type';
  document.getElementById('modalSaveBtn').textContent = 'Save';
  document.getElementById('fName').value = wt.name;
  document.getElementById('fColor').value = wt.color || '#808080';
  document.getElementById('fThickness').value = fmtThickness(mToDisplay(parseFloat(wt.thickness) || 0));
  populateVertFields(wt);
  syncUnitToggleUI();

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

// --- Vertical extent -------------------------------------------------------
//
// Ekahau stores lowerEdge/upperEdge in metres on the wall *type*. No upperEdge
// at all means Auto: the engine runs the wall from floor to ceiling. That is
// right for a wall and wrong for furniture, which is how 52 segments of
// warehouse shelving end up modelled as 27 dB of solid barrier to the roof.

let _heightMode = 'auto';

window.setHeightMode = function (mode) {
  _heightMode = (mode === 'fixed') ? 'fixed' : 'auto';
  document.querySelectorAll('.wt-vert-mode').forEach(b => {
    b.classList.toggle('active', b.dataset.vmode === _heightMode);
  });
  const fixed = document.getElementById('fVertFixed');
  if (fixed) fixed.hidden = (_heightMode !== 'fixed');
  if (_heightMode === 'fixed') {
    const top = document.getElementById('fUpperEdge');
    // Seed something plausible rather than an empty box the user must decode.
    if (top && !top.value) top.value = fmtHeight(mToHeight(2.0));
  }
  updateVertSummary();
};

function currentVertEdges() {
  if (_heightMode !== 'fixed') return { lower: 0, upper: null };
  const upper = heightToM(document.getElementById('fUpperEdge')?.value);
  const lowerRaw = heightToM(document.getElementById('fLowerEdge')?.value);
  return { lower: Number.isFinite(lowerRaw) ? lowerRaw : 0, upper: upper };
}

window.updateVertSummary = function () {
  const unit = heightUnitLabel();
  const unitEl = document.getElementById('fVertUnit');
  if (unitEl) unitEl.textContent = unit;

  const summary = document.getElementById('fVertSummary');
  const impact = document.getElementById('fVertImpact');
  if (!summary) return;

  const { lower, upper } = currentVertEdges();

  if (_heightMode !== 'fixed') {
    summary.innerHTML = 'Ekahau runs this type from the floor to the ceiling. ' +
      'Right for a real wall — wrong for anything you can see over, which is ' +
      'modelled as a solid barrier all the way up.';
  } else if (!Number.isFinite(upper) || upper <= 0) {
    summary.innerHTML = 'Enter how far above the floor this type reaches.';
  } else if (upper <= lower) {
    summary.innerHTML = '<strong>The top must be above the floor offset.</strong>';
  } else {
    const tall = upper - lower;
    summary.innerHTML =
      `Occupies ${esc(fmtHeight(mToHeight(lower)))}–${esc(fmtHeight(mToHeight(upper)))} ${esc(unit)} ` +
      `above the floor (${esc(fmtHeight(mToHeight(tall)))} ${esc(unit)} tall). ` +
      `Signal passes over the top.`;
  }

  // The per-type consequence, stated with the real number before saving.
  if (!impact) return;
  const existing = editingIndex >= 0 ? wallTypes[editingIndex] : null;
  const count = segmentsUsing(existing);
  const wasAuto = !(existing && Number.isFinite(parseFloat(existing.upperEdge)));
  const nowAuto = (_heightMode !== 'fixed');
  const changed = existing && (wasAuto !== nowAuto ||
    (!nowAuto && parseFloat(existing.upperEdge) !== upper) ||
    (!nowAuto && (parseFloat(existing.lowerEdge) || 0) !== lower));

  if (count > 0 && changed) {
    const what = nowAuto
      ? 'run floor-to-ceiling again'
      : `stop at ${esc(fmtHeight(mToHeight(upper)))} ${esc(unit)}`;
    impact.innerHTML =
      `<strong>Affects ${count} drawn segment${count === 1 ? '' : 's'}.</strong> ` +
      `Height belongs to the wall type, not to individual segments — every ` +
      `segment already drawn as “${esc(existing.name)}” will ${what} once you save.`;
    impact.hidden = false;
  } else if (count > 0) {
    impact.innerHTML = `${count} drawn segment${count === 1 ? '' : 's'} use this type.`;
    impact.hidden = false;
  } else {
    impact.hidden = true;
  }
};

// The one place the vertical extent is written onto a wall type. Kept separate
// from saveWallType so the rule can be tested against real output rather than
// re-stated in a test and hoped to match.
function applyVertExtent(wt, mode, lower, upper) {
  if (mode === 'fixed') {
    wt.lowerEdge = lower;
    wt.upperEdge = upper;
  } else {
    // Auto is the absence of upperEdge, not a zero: writing 0 would tell
    // Ekahau the type has no vertical extent at all rather than a full one.
    wt.lowerEdge = 0;
    delete wt.upperEdge;
  }
  return wt;
}

// Auto is a real answer, not an unset state, so returning to it has to be one
// click and has to survive a save. Anything that treats it as "not yet chosen"
// would leave a type stuck at whatever height it was last given.
function vertExtentError(mode, lower, upper) {
  if (mode !== 'fixed') return null;
  if (!Number.isFinite(upper) || upper <= 0) {
    return 'Enter how far above the floor this type reaches';
  }
  if (upper <= lower) return 'The top must be above the floor offset';
  return null;
}

function populateVertFields(src) {
  const upper = parseFloat(src && src.upperEdge);
  const lower = parseFloat(src && src.lowerEdge) || 0;
  const hasUpper = Number.isFinite(upper) && upper > 0;
  const topEl = document.getElementById('fUpperEdge');
  const lowEl = document.getElementById('fLowerEdge');
  if (topEl) topEl.value = hasUpper ? fmtHeight(mToHeight(upper)) : '';
  if (lowEl) lowEl.value = fmtHeight(mToHeight(lower));
  setHeightMode(hasUpper ? 'fixed' : 'auto');
}

function saveWallType() {
  const name = document.getElementById('fName').value.trim();
  if (!name) { showToast('Name is required'); return; }

  const keybindVal = document.getElementById('fKeybind').value;
  const keybindNum = keybindVal ? parseInt(keybindVal) : null;

  const { lower: vLower, upper: vUpper } = currentVertEdges();
  const vertError = vertExtentError(_heightMode, vLower, vUpper);
  if (vertError) { showToast(vertError); return; }

  const existing = editingIndex >= 0 ? wallTypes[editingIndex] : {};
  const wt = {
    ...existing,
    name: name,
    key: existing.key || name.replace(/[^a-zA-Z0-9]/g, ''),
    color: document.getElementById('fColor').value,
    thickness: displayToM(document.getElementById('fThickness').value),
    lowerEdge: vLower,
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

  applyVertExtent(wt, _heightMode, vLower, vUpper);

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
    revealSourceFolder();
  } else if (result === 'downloaded') {
    showToast('Downloading ' + defaultName + ' — check your browser downloads', 'success');
    revealSourceFolder();
  }
}

/* A dropped file gives the browser no path, so the folder can only be shown
   when the project was opened through "Open from disk" and the server knows
   where it came from. Failing to open a window never means the save failed, so
   nothing here surfaces an error. */
let _openedFromDisk = false;

async function revealSourceFolder() {
  if (!_openedFromDisk) return;
  try {
    const s = await fetch('/api/settings/get', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
      body: '{}',
    }).then(r => r.json());
    const walls = (s && s.settings && s.settings.walls) || {};
    if (walls.reveal_source_after_save === false) return;
    await fetch('/api/walls/reveal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
      body: '{}',
    });
  } catch (e) {
    /* cosmetic - the save already succeeded */
  }
}

// Three outcomes, and they are not the same thing: a file was chosen, the
// dialog was cancelled, or the dialog never opened. The third used to arrive
// as the second and was therefore silent, which left this button doing nothing
// at all. A picker that cannot run falls through to the browser's own file
// input - getting a project in matters more than which dialog did it.
async function openFromDisk() {
  const btn = document.querySelector('.dropzone-open-disk');
  const label = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = 'Opening…'; }
  const done = () => { if (btn) { btn.disabled = false; btn.textContent = label; } };
  try {
    const res = await fetch('/api/walls/pick', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
      body: '{}',
    }).then(r => r.json());
    if (!res || !res.ok) {
      done();
      if (res && res.code === 'picker_unavailable') {
        showToast(res.error + ' Use the drop zone instead.', 'error');
        fileInput.value = '';
        fileInput.click();
        return;
      }
      if (res && res.error && res.error !== 'No file selected') showToast(res.error, 'error');
      return;
    }
    const blob = await fetch('/api/walls/read', {
      method: 'POST',
      headers: { 'X-WD-Wireless-Tools': '1' },
    }).then(r => r.blob());
    _openedFromDisk = true;
    await loadFile(new File([blob], res.name));
    showToast('Opened from ' + res.dir, 'success');
  } catch (e) {
    showToast('Could not open that project: ' + e, 'error');
  }
}
window.openFromDisk = openFromDisk;

let _tplCache = [];

async function tplApi(action, data = {}) {
  const r = await fetch(`/api/templates/${action}`, {
    method: 'POST',
    headers: {'Content-Type':'application/json', 'X-WD-Wireless-Tools':'1'},
    body: JSON.stringify(data)
  });
  return r.json();
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

function toggleDzMenu(e) {
  WD.toggleMenu(e, 'dzMenu');
}

function toggleHelpMenu(e) {
  WD.toggleMenu(e, 'helpMenu');
}

// Backed by settings.json; loaded once by loadWallsPrefs().
function getDefaultTemplate() {
  return _defaultTemplate || null;
}
function setLastTemplate(name) {
  _defaultTemplate = name || null;
  _persistWallsPref({ default_template: name || '' });
  refreshTemplateBar();
}

function getAutoApply() {
  return _autoApply === true;
}
function toggleAutoApply() {
  const checked = document.getElementById('autoApplyCheck').checked;
  _autoApply = checked;
  _persistWallsPref({ auto_apply_template: checked });
  if (checked) showToast('Template will auto-apply on next file open', 'success');
}

let _ekahauDefaults = null;
let _ekahauDefaultKeys = null;

async function ensureEkahauDefaultsLoaded() {
  if (_ekahauDefaults) return;
  try {
    const r = await tplApi('defaults');
    if (r.ok) {
      _ekahauDefaults = { name: 'Ekahau Defaults', wallTypes: r.wallTypes };
      _ekahauDefaultKeys = new Set(r.wallTypes.map(wt => wt.key));
    }
  } catch (e) {
    console.warn('Could not load Ekahau defaults:', e);
  }
}

async function refreshTemplateBar() {
  await loadTemplatesFromServer();
  await ensureEkahauDefaultsLoaded();

  const sel = document.getElementById('templateSelect');
  const tpls = _tplCache;
  const def = getDefaultTemplate() || 'WD Template';

  let html = '';

  const wd = tpls.find(t => t.name === 'WD Template');
  if (wd) {
    const selected = def === wd.name ? ' selected' : '';
    html += `<option value="${escAttr(wd.name)}"${selected}>${esc(wd.name)} (${wd.wallTypes.length} types) ⭐</option>`;
  }

  // The two he asked for sit together at the top: his curated set, and
  // Ekahau's stock types as the baseline to come back to.
  //
  // `Ekahau Default` is now a real template file, seeded into his own
  // templates folder like any other, so it is exportable, backed up and his.
  // It replaces the synthetic `Ekahau Defaults` entry that used to be built
  // here out of `ekahau_defaults.json` - listing both would put two almost
  // identically named Ekahau rows in one dropdown.
  //
  // The **Ekahau Defaults button** is untouched and still does something this
  // option deliberately does not: it starts the wall list over, and asks
  // first. Choosing this option applies additively, like every other template.
  const ekahau = tpls.find(t => t.name === 'Ekahau Default');
  if (ekahau) {
    const selected = (def === ekahau.name || def === 'Ekahau Defaults') ? ' selected' : '';
    html += `<option value="${escAttr(ekahau.name)}"${selected}>${esc(ekahau.name)} (${ekahau.wallTypes.length} types)</option>`;
  } else if (_ekahauDefaults) {
    const selected = def === 'Ekahau Defaults' ? ' selected' : '';
    html += `<option value="Ekahau Defaults"${selected}>Ekahau Defaults (${_ekahauDefaults.wallTypes.length} types)</option>`;
  }

  const pinned = ['WD Template', 'Ekahau Default'];
  const userTpls = tpls.filter(t => pinned.indexOf(t.name) === -1);
  if (userTpls.length > 0) {
    html += '<option disabled>───────────────</option>';
    userTpls.forEach(t => {
      const selected = t.name === def ? ' selected' : '';
      html += `<option value="${escAttr(t.name)}"${selected}>${esc(t.name)} (${t.wallTypes.length} types)</option>`;
    });
  }

  sel.innerHTML = html;

  document.getElementById('autoApplyCheck').checked = getAutoApply();

  const selected = sel.value;
  const applyBtn = document.getElementById('tplApplyBtn');
  applyBtn.disabled = !selected || selected === '';
}

// What the toast says about types left as Ekahau ships them. Named rather than
// counted where there are few enough to read, because "left 3 alone" invites
// the question the names answer.
function keptPhrase(kept) {
  if (!kept || !kept.length) return '';
  if (kept.length <= 3) {
    return `left ${kept.map(n => `“${n}”`).join(', ')} as Ekahau ships ${kept.length === 1 ? 'it' : 'them'}`;
  }
  return `left ${kept.length} Ekahau types as Ekahau ships them`;
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

  const { added, updated, kept } = mergeTemplateTypes(
    newTypes, { fromDefaults: name === 'Ekahau Defaults' });

  renderAll();
  const parts = [];
  if (added) parts.push(`added ${added}`);
  if (updated) parts.push(`updated ${updated}`);
  if (kept.length) parts.push(keptPhrase(kept));
  showToast(parts.length
    ? `Applied "${name}" — ${parts.join(', ')}; nothing removed (${wallTypes.length} types)`
    : `"${name}" is already in this project`, 'success');
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

  const { added, updated, kept } = mergeTemplateTypes(
    newTypes, { fromDefaults: def === 'Ekahau Defaults' });

  renderAll();
  const parts = [];
  if (added) parts.push(`added ${added}`);
  if (updated) parts.push(`updated ${updated}`);
  if (kept.length) parts.push(keptPhrase(kept));
  showToast(parts.length
    ? `Auto-applied "${def}" — ${parts.join(', ')}; nothing removed`
    : `Auto-apply: "${def}" is already in this project`, 'success');
}

function _isEkahauDefault(wt) {
  return isStockType(wt);
}

function resetToEkahauDefaults() {
  if (!_ekahauDefaults) {
    showToast('Ekahau defaults not loaded yet');
    return;
  }
  // The one place that still replaces the list outright - which is the whole
  // point of it, so it says what it will cost before doing it.
  const own = wallTypes.filter(wt => !_isEkahauDefault(wt));
  const warning = own.length
    ? `\n\n${own.length} wall type${own.length === 1 ? '' : 's'} not in Ekahau's `
      + `defaults will be removed: ${own.slice(0, 6).map(w => w.name).join(', ')}`
      + `${own.length > 6 ? '…' : ''}.\n\nWalls already drawn with them will be `
      + `left without a type.`
    : '';
  if (!confirm('Reset all wall types to Ekahau factory defaults?' + warning)) return;

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
