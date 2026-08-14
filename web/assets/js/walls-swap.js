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

    selected: new Set(),

    view: { x: 0, y: 0, scale: 1 },
    fitScale: 1,

    tool: 'marquee',
    isDragging: false,
    dragStart: null,
    dragCurrent: null,
    isPanning: false,
    spaceHeld: false,

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
    state.selected.clear();
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
    state.selected.clear();
    const floor = state.floors.find(f => f.id === floorId);
    if (!floor) return;

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
    zoomFit();
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

  function renderSelection() {
    const el = $('swapSelBreakdown');
    const countEl = $('swapSelCount');
    countEl.textContent = state.selected.size;

    if (!state.selected.size) {
      el.innerHTML = '<div class="swap-empty">Drag a marquee to select walls, or click walls with the arrow tool.</div>';
      $('swapApplyBtn').disabled = true;
      $('swapDeleteBtn').disabled = true;
      return;
    }

    const counts = new Map();
    state.selected.forEach(id => {
      const g = state.segGeom.find(x => x.id === id);
      if (!g) return;
      counts.set(g.typeId, (counts.get(g.typeId) || 0) + 1);
    });
    const rows = [];
    counts.forEach((count, typeId) => {
      const wt = typeById(typeId);
      rows.push({ name: wt?.name || '(unknown)', color: wt ? safeColor(wt.color) : '#888', count });
    });
    rows.sort((a, b) => b.count - a.count);
    el.innerHTML = rows.map(r => `
      <div class="swap-sel-row">
        <span class="swap-legend-swatch" style="--swap-swatch:${r.color}"></span>
        <span class="swap-legend-name">${esc(r.name)}</span>
        <span class="swap-legend-count">${r.count}</span>
      </div>
    `).join('');

    $('swapApplyBtn').disabled = !$('swapTargetType').value;
    $('swapDeleteBtn').disabled = false;
  }

  function updateStatus() {
    const floor = state.floors.find(f => f.id === state.currentFloorId);
    const segCount = state.segGeom.length;
    const total = state.segments.length;
    const missing = segCount < (state.segmentsByFloor.get(state.currentFloorId) || []).length
      ? ' (' + ((state.segmentsByFloor.get(state.currentFloorId) || []).length - segCount) + ' skipped — unreadable geometry)'
      : '';
    $('swapStatus').textContent = `${segCount} walls on this floor · ${total} total in project${missing}`;
    const pct = state.fitScale > 0 ? Math.round((state.view.scale / state.fitScale) * 100) : 100;
    $('swapZoomLabel').textContent = pct + '%';
  }

  window.onSwapFloorChange = function () {
    const fid = $('swapFloorSelect').value;
    switchFloor(fid);
  };

  window.onSwapTargetChange = function () {
    $('swapApplyBtn').disabled = !$('swapTargetType').value || !state.selected.size;
  };

  window.setSwapTool = function (tool) {
    state.tool = tool;
    document.querySelectorAll('.swap-tool[data-tool]').forEach(b => {
      b.classList.toggle('active', b.dataset.tool === tool);
    });
    const c = canvas();
    c.style.cursor = tool === 'pan' ? 'grab' : (tool === 'click' ? 'pointer' : 'crosshair');
  };

  window.clearSwapSelection = function () {
    state.selected.clear();
    renderSelection();
    render();
  };

  window.selectAllOfType = function (typeId) {
    if (!typeId) return;
    state.segGeom.forEach(g => {
      if (g.typeId === typeId) state.selected.add(g.id);
    });
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
    render();
  }

  window.zoomFit = function () {
    const wrap = $('swapCanvasWrap');
    const w = wrap.clientWidth, h = wrap.clientHeight;
    if (!state.imgW || !state.imgH) return;
    const pad = 40;
    const sx = (w - pad) / state.imgW;
    const sy = (h - pad) / state.imgH;
    state.view.scale = Math.min(sx, sy);
    state.fitScale = state.view.scale;
    state.view.x = (w - state.imgW * state.view.scale) / 2;
    state.view.y = (h - state.imgH * state.view.scale) / 2;
    updateStatus();
    render();
  };

  window.zoomIn  = function () { zoomAt(1.25, null); };
  window.zoomOut = function () { zoomAt(0.8,  null); };

  function zoomAt(factor, anchor) {
    const c = canvas();
    const rect = c.getBoundingClientRect();
    const ax = anchor ? anchor.x : rect.width / 2;
    const ay = anchor ? anchor.y : rect.height / 2;
    const worldX = (ax - state.view.x) / state.view.scale;
    const worldY = (ay - state.view.y) / state.view.scale;
    const newScale = Math.max(0.02, Math.min(50, state.view.scale * factor));
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

    g.lineCap = 'round';
    for (const seg of state.segGeom) {
      if (state.selected.has(seg.id)) continue;
      const wt = typeById(seg.typeId);
      g.strokeStyle = wt ? safeColor(wt.color) : '#888';
      g.lineWidth = baseWidth;
      g.beginPath();
      g.moveTo(seg.x1, seg.y1);
      g.lineTo(seg.x2, seg.y2);
      g.stroke();
    }
    for (const seg of state.segGeom) {
      if (!state.selected.has(seg.id)) continue;
      const wt = typeById(seg.typeId);
      g.strokeStyle = '#ffffff';
      g.lineWidth = selWidth + 4 / state.view.scale;
      g.beginPath();
      g.moveTo(seg.x1, seg.y1);
      g.lineTo(seg.x2, seg.y2);
      g.stroke();
      g.strokeStyle = wt ? safeColor(wt.color) : '#888';
      g.lineWidth = selWidth;
      g.beginPath();
      g.moveTo(seg.x1, seg.y1);
      g.lineTo(seg.x2, seg.y2);
      g.stroke();
    }
    g.restore();

    if (state.isDragging && state.tool === 'marquee' && state.dragStart && state.dragCurrent) {
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

  const evHandlers = {};

  function installEventListeners() {
    const c = canvas();
    evHandlers.mousedown = onMouseDown;
    evHandlers.mousemove = onMouseMove;
    evHandlers.mouseup   = onMouseUp;
    evHandlers.wheel     = onWheel;
    evHandlers.keydown   = onKeyDown;
    evHandlers.keyup     = onKeyUp;
    evHandlers.resize    = resizeCanvas;
    evHandlers.railClick = (e) => {
      const btn = e.target.closest('.swap-tool');
      if (btn) btn.blur();
    };
    c.addEventListener('mousedown', evHandlers.mousedown);
    window.addEventListener('mousemove', evHandlers.mousemove);
    window.addEventListener('mouseup', evHandlers.mouseup);
    c.addEventListener('wheel', evHandlers.wheel, { passive: false });
    window.addEventListener('keydown', evHandlers.keydown);
    window.addEventListener('keyup', evHandlers.keyup);
    window.addEventListener('resize', evHandlers.resize);
    const rail = document.querySelector('.swap-toolrail');
    if (rail) rail.addEventListener('click', evHandlers.railClick);
    setSwapTool(state.tool);
  }

  function uninstallEventListeners() {
    const c = canvas();
    c.removeEventListener('mousedown', evHandlers.mousedown);
    window.removeEventListener('mousemove', evHandlers.mousemove);
    window.removeEventListener('mouseup', evHandlers.mouseup);
    c.removeEventListener('wheel', evHandlers.wheel);
    window.removeEventListener('keydown', evHandlers.keydown);
    window.removeEventListener('keyup', evHandlers.keyup);
    window.removeEventListener('resize', evHandlers.resize);
    const rail = document.querySelector('.swap-toolrail');
    if (rail && evHandlers.railClick) rail.removeEventListener('click', evHandlers.railClick);
  }

  function canvasPoint(e) {
    const rect = canvas().getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function onMouseDown(e) {
    const p = canvasPoint(e);
    const middleBtn = e.button === 1;
    if (middleBtn || state.spaceHeld || state.tool === 'pan') {
      state.isPanning = true;
      state.dragStart = { ...p, viewX: state.view.x, viewY: state.view.y };
      canvas().style.cursor = 'grabbing';
      e.preventDefault();
      return;
    }
    if (state.tool === 'click') {
      const w = screenToWorld(p.x, p.y);
      const tol = 6 / state.view.scale;
      const hit = pickSegmentAt(w.x, w.y, tol);
      if (hit) {
        if (state.selected.has(hit.id)) state.selected.delete(hit.id);
        else state.selected.add(hit.id);
        renderSelection();
        render();
      } else if (!e.shiftKey) {
        state.selected.clear();
        renderSelection();
        render();
      }
      return;
    }
    state.isDragging = true;
    state.dragStart = p;
    state.dragCurrent = p;
    if (!e.shiftKey) {
      state.selected.clear();
      renderSelection();
    }
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
    if (state.isDragging) {
      state.dragCurrent = p;
      render();
    }
  }

  function onMouseUp(e) {
    if (state.isPanning) {
      state.isPanning = false;
      state.dragStart = null;
      canvas().style.cursor = state.tool === 'pan' ? 'grab' : (state.tool === 'click' ? 'pointer' : 'crosshair');
      return;
    }
    if (state.isDragging) {
      state.isDragging = false;
      const s = state.dragStart, c = state.dragCurrent;
      const w1 = screenToWorld(s.x, s.y);
      const w2 = screenToWorld(c.x, c.y);
      const picked = state.segGeom.filter(seg => segmentInRect(seg, w1.x, w1.y, w2.x, w2.y));
      picked.forEach(seg => state.selected.add(seg.id));
      state.dragStart = null;
      state.dragCurrent = null;
      renderSelection();
      render();
    }
  }

  function onWheel(e) {
    e.preventDefault();
    const p = canvasPoint(e);
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    zoomAt(factor, p);
  }

  function onKeyDown(e) {
    if (e.key === 'Escape') {
      if (state.selected.size) {
        state.selected.clear();
        renderSelection();
        render();
      } else {
        closeSwapModal();
      }
      return;
    }
    if (e.key === ' ') {
      e.preventDefault();
      if (!state.spaceHeld) {
        state.spaceHeld = true;
        canvas().style.cursor = 'grab';
      }
    }
    if ((e.key === 'a' || e.key === 'A') && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      state.segGeom.forEach(g => state.selected.add(g.id));
      renderSelection();
      render();
    }
    if (e.key === 'm' || e.key === 'M') setSwapTool('marquee');
    if (e.key === 'v' || e.key === 'V') setSwapTool('click');
    if (e.key === 'h' || e.key === 'H') setSwapTool('pan');
  }

  function onKeyUp(e) {
    if (e.key === ' ') {
      e.preventDefault();
      state.spaceHeld = false;
      canvas().style.cursor = state.tool === 'pan' ? 'grab' : (state.tool === 'click' ? 'pointer' : 'crosshair');
    }
  }

  window.applySelectionSwap = function () {
    const targetId = $('swapTargetType').value;
    if (!targetId) { toast('Pick a target wall type'); return; }
    if (!state.selected.size) { toast('Nothing selected'); return; }

    const target = typeById(targetId);
    if (!target) { toast('Target wall type not found'); return; }

    let n = 0;
    const changed = [];
    for (const seg of state.segments) {
      if (state.selected.has(seg.id) && segmentTypeId(seg) !== targetId) {
        if ('wallTypeId' in seg) seg.wallTypeId = targetId;
        else if ('wallType' in seg) seg.wallType = targetId;
        else seg.wallTypeId = targetId;
        n++;
        changed.push(seg.id);
      }
    }
    state.segGeom.forEach(g => {
      if (state.selected.has(g.id)) g.typeId = targetId;
    });

    writeSegmentsBack();
    toast(`Swapped ${n} wall${n === 1 ? '' : 's'} → ${target.name}`, 'success');

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

    let n = 0;
    for (const seg of state.segments) {
      if (segmentTypeId(seg) !== fromId) continue;
      if (scope === 'floor' && segmentFloorId(seg) !== state.currentFloorId) continue;
      if ('wallTypeId' in seg) seg.wallTypeId = toId;
      else if ('wallType' in seg) seg.wallType = toId;
      else seg.wallTypeId = toId;
      n++;
    }

    state.segGeom.forEach(g => {
      if (g.typeId === fromId) g.typeId = toId;
    });

    writeSegmentsBack();
    const scopeLbl = scope === 'floor' ? 'on this floor' : 'across the project';
    toast(`Swapped ${n} wall${n === 1 ? '' : 's'} → ${target.name} ${scopeLbl}`, 'success');
    renderLegend();
    renderSelection();
    render();
  };

  window.deleteSelectedWalls = function () {
    if (!state.selected.size) { toast('Nothing selected'); return; }
    const n = state.selected.size;
    if (!confirm(`Delete ${n} wall${n === 1 ? '' : 's'} from the project? Nothing is written to disk until you press Save the *.esx.`)) return;

    const doomed = state.selected;
    state.segments = state.segments.filter(s => !doomed.has(s.id));

    state.segmentsByFloor.clear();
    state.segments.forEach(s => {
      const fid = segmentFloorId(s);
      if (!fid) return;
      if (!state.segmentsByFloor.has(fid)) state.segmentsByFloor.set(fid, []);
      state.segmentsByFloor.get(fid).push(s);
    });
    state.segGeom = state.segGeom.filter(g => !doomed.has(g.id));

    state.selected.clear();
    writeSegmentsBack();
    populateFloorSelect();
    $('swapFloorSelect').value = state.currentFloorId;
    renderLegend();
    renderSelection();
    updateStatus();
    render();
    toast(`Deleted ${n} wall${n === 1 ? '' : 's'}`, 'success');
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
    getTool: () => state.tool,
    getIsPanning: () => state.isPanning,
    logEvents: (on) => {
      if (on) {
        console.log('[Visual Swap] event logging ON');
      } else {
        console.log('[Visual Swap] event logging OFF');
      }
    },
  };
})();
