/* WD PlanTrim — crop empty canvas off Ekahau floor plans.
 *
 * Drop-in flow, the same shape as Quick Walls and Report: drop an .esx, see
 * what would change, save a new copy. The cropping itself is Python (Pillow),
 * so the bytes go to the local server and come back trimmed. The original file
 * on disk is never touched — you download a new one.
 */
(function () {
  'use strict';

  var state = { file: null, bytes: null, report: null, busy: false };

  function $(id) { return document.getElementById(id); }
  function esc(s) { return WD.esc(s); }
  function toast(m, k) { WD.toast(m, k); }

  function mb(bytes) {
    if (bytes === null || bytes === undefined) return '';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }

  // The .esx goes up as raw bytes; base64 would inflate a 30 MB survey by a
  // third for no benefit.
  function postEsx(action, bytes, params) {
    var qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return fetch('/api/plantrim/' + action + qs, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/octet-stream',
        'X-WD-Wireless-Tools': '1'
      },
      body: bytes
    });
  }

  // Drawn keep-regions ride in the query string; the body is already the .esx.
  function analyzeParams() {
    var params = { name: state.file.name };
    var boxes = window.__ptBoxes && window.__ptBoxes();
    if (boxes) params.boxes = JSON.stringify(boxes);
    return params;
  }

  // The box editor re-runs analyze after every change, so the list below the
  // canvas always describes what Save would actually produce.
  window.__ptAnalyze = function () {
    if (state.bytes && !state.busy) analyze();
  };

  // The set comparison needs the whole archive, so it goes to the server the
  // same way analyze does.
  window.__ptSuggest = function () {
    if (!state.bytes) return Promise.resolve({ ok: false, error: 'No file open' });
    return postEsx('suggest', state.bytes, { name: state.file.name })
      .then(function (r) { return r.json(); });
  };

  function busy(on, label) {
    state.busy = on;
    var save = $('ptSaveBtn');
    if (save) {
      save.disabled = on || !state.report || !state.report.trimmedCount;
      if (label) save.textContent = label;
    }
    document.body.classList.toggle('pt-busy', on);
  }

  // ---------------------------------------------------------------- dropzone
  var dropzone = $('dropzone');
  var fileInput = $('fileInput');

  dropzone.addEventListener('click', function () { fileInput.click(); });
  dropzone.addEventListener('dragover', function (e) {
    e.preventDefault();
    dropzone.classList.add('dragover');
  });
  dropzone.addEventListener('dragleave', function () { dropzone.classList.remove('dragover'); });
  dropzone.addEventListener('drop', function (e) {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files.length) loadFile(e.dataTransfer.files[0]);
  });
  fileInput.addEventListener('change', function (e) {
    if (e.target.files.length) loadFile(e.target.files[0]);
  });

  window.ptLoadNewFile = function () {
    fileInput.value = '';
    fileInput.click();
  };

  function loadFile(file) {
    if (!/\.esx$/i.test(file.name)) {
      toast('Not an .esx file', 'error');
      return Promise.resolve();
    }
    state.file = file;
    state.report = null;
    return file.arrayBuffer().then(function (buf) {
      state.bytes = buf;
      dropzone.style.display = 'none';
      $('dzTopbar').style.display = 'none';
      $('editor').classList.add('active');
      $('fileBadge').textContent = file.name;
      $('fileBadge').style.display = 'inline-block';
      // The badge truncates on a long project name, so the whole one lives here.
      $('fileBadge').title = file.name + '  —  click to open another .esx';
      return openForBoxes(buf).then(analyze);
    }).catch(function (e) { toast('Could not read that file: ' + e, 'error'); });
  }

  // The box editor needs the floor plan images, and the archive is already in
  // the browser - reading it here beats asking the server to send a
  // 75-megapixel plan back so it can be drawn on.
  function openForBoxes(buf) {
    if (!window.JSZip || !window.__ptBoxInit) return Promise.resolve();
    return JSZip.loadAsync(buf).then(function (zip) {
      var pj = zip.file('project.json');
      return (pj ? pj.async('string') : Promise.resolve(null)).then(function (txt) {
        var id = null;
        try { id = JSON.parse(txt).project.id; } catch (e) { id = null; }
        // No project id means no stable key to remember boxes against, so the
        // editor still works for this session and simply forgets afterwards.
        return window.__ptBoxInit(zip, id || ('name:' + state.file.name));
      });
    }).catch(function () { /* the analyze path reports a bad archive */ });
  }

  // ----------------------------------------------------------------- analyze
  function analyze() {
    busy(true, 'Reading…');
    $('ptFloors').innerHTML = '<div class="pt-empty">Reading floor plans…</div>';
    $('ptSizeNote').textContent = '';
    $('ptResult').hidden = true;

    return postEsx('analyze', state.bytes, analyzeParams())
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (!res || !res.ok) {
          $('ptFloors').innerHTML = '<div class="pt-empty pt-bad">' +
            esc((res && res.error) || 'Could not read that project') + '</div>';
          busy(false, 'Save trimmed .esx');
          return;
        }
        state.report = res;
        renderFloors(res);
        busy(false, 'Save trimmed .esx');
      })
      .catch(function (e) {
        $('ptFloors').innerHTML = '<div class="pt-empty pt-bad">' + esc(String(e)) + '</div>';
        busy(false, 'Save trimmed .esx');
      });
  }

  function renderFloors(res) {
    if (!res.floors.length) {
      $('ptFloors').innerHTML = '<div class="pt-empty">This project has no floor plans.</div>';
      return;
    }
    $('ptFloors').innerHTML = res.floors.map(function (f) {
      var right, badge;
      if (f.action === 'trimmed') {
        badge = 'Trim';
        right = '<span class="pt-dims">' + f.oldSize[0] + '&times;' + f.oldSize[1] +
                ' <span class="pt-arrow">&rarr;</span> ' + f.newSize[0] + '&times;' + f.newSize[1] +
                '</span><span class="pt-saved">&minus;' + f.areaSavedPct + '% area</span>';
      } else {
        badge = f.action === 'skipped' ? 'Leave as is' : 'Refused';
        right = '<span class="pt-reason">' + esc(f.reason || f.action) + '</span>';
      }
      return '<div class="pt-floor is-' + f.action + '">' +
               '<span class="pt-badge">' + badge + '</span>' +
               '<span class="pt-floor-name">' + esc(f.name) + '</span>' +
               right +
             '</div>';
    }).join('');

    var n = res.trimmedCount;
    var note = $('ptSizeNote');
    if (!n) {
      note.textContent = 'Nothing to trim here — every floor plan is already tight, or cannot be ' +
                         'cropped safely.';
    } else {
      // Empty canvas already compresses to almost nothing inside the .esx, so
      // say up front that the file size will barely move. Otherwise a correct
      // result reads like the tool did nothing.
      note.innerHTML = n + ' of ' + res.floorCount + ' floor plan' +
        (res.floorCount === 1 ? '' : 's') + ' will be cropped. ' +
        '<strong>The file size will barely change</strong> — empty canvas already compresses to ' +
        'almost nothing. What you gain is a plan that fills its page instead of sitting in one ' +
        'corner of it.';
    }
  }

  // -------------------------------------------------------------------- trim
  window.ptTrim = function () {
    if (state.busy || !state.bytes || !state.report || !state.report.trimmedCount) return;
    busy(true, 'Trimming…');
    $('ptResult').hidden = true;

    var meta = null;
    postEsx('trim', state.bytes, analyzeParams())
      .then(function (r) {
        if (!r.ok) {
          return r.json().then(function (j) { throw new Error(j.error || 'Trim failed'); });
        }
        try {
          meta = JSON.parse(decodeURIComponent(r.headers.get('X-PlanTrim-Report') || ''));
        } catch (e) { meta = null; }
        return r.blob();
      })
      .then(function (blob) {
        busy(false, 'Save trimmed .esx');
        var name = state.file.name.replace(/\.esx$/i, '') + ' (trimmed).esx';
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 4000);

        var count = meta ? meta.trimmedCount : state.report.trimmedCount;
        var box = $('ptResult');
        box.hidden = false;
        box.className = 'pt-result pt-good';
        box.innerHTML =
          '<strong>Saved — ' + count + ' floor plan' + (count === 1 ? '' : 's') + ' trimmed.</strong>' +
          '<div class="pt-result-path">' + esc(name) + '</div>' +
          (meta ? '<div class="pt-result-size">' + mb(meta.bytesBefore) + ' &rarr; ' +
                  mb(meta.bytesAfter) + '</div>' : '') +
          '<div class="pt-result-next">Open it in Ekahau to confirm it looks right before using it ' +
          'on real work. Your original file is untouched.</div>';
        toast('Trimmed ' + count + ' floor plan' + (count === 1 ? '' : 's'), 'success');
      })
      .catch(function (e) {
        busy(false, 'Save trimmed .esx');
        var box = $('ptResult');
        box.hidden = false;
        box.className = 'pt-result pt-bad';
        box.textContent = String(e.message || e);
        toast('Trim failed', 'error');
      });
  };

  // Diagnostics hook, same shape as Quick Walls' __wallsSwap.
  window.__plantrim = {
    loadFile: loadFile,
    getState: function () {
      return { name: state.file && state.file.name, busy: state.busy, report: state.report };
    }
  };
})();

/* WD PlanTrim — manual keep-region.
 *
 * Automatic detection reads a drawing frame and a title block as content,
 * because they are content: ink on the sheet. That is why a bare floor plate
 * trims and a titled CAD sheet does not, which reads as inconsistency when it
 * is really the detector being literal. Dragging a rectangle says what to keep
 * and the server takes it at its word.
 *
 * The image comes out of the .esx in the browser, with the copy of the archive
 * the page already holds — the bytes are here, and asking the server to send
 * a 75-megapixel plan back again to draw on it would be work for nothing.
 */
(function () {
  'use strict';

  var HANDLE = 8;           // hit radius, screen px
  var MIN_SIDE = 8;         // image px; matches MIN_MANUAL_SIDE server-side

  var box = {
    zip: null,
    floors: [],             // { id, name, imageId, w, h }
    boxes: {},              // floorPlanId -> [x0,y0,x1,y1] in image pixels
    current: null,
    img: null,
    view: { scale: 1, x: 0, y: 0 },
    drag: null,
    unsubPan: null
  };

  function $(id) { return document.getElementById(id); }

  // ------------------------------------------------------------ view maths
  function toImage(px, py) {
    return { x: (px - box.view.x) / box.view.scale, y: (py - box.view.y) / box.view.scale };
  }
  function toScreen(ix, iy) {
    return { x: ix * box.view.scale + box.view.x, y: iy * box.view.scale + box.view.y };
  }

  function fitView() {
    var cv = $('ptbCanvas');
    if (!box.img || !cv.width) return;
    var s = Math.min(cv.width / box.img.width, cv.height / box.img.height) * 0.92;
    box.view.scale = s;
    box.view.x = (cv.width - box.img.width * s) / 2;
    box.view.y = (cv.height - box.img.height * s) / 2;
  }

  function sizeCanvas() {
    var cv = $('ptbCanvas');
    var r = cv.getBoundingClientRect();
    var dpr = window.devicePixelRatio || 1;
    cv.width = Math.max(1, Math.round(r.width * dpr));
    cv.height = Math.max(1, Math.round(r.height * dpr));
  }

  // -------------------------------------------------------------- drawing
  function draw() {
    var cv = $('ptbCanvas');
    var g = cv.getContext('2d');
    g.clearRect(0, 0, cv.width, cv.height);
    if (!box.img) return;

    g.imageSmoothingEnabled = true;
    var tl = toScreen(0, 0);
    g.drawImage(box.img, tl.x, tl.y,
                box.img.width * box.view.scale, box.img.height * box.view.scale);

    var b = box.boxes[box.current];
    if (!b) return;

    var a = toScreen(b[0], b[1]);
    var c = toScreen(b[2], b[3]);
    var x = Math.min(a.x, c.x), y = Math.min(a.y, c.y);
    var w = Math.abs(c.x - a.x), h = Math.abs(c.y - a.y);

    // Dim what is being thrown away rather than outlining what is kept: the
    // question the user is answering is "what goes", and shading answers it
    // without them having to invert the picture in their head.
    g.save();
    g.fillStyle = 'rgba(0,0,0,0.55)';
    g.beginPath();
    g.rect(0, 0, cv.width, cv.height);
    g.rect(x, y, w, h);
    g.fill('evenodd');
    g.restore();

    g.strokeStyle = '#4a9eff';
    g.lineWidth = 2;
    g.strokeRect(x, y, w, h);

    g.fillStyle = '#4a9eff';
    handlePoints(x, y, w, h).forEach(function (p) {
      g.fillRect(p.x - 4, p.y - 4, 8, 8);
    });
  }

  function handlePoints(x, y, w, h) {
    return [
      { id: 'nw', x: x,         y: y         },
      { id: 'n',  x: x + w / 2, y: y         },
      { id: 'ne', x: x + w,     y: y         },
      { id: 'e',  x: x + w,     y: y + h / 2 },
      { id: 'se', x: x + w,     y: y + h     },
      { id: 's',  x: x + w / 2, y: y + h     },
      { id: 'sw', x: x,         y: y + h     },
      { id: 'w',  x: x,         y: y + h / 2 }
    ];
  }

  function handleAt(px, py) {
    var b = box.boxes[box.current];
    if (!b) return null;
    var a = toScreen(b[0], b[1]);
    var c = toScreen(b[2], b[3]);
    var x = Math.min(a.x, c.x), y = Math.min(a.y, c.y);
    var w = Math.abs(c.x - a.x), h = Math.abs(c.y - a.y);
    var found = null;
    handlePoints(x, y, w, h).forEach(function (p) {
      if (Math.abs(px - p.x) <= HANDLE && Math.abs(py - p.y) <= HANDLE) found = p.id;
    });
    if (found) return found;
    if (px > x && px < x + w && py > y && py < y + h) return 'move';
    return null;
  }

  // -------------------------------------------------------------- readout
  function updateReadout() {
    var b = box.boxes[box.current];
    var out = $('ptbReadout');
    var hint = $('ptbHint');
    var clear = $('ptbClear');
    var all = $('ptbApplyAll');
    hint.className = 'ptb-hint';

    if (!b) {
      out.textContent = 'Automatic';
      out.className = 'ptb-readout';
      clear.disabled = true;
      all.disabled = true;
      hint.textContent = box.img
        ? 'Drag a rectangle over the part of the sheet to keep.'
        : '';
      return;
    }
    var w = Math.round(Math.abs(b[2] - b[0]));
    var h = Math.round(Math.abs(b[3] - b[1]));
    var f = floorById(box.current);
    var pct = (f && f.w) ? Math.round((1 - (w * h) / (f.w * f.h)) * 100) : 0;
    out.textContent = w + ' \u00d7 ' + h + ' px';
    out.className = 'ptb-readout is-manual';
    clear.disabled = false;
    all.disabled = box.floors.length < 2;

    if (w < MIN_SIDE || h < MIN_SIDE) {
      hint.className = 'ptb-hint is-bad';
      hint.textContent = 'That rectangle is too small to crop to.';
    } else {
      hint.textContent = 'Keeps ' + w + ' \u00d7 ' + h + ' of ' + f.w + ' \u00d7 ' + f.h +
                         ' \u2014 drops ' + pct + '% of the sheet. Drag a handle to adjust.';
    }
  }

  function floorById(id) {
    for (var i = 0; i < box.floors.length; i++) {
      if (box.floors[i].id === id) return box.floors[i];
    }
    return null;
  }

  // ---------------------------------------------------------- interaction
  function clampBox(b, f) {
    return [
      Math.max(0, Math.min(b[0], f.w)), Math.max(0, Math.min(b[1], f.h)),
      Math.max(0, Math.min(b[2], f.w)), Math.max(0, Math.min(b[3], f.h))
    ];
  }

  function normalise(b) {
    return [Math.min(b[0], b[2]), Math.min(b[1], b[3]),
            Math.max(b[0], b[2]), Math.max(b[1], b[3])];
  }

  function onDown(e) {
    if (!box.img) return;
    var cv = $('ptbCanvas');
    var dpr = window.devicePixelRatio || 1;
    var r = cv.getBoundingClientRect();
    var px = (e.clientX - r.left) * dpr;
    var py = (e.clientY - r.top) * dpr;

    // Space, middle button and right button all mean "pan" everywhere else in
    // the suite, so they mean it here too rather than starting a rectangle.
    if (WD.PanZoom && WD.PanZoom.isPanGesture(e)) {
      box.drag = { mode: 'pan', px: px, py: py, ox: box.view.x, oy: box.view.y };
      $('ptbStage').classList.add('is-panning');
      e.preventDefault();
      return;
    }
    if (e.button !== 0) return;

    var grip = handleAt(px, py);
    var img = toImage(px, py);
    if (grip) {
      box.drag = { mode: grip, start: box.boxes[box.current].slice(),
                   ix: img.x, iy: img.y };
    } else {
      box.drag = { mode: 'new', ix: img.x, iy: img.y };
      box.boxes[box.current] = [img.x, img.y, img.x, img.y];
    }
    e.preventDefault();
  }

  function onMove(e) {
    var cv = $('ptbCanvas');
    var dpr = window.devicePixelRatio || 1;
    var r = cv.getBoundingClientRect();
    var px = (e.clientX - r.left) * dpr;
    var py = (e.clientY - r.top) * dpr;

    if (!box.drag) {
      $('ptbStage').classList.toggle('can-pan',
        !!(WD.PanZoom && WD.PanZoom.isHeld()));
      return;
    }
    var d = box.drag;
    if (d.mode === 'pan') {
      box.view.x = d.ox + (px - d.px);
      box.view.y = d.oy + (py - d.py);
      draw();
      return;
    }

    var f = floorById(box.current);
    var img = toImage(px, py);
    var b;
    if (d.mode === 'new') {
      b = [d.ix, d.iy, img.x, img.y];
    } else if (d.mode === 'move') {
      var dx = img.x - d.ix, dy = img.y - d.iy;
      b = [d.start[0] + dx, d.start[1] + dy, d.start[2] + dx, d.start[3] + dy];
      // Move keeps its size at the edge instead of squashing against it.
      var w = d.start[2] - d.start[0], h = d.start[3] - d.start[1];
      if (b[0] < 0) { b[0] = 0; b[2] = w; }
      if (b[1] < 0) { b[1] = 0; b[3] = h; }
      if (b[2] > f.w) { b[2] = f.w; b[0] = f.w - w; }
      if (b[3] > f.h) { b[3] = f.h; b[1] = f.h - h; }
    } else {
      b = d.start.slice();
      if (d.mode.indexOf('n') >= 0) b[1] = img.y;
      if (d.mode.indexOf('s') >= 0) b[3] = img.y;
      if (d.mode.indexOf('w') >= 0) b[0] = img.x;
      if (d.mode.indexOf('e') >= 0) b[2] = img.x;
    }
    box.boxes[box.current] = clampBox(normalise(b), f);
    draw();
    updateReadout();
  }

  function onUp() {
    if (!box.drag) return;
    var wasPan = box.drag.mode === 'pan';
    box.drag = null;
    $('ptbStage').classList.remove('is-panning');
    if (wasPan) return;

    var f = floorById(box.current);
    var b = box.boxes[box.current];
    if (b) {
      b = clampBox(normalise(b), f);
      // A click rather than a drag is not a rectangle; treat it as a miss and
      // fall back to automatic instead of leaving a sliver behind.
      if (Math.abs(b[2] - b[0]) < MIN_SIDE || Math.abs(b[3] - b[1]) < MIN_SIDE) {
        delete box.boxes[box.current];
      } else {
        box.boxes[box.current] = b;
      }
    }
    if (box.suggestions) delete box.suggestions[box.current];
    showEvidence();
    draw();
    updateReadout();
    persist();
    reanalyze();
  }

  function onWheel(e) {
    if (!box.img) return;
    e.preventDefault();
    var cv = $('ptbCanvas');
    var dpr = window.devicePixelRatio || 1;
    var r = cv.getBoundingClientRect();
    var px = (e.clientX - r.left) * dpr;
    var py = (e.clientY - r.top) * dpr;
    var before = toImage(px, py);
    var k = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    box.view.scale = Math.max(0.02, Math.min(20, box.view.scale * k));
    var after = toScreen(before.x, before.y);
    box.view.x += px - after.x;
    box.view.y += py - after.y;
    draw();
  }

  // -------------------------------------------------------- persistence
  // Boxes are keyed by the project's own id and the floor's, so re-opening the
  // same .esx brings back what was drawn. They live in the suite settings file
  // rather than the archive: writing our own member into someone's .esx is a
  // liberty, and Ekahau would not thank us for it.
  var PERSIST_KEY = 'plantrim.boxes';

  function persist() {
    if (!box.projectId) return;
    var payload = {};
    payload[box.projectId] = box.boxes;
    WD.api('plantrim/boxes_save', { projectId: box.projectId, boxes: box.boxes })
      .catch(function () { /* a lost box is a redraw, not a failure worth a toast */ });
  }

  function restore(projectId) {
    return WD.api('plantrim/boxes_load', { projectId: projectId })
      .then(function (r) { return (r && r.ok && r.boxes) || {}; })
      .catch(function () { return {}; });
  }

  // ------------------------------------------------------------- wiring
  window.ptbSelectFloor = function (id) {
    box.current = id;
    var f = floorById(id);
    $('ptbEmpty').hidden = true;
    if (!f) return;
    loadImage(f).then(function () {
      sizeCanvas();
      fitView();
      draw();
      updateReadout();
      showEvidence();
    });
  };

  window.ptbClearBox = function () {
    delete box.boxes[box.current];
    draw();
    updateReadout();
    persist();
    reanalyze();
  };

  window.ptbApplyToAll = function () {
    var b = box.boxes[box.current];
    if (!b) return;
    var applied = 0, skipped = [];
    box.floors.forEach(function (f) {
      if (f.id === box.current) return;
      // The same CAD set puts the title block in the same place on every sheet,
      // so the box carries over as-is - but only where the sheet is the same
      // size. On a different size the pixels mean something else, and silently
      // reusing the numbers would put the rectangle over the wrong part of it.
      var here = floorById(box.current);
      if (f.w !== here.w || f.h !== here.h) { skipped.push(f.name); return; }
      box.boxes[f.id] = b.slice();
      applied++;
    });
    persist();
    reanalyze();
    updateReadout();
    if (!applied) {
      WD.toast('No other floor is the same size as this one', 'error');
    } else if (skipped.length) {
      WD.toast('Applied to ' + applied + ' floor' + (applied === 1 ? '' : 's') +
               '; skipped ' + skipped.length + ' of a different size', 'success');
    } else {
      WD.toast('Applied to ' + applied + ' floor' + (applied === 1 ? '' : 's'), 'success');
    }
  };

  // ------------------------------------------------------------- suggest
  // Suggestions are filled into the editor, never applied. The rectangle lands
  // where it can be seen and dragged, the evidence for it is stated, and
  // nothing is written until Save. Detection that cannot be checked is what the
  // manual box exists to escape, so it does not get to act on its own.
  window.ptbSuggest = function () {
    var btn = $('ptbSuggest');
    btn.disabled = true;
    btn.textContent = 'Comparing sheets…';
    window.__ptSuggest().then(function (res) {
      btn.disabled = false;
      btn.textContent = 'Suggest from the set';
      if (!res || !res.ok) {
        WD.toast((res && res.error) || 'Could not compare the sheets', 'error');
        return;
      }
      box.suggestions = {};
      var filled = 0;
      (res.suggestions || []).forEach(function (s) {
        box.suggestions[s.floorId] = s;
        if (s.box) { box.boxes[s.floorId] = s.box.slice(); filled++; }
      });
      draw();
      updateReadout();
      showEvidence();
      reanalyze();
      if (!filled) {
        WD.toast('Nothing to suggest from this set', 'error');
      } else {
        WD.toast('Proposed a rectangle for ' + filled + ' floor' +
                 (filled === 1 ? '' : 's') + ' — check it before saving',
                 'success');
      }
    }).catch(function (e) {
      btn.disabled = false;
      btn.textContent = 'Suggest from the set';
      WD.toast('Could not compare the sheets', 'error');
    });
  };

  function showEvidence() {
    var el = $('ptbEvidence');
    var s = box.suggestions && box.suggestions[box.current];
    if (!s) { el.hidden = true; return; }
    var label = s.basis === 'cross-sheet'
      ? 'Proposed from ' + s.sheets + ' sheets of this size'
      : (s.basis === 'single-sheet' ? 'Proposed from this sheet alone'
                                    : 'Nothing could be proposed');
    el.innerHTML = '<span class="ptb-ev-basis"><strong>' + WD.esc(label) +
                   '</strong></span>' + WD.esc(s.evidence) +
                   ' <em>Check it and drag if it is wrong — nothing is written until you save.</em>';
    el.hidden = false;
  }

  function loadImage(f) {
    if (box.img && box.imgFor === f.imageId) return Promise.resolve();
    var entry = box.zip && box.zip.file('image-' + f.imageId);
    if (!entry) {
      box.img = null;
      $('ptbEmpty').hidden = false;
      $('ptbEmpty').textContent = 'This floor has no image in the archive.';
      return Promise.resolve();
    }
    return entry.async('blob').then(function (blob) {
      return new Promise(function (resolve) {
        var url = URL.createObjectURL(blob);
        var im = new Image();
        im.onload = function () {
          box.img = im;
          box.imgFor = f.imageId;
          URL.revokeObjectURL(url);
          resolve();
        };
        im.onerror = function () {
          box.img = null;
          $('ptbEmpty').hidden = false;
          $('ptbEmpty').textContent = 'This floor plan cannot be drawn on (it may be an SVG).';
          URL.revokeObjectURL(url);
          resolve();
        };
        im.src = url;
      });
    });
  }

  // Re-run analyze with the current boxes so the list below the canvas always
  // describes what Save would actually produce.
  var pending = null;
  function reanalyze() {
    clearTimeout(pending);
    pending = setTimeout(function () {
      if (window.__ptAnalyze) window.__ptAnalyze();
    }, 150);
  }

  window.__ptBoxes = function () {
    return Object.keys(box.boxes).length ? box.boxes : null;
  };

  // Called by loadFile once the archive is open.
  window.__ptBoxInit = function (zip, projectId) {
    box.zip = zip;
    box.projectId = projectId;
    box.boxes = {};
    box.img = null;
    box.imgFor = null;

    return Promise.all([
      zip.file('floorPlans.json') ? zip.file('floorPlans.json').async('string') : null,
      restore(projectId)
    ]).then(function (res) {
      var doc = res[0] ? JSON.parse(res[0]) : { floorPlans: [] };
      box.boxes = res[1] || {};
      box.floors = (doc.floorPlans || []).map(function (f) {
        return { id: f.id, name: f.name || '(unnamed)', imageId: f.imageId,
                 w: Math.round(f.width || 0), h: Math.round(f.height || 0) };
      });
      var sel = $('ptbFloor');
      sel.innerHTML = box.floors.map(function (f) {
        return '<option value="' + f.id + '">' + WD.esc(f.name) +
               ' \u2014 ' + f.w + '\u00d7' + f.h + '</option>';
      }).join('');
      $('ptBoxCard').hidden = box.floors.length === 0;
      if (box.floors.length) {
        sel.value = box.floors[0].id;
        window.ptbSelectFloor(box.floors[0].id);
      }
      var restored = Object.keys(box.boxes).length;
      if (restored) {
        WD.toast('Restored ' + restored + ' saved keep-region' +
                 (restored === 1 ? '' : 's'), 'success');
      }
    });
  };

  // ------------------------------------------------------------- listeners
  document.addEventListener('DOMContentLoaded', function () {
    var cv = $('ptbCanvas');
    if (!cv) return;
    cv.addEventListener('mousedown', onDown);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    cv.addEventListener('wheel', onWheel, { passive: false });
    cv.addEventListener('contextmenu', function (e) { e.preventDefault(); });
    window.addEventListener('resize', function () {
      if (!box.img) return;
      sizeCanvas(); fitView(); draw();
    });
    if (WD.PanZoom) {
      box.unsubPan = WD.PanZoom.onChange(function (held) {
        $('ptbStage').classList.toggle('can-pan', held && !box.drag);
      });
    }
  });

  window.__plantrimBox = box;
})();
