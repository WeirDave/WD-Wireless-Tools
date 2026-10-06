"""WD.PlanView and WD.ProjectFile, the shared floor plan canvas.

The first piece of Prep becoming one workbench over PlanTrim, Capacity and
Quick Walls (docs/prep-workbench.md). PlanTrim's canvas behaviour, made
mountable: the plan on a white page, zoom about the cursor, pan with the
suite's gestures, a tool's own drag handlers plugged in behind the pan.

Everything here drives the real file: the Node half evaluates
wd-planview.js whole against a recording canvas and fires the listeners it
registered, and the browser half renders it in Chrome, Edge and Firefox and
reads pixels back, because "fillStyle was #fff" and "the plan is white" are
different claims.
"""
from __future__ import annotations

import base64
import io
import json
import re
import shutil
import subprocess
import threading
import time
import unittest
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from tempfile import TemporaryDirectory

from tests import browsers as _browsers

try:  # pragma: no cover - availability varies by machine
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.action_chains import ActionChains
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False

ROOT = Path(__file__).resolve().parents[1]
PLANVIEW_JS = ROOT / "web" / "assets" / "js" / "wd-planview.js"
PREP_JS = ROOT / "web" / "assets" / "js" / "prep.js"
JSZIP_JS = ROOT / "web" / "assets" / "lib" / "jszip.min.js"
NODE_TIMEOUT_S = 120

needs_node = unittest.skipUnless(shutil.which("node"), "Node.js is not installed")

# A window, a stage and a canvas that record what is done to them. The
# listeners the module registers are kept so a test can fire them.
HARNESS = r"""
const fs = require('fs');
const calls = [];
const listeners = { window: {}, canvas: {}, stage: {} };
function on(where) {
  return {
    addEventListener(t, f) { (listeners[where][t] = listeners[where][t] || []).push(f); },
    removeEventListener(t, f) {
      listeners[where][t] = (listeners[where][t] || []).filter(x => x !== f);
    },
  };
}
function fire(where, type, ev) {
  (listeners[where][type] || []).forEach(f => f(Object.assign({
    preventDefault() {}, button: 0, clientX: 0, clientY: 0 }, ev)));
}
const g = new Proxy({}, {
  get(t, k) {
    if (k in t) return t[k];
    return (...a) => calls.push([k, ...a.map(x => (x && typeof x === 'object') ? 'obj' : x)]);
  },
  set(t, k, v) { if (k === 'fillStyle') calls.push(['fillStyle', v]); t[k] = v; return true; },
});
const canvas = Object.assign(on('canvas'), {
  width: 0, height: 0, getContext: () => g,
  getBoundingClientRect: () => ({ left: 0, top: 0, width: 400, height: 300 }),
});
const classes = new Set();
const stage = Object.assign(on('stage'), {
  classList: { add: c => classes.add(c), remove: c => classes.delete(c),
               toggle: (c, on) => on ? classes.add(c) : classes.delete(c) },
});
canvas.parentNode = stage;
globalThis.window = Object.assign(on('window'), { devicePixelRatio: 1 });
globalThis.WD = window.WD = {};
eval(fs.readFileSync(process.argv[1], 'utf8'));
const img = { width: 200, height: 100 };
"""


def node(body, *extra_args):
    r = subprocess.run(["node", "-e", HARNESS + body, str(PLANVIEW_JS), *extra_args],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout.strip().splitlines()[-1])


@needs_node
class ThePlanIsDrawnOnPaper(unittest.TestCase):

    def test_white_under_the_whole_plan_then_the_plan_then_the_overlay(self):
        out = node(r"""
let seen = null;
const pv = WD.PlanView.create({ canvas, overlay: (gg, v) => { calls.push(['overlay']); seen = v === pv; } });
pv.setImage(img);
console.log(JSON.stringify({ calls, seen }));
""")
        names = [c[0] for c in out["calls"]]
        fill, draw, over = names.index("fillRect"), names.index("drawImage"), names.index("overlay")
        self.assertEqual(out["calls"][fill - 1], ["fillStyle", "#fff"])
        self.assertLess(fill, draw)
        self.assertLess(draw, over)
        self.assertEqual(out["calls"][fill][1:], out["calls"][draw][2:],
                         "the white page is exactly the size and place of the plan")
        self.assertTrue(out["seen"], "the overlay is handed the view it is drawn on")

    def test_nothing_is_drawn_without_a_plan(self):
        out = node(r"""
const pv = WD.PlanView.create({ canvas, overlay: () => calls.push(['overlay']) });
pv.setImage(null);
console.log(JSON.stringify(calls.map(c => c[0])));
""")
        self.assertEqual(out, ["clearRect"])


@needs_node
class FramingAndZoom(unittest.TestCase):

    def test_the_whole_sheet_is_framed_centred(self):
        out = node(r"""
const pv = WD.PlanView.create({ canvas });
pv.setImage(img);
console.log(JSON.stringify([pv.view, pv.autoFramed, canvas.width, canvas.height]));
""")
        view, auto, w, h = out
        self.assertEqual((w, h), (400, 300))
        self.assertAlmostEqual(view["scale"], 2 * 0.97)
        self.assertAlmostEqual(view["x"], (400 - 200 * 1.94) / 2)
        self.assertAlmostEqual(view["y"], (300 - 100 * 1.94) / 2)
        self.assertTrue(auto)

    def test_a_frame_function_decides_what_fit_frames(self):
        out = node(r"""
const pv = WD.PlanView.create({ canvas, frame: () => ({ x: 50, y: 25, w: 100, h: 50 }) });
pv.setImage(img);
const c = pv.toScreen(100, 50);
console.log(JSON.stringify([pv.view.scale, c.x, c.y]));
""")
        self.assertAlmostEqual(out[0], 4 * 0.97)
        self.assertAlmostEqual(out[1], 200)
        self.assertAlmostEqual(out[2], 150)

    def test_the_wheel_zooms_about_the_point_under_the_cursor(self):
        out = node(r"""
const pv = WD.PlanView.create({ canvas });
pv.setImage(img);
const before = pv.toImage(123, 77);
const s0 = pv.view.scale;
fire('stage', 'wheel', { clientX: 123, clientY: 77, deltaY: -120 });
const after = pv.toImage(123, 77);
console.log(JSON.stringify([s0, pv.view.scale, before, after, pv.autoFramed]));
""")
        s0, s1, before, after, auto = out
        self.assertAlmostEqual(s1, s0 * 1.15)
        self.assertAlmostEqual(before["x"], after["x"])
        self.assertAlmostEqual(before["y"], after["y"])
        self.assertFalse(auto, "a zoom he made is not undone by the next automatic fit")

    def test_a_sideways_swipe_does_not_zoom(self):
        """deltaY 0 is horizontal scrolling. It used to count as "down" and
        zoom out; found when a browser sent one while scrolling into view."""
        out = node(r"""
const pv = WD.PlanView.create({ canvas });
pv.setImage(img);
const s0 = pv.view.scale;
let prevented = false;
fire('stage', 'wheel', { clientX: 50, clientY: 50, deltaY: 0, deltaX: 80,
                         preventDefault() { prevented = true; } });
console.log(JSON.stringify([pv.view.scale === s0, pv.autoFramed, prevented]));
""")
        self.assertEqual(out, [True, True, True])

    def test_zoom_stops_at_its_limits(self):
        out = node(r"""
const pv = WD.PlanView.create({ canvas });
pv.setImage(img);
for (let i = 0; i < 200; i++) pv.zoomAt(1.15, 10, 10);
const hi = pv.view.scale;
for (let i = 0; i < 400; i++) pv.zoomAt(1 / 1.15, 10, 10);
console.log(JSON.stringify([hi, pv.view.scale]));
""")
        self.assertAlmostEqual(out[0], 20)
        self.assertAlmostEqual(out[1], 0.02)

    def test_a_resize_refits_only_a_view_he_has_not_moved(self):
        out = node(r"""
const pv = WD.PlanView.create({ canvas });
pv.setImage(img);
pv.view.x = 999;
fire('window', 'resize', {});
const refitted = pv.view.x;
pv.zoomAt(1.15, 0, 0);
const held = pv.view.x;
fire('window', 'resize', {});
console.log(JSON.stringify([refitted !== 999, held === pv.view.x]));
""")
        self.assertEqual(out, [True, True])


@needs_node
class PanningAndTools(unittest.TestCase):

    def test_a_view_with_no_tool_pans_on_a_plain_drag(self):
        out = node(r"""
const pv = WD.PlanView.create({ canvas, dragPans: true });
pv.setImage(img);
const x0 = pv.view.x, y0 = pv.view.y;
fire('canvas', 'mousedown', { clientX: 100, clientY: 100 });
const during = classes.has('is-panning');
fire('window', 'mousemove', { clientX: 130, clientY: 90 });
fire('window', 'mouseup', {});
console.log(JSON.stringify([pv.view.x - x0, pv.view.y - y0, during, classes.has('is-panning')]));
""")
        self.assertEqual(out, [30, -10, True, False])

    def test_a_tool_gets_the_drag_and_the_pan_gesture_still_pans(self):
        out = node(r"""
const got = [];
WD.PanZoom = { isPanGesture: e => e.button === 1, isHeld: () => false };
const pv = WD.PlanView.create({ canvas,
  onDown: (e, p) => { got.push(['down', p.x, p.y]); return true; },
  onMove: (e, p, v, dragging) => { if (dragging) got.push(['move', p.x, p.y]); },
  onUp: (e, p) => got.push(['up']) });
pv.setImage(img);
const x0 = pv.view.x;
fire('canvas', 'mousedown', { clientX: 10, clientY: 20 });
fire('window', 'mousemove', { clientX: 15, clientY: 25 });
fire('window', 'mouseup', { clientX: 15, clientY: 25 });
const toolMoved = pv.view.x !== x0;
fire('canvas', 'mousedown', { clientX: 10, clientY: 20, button: 1 });
fire('window', 'mousemove', { clientX: 40, clientY: 20 });
fire('window', 'mouseup', {});
console.log(JSON.stringify({ got, toolMoved, panned: pv.view.x - x0 }));
""")
        self.assertEqual(out["got"], [["down", 10, 20], ["move", 15, 25], ["up"]])
        self.assertFalse(out["toolMoved"], "the tool's drag did not move the plan")
        self.assertEqual(out["panned"], 30, "middle-drag pans, and the tool never saw it")

    def test_without_a_tool_or_drag_pan_a_left_drag_does_nothing(self):
        out = node(r"""
const pv = WD.PlanView.create({ canvas });
pv.setImage(img);
const x0 = pv.view.x;
fire('canvas', 'mousedown', { clientX: 10, clientY: 10 });
fire('window', 'mousemove', { clientX: 60, clientY: 10 });
fire('window', 'mouseup', {});
console.log(JSON.stringify(pv.view.x - x0));
""")
        self.assertEqual(out, 0)

    def test_destroy_takes_every_listener_back(self):
        out = node(r"""
const pv = WD.PlanView.create({ canvas });
pv.destroy();
const left = [];
for (const where of Object.keys(listeners))
  for (const t of Object.keys(listeners[where]))
    if (listeners[where][t].length) left.push(where + ':' + t);
console.log(JSON.stringify(left));
""")
        self.assertEqual(out, [])


def _esx_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("floorPlans.json", json.dumps({"floorPlans": [
            {"id": "f1", "name": "Ground", "imageId": "i1", "width": 800.4, "height": 600},
            {"id": "f2", "imageId": "i2", "width": 10, "height": 10}]}))
        z.writestr("images.json", json.dumps({"images": [
            {"id": "i1", "imageFormat": "PNG"}, {"id": "i2", "imageFormat": "SVG"}]}))
    return buf.getvalue()


# The box editor on a real PlanView. The image renders at twice the plan's own
# size (an SVG does that), so every box assertion also proves the scaling: a
# drag of 100 canvas pixels is 50 plan units at a scale of 1.
EDITOR = r"""
let box = null, committed = [];
const ed = WD.BoxEditor.create({
  get: () => box, set: b => { box = b; }, commit: b => committed.push(b),
  size: () => ({ w: 100, h: 50 }), proposed: () => null, enabled: () => true,
});
const pv = WD.PlanView.create({ canvas, overlay: ed.overlay,
  onDown: ed.onDown, onMove: ed.onMove, onUp: ed.onUp });
pv.setImage(img);
pv.view.scale = 1; pv.view.x = 0; pv.view.y = 0;
function drag(x0, y0, x1, y1) {
  fire('canvas', 'mousedown', { clientX: x0, clientY: y0 });
  fire('window', 'mousemove', { clientX: x1, clientY: y1 });
  fire('window', 'mouseup', { clientX: x1, clientY: y1 });
}
"""


@needs_node
class TheBoxEditor(unittest.TestCase):

    def test_a_drag_draws_a_box_in_plan_units(self):
        out = node(EDITOR + "drag(20, 10, 120, 70); console.log(JSON.stringify([box, committed]));")
        self.assertEqual(out, [[10, 5, 60, 35], [[10, 5, 60, 35]]])

    def test_a_click_is_not_a_box(self):
        out = node(EDITOR + "drag(20, 10, 22, 12); console.log(JSON.stringify([box, committed]));")
        self.assertEqual(out, [None, [None]])

    def test_a_corner_handle_resizes_and_nothing_else_moves(self):
        out = node(EDITOR + "box = [10, 5, 60, 35]; drag(120, 70, 160, 90);"
                            "console.log(JSON.stringify(box));")
        self.assertEqual(out, [10, 5, 80, 45])

    def test_a_drag_inside_moves_it_and_stops_at_the_edge_whole(self):
        out = node(EDITOR + "box = [10, 5, 60, 35]; drag(80, 40, 380, 40);"
                            "console.log(JSON.stringify(box));")
        self.assertEqual(out, [50, 5, 100, 35], "moved to the edge, same size")

    def test_a_drag_outside_starts_a_new_box(self):
        out = node(EDITOR + "box = [10, 5, 20, 15]; drag(100, 60, 180, 90);"
                            "console.log(JSON.stringify(box));")
        self.assertEqual(out, [50, 30, 90, 45])

    def test_a_view_can_pan_on_a_plain_drag_only_while_its_tool_is_off(self):
        out = node(r"""
let tool = true;
const pv = WD.PlanView.create({ canvas, dragPans: () => !tool, onDown: () => true });
pv.setImage(img);
const x0 = pv.view.x;
fire('canvas', 'mousedown', { clientX: 10, clientY: 10 });
fire('window', 'mousemove', { clientX: 60, clientY: 10 });
fire('window', 'mouseup', {});
const withTool = pv.view.x - x0;
tool = false;
fire('canvas', 'mousedown', { clientX: 10, clientY: 10 });
fire('window', 'mousemove', { clientX: 60, clientY: 10 });
fire('window', 'mouseup', {});
console.log(JSON.stringify([withTool, pv.view.x - x0]));
""")
        self.assertEqual(out, [0, 50])

    def test_switched_off_it_takes_no_drag_and_the_view_pans(self):
        out = node(r"""
let box = null;
const ed = WD.BoxEditor.create({ get: () => box, set: b => { box = b; }, commit() {},
  size: () => ({ w: 100, h: 50 }), enabled: () => false });
const pv = WD.PlanView.create({ canvas, overlay: ed.overlay, dragPans: false,
  onDown: ed.onDown, onMove: ed.onMove, onUp: ed.onUp });
pv.setImage(img);
fire('canvas', 'mousedown', { clientX: 20, clientY: 10 });
fire('window', 'mousemove', { clientX: 120, clientY: 70 });
fire('window', 'mouseup', {});
console.log(JSON.stringify(box));
""")
        self.assertIsNone(out)


@needs_node
class TheProjectFileListsItsFloors(unittest.TestCase):

    def test_floors_come_from_the_archive_with_their_image_format(self):
        out = node(r"""
globalThis.JSZip = require(process.argv[2]);
const b = Buffer.from(process.argv[3], 'base64');
WD.ProjectFile.fromBytes(b).floors().then(f => console.log(JSON.stringify(f)))
  .catch(e => { console.error(e); process.exit(1); });
""", str(JSZIP_JS), base64.b64encode(_esx_bytes()).decode())
        self.assertEqual(out, [
            {"id": "f1", "name": "Ground", "imageId": "i1", "format": "PNG", "w": 800, "h": 600},
            {"id": "f2", "name": "(unnamed)", "imageId": "i2", "format": "SVG", "w": 10, "h": 10}])

    def test_a_server_image_is_asked_for_by_floor_id_and_cached(self):
        out = node(r"""
const asked = [];
globalThis.fetch = (url, o) => { asked.push([url, o.method, o.headers['X-WD-Wireless-Tools']]);
  return Promise.resolve({ ok: false, json: () => Promise.resolve({ error: 'no such floor' }) }); };
const pf = WD.ProjectFile.fromServer(id => '/api/prep/image?floor=' + encodeURIComponent(id));
pf.image('a b').catch(e => pf.image('a b').catch(e2 =>
  console.log(JSON.stringify({ asked, msg: e.message }))));
""")
        self.assertEqual(out["msg"], "no such floor")
        self.assertEqual(out["asked"][0], ["/api/prep/image?floor=a%20b", "POST", "1"])
        self.assertEqual(len(out["asked"]), 2, "a failure is not cached; asking again retries")


PREP_PROBE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function fn(head) {
  const a = src.indexOf(head);
  if (a < 0) throw new Error('moved: ' + head);
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
"""


def prep_node(body):
    r = subprocess.run(["node", "-e", PREP_PROBE + body, str(PREP_JS)],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout.strip().splitlines()[-1])


@needs_node
class PrepUsesTheSharedCanvas(unittest.TestCase):

    def test_the_kept_box_is_drawn_where_the_view_puts_the_plan(self):
        out = prep_node(r"""
const calls = [];
const g = new Proxy({}, { get(t, k) { if (k in t) return t[k];
  return (...a) => calls.push([k, ...a]); }, set(t, k, v) { t[k] = v; return true; } });
const window = { devicePixelRatio: 1 };
const f = { id: 'f', action: 'trimmed', oldSize: [200, 100], newSize: [100, 50],
            offset: [50, 25] };
eval(fn('function mapKeptBox(f, iw, ih) {'));
eval(fn('function drawKept(g, pv, f) {'));
const pv = { img: { width: 400, height: 200 },
             toScreen: (x, y) => ({ x: x * 0.5 + 10, y: y * 0.5 + 20 }) };
drawKept(g, pv, f);
console.log(JSON.stringify(calls.filter(c => c[0] === 'strokeRect')));
""")
        # The report box is in the plan's own 200x100 space; the image renders
        # at 400x200, so the box doubles, then the view places it.
        self.assertEqual(out, [["strokeRect", 60, 45, 100, 50]])

    def test_a_project_opened_from_disk_fetches_images_from_the_server(self):
        out = prep_node(r"""
const made = [];
const WD = { ProjectFile: {
  fromServer: u => { made.push(['server', u('f 1')]); return {}; },
  fromBytes: b => { made.push(['bytes', b]); return {}; } } };
var map = { file: null };
var fromDisk = true, fileBytes = null;
eval(fn('function mapFile() {'));
mapFile(); mapFile();
map.file = null; fromDisk = false; fileBytes = 'BYTES';
mapFile();
console.log(JSON.stringify(made));
""")
        self.assertEqual(out, [["server", "/api/prep/image?floor=f%201"], ["bytes", "BYTES"]])

    def test_the_fit_button_resets_the_view(self):
        """The handler is read off the button in prep.html and then called."""
        html = (ROOT / "web" / "prep.html").read_text(encoding="utf-8")
        self.assertLess(html.index("/assets/js/wd-planview.js"),
                        html.index("/assets/js/prep.js"))
        handler = re.search(r'data-fn="([^"]+)"[^>]*>Fit<', html).group(1)
        out = prep_node(r"""
let reset = 0;
const window = {};
var map = { view: { reset: () => reset++ } };
eval(fn('window.%s = function () {'));
window['%s']();
map.view = null;
window['%s']();
console.log(JSON.stringify(reset));
""" % (handler, handler, handler))
        self.assertEqual(out, 1, "Fit resets a view that exists, and is safe before one does")


BROWSER_PAGE = """<!doctype html><meta charset="utf-8">
<body style="margin:0;background:#202020">
<div id="stage" style="width:400px;height:300px"><canvas id="c"
  style="display:block;width:400px;height:300px"></canvas></div>
<script>window.onerror=function(m){document.title='ERR '+m;};</script>
<script>%s</script>
<script>
var pv = WD.PlanView.create({ canvas: document.getElementById('c'), dragPans: true });
var im = new Image();
im.onload = function () { pv.setImage(im); document.title = 'ready'; };
im.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(%s);
function px(x, y) {
  var d = document.getElementById('c').getContext('2d').getImageData(x, y, 1, 1).data;
  return [d[0], d[1], d[2], d[3]];
}
</script>"""

# Transparent everywhere except a grey outline: the shape that read as black.
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="150">'
       '<rect x="50" y="40" width="100" height="70" fill="none" stroke="#808080" '
       'stroke-width="3"/></svg>')


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheCanvasInARealBrowser(unittest.TestCase):

    @staticmethod
    def _driver(kind, binary):
        if not Path(binary).exists():
            return None
        try:
            if kind == "safari":
                return _browsers.safari_driver()
            if kind == "firefox":
                o = webdriver.FirefoxOptions()
                o.binary_location = binary
                o.add_argument("-headless")
                return webdriver.Firefox(options=o)
            if kind == "chrome":
                o = webdriver.ChromeOptions()
                o.binary_location = binary
                o.add_argument("--headless=new")
                o.add_argument("--no-sandbox")
                return webdriver.Chrome(options=o)
            o = webdriver.EdgeOptions()
            o.binary_location = binary
            o.add_argument("--headless=new")
            return webdriver.Edge(options=o)
        except (WebDriverException, OSError):
            return None

    def test_white_paper_zoom_and_pan(self):
        with TemporaryDirectory() as tmp:
            page = Path(tmp) / "planview.html"
            page.write_text(BROWSER_PAGE % (PLANVIEW_JS.read_text(encoding="utf-8"),
                                            json.dumps(SVG)), encoding="utf-8")
            # Served, not opened as a file: Safari answers a file: URL from an
            # automated session with "Failed to open page".
            handler = type("Quiet", (SimpleHTTPRequestHandler,),
                           {"log_message": lambda *a, **k: None})
            server = _browsers.ExclusiveServer(
                ("127.0.0.1", 0), partial(handler, directory=tmp))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(_browsers.stop_server, server)
            url = "http://127.0.0.1:%d/planview.html" % server.server_address[1]
            started = 0
            for kind, binary in _browsers.triple():
                driver = self._driver(kind, binary)
                if driver is None:
                    continue
                started += 1
                try:
                    driver.set_window_size(900, 700)
                    driver.set_script_timeout(20)
                    driver.get(url)
                    for _ in range(100):
                        if driver.title == "ready" or driver.title.startswith("ERR"):
                            break
                        time.sleep(0.1)
                    with self.subTest(browser=kind):
                        self.assertEqual(driver.title, "ready")
                        # Inside the plan, away from the outline: paper, not the page.
                        self.assertEqual(driver.execute_script("return px(200, 40)"),
                                         [255, 255, 255, 255])
                        # Outside the plan the stage stays clear.
                        self.assertEqual(driver.execute_script("return px(2, 150)")[3], 0)

                        s0 = driver.execute_script("return pv.view.scale")
                        driver.execute_script(
                            "document.getElementById('stage').dispatchEvent(new WheelEvent("
                            "'wheel', {deltaY: -120, clientX: 200, clientY: 150, "
                            "bubbles: true, cancelable: true}))")
                        s1 = driver.execute_script("return pv.view.scale")
                        self.assertAlmostEqual(s1 / s0, 1.15, places=6)

                        x0 = driver.execute_script("return pv.view.x")
                        canvas = driver.find_element("id", "c")
                        (ActionChains(driver).move_to_element(canvas).click_and_hold()
                         .move_by_offset(40, 0).release().perform())
                        dx = driver.execute_script("return pv.view.x") - x0
                        dpr = driver.execute_script("return window.devicePixelRatio || 1")
                        self.assertAlmostEqual(dx, 40 * dpr, delta=2 * dpr)
                finally:
                    _browsers.shut_down(driver)
            if not started:
                self.skipTest(_browsers.why_missing())


if __name__ == "__main__":
    unittest.main()
