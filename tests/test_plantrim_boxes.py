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


if __name__ == "__main__":
    unittest.main()
