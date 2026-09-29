"""Prep takes the existing-devices choice, starting from the saved default.

Prep always kept a floor that already carried devices. It now has the same
Floors that already have devices dropdown as Capacity, starting on
Settings -> Capacity -> Floors that already have devices, and passes it through
the pipeline to the same writer - so replacing sets the floor to the new count
and clears the devices from any second capacity area on it, never adding to
what was there.

The pipeline tests read the counts back out of the prepared archive. The page
test runs the real prep.js against a stubbed settings/get and checks the
request that reaches the server.
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
from test_capacity_profiles import FLOOR, FLOOR_2, LAPTOP, NORMAL, build_esx  # noqa: E402
from test_prep_per_floor_headcount import CANVAS, with_areas, read_areas, floor_total  # noqa: E402
from delegated import DELEGATED_JS  # noqa: E402

PREP_JS = ROOT / "web" / "assets" / "js" / "prep.js"

BIG = [{"x": 100.0, "y": 100.0}, {"x": 900.0, "y": 100.0},
       {"x": 900.0, "y": 800.0}, {"x": 100.0, "y": 800.0}]
SMALL = [{"x": 150.0, "y": 150.0}, {"x": 300.0, "y": 150.0},
         {"x": 300.0, "y": 300.0}]


def items(n):
    return [{"deviceCount": n, "deviceProfileId": LAPTOP, "usageProfileId": NORMAL}]


class PrepExistingDevicesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        src = Path(build_esx(self.dir / "src.esx"))
        self.tpl = cap.derive_template(cap.extract(src), 500, "Office")
        self.assertTrue(self.tpl["ok"], self.tpl.get("error"))
        self.built = Path(build_esx(self.dir / "built.esx", areas=[], extra_floor=True))
        # FLOOR carries two capacity areas - the shape that used to compound.
        self.two = with_areas(self.built, self.dir / "two.esx", [
            {"id": "big", "floorPlanId": FLOOR, "requirementId": "req-1",
             "capacityItems": items(100), "area": BIG},
            {"id": "small", "floorPlanId": FLOOR, "requirementId": "req-1",
             "capacityItems": items(50), "area": SMALL},
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def expected(self, people):
        return cap.apply_headcount(self.tpl, people)["totalDevices"]

    def run_prep(self, src, name, **kw):
        dest = self.dir / name
        r = prep_pipeline.run(src, dest=dest, steps=["areas"], template=self.tpl,
                              occupants=200, **kw)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["failed"], [])
        return r, dest

    def test_keep_is_still_what_happens_when_nothing_is_chosen(self):
        _r, dest = self.run_prep(self.two, "out.esx")
        self.assertEqual(floor_total(read_areas(dest), FLOOR), 150)

    def test_replacing_sets_the_floor_to_the_new_number(self):
        _r, dest = self.run_prep(self.two, "out.esx", existing="devices")
        areas = read_areas(dest)
        self.assertEqual(floor_total(areas, FLOOR), self.expected(200))
        small = [a for a in areas if a["id"] == "small"][0]
        self.assertEqual(small["capacityItems"], [])
        self.assertEqual(small["area"], SMALL)

    def test_preparing_twice_does_not_compound(self):
        _r, once = self.run_prep(self.two, "once.esx", existing="devices")
        _r, twice = self.run_prep(once, "twice.esx", existing="devices")
        self.assertEqual(floor_total(read_areas(twice), FLOOR), self.expected(200))

    def test_reshape_redraws_the_outline(self):
        _r, dest = self.run_prep(self.two, "out.esx", existing="reshape")
        big = [a for a in read_areas(dest) if a["id"] == "big"][0]
        self.assertNotEqual(big["area"], BIG)

    def test_the_preview_says_replace(self):
        plan = prep_pipeline.plan(self.two, steps=["areas"], template=self.tpl,
                                  occupants=200, existing="devices")
        f = [x for x in plan["step"]["areas"]["floors"] if x["floorPlanId"] == FLOOR][0]
        self.assertFalse(f["skipped"])
        self.assertEqual(f["existingChoice"], "devices")

    def test_a_remeasured_placeholder_is_not_counted_twice(self):
        """Re-measuring removes the whole-canvas placeholder and writes a new
        area; with Replace chosen too, the floor must still end at one count."""
        src = with_areas(self.built, self.dir / "ph.esx", [
            {"id": "ph", "floorPlanId": FLOOR, "requirementId": "req-1",
             "capacityItems": items(77), "area": CANVAS}])
        _r, dest = self.run_prep(src, "out.esx", existing="devices")
        areas = read_areas(dest)
        self.assertEqual(floor_total(areas, FLOOR), self.expected(200))
        self.assertFalse([a for a in areas if a["id"] == "ph"])

    def test_the_route_passes_the_choice_through(self):
        import server
        tpl = dict(self.tpl, _file="x_capacitytemplate.json")
        orig = cap.list_templates
        cap.list_templates = lambda: {"templates": [tpl]}
        try:
            client = server.app.test_client()
            q = ("?name=two.esx&steps=areas&retighten=1"
                 "&capacityTemplate=x_capacitytemplate.json&occupants=200&existing=reshape")
            r = client.post("/api/prep/plan" + q, data=self.two.read_bytes(),
                            headers={"X-WD-Wireless-Tools": "1"})
        finally:
            cap.list_templates = orig
        body = r.get_json()
        self.assertTrue(body["ok"], body)
        f = [x for x in body["step"]["areas"]["floors"] if x["floorPlanId"] == FLOOR][0]
        self.assertEqual(f["existingChoice"], "reshape")


PAGE_HARNESS = DELEGATED_JS + r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const SAVED = process.argv[2] || '';
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
el('prepOccupants').value = '200';
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
  esc: s => String(s), escAttr: s => String(s).replace(/"/g, '&quot;'),
  toast() {}, applyVersions() {}, savedWallTemplateName: () => Promise.resolve(''),
  api: (action) => fetch('/api/' + action).then(r => r.json()),
};
const calls = [];
const PLAN = { ok: true, steps: ['areas'], step: { areas: {
  ok: true, willWrite: 1, willSkip: 0, occupants: 200, totalDevices: 600,
  occupantsWritten: 200, devicesWritten: 600,
  floors: [{ floorPlanId: 'f-1', floorName: 'Level 1', mode: 'replace', skipped: false,
             action: 'replace 150 devices with 600, keep the outline',
             totalDevices: 600, basis: 'walls' }] } } };
global.fetch = (url) => {
  calls.push(url);
  const body = url.indexOf('/settings/get') >= 0
      ? { ok: true, settings: SAVED ? { capacity: { existing_devices: SAVED } } : {} }
    : url.indexOf('/prep/plan') >= 0 ? PLAN
    : url.indexOf('templates') >= 0 ? { templates: [] }
    : { ok: true };
  return Promise.resolve({ json: () => Promise.resolve(body), ok: true, status: 200,
                           headers: { get: () => null } });
};
const flush = () => new Promise(r => setTimeout(r, 0));
const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function param(url, name) {
  const m = new RegExp('[?&]' + name + '=([^&]*)').exec(url || '');
  return m ? decodeURIComponent(m[1]) : null;
}
function last(kind) { return calls.filter(u => u.indexOf('/prep/' + kind) >= 0).pop(); }
function open(name) {
  el('fileInput').listeners.change({ target: { files: [{ name,
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(4)) }], value: '' } });
}

(async () => {
  eval(src);
  docListeners.DOMContentLoaded();
  for (let i = 0; i < 5; i++) await flush();
  const want = ['keep', 'devices', 'reshape'].indexOf(SAVED) >= 0 ? SAVED : 'keep';
  check('the dropdown starts on the saved default (' + want + '), not "'
        + el('prepExisting').value + '"', el('prepExisting').value === want);

  open('Invented.esx');
  for (let i = 0; i < 8; i++) await flush();
  check('the preview sends the saved choice: ' + param(last('plan'), 'existing'),
        param(last('plan'), 'existing') === want);

  el('prepExisting').value = 'reshape';
  window.prepSyncStepUi();
  for (let i = 0; i < 5; i++) await flush();
  check('changing the dropdown reaches the preview',
        param(last('plan'), 'existing') === 'reshape');

  window.prepRun();
  for (let i = 0; i < 5; i++) await flush();
  check('prepare sends the same choice', param(last('run'), 'existing') === 'reshape');

  open('Other.esx');
  for (let i = 0; i < 8; i++) await flush();
  check('another project starts from the saved default again',
        el('prepExisting').value === want && param(last('plan'), 'existing') === want);

  el('prepExisting').value = 'nonsense';
  window.prepSyncStepUi();
  for (let i = 0; i < 5; i++) await flush();
  check('an unknown value is sent as keep', param(last('plan'), 'existing') === 'keep');

  check('the page never writes the setting',
        !calls.some(u => u.indexOf('/settings/update') >= 0));

  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class PrepExistingDevicesControlTests(unittest.TestCase):
    def run_page(self, saved=""):
        r = subprocess.run(["node", "-e", PAGE_HARNESS, str(PREP_JS), saved],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=120)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())

    def test_with_nothing_saved_it_is_keep(self):
        self.run_page()

    def test_it_starts_on_the_saved_default(self):
        """Settings -> Capacity -> Floors that already have devices."""
        self.run_page("devices")
        self.run_page("reshape")

    def test_a_saved_value_it_does_not_know_falls_back_to_keep(self):
        self.run_page("everything")


if __name__ == "__main__":
    unittest.main()
