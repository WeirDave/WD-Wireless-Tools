"""Capacity and Prep show the devices-per-person multiplier between people and devices.

A floor typed as 250 people on the shipped example template (3 devices per
person) came out as 750 devices, beside floors of 600 and 300. With only the
people and the devices on screen, that read as the per-floor number being
added to the building number. The arithmetic was right; the page never
showed the x3 that joins the two.

The plan here is built by the real `plan_application` from a synthetic
project and the shipped template, then drawn by the real `capacity.js` in
Node, so the multiplier on screen is the one the server works out and the
device count beside it is the one the file gets. Prep's requirement-area
step uses the same plan, and is checked the same way through `prep.js`.
"""
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

from tools import capacity_profiles as cap, prep_pipeline  # noqa: E402
from test_capacity_profiles import FLOOR, FLOOR_2, build_esx  # noqa: E402

CAPACITY_JS = ROOT / "web" / "assets" / "js" / "capacity.js"
PREP_JS = ROOT / "web" / "assets" / "js" / "prep.js"
EXAMPLE = ROOT / "templates" / "Office_Wi-Fi_6E_example_capacitytemplate.json"


def blank_two_floor_project(directory: Path) -> Path:
    built = Path(build_esx(directory / "built.esx", areas=[], extra_floor=True))
    blank = directory / "blank.esx"
    with zipfile.ZipFile(built) as zin, zipfile.ZipFile(blank, "w") as zout:
        for name in zin.namelist():
            body = zin.read(name)
            if name == "areas.json":
                body = json.dumps({"areas": []}).encode("utf-8")
            zout.writestr(name, body)
    return blank


HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const PLAN = JSON.parse(process.argv[2]);
const HEADCOUNT = process.argv[3];
const els = {};
function el(id) {
  if (!els[id]) els[id] = {
    id, innerHTML: '', textContent: '', value: '', checked: false, hidden: false,
    disabled: false, style: {}, files: [],
    classList: { add() {}, remove() {} },
    listeners: {}, addEventListener(t, f) { this.listeners[t] = f; }, click() {},
  };
  return els[id];
}
el('capHeadcount').value = HEADCOUNT;
global.document = { readyState: 'complete', getElementById: el,
                    createElement: () => ({ click() {}, remove() {} }),
                    body: { appendChild() {} } };
global.window = global;
global.WD = {
  esc: s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
  escAttr: s => String(s).replace(/&/g, '&amp;').replace(/'/g, '&#39;')
                         .replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
  toast() {},
  api: (action) => fetch('/api/' + action).then(r => r.json()),
};
global.fetch = (url) => {
  const body = url.indexOf('/templates') >= 0 ? { templates: [] }
    : url.indexOf('/analyze') >= 0 ? { ok: false, error: 'not under test' }
    : url.indexOf('/plan') >= 0 ? PLAN : { ok: true };
  return Promise.resolve({ json: () => Promise.resolve(body),
                           headers: { get: () => null } });
};
const flush = () => new Promise(r => setTimeout(r, 0));
(async () => {
  eval(src);
  el('fileInput').files = [{ name: 'Invented.esx', arrayBuffer: () => Promise.resolve(new ArrayBuffer(4)) }];
  el('fileInput').listeners.change();
  for (let i = 0; i < 5; i++) await flush();
  window.capChoose('t_capacitytemplate.json');
  for (let i = 0; i < 5; i++) await flush();
  process.stdout.write(JSON.stringify({ html: el('capPlan').innerHTML }));
  process.exit(0);
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


class TheServerReportsTheMultiplier(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.blank = blank_two_floor_project(self.dir)
        self.tpl = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_plan_carries_the_templates_devices_per_person(self):
        plan = cap.plan_application(self.blank, self.tpl, 200)
        self.assertTrue(plan["ok"], plan.get("error"))
        self.assertAlmostEqual(plan["devicesPerPerson"], 3.0)

    def test_the_written_counts_are_people_times_the_multiplier(self):
        dest = self.dir / "out.esx"
        r = cap.apply_to(self.blank, dest, self.tpl, 200, floor_occupants={FLOOR: 250})
        self.assertTrue(r["ok"], r.get("error"))
        self.assertAlmostEqual(r["devicesPerPerson"], 3.0)
        with zipfile.ZipFile(dest) as zf:
            areas = json.loads(zf.read("areas.json"))["areas"]
        got = {a["floorPlanId"]: sum(i["deviceCount"] for i in a["capacityItems"])
               for a in areas}
        # 250 x 3 and 200 x 3: the floor's own number replaces the building
        # number, it is never added to it (that would be 450 x 3 = 1350).
        self.assertEqual(got, {FLOOR: 750, FLOOR_2: 600})


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ThePageShowsTheMultiplier(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.blank = blank_two_floor_project(Path(self.tmp.name))
        self.tpl = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, headcount, floor_occupants=None):
        plan = cap.plan_application(self.blank, self.tpl, headcount,
                                    floor_occupants=floor_occupants)
        self.assertTrue(plan["ok"], plan.get("error"))
        r = subprocess.run(["node", "-e", HARNESS, str(CAPACITY_JS),
                            json.dumps(plan), str(headcount)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=120)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout)["html"]

    def test_each_floor_shows_people_times_devices_each(self):
        html = self.render(200, {FLOOR: 250})
        self.assertIn("250 people &times; 3 devices each = 750 devices", html)
        self.assertIn("200 people &times; 3 devices each = 600 devices", html)

    def test_the_building_total_shows_the_multiplier(self):
        html = self.render(200)
        self.assertIn("Per floor, 200 people &times; 3 devices each = 600 devices", html)

    def test_a_total_that_rounding_moved_is_not_shown_as_an_exact_sum(self):
        # 15 people: every row of the example lands on .5 and rounds up, so
        # the floor gets 48 devices, not 45. Writing "15 x 3 = 48" would be a
        # wrong sum on screen.
        html = self.render(15)
        self.assertIn("15 people &times; 3 devices each &asymp; 48 devices", html)
        self.assertNotIn("= 48 devices", html)


PREP_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const PLAN = JSON.parse(process.argv[2]);
const els = {};
function el(id) {
  if (!els[id]) els[id] = {
    id, innerHTML: '', textContent: '', value: '', checked: false, hidden: false,
    disabled: false, style: {}, files: [], title: '', options: [],
    classList: { add() {}, remove() {}, toggle() {} },
    listeners: {}, addEventListener(t, f) { this.listeners[t] = f; }, click() {},
    appendChild() {}, querySelector() { return null; }, querySelectorAll() { return []; },
    setAttribute() {}, removeAttribute() {},
  };
  return els[id];
}
el('prepStep-areas').checked = true;
el('prepOccupants').value = process.argv[3];
el('prepCapTpl').value = 'x_capacitytemplate.json';
const docListeners = {};
global.document = { readyState: 'complete', getElementById: el,
                    addEventListener(t, f) { docListeners[t] = f; },
                    createElement: () => el('_tmp' + Math.random()),
                    querySelectorAll: () => [], body: { appendChild() {} } };
global.window = global;
global.addEventListener = () => {};
global.URL = { createObjectURL: () => 'blob:x', revokeObjectURL() {} };
global.WD = {
  esc: s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
  escAttr: s => String(s).replace(/&/g, '&amp;').replace(/'/g, '&#39;')
                         .replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
  toast() {}, applyVersions() {}, savedWallTemplateName: () => Promise.resolve(''),
  api: (action) => fetch('/api/' + action).then(r => r.json()),
};
global.fetch = (url) => {
  const body = url.indexOf('/prep/plan') >= 0 ? PLAN
    : url.indexOf('templates') >= 0 ? { templates: [] }
    : { ok: true, settings: {} };
  return Promise.resolve({ json: () => Promise.resolve(body), ok: true, status: 200,
                           headers: { get: () => null } });
};
const flush = () => new Promise(r => setTimeout(r, 0));
(async () => {
  eval(src);
  docListeners.DOMContentLoaded();
  for (let i = 0; i < 5; i++) await flush();
  el('fileInput').listeners.change({ target: { files: [{ name: 'Invented.esx',
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(4)) }], value: '' } });
  for (let i = 0; i < 8; i++) await flush();
  window.prepStage('areas');
  process.stdout.write(JSON.stringify({ html: el('prepAreaFloors').innerHTML,
                                        strip: el('prepMapStrip').innerHTML }));
  process.exit(0);
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class PrepShowsTheMultiplier(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.blank = blank_two_floor_project(Path(self.tmp.name))
        self.tpl = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, headcount, floor_occupants=None):
        plan = prep_pipeline.plan(self.blank, steps=["areas"], template=self.tpl,
                                  occupants=headcount, floor_occupants=floor_occupants)
        self.assertTrue(plan["step"]["areas"]["ok"], plan["step"]["areas"].get("error"))
        self.assertAlmostEqual(plan["step"]["areas"]["devicesPerPerson"], 3.0)
        r = subprocess.run(["node", "-e", PREP_HARNESS, str(PREP_JS),
                            json.dumps(plan), str(headcount)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=120)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout)

    def test_each_floor_shows_people_times_devices_each(self):
        html = self.render(200, {FLOOR: 250})["html"]
        self.assertIn("250 people × 3 devices each = 750 devices", html)
        self.assertIn("200 people × 3 devices each = 600 devices", html)
        self.assertIn("1350 devices for 450 people at 3 devices each", html)

    def test_the_floor_strip_tooltip_shows_the_multiplier(self):
        strip = self.render(200, {FLOOR: 250})["strip"]
        self.assertIn('title="250 people × 3 devices each = 750 devices"', strip)

    def test_a_total_that_rounding_moved_is_not_shown_as_an_exact_sum(self):
        html = self.render(15)["html"]
        self.assertIn("15 people × 3 devices each ≈ 48 devices", html)
        self.assertNotIn("= 48 devices", html)


if __name__ == "__main__":
    unittest.main()
