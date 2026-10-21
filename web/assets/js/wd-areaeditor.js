/* WD.AreaEditor - draw the requirement area on the plan.
 *
 * One tool for Prep and for Capacity, so the two cannot drift apart: the
 * drawing, the rules for what counts as an area, the buttons and the sentence
 * under them live here, and each page supplies only where its floors, its
 * canvas and its saved outlines are.
 *
 * It mounts on a WD.PlanView the way WD.BoxEditor does - pass onDown / onMove
 * / onUp to PlanView.create and call overlay from the view's overlay - and,
 * like the box, keeps its outline in plan units (the floor's own width and
 * height, the space the file is written in) scaled onto the displayed image.
 *
 * An outline is a list of [x, y] corners. Two ways to make one:
 *   rect   drag out a rectangle
 *   poly   click each corner; click the first corner, double-click or press
 *          Enter to finish; Backspace takes the last corner back; Esc cancels
 * and once there is one, drag a corner to move it or drag the small dot in the
 * middle of an edge to add a corner.
 *
 * The rules (three corners, a real size, no crossing edges) and the wording of
 * each refusal are tools.capacity_profiles.polygon_problem's twin;
 * tests/test_area_editor.py runs both on the same shapes.
 */
(function () {
  'use strict';

  var WD = window.WD = window.WD || {};

  var MIN_SIDE = 8;            // plan units, as WD.BoxEditor and the server
  // CSS pixels, scaled to the canvas's device pixels where used.
  var HIT_CSS = 12;            // aiming at a corner
  var MID_CSS = 10;            // aiming at the dot on an edge
  var DRAW_CSS = 10;           // corner square
  var CLOSE_CSS = 14;          // how near the first corner counts as "finish"
  var SLOP_CSS = 5;            // movement that is still a click
  var DEDUPE_CSS = 3;          // a second click this close adds nothing
  var DOUBLE_MS = 500;          // a second click this soon, on the spot, is a double-click
  var COLOR = '#db2777';       // the colour Prep already draws the area in

  var MSG = {
    few: 'An area needs at least three corners.',
    small: 'That area is too small.',
    cross: 'The outline crosses itself.',
  };

  // ── geometry ──────────────────────────────────────────────────────────────
  function orient(a, b, c) {
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  }

  function edgesCross(a, b, c, d) {
    return orient(a, b, c) * orient(a, b, d) < 0 && orient(c, d, a) * orient(c, d, b) < 0;
  }

  function polygonArea(pts) {
    var t = 0;
    for (var i = 0; i < pts.length; i++) {
      var a = pts[i], b = pts[(i + 1) % pts.length];
      t += a[0] * b[1] - b[0] * a[1];
    }
    return Math.abs(t) / 2;
  }

  // Why this cannot be an area, or '' when it can.
  function problem(pts) {
    if (!pts || pts.length < 3) return MSG.few;
    var xs = pts.map(function (p) { return p[0]; });
    var ys = pts.map(function (p) { return p[1]; });
    if (Math.max.apply(null, xs) - Math.min.apply(null, xs) < MIN_SIDE ||
        Math.max.apply(null, ys) - Math.min.apply(null, ys) < MIN_SIDE) return MSG.small;
    var n = pts.length;
    for (var i = 0; i < n; i++) {
      for (var j = i + 1; j < n; j++) {
        // Edges that share a corner always touch there; that is not a cross.
        if ((j + 1) % n === i || (i + 1) % n === j) continue;
        if (edgesCross(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n])) return MSG.cross;
      }
    }
    // After the crossing test: a bow tie nets to zero, and "too small" would
    // be the wrong thing to tell him about it.
    if (polygonArea(pts) <= 0) return MSG.small;
    return '';
  }

  function clone(pts) { return pts.map(function (p) { return [p[0], p[1]]; }); }

  function rectPoints(ax, ay, bx, by) {
    var x0 = Math.min(ax, bx), x1 = Math.max(ax, bx);
    var y0 = Math.min(ay, by), y1 = Math.max(ay, by);
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
  }

  // {floorId: [[x, y]]} as the query parameter the server reads, or ''.
  function param(drawn) {
    var out = {};
    Object.keys(drawn || {}).forEach(function (id) {
      var pts = drawn[id];
      if (!pts || pts.length < 3) return;
      out[id] = pts.map(function (p) {
        return { x: Math.round(p[0] * 100) / 100, y: Math.round(p[1] * 100) / 100 };
      });
    });
    return Object.keys(out).length ? JSON.stringify(out) : '';
  }

  // ── the tool ──────────────────────────────────────────────────────────────
  /* opts:
       get()       this floor's drawn outline [[x, y], ...], or null
       set(pts)    the outline while it is being changed (null: none)
       commit(pts) the outline once the button is let go
       size()      {w, h} of the floor in plan units
       shown()     what would be written otherwise, as [[x, y], ...], drawn
                   dashed while nothing is drawn; null for nothing
       enabled()   false: the editor draws nothing and takes no drag
       onMode(m)   'idle' | 'rect' | 'poly', when it changes
       onReject(m) a sentence, when an outline was refused */
  function create(opts) {
    var st = { mode: 'idle', pts: [], draft: null, cursor: null, drag: null, down: null, pv: null };
    var ed = {};

    function dpr() { return window.devicePixelRatio || 1; }
    function on() { return !opts.enabled || opts.enabled(); }

    function ratio(pv) {
      var s = opts.size();
      if (!pv.img || !s || !s.w || !s.h) return null;
      return { x: pv.img.width / s.w, y: pv.img.height / s.h };
    }
    function toScreen(pv, pt) {
      var k = ratio(pv);
      return pv.toScreen(pt[0] * k.x, pt[1] * k.y);
    }
    function toPlan(pv, p) {
      var k = ratio(pv);
      var i = pv.toImage(p.x, p.y);
      var s = opts.size();
      return [Math.max(0, Math.min(s.w, i.x / k.x)), Math.max(0, Math.min(s.h, i.y / k.y))];
    }
    function dist(a, b) { return Math.sqrt((a.x - b.x) * (a.x - b.x) + (a.y - b.y) * (a.y - b.y)); }
    function setCursor(pv, name) {
      if (pv.canvas && pv.canvas.style) pv.canvas.style.cursor = name || '';
    }
    function redraw() { if (st.pv) st.pv.draw(); }
    function mode(m) {
      st.mode = m;
      if (opts.onMode) opts.onMode(m);
    }
    function reject(msg) {
      if (opts.onReject) opts.onReject(msg);
      else if (WD.toast) WD.toast(msg, 'error');
    }

    // The corner or edge dot under the pointer, on the outline that exists.
    function hitAt(pv, p) {
      var poly = opts.get();
      if (!poly || !ratio(pv)) return null;
      var d = dpr();
      var i, s;
      for (i = 0; i < poly.length; i++) {
        if (dist(toScreen(pv, poly[i]), p) <= HIT_CSS * d) return { kind: 'vertex', i: i };
      }
      for (i = 0; i < poly.length; i++) {
        var a = poly[i], b = poly[(i + 1) % poly.length];
        s = toScreen(pv, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]);
        if (dist(s, p) <= MID_CSS * d) return { kind: 'mid', i: i };
      }
      return null;
    }

    ed.mode = function () { return st.mode; };
    ed.drawing = function () { return st.mode !== 'idle'; };

    ed.start = function (kind) {
      if (!on() || (kind !== 'rect' && kind !== 'poly')) return;
      st.pts = []; st.draft = null; st.cursor = null; st.drag = null; st.down = null; st.lastUp = null;
      mode(kind);
      redraw();
    };

    ed.cancel = function () {
      var was = st.mode;
      st.pts = []; st.draft = null; st.cursor = null; st.drag = null; st.down = null; st.lastUp = null;
      if (was !== 'idle') mode('idle');
      redraw();
    };

    // Whether a drag starting here belongs to this tool rather than to the
    // plan: always while drawing, and on a corner or edge dot after.
    ed.claims = function (e, p, pv) {
      if (!on() || !ratio(pv)) return false;
      return st.mode !== 'idle' || !!hitAt(pv, p);
    };

    function finish(poly) {
      st.pts = []; st.draft = null; st.cursor = null; st.drag = null; st.down = null; st.lastUp = null;
      opts.set(poly);
      mode('idle');
      opts.commit(poly);
      redraw();
    }

    function closeShape() {
      var why = problem(st.pts);
      if (why) { reject(why); redraw(); return; }
      finish(clone(st.pts));
    }

    ed.onDown = function (e, p, pv) {
      if (!on() || e.button !== 0 || !ratio(pv)) return false;
      st.pv = pv;
      var at = toPlan(pv, p);
      if (st.mode === 'rect') {
        st.drag = { mode: 'rect', ix: at[0], iy: at[1] };
        st.draft = rectPoints(at[0], at[1], at[0], at[1]);
        return true;
      }
      if (st.mode === 'poly') {
        st.down = { x: p.x, y: p.y };
        return true;
      }
      var hit = hitAt(pv, p);
      if (!hit) return false;
      var poly = opts.get();
      if (hit.kind === 'vertex') {
        st.drag = { mode: 'vertex', i: hit.i, base: clone(poly), revert: clone(poly),
                    x: p.x, y: p.y, moved: false };
      } else {
        var a = poly[hit.i], b = poly[(hit.i + 1) % poly.length];
        var base = clone(poly);
        base.splice(hit.i + 1, 0, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]);
        st.drag = { mode: 'vertex', i: hit.i + 1, base: base, revert: clone(poly),
                    x: p.x, y: p.y, moved: false };
        opts.set(base);
      }
      return true;
    };

    ed.onMove = function (e, p, pv, dragging) {
      st.pv = pv;
      if (!ratio(pv) || !on()) return;
      var d = dpr();
      if (st.mode === 'poly') {
        st.cursor = toPlan(pv, p);
        setCursor(pv, 'crosshair');
        pv.draw();
        return;
      }
      if (!dragging || !st.drag) {
        if (st.mode === 'rect') { setCursor(pv, 'crosshair'); return; }
        var hit = hitAt(pv, p);
        setCursor(pv, hit ? (hit.kind === 'vertex' ? 'move' : 'copy') : '');
        return;
      }
      var at = toPlan(pv, p);
      if (st.drag.mode === 'rect') {
        st.draft = rectPoints(st.drag.ix, st.drag.iy, at[0], at[1]);
      } else {
        if (dist(st.drag, p) > SLOP_CSS * d) st.drag.moved = true;
        var next = clone(st.drag.base);
        next[st.drag.i] = at;
        opts.set(next);
      }
      pv.draw();
    };

    ed.onUp = function (e, p, pv) {
      st.pv = pv;
      var d = dpr();
      if (st.mode === 'poly') {
        var down = st.down;
        st.down = null;
        if (!down || dist(down, p) > SLOP_CSS * d) { pv.draw(); return; }
        var first = st.pts.length >= 3 ? toScreen(pv, st.pts[0]) : null;
        if (first && dist(first, p) <= CLOSE_CSS * d) { closeShape(); return; }
        var at = toPlan(pv, p);
        var last = st.pts.length ? toScreen(pv, st.pts[st.pts.length - 1]) : null;
        if (!last || dist(last, p) > DEDUPE_CSS * d) st.pts.push(at);
        // A double-click is a click that finishes. The browser's own click
        // count is not trusted alone: Safari's synthesised double-click
        // arrives with a count of 1 on both mouse-ups, so a second click on
        // the same spot straight after the first counts too.
        var now = Date.now();
        var again = e.detail >= 2 || (st.lastUp && now - st.lastUp.t <= DOUBLE_MS &&
                                      dist(st.lastUp, p) <= SLOP_CSS * d);
        if (again && st.pts.length >= 3) { closeShape(); return; }
        st.lastUp = { x: p.x, y: p.y, t: now };
        pv.draw();
        return;
      }
      var drag = st.drag;
      if (!drag) return;
      st.drag = null;
      if (drag.mode === 'rect') {
        var box = st.draft;
        st.draft = null;
        // A click is not a rectangle. It stays in this mode so a stray click
        // does not cost the button he just pressed.
        if (!box || box[2][0] - box[0][0] < MIN_SIDE || box[2][1] - box[0][1] < MIN_SIDE) {
          pv.draw();
          return;
        }
        finish(box);
        return;
      }
      if (!drag.moved) {
        // Pressed and let go on the spot: a corner is where it was, and a dot
        // on an edge has not become a corner.
        opts.set(drag.revert);
        pv.draw();
        return;
      }
      var poly = opts.get();
      var why = problem(poly);
      if (why) {
        opts.set(drag.revert);
        reject(why);
        pv.draw();
        return;
      }
      opts.commit(poly);
      pv.draw();
    };

    // Returns true when the key was this tool's.
    ed.onKey = function (e) {
      if (!on()) return false;
      if (st.mode === 'idle') return false;
      if (e.key === 'Escape') { ed.cancel(); return true; }
      if (st.mode === 'poly') {
        if (e.key === 'Enter') {
          if (st.pts.length >= 3) closeShape();
          else { reject(MSG.few); }
          return true;
        }
        if (e.key === 'Backspace' || e.key === 'Delete') {
          st.pts.pop();
          redraw();
          return true;
        }
      }
      return false;
    };

    function trace(g, pv, pts) {
      pts.forEach(function (c, i) {
        var s = toScreen(pv, c);
        if (i) g.lineTo(s.x, s.y); else g.moveTo(s.x, s.y);
      });
    }

    function square(g, s, size, fill) {
      g.fillStyle = '#ffffff';
      g.fillRect(s.x - size / 2 - 1, s.y - size / 2 - 1, size + 2, size + 2);
      g.fillStyle = fill;
      g.fillRect(s.x - size / 2, s.y - size / 2, size, size);
    }

    function outline(g, pv, pts, o) {
      if (!pts || pts.length < 3) return;
      var d = dpr();
      g.save();
      g.beginPath();
      trace(g, pv, pts);
      g.closePath();
      g.fillStyle = o.fill;
      g.fill();
      g.strokeStyle = o.stroke;
      g.lineWidth = 2 * d;
      if (o.dash) g.setLineDash([7 * d, 5 * d]);
      g.stroke();
      g.restore();
      if (!o.handles) return;
      var hs = DRAW_CSS * d;
      g.save();
      pts.forEach(function (c, i) {
        var b = pts[(i + 1) % pts.length];
        var m = toScreen(pv, [(c[0] + b[0]) / 2, (c[1] + b[1]) / 2]);
        g.beginPath();
        g.arc(m.x, m.y, (MID_CSS / 2) * d, 0, Math.PI * 2);
        g.fillStyle = '#ffffff';
        g.fill();
        g.strokeStyle = COLOR;
        g.lineWidth = 1.5 * d;
        g.stroke();
      });
      pts.forEach(function (c) { square(g, toScreen(pv, c), hs, COLOR); });
      g.restore();
    }

    ed.overlay = function (g, pv) {
      st.pv = pv;
      if (!on() || !ratio(pv)) return;
      var d = dpr();
      var drawing = st.mode !== 'idle';
      var poly = opts.get();
      if (poly && !drawing) {
        outline(g, pv, poly, { fill: 'rgba(236,72,153,0.18)', stroke: COLOR, handles: true });
      } else if (poly) {
        // What the new outline will replace.
        outline(g, pv, poly, { fill: 'rgba(236,72,153,0.06)', stroke: COLOR, dash: true });
      } else if (!drawing && opts.shown) {
        outline(g, pv, opts.shown(), { fill: 'rgba(236,72,153,0.10)', stroke: COLOR, dash: true });
      }
      if (st.mode === 'rect' && st.draft) {
        outline(g, pv, st.draft, { fill: 'rgba(236,72,153,0.18)', stroke: COLOR });
      }
      if (st.mode === 'poly' && st.pts.length) {
        g.save();
        g.beginPath();
        trace(g, pv, st.pts);
        if (st.cursor) {
          var c = toScreen(pv, st.cursor);
          g.lineTo(c.x, c.y);
        }
        g.strokeStyle = COLOR;
        g.lineWidth = 2 * d;
        g.stroke();
        st.pts.forEach(function (pt, i) {
          var s = toScreen(pv, pt);
          g.beginPath();
          g.arc(s.x, s.y, (i === 0 && st.pts.length >= 3 ? 7 : 4.5) * d, 0, Math.PI * 2);
          g.fillStyle = i === 0 ? COLOR : '#ffffff';
          g.fill();
          g.strokeStyle = COLOR;
          g.lineWidth = 2 * d;
          g.stroke();
        });
        g.restore();
      }
    };

    return ed;
  }

  // ── the buttons and the sentence under them ───────────────────────────────
  /* One set of controls, the same words on both pages. The page binds the
     floor it is showing and what is drawn on it; the handlers here act on
     whichever page bound them.

     ctl:
       editor     the tool from create()
       floor()    {id, name} of the floor on show, or null
       drawn()    this floor's drawn outline, or null
       enabled()  whether drawing is allowed at all right now
       why()      the sentence to show when it is not, or ''
       clear()    take this floor's drawn outline away */
  var ctl = null;

  function controlsHtml() {
    return '<div class="pb-grid2 wd-area-controls">'
      + '<button type="button" class="btn btn-sec" id="wdAreaRect" aria-pressed="false"'
      + ' data-action="call" data-fn="WD.AreaEditor.start" data-arg="rect"'
      + ' title="Drag out a rectangle on the plan. It replaces the automatic area on this floor.">'
      + 'Draw a rectangle</button>'
      + '<button type="button" class="btn btn-sec" id="wdAreaPoly" aria-pressed="false"'
      + ' data-action="call" data-fn="WD.AreaEditor.start" data-arg="poly"'
      + ' title="Click each corner of any shape. It replaces the automatic area on this floor.">'
      + 'Draw a shape</button>'
      + '<button type="button" class="btn btn-sec" id="wdAreaClear"'
      + ' data-action="call" data-fn="WD.AreaEditor.clear"'
      + ' title="Take this floor\'s drawn area away and let it be worked out automatically">'
      + 'Back to automatic</button>'
      + '</div>'
      + '<p class="pb-hint" id="wdAreaHint" role="status"></p>';
  }

  function hintText() {
    if (!ctl) return '';
    var m = ctl.editor.mode();
    if (m === 'rect') return 'Drag out the rectangle on the plan. Esc cancels.';
    if (m === 'poly') {
      return 'Click each corner. Click the first corner, double-click or press Enter to '
        + 'finish; Backspace takes the last corner back; Esc cancels.';
    }
    var why = ctl.why && ctl.why();
    if (why) return why;
    var f = ctl.floor && ctl.floor();
    var name = f && f.name ? f.name : 'this floor';
    if (ctl.drawn()) {
      return 'The area you drew on ' + name + ' is the one that gets written. Drag a corner to '
        + 'move it, or the small dot on an edge to add a corner.';
    }
    return 'Nothing drawn on ' + name + ', so its area is worked out automatically (the dashed '
      + 'line). Draw a rectangle or a shape to choose your own.';
  }

  function sync() {
    var q = function (id) { return document.getElementById(id); };
    var rect = q('wdAreaRect'), poly = q('wdAreaPoly'), clear = q('wdAreaClear'), hint = q('wdAreaHint');
    if (!rect || !ctl) return;
    var can = !!ctl.enabled();
    var m = ctl.editor.mode();
    rect.disabled = !can;
    poly.disabled = !can;
    rect.setAttribute('aria-pressed', m === 'rect' ? 'true' : 'false');
    poly.setAttribute('aria-pressed', m === 'poly' ? 'true' : 'false');
    rect.classList.toggle('is-on', m === 'rect');
    poly.classList.toggle('is-on', m === 'poly');
    clear.disabled = !can || !ctl.drawn();
    if (hint) hint.textContent = hintText();
  }

  var keysInstalled = false;
  function installKeys() {
    if (keysInstalled || !document.addEventListener) return;
    keysInstalled = true;
    document.addEventListener('keydown', function (e) {
      if (!ctl || !ctl.enabled()) return;
      var t = e.target, tag = t && t.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) return;
      if (ctl.editor.onKey(e)) e.preventDefault();
    });
  }

  function bind(c) {
    ctl = c;
    installKeys();
    sync();
  }

  function startKind(kind) {
    if (!ctl || !ctl.enabled()) return;
    // Pressing the button that is already on puts the tool down again.
    if (ctl.editor.mode() === kind) ctl.editor.cancel();
    else ctl.editor.start(kind);
    sync();
  }

  function clearDrawn() {
    if (!ctl || !ctl.drawn()) return;
    ctl.editor.cancel();
    ctl.clear();
    sync();
  }

  WD.AreaEditor = {
    create: create,
    problem: problem,
    polygonArea: polygonArea,
    param: param,
    controlsHtml: controlsHtml,
    bind: bind,
    sync: sync,
    start: startKind,
    clear: clearDrawn,
    MIN_SIDE: MIN_SIDE,
    MESSAGES: MSG,
  };
})();
