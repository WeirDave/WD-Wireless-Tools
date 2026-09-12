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
    var cut = $('ptbCut');
    if (cut) {
      cut.disabled = on || !state.report || !state.report.trimmedCount;
      if (on && label) cut.textContent = label;
    }
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
        busy(false, 'Save trimmed .esx');
        syncCutButton(res);
        if (window.__ptRenderStrip) window.__ptRenderStrip(res);
        if (window.__ptRefit) window.__ptRefit();
      })
      .catch(function (e) {
        $('ptFloors').innerHTML = '<div class="pt-empty pt-bad">' + esc(String(e)) + '</div>';
        busy(false, 'Save trimmed .esx');
      });
  }

  // The verb, next to the thing it acts on. Everything else on the page is a
  // modifier; this is the only control that does anything to the file, so it
  // says what it does rather than naming a file operation.
  function syncCutButton(res) {
    var btn = $('ptbCut');
    var note = $('ptbCutNote');
    if (!btn) return;
    var n = res && res.trimmedCount;
    btn.disabled = !n || state.busy;
    if (!res) {
      btn.textContent = 'Cut and save';
      if (note) note.textContent = '';
      return;
    }
    btn.textContent = n ? 'Cut and save' : 'Nothing to cut';
    if (!note) return;
    if (!n) {
      note.textContent = 'Every floor plan is already tight, or cannot be cropped.';
    } else {
      var drawn = 0;
      (res.floors || []).forEach(function (f) { if (f.source === 'manual') drawn++; });
      note.textContent = n + ' floor plan' + (n === 1 ? '' : 's') + ' will be cropped' +
        (drawn ? ' (' + drawn + ' to a box you drew)' : ' automatically') +
        '. Your original file is not changed \u2014 you get a new copy.';
    }
  }

  window.ptCut = function () { window.ptTrim(); };

  // The report is the strip's data source now; it used to be rendered twice,
  // once here and once beside the canvas, which is the duplication that let the
  // two drift apart.
  window.__ptReport = function () { return state.report; };

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
          // Stated, not asked about: scissors do not keep what they cut away.
          (meta && meta.droppedCount
            ? '<div class="pt-result-cut">' + meta.droppedCount + ' object' +
              (meta.droppedCount === 1 ? '' : 's') + ' outside the box ' +
              (meta.droppedCount === 1 ? 'was' : 'were') + ' cut away with it.</div>'
            : '') +
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

  // Sizes are CSS pixels, scaled to the canvas's device pixels where used.
  // They used to be device pixels, which on a 1.5x or 2x Windows display made
  // both the drawn handle and its hit target about four CSS pixels across: too
  // small to aim at, and a near miss did not merely fail to grab the handle,
  // it started a new box over the one being adjusted. "Drag a handle to
  // adjust" destroyed the work rather than doing nothing.
  var HANDLE_HIT_CSS = 16;   // how close a press counts as grabbing a handle
  var HANDLE_DRAW_CSS = 11;  // how big the handle looks
  var MIN_SIDE = 8;          // image px; matches MIN_MANUAL_SIDE server-side

  function dpr() { return window.devicePixelRatio || 1; }
  function hitRadius() { return HANDLE_HIT_CSS * dpr(); }
  function handleSize() { return HANDLE_DRAW_CSS * dpr(); }

  var box = {
    zip: null,
    floors: [],             // { id, name, imageId, w, h }
    boxes: {},              // floorPlanId -> [x0,y0,x1,y1] in image pixels
    // A drawn rectangle is a draft until Crop is pressed, the way a marquee is
    // in any image editor. Only applied boxes reach the server, so a box he
    // drew and did not crop changes nothing - which is what makes the Crop
    // button mean something rather than decorate the page.
    applied: {},            // floorPlanId -> true once cropped
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

  // What the stage should frame: the kept region once cropped, the whole sheet
  // while still drawing. The cropped preview costs nothing because it is a
  // viewport change rather than a new image - which is also why it cannot
  // accidentally become a commit.
  function framedRegion() {
    var b = box.boxes[box.current];
    // A cropped floor is framed exactly: that view is the result.
    if (b && box.applied && box.applied[box.current]) {
      return { x: b[0], y: b[1], w: b[2] - b[0], h: b[3] - b[1] };
    }
    // A rectangle still being drawn is framed with room around it, because the
    // handles live on its edges. Framing something narrower than the rectangle
    // - which is what detection's own bounds are, once Suggest or a drag has
    // widened the box past them - pushes those edges onto the edge of the stage
    // and there is nothing left to grab. That is exactly what happened: a
    // 6234-wide suggestion inside a view sized for a 3275-wide detection put
    // the whole right-hand side of the box against the frame.
    if (b) {
      var bw = b[2] - b[0], bh = b[3] - b[1];
      if (bw > 1 && bh > 1) {
        var m = 0.12;
        return { x: b[0] - bw * m, y: b[1] - bh * m,
                 w: bw * (1 + 2 * m), h: bh * (1 + 2 * m) };
      }
    }

    // Before anything is cropped, frame the drawing rather than the sheet. A
    // 10000x7500 CAD canvas with the building using a fifth of it renders the
    // building as a postage stamp in a white field, which is a poor thing to
    // ask someone to draw a precise rectangle around. The server already found
    // the content - its automatic crop is exactly those bounds - so the view
    // reuses it, padded so there is room to drag wider than the detection.
    var rep = window.__ptReport && window.__ptReport();
    var f = null;
    ((rep && rep.floors) || []).forEach(function (x) {
      if (x.id === box.current && x.action === 'trimmed' && x.offset && x.newSize) f = x;
    });
    if (f) {
      var pad = 0.18;
      var px = f.newSize[0] * pad, py = f.newSize[1] * pad;
      var x0 = Math.max(0, f.offset[0] - px);
      var y0 = Math.max(0, f.offset[1] - py);
      var x1 = Math.min(box.img.width, f.offset[0] + f.newSize[0] + px);
      var y1 = Math.min(box.img.height, f.offset[1] + f.newSize[1] + py);
      if (x1 - x0 > 1 && y1 - y0 > 1) {
        return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
      }
    }
    return { x: 0, y: 0, w: box.img.width, h: box.img.height };
  }

  function fitView() {
    var cv = $('ptbCanvas');
    if (!box.img || !cv.width) return;
    var r = framedRegion();
    var s = Math.min(cv.width / r.w, cv.height / r.h) * 0.97;
    box.view.scale = s;
    box.view.x = (cv.width - r.w * s) / 2 - r.x * s;
    box.view.y = (cv.height - r.h * s) / 2 - r.y * s;
    // Detection usually lands after the image does, so the first fit has to be
    // allowed to improve itself. Once he has panned or zoomed, it must not:
    // moving the plan under someone mid-drag is worse than a loose fit.
    box.autoFramed = true;
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

    // Cropped: the kept region is the picture. No shading and no handles,
    // because there is nothing being chosen any more - this is the result.
    if (box.applied && box.applied[box.current]) {
      var tl2 = toScreen(b[0], b[1]);
      var br2 = toScreen(b[2], b[3]);
      g.save();
      g.fillStyle = 'rgba(0,0,0,0.75)';
      g.beginPath();
      g.rect(0, 0, cv.width, cv.height);
      g.rect(tl2.x, tl2.y, br2.x - tl2.x, br2.y - tl2.y);
      g.fill('evenodd');
      g.restore();
      g.strokeStyle = 'rgba(74,158,255,0.55)';
      g.lineWidth = 1;
      g.strokeRect(tl2.x, tl2.y, br2.x - tl2.x, br2.y - tl2.y);
      return;
    }

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

    // Big enough to grab, with a white surround so a handle stays visible
    // over dark linework as well as over paper.
    var hs = handleSize();
    handlePoints(x, y, w, h).forEach(function (p) {
      g.fillStyle = '#ffffff';
      g.fillRect(p.x - hs / 2 - 1, p.y - hs / 2 - 1, hs + 2, hs + 2);
      g.fillStyle = '#4a9eff';
      g.fillRect(p.x - hs / 2, p.y - hs / 2, hs, hs);
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
    // Nearest handle within reach, rather than the last one that matches:
    // corner and edge handles sit close together on a small box, and picking
    // by iteration order grabs the wrong one.
    var r = hitRadius();
    var found = null, best = Infinity;
    handlePoints(x, y, w, h).forEach(function (p) {
      var d = Math.max(Math.abs(px - p.x), Math.abs(py - p.y));
      if (d <= r && d < best) { best = d; found = p.id; }
    });
    if (found) return found;

    // Anywhere along an edge drags that edge. Corners still win because they
    // are tested first, and the square on each side is still drawn - it says
    // the edge can be dragged - but it is no longer the only place that works.
    var onY = py >= y - r && py <= y + h + r;
    var onX = px >= x - r && px <= x + w + r;
    if (onY && Math.abs(px - x) <= r) return 'w';
    if (onY && Math.abs(px - (x + w)) <= r) return 'e';
    if (onX && Math.abs(py - y) <= r) return 'n';
    if (onX && Math.abs(py - (y + h)) <= r) return 's';

    if (px > x && px < x + w && py > y && py < y + h) return 'move';
    return null;
  }

  // -------------------------------------------------------------- readout
  // One control is obviously next at any moment: Crop when a rectangle is
  // waiting, nothing in the card once the floor is settled.
  function syncFloorButtons() {
    var drafted = hasDraft(box.current);
    var cropped = !!(box.applied && box.applied[box.current]);
    var crop = $('ptbCrop'), edit = $('ptbEdit'), clear = $('ptbClear');
    if (crop) { crop.hidden = !drafted; crop.disabled = !drafted; }
    if (edit) { edit.hidden = !cropped; }
    if (clear) { clear.disabled = !box.boxes[box.current]; }
    // Exactly one loud control at a time. While a rectangle is waiting, Crop is
    // plainly what comes next, so finishing the file steps back until it is.
    var cut = $('ptbCut');
    if (cut && cut.classList) {
      cut.classList.toggle('btn-primary', !drafted);
      cut.classList.toggle('btn-sec', drafted);
    }
  }

  function updateReadout() {
    syncFloorButtons();
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
    // While a floor shows its cropped result, dragging would silently start a
    // new rectangle over it. Edit box puts it back into drawing mode.
    if (box.applied && box.applied[box.current] &&
        !(WD.PanZoom && WD.PanZoom.isPanGesture(e))) return;
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
      box.autoFramed = false;
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
    // Always swallow the wheel over the stage, even with nothing to zoom.
    // Returning first meant that a floor whose image had not loaded - every
    // vector plan, before those started rendering - scrolled the page instead,
    // which reads as the canvas ignoring the wheel entirely.
    e.preventDefault();
    if (!box.img) return;
    var cv = $('ptbCanvas');
    var dpr = window.devicePixelRatio || 1;
    var r = cv.getBoundingClientRect();
    var px = (e.clientX - r.left) * dpr;
    var py = (e.clientY - r.top) * dpr;
    var before = toImage(px, py);
    var k = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    box.view.scale = Math.max(0.02, Math.min(20, box.view.scale * k));
    box.autoFramed = false;
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
    // Only cropped floors are remembered. A rectangle he drew and did not crop
    // is not a decision yet, so it lives for the session and no longer - which
    // also keeps the stored shape exactly four numbers.
    var stored = {};
    Object.keys(box.boxes).forEach(function (id) {
      if (box.applied && box.applied[id]) stored[id] = box.boxes[id];
    });
    WD.api('plantrim/boxes_save', { projectId: box.projectId, boxes: stored })
      .catch(function () { /* a lost box is a redraw, not a failure worth a toast */ });
  }

  function restore(projectId) {
    return WD.api('plantrim/boxes_load', { projectId: projectId })
      .then(function (r) { return (r && r.ok && r.boxes) || {}; })
      .catch(function () { return {}; });
  }

  // ------------------------------------------------------------- wiring
  // Where he is, and what every floor is going to do. The same facts used to
  // live in a separate card below the canvas, which is how the flow came apart:
  // the state was on the page but not beside the thing it described, so there
  // was nothing to tell him what had registered or how much was left.
  function floorState(rep, id) {
    var f = null;
    ((rep && rep.floors) || []).forEach(function (x) { if (x.id === id) f = x; });
    if (!f) return { word: 'Reading\u2026', cls: 'is-pending', detail: '' };
    if (f.action === 'trimmed') {
      var dims = f.oldSize[0] + '\u00d7' + f.oldSize[1] + ' \u2192 ' +
                 f.newSize[0] + '\u00d7' + f.newSize[1];
      var saved = (f.areaSavedPct ? '  \u2212' + f.areaSavedPct + '%' : '');
      return f.source === 'manual'
        ? { word: 'Your box', cls: 'is-manual', detail: dims + saved }
        : { word: 'Automatic', cls: 'is-auto', detail: dims + saved };
    }
    if (f.action === 'skipped') {
      return { word: 'Nothing to do', cls: 'is-skip', detail: f.reason || '' };
    }
    return { word: 'Cannot crop', cls: 'is-refused', detail: f.reason || '' };
  }

  function renderStrip(rep) {
    var el = $('ptbStrip');
    if (!el) return;
    if (!box.floors.length) { el.innerHTML = ''; return; }
    el.innerHTML = box.floors.map(function (f, i) {
      var st = floorState(rep, f.id);
      var here = f.id === box.current;
      return '<button type="button" class="ptb-row ' + st.cls +
               (here ? ' is-current' : '') + '" data-floor="' + WD.esc(f.id) + '">' +
               '<span class="ptb-row-n">' + (i + 1) + '</span>' +
               '<span class="ptb-row-name">' + WD.esc(f.name) + '</span>' +
               '<span class="ptb-row-state">' + WD.esc(st.word) + '</span>' +
               '<span class="ptb-row-detail">' + WD.esc(st.detail) + '</span>' +
             '</button>';
    }).join('');
    var next = $('ptbNext');
    if (next) {
      next.hidden = box.floors.length < 2;
      var i = floorIndex(box.current);
      next.disabled = i < 0 || i >= box.floors.length - 1;
      next.textContent = next.disabled ? 'Last floor' : 'Next floor \u2192';
    }
    var count = $('ptbFloorCount');
    if (count) {
      var i2 = floorIndex(box.current);
      count.textContent = box.floors.length === 1
        ? '1 floor plan'
        : 'Floor ' + (i2 + 1) + ' of ' + box.floors.length;
    }
  }

  function floorIndex(id) {
    for (var i = 0; i < box.floors.length; i++) {
      if (box.floors[i].id === id) return i;
    }
    return -1;
  }

  // Clicking a floor jumps to it. Nothing is locked and there is no sequence to
  // follow - the strip says what each floor will do, it does not gate them.
  document.addEventListener('click', function (e) {
    var row = e.target && e.target.closest && e.target.closest('[data-floor]');
    if (row) window.ptbSelectFloor(row.getAttribute('data-floor'));
  });

  // "you just choose to go to the next floor kind of thing" - his words, so the
  // control gets the name he already uses for it.
  window.ptbNextFloor = function () {
    var i = floorIndex(box.current);
    if (i >= 0 && i < box.floors.length - 1) {
      window.ptbSelectFloor(box.floors[i + 1].id);
    }
  };

  // Called by the analyze path so the strip always describes the current plan.
  window.__ptRenderStrip = function (rep) { renderStrip(rep); };

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
      renderStrip(window.__ptReport && window.__ptReport());
    });
  };

  // Every pan and zoom needs a way back. Without one, one stray wheel over
  // the stage leaves the plan somewhere off screen with no way to find it.
  window.ptbFitView = function () {
    if (!box.img) return;
    sizeCanvas();
    fitView();
    draw();
  };

  // Draw, crop, see the result - the model every other cropping tool uses, so
  // the next move needs no explanation and the cropped image is the
  // confirmation. Nothing is written: this is a view of what the output will
  // be, and the file on disk is untouched until the whole project is saved.
  window.ptbCropBox = function () {
    var b = box.boxes[box.current];
    if (!b) return;
    box.applied[box.current] = true;
    fitView();
    draw();
    updateReadout();
    persist();
    reanalyze();
    WD.toast('Cropped \u2014 nothing is written until you save', 'success');
  };

  // A crop he cannot back out of turns a misdrag into starting the floor over,
  // so the rectangle survives: this puts the handles back on the box he had.
  window.ptbEditBox = function () {
    if (!box.boxes[box.current]) return;
    box.applied[box.current] = false;
    fitView();
    draw();
    updateReadout();
    persist();
    reanalyze();
  };

  window.ptbClearBox = function () {
    delete box.boxes[box.current];
    delete box.applied[box.current];
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
    if (window.__ptRefit) window.__ptRefit();
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
      if (window.__ptRefit) window.__ptRefit();
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

  // A floor plan member carries no extension and no content type, so a blob
  // made from it has neither. A browser will sniff a raster out of that, but an
  // SVG is text and will not render without being told it is an image - which
  // is why vector plans showed an empty canvas and no error. The format comes
  // from images.json, cross-checked against the bytes in the same spirit as the
  // extractor: what the file *is* wins over what it is labelled.
  var MIME = { SVG: 'image/svg+xml', PNG: 'image/png', JPEG: 'image/jpeg',
               JPG: 'image/jpeg', GIF: 'image/gif', BMP: 'image/bmp',
               TIFF: 'image/tiff', WEBP: 'image/webp' };

  function sniffMime(bytes) {
    // Guards are the number of bytes each check actually reads, not the length
    // of the signature: a four-byte read behind a "length > 8" guard silently
    // declines to identify a file it could have.
    if (bytes.length >= 4 && bytes[0] === 0x89 && bytes[1] === 0x50 &&
        bytes[2] === 0x4e && bytes[3] === 0x47) return 'image/png';
    if (bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xd8) return 'image/jpeg';
    if (bytes.length >= 3 && bytes[0] === 0x47 && bytes[1] === 0x49 &&
        bytes[2] === 0x46) return 'image/gif';
    // SVG is text: look past a byte-order mark and any leading whitespace.
    var i = 0;
    if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) i = 3;
    while (i < bytes.length && bytes[i] <= 0x20) i++;
    if (bytes[i] === 0x3c) {          // '<'
      var head = '';
      for (var j = i; j < Math.min(i + 8, bytes.length); j++) {
        head += String.fromCharCode(bytes[j]);
      }
      if (head.indexOf('<?xml') === 0 || head.indexOf('<svg') === 0) return 'image/svg+xml';
    }
    return '';
  }

  function mimeFor(bytes, declared) {
    return sniffMime(bytes) || MIME[String(declared || '').toUpperCase()] || '';
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
    return entry.async('uint8array').then(function (bytes) {
      return new Promise(function (resolve) {
        var type = mimeFor(bytes, f.format);
        var url = URL.createObjectURL(new Blob([bytes], type ? { type: type } : undefined));
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
          $('ptbEmpty').textContent = type
            ? 'This floor plan image could not be displayed.'
            : 'This floor plan is in a format the page cannot display.';
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
    var out = {};
    Object.keys(box.boxes).forEach(function (id) {
      if (box.applied && box.applied[id]) out[id] = box.boxes[id];
    });
    return Object.keys(out).length ? out : null;
  };

  // Called when analyze returns: the content bounds are only known then, so a
  // view that is still the automatic one re-frames onto the drawing.
  window.__ptRefit = function () {
    if (!box.img || !box.autoFramed) return;
    fitView();
    draw();
  };

  // True when this floor has a rectangle waiting to be cropped. The applied
  // lookup is written defensively here and at its three other call sites
  // because box is rebuilt on every file open, and because the Node tests
  // evaluate these functions in isolation from one another.
  function hasDraft(id) {
    return !!(box.boxes[id] && !(box.applied && box.applied[id]));
  }

  // Called by loadFile once the archive is open.
  window.__ptBoxInit = function (zip, projectId) {
    box.zip = zip;
    box.projectId = projectId;
    box.boxes = {};
    box.img = null;
    box.imgFor = null;

    return Promise.all([
      zip.file('floorPlans.json') ? zip.file('floorPlans.json').async('string') : null,
      restore(projectId),
      zip.file('images.json') ? zip.file('images.json').async('string') : null
    ]).then(function (res) {
      var doc = res[0] ? JSON.parse(res[0]) : { floorPlans: [] };
      var saved = res[1] || {};
      box.boxes = {};
      box.applied = {};
      // Anything that was stored had been cropped, so it comes back cropped.
      Object.keys(saved).forEach(function (id) {
        box.boxes[id] = saved[id].slice(0, 4);
        box.applied[id] = true;
      });
      var formats = {};
      try {
        ((JSON.parse(res[2] || '{}').images) || []).forEach(function (i) {
          if (i && i.id) formats[i.id] = i.imageFormat || '';
        });
      } catch (e) { formats = {}; }
      box.floors = (doc.floorPlans || []).map(function (f) {
        return { id: f.id, name: f.name || '(unnamed)', imageId: f.imageId,
                 format: formats[f.imageId] || '',
                 w: Math.round(f.width || 0), h: Math.round(f.height || 0) };
      });
      $('ptBoxCard').hidden = box.floors.length === 0;
      renderStrip(null);
      if (box.floors.length) {
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
    // Bound on the stage rather than the canvas so the whole framed area
    // answers, including any overlay sitting on top of it.
    $('ptbStage').addEventListener('wheel', onWheel, { passive: false });
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
