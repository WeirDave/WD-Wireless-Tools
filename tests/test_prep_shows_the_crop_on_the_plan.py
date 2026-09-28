"""Prep draws the plan with the crop on it, the way PlanTrim does.

Asked for as "show the map like we do in trim so we can see what we are
trimming". Before this, Prep's trim card was numbers only - "800x600 -> 242x212"
- which says how much goes and not which part.

Three pieces, each driven here rather than read:

* `/api/prep/image` hands a disk-opened project's floor image to the page,
  chosen by floor id out of floorPlans.json and nothing else;
* `mapKeptBox` turns the plan report's offset/newSize into a rectangle on the
  image actually displayed, including an SVG a browser renders at a size
  other than its coordinate space;
* the strip `renderMap` draws selects a floor through the real dispatcher
  attributes, with the handler that exists.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import server  # noqa: E402
from test_prep_pipeline import Image, make_esx  # noqa: E402

PREP_JS = ROOT / "web" / "assets" / "js" / "prep.js"
HDR = {"X-WD-Wireless-Tools": "1"}
NODE_TIMEOUT_S = 120


@unittest.skipIf(Image is None, "Pillow is required to build the fixture")
class TheFloorImageComesFromTheProjectOnDisk(unittest.TestCase):

    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        self.esx = make_esx(Path(self.tmp.name) / "Project.esx")
        self._picked = dict(server._PREP_PROJECT)
        server._PREP_PROJECT["path"] = str(self.esx)

    def tearDown(self):
        server._PREP_PROJECT.update(self._picked)
        self.tmp.cleanup()

    def image(self, floor):
        return self.client.post(f"/api/prep/image?floor={floor}", headers=HDR)

    def test_it_returns_that_floors_image_as_an_image(self):
        res = self.image("f1")
        self.assertEqual(res.status_code, 200)
        with zipfile.ZipFile(self.esx) as z:
            self.assertEqual(res.data, z.read("image-img1"))
        self.assertEqual(res.mimetype, "image/png")

    def test_it_is_served_sandboxed(self):
        """A CAD import is SVG, and SVG opened as a document runs script."""
        res = self.image("f1")
        self.assertEqual(res.headers["Content-Security-Policy"], "sandbox")
        self.assertEqual(res.headers["X-Content-Type-Options"], "nosniff")

    def test_an_svg_plan_is_labelled_as_one(self):
        svg = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'
        path = Path(self.tmp.name) / "Vector.esx"
        with zipfile.ZipFile(self.esx) as src, zipfile.ZipFile(path, "w") as dst:
            for n in src.namelist():
                dst.writestr(n, svg if n == "image-img1" else src.read(n))
        server._PREP_PROJECT["path"] = str(path)
        res = self.image("f1")
        self.assertEqual(res.mimetype, "image/svg+xml")

    def test_a_floor_that_is_not_in_the_project_is_refused(self):
        self.assertEqual(self.image("nope").status_code, 404)

    def test_the_request_cannot_name_an_archive_member(self):
        """Only a floor id is taken; a member name is just an unknown floor."""
        for probe in ("floorPlans.json", "image-img1", "../project.json"):
            self.assertEqual(self.image(probe).status_code, 404, probe)

    def test_nothing_is_served_without_a_project_opened_from_disk(self):
        server._PREP_PROJECT["path"] = None
        self.assertEqual(self.image("f1").status_code, 404)


PROBE = r"""
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


def node(body):
    r = subprocess.run(["node", "-e", PROBE + body, str(PREP_JS)],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout.strip().splitlines()[-1])


needs_node = unittest.skipUnless(shutil.which("node"), "Node.js is not installed")


@needs_node
class TheBoxLandsOnTheDrawing(unittest.TestCase):

    def box(self, floor, iw, ih):
        return node("eval(fn('function mapKeptBox(f, iw, ih) {'));"
                    f"console.log(JSON.stringify(mapKeptBox({json.dumps(floor)}, {iw}, {ih})));")

    TRIMMED = {"action": "trimmed", "oldSize": [800, 600],
               "newSize": [242, 212], "offset": [59, 29]}

    def test_a_raster_is_boxed_in_its_own_pixels(self):
        self.assertEqual(self.box(self.TRIMMED, 800, 600), [59, 29, 301, 241])

    def test_an_image_rendered_at_another_size_is_scaled(self):
        """An SVG whose root asks for twice its viewBox renders twice as big;
        the box has to follow it or it lands on the wrong part of the plan."""
        self.assertEqual(self.box(self.TRIMMED, 1600, 1200), [118, 58, 602, 482])

    def test_a_floor_that_is_not_cropped_has_no_box(self):
        for f in ({"action": "skipped", "oldSize": [800, 600]},
                  {"action": "refused", "reason": "geo-anchored"},
                  dict(self.TRIMMED, oldSize=[0, 600])):
            self.assertIsNone(self.box(f, 800, 600), f)


@needs_node
class TheFloorStripSelectsAFloor(unittest.TestCase):
    """The rows are delegated controls. Asserting the markup names
    `prepMapSelect` would pass with the handler deleted, so the handler is
    taken from the rendered row and called."""

    def test_clicking_a_row_selects_that_floor(self):
        out = node(r"""
const els = {};
function mk(id) { return els[id] || (els[id] = { id, hidden: true, innerHTML: '', textContent: '',
  children: [], classList: { toggle() {} } }); }
globalThis.document = { getElementById: mk };
const shown = [];
var map = { floors: [], current: null, images: {}, zip: null };
function $(id) { return mk(id); }
function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;'); }
function escAttr(s) { return esc(s).replace(/"/g,'&quot;'); }
function showMapFloor() { shown.push(map.current); }
eval(fn('function mapFloorState(f) {'));
eval(fn('function renderMap(t) {'));
const window = {};
eval(fn('window.prepMapSelect = function (id) {'));
renderMap({ floors: [
  { id: 'a', name: 'Ground', action: 'skipped', reason: 'content already fills it' },
  { id: 'b', name: 'Level 2', action: 'trimmed', oldSize: [800, 600], newSize: [200, 100], offset: [1, 2] },
]});
const opened = map.current;
const html = mk('prepMapStrip').innerHTML;
const rows = [...html.matchAll(/data-fn="([^"]+)" data-arg="([^"]+)"/g)].map(m => [m[1], m[2]]);
const [fnName, arg] = rows[0];
window[fnName](arg);
console.log(JSON.stringify({ opened, rows, now: map.current, shown,
                             visible: !mk('prepMap').hidden }));
""")
        self.assertTrue(out["visible"])
        self.assertEqual(out["opened"], "b", "opens on the floor that is being cropped")
        self.assertEqual(out["rows"], [["prepMapSelect", "a"], ["prepMapSelect", "b"]])
        self.assertEqual(out["now"], "a")
        self.assertEqual(out["shown"], ["b", "a"])

    def test_no_trim_step_hides_the_map(self):
        out = node(r"""
const els = {};
function mk(id) { return els[id] || (els[id] = { hidden: false, innerHTML: '' }); }
var map = { floors: [], current: null };
function $(id) { return mk(id); }
eval(fn('function renderMap(t) {'));
renderMap(null);
const a = mk('prepMap').hidden;
mk('prepMap').hidden = false;
renderMap({ error: 'cannot' });
console.log(JSON.stringify([a, mk('prepMap').hidden]));
""")
        self.assertEqual(out, [True, True])


if __name__ == "__main__":
    unittest.main()
