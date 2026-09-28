"""Running Capacity again sets the device count; it never adds to it.

Ekahau totals every capacity area on a floor. "Replace" used to rewrite only
the first capacity area it found, so a floor carrying two kept counting the
second, and every run stacked another layer of devices on top. A floor that
already has devices now takes one of three choices - keep, replace the counts
and keep the outline, or replace the counts and redraw the outline - and both
replacing choices clear the devices from every other capacity area on the
floor, so the floor total is exactly what was asked for.

Everything here is read back out of the archive the writer produced, because
the number that matters is the one Ekahau will add up.
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
from test_capacity_profiles import (  # noqa: E402
    FLOOR, FLOOR_2, LAPTOP, NORMAL, build_esx)
from delegated import DELEGATED_JS  # noqa: E402

CAPACITY_JS = ROOT / "web" / "assets" / "js" / "capacity.js"

BIG = [{"x": 100.0, "y": 100.0}, {"x": 900.0, "y": 100.0},
       {"x": 900.0, "y": 800.0}, {"x": 100.0, "y": 800.0}]
SMALL = [{"x": 150.0, "y": 150.0}, {"x": 300.0, "y": 150.0},
         {"x": 300.0, "y": 300.0}]


def items(n):
    return [{"deviceCount": n, "deviceProfileId": LAPTOP, "usageProfileId": NORMAL}]


def read_areas(path):
    with zipfile.ZipFile(path) as zf:
        return {a["id"]: a for a in json.loads(zf.read("areas.json"))["areas"]}


def floor_total(areas, floor_id):
    return sum(i["deviceCount"] for a in areas.values()
               if a.get("floorPlanId") == floor_id
               for i in a.get("capacityItems") or [])


class ExistingDevicesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        src = Path(build_esx(self.dir / "src.esx"))
        self.tpl = cap.derive_template(cap.extract(src), 500, "Office")
        self.assertTrue(self.tpl["ok"], self.tpl.get("error"))
        # One floor carrying two capacity areas: the shape that compounded.
        built = Path(build_esx(self.dir / "built.esx", areas=[], extra_floor=True))
        self.src = self.dir / "two-areas.esx"
        areas = [
            {"id": "big", "floorPlanId": FLOOR, "requirementId": "req-1",
             "name": "Drawn", "capacityItems": items(100), "area": BIG},
            {"id": "small", "floorPlanId": FLOOR, "requirementId": "req-1",
             "capacityItems": items(50), "area": SMALL},
            {"id": "upstairs", "floorPlanId": FLOOR_2, "requirementId": "req-1",
             "capacityItems": items(70), "area": BIG},
        ]
        with zipfile.ZipFile(built) as zin, zipfile.ZipFile(self.src, "w") as zout:
            for name in zin.namelist():
                body = zin.read(name)
                if name == "areas.json":
                    body = json.dumps({"areas": areas}).encode("utf-8")
                zout.writestr(name, body)

    def tearDown(self):
        self.tmp.cleanup()

    def expected(self, people):
        return cap.apply_headcount(self.tpl, people)["totalDevices"]

    def apply(self, src, name, **kw):
        dest = self.dir / name
        r = cap.apply_to(src, dest, self.tpl, 200, **kw)
        self.assertTrue(r["ok"], r.get("error"))
        return r, dest

    def test_replacing_sets_the_floor_to_the_new_number(self):
        r, dest = self.apply(self.src, "out.esx", existing="devices")
        got = read_areas(dest)
        self.assertEqual(floor_total(got, FLOOR), self.expected(200))
        self.assertEqual(floor_total(got, FLOOR_2), self.expected(200))
        self.assertEqual(got["small"]["capacityItems"], [])
        self.assertEqual(r["areasCleared"], 1)

    def test_running_it_twice_does_not_compound(self):
        _r, once = self.apply(self.src, "once.esx", existing="devices")
        _r, twice = self.apply(once, "twice.esx", existing="devices")
        for fid in (FLOOR, FLOOR_2):
            self.assertEqual(floor_total(read_areas(twice), fid), self.expected(200))

    def test_devices_only_keeps_every_outline(self):
        _r, dest = self.apply(self.src, "out.esx", existing="devices")
        got = read_areas(dest)
        self.assertEqual(got["big"]["area"], BIG)
        self.assertEqual(got["small"]["area"], SMALL)
        self.assertEqual(got["big"]["name"], "Drawn")

    def test_reshape_redraws_the_outline_from_the_walls(self):
        plan = cap.plan_application(self.src, self.tpl, 200, existing="reshape")
        drawn = [f for f in plan["floors"] if f["floorPlanId"] == FLOOR][0]["polygon"]
        r, dest = self.apply(self.src, "out.esx", existing="reshape")
        got = read_areas(dest)
        self.assertEqual(got["big"]["area"], [{"x": p["x"], "y": p["y"]} for p in drawn])
        self.assertNotEqual(got["big"]["area"], BIG)
        self.assertEqual(got["small"]["area"], SMALL)
        self.assertEqual(got["small"]["capacityItems"], [])
        self.assertEqual(floor_total(got, FLOOR), self.expected(200))
        self.assertEqual(r["areasReshaped"], 2)

    def test_keep_changes_nothing(self):
        r = cap.apply_to(self.src, self.dir / "out.esx", self.tpl, 200, existing="keep")
        self.assertTrue(r["ok"])
        self.assertIsNone(r["written"])

    def test_the_default_is_still_keep(self):
        plan = cap.plan_application(self.src, self.tpl, 200)
        self.assertEqual(plan["willWrite"], 0)
        self.assertEqual(plan["floorsWithDevices"], 2)

    def test_the_old_replace_flag_means_replace_devices(self):
        _r, dest = self.apply(self.src, "out.esx", replace_existing=True)
        got = read_areas(dest)
        self.assertEqual(floor_total(got, FLOOR), self.expected(200))
        self.assertEqual(got["big"]["area"], BIG)

    def test_each_floor_can_choose_for_itself(self):
        _r, dest = self.apply(self.src, "out.esx", existing="keep",
                              floor_existing={FLOOR_2: "devices"})
        got = read_areas(dest)
        self.assertEqual(floor_total(got, FLOOR), 150)       # kept: 100 + 50
        self.assertEqual(floor_total(got, FLOOR_2), self.expected(200))

    def test_the_preview_states_what_is_there_and_what_it_becomes(self):
        plan = cap.plan_application(self.src, self.tpl, 200, existing="devices")
        f = [x for x in plan["floors"] if x["floorPlanId"] == FLOOR][0]
        self.assertEqual(f["existingDevices"], 150)
        self.assertEqual(f["existingAreaCount"], 2)
        self.assertEqual(f["targetAreaId"], "big")
        self.assertEqual(f["clearAreaIds"], ["small"])
        self.assertIn("150", f["action"])
        self.assertIn(str(self.expected(200)), f["action"])

    def test_the_route_takes_the_choice(self):
        import server
        tpl = dict(self.tpl, _file="x_capacitytemplate.json")
        orig = cap.list_templates
        cap.list_templates = lambda: {"templates": [tpl]}
        try:
            client = server.app.test_client()
            q = ("?name=a.esx&template=x_capacitytemplate.json&occupants=200"
                 "&existing=keep&floorExisting=" + json.dumps({FLOOR: "reshape"}))
            r = client.post("/api/capacity/plan" + q, data=self.src.read_bytes(),
                            headers={"X-WD-Wireless-Tools": "1"})
        finally:
            cap.list_templates = orig
        body = r.get_json()
        self.assertTrue(body["ok"], body)
        choices = {f["floorPlanId"]: f["existingChoice"] for f in body["floors"]}
        self.assertEqual(choices, {FLOOR: "reshape", FLOOR_2: "keep"})


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
el('capExisting').value = 'keep';
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
const calls = [];
const PLAN = { ok: true, occupants: 200, totalDevices: 600, rows: [], perFloor: false,
  occupantsWritten: 0, devicesWritten: 0, willWrite: 0, willSkip: 1, floorsWithDevices: 1,
  floors: [
    { floorPlanId: 'f-1', floorName: 'Level 1', mode: 'replace', skipped: true,
      existingChoice: 'keep', existingDevices: 150, existingAreaCount: 2,
      action: 'keep', totalDevices: 600, basis: 'walls' },
  ] };
const SAVED = process.argv[2] || '';
global.fetch = (url) => {
  calls.push(url);
  const body = url.indexOf('/settings/get') >= 0
      ? { ok: true, settings: SAVED ? { capacity: { existing_devices: SAVED } } : {} }
    : url.indexOf('/templates') >= 0 ? { templates: [] }
    : url.indexOf('/analyze') >= 0 ? { ok: false, error: 'not under test' }
    : url.indexOf('/plan') >= 0 ? PLAN : { ok: true };
  return Promise.resolve({ json: () => Promise.resolve(body),
                           headers: { get: () => null } });
};
const flush = () => new Promise(r => setTimeout(r, 0));
const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function param(url, name) {
  const m = new RegExp('[?&]' + name + '=([^&]*)').exec(url);
  return m ? decodeURIComponent(m[1]) : null;
}
function last(kind) { return calls.filter(u => u.indexOf('/' + kind) >= 0).pop(); }

(async () => {
  eval(src);
  if (SAVED) {
    for (let i = 0; i < 5; i++) await flush();
    const want = ['keep', 'devices', 'reshape'].indexOf(SAVED) >= 0 ? SAVED : 'keep';
    check('the page opens on the saved default (' + want + '), not "' + el('capExisting').value + '"',
          el('capExisting').value === want);
    el('capExisting').value = 'keep';
    el('fileInput').files = [{ name: 'Second.esx', arrayBuffer: () => Promise.resolve(new ArrayBuffer(4)) }];
    el('fileInput').listeners.change();
    for (let i = 0; i < 5; i++) await flush();
    check('opening another project starts from the saved default again',
          el('capExisting').value === want);
    const hitSettings = calls.filter(u => u.indexOf('/settings/update') >= 0);
    check('the page never writes the setting', hitSettings.length === 0);
    if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
    process.exit(0);
  }
  el('fileInput').files = [{ name: 'Invented.esx', arrayBuffer: () => Promise.resolve(new ArrayBuffer(4)) }];
  el('fileInput').listeners.change();
  for (let i = 0; i < 5; i++) await flush();
  window.capChoose('t_capacitytemplate.json');
  for (let i = 0; i < 5; i++) await flush();

  const html = el('capPlan').innerHTML;
  check('a floor with devices says how many are there', /150<\/b> devices/.test(html));
  check('it warns that floors already have devices', /1 floor already has devices/.test(html));
  check('the building-wide choice is sent', param(last('plan'), 'existing') === 'keep');

  const hit = delegated(html, 'capFloorExisting');
  check('the floor offers its own choice', !!hit);
  check('the choice names its floor', hit && hit.args[0] === 'f-1');
  check('the choice passes its value', hit && /data-arg-value="1"/.test(hit.tag));
  check('it shows the current choice', /value="keep" selected/.test(html));

  window[hit.fn].apply(null, hit.args.concat(['reshape']));
  await flush(); await flush();
  const per = JSON.parse(param(last('plan'), 'floorExisting') || 'null');
  check('the floor choice reaches the plan: ' + JSON.stringify(per),
        per && per['f-1'] === 'reshape');

  el('capApplyBtn').textContent = 'Apply';
  window.capApply();
  await flush(); await flush();
  const applied = JSON.parse(param(last('apply'), 'floorExisting') || 'null');
  check('apply sends the same choice', applied && applied['f-1'] === 'reshape');

  el('capExisting').value = 'devices';
  window.capExistingAll('devices');
  await flush(); await flush();
  check('the building-wide choice resets the floors',
        param(last('plan'), 'floorExisting') === null
        && param(last('plan'), 'existing') === 'devices');

  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ExistingDevicesControlTests(unittest.TestCase):
    def run_page(self, saved=""):
        r = subprocess.run(["node", "-e", PAGE_HARNESS, str(CAPACITY_JS), saved],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=120)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())

    def test_the_choice_reaches_the_server(self):
        self.run_page()

    def test_the_page_opens_on_the_saved_default(self):
        """Settings → Capacity → Floors that already have devices."""
        self.run_page("devices")
        self.run_page("reshape")

    def test_a_saved_value_it_does_not_know_falls_back_to_keep(self):
        self.run_page("everything")


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheSettingsPageSavesIt(unittest.TestCase):
    """Settings → Capacity. Runs the real SP.save and reads the patch it sends."""

    def _patch(self, values):
        from test_one_control_per_setting_across_pages import SavingKeepsWhatItCannotSee
        return SavingKeepsWhatItCannotSee._save_patch(
            SavingKeepsWhatItCannotSee(), "ask", None, values, [])

    def test_the_chosen_default_is_written(self):
        for choice in ("keep", "devices", "reshape"):
            with self.subTest(choice=choice):
                patch = self._patch({"sCapExisting": choice})
                self.assertEqual(patch["capacity"]["existing_devices"], choice)

    def test_an_unrendered_select_keeps_what_is_saved(self):
        patch = self._patch({"sCapExisting": ""})
        self.assertEqual(patch["capacity"]["existing_devices"], "keep")


class TheSettingIsDeclaredAndDefaultsToKeep(unittest.TestCase):
    def test_it_ships_as_keep(self):
        from tools import settings as st
        self.assertEqual(st.DEFAULTS["capacity"]["existing_devices"], "keep")

    def test_the_registry_names_exactly_the_choices_the_writer_takes(self):
        reg = json.loads((ROOT / "web" / "assets" / "settings-registry.json")
                         .read_text(encoding="utf-8"))
        entry = [e for e in reg["settings"] if e.get("key") == "capacity.existing_devices"][0]
        self.assertEqual(set(entry["values"]), set(cap.EXISTING_CHOICES))
        self.assertEqual(entry["home"], "settings")


if __name__ == "__main__":
    unittest.main()
