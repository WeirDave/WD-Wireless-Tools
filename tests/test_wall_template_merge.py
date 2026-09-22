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
class HisOwnValuesReachHisProjects(unittest.TestCase):
    """A template updates a type the project already has, stock or not.

    v2.100.5 made the merge skip anything Ekahau ships, on the reading that a
    template must never deviate from the standard set. That was wrong about
    this template: the three colours it protected the greys from are his, and
    the Quick Walls guide had described them as a feature for as long as they
    existed. He asked for them back.

    The guard could not simply be left in place alongside the restored colours.
    Every Ekahau project already contains those three types, so the skip would
    fire on every project and his colours would never arrive - a restoration
    that changed a file and nothing a person would see.
    """

    DEFAULTS = """
      globalThis._ekahauDefaults = { wallTypes: [
        { key: 'DRY_WALL', name: 'Dry Wall', color: '#D9D9D9' },
        { key: 'ElevatorShaft', name: 'Elevator Shaft', color: '#5A5A5A' }
      ] };
    """

    def test_his_colour_lands_on_a_stock_type_the_project_already_has(self):
        out = run_node(self.DEFAULTS + """
          wallTypes = [{ id: 'id-lift', key: 'ElevatorShaft',
                         name: 'Elevator Shaft', color: '#5A5A5A' }];
          const r = mergeTemplateTypes([{ id: 't', key: 'ElevatorShaft',
                         name: 'Elevator Shaft', color: '#5FAB4F' }]);
          console.log(JSON.stringify({ color: wallTypes[0].color,
                                       id: wallTypes[0].id, r }));
        """)
        self.assertEqual(out["color"], "#5FAB4F",
                         "his colour has to reach a project that already has "
                         "the type, or restoring it changes nothing he can see")
        self.assertEqual(out["id"], "id-lift",
                         "and the project's own id is still kept, so walls "
                         "already drawn with it still resolve")
        self.assertEqual(out["r"]["updated"], 1)

    def test_a_custom_type_is_updated_too(self):
        out = run_node(self.DEFAULTS + """
          wallTypes = [{ id: 'id-pod', name: 'Framery Pod', color: '#111111' }];
          const r = mergeTemplateTypes([{ id: 't', name: 'Framery Pod',
                                          color: '#222222' }]);
          console.log(JSON.stringify({ color: wallTypes[0].color, r }));
        """)
        self.assertEqual(out["color"], "#222222")

    def test_nothing_is_removed_by_any_of_this(self):
        """The rule that has not changed and must not."""
        out = run_node(self.DEFAULTS + """
          wallTypes = [{ id: 'keep', name: 'Retail Shelf', upperEdge: 2.5 }];
          mergeTemplateTypes([{ id: 't', name: 'Framery Pod' }]);
          console.log(JSON.stringify({ names: wallTypes.map(w => w.name) }));
        """)
        self.assertIn("Retail Shelf", out["names"])


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

    def test_wd_template_carries_the_three_colours_he_chose(self):
        """Recovered from his own most recent project after they were lost.

        Ekahau's greys for these three are hard to tell apart on a plan, so he
        recoloured them; that is why the guide described it as a feature. They
        were removed in v2.100.5 by me, on a wrong reading, and restored here
        from the project file that still carried them - his work of
        2026-09-11, the only one of three September projects that had the
        recoloured template applied.
        """
        his = {"Door, Steel Fire/Exit": "#E85D04",
               "Elevator Shaft": "#5FAB4F",
               "Window, Thick": "#0093EA"}
        by_name = {w["name"]: w for w in self._types("WD Template_walltemplate.json")}
        for name, colour in his.items():
            with self.subTest(wall_type=name):
                self.assertEqual(by_name[name].get("color"), colour)

    def test_the_named_heights_are_still_there(self):
        """His projects predate these, so the template is the newer record and
        the files do not overrule it here."""
        by_name = {w["name"]: w for w in self._types("WD Template_walltemplate.json")}
        self.assertAlmostEqual(by_name["Walls, Steel 12ft"]["upperEdge"], 3.6576, places=4)
        self.assertAlmostEqual(by_name["Warehouse Rack Wall - 16ft"]["upperEdge"], 4.8768, places=4)
        self.assertIsNone(by_name["Warehouse Rack Wall"].get("upperEdge"))

    def test_wd_template_carries_his_own_additions(self):
        wd = {w["name"] for w in self._types("WD Template_walltemplate.json")}
        for name in ("Framery Pod", "Warehouse Rack Wall - 12ft",
                     "Warehouse Rack Wall - 16ft"):
            self.assertIn(name, wd)


class ResetIsTheOnlyDestructiveActionTests(unittest.TestCase):
    def test_the_reset_button_still_exists_and_is_separate(self):
        html = WALLS_HTML.read_text(encoding="utf-8")
        self.assertIn('data-fn="resetToEkahauDefaults"', html)

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
