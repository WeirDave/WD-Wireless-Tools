"""Capacity takes a headcount per floor.

One number used to go onto every floor, so a three-storey building for 600
people came out with 600 people's devices on each storey - 1,800 in all. Each
floor now takes its own number, the building number stays as the fallback for
any floor left blank, and 0 leaves a floor alone.

The writer tests drive `apply_to` and read the areas back out of the archive it
wrote, because the counts that matter are the ones Ekahau will open. The page
test runs the real `capacity.js`, takes the per-floor control back out of the
markup it rendered and calls what it names, then checks the request that
reaches the server.
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

from tools import capacity_profiles as cap  # noqa: E402
from test_capacity_profiles import FLOOR, FLOOR_2, build_esx  # noqa: E402
from delegated import DELEGATED_JS  # noqa: E402

CAPACITY_JS = ROOT / "web" / "assets" / "js" / "capacity.js"


def areas_by_floor(path):
    with zipfile.ZipFile(path) as zf:
        areas = json.loads(zf.read("areas.json")).get("areas", [])
    return {a["floorPlanId"]: a for a in areas if a.get("capacityItems")}


def devices(area):
    return sum(i["deviceCount"] for i in area["capacityItems"])


class PerFloorHeadcountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        src = Path(build_esx(self.dir / "src.esx"))
        self.tpl = cap.derive_template(cap.extract(src), 500, "Office")
        self.assertTrue(self.tpl["ok"], self.tpl.get("error"))
        # Two floors, nothing drawn on either, so both get written. The shared
        # fixture always puts an area on its second floor, so it is taken off.
        built = Path(build_esx(self.dir / "built.esx", areas=[], extra_floor=True))
        self.blank = self.dir / "blank.esx"
        with zipfile.ZipFile(built) as zin, zipfile.ZipFile(self.blank, "w") as zout:
            for name in zin.namelist():
                body = zin.read(name)
                if name == "areas.json":
                    body = json.dumps({"areas": []}).encode("utf-8")
                zout.writestr(name, body)

    def tearDown(self):
        self.tmp.cleanup()

    def expected(self, people):
        return cap.apply_headcount(self.tpl, people)["totalDevices"]

    def apply(self, occupants, floor_occupants=None):
        dest = self.dir / "out.esx"
        r = cap.apply_to(self.blank, dest, self.tpl, occupants,
                         floor_occupants=floor_occupants)
        self.assertTrue(r["ok"], r.get("error"))
        return r, dest

    def test_each_floor_gets_its_own_headcount(self):
        r, dest = self.apply(200, {FLOOR: 300, FLOOR_2: 40})
        got = areas_by_floor(dest)
        self.assertEqual(devices(got[FLOOR]), self.expected(300))
        self.assertEqual(devices(got[FLOOR_2]), self.expected(40))
        self.assertNotEqual(devices(got[FLOOR]), devices(got[FLOOR_2]))
        self.assertEqual(r["occupantsWritten"], 340)
        self.assertEqual(r["devicesWritten"], self.expected(300) + self.expected(40))

    def test_a_floor_left_blank_uses_the_building_number(self):
        _r, dest = self.apply(200, {FLOOR_2: 40, FLOOR: ""})
        got = areas_by_floor(dest)
        self.assertEqual(devices(got[FLOOR]), self.expected(200))
        self.assertEqual(devices(got[FLOOR_2]), self.expected(40))

    def test_without_per_floor_numbers_every_floor_gets_the_building_number(self):
        _r, dest = self.apply(200)
        got = areas_by_floor(dest)
        self.assertEqual(devices(got[FLOOR]), self.expected(200))
        self.assertEqual(devices(got[FLOOR_2]), self.expected(200))

    def test_zero_people_leaves_the_floor_alone(self):
        r, dest = self.apply(200, {FLOOR_2: 0})
        got = areas_by_floor(dest)
        self.assertIn(FLOOR, got)
        self.assertNotIn(FLOOR_2, got)
        self.assertEqual(r["floorsSkipped"], ["Level 2"])

    def test_every_floor_numbered_needs_no_building_number(self):
        _r, dest = self.apply("", {FLOOR: 120, FLOOR_2: 80})
        got = areas_by_floor(dest)
        self.assertEqual(devices(got[FLOOR]), self.expected(120))
        self.assertEqual(devices(got[FLOOR_2]), self.expected(80))

    def test_a_floor_without_a_number_still_needs_the_building_number(self):
        r = cap.plan_application(self.blank, self.tpl, "", floor_occupants={FLOOR: 120})
        self.assertFalse(r["ok"])

    def test_the_preview_says_what_the_writer_writes(self):
        per = {FLOOR: 300, FLOOR_2: 40}
        plan = cap.plan_application(self.blank, self.tpl, 200, floor_occupants=per)
        _r, dest = self.apply(200, per)
        got = areas_by_floor(dest)
        for f in plan["floors"]:
            self.assertEqual(f["totalDevices"], devices(got[f["floorPlanId"]]))
            self.assertTrue(f["occupantsOverridden"])

    def test_the_route_passes_the_per_floor_numbers_through(self):
        import server
        tpl = dict(self.tpl, _file="per-floor_capacitytemplate.json")
        orig = cap.list_templates
        cap.list_templates = lambda: {"templates": [tpl]}
        try:
            client = server.app.test_client()
            q = ("?name=blank.esx&template=per-floor_capacitytemplate.json&occupants=200"
                 "&replace=0&floorOccupants=" + json.dumps({FLOOR_2: 0}))
            r = client.post("/api/capacity/plan" + q, data=self.blank.read_bytes(),
                            headers={"X-WD-Wireless-Tools": "1"})
        finally:
            cap.list_templates = orig
        body = r.get_json()
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["willWrite"], 1)
        skipped = [f["floorPlanId"] for f in body["floors"] if f["skipped"]]
        self.assertEqual(skipped, [FLOOR_2])


# The real page, run in Node against a stub DOM and a recording fetch.
PAGE_HARNESS = DELEGATED_JS + r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
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
el('capHeadcount').value = '200';
global.document = { readyState: 'complete', getElementById: el,
                    createElement: () => ({ click() {}, remove() {} }),
                    body: { appendChild() {} } };
global.window = global;
global.WD = {
  esc: s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
  escAttr: s => String(s).replace(/&/g, '&amp;').replace(/'/g, '&#39;')
                         .replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
  toast() {},
};
const calls = [];
const PLAN = { ok: true, occupants: 200, totalDevices: 600, rows: [], perFloor: false,
  occupantsWritten: 400, devicesWritten: 1200, willWrite: 2, willSkip: 0,
  floors: [
    { floorPlanId: 'f-1', floorName: 'Level 1', mode: 'create', skipped: false,
      action: 'create', totalDevices: 600, basis: 'walls' },
    { floorPlanId: "f-'2", floorName: 'Level 2', mode: 'create', skipped: false,
      action: 'create', totalDevices: 600, basis: 'walls' },
  ] };
global.fetch = (url) => {
  calls.push(url);
  const body = url.indexOf('/templates') >= 0 ? { templates: [] }
    : url.indexOf('/analyze') >= 0 ? { ok: false, error: 'not under test' }
    : url.indexOf('/plan') >= 0 ? PLAN : { ok: true };
  return Promise.resolve({ json: () => Promise.resolve(body),
                           headers: { get: () => null } });
};
const flush = () => new Promise(r => setTimeout(r, 0));
const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function query(url) {
  const m = /[?&]floorOccupants=([^&]*)/.exec(url);
  return m ? JSON.parse(decodeURIComponent(m[1])) : null;
}
function last(kind) { return calls.filter(u => u.indexOf('/' + kind) >= 0).pop(); }

(async () => {
  eval(src);
  el('fileInput').files = [{ name: 'Invented.esx', arrayBuffer: () => Promise.resolve(new ArrayBuffer(4)) }];
  el('fileInput').listeners.change();
  for (let i = 0; i < 5; i++) await flush();
  window.capChoose('t_capacitytemplate.json');
  for (let i = 0; i < 5; i++) await flush();

  const html = el('capPlan').innerHTML;
  const hit = delegated(html, 'capFloorOccupants');
  check('each floor renders a per-floor headcount control', !!hit);
  check('the control reports on change, not per keystroke',
        hit && /data-action-change="call"/.test(hit.tag));
  check('the control passes its value', hit && /data-arg-value="1"/.test(hit.tag));
  check('the control names its floor', hit && hit.args[0] === 'f-1');
  check('the building number is shown as the fallback',
        hit && /placeholder="200"/.test(hit.tag));
  check('one control per floor', (html.match(/data-fn="capFloorOccupants"/g) || []).length === 2);
  check('the plan did not send per-floor numbers before any were typed',
        query(last('plan')) === null);

  // A floor id with an apostrophe must survive the attribute.
  const tags = html.match(/<input[^>]*data-fn="capFloorOccupants"[^>]*>/g) || [];
  const secondArg = tags[1] && delegated(tags[1], 'capFloorOccupants').args[0];
  check("a floor id with an apostrophe arrives intact: " + secondArg, secondArg === "f-'2");

  window[hit.fn].apply(null, hit.args.concat(['50']));
  await flush(); await flush();
  const sent = query(last('plan'));
  check('the typed number reaches the plan request: ' + JSON.stringify(sent),
        sent && sent['f-1'] === 50 && Object.keys(sent).length === 1);

  window[hit.fn].apply(null, [secondArg, '0']);
  await flush(); await flush();
  const both = query(last('plan'));
  check('0 is sent as 0, not dropped', both && both["f-'2"] === 0);

  el('capApplyBtn').textContent = 'Apply';
  window.capApply();
  await flush(); await flush();
  const applied = query(last('apply'));
  check('apply sends the same per-floor numbers the preview used',
        applied && applied['f-1'] === 50 && applied["f-'2"] === 0);

  window[hit.fn].apply(null, hit.args.concat(['']));
  await flush(); await flush();
  const cleared = query(last('plan'));
  check('clearing a floor hands it back to the building number',
        cleared && !('f-1' in cleared) && cleared["f-'2"] === 0);

  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class PerFloorControlTests(unittest.TestCase):
    def test_the_per_floor_box_reaches_the_server(self):
        r = subprocess.run(["node", "-e", PAGE_HARNESS, str(CAPACITY_JS)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=120)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())


if __name__ == "__main__":
    unittest.main()
