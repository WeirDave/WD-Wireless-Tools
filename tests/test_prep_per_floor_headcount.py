"""Prep takes a headcount per floor, the same way Capacity does.

Prep's requirement-area step put one headcount on every floor, so a building
of several storeys came out with the whole building's devices on each. It now
takes the per-floor numbers Capacity takes: blank uses the number above, a
number overrides it, 0 leaves the floor alone.

0 is the case with a trap in it. Prep re-measures a placeholder area that still
covers the whole plan by dropping it and relying on the writer to put a
tighter one in. The writer writes nothing on a floor with nobody on it, so a
floor set to 0 would have lost its area and its devices. It is left out of the
re-measure, and a test here builds exactly that project.
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
from delegated import DELEGATED_JS  # noqa: E402

PREP_JS = ROOT / "web" / "assets" / "js" / "prep.js"

# The fixture's plans are 2000 x 1500; this is the whole-canvas placeholder
# Prep writes on a plan with nothing to measure.
CANVAS = [{"x": 0.0, "y": 0.0}, {"x": 2000.0, "y": 0.0},
          {"x": 2000.0, "y": 1500.0}, {"x": 0.0, "y": 1500.0}]


def with_areas(built, dest, areas):
    with zipfile.ZipFile(built) as zin, zipfile.ZipFile(dest, "w") as zout:
        for name in zin.namelist():
            body = zin.read(name)
            if name == "areas.json":
                body = json.dumps({"areas": areas}).encode("utf-8")
            zout.writestr(name, body)
    return dest


def read_areas(path):
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read("areas.json"))["areas"]


def floor_total(areas, fid):
    return sum(i["deviceCount"] for a in areas if a.get("floorPlanId") == fid
               for i in a.get("capacityItems") or [])


class PrepPerFloorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        src = Path(build_esx(self.dir / "src.esx"))
        self.tpl = cap.derive_template(cap.extract(src), 500, "Office")
        self.assertTrue(self.tpl["ok"], self.tpl.get("error"))
        self.built = Path(build_esx(self.dir / "built.esx", areas=[], extra_floor=True))
        self.blank = with_areas(self.built, self.dir / "blank.esx", [])

    def tearDown(self):
        self.tmp.cleanup()

    def expected(self, people):
        return cap.apply_headcount(self.tpl, people)["totalDevices"]

    def run_prep(self, src, floor_occupants=None, occupants=200):
        dest = self.dir / "out.esx"
        r = prep_pipeline.run(src, dest=dest, steps=["areas"], template=self.tpl,
                              occupants=occupants, floor_occupants=floor_occupants)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["failed"], [])
        return r, dest

    def test_each_floor_gets_its_own_headcount(self):
        _r, dest = self.run_prep(self.blank, {FLOOR: 300, FLOOR_2: 40})
        areas = read_areas(dest)
        self.assertEqual(floor_total(areas, FLOOR), self.expected(300))
        self.assertEqual(floor_total(areas, FLOOR_2), self.expected(40))

    def test_without_per_floor_numbers_it_is_unchanged(self):
        _r, dest = self.run_prep(self.blank)
        areas = read_areas(dest)
        self.assertEqual(floor_total(areas, FLOOR), self.expected(200))
        self.assertEqual(floor_total(areas, FLOOR_2), self.expected(200))

    def test_zero_leaves_the_floor_without_an_area(self):
        _r, dest = self.run_prep(self.blank, {FLOOR_2: 0})
        areas = read_areas(dest)
        self.assertEqual(floor_total(areas, FLOOR), self.expected(200))
        self.assertFalse([a for a in areas if a["floorPlanId"] == FLOOR_2])

    def test_zero_does_not_drop_a_placeholder_it_will_not_replace(self):
        """The placeholder is whole-canvas and the floor now has walls, so
        re-measuring would normally take it. At 0 people it must stay."""
        placeholder = {"id": "ph", "floorPlanId": FLOOR, "requirementId": "req-1",
                       "capacityItems": [{"deviceCount": 77, "deviceProfileId": LAPTOP,
                                          "usageProfileId": NORMAL}],
                       "area": CANVAS}
        src = with_areas(self.built, self.dir / "ph.esx", [placeholder])
        stale = prep_pipeline.stale_placeholder_areas(prep_pipeline._members(src))
        self.assertEqual([s["areaId"] for s in stale], ["ph"],
                         "fixture no longer produces a placeholder to re-measure")

        plan = prep_pipeline.plan(src, steps=["areas"], template=self.tpl,
                                  occupants=200, floor_occupants={FLOOR: 0})
        floor = [f for f in plan["step"]["areas"]["floors"] if f["floorPlanId"] == FLOOR][0]
        self.assertTrue(floor["skipped"])

        _r, dest = self.run_prep(src, {FLOOR: 0})
        kept = [a for a in read_areas(dest) if a["id"] == "ph"]
        self.assertEqual(len(kept), 1, "the floor set to 0 lost its area")
        self.assertEqual(floor_total(read_areas(dest), FLOOR), 77)

    def test_the_preview_counts_each_floor(self):
        plan = prep_pipeline.plan(self.blank, steps=["areas"], template=self.tpl,
                                  occupants=200, floor_occupants={FLOOR_2: 40})
        a = plan["step"]["areas"]
        by = {f["floorPlanId"]: f["totalDevices"] for f in a["floors"]}
        self.assertEqual(by, {FLOOR: self.expected(200), FLOOR_2: self.expected(40)})
        self.assertEqual(a["occupantsWritten"], 240)

    def test_the_route_passes_the_numbers_through(self):
        import server
        tpl = dict(self.tpl, _file="x_capacitytemplate.json")
        orig = cap.list_templates
        cap.list_templates = lambda: {"templates": [tpl]}
        try:
            client = server.app.test_client()
            q = ("?name=blank.esx&steps=areas&retighten=1"
                 "&capacityTemplate=x_capacitytemplate.json&occupants=200"
                 "&floorOccupants=" + json.dumps({FLOOR_2: 0}))
            r = client.post("/api/prep/plan" + q, data=self.blank.read_bytes(),
                            headers={"X-WD-Wireless-Tools": "1"})
        finally:
            cap.list_templates = orig
        body = r.get_json()
        self.assertTrue(body["ok"], body)
        skipped = [f["floorPlanId"] for f in body["step"]["areas"]["floors"] if f["skipped"]]
        self.assertEqual(skipped, [FLOOR_2])


PAGE_HARNESS = DELEGATED_JS + r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
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
  esc: s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
  escAttr: s => String(s).replace(/&/g, '&amp;').replace(/'/g, '&#39;')
                         .replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
  toast() {}, applyVersions() {}, savedWallTemplateName: () => Promise.resolve(''),
  api: (action) => fetch('/api/' + action).then(r => r.json()),
};
const calls = [];
const PLAN = { ok: true, steps: ['areas'], step: { areas: {
  ok: true, willWrite: 2, willSkip: 0, occupants: 200, totalDevices: 600,
  occupantsWritten: 400, devicesWritten: 1200,
  floors: [
    { floorPlanId: 'f-1', floorName: 'Level 1', mode: 'create', skipped: false,
      action: 'create', totalDevices: 600, basis: 'walls' },
    { floorPlanId: "f-'2", floorName: 'Level 2', mode: 'create', skipped: false,
      action: 'create', totalDevices: 600, basis: 'walls' },
  ] } } };
global.fetch = (url) => {
  calls.push(url);
  const body = url.indexOf('/prep/plan') >= 0 ? PLAN
    : url.indexOf('templates') >= 0 ? { templates: [] }
    : { ok: true, settings: {} };
  return Promise.resolve({ json: () => Promise.resolve(body), ok: true, status: 200,
                           headers: { get: () => null } });
};
const flush = () => new Promise(r => setTimeout(r, 0));
const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function sent(url) {
  const m = /[?&]floorOccupants=([^&]*)/.exec(url || '');
  return m ? JSON.parse(decodeURIComponent(m[1])) : null;
}
function last(kind) { return calls.filter(u => u.indexOf('/prep/' + kind) >= 0).pop(); }

(async () => {
  eval(src);
  docListeners.DOMContentLoaded();
  for (let i = 0; i < 5; i++) await flush();
  el('fileInput').listeners.change({ target: { files: [{ name: 'Invented.esx',
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(4)) }], value: '' } });
  for (let i = 0; i < 8; i++) await flush();

  const html = el('prepPreview').innerHTML;
  const tags = html.match(/<input[^>]*data-fn="prepFloorOccupants"[^>]*>/g) || [];
  check('each floor renders a People on this floor box: ' + tags.length, tags.length === 2);
  const hit = tags[0] && delegated(tags[0], 'prepFloorOccupants');
  const second = tags[1] && delegated(tags[1], 'prepFloorOccupants');
  check('the box names its floor', hit && hit.args[0] === 'f-1');
  check("a floor id with an apostrophe arrives intact", second && second.args[0] === "f-'2");
  check('it reports on change and passes its value',
        hit && /data-action-change="call"/.test(hit.tag) && /data-arg-value="1"/.test(hit.tag));
  check('the number above is the fallback', hit && /placeholder="200"/.test(hit.tag));
  check('nothing per-floor is sent before anything is typed', sent(last('plan')) === null);
  check('the summary totals the floors being written', /1200 devices for 400 people/.test(html));

  window[hit.fn].apply(null, hit.args.concat(['50']));
  await flush(); await flush();
  window[second.fn].apply(null, second.args.concat(['0']));
  await flush(); await flush();
  const p = sent(last('plan'));
  check('the preview sends both floors: ' + JSON.stringify(p),
        p && p['f-1'] === 50 && p["f-'2"] === 0);

  window.prepRun();
  for (let i = 0; i < 5; i++) await flush();
  const r = sent(last('run'));
  check('prepare sends the same numbers: ' + JSON.stringify(r),
        r && r['f-1'] === 50 && r["f-'2"] === 0);

  window[hit.fn].apply(null, hit.args.concat(['']));
  await flush(); await flush();
  const c = sent(last('plan'));
  check('clearing a box hands the floor back to the number above',
        c && !('f-1' in c) && c["f-'2"] === 0);

  el('fileInput').listeners.change({ target: { files: [{ name: 'Other.esx',
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(4)) }], value: '' } });
  for (let i = 0; i < 8; i++) await flush();
  check('another project starts with no per-floor numbers', sent(last('plan')) === null);

  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class PrepPerFloorControlTests(unittest.TestCase):
    def test_the_box_reaches_the_server(self):
        r = subprocess.run(["node", "-e", PAGE_HARNESS, str(PREP_JS)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=120)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())


if __name__ == "__main__":
    unittest.main()
