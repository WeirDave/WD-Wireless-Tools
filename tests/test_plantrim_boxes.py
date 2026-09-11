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
        for ident in ("ptbFloor", "ptbCanvas", "ptbReadout", "ptbApplyAll",
                      "ptbClear", "ptbStage", "ptbHint", "ptBoxCard"):
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


if __name__ == "__main__":
    unittest.main()
