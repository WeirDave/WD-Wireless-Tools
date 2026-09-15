"""Applying a Quick Walls template adds; it does not delete.

Replacing the whole list is what it used to do, and it deleted every wall type
the template had no counterpart for. That is invisible until a project uses
one: on a real retail project, 92 segments were drawn with "Retail Shelf", the
template did not carry it, and the saved file came out with ten segments
pointing at a wall type that was no longer in it. Nothing said so. Measured
across 70 local projects that have walls drawn, the old behaviour would have
stranded walls in 11 of them, every time on a shelving type.

The rule now: a type the template carries is added, or updated in place if the
project already has it - keeping the id the project already uses, so walls drawn
with it still resolve. A type the template says nothing about is left alone.
Only the Ekahau Defaults button removes anything, and it asks first.

These drive the real merge out of walls.js rather than asserting on its source,
because the test this replaces asserted on source and stayed green throughout.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WALLS_JS = ROOT / "web" / "assets" / "js" / "walls.js"
WALLS_HTML = ROOT / "web" / "walls.html"
TEMPLATES = ROOT / "templates"

NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0) throw new Error('could not find ' + from);
  if (b < 0) throw new Error('could not find ' + to);
  return source.slice(a, b);
}
globalThis.wallTypes = [];
globalThis._originalIdMap = {};
globalThis.crypto = globalThis.crypto || { randomUUID: () => 'new-' + (++n) };
let n = 0;
eval(slice('function preserveId', '\nlet editingIndex'));
"""


def run_node(script: str) -> dict:
    proc = subprocess.run(["node", "-e", PRELUDE + script, str(WALLS_JS)],
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=NODE_TIMEOUT_S)
    if proc.returncode != 0:
        raise AssertionError("node failed:\n" + proc.stderr)
    return json.loads(proc.stdout)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class MergeTests(unittest.TestCase):

    PROJECT = """
      wallTypes = [
        { id: 'id-dry',   key: 'DRY_WALL', name: 'Dry Wall' },
        { id: 'id-conc',  key: 'CONCRETE', name: 'Concrete' },
        { id: 'id-shelf', name: 'Retail Shelf', lowerEdge: 0, upperEdge: 2.5 }
      ];
    """
    TEMPLATE = """
      const template = [
        { id: 't1', key: 'DRY_WALL', name: 'Wall, Dry' },
        { id: 't2', key: 'CONCRETE', name: 'Wall, Concrete' },
        { id: 't3', name: 'Framery Pod' }
      ];
    """

    def test_a_type_the_template_omits_is_kept(self):
        """The whole defect: Retail Shelf is not in the template, and the walls
        drawn with it must not be orphaned."""
        out = run_node(self.PROJECT + self.TEMPLATE + """
          const r = mergeTemplateTypes(template);
          console.log(JSON.stringify({
            ids: wallTypes.map(w => w.id),
            shelf: wallTypes.find(w => w.id === 'id-shelf') || null, r }));
        """)
        self.assertIn("id-shelf", out["ids"])
        self.assertEqual(out["shelf"]["name"], "Retail Shelf")
        self.assertEqual(out["shelf"]["upperEdge"], 2.5,
                         "its height has to survive too")

    def test_nothing_is_ever_removed(self):
        out = run_node(self.PROJECT + self.TEMPLATE + """
          const before = wallTypes.map(w => w.id);
          mergeTemplateTypes(template);
          const after = wallTypes.map(w => w.id);
          console.log(JSON.stringify({
            lost: before.filter(i => after.indexOf(i) < 0) }));
        """)
        self.assertEqual(out["lost"], [])

    def test_a_matching_type_keeps_the_id_the_project_uses(self):
        """Walls reference a type by id. Rename it all you like; change the id
        and every segment drawn with it is stranded."""
        out = run_node(self.PROJECT + self.TEMPLATE + """
          mergeTemplateTypes(template);
          const dry = wallTypes.find(w => w.key === 'DRY_WALL');
          console.log(JSON.stringify({ id: dry.id, name: dry.name }));
        """)
        self.assertEqual(out["id"], "id-dry", "the project's id must be kept")
        self.assertEqual(out["name"], "Wall, Dry", "the template's name applies")

    def test_a_type_the_project_lacks_is_added(self):
        out = run_node(self.PROJECT + self.TEMPLATE + """
          const r = mergeTemplateTypes(template);
          console.log(JSON.stringify({
            names: wallTypes.map(w => w.name), added: r.added, updated: r.updated }));
        """)
        self.assertIn("Framery Pod", out["names"])
        self.assertEqual(out["added"], 1)
        self.assertEqual(out["updated"], 2)

    def test_names_match_even_when_punctuation_differs(self):
        """"Dry Wall" and "drywall" are the same type; adding both would give
        him two entries for one material."""
        out = run_node("""
          wallTypes = [{ id: 'a', name: 'Dry Wall' }];
          mergeTemplateTypes([{ id: 'b', name: 'drywall' }]);
          console.log(JSON.stringify({ count: wallTypes.length, id: wallTypes[0].id }));
        """)
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["id"], "a")

    def test_applying_twice_changes_nothing_the_second_time(self):
        out = run_node(self.PROJECT + self.TEMPLATE + """
          mergeTemplateTypes(template);
          const once = wallTypes.length;
          const r = mergeTemplateTypes(template);
          console.log(JSON.stringify({ once, twice: wallTypes.length, r }));
        """)
        self.assertEqual(out["once"], out["twice"])
        self.assertEqual(out["r"]["added"], 0)

    def test_a_shortcut_belongs_to_one_type_only(self):
        """Two types holding [3] is a shortcut that does something different
        depending on which one Ekahau reads first."""
        out = run_node("""
          wallTypes = [{ id: 'old', name: 'Old Thing', keybindNumber: 3 }];
          mergeTemplateTypes([{ id: 't', name: 'New Thing', keybindNumber: 3 }]);
          console.log(JSON.stringify({
            holders: wallTypes.filter(w => w.keybindNumber === 3).map(w => w.name),
            old: wallTypes.find(w => w.id === 'old') }));
        """)
        self.assertEqual(out["holders"], ["New Thing"])
        self.assertNotIn("keybindNumber", out["old"],
                         "the displaced type loses the binding, not the type")


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class StockTypesAreLeftAsEkahauShipsThem(unittest.TestCase):
    """A template may add types; it may not quietly restyle the standard set.

    His rule, after finding that applying WD Template recoloured three wall
    types Ekahau ships: "I just want to add in the walls that we added, not
    change anything from the defaults. So if stuff has changed from the
    defaults, that's probably wrong."

    The recolour had got into the template because it was saved out of a
    project where those types had been changed once, and from there it
    travelled to every project the template was applied to. Nothing said so.
    """

    DEFAULTS = """
      globalThis._ekahauDefaults = { wallTypes: [
        { key: 'DRY_WALL', name: 'Dry Wall', color: '#D9D9D9' },
        { key: 'ElevatorShaft', name: 'Elevator Shaft', color: '#5A5A5A' }
      ] };
    """

    def test_a_stock_type_is_not_recoloured(self):
        out = run_node(self.DEFAULTS + """
          wallTypes = [{ id: 'id-lift', key: 'ElevatorShaft',
                         name: 'Elevator Shaft', color: '#5A5A5A' }];
          const r = mergeTemplateTypes([{ id: 't', key: 'ElevatorShaft',
                         name: 'Elevator Shaft', color: '#5fab4f' }]);
          console.log(JSON.stringify({ color: wallTypes[0].color, r }));
        """)
        self.assertEqual(out["color"], "#5A5A5A")
        self.assertEqual(out["r"]["updated"], 0)
        self.assertEqual(out["r"]["kept"], ["Elevator Shaft"])

    def test_what_was_left_alone_is_reported_not_swallowed(self):
        """Silently ignoring half a template is its own kind of wrong."""
        js = WALLS_JS.read_text(encoding="utf-8")
        self.assertIn("keptPhrase", js)
        body = js[js.index("async function applySelectedTemplate"):]
        body = body[:body.index("async function tryAutoApply")]
        self.assertIn("keptPhrase(kept)", body)

    def test_a_custom_type_is_still_updated(self):
        """The template is authoritative for the types he added - that is what
        a template is for. Only the standard set is protected."""
        out = run_node(self.DEFAULTS + """
          wallTypes = [{ id: 'id-pod', name: 'Framery Pod', color: '#111111' }];
          const r = mergeTemplateTypes([{ id: 't', name: 'Framery Pod',
                                          color: '#222222' }]);
          console.log(JSON.stringify({ color: wallTypes[0].color, r }));
        """)
        self.assertEqual(out["color"], "#222222")
        self.assertEqual(out["r"]["updated"], 1)
        self.assertEqual(out["r"]["kept"], [])

    def test_the_ekahau_defaults_template_may_still_write_stock_types(self):
        """Putting the stock values back is the whole point of that one."""
        out = run_node(self.DEFAULTS + """
          wallTypes = [{ id: 'id-lift', key: 'ElevatorShaft',
                         name: 'Elevator Shaft', color: '#5fab4f' }];
          const r = mergeTemplateTypes(_ekahauDefaults.wallTypes,
                                       { fromDefaults: true });
          const lift = wallTypes.find(w => w.key === 'ElevatorShaft');
          console.log(JSON.stringify({ color: lift.color, id: lift.id, r }));
        """)
        self.assertEqual(out["color"], "#5A5A5A")
        self.assertEqual(out["id"], "id-lift", "the project's id is still kept")
        self.assertEqual(out["r"]["kept"], [])

    def test_an_identical_stock_type_is_not_reported_as_kept(self):
        """Nothing was refused, so nothing is announced."""
        out = run_node(self.DEFAULTS + """
          wallTypes = [{ id: 'id-lift', key: 'ElevatorShaft',
                         name: 'Elevator Shaft', color: '#5A5A5A' }];
          const r = mergeTemplateTypes([{ id: 't', key: 'ElevatorShaft',
                         name: 'Elevator Shaft', color: '#5A5A5A' }]);
          console.log(JSON.stringify({ r }));
        """)
        self.assertEqual(out["r"]["kept"], [])

    def test_a_stock_type_the_project_does_not_have_is_still_added(self):
        """The guard is about not changing what is there, not about refusing
        to complete the standard set."""
        out = run_node(self.DEFAULTS + """
          wallTypes = [];
          const r = mergeTemplateTypes([{ id: 't', key: 'ElevatorShaft',
                         name: 'Elevator Shaft', color: '#5fab4f' }]);
          console.log(JSON.stringify({ n: wallTypes.length, r }));
        """)
        self.assertEqual(out["n"], 1)
        self.assertEqual(out["r"]["added"], 1)


class ShippedTemplateTests(unittest.TestCase):
    """What WD Template carries, since the merge makes its contents the whole
    of what applying it does."""

    @staticmethod
    def _types(name):
        return json.loads((TEMPLATES / name).read_text(encoding="utf-8"))["wallTypes"]

    @staticmethod
    def _key(w):
        k = (w.get("key") or "").strip()
        return k or "".join(c for c in (w.get("name") or "").lower() if c.isalnum())

    def test_wd_template_still_carries_every_ekahau_default(self):
        """He has not changed the defaults, only added to them - so the
        template has to be a superset, or applying it would look like it
        dropped something even though the merge keeps it."""
        ek = {self._key(w) for w in self._types("ekahau_defaults.json")}
        wd = {self._key(w) for w in self._types("WD Template_walltemplate.json")}
        self.assertEqual(ek - wd, set(),
                         "Ekahau defaults missing from WD Template")

    def test_wd_template_does_not_deviate_from_the_stock_types(self):
        """Three colours had drifted. The merge guard would now stop them
        landing, but a template that carries a wrong value is still wrong -
        anyone reading it would take those colours for his house standard.
        """
        ek = {self._key(w): w for w in self._types("ekahau_defaults.json")}
        drift = []
        for w in self._types("WD Template_walltemplate.json"):
            o = ek.get(self._key(w))
            if not o:
                continue
            for f in ("name", "color", "attenuationFactor", "thickness",
                      "upperEdge", "lowerEdge"):
                if f in w and w.get(f) != o.get(f):
                    drift.append("%s.%s = %r, Ekahau ships %r"
                                 % (w.get("name"), f, w.get(f), o.get(f)))
        self.assertEqual(drift, [], "; ".join(drift))

    def test_wd_template_carries_his_own_additions(self):
        wd = {w["name"] for w in self._types("WD Template_walltemplate.json")}
        for name in ("Framery Pod", "Warehouse Rack Wall - 12ft",
                     "Warehouse Rack Wall - 16ft"):
            self.assertIn(name, wd)


class ResetIsTheOnlyDestructiveActionTests(unittest.TestCase):
    def test_the_reset_button_still_exists_and_is_separate(self):
        html = WALLS_HTML.read_text(encoding="utf-8")
        self.assertIn("resetToEkahauDefaults()", html)

    def test_the_reset_says_what_it_will_remove(self):
        """It is the one action that deletes wall types, so it names them
        before doing it rather than after."""
        js = WALLS_JS.read_text(encoding="utf-8")
        body = js[js.index("function resetToEkahauDefaults"):]
        body = body[:body.index("\n}")]
        self.assertIn("will be removed", body)
        self.assertIn("confirm(", body)

    def test_applying_a_template_no_longer_replaces_the_list(self):
        js = WALLS_JS.read_text(encoding="utf-8")
        body = js[js.index("async function applySelectedTemplate"):]
        body = body[:body.index("\nasync function tryAutoApply")]
        self.assertIn("mergeTemplateTypes", body)
        self.assertNotIn("wallTypes = newTypes", body)


if __name__ == "__main__":
    unittest.main()
