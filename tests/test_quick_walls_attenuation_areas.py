"""Quick Walls adds outdoor attenuation area types, and writes them to the .esx.

The presets are the two he keeps needing outdoors - a tree canopy and low
planting - kept in feet and dB per foot as he measures them. Ekahau keeps
metres, so the numbers that matter are the converted ones, and they are
asserted here as results (what lands in the file), not as source text.

The project fixture is synthetic. Its layout is a guess at Ekahau's, which is
the point of the refusal test: the code copies the layout from a type the
project already carries instead of trusting this guess, so a project with no
such type must be refused rather than written to.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from delegated import DELEGATED_JS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AREAS_JS = ROOT / "web" / "assets" / "js" / "walls-areas.js"
WALLS_JS = ROOT / "web" / "assets" / "js" / "walls.js"
WALLS_HTML = ROOT / "web" / "walls.html"
PRESETS = ROOT / "web" / "assets" / "attenuation-area-presets.json"

NODE_TIMEOUT_S = 60

# Shaped like a stock type in a project drawn in Ekahau - a snake_case ``key``,
# bands in Ekahau's own TWO / SIX / FIVE order, no ``status`` - with invented
# values. Fields the code does not own (a reflection coefficient, anything
# else) must survive the clone untouched.
EXISTING_TYPE = {
    "id": "id-existing", "name": "Invented Hedge", "key": "invented_hedge",
    "color": "#112233", "lowerEdge": 0, "upperEdge": 2, "invented_extra": 7,
    "propagationProperties": [
        {"band": b, "attenuationFactor": 3, "reflectionCoefficient": 0.2,
         "diffractionCoefficient": 11}
        for b in ("TWO", "SIX", "FIVE")],
}


def node(script: str):
    prelude = (f"const A = require({json.dumps(str(AREAS_JS))});"
               f"const presets = {PRESETS.read_text(encoding='utf-8')}.presets;"
               "let n = 0; const newId = () => 'new-' + (++n);")
    proc = subprocess.run(["node", "-e", prelude + script], capture_output=True,
                          text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
    if proc.returncode != 0:
        raise AssertionError((proc.stdout + proc.stderr).strip())
    return json.loads(proc.stdout)


@unittest.skipUnless(shutil.which("node"), "node is required")
class PresetsLandInTheFileTests(unittest.TestCase):
    def plan(self, types):
        return node(f"console.log(JSON.stringify(A.addPresets("
                    f"{json.dumps(types)}, presets, newId)));")

    def by_name(self, plan):
        return {t["name"]: t for t in plan["types"]}

    def test_both_presets_are_added_in_metres_and_per_metre(self):
        plan = self.plan([EXISTING_TYPE])
        self.assertEqual(plan["added"], ["Tree Canopy", "Shrubbery/Low Plants"])
        types = self.by_name(plan)

        canopy = types["Tree Canopy"]
        self.assertAlmostEqual(canopy["lowerEdge"], 9 * 0.3048, places=4)
        self.assertAlmostEqual(canopy["upperEdge"], 35 * 0.3048, places=4)
        att = {p["band"]: p["attenuationFactor"] for p in canopy["propagationProperties"]}
        for band, per_ft in {"TWO": 1.0, "FIVE": 1.3, "SIX": 1.5}.items():
            self.assertAlmostEqual(att[band], per_ft / 0.3048, places=3, msg=band)

        shrub = types["Shrubbery/Low Plants"]
        self.assertEqual(shrub["lowerEdge"], 0)
        self.assertAlmostEqual(shrub["upperEdge"], 4 * 0.3048, places=4)
        att = {p["band"]: p["attenuationFactor"] for p in shrub["propagationProperties"]}
        for band, per_ft in {"TWO": 1.2, "FIVE": 1.6, "SIX": 1.8}.items():
            self.assertAlmostEqual(att[band], per_ft / 0.3048, places=3, msg=band)

    def test_new_types_take_the_presets_colour(self):
        types = self.by_name(self.plan([EXISTING_TYPE]))
        self.assertEqual({types["Tree Canopy"]["color"], types["Shrubbery/Low Plants"]["color"]},
                         {"#193300"})

    def test_the_layout_comes_from_the_project_and_nothing_else_is_lost(self):
        canopy = self.by_name(self.plan([EXISTING_TYPE]))["Tree Canopy"]
        self.assertEqual(canopy["invented_extra"], 7)
        self.assertTrue(all(p["reflectionCoefficient"] == 0.2
                            for p in canopy["propagationProperties"]))
        self.assertNotEqual(canopy["id"], EXISTING_TYPE["id"])

    def test_a_new_type_carries_no_key_because_ekahaus_custom_types_do_not(self):
        self.assertTrue(all("key" not in t for t in self.plan([EXISTING_TYPE])["types"][1:]))

    def test_existing_types_are_untouched_and_ids_are_unique(self):
        plan = self.plan([EXISTING_TYPE])
        self.assertEqual(plan["types"][0], EXISTING_TYPE)
        ids = [t["id"] for t in plan["types"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_a_second_run_changes_nothing(self):
        once = self.plan([EXISTING_TYPE])["types"]
        again = self.plan(once)
        self.assertEqual((again["added"], again["updated"], again["unchanged"]),
                         ([], [], 2))
        self.assertEqual(again["types"], once)

    def test_a_type_ekahau_already_holds_in_its_own_float_noise_is_unchanged(self):
        # Ekahau stores 9 ft as 2.7432000000000003 and 35 ft as 10.668.
        drawn = [EXISTING_TYPE, {
            "id": "id-canopy", "name": "Tree Canopy", "color": "#193300",
            "lowerEdge": 2.7432000000000003, "upperEdge": 10.668,
            "propagationProperties": [
                {"band": "TWO", "attenuationFactor": 3.2808, "reflectionCoefficient": 0.5, "diffractionCoefficient": 11},
                {"band": "SIX", "attenuationFactor": 4.9213, "reflectionCoefficient": 0.5, "diffractionCoefficient": 11},
                {"band": "FIVE", "attenuationFactor": 4.2651, "reflectionCoefficient": 0.5, "diffractionCoefficient": 11}]}]
        plan = self.plan(drawn)
        self.assertEqual((plan["added"], plan["updated"], plan["unchanged"]),
                         (["Shrubbery/Low Plants"], [], 1))

    def test_a_type_with_the_same_name_is_updated_and_keeps_its_id(self):
        stale = json.loads(json.dumps(EXISTING_TYPE))
        stale.update(id="id-mine", name="tree canopy ")
        plan = self.plan([EXISTING_TYPE, stale])
        self.assertEqual(plan["updated"], ["Tree Canopy"])
        self.assertEqual(plan["added"], ["Shrubbery/Low Plants"])
        updated = [t for t in plan["types"] if t["id"] == "id-mine"][0]
        # The name and colour he gave it in Ekahau are kept; only physics changes.
        self.assertEqual((updated["name"], updated["color"]), ("tree canopy ", "#112233"))
        self.assertAlmostEqual(updated["upperEdge"], 35 * 0.3048, places=4)

    def test_a_project_with_nothing_to_copy_is_refused_with_a_reason(self):
        for types in ([], [{"id": "x", "name": "No attenuation list"}]):
            with self.subTest(types=types):
                plan = self.plan(types)
                self.assertIn("error", plan)
                self.assertNotIn("types", plan)
                self.assertTrue(plan["error"].strip())

    def test_the_list_key_is_read_from_the_file_not_assumed(self):
        out = node("console.log(JSON.stringify(["
                   "A.listKey({attenuationAreaTypes: []}), A.listKey({a: [], b: []}),"
                   "A.listKey([]), A.findMember(['x.json', 'AttenuationAreaTypes.JSON'])]))")
        self.assertEqual(out, ["attenuationAreaTypes", None, None,
                               "AttenuationAreaTypes.JSON"])

    def test_presets_file_carries_the_numbers_as_given(self):
        data = {p["name"]: p for p in json.loads(PRESETS.read_text(encoding="utf-8"))["presets"]}
        canopy, shrub = data["Tree Canopy"], data["Shrubbery/Low Plants"]
        self.assertEqual((canopy["lowerEdgeFt"], canopy["upperEdgeFt"]), (9, 35))
        self.assertEqual(canopy["attenuationDbPerFt"], {"TWO": 1.0, "FIVE": 1.3, "SIX": 1.5})
        self.assertEqual((shrub["lowerEdgeFt"], shrub["upperEdgeFt"]), (0, 4))
        self.assertEqual(shrub["attenuationDbPerFt"], {"TWO": 1.2, "FIVE": 1.6, "SIX": 1.8})


@unittest.skipUnless(shutil.which("node"), "node is required")
class AddOneTypeTests(unittest.TestCase):
    def add(self, types, **spec):
        base = {"name": "Invented Reeds", "color": "#445566", "lowerEdgeFt": 0,
                "upperEdgeFt": 6, "attenuationDbPerFt": {"TWO": 0.5, "FIVE": 0.75, "SIX": 1.25}}
        base.update(spec)
        return node(f"console.log(JSON.stringify(A.addType({json.dumps(types)}, "
                    f"{json.dumps(base)}, newId)));")

    def test_it_is_added_in_metres_with_the_forms_values_and_no_key(self):
        out = self.add([EXISTING_TYPE])
        new = out["types"][1]
        self.assertEqual((new["name"], new["color"]), ("Invented Reeds", "#445566"))
        self.assertNotIn("key", new)
        self.assertAlmostEqual(new["upperEdge"], 6 * 0.3048, places=4)
        att = {p["band"]: p["attenuationFactor"] for p in new["propagationProperties"]}
        for band, per_ft in {"TWO": 0.5, "FIVE": 0.75, "SIX": 1.25}.items():
            self.assertAlmostEqual(att[band], per_ft / 0.3048, places=3, msg=band)
        self.assertEqual(new["invented_extra"], 7)
        self.assertEqual(out["types"][0], EXISTING_TYPE)

    def test_an_empty_upper_edge_means_auto_and_writes_no_upper_edge(self):
        new = self.add([EXISTING_TYPE], upperEdgeFt=None)["types"][1]
        self.assertNotIn("upperEdge", new)

    def test_it_refuses_with_a_reason_and_writes_nothing(self):
        cases = {
            "no name": dict(name="  "),
            "same name as one there": dict(name="invented hedge"),
            "upper below lower": dict(lowerEdgeFt=5, upperEdgeFt=2),
            "negative loss": dict(attenuationDbPerFt={"TWO": -1, "FIVE": 1, "SIX": 1}),
            "a missing band": dict(attenuationDbPerFt={"TWO": 1, "FIVE": None, "SIX": 1}),
        }
        for label, spec in cases.items():
            with self.subTest(label):
                out = self.add([EXISTING_TYPE], **spec)
                self.assertNotIn("types", out)
                self.assertTrue(out["error"].strip())

    def test_a_project_with_nothing_to_copy_is_refused(self):
        self.assertIn("error", self.add([]))


# The page: load a project that has the file, press Add, press Save, read the
# member back out of the archive that Save generated.
PAGE_PROBE = r"""
const fs = require('fs');
globalThis.WDAreas = require(process.argv[1]);
const src = fs.readFileSync(process.argv[2], 'utf8');
function slice(open) {
  const a = src.indexOf(open);
  if (a < 0) throw new Error('moved: ' + open);
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; } else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
const members = {'attenuationAreaTypes.json': JSON.stringify({attenuationAreaTypes: [EXISTING]})};
const written = {};
globalThis.esxZip = {
  files: members,
  file(name, body) {
    if (body === undefined) return members[name] === undefined ? null
      : {async: async () => members[name]};
    written[name] = body;
  },
  generateAsync: async () => 'blob',
};
globalThis.fileName = 'x.esx';
globalThis.wallTypes = [];
globalThis.areaMember = null; globalThis.areaDoc = null; globalThis.areaKey = null;
globalThis.areaTypes = []; globalThis.areaPresets = []; globalThis.areaDirty = false;
const toasts = [];
globalThis.showToast = (m) => toasts.push(m);
globalThis.document = {getElementById: () => null};
globalThis.fetch = async () => ({json: async () => PRESETS});
globalThis.crypto = {randomUUID: (() => { let i = 0; return () => 'u-' + (++i); })()};
globalThis.safeColor = c => c; globalThis.esc = x => x;
globalThis.renderAll = () => {}; globalThis.nativeSave = async () => 'saved';
globalThis.revealSourceFolder = () => {};
eval(slice('async function loadAreaTypes') + slice('function areaProjectBlock') + slice('function areaBlockReason')
   + slice('function addAreaPresets') + slice('async function saveEsx'));
globalThis.loadAreaTypes = loadAreaTypes; globalThis.areaBlockReason = areaBlockReason;
globalThis.addAreaPresets = addAreaPresets; globalThis.saveEsx = saveEsx;
(async () => {
  await loadAreaTypes();
  const before = areaBlockReason();
  await saveEsx();
  const savedUntouched = 'attenuationAreaTypes.json' in written;
  // The control is found in the real page and its own declared handler is the
  // one that runs, so a misnamed or missing data-fn is a failure here.
  const html = fs.readFileSync(process.argv[3], 'utf8');
  eval(DELEGATED);
  const hit = delegated(html, 'addAreaPresets');
  if (!hit) throw new Error('no control on walls.html names addAreaPresets');
  const reachable = typeof globalThis[hit.fn] === 'function';
  const order = html.indexOf('walls-areas.js') >= 0
    && html.indexOf('walls-areas.js') < html.indexOf('/assets/js/walls.js');
  globalThis[hit.fn].apply(null, hit.args);
  await saveEsx();
  const out = JSON.parse(written['attenuationAreaTypes.json']);
  console.log(JSON.stringify({before, savedUntouched, toasts, reachable, order,
    names: out.attenuationAreaTypes.map(t => t.name)}));
})().catch(e => { console.error(e.stack); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "node is required")
class ThePageAddsAndSavesTests(unittest.TestCase):
    def test_add_then_save_writes_the_member_and_unchanged_save_does_not(self):
        script = (f"const EXISTING = {json.dumps(EXISTING_TYPE)};"
                  f"const PRESETS = {PRESETS.read_text(encoding='utf-8')}.presets;"
                  f"const DELEGATED = {json.dumps(DELEGATED_JS)};{PAGE_PROBE}")
        # PAGE_PROBE reads argv[1]/argv[2]; PRESETS is the list the fetch stub returns.
        script = script.replace("fetch = async () => ({json: async () => PRESETS})",
                                "fetch = async () => ({json: async () => ({presets: PRESETS})})")
        proc = subprocess.run(["node", "-e", script, str(AREAS_JS), str(WALLS_JS), str(WALLS_HTML)],
                              capture_output=True, text=True, encoding="utf-8",
                              timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError((proc.stdout + proc.stderr).strip())
        r = json.loads(proc.stdout)
        self.assertEqual(r["before"], "", "Add must be available on a project that has the file")
        self.assertFalse(r["savedUntouched"], "Save rewrote the member although nothing changed")
        self.assertEqual(r["names"], ["Invented Hedge", "Tree Canopy", "Shrubbery/Low Plants"])

        self.assertTrue(r["reachable"], "the control's handler is not a function")
        self.assertTrue(r["order"], "walls.js uses WDAreas, so walls-areas.js must load first")


TAB_PROBE = r"""
const fs = require('fs');
globalThis.WDAreas = require(process.argv[1]);
const src = fs.readFileSync(process.argv[2], 'utf8');
function slice(open) {
  const a = src.indexOf(open);
  if (a < 0) throw new Error('moved: ' + open);
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; } else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
const els = {};
const el = id => els[id] || (els[id] = {id, hidden: false, innerHTML: '', textContent: '',
  disabled: false, attrs: {}, on: {},
  classList: {toggle(c, on) { els[id].on[c] = on; }},
  setAttribute(k, v) { els[id].attrs[k] = v; }});
globalThis.document = {getElementById: el};
globalThis.esc = x => String(x); globalThis.safeColor = c => c;
globalThis.esxZip = {};
globalThis.areaDoc = {}; globalThis.areaTypes = [EXISTING]; globalThis.areaPresets = PRESETS;
const consts = src.match(/const perFt = [^\n]*\nconst ftOf = [^\n]*\n/)[0];
eval(consts + slice('function switchWallsTab') + slice('function areaCard')
   + slice('function areaProjectBlock') + slice('function areaBlockReason') + slice('function renderAreaPanel'));
renderAreaPanel();
const before = {list: el('areaList').innerHTML, presets: el('areaPresets').innerHTML,
                count: el('areaCount').textContent, disabled: el('areaAddBtn').disabled};
switchWallsTab('areas');
const onAreas = {walls: el('wallsBody').hidden, areas: el('areasBody').hidden,
                 tab: el('tabAreas').attrs['aria-selected']};
switchWallsTab('walls');
console.log(JSON.stringify({before, onAreas, back: {walls: el('wallsBody').hidden,
  areas: el('areasBody').hidden}}));
"""


@unittest.skipUnless(shutil.which("node"), "node is required")
class TheTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = (f"const EXISTING = {json.dumps(dict(EXISTING_TYPE, lowerEdge=0.9144, upperEdge=3.048))};"
                  f"const PRESETS = {PRESETS.read_text(encoding='utf-8')}.presets;{TAB_PROBE}")
        proc = subprocess.run(["node", "-e", script, str(AREAS_JS), str(WALLS_JS)],
                              capture_output=True, text=True, encoding="utf-8",
                              timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError((proc.stdout + proc.stderr).strip())
        cls.r = json.loads(proc.stdout)

    def test_the_tab_swaps_the_two_bodies_and_back(self):
        self.assertEqual(self.r["onAreas"], {"walls": True, "areas": False, "tab": "true"})
        self.assertEqual(self.r["back"], {"walls": False, "areas": True})

    def test_the_project_list_shows_feet_and_per_foot(self):
        # 3 dB/m is 0.91 dB/ft; 0.9144 m and 3.048 m are 3 ft and 10 ft.
        html = self.r["before"]["list"]
        self.assertIn("Invented Hedge", html)
        self.assertIn("0.91", html)
        self.assertIn("3\u201310 ft", html)

    def test_presets_are_listed_with_their_numbers(self):
        html = self.r["before"]["presets"]
        for needle in ("Tree Canopy", "9\u201335 ft", "Shrubbery/Low Plants", "1.8"):
            self.assertIn(needle, html)
        self.assertEqual(self.r["before"]["count"], "1 area type")
        self.assertFalse(self.r["before"]["disabled"])


MODAL_PROBE = r"""
const fs = require('fs');
globalThis.WDAreas = require(process.argv[1]);
const src = fs.readFileSync(process.argv[2], 'utf8');
const html = fs.readFileSync(process.argv[3], 'utf8');
function slice(open) {
  const a = src.indexOf(open);
  if (a < 0) throw new Error('moved: ' + open);
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; } else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
eval(DELEGATED);
const els = {};
const el = id => els[id] || (els[id] = {id, value: '', hidden: false, textContent: '',
  focused: false, classes: new Set(),
  classList: {add(c) { els[id].classes.add(c); }, remove(c) { els[id].classes.delete(c); }},
  focus() { els[id].focused = true; }});
globalThis.document = {getElementById: el};
globalThis.areaDoc = {attenuationAreaTypes: []}; globalThis.areaKey = 'attenuationAreaTypes';
globalThis.areaTypes = [EXISTING]; globalThis.areaDoc.attenuationAreaTypes = areaTypes;
globalThis.areaDirty = false; globalThis.esxZip = {};
const toasts = []; globalThis.showToast = m => toasts.push(m);
globalThis.renderAll = () => {};
globalThis.crypto = {randomUUID: () => 'u-1'};
eval(slice('function areaProjectBlock') + slice('function openAreaModal')
   + slice('function closeAreaModal') + slice('function areaNumber') + slice('function saveAreaType'));
const reach = {};
['openAreaModal', 'saveAreaType', 'closeAreaModal'].forEach(fn => {
  const hit = delegated(html, fn);
  reach[fn] = !!hit && typeof eval(fn) === 'function';
});
const fn = (name) => eval(name);
const set = (id, v) => { el(id).value = v; };

const out = {reach};
fn('openAreaModal')();
out.opened = el('areaModal').classes.has('active');
out.defaults = [el('aLower').value, el('aUpper').value, el('aTwo').value];
// A duplicate name is explained in the dialog, which stays open.
set('aName', 'invented hedge');
fn('saveAreaType')();
out.dup = {error: el('aError').textContent, hidden: el('aError').hidden,
           open: el('areaModal').classes.has('active'), count: areaTypes.length, dirty: areaDirty};
// A valid one is added, the dialog closes, an empty upper edge is Auto.
set('aName', 'Invented Reeds'); set('aUpper', ''); set('aTwo', '0.5');
fn('saveAreaType')();
const added = areaTypes[areaTypes.length - 1];
out.ok = {count: areaTypes.length, dirty: areaDirty, open: el('areaModal').classes.has('active'),
          name: added.name, hasUpper: 'upperEdge' in added, id: added.id,
          twoDbPerM: added.propagationProperties.find(p => p.band === 'TWO').attenuationFactor,
          inDoc: areaDoc.attenuationAreaTypes === areaTypes, toast: toasts[toasts.length - 1]};
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node is required")
class TheAddDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = (f"const EXISTING = {json.dumps(EXISTING_TYPE)};"
                  f"const DELEGATED = {json.dumps(DELEGATED_JS)};{MODAL_PROBE}")
        proc = subprocess.run(["node", "-e", script, str(AREAS_JS), str(WALLS_JS),
                               str(WALLS_HTML)], capture_output=True, text=True,
                              encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError((proc.stdout + proc.stderr).strip())
        cls.r = json.loads(proc.stdout)

    def test_every_control_in_the_dialog_reaches_its_handler(self):
        self.assertEqual(self.r["reach"], {"openAreaModal": True, "saveAreaType": True,
                                           "closeAreaModal": True})

    def test_it_opens_with_sensible_defaults(self):
        self.assertTrue(self.r["opened"])
        self.assertEqual(self.r["defaults"], ["0", "", "1"])

    def test_a_refusal_is_explained_in_the_dialog_and_adds_nothing(self):
        d = self.r["dup"]
        self.assertIn("already has", d["error"])
        self.assertFalse(d["hidden"])
        self.assertTrue(d["open"])
        self.assertEqual((d["count"], d["dirty"]), (1, False))

    def test_a_valid_one_is_added_the_dialog_closes_and_save_will_write_it(self):
        ok = self.r["ok"]
        self.assertEqual((ok["count"], ok["dirty"], ok["open"]), (2, True, False))
        self.assertEqual(ok["name"], "Invented Reeds")
        self.assertFalse(ok["hasUpper"], "an empty upper edge is Auto")
        self.assertAlmostEqual(ok["twoDbPerM"], 0.5 / 0.3048, places=3)
        self.assertTrue(ok["inDoc"])
        self.assertIn("Save the .esx", ok["toast"])


if __name__ == "__main__":
    unittest.main()
