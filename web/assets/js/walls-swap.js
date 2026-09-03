(function () {
  'use strict';

  const state = {
    floors: [],
    currentFloorId: null,
    segments: [],
    segmentsByFloor: new Map(),
    wallPoints: new Map(),
    imageBlobs: new Map(),
    loadedImage: null,
    imgW: 0, imgH: 0,

    // `selected` is the working set the marquee/click/legend produced.
    // `excluded` is what the user has since unchecked out of it. Everything
    // that acts on a selection goes through targetIds() = selected - excluded,
    // so a fresh marquee hit always arrives checked.
    selected: new Set(),
    excluded: new Set(),
    collapsedTypes: new Set(),
    hoverSegId: null,
    hoverGroupKey: null,
    segOrdinal: new Map(),
    showNumbers: false,
    renderQueued: false,
    history: [],
    historyIndex: -1,
    metersPerUnit: 0,

    view: { x: 0, y: 0, scale: 1 },
    fitScale: 0,

    tool: 'marquee',
    isDragging: false,
    dragStart: null,
    dragCurrent: null,
    isPanning: false,
    spaceHeld: false,
    touch: null,
    pressStart: null,
    pressMoved: false,

    segGeom: [],
  };

  const $ = (id) => document.getElementById(id);
  const canvas = () => $('swapCanvas');
  const ctx = () => canvas().getContext('2d');

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function toast(msg, kind) {
    if (window.WD && WD.toast) WD.toast(msg, kind);
  }

  function wallTypesList() {
    return Array.isArray(window.wallTypes) ? window.wallTypes : [];
  }

  function typeById(id) {
    return wallTypesList().find(w => w.id === id) || null;
  }

  function extractPointRef(entry) {
    if (entry == null) return null;
    if (typeof entry === 'string') return entry;
    if (typeof entry === 'object') {
      return entry.id || entry.wallPointId || entry.pointId || null;
    }
    return null;
  }

  function resolvePointById(id) {
    if (!id) return null;
    return state.wallPoints.get(id) || null;
  }

  function segmentEndpoints(seg) {
    const pts = seg.wallPoints || seg.points;
    if (!Array.isArray(pts) || pts.length < 2) return null;

    const idA = extractPointRef(pts[0]);
    const idB = extractPointRef(pts[pts.length - 1]);
    if (idA && idB) {
      const a = resolvePointById(idA);
      const b = resolvePointById(idB);
      if (a && b && [a.x, a.y, b.x, b.y].every(v => Number.isFinite(v))) {
        return { x1: a.x, y1: a.y, x2: b.x, y2: b.y };
      }
    }

    const p1 = pts[0], p2 = pts[pts.length - 1];
    const x1 = p1?.x ?? p1?.location?.x;
    const y1 = p1?.y ?? p1?.location?.y;
    const x2 = p2?.x ?? p2?.location?.x;
    const y2 = p2?.y ?? p2?.location?.y;
    if ([x1, y1, x2, y2].every(v => Number.isFinite(v))) {
      return { x1, y1, x2, y2 };
    }
    return null;
  }

  function segmentFloorId(seg) {
    const pts = seg.wallPoints || seg.points;
    if (Array.isArray(pts)) {
      for (const raw of pts) {
        const id = extractPointRef(raw);
        const p = resolvePointById(id);
        if (p && p.floorPlanId) return p.floorPlanId;
        const inlineFid = raw?.location?.floorPlanId || raw?.floorPlanId;
        if (inlineFid) return inlineFid;
      }
    }
    return seg.floorPlanId || seg.floorId || null;
  }

  function segmentTypeId(seg) {
    return seg.wallTypeId || seg.wallType || null;
  }

  // --- pure history core (sliced out and unit-tested under Node) ---
  function setSegmentType(seg, typeId) {
    if ('wallTypeId' in seg) seg.wallTypeId = typeId;
    else if ('wallType' in seg) seg.wallType = typeId;
    else seg.wallTypeId = typeId;
  }

  // changes: [{ id, from, to }]. Returns how many segments it actually touched.
  function applyTypeChanges(segments, changes) {
    const byId = new Map();
    segments.forEach(seg => byId.set(seg.id, seg));
    let hits = 0;
    changes.forEach(c => {
      const seg = byId.get(c.id);
      if (!seg) return;
      setSegmentType(seg, c.to);
      hits++;
    });
    return hits;
  }

  function invertTypeChanges(changes) {
    return changes.map(c => ({ id: c.id, from: c.to, to: c.from }));
  }

  // Deletes remember where each segment sat so an undo puts it back in place
  // rather than appending it to the end of the file.
  function restoreRemoved(segments, removed) {
    const out = segments.slice();
    removed.slice().sort((a, b) => a.index - b.index)
      .forEach(r => out.splice(Math.min(r.index, out.length), 0, r.seg));
    return out;
  }
  // --- end pure history core ---

  function colorOf(seg) {
    const wt = typeById(seg.typeId);
    return wt ? safeColor(wt.color) : '#888';
  }

  window.openSwapModal = async function () {
    const zip = window.esxZip;
    if (!zip) { toast('Open an .esx file first'); return; }

    try {
      await loadEsxData(zip);
    } catch (err) {
      console.error('Swap modal load failed:', err);
      toast('Could not read floor plans: ' + err.message);
      return;
    }

    if (!state.floors.length) {
      toast('This .esx has no floor plans');
      return;
    }

    populateFloorSelect();
    populateTypeSelectors();
    const firstWithWalls = state.floors.find(f => {
      const segs = state.segmentsByFloor.get(f.id) || [];
      return segs.some(s => segmentEndpoints(s));
    }) || state.floors[0];
    state.currentFloorId = firstWithWalls.id;
    $('swapFloorSelect').value = firstWithWalls.id;

    const badge = $('swapFileBadge');
    if (badge) {
      const fn = window.fileName || '';
      badge.textContent = fn;
      badge.style.display = fn ? 'inline-block' : 'none';
    }

    $('swapModal').classList.add('active');
    document.body.style.overflow = 'hidden';

    await switchFloor(firstWithWalls.id);
    installEventListeners();
  };

  window.closeSwapModal = function () {
    $('swapModal').classList.remove('active');
    document.body.style.overflow = '';
    uninstallEventListeners();
    state.imageBlobs.forEach(url => URL.revokeObjectURL(url));
    state.imageBlobs.clear();
    state.loadedImage = null;
    // A drag or touch in flight when the modal closes would otherwise leave
    // these latched for the next open.
    state.isPanning = false;
    state.isDragging = false;
    state.dragStart = null;
    state.dragCurrent = null;
    state.touch = null;
    state.spaceHeld = false;
    state.history = [];
    state.historyIndex = -1;
    dismissUndoToast();
    const wrap = $('swapCanvasWrap');
    if (wrap) wrap.classList.remove('pan-active');
    clearSelectionState();
  };

  async function loadEsxData(zip) {
    const fpFile = zip.file('floorPlans.json');
    const floors = [];
    if (fpFile) {
      const j = JSON.parse(await fpFile.async('string'));
      const list = j.floorPlans || j.floorplans || [];
      list.forEach(f => {
        floors.push({
          id: f.id,
          name: f.name || 'Untitled floor',
          imageId: f.imageId || f.image?.id || f.image,
          w: f.width || 0,
          h: f.height || 0,
          metersPerUnit: f.metersPerUnit || 0,
        });
      });
    }
    state.floors = floors;

    state.wallPoints.clear();
    const wpFile = zip.file('wallPoints.json');
    if (wpFile) {
      const j = JSON.parse(await wpFile.async('string'));
      const list = j.wallPoints || j.wallpoints || [];
      list.forEach(p => {
        const loc = p.location || p;
        const c = loc?.coord || loc;
        const x = c?.x, y = c?.y;
        const fid = loc?.floorPlanId || p.floorPlanId || null;
        if (p.id && Number.isFinite(x) && Number.isFinite(y)) {
          state.wallPoints.set(p.id, { x, y, floorPlanId: fid });
        }
      });
    }

    const wsFile = zip.file('wallSegments.json');
    let segs = [];
    if (wsFile) {
      const j = JSON.parse(await wsFile.async('string'));
      segs = j.wallSegments || j.wallsegments || [];
    }
    state.segments = segs;

    state.segmentsByFloor.clear();
    segs.forEach(s => {
      const fid = segmentFloorId(s);
      if (!fid) return;
      if (!state.segmentsByFloor.has(fid)) state.segmentsByFloor.set(fid, []);
      state.segmentsByFloor.get(fid).push(s);
    });

    if (segs.length && state.segmentsByFloor.size === 0) {
      console.warn('[Visual Swap] Loaded ' + segs.length + ' wall segments but could not resolve any to a floor.');
      console.warn('[Visual Swap] Sample segment:', segs[0]);
      const firstPointId = extractPointRef((segs[0].wallPoints || [])[0]);
      console.warn('[Visual Swap] Sample point (id=' + firstPointId + '):',
        firstPointId ? state.wallPoints.get(firstPointId) : '(no ref)');
      console.warn('[Visual Swap] wallPoints map size:', state.wallPoints.size);
    }
  }

  async function loadImageForFloor(floor) {
    if (!floor || !floor.imageId) return null;
    let url = state.imageBlobs.get(floor.imageId);
    if (!url) {
      const zip = window.esxZip;
      const entry = zip.file('image-' + floor.imageId);
      if (!entry) return null;
      const blob = await entry.async('blob');
      url = URL.createObjectURL(blob);
      state.imageBlobs.set(floor.imageId, url);
    }
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error('image decode failed'));
      img.src = url;
    });
  }

  async function switchFloor(floorId) {
    state.currentFloorId = floorId;
    state.fitScale = 0;
    clearSelectionState();
    const floor = state.floors.find(f => f.id === floorId);
    if (!floor) return;
    state.metersPerUnit = floor.metersPerUnit || 0;

    $('swapCanvasEmpty').textContent = 'Loading floor plan…';
    $('swapCanvasEmpty').style.display = 'flex';

    const floorSegs = state.segmentsByFloor.get(floorId) || [];
    state.segGeom = [];
    floorSegs.forEach(s => {
      const ep = segmentEndpoints(s);
      if (!ep) return;
      state.segGeom.push({
        id: s.id,
        typeId: segmentTypeId(s),
        x1: ep.x1, y1: ep.y1, x2: ep.x2, y2: ep.y2,
      });
    });

    let img = null;
    try { img = await loadImageForFloor(floor); }
    catch (e) { console.warn('Floor image failed to load:', e); }

    state.loadedImage = img;
    state.imgW = floor.w || (img ? img.naturalWidth  : 1000);
    state.imgH = floor.h || (img ? img.naturalHeight : 800);

    resizeCanvas();
    if (!zoomFit()) {
      // rAF normally lands the moment layout settles, but it is throttled in a
      // background tab — the timeout is the backstop so the plan is never left
      // unfitted.
      const retry = () => { if (state.fitScale > 0) return; resizeCanvas(); zoomFit(); };
      requestAnimationFrame(retry);
      setTimeout(retry, 80);
    }
    renderLegend();
    renderSelection();
    updateStatus();

    $('swapCanvasEmpty').style.display = state.segGeom.length || img ? 'none' : 'flex';
    if (!state.segGeom.length && !img) {
      $('swapCanvasEmpty').textContent = 'This floor has no walls and no floor plan image.';
    }
  }

  function populateFloorSelect() {
    const sel = $('swapFloorSelect');
    const opts = state.floors.map(f => {
      const n = (state.segmentsByFloor.get(f.id) || []).length;
      return `<option value="${esc(f.id)}">${esc(f.name)} — ${n} wall${n === 1 ? '' : 's'}</option>`;
    });
    sel.innerHTML = opts.join('');
  }

  function populateTypeSelectors() {
    const wts = [...wallTypesList()].sort((a, b) =>
      (a.name || '').localeCompare(b.name || '', undefined, { sensitivity: 'base' }));
    const opts = ['<option value="">Pick a wall type…</option>']
      .concat(wts.map(w =>
        `<option value="${esc(w.id)}">${esc(w.name)}</option>`)).join('');
    $('swapTargetType').innerHTML = opts;
    $('swapFromType').innerHTML = opts;
    $('swapToType').innerHTML = opts;
  }

  function renderLegend() {
    const counts = new Map();
    state.segGeom.forEach(g => {
      counts.set(g.typeId, (counts.get(g.typeId) || 0) + 1);
    });

    const rows = [];
    counts.forEach((count, typeId) => {
      const wt = typeById(typeId);
      rows.push({
        typeId,
        name: wt?.name || '(deleted wall type)',
        color: wt ? safeColor(wt.color) : '#888',
        count,
      });
    });
    rows.sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));

    const el = $('swapLegend');
    if (!rows.length) {
      el.innerHTML = '<div class="swap-empty">No walls on this floor.</div>';
      return;
    }
    el.innerHTML = rows.map(r => `
      <button class="swap-legend-row" onclick="selectAllOfType('${escJsStr(r.typeId)}')" title="Select all ${esc(r.name)} walls on this floor">
        <span class="swap-legend-swatch" style="--swap-swatch:${r.color}"></span>
        <span class="swap-legend-name">${esc(r.name)}</span>
        <span class="swap-legend-count">${r.count}</span>
      </button>
    `).join('');
  }

  const M_TO_FT = 3.28084;
  const NO_TYPE = '__notype__';

  function segGeomById(id) {
    return state.segGeom.find(g => g.id === id) || null;
  }

  // The set that actually gets swapped/deleted: everything the marquee caught
  // minus whatever the user has unchecked since.
  function targetIds() {
    const out = [];
    state.selected.forEach(id => { if (!state.excluded.has(id)) out.push(id); });
    return out;
  }

  function targetCount() {
    let n = 0;
    state.selected.forEach(id => { if (!state.excluded.has(id)) n++; });
    return n;
  }

  // Anything unchecked but no longer in the selection is meaningless — drop it
  // so a stale exclusion can't silently spare a segment in a later marquee.
  function pruneExcluded() {
    state.excluded.forEach(id => { if (!state.selected.has(id)) state.excluded.delete(id); });
  }

  // Segments enter the selection checked, always. Re-marqueeing over something
  // you previously unchecked re-checks it.
  function addToSelection(ids) {
    ids.forEach(id => { state.selected.add(id); state.excluded.delete(id); });
  }

  function clearSelectionState() {
    state.selected.clear();
    state.excluded.clear();
    state.collapsedTypes.clear();
    state.hoverSegId = null;
    state.hoverGroupKey = null;
  }

  function segLengthFt(g) {
    if (!state.metersPerUnit) return null;
    const px = Math.hypot(g.x2 - g.x1, g.y2 - g.y1);
    return px * state.metersPerUnit * M_TO_FT;
  }

  function segLengthLabel(g) {
    const ft = segLengthFt(g);
    if (!Number.isFinite(ft) || ft <= 0) return '';
    return (ft < 10 ? ft.toFixed(1) : Math.round(ft)) + ' ft';
  }

  function groupKeyOf(g) {
    return g.typeId || NO_TYPE;
  }

  // Group the current selection by wall type, longest segment first inside each
  // group — a 14 ft bay door sorts above the 3 ft man doors it is mixed in with.
  function selectionGroups() {
    const map = new Map();
    state.selected.forEach(id => {
      const g = segGeomById(id);
      if (!g) return;
      const key = groupKeyOf(g);
      if (!map.has(key)) {
        const wt = typeById(g.typeId);
        map.set(key, {
          key,
          name: wt?.name || '(deleted wall type)',
          color: wt ? safeColor(wt.color) : '#888',
          segs: [],
        });
      }
      map.get(key).segs.push(g);
    });
    const groups = [...map.values()];
    groups.forEach(gr => {
      gr.segs.sort((a, b) => (segLengthFt(b) || 0) - (segLengthFt(a) || 0));
      gr.checked = gr.segs.filter(x => !state.excluded.has(x.id)).length;
    });
    groups.sort((a, b) => b.segs.length - a.segs.length || a.name.localeCompare(b.name));
    // Remember each segment's position in its group so the canvas can label it
    // with the same number the panel shows.
    state.segOrdinal = new Map();
    groups.forEach(gr => gr.segs.forEach((g, i) => state.segOrdinal.set(g.id, i + 1)));
    return groups;
  }

  function renderSelection() {
    const el = $('swapSelBreakdown');
    const total = state.selected.size;

    if (!total) {
      el.innerHTML = '<div class="swap-empty">Drag a marquee to select walls, or click walls with the arrow tool. Everything you catch starts checked — uncheck what you don’t want to change.</div>';
      refreshSelectionMeta();
      updateCollapseAllButton();
      return;
    }

    const scrollTop = el.scrollTop;
    const groups = selectionGroups();
    el.innerHTML = groups.map(gr => {
      const collapsed = state.collapsedTypes.has(gr.key);
      const rows = gr.segs.map((g, i) => {
        const len = segLengthLabel(g);
        const jid = escJsStr(g.id);
        return '<div class="swap-seg-row" data-seg-id="' + esc(g.id) + '" '
          + 'onmouseenter="swapHoverSeg(\'' + jid + '\',1)" '
          + 'onmouseleave="swapHoverSeg(\'' + jid + '\',0)">'
          + '<input type="checkbox" data-seg-id="' + esc(g.id) + '"'
          + (state.excluded.has(g.id) ? '' : ' checked')
          + ' onchange="toggleSwapSeg(this)" '
          + 'title="Include this segment in the swap">'
          + '<button type="button" class="swap-seg-locate" '
          +   'onclick="locateSwapSeg(\'' + jid + '\')" '
          +   'title="Find this one on the plan">'
          +   '<span class="swap-seg-name">Segment ' + (i + 1) + '</span>'
          +   (len ? '<span class="swap-seg-len">' + esc(len) + '</span>' : '')
          + '</button>'
          + '</div>';
      }).join('');
      const parentAttrs = gr.checked === gr.segs.length ? ' checked'
        : (gr.checked === 0 ? '' : ' data-indeterminate="1"');
      return '<div class="swap-sel-group' + (collapsed ? ' is-collapsed' : '') + '" '
        + 'data-group-key="' + esc(gr.key) + '">'
        + '<div class="swap-sel-group-head" '
        +   'onmouseenter="swapHoverGroup(\'' + escJsStr(gr.key) + '\',1)" '
        +   'onmouseleave="swapHoverGroup(\'' + escJsStr(gr.key) + '\',0)">'
        +   '<button type="button" class="swap-sel-group-chevron" '
        +     'onclick="toggleSwapGroupCollapse(\'' + escJsStr(gr.key) + '\')" '
        +     'title="Show the individual segments">▾</button>'
        +   '<input type="checkbox" class="swap-sel-group-check" '
        +     'data-group-key="' + esc(gr.key) + '"' + parentAttrs
        +     ' onchange="toggleSwapGroup(this)" '
        +     'title="Check or uncheck every ' + esc(gr.name) + ' in the selection">'
        +   '<span class="swap-legend-swatch" style="--swap-swatch:' + gr.color + '"></span>'
        +   '<span class="swap-legend-name">' + esc(gr.name) + '</span>'
        +   '<span class="swap-sel-group-count">' + gr.checked + ' of ' + gr.segs.length + '</span>'
        + '</div>'
        + '<div class="swap-sel-group-body">' + rows + '</div>'
        + '</div>';
    }).join('');

    syncIndeterminate();
    el.scrollTop = scrollTop;
    refreshSelectionMeta();
    updateCollapseAllButton();
  }

  // `indeterminate` is a property, not an attribute — it cannot be set in markup.
  function syncIndeterminate() {
    document.querySelectorAll('#swapSelBreakdown .swap-sel-group-check').forEach(cb => {
      cb.indeterminate = cb.getAttribute('data-indeterminate') === '1';
    });
  }

  // The blast radius goes on the buttons themselves, so it is unambiguous
  // before you commit.
  function updateActionButtons() {
    const n = targetCount();
    const applyBtn = $('swapApplyBtn');
    const delBtn = $('swapDeleteBtn');
    const noun = 'segment' + (n === 1 ? '' : 's');
    applyBtn.textContent = n ? 'Swap ' + n + ' ' + noun : 'Swap';
    applyBtn.disabled = !n || !$('swapTargetType').value;
    delBtn.innerHTML = '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" '
      + 'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
      + '<path d="M2.5 4h11M6 4V2.5h4V4M4 4l1 9.5h6L12 4"/></svg>'
      + (n ? 'Delete ' + n + ' ' + noun : 'Delete selected');
    delBtn.disabled = !n;
  }

  function refreshSelectionMeta() {
    const countEl = $('swapSelCount');
    const total = state.selected.size;
    const checked = targetCount();
    countEl.textContent = (checked === total) ? String(total) : (checked + ' / ' + total);
    countEl.classList.toggle('is-partial', checked !== total);
    updateActionButtons();
  }

  function refreshGroupHead(key) {
    const host = document.querySelector('#swapSelBreakdown .swap-sel-group[data-group-key="'
      + CSS.escape(key) + '"]');
    if (!host) return;
    let total = 0, checked = 0;
    state.selected.forEach(id => {
      const g = segGeomById(id);
      if (!g || groupKeyOf(g) !== key) return;
      total++;
      if (!state.excluded.has(id)) checked++;
    });
    const countEl = host.querySelector('.swap-sel-group-count');
    if (countEl) countEl.textContent = checked + ' of ' + total;
    const parent = host.querySelector('.swap-sel-group-check');
    if (parent) {
      parent.checked = total > 0 && checked === total;
      parent.indeterminate = checked > 0 && checked < total;
    }
  }

  // Row toggles patch the DOM in place rather than re-rendering the panel — a
  // full rebuild would re-sort groups and scroll away from what you are doing.
  window.toggleSwapSeg = function (cb) {
    const id = cb.getAttribute('data-seg-id');
    if (cb.checked) state.excluded.delete(id); else state.excluded.add(id);
    const g = segGeomById(id);
    if (g) refreshGroupHead(groupKeyOf(g));
    refreshSelectionMeta();
    render();
  };

  window.toggleSwapGroup = function (cb) {
    const key = cb.getAttribute('data-group-key');
    const on = cb.checked;
    state.selected.forEach(id => {
      const g = segGeomById(id);
      if (!g || groupKeyOf(g) !== key) return;
      if (on) state.excluded.delete(id); else state.excluded.add(id);
    });
    const host = document.querySelector('#swapSelBreakdown .swap-sel-group[data-group-key="'
      + CSS.escape(key) + '"]');
    if (host) {
      host.querySelectorAll('.swap-seg-row input[type="checkbox"]').forEach(c => { c.checked = on; });
    }
    refreshGroupHead(key);
    refreshSelectionMeta();
    render();
  };

  function allGroupKeys() {
    const keys = new Set();
    state.selected.forEach(id => {
      const g = segGeomById(id);
      if (g) keys.add(groupKeyOf(g));
    });
    return [...keys];
  }

  window.toggleAllSwapGroups = function () {
    const keys = allGroupKeys();
    if (!keys.length) return;
    const anyOpen = keys.some(k => !state.collapsedTypes.has(k));
    if (anyOpen) keys.forEach(k => state.collapsedTypes.add(k));
    else state.collapsedTypes.clear();
    renderSelection();
  };

  function updateCollapseAllButton() {
    const btn = $('swapCollapseAllBtn');
    if (!btn) return;
    const keys = allGroupKeys();
    btn.disabled = !keys.length;
    const anyOpen = keys.some(k => !state.collapsedTypes.has(k));
    btn.textContent = anyOpen ? 'Collapse all' : 'Expand all';
    btn.title = anyOpen ? 'Collapse every wall type' : 'Expand every wall type';
  }

  window.toggleSwapGroupCollapse = function (key) {
    if (state.collapsedTypes.has(key)) state.collapsedTypes.delete(key);
    else state.collapsedTypes.add(key);
    const host = document.querySelector('#swapSelBreakdown .swap-sel-group[data-group-key="'
      + CSS.escape(key) + '"]');
    if (host) host.classList.toggle('is-collapsed', state.collapsedTypes.has(key));
    updateCollapseAllButton();
  };

  window.swapHoverSeg = function (id, on) {
    setHoverSeg(on ? id : null, false);
  };

  window.swapHoverGroup = function (key, on) {
    const next = on ? key : null;
    if (state.hoverGroupKey === next) return;
    state.hoverGroupKey = next;
    requestRender();
  };

  // `fromCanvas` decides which way the highlight travels: pointing at the plan
  // brings the matching row into view, pointing at a row only paints the plan.
  function setHoverSeg(id, fromCanvas) {
    if (state.hoverSegId === id) return;
    state.hoverSegId = id;
    if (fromCanvas) syncHoverRow(id);
    requestRender();
  }

  // Canvas -> panel. This is what removes the need to read a number off the
  // map: point at the wall and its row lights up and scrolls into view.
  function syncHoverRow(id) {
    const host = $('swapSelBreakdown');
    if (!host) return;
    host.querySelectorAll('.is-hovered').forEach(el => el.classList.remove('is-hovered'));
    if (!id) return;
    const row = host.querySelector('.swap-seg-row[data-seg-id="' + CSS.escape(id) + '"]');
    if (row && row.offsetParent) {
      row.classList.add('is-hovered');
      row.scrollIntoView({ block: 'nearest' });
      return;
    }
    // Collapsed group (or a wall that is not in the selection yet) — fall back
    // to flagging the type it belongs to.
    const g = segGeomById(id);
    if (!g) return;
    const grp = host.querySelector('.swap-sel-group[data-group-key="'
      + CSS.escape(groupKeyOf(g)) + '"]');
    if (grp) { grp.classList.add('is-hovered'); grp.scrollIntoView({ block: 'nearest' }); }
  }

  // Panel -> canvas. Only moves the view when the segment is actually off
  // screen, so clicking a row you can already see does not jump the plan.
  window.locateSwapSeg = function (id) {
    const g = segGeomById(id);
    if (!g) return;
    const c = canvas();
    const w = c.clientWidth, h = c.clientHeight;
    const pts = [[g.x1, g.y1], [g.x2, g.y2]].map(([wx, wy]) => ({
      x: wx * state.view.scale + state.view.x,
      y: wy * state.view.scale + state.view.y,
    }));
    const pad = 30;
    const offScreen = pts.some(pt =>
      pt.x < pad || pt.x > w - pad || pt.y < pad || pt.y > h - pad);
    if (offScreen) {
      const midX = (g.x1 + g.x2) / 2, midY = (g.y1 + g.y2) / 2;
      state.view.x = w / 2 - midX * state.view.scale;
      state.view.y = h / 2 - midY * state.view.scale;
      updateStatus();
    }
    setHoverSeg(id, false);
    render();
  };

  window.toggleSwapNumbers = function (cb) {
    state.showNumbers = !!cb.checked;
    render();
  };

  function requestRender() {
    if (state.renderQueued) return;
    state.renderQueued = true;
    requestAnimationFrame(() => { state.renderQueued = false; render(); });
  }

  function updateStatus() {
    const floor = state.floors.find(f => f.id === state.currentFloorId);
    const segCount = state.segGeom.length;
    const total = state.segments.length;
    const missing = segCount < (state.segmentsByFloor.get(state.currentFloorId) || []).length
      ? ' (' + ((state.segmentsByFloor.get(state.currentFloorId) || []).length - segCount) + ' skipped — unreadable geometry)'
      : '';
    $('swapStatus').textContent = `${segCount} walls on this floor · ${total} total in project${missing}`;
    const pct = (state.fitScale > 0 && state.view.scale > 0)
      ? Math.round((state.view.scale / state.fitScale) * 100) : 100;
    $('swapZoomLabel').textContent = pct + '%';
  }

  window.onSwapFloorChange = function () {
    const fid = $('swapFloorSelect').value;
    switchFloor(fid);
  };

  window.onSwapTargetChange = function () {
    updateActionButtons();
  };

  window.setSwapTool = function (tool) {
    state.tool = tool;
    document.querySelectorAll('.swap-tool[data-tool]').forEach(b => {
      b.classList.toggle('active', b.dataset.tool === tool);
    });
    canvas().style.cursor = idleCursor();
  };

  window.clearSwapSelection = function () {
    clearSelectionState();
    renderSelection();
    render();
  };

  window.selectAllOfType = function (typeId) {
    if (!typeId) return;
    addToSelection(state.segGeom.filter(g => g.typeId === typeId).map(g => g.id));
    renderSelection();
    render();
  };

  function resizeCanvas() {
    const wrap = $('swapCanvasWrap');
    const c = canvas();
    const dpr = window.devicePixelRatio || 1;
    const w = wrap.clientWidth;
    const h = wrap.clientHeight;
    c.width = Math.max(1, Math.floor(w * dpr));
    c.height = Math.max(1, Math.floor(h * dpr));
    c.style.width = w + 'px';
    c.style.height = h + 'px';
    ctx().setTransform(dpr, 0, 0, dpr, 0, 0);
    // Self-heal: if we never got a valid fit (modal opened before layout, or a
    // hidden tab), take the first resize that gives us real dimensions.
    if (state.fitScale <= 0 && w > 0 && h > 0) { zoomFit(); return; }
    render();
  }

  window.zoomFit = function () {
    const wrap = $('swapCanvasWrap');
    const w = wrap.clientWidth, h = wrap.clientHeight;
    if (!state.imgW || !state.imgH) return false;
    const pad = 40;
    const scale = Math.min((w - pad) / state.imgW, (h - pad) / state.imgH);
    // The modal's flex layout can still be settling on the first call, which
    // yields a zero (or negative) scale and paints the plan as a speck in the
    // corner. Leave the view alone and let the caller retry next frame.
    if (!Number.isFinite(scale) || scale <= 0) return false;
    state.view.scale = scale;
    state.fitScale = scale;
    state.view.x = (w - state.imgW * scale) / 2;
    state.view.y = (h - state.imgH * scale) / 2;
    updateStatus();
    render();
    return true;
  };

  // Same numbers the Report tool's grid preview uses.
  const ZOOM_MIN = 1, ZOOM_MAX = 8, ZOOM_STEP = 0.15;

  window.zoomIn  = function () { zoomStep(+1, null); };
  window.zoomOut = function () { zoomStep(-1, null); };

  function currentZoom() {
    return state.fitScale > 0 ? state.view.scale / state.fitScale : 1;
  }

  function clampZoom(z) {
    let out = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));
    // Reports snaps anything within 1% of the floor back to an exact fit, so
    // you can never end up almost-but-not-quite zoomed out.
    if (out <= 1.01) out = 1;
    return out;
  }

  // direction: +1 zooms in, -1 zooms out. anchor is a canvas-space point (the
  // pointer, or the centre for the toolbar buttons).
  function zoomStep(direction, anchor) {
    if (!(state.fitScale > 0)) return;
    const zoom = currentZoom();
    applyZoom(clampZoom(zoom + direction * ZOOM_STEP * zoom), anchor);
  }

  function applyZoom(newZoom, anchor) {
    if (!(state.fitScale > 0)) return;
    // At the floor Reports drops the pan entirely and returns to the centred
    // view, rather than leaving a fit-sized image parked off to one side.
    if (newZoom === ZOOM_MIN) { zoomFit(); return; }
    const rect = canvas().getBoundingClientRect();
    const ax = anchor ? anchor.x : rect.width / 2;
    const ay = anchor ? anchor.y : rect.height / 2;
    const worldX = (ax - state.view.x) / state.view.scale;
    const worldY = (ay - state.view.y) / state.view.scale;
    const newScale = state.fitScale * newZoom;
    state.view.scale = newScale;
    state.view.x = ax - worldX * newScale;
    state.view.y = ay - worldY * newScale;
    updateStatus();
    render();
  }

  function screenToWorld(sx, sy) {
    return {
      x: (sx - state.view.x) / state.view.scale,
      y: (sy - state.view.y) / state.view.scale,
    };
  }

  function render() {
    const c = canvas();
    const g = ctx();
    const w = c.clientWidth, h = c.clientHeight;
    g.save();
    g.clearRect(0, 0, w, h);

    g.fillStyle = getComputedStyle(document.body).getPropertyValue('--bg') || '#0f1620';
    g.fillRect(0, 0, w, h);

    g.translate(state.view.x, state.view.y);
    g.scale(state.view.scale, state.view.scale);

    if (state.loadedImage) {
      g.drawImage(state.loadedImage, 0, 0, state.imgW, state.imgH);
      g.fillStyle = 'rgba(0,0,0,0.15)';
      g.fillRect(0, 0, state.imgW, state.imgH);
    } else {
      g.strokeStyle = '#3a4553';
      g.lineWidth = 2 / state.view.scale;
      g.strokeRect(0, 0, state.imgW, state.imgH);
    }

    const zoomRatio = state.fitScale > 0 ? state.view.scale / state.fitScale : 1;
    const baseScreenPx = Math.max(2.5, Math.min(14, 3 * Math.sqrt(zoomRatio)));
    const selScreenPx  = baseScreenPx + 3;
    const baseWidth = baseScreenPx / state.view.scale;
    const selWidth  = selScreenPx  / state.view.scale;

    const hi = highlightIds();
    const dim = hi.size ? 0.18 : 1;

    g.lineCap = 'round';
    const stroke = (seg) => {
      g.beginPath();
      g.moveTo(seg.x1, seg.y1);
      g.lineTo(seg.x2, seg.y2);
      g.stroke();
    };

    // Pass 1 — walls the marquee never touched.
    g.globalAlpha = dim;
    for (const seg of state.segGeom) {
      if (state.selected.has(seg.id)) continue;
      g.strokeStyle = colorOf(seg);
      g.lineWidth = baseWidth;
      stroke(seg);
    }
    g.globalAlpha = 1;

    // Pass 2 — in the selection but unchecked. Dimmed and dashed, so what you
    // culled stays visible (and re-checkable) without reading as targeted.
    g.setLineDash([6 / state.view.scale, 5 / state.view.scale]);
    for (const seg of state.segGeom) {
      if (!state.selected.has(seg.id) || !state.excluded.has(seg.id)) continue;
      g.globalAlpha = 0.4 * dim;
      g.strokeStyle = colorOf(seg);
      g.lineWidth = baseWidth;
      stroke(seg);
      g.globalAlpha = 1;
    }
    g.setLineDash([]);

    // Pass 3 — still checked: this is exactly what the Swap button will change.
    g.globalAlpha = dim;
    for (const seg of state.segGeom) {
      if (!state.selected.has(seg.id) || state.excluded.has(seg.id)) continue;
      if (hi.has(seg.id)) continue;
      g.strokeStyle = '#ffffff';
      g.lineWidth = selWidth + 4 / state.view.scale;
      stroke(seg);
      g.strokeStyle = colorOf(seg);
      g.lineWidth = selWidth;
      stroke(seg);
    }
    g.globalAlpha = 1;

    // Pass 4 — whatever is being pointed at: one segment (hovered on the plan
    // or in the panel) or every member of a hovered wall-type group. Everything
    // else is dimmed above, so this reads as a spotlight rather than an outline.
    if (hi.size) {
      const px = (v) => v / state.view.scale;
      for (const seg of state.segGeom) {
        if (!hi.has(seg.id)) continue;
        g.strokeStyle = '#ffffff';
        g.lineWidth = selWidth + px(20);
        g.globalAlpha = 0.85;
        stroke(seg);
        g.globalAlpha = 1;
        g.strokeStyle = '#0ea5e9';
        g.lineWidth = selWidth + px(12);
        stroke(seg);
        g.strokeStyle = colorOf(seg);
        g.lineWidth = selWidth + px(2);
        stroke(seg);
        // End caps make a short segment findable even on a busy wall run.
        g.fillStyle = '#0ea5e9';
        [[seg.x1, seg.y1], [seg.x2, seg.y2]].forEach(([cx, cy]) => {
          g.beginPath();
          g.arc(cx, cy, px(5), 0, Math.PI * 2);
          g.fill();
          g.strokeStyle = '#ffffff';
          g.lineWidth = px(1.5);
          g.stroke();
        });
      }
    }
    g.restore();

    drawSegmentNumbers(hi);

    if (state.isDragging && state.pressMoved && state.tool === 'marquee'
        && state.dragStart && state.dragCurrent) {
      const x = Math.min(state.dragStart.x, state.dragCurrent.x);
      const y = Math.min(state.dragStart.y, state.dragCurrent.y);
      const rw = Math.abs(state.dragCurrent.x - state.dragStart.x);
      const rh = Math.abs(state.dragCurrent.y - state.dragStart.y);
      g.strokeStyle = '#0ea5e9';
      g.fillStyle = 'rgba(14,165,233,0.12)';
      g.lineWidth = 1.5;
      g.setLineDash([5, 4]);
      g.fillRect(x, y, rw, rh);
      g.strokeRect(x, y, rw, rh);
      g.setLineDash([]);
    }
  }

  function highlightIds() {
    const out = new Set();
    if (state.hoverSegId) out.add(state.hoverSegId);
    if (state.hoverGroupKey) {
      state.selected.forEach(id => {
        const seg = segGeomById(id);
        if (seg && groupKeyOf(seg) === state.hoverGroupKey) out.add(id);
      });
    }
    return out;
  }

  // Optional, off by default. Numbers are drawn in screen space so they stay
  // legible at any zoom, and only for the current selection — labelling every
  // wall on a CAD import would be unreadable soup.
  function drawSegmentNumbers(hi) {
    if (!state.showNumbers || !state.selected.size) return;
    const g = ctx();
    const c = canvas();
    const viewW = c.clientWidth, viewH = c.clientHeight;
    g.save();
    g.font = '600 11px ' + (getComputedStyle(document.body).getPropertyValue('--mono') || 'monospace');
    g.textAlign = 'center';
    g.textBaseline = 'middle';

    // Draw the biggest segments first so that when labels are too dense to all
    // fit, the ones that survive are the ones worth reading.
    const ordered = [];
    state.selected.forEach(id => {
      const seg = segGeomById(id);
      if (seg && state.segOrdinal.get(id)) ordered.push(seg);
    });
    ordered.sort((a, b) => Math.hypot(b.x2 - b.x1, b.y2 - b.y1)
                         - Math.hypot(a.x2 - a.x1, a.y2 - a.y1));

    const placed = [];
    const overlaps = (r) => placed.some(q =>
      r.x < q.x + q.w && r.x + r.w > q.x && r.y < q.y + q.h && r.y + r.h > q.y);

    ordered.forEach(seg => {
      const num = state.segOrdinal.get(seg.id);
      const x = ((seg.x1 + seg.x2) / 2) * state.view.scale + state.view.x;
      const y = ((seg.y1 + seg.y2) / 2) * state.view.scale + state.view.y;
      if (x < -40 || y < -40 || x > viewW + 40 || y > viewH + 40) return;
      const label = String(num);
      const w = Math.max(18, g.measureText(label).width + 12);
      const rect = { x: x - w / 2, y: y - 9, w, h: 18 };
      // A hovered label always wins its space; the rest yield to whatever was
      // placed first.
      const forced = hi.has(seg.id);
      if (!forced && overlaps(rect)) return;
      placed.push(rect);

      g.globalAlpha = state.excluded.has(seg.id) ? 0.5 : 1;
      // Ordinals restart per wall type, so three different segments on one wall
      // can all read "2". Tint the pill with the type colour to disambiguate —
      // the number alone is not enough to identify a segment.
      const pill = forced ? '#0ea5e9' : colorOf(seg);
      g.fillStyle = pill;
      roundRect(g, rect.x, rect.y, rect.w, rect.h, 9);
      g.fill();
      g.strokeStyle = forced ? '#ffffff' : 'rgba(0,0,0,0.45)';
      g.lineWidth = forced ? 2 : 1;
      g.stroke();
      g.fillStyle = readableOn(pill);
      g.fillText(label, x, y);
      g.globalAlpha = 1;
    });
    g.restore();
  }

  // Pick black or white text for a pill of the given fill, so a pale wall-type
  // colour does not produce white-on-white.
  function readableOn(hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(String(hex).trim());
    if (!m) return '#ffffff';
    const v = parseInt(m[1], 16);
    const r = (v >> 16) & 255, gg = (v >> 8) & 255, b = v & 255;
    // Rec. 601 luma is plenty for a two-way choice.
    return (0.299 * r + 0.587 * gg + 0.114 * b) > 150 ? '#10161f' : '#ffffff';
  }

  function roundRect(g, x, y, w, h, r) {
    g.beginPath();
    g.moveTo(x + r, y);
    g.arcTo(x + w, y, x + w, y + h, r);
    g.arcTo(x + w, y + h, x, y + h, r);
    g.arcTo(x, y + h, x, y, r);
    g.arcTo(x, y, x + w, y, r);
    g.closePath();
  }

  function segmentInRect(seg, rx1, ry1, rx2, ry2) {
    const xmin = Math.min(rx1, rx2), xmax = Math.max(rx1, rx2);
    const ymin = Math.min(ry1, ry2), ymax = Math.max(ry1, ry2);

    const inside = (x, y) => x >= xmin && x <= xmax && y >= ymin && y <= ymax;
    if (inside(seg.x1, seg.y1) || inside(seg.x2, seg.y2)) return true;

    return (
      segmentsIntersect(seg.x1, seg.y1, seg.x2, seg.y2, xmin, ymin, xmax, ymin) ||
      segmentsIntersect(seg.x1, seg.y1, seg.x2, seg.y2, xmax, ymin, xmax, ymax) ||
      segmentsIntersect(seg.x1, seg.y1, seg.x2, seg.y2, xmax, ymax, xmin, ymax) ||
      segmentsIntersect(seg.x1, seg.y1, seg.x2, seg.y2, xmin, ymax, xmin, ymin)
    );
  }

  function segmentsIntersect(ax, ay, bx, by, cx, cy, dx, dy) {
    const d1 = orient(cx, cy, dx, dy, ax, ay);
    const d2 = orient(cx, cy, dx, dy, bx, by);
    const d3 = orient(ax, ay, bx, by, cx, cy);
    const d4 = orient(ax, ay, bx, by, dx, dy);
    return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) &&
           ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0));
  }

  function orient(ax, ay, bx, by, cx, cy) {
    return (by - ay) * (cx - bx) - (bx - ax) * (cy - by);
  }

  function pointSegmentDistance(px, py, x1, y1, x2, y2) {
    const dx = x2 - x1, dy = y2 - y1;
    const len2 = dx * dx + dy * dy;
    if (len2 === 0) return Math.hypot(px - x1, py - y1);
    let t = ((px - x1) * dx + (py - y1) * dy) / len2;
    t = Math.max(0, Math.min(1, t));
    const qx = x1 + t * dx, qy = y1 + t * dy;
    return Math.hypot(px - qx, py - qy);
  }

  function pickSegmentAt(worldX, worldY, worldTolerance) {
    let best = null, bestDist = worldTolerance;
    for (const seg of state.segGeom) {
      const d = pointSegmentDistance(worldX, worldY, seg.x1, seg.y1, seg.x2, seg.y2);
      if (d < bestDist) { best = seg; bestDist = d; }
    }
    return best;
  }

  // The checkbox tree needs room on a dense floor, so the panel is draggable
  // like Paint Shop Pro's. Width is a view preference, not project data, so it
  // lives in localStorage — and unlike a hidden filter it is plainly visible,
  // which is why persisting it here is safe.
  // The splitter itself lives in wd-shared.js so Visual Wall Swap and the AP
  // Labeler share one implementation rather than two copies that drift.
  const SIDEBAR_KEY = 'wd.walls.swapSidebarWidth';
  const SIDEBAR_MIN = 260;
  const SIDEBAR_DEFAULT = 320;
  let _splitter = null;

  function reflowSidebarWidth() {
    if (_splitter) _splitter.reflow();
  }

  function applySidebarWidth(px, persist) {
    if (_splitter) _splitter.set(px, persist);
  }

  function installSplitter() {
    _splitter = WD.mountSplitter({
      splitter: 'swapSplitter',
      panel: 'swapSidebar',
      container: '.swap-body',
      key: SIDEBAR_KEY,
      min: SIDEBAR_MIN,
      def: SIDEBAR_DEFAULT,
      maxRatio: 0.6,
      onResize: resizeCanvas,
    });
  }

  function initSidebarWidth() {
    // mountSplitter already reads the stored width and reflows; kept as a
    // named step so the call site still reads in order.
    reflowSidebarWidth();
  }

  // Collapsible side panels, Paint Shop Pro style — folding Quick Swap away is
  // how you give the selection tree the whole column on a dense floor.
  const FOLD_KEY = 'wd.walls.swapFolded';

  function readFolded() {
    try {
      const raw = localStorage.getItem(FOLD_KEY);
      return raw ? new Set(JSON.parse(raw)) : new Set();
    } catch (e) { return new Set(); }
  }

  function writeFolded(set) {
    try { localStorage.setItem(FOLD_KEY, JSON.stringify([...set])); } catch (e) { /* private mode */ }
  }

  function applyFolded() {
    const folded = readFolded();
    document.querySelectorAll('.swap-panel-foldable').forEach(el => {
      el.classList.toggle('is-folded', folded.has(el.dataset.fold));
    });
    resizeCanvas();
  }

  window.toggleSwapPanel = function (key) {
    const folded = readFolded();
    if (folded.has(key)) folded.delete(key); else folded.add(key);
    writeFolded(folded);
    applyFolded();
  };

  const evHandlers = {};

  function installEventListeners() {
    const c = canvas();
    evHandlers.mousedown = onMouseDown;
    evHandlers.mousemove = onMouseMove;
    evHandlers.mouseup   = onMouseUp;
    evHandlers.wheel     = onWheel;
    evHandlers.contextmenu = (ev) => ev.preventDefault();
    evHandlers.mouseleave = () => {
      if (state.isPanning || state.isDragging) return;
      setHoverSeg(null, true);
      canvas().style.cursor = idleCursor();
    };
    evHandlers.touchstart  = onTouchStart;
    evHandlers.touchmove   = onTouchMove;
    evHandlers.touchend    = onTouchEnd;
    evHandlers.keydown   = onKeyDown;
    evHandlers.spaceOff  = WD.PanZoom.onChange(onSpaceChange);
    evHandlers.resize    = () => { reflowSidebarWidth(); resizeCanvas(); };
    evHandlers.railClick = (e) => {
      const btn = e.target.closest('.swap-tool');
      if (btn) btn.blur();
    };
    c.addEventListener('mousedown', evHandlers.mousedown);
    window.addEventListener('mousemove', evHandlers.mousemove);
    window.addEventListener('mouseup', evHandlers.mouseup);
    c.addEventListener('wheel', evHandlers.wheel, { passive: false });
    c.addEventListener('contextmenu', evHandlers.contextmenu);
    c.addEventListener('mouseleave', evHandlers.mouseleave);
    c.addEventListener('touchstart', evHandlers.touchstart, { passive: false });
    c.addEventListener('touchmove', evHandlers.touchmove, { passive: false });
    c.addEventListener('touchend', evHandlers.touchend);
    c.addEventListener('touchcancel', evHandlers.touchend);
    window.addEventListener('keydown', evHandlers.keydown);
    window.addEventListener('resize', evHandlers.resize);
    const rail = document.querySelector('.swap-toolrail');
    if (rail) rail.addEventListener('click', evHandlers.railClick);
    if (typeof ResizeObserver === 'function') {
      evHandlers.ro = new ResizeObserver(() => resizeCanvas());
      evHandlers.ro.observe($('swapCanvasWrap'));
      evHandlers.roBody = new ResizeObserver(() => reflowSidebarWidth());
      const body = document.querySelector('.swap-body');
      if (body) evHandlers.roBody.observe(body);
    }
    installSplitter();
    initSidebarWidth();
    applyFolded();
    updateHistoryButtons();
    setSwapTool(state.tool);
  }

  function uninstallEventListeners() {
    const c = canvas();
    c.removeEventListener('mousedown', evHandlers.mousedown);
    window.removeEventListener('mousemove', evHandlers.mousemove);
    window.removeEventListener('mouseup', evHandlers.mouseup);
    c.removeEventListener('wheel', evHandlers.wheel);
    c.removeEventListener('contextmenu', evHandlers.contextmenu);
    c.removeEventListener('mouseleave', evHandlers.mouseleave);
    c.removeEventListener('touchstart', evHandlers.touchstart);
    c.removeEventListener('touchmove', evHandlers.touchmove);
    c.removeEventListener('touchend', evHandlers.touchend);
    c.removeEventListener('touchcancel', evHandlers.touchend);
    window.removeEventListener('keydown', evHandlers.keydown);
    if (evHandlers.spaceOff) { evHandlers.spaceOff(); evHandlers.spaceOff = null; }
    window.removeEventListener('resize', evHandlers.resize);
    const rail = document.querySelector('.swap-toolrail');
    if (rail && evHandlers.railClick) rail.removeEventListener('click', evHandlers.railClick);
    if (evHandlers.ro) { evHandlers.ro.disconnect(); evHandlers.ro = null; }
    if (evHandlers.roBody) { evHandlers.roBody.disconnect(); evHandlers.roBody = null; }
  }

  function canvasPoint(e) {
    const rect = canvas().getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function idleCursor() {
    if (state.tool === 'pan' || state.spaceHeld) return 'grab';
    return state.tool === 'click' ? 'pointer' : 'crosshair';
  }

  // Reports flags the whole preview container while a drag is in flight and
  // forces `grabbing` on every descendant; do the same so the cursor never
  // reverts mid-drag over the canvas.
  function startPan(p) {
    state.isPanning = true;
    state.panViaSpace = state.spaceHeld;
    state.dragStart = { ...p, viewX: state.view.x, viewY: state.view.y };
    const wrap = $('swapCanvasWrap');
    if (wrap) wrap.classList.add('pan-active');
  }

  function endPan() {
    state.isPanning = false;
    state.dragStart = null;
    const wrap = $('swapCanvasWrap');
    if (wrap) wrap.classList.remove('pan-active');
    canvas().style.cursor = idleCursor();
  }

  function onMouseDown(e) {
    const p = canvasPoint(e);
    // Right- and middle-drag pan from any tool. Right-drag is the CAD/Ekahau
    // reflex, and unlike Space+drag or the H tool it needs no mode change.
    const panBtn = e.button === 1 || e.button === 2;
    if (panBtn || state.spaceHeld || state.tool === 'pan') {
      startPan(p);
      e.preventDefault();
      return;
    }
    state.pressStart = p;
    state.pressMoved = false;
    if (state.tool === 'marquee') {
      state.isDragging = true;
      state.dragStart = p;
      state.dragCurrent = p;
    }
  }

  const HIT_TOL_PX = 8;

  function hitAt(p) {
    const w = screenToWorld(p.x, p.y);
    return pickSegmentAt(w.x, w.y, HIT_TOL_PX / state.view.scale);
  }

  // A plain click on a wall toggles that wall's checkbox — the whole point of
  // the exercise, since pointing at the thing you can see beats reading a
  // number off it. A wall that is not in the selection joins it, checked.
  function clickSegment(hit, shiftKey) {
    if (!hit) {
      if (!shiftKey) { clearSelectionState(); renderSelection(); render(); }
      return;
    }
    if (state.selected.has(hit.id)) {
      if (state.excluded.has(hit.id)) state.excluded.delete(hit.id);
      else state.excluded.add(hit.id);
    } else {
      addToSelection([hit.id]);
    }
    renderSelection();
    syncHoverRow(hit.id);
    render();
  }

  function onMouseMove(e) {
    const p = canvasPoint(e);
    if (state.isPanning && state.dragStart) {
      state.view.x = state.dragStart.viewX + (p.x - state.dragStart.x);
      state.view.y = state.dragStart.viewY + (p.y - state.dragStart.y);
      render();
      return;
    }
    if (state.pressStart && !state.pressMoved) {
      const moved = Math.hypot(p.x - state.pressStart.x, p.y - state.pressStart.y);
      if (moved > 4) state.pressMoved = true;
    }
    if (state.isDragging) {
      state.dragCurrent = p;
      render();
      return;
    }
    // Idle: identify the wall under the pointer and light up its row.
    const hit = hitAt(p);
    const id = hit ? hit.id : null;
    if (id !== state.hoverSegId) {
      setHoverSeg(id, true);
      canvas().style.cursor = id ? 'pointer' : idleCursor();
    }
  }

  function onMouseUp(e) {
    if (state.isPanning) {
      endPan();
      return;
    }
    const wasDrag = state.pressMoved;
    const press = state.pressStart;
    state.pressStart = null;
    state.pressMoved = false;

    if (state.isDragging) {
      state.isDragging = false;
      const a = state.dragStart, b = state.dragCurrent;
      state.dragStart = null;
      state.dragCurrent = null;
      if (wasDrag && a && b) {
        if (!e.shiftKey) clearSelectionState();
        const w1 = screenToWorld(a.x, a.y);
        const w2 = screenToWorld(b.x, b.y);
        addToSelection(state.segGeom
          .filter(seg => segmentInRect(seg, w1.x, w1.y, w2.x, w2.y))
          .map(seg => seg.id));
        renderSelection();
        render();
        return;
      }
    }
    if (!wasDrag && press) clickSegment(hitAt(press), e.shiftKey);
  }

  function touchPoints(e) {
    const rect = canvas().getBoundingClientRect();
    return [...e.touches].map(t => ({ x: t.clientX - rect.left, y: t.clientY - rect.top }));
  }

  function onTouchStart(e) {
    const pts = touchPoints(e);
    if (pts.length >= 2) {
      e.preventDefault();
      state.isDragging = false;
      state.isPanning = false;
      const mid = { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 };
      state.touch = {
        mode: 'pinch',
        mid,
        dist: Math.max(1, Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y)),
        world: screenToWorld(mid.x, mid.y),
        scale: state.view.scale,
      };
      render();
      return;
    }
    if (pts.length !== 1) return;
    e.preventDefault();
    const p = pts[0];
    if (state.tool === 'pan' || state.spaceHeld) {
      state.touch = { mode: 'pan' };
      startPan(p);
      return;
    }
    if (state.tool === 'click') {
      state.touch = { mode: 'tap', start: p };
      return;
    }
    state.touch = { mode: 'marquee' };
    state.isDragging = true;
    state.dragStart = p;
    state.dragCurrent = p;
    clearSelectionState();
    renderSelection();
    render();
  }

  function onTouchMove(e) {
    if (!state.touch) return;
    const pts = touchPoints(e);
    if (state.touch.mode === 'pinch' && pts.length >= 2) {
      e.preventDefault();
      const t = state.touch;
      const mid = { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 };
      const dist = Math.max(1, Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y));
      // Pan and zoom fall out of one equation: keep the world point that was
      // under the initial midpoint pinned under the current midpoint.
      const zoom = clampZoom((t.scale / state.fitScale) * (dist / t.dist));
      const scale = state.fitScale * zoom;
      state.view.scale = scale;
      state.view.x = mid.x - t.world.x * scale;
      state.view.y = mid.y - t.world.y * scale;
      updateStatus();
      render();
      return;
    }
    if (pts.length !== 1) return;
    e.preventDefault();
    const p = pts[0];
    if (state.touch.mode === 'pan' && state.dragStart) {
      state.view.x = state.dragStart.viewX + (p.x - state.dragStart.x);
      state.view.y = state.dragStart.viewY + (p.y - state.dragStart.y);
      render();
    } else if (state.touch.mode === 'marquee' && state.isDragging) {
      state.dragCurrent = p;
      render();
    } else if (state.touch.mode === 'tap') {
      state.touch.moved = true;
    }
  }

  function onTouchEnd(e) {
    const t = state.touch;
    if (!t) return;
    if (e.touches.length > 0) return;
    state.touch = null;
    if (t.mode === 'pinch' || t.mode === 'pan') { endPan(); return; }
    if (t.mode === 'tap') {
      if (!t.moved && t.start) {
        const w = screenToWorld(t.start.x, t.start.y);
        clickSegment(pickSegmentAt(w.x, w.y, 14 / state.view.scale), false);
      }
      return;
    }
    if (t.mode === 'marquee' && state.isDragging) {
      state.isDragging = false;
      const a = state.dragStart, b = state.dragCurrent;
      if (a && b) {
        const w1 = screenToWorld(a.x, a.y);
        const w2 = screenToWorld(b.x, b.y);
        addToSelection(state.segGeom
          .filter(seg => segmentInRect(seg, w1.x, w1.y, w2.x, w2.y))
          .map(seg => seg.id));
      }
      state.dragStart = null;
      state.dragCurrent = null;
      renderSelection();
      render();
    }
  }

  function onWheel(e) {
    e.preventDefault();
    zoomStep(e.deltaY > 0 ? -1 : +1, canvasPoint(e));
  }

  function isFormFocused() {
    const el = document.activeElement;
    if (!el) return false;
    const tag = el.tagName;
    return tag === 'SELECT' || tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
  }

  function onKeyDown(e) {
    if (e.key === 'Escape') {
      if (state.selected.size) {
        clearSelectionState();
        renderSelection();
        render();
      } else {
        closeSwapModal();
      }
      return;
    }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) {
      e.preventDefault();
      if (e.shiftKey) swapRedo(); else swapUndo();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || e.key === 'Y')) {
      e.preventDefault();
      swapRedo();
      return;
    }
    if ((e.key === 'a' || e.key === 'A') && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      addToSelection(state.segGeom.map(g => g.id));
      renderSelection();
      render();
    }
    if (isFormFocused()) return;
    if (e.key === 'm' || e.key === 'M') setSwapTool('marquee');
    if (e.key === 'v' || e.key === 'V') setSwapTool('click');
    if (e.key === 'h' || e.key === 'H') setSwapTool('pan');
  }

  // Space is tracked by WD.PanZoom so that Report and Quick Walls agree on what
  // counts as a pan, and so that typing a space into a name box stays typing.
  function onSpaceChange(isHeld) {
    state.spaceHeld = isHeld;
    if (!isHeld && state.isPanning && state.panViaSpace) { endPan(); render(); return; }
    if (!state.isPanning) canvas().style.cursor = idleCursor();
  }

  window.applySelectionSwap = function () {
    const targetId = $('swapTargetType').value;
    if (!targetId) { toast('Pick a target wall type'); return; }
    const doomed = new Set(targetIds());
    if (!doomed.size) { toast('Nothing checked'); return; }

    const target = typeById(targetId);
    if (!target) { toast('Target wall type not found'); return; }

    const before = selectionSnapshot();
    const changes = [];
    for (const seg of state.segments) {
      if (doomed.has(seg.id) && segmentTypeId(seg) !== targetId) {
        changes.push({ id: seg.id, from: segmentTypeId(seg), to: targetId });
      }
    }
    if (!changes.length) { toast(`Already ${target.name} — nothing to change`); return; }

    const n = applyTypeChanges(state.segments, changes);
    refreshGeomTypes();

    const label = `Swap ${n} wall${n === 1 ? '' : 's'} → ${target.name}`;
    pushHistory({ kind: 'type', label, changes, before, after: selectionSnapshot() });

    writeSegmentsBack();
    undoToast(`Swapped ${n} wall${n === 1 ? '' : 's'} → ${target.name}`);

    renderLegend();
    renderSelection();
    render();
  };

  window.applyQuickSwap = function () {
    const fromId = $('swapFromType').value;
    const toId   = $('swapToType').value;
    const scope  = $('swapScope').value;
    if (!fromId || !toId) { toast('Pick both a From and a To wall type'); return; }
    if (fromId === toId) { toast('From and To are the same — nothing to swap'); return; }

    const target = typeById(toId);
    if (!target) { toast('Target wall type not found'); return; }

    const before = selectionSnapshot();
    const changes = [];
    for (const seg of state.segments) {
      if (segmentTypeId(seg) !== fromId) continue;
      if (scope === 'floor' && segmentFloorId(seg) !== state.currentFloorId) continue;
      changes.push({ id: seg.id, from: fromId, to: toId });
    }
    if (!changes.length) { toast('No walls of that type in scope'); return; }

    const n = applyTypeChanges(state.segments, changes);
    refreshGeomTypes();

    const scopeLbl = scope === 'floor' ? 'on this floor' : 'across the project';
    const label = `Swap all ${n} ${typeById(fromId)?.name || 'wall'} → ${target.name} ${scopeLbl}`;
    pushHistory({ kind: 'type', label, changes, before, after: selectionSnapshot() });

    writeSegmentsBack();
    undoToast(`Swapped ${n} wall${n === 1 ? '' : 's'} → ${target.name} ${scopeLbl}`);
    renderLegend();
    renderSelection();
    render();
  };

  window.deleteSelectedWalls = function () {
    const doomed = new Set(targetIds());
    const n = doomed.size;
    if (!n) { toast('Nothing checked'); return; }
    if (!confirm(`Delete ${n} wall${n === 1 ? '' : 's'} from the project? Nothing is written to disk until you press Save the *.esx.`)) return;

    const before = selectionSnapshot();
    // Keep the original index so an undo puts each wall back where it was.
    const removed = [];
    state.segments.forEach((seg, index) => {
      if (doomed.has(seg.id)) removed.push({ index, seg });
    });

    state.segments = state.segments.filter(seg => !doomed.has(seg.id));
    rebuildFloorIndex();
    state.segGeom = state.segGeom.filter(g => !doomed.has(g.id));

    doomed.forEach(id => { state.selected.delete(id); state.excluded.delete(id); });
    pruneExcluded();

    const label = `Delete ${n} wall${n === 1 ? '' : 's'}`;
    pushHistory({ kind: 'delete', label, removed, before, after: selectionSnapshot() });

    writeSegmentsBack();
    populateFloorSelect();
    $('swapFloorSelect').value = state.currentFloorId;
    renderLegend();
    renderSelection();
    updateStatus();
    render();
    undoToast(`Deleted ${n} wall${n === 1 ? '' : 's'}`);
  };

  const HISTORY_LIMIT = 50;

  function selectionSnapshot() {
    return { selected: [...state.selected], excluded: [...state.excluded] };
  }

  function restoreSelection(snap) {
    if (!snap) return;
    state.selected = new Set(snap.selected);
    state.excluded = new Set(snap.excluded);
    pruneExcluded();
  }

  function pushHistory(entry) {
    // Anything redoable is discarded the moment a new edit lands.
    state.history.length = state.historyIndex + 1;
    state.history.push(entry);
    if (state.history.length > HISTORY_LIMIT) state.history.shift();
    state.historyIndex = state.history.length - 1;
    updateHistoryButtons();
  }

  function canUndo() { return state.historyIndex >= 0; }
  function canRedo() { return state.historyIndex < state.history.length - 1; }

  function rebuildFloorIndex() {
    state.segmentsByFloor.clear();
    state.segments.forEach(seg => {
      const fid = segmentFloorId(seg);
      if (!fid) return;
      if (!state.segmentsByFloor.has(fid)) state.segmentsByFloor.set(fid, []);
      state.segmentsByFloor.get(fid).push(seg);
    });
  }

  // Re-derive the on-screen geometry for the current floor from state.segments,
  // which is the source of truth an undo has just rewritten.
  function refreshGeomTypes() {
    const byId = new Map();
    state.segments.forEach(seg => byId.set(seg.id, seg));
    state.segGeom.forEach(g => {
      const seg = byId.get(g.id);
      if (seg) g.typeId = segmentTypeId(seg);
    });
  }

  function rebuildGeomForCurrentFloor() {
    const floorSegs = state.segmentsByFloor.get(state.currentFloorId) || [];
    state.segGeom = [];
    floorSegs.forEach(seg => {
      const ep = segmentEndpoints(seg);
      if (!ep) return;
      state.segGeom.push({
        id: seg.id,
        typeId: segmentTypeId(seg),
        x1: ep.x1, y1: ep.y1, x2: ep.x2, y2: ep.y2,
      });
    });
  }

  function afterHistoryStep() {
    writeSegmentsBack();
    populateFloorSelect();
    const fsel = $('swapFloorSelect');
    if (fsel) fsel.value = state.currentFloorId;
    renderLegend();
    renderSelection();
    updateStatus();
    render();
    updateHistoryButtons();
  }

  window.swapUndo = function () {
    if (!canUndo()) { toast('Nothing to undo'); return; }
    const entry = state.history[state.historyIndex];
    if (entry.kind === 'type') {
      applyTypeChanges(state.segments, invertTypeChanges(entry.changes));
      refreshGeomTypes();
    } else if (entry.kind === 'delete') {
      state.segments = restoreRemoved(state.segments, entry.removed);
      rebuildFloorIndex();
      rebuildGeomForCurrentFloor();
    }
    restoreSelection(entry.before);
    state.historyIndex--;
    afterHistoryStep();
    toast('Undid: ' + entry.label, 'success');
  };

  window.swapRedo = function () {
    if (!canRedo()) { toast('Nothing to redo'); return; }
    const entry = state.history[state.historyIndex + 1];
    if (entry.kind === 'type') {
      applyTypeChanges(state.segments, entry.changes);
      refreshGeomTypes();
    } else if (entry.kind === 'delete') {
      const gone = new Set(entry.removed.map(r => r.seg.id));
      state.segments = state.segments.filter(seg => !gone.has(seg.id));
      rebuildFloorIndex();
      rebuildGeomForCurrentFloor();
    }
    restoreSelection(entry.after);
    state.historyIndex++;
    afterHistoryStep();
    toast('Redid: ' + entry.label, 'success');
  };

  function updateHistoryButtons() {
    const u = $('swapUndoBtn'), r = $('swapRedoBtn');
    if (u) {
      u.disabled = !canUndo();
      u.title = canUndo()
        ? 'Undo: ' + state.history[state.historyIndex].label + '  (Ctrl+Z)'
        : 'Nothing to undo  (Ctrl+Z)';
    }
    if (r) {
      r.disabled = !canRedo();
      r.title = canRedo()
        ? 'Redo: ' + state.history[state.historyIndex + 1].label + '  (Ctrl+Y)'
        : 'Nothing to redo  (Ctrl+Y)';
    }
  }

  // A toast you can act on, so the fix for a mis-click is right where you are
  // looking when you make it.
  let _undoToastTimer = null;
  function undoToast(msg) {
    const el = $('swapUndoToast');
    if (!el) { toast(msg, 'success'); return; }
    $('swapUndoToastMsg').textContent = msg;
    el.classList.add('visible');
    clearTimeout(_undoToastTimer);
    _undoToastTimer = setTimeout(() => el.classList.remove('visible'), 9000);
  }

  window.dismissUndoToast = function () {
    const el = $('swapUndoToast');
    if (el) el.classList.remove('visible');
    clearTimeout(_undoToastTimer);
  };

  window.undoFromToast = function () {
    dismissUndoToast();
    swapUndo();
  };

  function writeSegmentsBack() {
    const zip = window.esxZip;
    if (!zip) return;
    const payload = JSON.stringify({ wallSegments: state.segments }, null, 2);
    zip.file('wallSegments.json', payload);
  }

  window.__wallsSwap = {
    getView: () => ({ ...state.view }),
    getFitScale: () => state.fitScale,
    getZoom: () => currentZoom(),
    getHover: () => ({ seg: state.hoverSegId, group: state.hoverGroupKey }),
    getHistory: () => ({
      labels: state.history.map(h => h.label),
      index: state.historyIndex,
      canUndo: canUndo(), canRedo: canRedo(),
    }),
    getSegTypes: () => state.segments.map(x => ({ id: x.id, type: segmentTypeId(x) })),
    getSegmentCount: () => state.segments.length,
    getSidebarPref: () => (_splitter ? _splitter.get() : SIDEBAR_DEFAULT),
    getSidebarWidth: () => {
      const el = $('swapSidebar');
      return el ? Math.round(el.getBoundingClientRect().width) : 0;
    },
    setSidebarWidth: (px, persist) => applySidebarWidth(px, !!persist),
    getHighlighted: () => [...highlightIds()],
    getOrdinal: (id) => state.segOrdinal.get(id) || null,
    hitAtWorld: (wx, wy) => {
      const hit = pickSegmentAt(wx, wy, HIT_TOL_PX / state.view.scale);
      return hit ? hit.id : null;
    },
    getTool: () => state.tool,
    getIsPanning: () => state.isPanning,
    getSelected: () => [...state.selected],
    getExcluded: () => [...state.excluded],
    getTargetIds: () => targetIds(),
    getGroups: () => selectionGroups().map(g => ({
      key: g.key, name: g.name, total: g.segs.length, checked: g.checked,
      lengths: g.segs.map(x => segLengthLabel(x)),
    })),
    selectAll: () => { addToSelection(state.segGeom.map(g => g.id)); renderSelection(); render(); },
    marqueeWorld: (x1, y1, x2, y2) => {
      addToSelection(state.segGeom
        .filter(seg => segmentInRect(seg, x1, y1, x2, y2)).map(seg => seg.id));
      renderSelection(); render();
    },
    logEvents: (on) => {
      if (on) {
        console.log('[Visual Swap] event logging ON');
      } else {
        console.log('[Visual Swap] event logging OFF');
      }
    },
  };
})();
