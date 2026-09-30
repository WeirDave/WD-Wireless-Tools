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
       dragPans  true: a plain left drag pans too (a view with no tool on it)
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
      if (panGesture(e) || (opts.dragPans && e.button === 0)) {
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
