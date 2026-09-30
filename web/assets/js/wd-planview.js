/* WD.PlanView and WD.ProjectFile - the floor plan canvas, and the floors it
 * shows, as pieces any tool can mount.
 *
 * The first step of Prep becoming one workbench over PlanTrim, Capacity and
 * Quick Walls (docs/prep-workbench.md). The behaviour is PlanTrim's, which had
 * the most complete canvas in the suite: the same zoom step and limits, the
 * same pan gestures through WD.PanZoom, and the plan always drawn on a white
 * page. Two copies of that page is how Prep came to show CAD plans as grey
 * lines on black after PlanTrim had stopped doing so, so there is one here.
 *
 * Everything is in device pixels on the canvas, as in PlanTrim; `point(e)`
 * turns a mouse event into those.
 */
(function () {
  'use strict';

  var WD = window.WD = window.WD || {};

  var ZOOM_STEP = 1.15;
  var MIN_SCALE = 0.02;
  var MAX_SCALE = 20;
  var FIT_FILL = 0.97;

  function panGesture(e) {
    return !!(WD.PanZoom && WD.PanZoom.isPanGesture(e));
  }

  /* opts:
       canvas    the <canvas> to draw on (required)
       stage     element that takes the wheel and the pan classes; defaults to
                 the canvas's parent
       overlay   function (g, pv) drawn over the plan on every redraw
       frame     function () -> {x, y, w, h} in image pixels, or null for the
                 whole sheet; what fit() frames
       dragPans  true: a plain left drag pans too (a view with no tool on it);
                 or a function answering that at the moment of the drag
       onDown / onMove / onUp
                 a tool's own handlers. A pan gesture is always taken first;
                 onDown returning true claims the drag, and onMove / onUp are
                 then called with the same point until the button is let go. */
  function create(opts) {
    var cv = opts.canvas;
    var stage = opts.stage || cv.parentNode;
    var pv = {
      canvas: cv,
      img: null,
      view: { scale: 1, x: 0, y: 0 },
      // True until he pans or zooms. A later fit (the drawing's bounds tend to
      // arrive after the image) may then improve the framing; once he has
      // moved the plan it must stay where he put it.
      autoFramed: true,
      drag: null,
    };

    pv.toImage = function (px, py) {
      return { x: (px - pv.view.x) / pv.view.scale, y: (py - pv.view.y) / pv.view.scale };
    };
    pv.toScreen = function (ix, iy) {
      return { x: ix * pv.view.scale + pv.view.x, y: iy * pv.view.scale + pv.view.y };
    };

    pv.point = function (e) {
      var r = cv.getBoundingClientRect();
      var dpr = window.devicePixelRatio || 1;
      return { x: (e.clientX - r.left) * dpr, y: (e.clientY - r.top) * dpr };
    };

    pv.size = function () {
      var r = cv.getBoundingClientRect();
      var dpr = window.devicePixelRatio || 1;
      cv.width = Math.max(1, Math.round(r.width * dpr));
      cv.height = Math.max(1, Math.round(r.height * dpr));
    };

    pv.fit = function (region) {
      if (!pv.img || !cv.width) return;
      var r = region || (opts.frame && opts.frame()) ||
              { x: 0, y: 0, w: pv.img.width, h: pv.img.height };
      if (!(r.w > 0) || !(r.h > 0)) return;
      var s = Math.min(cv.width / r.w, cv.height / r.h) * FIT_FILL;
      pv.view.scale = s;
      pv.view.x = (cv.width - r.w * s) / 2 - r.x * s;
      pv.view.y = (cv.height - r.h * s) / 2 - r.y * s;
      pv.autoFramed = true;
    };

    pv.draw = function () {
      var g = cv.getContext('2d');
      g.clearRect(0, 0, cv.width, cv.height);
      if (!pv.img) return;
      g.imageSmoothingEnabled = true;
      var tl = pv.toScreen(0, 0);
      var w = pv.img.width * pv.view.scale, h = pv.img.height * pv.view.scale;
      // A plan is drawn on paper. A CAD plan is an SVG and parts of it can be
      // transparent; on a dark stage that reads as grey lines on black, which
      // is not how it looks on any sheet it is printed on.
      g.fillStyle = '#fff';
      g.fillRect(tl.x, tl.y, w, h);
      g.drawImage(pv.img, tl.x, tl.y, w, h);
      if (opts.overlay) opts.overlay(g, pv);
    };

    // A new image is framed afresh; null clears the stage.
    pv.setImage = function (img) {
      pv.img = img || null;
      pv.size();
      pv.fit();
      pv.draw();
    };

    // The Fit button, and a window resize while the view is still automatic.
    pv.reset = function () {
      pv.size();
      pv.fit();
      pv.draw();
    };

    pv.zoomAt = function (k, px, py) {
      if (!pv.img) return;
      var before = pv.toImage(px, py);
      pv.view.scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, pv.view.scale * k));
      var after = pv.toScreen(before.x, before.y);
      pv.view.x += px - after.x;
      pv.view.y += py - after.y;
      pv.autoFramed = false;
      pv.draw();
    };

    function onWheel(e) {
      // Always swallowed over the stage, even with nothing loaded: a wheel
      // that scrolls the page instead reads as the canvas ignoring it.
      e.preventDefault();
      // No vertical movement is a sideways trackpad swipe, not a zoom. Read as
      // one it zoomed out, since anything that is not "up" counted as "down".
      if (!e.deltaY) return;
      var p = pv.point(e);
      pv.zoomAt(e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP, p.x, p.y);
    }

    function onDown(e) {
      if (!pv.img) return;
      var p = pv.point(e);
      // dragPans may be a function: a view whose tool is only sometimes on
      // (Prep's box editor, on the Trim stage) pans on a plain drag the rest
      // of the time.
      var dragPans = typeof opts.dragPans === 'function' ? opts.dragPans() : opts.dragPans;
      if (panGesture(e) || (dragPans && e.button === 0)) {
        pv.drag = { mode: 'pan', px: p.x, py: p.y, ox: pv.view.x, oy: pv.view.y };
        stage.classList.add('is-panning');
        e.preventDefault();
        return;
      }
      if (opts.onDown && opts.onDown(e, p, pv)) {
        pv.drag = { mode: 'tool' };
        e.preventDefault();
      }
    }

    function onMove(e) {
      var p = pv.point(e);
      var d = pv.drag;
      if (!d) {
        stage.classList.toggle('can-pan', !!(WD.PanZoom && WD.PanZoom.isHeld()));
        if (opts.onMove) opts.onMove(e, p, pv, false);
        return;
      }
      if (d.mode === 'pan') {
        pv.view.x = d.ox + (p.x - d.px);
        pv.view.y = d.oy + (p.y - d.py);
        pv.autoFramed = false;
        pv.draw();
        return;
      }
      if (opts.onMove) opts.onMove(e, p, pv, true);
    }

    function onUp(e) {
      var d = pv.drag;
      if (!d) return;
      pv.drag = null;
      stage.classList.remove('is-panning');
      if (d.mode === 'tool' && opts.onUp) opts.onUp(e, pv.point(e), pv);
    }

    function onResize() {
      if (!pv.img) return;
      pv.size();
      if (pv.autoFramed) pv.fit();
      pv.draw();
    }

    function onContext(e) { e.preventDefault(); }

    stage.addEventListener('wheel', onWheel, { passive: false });
    cv.addEventListener('mousedown', onDown);
    cv.addEventListener('contextmenu', onContext);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    window.addEventListener('resize', onResize);
    var unsubPan = WD.PanZoom && WD.PanZoom.onChange
      ? WD.PanZoom.onChange(function (held) { stage.classList.toggle('can-pan', !!held); })
      : null;

    pv.destroy = function () {
      stage.removeEventListener('wheel', onWheel);
      cv.removeEventListener('mousedown', onDown);
      cv.removeEventListener('contextmenu', onContext);
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      window.removeEventListener('resize', onResize);
      if (typeof unsubPan === 'function') unsubPan();
    };

    return pv;
  }

  WD.PlanView = { create: create, ZOOM_STEP: ZOOM_STEP };

  /* ── WD.BoxEditor ───────────────────────────────────────────────────────
     PlanTrim's keep-region editor as a tool that mounts on a PlanView: drag
     out a rectangle, drag a handle or an edge to adjust it, drag inside it to
     move it. Pass its onDown / onMove / onUp to WD.PlanView.create and call
     its overlay from the view's.

     The box lives in plan units - the floor's own width and height, the space
     the trimmer crops in - and is scaled onto the displayed image, because a
     browser renders an SVG plan at whatever size its root element asks for.

     opts:
       get()        this floor's box [x0, y0, x1, y1], or null
       set(b)       a box while it is being dragged (null: none)
       commit(b)    the box once the button is let go (null: taken away)
       size()       {w, h} of the floor in plan units
       proposed()   what automatic would keep, drawn dashed when there is no
                    box; null for nothing
       enabled()    false: the editor draws nothing and takes no drag */

  // CSS pixels, scaled to the canvas's device pixels where used. They used to
  // be device pixels in PlanTrim, which on a 1.5x or 2x display made a handle
  // about four CSS pixels across: too small to aim at, and a near miss started
  // a new box over the one being adjusted.
  var HANDLE_HIT_CSS = 16;
  var HANDLE_DRAW_CSS = 11;
  var MIN_SIDE = 8;          // plan units; matches MIN_MANUAL_SIDE server-side

  var HANDLE_CURSORS = {
    nw: 'nwse-resize', se: 'nwse-resize',
    ne: 'nesw-resize', sw: 'nesw-resize',
    n: 'ns-resize', s: 'ns-resize',
    e: 'ew-resize', w: 'ew-resize',
    move: 'move',
  };

  function normaliseBox(b) {
    return [Math.min(b[0], b[2]), Math.min(b[1], b[3]),
            Math.max(b[0], b[2]), Math.max(b[1], b[3])];
  }

  function clampBox(b, s) {
    return [Math.max(0, Math.min(b[0], s.w)), Math.max(0, Math.min(b[1], s.h)),
            Math.max(0, Math.min(b[2], s.w)), Math.max(0, Math.min(b[3], s.h))];
  }

  function handlePoints(x, y, w, h) {
    return [
      { id: 'nw', x: x, y: y }, { id: 'n', x: x + w / 2, y: y },
      { id: 'ne', x: x + w, y: y }, { id: 'e', x: x + w, y: y + h / 2 },
      { id: 'se', x: x + w, y: y + h }, { id: 's', x: x + w / 2, y: y + h },
      { id: 'sw', x: x, y: y + h }, { id: 'w', x: x, y: y + h / 2 },
    ];
  }

  function boxEditor(opts) {
    var drag = null;
    function dpr() { return window.devicePixelRatio || 1; }
    function on() { return !opts.enabled || opts.enabled(); }

    // Plan units per displayed image pixel, each way.
    function ratio(pv) {
      var s = opts.size();
      if (!pv.img || !s || !s.w || !s.h) return null;
      return { x: pv.img.width / s.w, y: pv.img.height / s.h };
    }
    function toScreen(pv, px, py) {
      var k = ratio(pv);
      return pv.toScreen(px * k.x, py * k.y);
    }
    function toPlan(pv, p) {
      var k = ratio(pv);
      var i = pv.toImage(p.x, p.y);
      return { x: i.x / k.x, y: i.y / k.y };
    }
    function rectOnScreen(pv, b) {
      var a = toScreen(pv, b[0], b[1]), c = toScreen(pv, b[2], b[3]);
      return { x: Math.min(a.x, c.x), y: Math.min(a.y, c.y),
               w: Math.abs(c.x - a.x), h: Math.abs(c.y - a.y) };
    }

    function handleAt(pv, p) {
      var b = opts.get();
      if (!b || !ratio(pv)) return null;
      var r = rectOnScreen(pv, b);
      var reach = HANDLE_HIT_CSS * dpr();
      // Nearest handle within reach: corner and edge handles sit close
      // together on a small box, and the first match grabs the wrong one.
      var found = null, best = Infinity;
      handlePoints(r.x, r.y, r.w, r.h).forEach(function (h) {
        var d = Math.max(Math.abs(p.x - h.x), Math.abs(p.y - h.y));
        if (d <= reach && d < best) { best = d; found = h.id; }
      });
      if (found) return found;
      // Anywhere along an edge drags that edge.
      var onY = p.y >= r.y - reach && p.y <= r.y + r.h + reach;
      var onX = p.x >= r.x - reach && p.x <= r.x + r.w + reach;
      if (onY && Math.abs(p.x - r.x) <= reach) return 'w';
      if (onY && Math.abs(p.x - (r.x + r.w)) <= reach) return 'e';
      if (onX && Math.abs(p.y - r.y) <= reach) return 'n';
      if (onX && Math.abs(p.y - (r.y + r.h)) <= reach) return 's';
      if (p.x > r.x && p.x < r.x + r.w && p.y > r.y && p.y < r.y + r.h) return 'move';
      return null;
    }

    function setCursor(pv, name) {
      if (pv.canvas && pv.canvas.style) pv.canvas.style.cursor = name || '';
    }

    var ed = {};

    ed.cursorAt = function (pv, p) {
      if (!on() || !pv.img) return '';
      var id = handleAt(pv, p);
      return id ? HANDLE_CURSORS[id] : 'crosshair';
    };

    ed.onDown = function (e, p, pv) {
      if (!on() || e.button !== 0 || !ratio(pv)) return false;
      var grip = handleAt(pv, p);
      var at = toPlan(pv, p);
      var b = opts.get();
      if (grip) {
        drag = { mode: grip, start: b.slice(), ix: at.x, iy: at.y };
      } else {
        drag = { mode: 'new', ix: at.x, iy: at.y };
        opts.set([at.x, at.y, at.x, at.y]);
      }
      return true;
    };

    ed.onMove = function (e, p, pv, dragging) {
      if (!dragging || !drag) {
        var held = !!(WD.PanZoom && WD.PanZoom.isHeld());
        // While space is held the stylesheet's grab cursor applies.
        setCursor(pv, held ? '' : ed.cursorAt(pv, p));
        return;
      }
      setCursor(pv, HANDLE_CURSORS[drag.mode] || 'crosshair');
      var s = opts.size();
      var at = toPlan(pv, p);
      var b;
      if (drag.mode === 'new') {
        b = [drag.ix, drag.iy, at.x, at.y];
      } else if (drag.mode === 'move') {
        var dx = at.x - drag.ix, dy = at.y - drag.iy;
        var w = drag.start[2] - drag.start[0], h = drag.start[3] - drag.start[1];
        b = [drag.start[0] + dx, drag.start[1] + dy, drag.start[2] + dx, drag.start[3] + dy];
        // A move keeps its size at the edge instead of squashing against it.
        if (b[0] < 0) { b[0] = 0; b[2] = w; }
        if (b[1] < 0) { b[1] = 0; b[3] = h; }
        if (b[2] > s.w) { b[2] = s.w; b[0] = s.w - w; }
        if (b[3] > s.h) { b[3] = s.h; b[1] = s.h - h; }
      } else {
        b = drag.start.slice();
        if (drag.mode.indexOf('n') >= 0) b[1] = at.y;
        if (drag.mode.indexOf('s') >= 0) b[3] = at.y;
        if (drag.mode.indexOf('w') >= 0) b[0] = at.x;
        if (drag.mode.indexOf('e') >= 0) b[2] = at.x;
      }
      opts.set(clampBox(normaliseBox(b), s));
      pv.draw();
    };

    ed.onUp = function (e, p, pv) {
      if (!drag) return;
      drag = null;
      var b = opts.get();
      if (b) {
        b = clampBox(normaliseBox(b), opts.size());
        // A click is not a rectangle. Leaving a sliver behind would crop the
        // floor to nothing, so it counts as a miss and the floor stays
        // automatic.
        if (b[2] - b[0] < MIN_SIDE || b[3] - b[1] < MIN_SIDE) b = null;
      }
      opts.set(b);
      opts.commit(b);
      pv.draw();
    };

    ed.overlay = function (g, pv) {
      if (!on() || !ratio(pv)) return;
      var cv = pv.canvas;
      var b = opts.get();
      var d = dpr();
      if (!b) {
        // What automatic would keep: shaded outside, a dashed edge, no
        // handles - there is nothing to grab until he draws.
        var auto = opts.proposed && opts.proposed();
        if (!auto) return;
        var a = rectOnScreen(pv, auto);
        g.save();
        g.fillStyle = 'rgba(0,0,0,0.38)';
        g.beginPath();
        g.rect(0, 0, cv.width, cv.height);
        g.rect(a.x, a.y, a.w, a.h);
        g.fill('evenodd');
        g.strokeStyle = 'rgba(74,158,255,0.9)';
        g.lineWidth = 2 * d;
        g.setLineDash([7 * d, 5 * d]);
        g.strokeRect(a.x, a.y, a.w, a.h);
        g.restore();
        return;
      }
      var r = rectOnScreen(pv, b);
      // Dim what is being thrown away: the question being answered is "what
      // goes", and shading answers it without inverting the picture.
      g.save();
      g.fillStyle = 'rgba(0,0,0,0.55)';
      g.beginPath();
      g.rect(0, 0, cv.width, cv.height);
      g.rect(r.x, r.y, r.w, r.h);
      g.fill('evenodd');
      g.strokeStyle = '#4a9eff';
      g.lineWidth = 2 * d;
      g.strokeRect(r.x, r.y, r.w, r.h);
      // White surround so a handle shows over dark linework and over paper.
      var hs = HANDLE_DRAW_CSS * d;
      handlePoints(r.x, r.y, r.w, r.h).forEach(function (h) {
        g.fillStyle = '#ffffff';
        g.fillRect(h.x - hs / 2 - 1, h.y - hs / 2 - 1, hs + 2, hs + 2);
        g.fillStyle = '#4a9eff';
        g.fillRect(h.x - hs / 2, h.y - hs / 2, hs, hs);
      });
      g.restore();
    };

    return ed;
  }

  WD.BoxEditor = { create: boxEditor, MIN_SIDE: MIN_SIDE,
                   normalise: normaliseBox, clamp: clampBox };

  /* ── WD.ProjectFile ─────────────────────────────────────────────────────
     The floors of one project and their images, loaded once and cached.

     Two sources, because a project reaches a tool two ways. A dropped file is
     already in the browser and is read with JSZip. One opened from disk never
     is - the point of opening from disk is not uploading a large project - so
     each floor's image is asked for on its own from the server. */

  function readFloors(zip) {
    var fp = zip.file('floorPlans.json');
    if (!fp) return Promise.resolve([]);
    var im = zip.file('images.json');
    return Promise.all([fp.async('string'), im ? im.async('string') : null])
      .then(function (res) {
        var formats = {};
        try {
          ((JSON.parse(res[1] || '{}').images) || []).forEach(function (i) {
            if (i && i.id) formats[i.id] = i.imageFormat || '';
          });
        } catch (e) { formats = {}; }
        return ((JSON.parse(res[0]).floorPlans) || []).map(function (f) {
          return { id: f.id, name: f.name || '(unnamed)', imageId: f.imageId,
                   format: formats[f.imageId] || '',
                   w: Math.round(f.width || 0), h: Math.round(f.height || 0) };
        });
      });
  }

  function toImage(blob, declaredType) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(blob);
      var im = new Image();
      im.onload = function () { URL.revokeObjectURL(url); resolve(im); };
      im.onerror = function () {
        URL.revokeObjectURL(url);
        reject(new Error(declaredType === ''
          ? 'This floor plan is in a format the page cannot display.'
          : 'This floor plan image could not be displayed.'));
      };
      im.src = url;
    });
  }

  function projectFile(fetchImage, listFloors) {
    var cache = {};
    var floorsP = null;
    return {
      floors: function () {
        if (!floorsP) floorsP = listFloors();
        return floorsP;
      },
      image: function (floorId) {
        if (!cache[floorId]) {
          cache[floorId] = fetchImage(floorId);
          // A failure is not remembered: the next ask tries again.
          cache[floorId].catch(function () { delete cache[floorId]; });
        }
        return cache[floorId];
      },
    };
  }

  WD.ProjectFile = {
    fromBytes: function (bytes) {
      var zipP = null;
      function zip() {
        if (typeof JSZip === 'undefined') return Promise.reject(new Error('no image'));
        if (!zipP) zipP = JSZip.loadAsync(bytes);
        return zipP;
      }
      var pf = projectFile(function (floorId) {
        return pf.floors().then(function (floors) {
          var f = floors.filter(function (x) { return x.id === floorId; })[0];
          if (!f) throw new Error('This project has no floor plans.');
          return zip().then(function (z) {
            var entry = f.imageId && z.file('image-' + f.imageId);
            if (!entry) throw new Error('This floor has no image in the archive.');
            return entry.async('uint8array').then(function (b) {
              var type = WD.imageMime ? WD.imageMime(b, f.format) : '';
              return toImage(new Blob([b], type ? { type: type } : undefined), type);
            });
          });
        });
      }, function () { return zip().then(readFloors); });
      return pf;
    },

    // `url(floorId)` names the server route that returns that floor's image.
    // The floor list comes from whatever report the tool already has.
    fromServer: function (url) {
      return projectFile(function (floorId) {
        return fetch(url(floorId), {
          method: 'POST', headers: { 'X-WD-Wireless-Tools': '1' },
        }).then(function (r) {
          if (!r.ok) {
            return r.json().then(function (j) { throw new Error(j.error || 'no image'); },
                                 function () { throw new Error('no image'); });
          }
          return r.blob().then(function (b) { return toImage(b, b.type); });
        });
      }, function () { return Promise.resolve([]); });
    },
  };
})();
