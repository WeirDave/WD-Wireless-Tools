"""Remembering a drawn keep-region, and the page that draws it.

Drawing a rectangle on fourteen CAD sheets once is a fair ask; doing it again on
every re-open is not. These cover the store that remembers them, the endpoints
the page calls, and the parts of the editor that are easy to get quietly wrong -
the box never being widened back out, and apply-to-all refusing sheets of a
different size rather than putting the rectangle over the wrong part of them.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from server import API_REQUEST_HEADER, app
from tools import plantrim_store

ROOT = Path(__file__).resolve().parent.parent
PLANTRIM_JS = ROOT / "web" / "assets" / "js" / "plantrim.js"
PLANTRIM_HTML = ROOT / "web" / "plantrim.html"

NODE_TIMEOUT_S = 120


class StoreTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        store = Path(self.tmp.name) / "plantrim-boxes.json"
        self.p_dir = patch.object(plantrim_store, "USER_DIR", Path(self.tmp.name))
        self.p_store = patch.object(plantrim_store, "STORE", store)
        self.p_dir.start(); self.p_store.start()
        self.addCleanup(self.p_dir.stop); self.addCleanup(self.p_store.stop)

    def test_a_box_survives_a_round_trip(self):
        plantrim_store.save("proj-1", {"floor-a": [10, 20, 300, 400]})
        self.assertEqual(plantrim_store.load("proj-1"),
                         {"floor-a": [10.0, 20.0, 300.0, 400.0]})

    def test_projects_do_not_see_each_others_boxes(self):
        plantrim_store.save("proj-1", {"floor-a": [1, 2, 3, 4]})
        plantrim_store.save("proj-2", {"floor-a": [9, 9, 90, 90]})
        self.assertEqual(plantrim_store.load("proj-1")["floor-a"], [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(plantrim_store.load("proj-2")["floor-a"], [9.0, 9.0, 90.0, 90.0])

    def test_an_empty_map_forgets_the_project(self):
        plantrim_store.save("proj-1", {"floor-a": [1, 2, 3, 4]})
        plantrim_store.save("proj-1", {})
        self.assertEqual(plantrim_store.load("proj-1"), {})

    def test_junk_is_dropped_rather_than_stored(self):
        plantrim_store.save("proj-1", {
            "good": [1, 2, 3, 4],
            "short": [1, 2, 3],
            "words": ["a", "b", "c", "d"],
            "notalist": {"x": 1},
        })
        self.assertEqual(list(plantrim_store.load("proj-1")), ["good"])

    def test_an_unreadable_store_reads_as_empty(self):
        plantrim_store.STORE.parent.mkdir(parents=True, exist_ok=True)
        plantrim_store.STORE.write_text("{ not json", encoding="utf-8")
        self.assertEqual(plantrim_store.load("proj-1"), {})

    def test_a_failed_write_leaves_the_previous_boxes(self):
        plantrim_store.save("proj-1", {"floor-a": [1, 2, 3, 4]})
        with patch("json.dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                plantrim_store.save("proj-1", {"floor-a": [5, 6, 7, 8]})
        self.assertEqual(plantrim_store.load("proj-1")["floor-a"], [1.0, 2.0, 3.0, 4.0])

    def test_no_temp_files_are_left_behind(self):
        plantrim_store.save("proj-1", {"floor-a": [1, 2, 3, 4]})
        leftovers = list(Path(self.tmp.name).glob(".plantrim-*"))
        self.assertEqual(leftovers, [])

    def test_the_store_does_not_grow_without_bound(self):
        for i in range(plantrim_store.MAX_PROJECTS + 25):
            plantrim_store.save(f"proj-{i}", {"f": [0, 0, 10, 10]})
        data = json.loads(plantrim_store.STORE.read_text(encoding="utf-8"))
        self.assertLessEqual(len(data), plantrim_store.MAX_PROJECTS)
        # The most recent survives; the oldest is what goes.
        self.assertIn(f"proj-{plantrim_store.MAX_PROJECTS + 24}", data)

    def test_no_project_id_stores_nothing(self):
        self.assertEqual(plantrim_store.save("", {"f": [0, 0, 1, 1]}), {})
        self.assertEqual(plantrim_store.load(""), {})


class EndpointTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        store = Path(self.tmp.name) / "plantrim-boxes.json"
        for attr, value in (("USER_DIR", Path(self.tmp.name)), ("STORE", store)):
            p = patch.object(plantrim_store, attr, value)
            p.start(); self.addCleanup(p.stop)

    def post(self, action, payload):
        return self.client.post(f"/api/plantrim/{action}", json=payload,
                                headers={API_REQUEST_HEADER: "1"})

    def test_save_then_load(self):
        r = self.post("boxes_save", {"projectId": "p1",
                                     "boxes": {"f1": [1, 2, 30, 40]}})
        self.assertEqual(r.status_code, 200)
        r = self.post("boxes_load", {"projectId": "p1"})
        self.assertEqual(r.get_json()["boxes"], {"f1": [1.0, 2.0, 30.0, 40.0]})

    def test_loading_an_unknown_project_is_empty_not_an_error(self):
        r = self.post("boxes_load", {"projectId": "never-seen"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["boxes"], {})

    def test_a_missing_project_id_is_handled(self):
        r = self.post("boxes_load", {})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["boxes"], {})

    def test_an_unknown_action_is_still_a_404(self):
        r = self.post("boxes_delete_everything", {"projectId": "p1"})
        self.assertEqual(r.status_code, 404)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class EditorLogicTests(unittest.TestCase):
    """The two behaviours that would be silent if they broke."""

    PRELUDE = r"""
    const fs = require('fs');
    const src = fs.readFileSync(process.argv[1], 'utf8');
    function slice(from, to) {
      const a = src.indexOf(from), b = src.indexOf(to, a);
      if (a < 0 || b < 0) throw new Error('could not find ' + from);
      return src.slice(a, b);
    }
    eval(slice('function clampBox', '\n  function onDown'));
    """

    def run_node(self, script):
        proc = subprocess.run(["node", "-e", self.PRELUDE + script, str(PLANTRIM_JS)],
                              capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError(f"node failed:\n{proc.stderr}")
        return json.loads(proc.stdout)

    def test_a_reversed_drag_normalises(self):
        out = self.run_node(
            "console.log(JSON.stringify(normalise([900, 800, 100, 200])));")
        self.assertEqual(out, [100, 200, 900, 800])

    def test_a_box_is_clamped_to_the_sheet(self):
        out = self.run_node(
            "console.log(JSON.stringify(clampBox([-50, -50, 5000, 6000], "
            "{w: 2000, h: 1500})));")
        self.assertEqual(out, [0, 0, 2000, 1500])


class EditorMarkupTests(unittest.TestCase):
    def test_the_controls_exist(self):
        html = PLANTRIM_HTML.read_text(encoding="utf-8")
        for ident in ("ptbStrip", "ptbCanvas", "ptbReadout", "ptbApplyAll",
                      "ptbClear", "ptbStage", "ptbHint", "ptBoxCard",
                      "ptbNext", "ptbFloorCount"):
            with self.subTest(id=ident):
                self.assertIn(f'id="{ident}"', html)

    def test_the_page_loads_jszip_to_read_the_plans(self):
        html = PLANTRIM_HTML.read_text(encoding="utf-8")
        self.assertIn("jszip.min.js", html)

    def test_space_drag_pans_using_the_shared_helper(self):
        """Ekahau pans on held Space; every canvas in the suite answers to it."""
        js = PLANTRIM_JS.read_text(encoding="utf-8")
        self.assertIn("WD.PanZoom.isPanGesture", js)
        self.assertIn("WD.PanZoom.onChange", js)

    def test_apply_to_all_refuses_a_different_sized_sheet(self):
        js = PLANTRIM_JS.read_text(encoding="utf-8")
        self.assertIn("f.w !== here.w || f.h !== here.h", js)

    def test_styles_are_scoped_to_the_page(self):
        shared = (ROOT / "web" / "assets" / "wd-tools.css").read_text(encoding="utf-8")
        self.assertNotIn("ptb-stage", shared)
        self.assertIn("ptb-stage", PLANTRIM_HTML.read_text(encoding="utf-8"))

    def test_boxes_are_not_written_into_the_esx(self):
        """The archive is Ekahau's format; our state lives beside the app."""
        store = (ROOT / "tools" / "plantrim_store.py").read_text(encoding="utf-8")
        self.assertIn(".wd_wireless_tools", store)
        self.assertNotIn("zipfile", store)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class HandleDragTests(unittest.TestCase):
    """A handle that renders is not a handle that works.

    Reported as "it says I can drag a handle to adjust but that is not working
    either". The handles drew fine. The sizes were in canvas *device* pixels,
    so on a 1.5x or 2x Windows display both the drawn handle and its hit target
    were about four CSS pixels across - and a near miss did not simply fail to
    grab, it fell through to "start a new box" and wiped the one being adjusted.

    So these drive a real press-move-release against the real functions and
    assert the box moved, at each display scaling, rather than checking that
    handles are drawn.
    """

    HARNESS = r"""
    const fs = require('fs');
    const src = fs.readFileSync(process.argv[1], 'utf8');
    function slice(a, b) {
      const i = src.indexOf(a), j = src.indexOf(b, i);
      if (i < 0 || j < 0) throw new Error('missing ' + a);
      return src.slice(i, j);
    }
    const DPR = Number(process.argv[2]);
    const stage = { classList: { add(){}, remove(){}, toggle(){} } };
    const ctx = new Proxy({}, { get: () => () => {} });
    const canvas = {
      width: 1200 * DPR, height: 800 * DPR,
      getContext: () => ctx,
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 1200, height: 800 }),
    };
    const els = { ptbCanvas: canvas, ptbStage: stage };
    const stub = () => ({ value:'', textContent:'', innerHTML:'', hidden:true,
                          disabled:false, className:'',
                          classList:{add(){},remove(){},toggle(){}} });
    globalThis.document = { getElementById: id => els[id] || (els[id] = stub()),
                            addEventListener(){} };
    globalThis.window = { devicePixelRatio: DPR, addEventListener(){} };
    globalThis.WD = { PanZoom: { isPanGesture: e => e.button === 1 || e.button === 2,
                                 isHeld: () => false, onChange(){} },
                      toast(){}, esc: s => String(s) };
    globalThis.$ = id => document.getElementById(id);
    globalThis.box = { boxes:{}, current:'f1', img:{ width:5000, height:3750 },
                       view:{ scale:1, x:0, y:0 }, drag:null,
                       floors:[{ id:'f1', name:'L1', w:5000, h:3750 }] };
    globalThis.draw = () => {};
    globalThis.updateReadout = () => {};
    globalThis.persist = () => {};
    globalThis.reanalyze = () => {};
    globalThis.showEvidence = () => {};
    globalThis.floorById = id => box.floors.find(f => f.id === id);

    eval(slice('  var HANDLE_HIT_CSS', '  var box = {'));
    eval(slice('  function toImage(px, py)', '  function fitView()'));
    eval(slice('  function handlePoints(x, y, w, h)', '  function updateReadout()'));
    eval(slice('  function clampBox(b, f)', '  function onWheel(e)'));

    const sc = Math.min(canvas.width/5000, canvas.height/3750) * 0.97;
    box.view = { scale: sc, x: (canvas.width-5000*sc)/2, y: (canvas.height-3750*sc)/2 };
    """

    def run_js(self, dpr, script):
        body = self.HARNESS + script
        proc = subprocess.run(["node", "-e", body, str(PLANTRIM_JS), str(dpr)],
                              capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError("node failed:\n" + proc.stderr)
        return json.loads(proc.stdout)

    DRAG = """
    box.boxes.f1 = [1000, 800, 3200, 3000];
    const before = box.boxes.f1.slice();
    const c = toScreen(3200, 3000);
    const off = Number(process.env.AIM_OFF_CSS || 0) * DPR;
    onDown({ button:0, clientX:(c.x+off)/DPR, clientY:(c.y+off)/DPR,
             preventDefault(){} });
    const mode = box.drag && box.drag.mode;
    onMove({ clientX:(c.x+160)/DPR, clientY:(c.y+80)/DPR });
    onUp();
    console.log(JSON.stringify({ mode: mode,
      before: before, after: box.boxes.f1,
      changed: JSON.stringify(box.boxes.f1) !== JSON.stringify(before) }));
    """

    def test_a_drag_on_a_handle_resizes_the_box(self):
        for dpr in (1, 1.5, 2, 3):
            with self.subTest(dpr=dpr):
                out = self.run_js(dpr, self.DRAG)
                self.assertEqual(out["mode"], "se",
                                 "the press must grab the handle, not start a new box")
                self.assertTrue(out["changed"], "the box did not move")
                self.assertGreater(out["after"][2], out["before"][2])
                self.assertGreater(out["after"][3], out["before"][3])

    def test_an_imprecise_aim_still_grabs_the_handle(self):
        """Six CSS pixels off used to miss and wipe the box."""
        import os
        env = dict(os.environ, AIM_OFF_CSS="6")
        for dpr in (1.5, 2):
            with self.subTest(dpr=dpr):
                body = self.HARNESS + self.DRAG
                proc = subprocess.run(["node", "-e", body, str(PLANTRIM_JS), str(dpr)],
                                      capture_output=True, text=True,
                                      timeout=NODE_TIMEOUT_S, env=env)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                out = json.loads(proc.stdout)
                self.assertEqual(out["mode"], "se")
                self.assertTrue(out["changed"])

    def test_the_hit_target_is_the_same_size_at_every_scaling(self):
        script = ("console.log(JSON.stringify({ hitCss: hitRadius() / DPR, "
                  "drawCss: handleSize() / DPR }));")
        for dpr in (1, 1.5, 2, 3):
            with self.subTest(dpr=dpr):
                out = self.run_js(dpr, script)
                self.assertAlmostEqual(out["hitCss"], 16, places=6)
                self.assertAlmostEqual(out["drawCss"], 11, places=6)

    def test_a_press_well_away_from_the_box_still_starts_a_new_one(self):
        script = """
        box.boxes.f1 = [1000, 800, 3200, 3000];
        const p = toScreen(4600, 3500);
        onDown({ button:0, clientX:p.x/DPR, clientY:p.y/DPR, preventDefault(){} });
        console.log(JSON.stringify({ mode: box.drag && box.drag.mode }));
        """
        self.assertEqual(self.run_js(2, script)["mode"], "new")

    def test_space_held_pans_instead_of_drawing(self):
        script = """
        box.boxes.f1 = [1000, 800, 3200, 3000];
        WD.PanZoom.isPanGesture = () => true;
        const c = toScreen(3200, 3000);
        onDown({ button:0, clientX:c.x/DPR, clientY:c.y/DPR, preventDefault(){} });
        console.log(JSON.stringify({ mode: box.drag && box.drag.mode }));
        """
        self.assertEqual(self.run_js(2, script)["mode"], "pan")


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class CanvasImageTypeTests(unittest.TestCase):
    """A floor plan has to be visible before a box can be drawn around it.

    Members inside an .esx carry no extension and no content type, so a blob
    built from one has neither. A browser sniffs a raster out of that happily,
    but an SVG is text and will not render through <img> without being told it
    is an image - so vector plans showed an empty canvas and no error at all.
    """

    PRELUDE = r"""
    const fs = require('fs');
    const src = fs.readFileSync(process.argv[1], 'utf8');
    function slice(a, b) {
      const i = src.indexOf(a), j = src.indexOf(b, i);
      if (i < 0 || j < 0) throw new Error('could not find ' + a);
      return src.slice(i, j);
    }
    eval(slice('  var MIME = {', '  function loadImage(f)'));
    const bytesOf = (arr) => new Uint8Array(arr);
    const textBytes = (s) => new Uint8Array([...s].map(c => c.charCodeAt(0)));
    """

    def run_js(self, script):
        proc = subprocess.run(["node", "-e", self.PRELUDE + script, str(PLANTRIM_JS)],
                              capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError("node failed: " + proc.stderr)
        return json.loads(proc.stdout)

    def test_an_svg_gets_a_type_that_renders(self):
        out = self.run_js("""
          console.log(JSON.stringify({
            decl: mimeFor(textBytes('<?xml version="1.0"?><svg/>'), 'SVG'),
            bare: mimeFor(textBytes('<svg xmlns="x"/>'), ''),
            bom: mimeFor(new Uint8Array([0xef,0xbb,0xbf,
                   ...textBytes('<svg  ')]), ''),
            spaced: mimeFor(textBytes(String.fromCharCode(10) +
                     '  <?xml version="1.0"?>'), ''),
          }));
        """)
        for key, mime in out.items():
            with self.subTest(case=key):
                self.assertEqual(mime, "image/svg+xml")

    def test_the_raster_formats_still_work(self):
        out = self.run_js("""
          console.log(JSON.stringify({
            png: mimeFor(bytesOf([0x89,0x50,0x4e,0x47,13,10,26,10]), 'PNG'),
            jpeg: mimeFor(bytesOf([0xff,0xd8,0xff,0xe0]), 'JPEG'),
            gif: mimeFor(textBytes('GIF89a'), 'GIF'),
          }));
        """)
        self.assertEqual(out["png"], "image/png")
        self.assertEqual(out["jpeg"], "image/jpeg")
        self.assertEqual(out["gif"], "image/gif")

    def test_the_bytes_beat_a_wrong_declaration(self):
        """Same rule as the extractor: what the file is, not what it claims."""
        out = self.run_js("""
          console.log(JSON.stringify({
            m: mimeFor(bytesOf([0x89,0x50,0x4e,0x47,13,10,26,10]), 'JPEG') }));
        """)
        self.assertEqual(out["m"], "image/png")

    def test_a_short_buffer_is_still_identified(self):
        """Guards count the bytes actually read, not the signature length."""
        out = self.run_js("""
          console.log(JSON.stringify({
            png: mimeFor(bytesOf([0x89,0x50,0x4e,0x47]), ''),
            jpeg: mimeFor(bytesOf([0xff,0xd8]), ''),
          }));
        """)
        self.assertEqual(out["png"], "image/png")
        self.assertEqual(out["jpeg"], "image/jpeg")

    def test_the_declaration_fills_in_when_the_bytes_say_nothing(self):
        out = self.run_js("""
          console.log(JSON.stringify({ m: mimeFor(bytesOf([1,2,3,4,5]), 'PNG') }));
        """)
        self.assertEqual(out["m"], "image/png")

    def test_an_unidentifiable_image_gets_no_type_rather_than_a_guess(self):
        out = self.run_js("""
          console.log(JSON.stringify({ m: mimeFor(bytesOf([1,2,3,4,5]), 'WBMP') }));
        """)
        self.assertEqual(out["m"], "")

    def test_the_editor_reads_the_declared_formats(self):
        js = PLANTRIM_JS.read_text(encoding="utf-8")
        self.assertIn("images.json", js)
        self.assertIn("format: formats[f.imageId]", js)
        self.assertIn("mimeFor(bytes, f.format)", js)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class WheelTests(unittest.TestCase):
    """Scrolling over the plan must zoom it, never scroll the page.

    Reported as "you can scroll over towards the bounding box and it scrolls the
    document". The handler existed and called preventDefault - but only after an
    early return for a floor whose image had not loaded, so on those the wheel
    fell straight through to the page. Same shape as the drag-handle bug: a
    handler that is present but never gets to act.
    """

    HARNESS = r"""
    const fs = require('fs');
    const src = fs.readFileSync(process.argv[1], 'utf8');
    function slice(a, b) {
      const i = src.indexOf(a), j = src.indexOf(b, i);
      if (i < 0 || j < 0) throw new Error('missing ' + a);
      return src.slice(i, j);
    }
    const DPR = 2;
    const stage = { classList:{add(){},remove(){},toggle(){}} };
    const ctx = new Proxy({}, { get: () => () => {} });
    const canvas = { width:1200*DPR, height:600*DPR, getContext:()=>ctx,
      getBoundingClientRect:()=>({left:0,top:0,width:1200,height:600}) };
    const els = { ptbCanvas: canvas, ptbStage: stage };
    const stub = () => ({ value:'', textContent:'', innerHTML:'', hidden:true,
      disabled:false, className:'', classList:{add(){},remove(){},toggle(){}} });
    globalThis.document = { getElementById: id => els[id] || (els[id]=stub()),
                            addEventListener(){} };
    globalThis.window = { devicePixelRatio: DPR, addEventListener(){} };
    globalThis.WD = { PanZoom:{ isPanGesture:()=>false, isHeld:()=>false,
                                onChange(){} }, toast(){}, esc:s=>String(s) };
    globalThis.$ = id => document.getElementById(id);
    globalThis.box = { boxes:{}, current:'f1', img:{width:5000,height:3750},
      view:{scale:1,x:0,y:0}, drag:null,
      floors:[{id:'f1',name:'L1',w:5000,h:3750}] };
    globalThis.draw=()=>{}; globalThis.updateReadout=()=>{};
    globalThis.persist=()=>{}; globalThis.reanalyze=()=>{};
    globalThis.showEvidence=()=>{};
    globalThis.floorById = id => box.floors.find(f=>f.id===id);
    eval(slice('  var HANDLE_HIT_CSS', '  var box = {'));
    eval(slice('  function toImage(px, py)', '  function fitView()'));
    eval(slice('  function handlePoints(x, y, w, h)', '  function updateReadout()'));
    eval(slice('  function clampBox(b, f)', '  function floorState(rep, id)'));
    const sc = Math.min(canvas.width/5000, canvas.height/3750) * 0.97;
    box.view = { scale: sc, x:(canvas.width-5000*sc)/2, y:(canvas.height-3750*sc)/2 };
    box.boxes.f1 = [1000, 800, 3200, 3000];
    function wheelAt(cx, cy) {
      let prevented = false;
      onWheel({ clientX:cx, clientY:cy, deltaY:-120,
                preventDefault(){ prevented = true; } });
      return prevented;
    }
    """

    def run_js(self, script):
        proc = subprocess.run(["node", "-e", self.HARNESS + script, str(PLANTRIM_JS)],
                              capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError("node failed: " + proc.stderr)
        return json.loads(proc.stdout)

    def test_the_page_never_scrolls_over_the_plan(self):
        out = self.run_js("""
          const mid = toScreen(2100, 1900), corner = toScreen(3200, 3000);
          const r = { empty: wheelAt(100, 60),
                      overBox: wheelAt(mid.x/DPR, mid.y/DPR),
                      overHandle: wheelAt(corner.x/DPR, corner.y/DPR) };
          box.img = null;
          r.noImage = wheelAt(300, 200);
          console.log(JSON.stringify(r));
        """)
        for where, prevented in out.items():
            with self.subTest(where=where):
                self.assertTrue(prevented, f"the wheel reached the page at {where}")

    def test_the_wheel_actually_zooms(self):
        out = self.run_js("""
          const before = box.view.scale;
          wheelAt(600, 300);
          console.log(JSON.stringify({ changed: box.view.scale !== before }));
        """)
        self.assertTrue(out["changed"])

    def test_zoom_stays_anchored_at_the_cursor(self):
        out = self.run_js("""
          const p = { x:1234, y:999 };
          const a = toScreen(p.x, p.y);
          wheelAt(a.x/DPR, a.y/DPR);
          const b = toScreen(p.x, p.y);
          console.log(JSON.stringify({ dx: Math.abs(a.x-b.x), dy: Math.abs(a.y-b.y) }));
        """)
        self.assertLess(out["dx"], 0.5)
        self.assertLess(out["dy"], 0.5)

    def test_fit_restores_the_view(self):
        js = PLANTRIM_JS.read_text(encoding="utf-8")
        self.assertIn("window.ptbFitView", js)
        self.assertIn("fitView();", js)


class ActionVisibilityTests(unittest.TestCase):
    """The verb has to be next to the thing it acts on, and be the only primary."""

    def setUp(self):
        self.html = PLANTRIM_HTML.read_text(encoding="utf-8")

    def test_there_is_a_cut_action_on_the_drawing_card(self):
        self.assertIn('id="ptbCut"', self.html)
        self.assertIn("Cut and save", self.html)

    def test_the_cut_action_sits_inside_the_box_card(self):
        card = self.html[self.html.index('id="ptBoxCard"'):]
        card = card[:card.index('id="ptResult"')]
        self.assertIn('id="ptbCut"', card, "the verb must live with the canvas")
        self.assertIn('id="ptbStage"', card)
        self.assertIn('id="ptbStrip"', card)

    def test_it_is_the_only_primary_button(self):
        """Suggest used to be the loudest control on the page."""
        self.assertEqual(self.html.count("btn-primary"), 1)
        suggest = self.html[self.html.index('id="ptbSuggest"'):]
        self.assertNotIn("btn-primary", suggest[:200])

    def test_the_action_row_is_pinned(self):
        self.assertIn(".ptb-actions", self.html)
        row = self.html[self.html.index(".ptb-actions {"):]
        self.assertIn("position: sticky", row[:300])

    def test_there_is_a_way_back_to_a_fitted_view(self):
        self.assertIn('id="ptbFit"', self.html)
        self.assertIn("ptbFitView()", self.html)

    def test_the_stage_leaves_room_for_its_controls(self):
        """72vh put the action below the fold on his laptop."""
        self.assertIn("min(58vh, 760px)", self.html)
        self.assertNotIn("min(72vh, 900px)", self.html)

    def test_firefox_gets_a_findable_scrollbar(self):
        self.assertIn("scrollbar-width: auto", self.html)
        self.assertIn("scrollbar-color:", self.html)

    def test_the_wheel_does_not_chain_to_the_page(self):
        self.assertIn("overscroll-behavior: contain", self.html)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class FloorStripTests(unittest.TestCase):
    """Where he is, and what every floor will do, beside the plan.

    His words: "there's no leading key that tells you what you're supposed to do
    next... it's not that complicated but it makes it complicated." The facts
    were all on the page - in a second card below the canvas, away from the
    thing they described - so nothing said which floors were settled or how much
    was left. His real case is the mixed one: automatic on floor 1, a drawn box
    on floor 2, with no way to see that either had registered.
    """

    HARNESS = r"""
    const fs = require('fs');
    const src = fs.readFileSync(process.argv[1], 'utf8');
    function slice(a, b) {
      const i = src.indexOf(a), j = src.indexOf(b, i);
      if (i < 0 || j < 0) throw new Error('missing ' + a);
      return src.slice(i, j);
    }
    const made = {};
    function el(id) {
      if (!made[id]) made[id] = { id, innerHTML:'', textContent:'', hidden:false,
        disabled:false, classList:{add(){},remove(){},toggle(){}} };
      return made[id];
    }
    globalThis.document = { getElementById: el, addEventListener(){} };
    globalThis.window = { devicePixelRatio:1, addEventListener(){} };
    globalThis.WD = { esc: s => String(s), toast(){},
      PanZoom:{ isPanGesture:()=>false, isHeld:()=>false, onChange(){} } };
    globalThis.$ = el;
    globalThis.box = { floors: [], current: null, boxes: {} };
    globalThis.draw=()=>{}; globalThis.updateReadout=()=>{};
    globalThis.showEvidence=()=>{};
    eval(slice('  function floorState(rep, id)',
               '  window.ptbSelectFloor = function (id)'));
    function mixedSet(n) {
      box.floors = Array.from({length:n}, (_,i) =>
        ({ id:'f'+(i+1), name:'Level '+(i+1), w:5000, h:3750 }));
      return { floors: box.floors.map((f,i) => {
        if (i === 1) return { id:f.id, action:'trimmed', source:'manual',
          oldSize:[5000,3750], newSize:[2207,2227], areaSavedPct:74 };
        if (i === n-2) return { id:f.id, action:'skipped',
          reason:'content already fills 100% of the canvas' };
        if (i === n-1) return { id:f.id, action:'refused',
          reason:'floor plan is geo-anchored' };
        return { id:f.id, action:'trimmed', source:'auto',
          oldSize:[5000,3750], newSize:[3275,2469], areaSavedPct:57 };
      })};
    }
    const strip = () => el('ptbStrip').innerHTML;
    const rows = () => strip().split('<button').filter(x => x.includes('data-floor'));
    const plain = t => t.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
    """

    def run_js(self, script):
        proc = subprocess.run(["node", "-e", self.HARNESS + script, str(PLANTRIM_JS)],
                              capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError("node failed: " + proc.stderr)
        return json.loads(proc.stdout)

    def test_it_says_which_floor_he_is_on(self):
        out = self.run_js("""
          const rep = mixedSet(14); box.current = 'f2'; renderStrip(rep);
          console.log(JSON.stringify({ where: el('ptbFloorCount').textContent }));
        """)
        self.assertEqual(out["where"], "Floor 2 of 14")

    def test_every_floor_says_what_it_will_do(self):
        out = self.run_js("""
          const rep = mixedSet(14); box.current = 'f1'; renderStrip(rep);
          const txt = rows().map(plain);
          console.log(JSON.stringify({ auto: txt[0], manual: txt[1],
                                       skip: txt[12], refused: txt[13] }));
        """)
        self.assertIn("Automatic", out["auto"])
        self.assertIn("Your box", out["manual"])
        self.assertIn("2207", out["manual"], "the drawn box result should be visible")
        self.assertIn("Nothing to do", out["skip"])
        self.assertIn("Cannot crop", out["refused"])

    def test_the_current_floor_is_marked(self):
        out = self.run_js("""
          const rep = mixedSet(14); box.current = 'f2'; renderStrip(rep);
          const r = rows();
          console.log(JSON.stringify({ cur: r[1].includes('is-current'),
                                       other: r[0].includes('is-current') }));
        """)
        self.assertTrue(out["cur"])
        self.assertFalse(out["other"])

    def test_a_drawn_box_reads_differently_from_automatic(self):
        """The confirmation he never got: floor 2 visibly differs from floor 1."""
        out = self.run_js("""
          const rep = mixedSet(14); box.current = 'f1'; renderStrip(rep);
          const r = rows();
          console.log(JSON.stringify({ manual: r[1].includes('is-manual'),
                                       auto: r[0].includes('is-auto') }));
        """)
        self.assertTrue(out["manual"])
        self.assertTrue(out["auto"])

    def test_every_floor_can_be_jumped_to(self):
        """No sequence and no locking - the strip reports, it does not gate."""
        out = self.run_js("""
          const rep = mixedSet(14); box.current = 'f1'; renderStrip(rep);
          console.log(JSON.stringify({ n: (strip().match(/data-floor=/g)||[]).length }));
        """)
        self.assertEqual(out["n"], 14)

    def test_next_floor_stops_at_the_last_one(self):
        out = self.run_js("""
          const rep = mixedSet(14);
          box.current = 'f1'; renderStrip(rep);
          const first = { label: el('ptbNext').textContent, off: el('ptbNext').disabled };
          box.current = 'f14'; renderStrip(rep);
          const last = { label: el('ptbNext').textContent, off: el('ptbNext').disabled };
          console.log(JSON.stringify({ first, last }));
        """)
        self.assertFalse(out["first"]["off"])
        self.assertIn("Next floor", out["first"]["label"])
        self.assertTrue(out["last"]["off"])

    def test_a_single_floor_project_carries_no_navigation(self):
        out = self.run_js("""
          box.floors = [{ id:'only', name:'Ground', w:1000, h:800 }];
          box.current = 'only';
          renderStrip({ floors:[{ id:'only', action:'trimmed', source:'auto',
            oldSize:[1000,800], newSize:[900,700], areaSavedPct:21 }] });
          console.log(JSON.stringify({ hidden: el('ptbNext').hidden,
                                       where: el('ptbFloorCount').textContent }));
        """)
        self.assertTrue(out["hidden"], "one floor needs no Next button")
        self.assertEqual(out["where"], "1 floor plan")

    def test_it_says_something_before_the_first_analyze(self):
        out = self.run_js("""
          box.floors = [{ id:'g0', name:'F0', w:10, h:10 }];
          box.current = 'g0'; renderStrip(null);
          console.log(JSON.stringify({ txt: plain(strip()) }));
        """)
        self.assertIn("Reading", out["txt"])


class NoDuplicateStateTests(unittest.TestCase):
    """The same facts in two places is how the flow came apart."""

    def test_the_second_floor_list_card_is_gone(self):
        html = PLANTRIM_HTML.read_text(encoding="utf-8")
        self.assertNotIn("What PlanTrim would do", html)

    def test_the_strip_lives_with_the_canvas(self):
        html = PLANTRIM_HTML.read_text(encoding="utf-8")
        card = html[html.index('id="ptBoxCard"'):]
        self.assertLess(card.index('id="ptbStrip"'), card.index('id="ptbStage"'),
                        "state belongs beside the plan it describes")

    def test_the_floor_dropdown_is_gone(self):
        html = PLANTRIM_HTML.read_text(encoding="utf-8")
        self.assertNotIn('id="ptbFloor"', html)


if __name__ == "__main__":
    unittest.main()
