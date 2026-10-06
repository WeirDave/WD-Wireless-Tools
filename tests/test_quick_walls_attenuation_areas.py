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


# --- the page ---------------------------------------------------------------
#
# The whole attenuation-area section of walls.js is loaded into Node against a
# recording fake of the page, and driven through the controls' own handlers:
# each handler is pulled out of the markup the real render function produced
# (tests/delegated.py), not found by name.

PAGE_PRELUDE = r"""
const fs = require('fs');
globalThis.WDAreas = require(process.argv[1]);
const src = fs.readFileSync(process.argv[2], 'utf8');
const html = fs.readFileSync(process.argv[3], 'utf8');
eval(DELEGATED);

function between(a, b) {
  const i = src.indexOf(a), j = src.indexOf(b);
  if (i < 0 || j < 0) throw new Error('moved: ' + (i < 0 ? a : b));
  return src.slice(i, j);
}
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
const el = id => els[id] || (els[id] = {id, value: '', hidden: false, disabled: false,
  textContent: '', innerHTML: '', attrs: {}, classes: new Set(), focused: false,
  classList: {add(c) { els[id].classes.add(c); }, remove(c) { els[id].classes.delete(c); },
              toggle(c, on) { on ? els[id].classes.add(c) : els[id].classes.delete(c); }},
  setAttribute(k, v) { els[id].attrs[k] = v; }, focus() { els[id].focused = true; }});
globalThis.document = {getElementById: el};
const attr = x => String(x).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
  .replace(/</g, '&lt;').replace(/>/g, '&gt;');
globalThis.esc = attr; globalThis.escAttr = attr; globalThis.safeColor = c => c;

const toasts = []; globalThis.showToast = (m, k) => toasts.push([m, k || '']);
const confirms = []; let confirmAnswer = true;
globalThis.confirm = m => { confirms.push(m); return confirmAnswer; };
globalThis.renderAll = () => renderAreaPanel();
let uuid = 0; globalThis.crypto = {randomUUID: () => 'new-' + (++uuid)};

const calls = [];            // every request the page made to the server
let serverReply = body => ({ok: true, presets: PRESETS});
globalThis.fetch = async (url, init) => {
  const body = init && init.body ? JSON.parse(init.body) : {};
  calls.push({url, body});
  const reply = serverReply(url, body);
  return {json: async () => reply};
};

const members = {
  'attenuationAreaTypes.json': JSON.stringify({attenuationAreaTypes: TYPES}),
};
if (typeof DRAWN !== 'undefined') members['attenuationAreas.json'] = DRAWN;
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
globalThis.fileName = 'x.esx'; globalThis.wallTypes = [];
globalThis.areaMember = null; globalThis.areaDoc = null; globalThis.areaKey = null;
globalThis.areaTypes = []; globalThis.areaPresets = []; globalThis.areaDirty = false;
globalThis.areaEditing = -1; globalThis.areaUsage = {}; globalThis.areaUsageKnown = false;
globalThis.nativeSave = async () => 'saved'; globalThis.revealSourceFolder = () => {};

eval(between('async function areaPresetCall', '/* The footer says what Save will write')
   .replace(/^/, '')
   + slice('async function saveEsx'));
const G = n => eval(n);       // the page's own functions, by name
// The perFt / ftOf helpers are consts in the section, so they are in scope here.

// The control for `fn`, found in the markup the render produced, then run.
async function click(container, fn, ...more) {
  const hit = delegated(el(container).innerHTML, fn);
  if (!hit) throw new Error('no control in #' + container + ' names ' + fn);
  if (hit.disabled) return {disabled: true};
  const out = G(hit.fn)(...hit.args, ...more);
  if (out && out.then) await out;
  return {disabled: false, args: hit.args};
}
"""


def page(body: str, types=None, drawn=None, presets=None):
    """Run `body` in Node against the page; it must `console.log(JSON.stringify(..))`."""
    prelude = (f"const TYPES = {json.dumps(types if types is not None else [EXISTING_TYPE])};"
               f"const PRESETS = {json.dumps(presets if presets is not None else PRESET_LIST)};"
               f"const DELEGATED = {json.dumps(DELEGATED_JS)};")
    if drawn is not None:
        prelude += f"const DRAWN = {json.dumps(json.dumps(drawn))};"
    script = f"{prelude}{PAGE_PRELUDE}(async () => {{ try {{ {body} }} catch (e) {{ console.error(e.stack); process.exit(1); }} }})();"
    proc = subprocess.run(["node", "-e", script, str(AREAS_JS), str(WALLS_JS), str(WALLS_HTML)],
                          capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
    if proc.returncode != 0:
        raise AssertionError((proc.stdout + proc.stderr).strip())
    return json.loads(proc.stdout.strip().splitlines()[-1])


BUILTIN = {"name": "Invented Canopy", "color": "#102030", "lowerEdgeFt": 9, "upperEdgeFt": 35,
           "attenuationDbPerFt": {"TWO": 1, "FIVE": 1.3, "SIX": 1.5}, "builtin": True}
KEPT = {"name": "Invented Reeds", "color": "#405060", "lowerEdgeFt": 0, "upperEdgeFt": None,
        "attenuationDbPerFt": {"TWO": 0.5, "FIVE": 0.75, "SIX": 1.25}, "builtin": False}
PRESET_LIST = [BUILTIN, KEPT]
NODE = unittest.skipUnless(shutil.which("node"), "node is required")


@NODE
class SavingTests(unittest.TestCase):
    def test_a_save_writes_the_member_only_when_something_changed(self):
        r = page("""
          await loadAreaTypes();
          await G('saveEsx')();
          const untouched = 'attenuationAreaTypes.json' in written;
          await click('areasBody', 'x').catch(() => {});
          const hit = delegated(html, 'openAreaModal');
          G('openAreaModal')();
          el('aName').value = 'Invented Marsh';
          G('saveAreaType')();
          await G('saveEsx')();
          const out = JSON.parse(written['attenuationAreaTypes.json']);
          console.log(JSON.stringify({untouched, names: out.attenuationAreaTypes.map(t => t.name)}));
        """)
        self.assertFalse(r["untouched"])
        self.assertEqual(r["names"], ["Invented Hedge", "Invented Marsh"])

    def test_every_dialog_control_is_declared_in_the_page(self):
        r = page("""
          const reach = {};
          ['openAreaModal', 'saveAreaType', 'closeAreaModal', 'addAreaPresets']
            .forEach(fn => { const h = delegated(html, fn); reach[fn] = !!h && typeof G(fn) === 'function'; });
          console.log(JSON.stringify(reach));
        """)
        self.assertEqual(r, {"openAreaModal": True, "saveAreaType": True,
                             "closeAreaModal": True, "addAreaPresets": True})


@NODE
class TheDialogTests(unittest.TestCase):
    def test_add_refuses_a_duplicate_in_the_dialog_then_adds(self):
        r = page("""
          await loadAreaTypes();
          G('openAreaModal')();
          const opened = el('areaModal').classes.has('active');
          const title = el('aTitle').textContent;
          el('aName').value = 'invented hedge';
          G('saveAreaType')();
          const dup = {error: el('aError').textContent, shown: !el('aError').hidden,
                       open: el('areaModal').classes.has('active'), n: areaTypes.length, dirty: areaDirty};
          el('aName').value = 'Invented Reeds'; el('aUpper').value = ''; el('aTwo').value = '0.5';
          G('saveAreaType')();
          const added = areaTypes[areaTypes.length - 1];
          console.log(JSON.stringify({opened, title, dup, n: areaTypes.length, dirty: areaDirty,
            open: el('areaModal').classes.has('active'), hasUpper: 'upperEdge' in added,
            twoPerM: added.propagationProperties.find(p => p.band === 'TWO').attenuationFactor,
            toast: toasts[toasts.length - 1][0]}));
        """)
        self.assertTrue(r["opened"])
        self.assertEqual(r["title"], "Add Attenuation Area")
        self.assertIn("already has", r["dup"]["error"])
        self.assertTrue(r["dup"]["shown"] and r["dup"]["open"])
        self.assertEqual((r["dup"]["n"], r["dup"]["dirty"]), (1, False))
        self.assertEqual((r["n"], r["dirty"], r["open"]), (2, True, False))
        self.assertFalse(r["hasUpper"], "an empty upper edge is Auto")
        self.assertAlmostEqual(r["twoPerM"], 0.5 / 0.3048, places=3)
        self.assertIn("Save the .esx", r["toast"])

    def test_edit_opens_filled_in_feet_and_saves_the_change_keeping_the_id(self):
        drawn = dict(EXISTING_TYPE, id="id-feet", name="Invented Feet", lowerEdge=2.7432000000000003,
                     upperEdge=10.668, propagationProperties=[
                         {"band": b, "attenuationFactor": v, "reflectionCoefficient": 0.5,
                          "diffractionCoefficient": 11}
                         for b, v in (("TWO", 3.2808), ("SIX", 4.9213), ("FIVE", 4.2651))])
        r = page("""
          await loadAreaTypes();
          G('renderAreaPanel')();
          await click('areaList', 'editAreaType');
          const filled = ['aName', 'aColor', 'aLower', 'aUpper', 'aTwo', 'aFive', 'aSix']
            .map(id => el(id).value);
          const title = [el('aTitle').textContent, el('aSaveBtn').textContent];
          el('aFive').value = '2'; el('aName').value = 'Invented Feet 2';
          G('saveAreaType')();
          const t = areaTypes[0];
          console.log(JSON.stringify({filled, title, id: t.id, name: t.name, n: areaTypes.length,
            dirty: areaDirty, open: el('areaModal').classes.has('active'),
            lower: t.lowerEdge, five: t.propagationProperties.find(p => p.band === 'FIVE').attenuationFactor,
            two: t.propagationProperties.find(p => p.band === 'TWO').attenuationFactor}));
        """, types=[drawn])
        self.assertEqual(r["filled"], ["Invented Feet", "#112233", "9", "35", "1", "1.3", "1.5"])
        self.assertEqual(r["title"], ["Edit Attenuation Area", "Save"])
        self.assertEqual((r["id"], r["name"], r["n"]), ("id-feet", "Invented Feet 2", 1))
        self.assertTrue(r["dirty"] and not r["open"])
        self.assertAlmostEqual(r["five"], 2 / 0.3048, places=3)
        # Untouched values keep the exact numbers Ekahau stored.
        self.assertEqual(r["lower"], 2.7432000000000003)
        self.assertEqual(r["two"], 3.2808)

    def test_opening_and_saving_an_edit_changes_nothing(self):
        r = page("""
          await loadAreaTypes();
          G('renderAreaPanel')();
          await click('areaList', 'editAreaType');
          G('saveAreaType')();
          console.log(JSON.stringify({dirty: areaDirty, same: JSON.stringify(areaTypes) === JSON.stringify(TYPES),
            open: el('areaModal').classes.has('active'), toast: toasts[toasts.length - 1][0]}));
        """)
        self.assertFalse(r["dirty"])
        self.assertTrue(r["same"])
        self.assertFalse(r["open"])
        self.assertIn("Nothing changed", r["toast"])

    def test_edit_refuses_a_name_another_area_has_and_stays_open(self):
        other = dict(EXISTING_TYPE, id="id-other", name="Invented Other")
        r = page("""
          await loadAreaTypes();
          G('renderAreaPanel')();
          await click('areaList', 'editAreaType');
          el('aName').value = 'invented other';
          G('saveAreaType')();
          console.log(JSON.stringify({error: el('aError').textContent, open: el('areaModal').classes.has('active'),
            dirty: areaDirty, name: areaTypes[0].name}));
        """, types=[EXISTING_TYPE, other])
        self.assertIn("another attenuation area", r["error"])
        self.assertTrue(r["open"])
        self.assertFalse(r["dirty"])
        self.assertEqual(r["name"], "Invented Hedge")


@NODE
class DeleteTests(unittest.TestCase):
    USED = {"attenuationAreas": [{"id": "a1", "attenuationAreaTypeId": "id-existing", "floorPlanId": "f",
                                  "area": []}] * 3}

    def test_an_unused_type_is_removed_after_naming_it(self):
        r = page("""
          await loadAreaTypes();
          G('renderAreaPanel')();
          const hit = await click('areaList', 'deleteAreaType');
          console.log(JSON.stringify({disabled: hit.disabled, n: areaTypes.length, dirty: areaDirty,
            asked: confirms, inDoc: areaDoc.attenuationAreaTypes.length}));
        """, drawn={"attenuationAreas": []})
        self.assertFalse(r["disabled"])
        self.assertEqual((r["n"], r["dirty"], r["inDoc"]), (0, True, 0))
        self.assertEqual(len(r["asked"]), 1)
        self.assertIn("Invented Hedge", r["asked"][0])

    def test_a_type_that_drawn_areas_use_cannot_be_deleted_and_says_how_many(self):
        r = page("""
          await loadAreaTypes();
          G('renderAreaPanel')();
          const tag = el('areaList').innerHTML.match(/<button[^>]*deleteAreaType[^>]*>/)[0];
          const hit = await click('areaList', 'deleteAreaType');
          G('deleteAreaType')(0);          // even called directly, it refuses
          console.log(JSON.stringify({disabled: hit.disabled, title: (tag.match(/title="([^"]*)"/) || [])[1],
            n: areaTypes.length, dirty: areaDirty, asked: confirms.length,
            drawn: /drawn:<\\/span> 3/.test(el('areaList').innerHTML),
            toast: toasts[toasts.length - 1]}));
        """, drawn=self.USED)
        self.assertTrue(r["disabled"])
        self.assertIn("3 drawn areas use this type", r["title"])
        self.assertEqual((r["n"], r["dirty"], r["asked"]), (1, False, 0))
        self.assertTrue(r["drawn"])
        self.assertEqual(r["toast"][1], "error")

    def test_when_it_cannot_tell_what_is_drawn_it_will_not_delete(self):
        r = page("""
          await loadAreaTypes();
          G('renderAreaPanel')();
          const hit = await click('areaList', 'deleteAreaType');
          console.log(JSON.stringify({disabled: hit.disabled, known: areaUsageKnown, n: areaTypes.length}));
        """, drawn="not json")
        self.assertTrue(r["disabled"])
        self.assertFalse(r["known"])
        self.assertEqual(r["n"], 1)

    def test_declining_the_question_removes_nothing(self):
        r = page("""
          await loadAreaTypes();
          G('renderAreaPanel')();
          confirmAnswer = false;
          await click('areaList', 'deleteAreaType');
          console.log(JSON.stringify({n: areaTypes.length, dirty: areaDirty}));
        """, drawn={"attenuationAreas": []})
        self.assertEqual((r["n"], r["dirty"]), (1, False))


@NODE
class KeptPresetTests(unittest.TestCase):
    def test_keep_sends_the_type_in_feet_and_takes_the_servers_list_back(self):
        drawn = dict(EXISTING_TYPE, id="id-feet", name="Invented Feet", color="#aa5500", lowerEdge=0,
                     upperEdge=1.2192, propagationProperties=[
                         {"band": b, "attenuationFactor": v, "reflectionCoefficient": 0.5,
                          "diffractionCoefficient": 11}
                         for b, v in (("TWO", 3.937), ("SIX", 5.9055), ("FIVE", 5.2493))])
        r = page("""
          await loadAreaTypes();
          const before = areaPresets.length;
          serverReply = () => ({ok: true, presets: PRESETS.concat([{name: 'Invented Feet', builtin: false,
            color: '#AA5500', lowerEdgeFt: 0, upperEdgeFt: 4, attenuationDbPerFt: {TWO: 1.2, FIVE: 1.6, SIX: 1.8}}])});
          G('renderAreaPanel')();
          await click('areaList', 'keepAreaPreset');
          const save = calls.filter(c => /area_preset_save/.test(c.url));
          console.log(JSON.stringify({before, after: areaPresets.length, save: save.map(c => c.body),
            toast: toasts[toasts.length - 1][0], dirty: areaDirty,
            listed: /Invented Feet/.test(el('areaPresets').innerHTML)}));
        """, types=[drawn])
        self.assertEqual(r["save"], [{"preset": {
            "name": "Invented Feet", "color": "#aa5500", "lowerEdgeFt": 0, "upperEdgeFt": 4,
            "attenuationDbPerFt": {"TWO": 1.2, "FIVE": 1.6, "SIX": 1.8}}}])
        self.assertEqual((r["before"], r["after"]), (2, 3))
        self.assertTrue(r["listed"])
        self.assertFalse(r["dirty"], "keeping a preset must not change the project")
        self.assertIn("Kept", r["toast"])

    def test_a_refusal_from_the_server_is_shown_and_nothing_is_listed(self):
        r = page("""
          await loadAreaTypes();
          serverReply = () => ({ok: false, error: 'It is a built-in preset.'});
          G('renderAreaPanel')();
          await click('areaList', 'keepAreaPreset');
          console.log(JSON.stringify({n: areaPresets.length, toast: toasts[toasts.length - 1]}));
        """)
        self.assertEqual(r["n"], 2)
        self.assertEqual(r["toast"], ["It is a built-in preset.", "error"])

    def test_an_area_with_no_loss_at_a_band_cannot_be_kept(self):
        broken = dict(EXISTING_TYPE, propagationProperties=[
            {"band": "TWO", "attenuationFactor": 3, "reflectionCoefficient": 0.5, "diffractionCoefficient": 11}])
        r = page("""
          await loadAreaTypes();
          G('renderAreaPanel')();
          await click('areaList', 'keepAreaPreset');
          console.log(JSON.stringify({asked: calls.filter(c => /area_preset_save/.test(c.url)).length,
            toast: toasts[toasts.length - 1]}));
        """, types=[broken])
        self.assertEqual(r["asked"], 0)
        self.assertEqual(r["toast"][1], "error")

    def test_only_kept_presets_offer_remove_and_it_names_the_preset(self):
        r = page("""
          await loadAreaTypes();
          G('renderAreaPanel')();
          const html2 = el('areaPresets').innerHTML;
          const removes = (html2.match(/removeAreaPreset/g) || []).length;
          serverReply = () => ({ok: true, presets: [PRESETS[0]]});
          const hit = await click('areaPresets', 'removeAreaPreset');
          console.log(JSON.stringify({removes, args: hit.args, asked: confirms,
            del: calls.filter(c => /area_preset_delete/.test(c.url)).map(c => c.body), n: areaPresets.length}));
        """)
        self.assertEqual(r["removes"], 1, "the built-in preset must not offer Remove")
        self.assertEqual(r["args"], [1])
        self.assertEqual(r["del"], [{"name": "Invented Reeds"}])
        self.assertIn("Invented Reeds", r["asked"][0])
        self.assertEqual(r["n"], 1)

    def test_a_preset_card_adds_just_that_preset(self):
        r = page("""
          await loadAreaTypes();
          G('renderAreaPanel')();
          await click('areaPresets', 'addOneAreaPreset');
          console.log(JSON.stringify({names: areaTypes.map(t => t.name), dirty: areaDirty}));
        """)
        self.assertEqual(r["names"], ["Invented Hedge", "Invented Canopy"])
        self.assertTrue(r["dirty"])

    def test_preset_add_is_greyed_with_the_reason_when_the_project_cannot_take_it(self):
        r = page("""
          await loadAreaTypes();
          G('renderAreaPanel')();
          const hit = await click('areaPresets', 'addOneAreaPreset');
          console.log(JSON.stringify({disabled: hit.disabled, note: el('areaNote').textContent}));
        """, types=[])
        self.assertTrue(r["disabled"])
        self.assertIn("no attenuation area type", r["note"])


@NODE
class TheTabTests(unittest.TestCase):
    def test_the_tab_swaps_the_two_bodies_and_back(self):
        r = page("""
          G('switchWallsTab')('areas');
          const on = {walls: el('wallsBody').hidden, areas: el('areasBody').hidden, tab: el('tabAreas').attrs['aria-selected']};
          G('switchWallsTab')('walls');
          console.log(JSON.stringify({on, back: {walls: el('wallsBody').hidden, areas: el('areasBody').hidden}}));
        """)
        self.assertEqual(r["on"], {"walls": True, "areas": False, "tab": "true"})
        self.assertEqual(r["back"], {"walls": False, "areas": True})

    def test_the_project_list_shows_feet_and_per_foot_and_the_count(self):
        t = dict(EXISTING_TYPE, lowerEdge=0.9144, upperEdge=3.048)
        r = page("""
          await loadAreaTypes();
          G('renderAreaPanel')();
          console.log(JSON.stringify({list: el('areaList').innerHTML, presets: el('areaPresets').innerHTML,
            count: el('areaCount').textContent, add: el('areaAddBtn').disabled, neu: el('areaNewBtn').disabled}));
        """, types=[t])
        self.assertIn("Invented Hedge", r["list"])
        self.assertIn("0.91", r["list"])
        self.assertIn("3–10 ft", r["list"])
        for needle in ("Invented Canopy", "9–35 ft", "Invented Reeds", "0–ceiling", "built in", "kept by you"):
            self.assertIn(needle, r["presets"])
        self.assertEqual(r["count"], "1 area type")
        self.assertFalse(r["add"] or r["neu"])


if __name__ == "__main__":
    unittest.main()
