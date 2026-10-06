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

# Property-shaped fixture, invented names. Extra fields (``status``, a
# reflection coefficient) must survive the clone untouched.
EXISTING_TYPE = {
    "id": "id-existing", "name": "Invented Hedge", "color": "#112233",
    "status": "CREATED", "lowerEdge": 0, "upperEdge": 2,
    "propagationProperties": [
        {"band": b, "attenuationFactor": 3, "reflectionCoefficient": 0.2}
        for b in ("FIVE", "SIX", "TWO")],
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
        self.assertEqual(plan["added"], ["Tree Canopy", "Shrubbery, Low Planting"])
        types = self.by_name(plan)

        canopy = types["Tree Canopy"]
        self.assertAlmostEqual(canopy["lowerEdge"], 9 * 0.3048, places=4)
        self.assertAlmostEqual(canopy["upperEdge"], 35 * 0.3048, places=4)
        att = {p["band"]: p["attenuationFactor"] for p in canopy["propagationProperties"]}
        for band, per_ft in {"TWO": 1.0, "FIVE": 1.3, "SIX": 1.5}.items():
            self.assertAlmostEqual(att[band], per_ft / 0.3048, places=3, msg=band)

        shrub = types["Shrubbery, Low Planting"]
        self.assertEqual(shrub["lowerEdge"], 0)
        self.assertAlmostEqual(shrub["upperEdge"], 4 * 0.3048, places=4)
        att = {p["band"]: p["attenuationFactor"] for p in shrub["propagationProperties"]}
        for band, per_ft in {"TWO": 1.2, "FIVE": 1.6, "SIX": 1.8}.items():
            self.assertAlmostEqual(att[band], per_ft / 0.3048, places=3, msg=band)

    def test_the_layout_comes_from_the_project_and_nothing_else_is_lost(self):
        canopy = self.by_name(self.plan([EXISTING_TYPE]))["Tree Canopy"]
        self.assertEqual(canopy["status"], "CREATED")
        self.assertTrue(all(p["reflectionCoefficient"] == 0.2
                            for p in canopy["propagationProperties"]))
        self.assertNotEqual(canopy["id"], EXISTING_TYPE["id"])

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

    def test_a_type_with_the_same_name_is_updated_and_keeps_its_id(self):
        stale = json.loads(json.dumps(EXISTING_TYPE))
        stale.update(id="id-mine", name="tree canopy ")
        plan = self.plan([EXISTING_TYPE, stale])
        self.assertEqual(plan["updated"], ["Tree Canopy"])
        self.assertEqual(plan["added"], ["Shrubbery, Low Planting"])
        updated = [t for t in plan["types"] if t["id"] == "id-mine"][0]
        self.assertEqual(updated["name"], "Tree Canopy")
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
        canopy, shrub = data["Tree Canopy"], data["Shrubbery, Low Planting"]
        self.assertEqual((canopy["lowerEdgeFt"], canopy["upperEdgeFt"]), (9, 35))
        self.assertEqual(canopy["attenuationDbPerFt"], {"TWO": 1.0, "FIVE": 1.3, "SIX": 1.5})
        self.assertEqual((shrub["lowerEdgeFt"], shrub["upperEdgeFt"]), (0, 4))
        self.assertEqual(shrub["attenuationDbPerFt"], {"TWO": 1.2, "FIVE": 1.6, "SIX": 1.8})


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
eval(slice('async function loadAreaTypes') + slice('function areaBlockReason')
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
        self.assertEqual(r["names"], ["Invented Hedge", "Tree Canopy", "Shrubbery, Low Planting"])

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
   + slice('function areaBlockReason') + slice('function renderAreaPanel'));
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
        for needle in ("Tree Canopy", "9\u201335 ft", "Shrubbery, Low Planting", "1.8"):
            self.assertIn(needle, html)
        self.assertEqual(self.r["before"]["count"], "1 area type")
        self.assertFalse(self.r["before"]["disabled"])


if __name__ == "__main__":
    unittest.main()
