"""Applying a template never merges two different wall types into one.

Three ways it used to, each driven here through the real merge out of
walls.js:

* **A name in another script.** Matching threw away everything outside
  `[a-z0-9]`, so every keyless type named in Cyrillic, Greek or CJK reduced to
  the same empty key and matched every other one. Applying a template then
  wrote one template type over a different project type - the walls drawn with
  it changed type - and the rest of the template was never added.
* **An id the project already uses.** A type the template adds kept the
  template's id even where the project had that id on a different type, so the
  file came out with two types answering to one id. `tools/wall_inject.py`
  already guarded this; the page did not.
* **A key derived from a custom type's name.** "Concrete" became key
  `Concrete`, which is Ekahau's own key for "Wall, Concrete": the type listed
  under Standard Ekahau, and a template carrying the stock type overwrote it.
"""
from __future__ import annotations

import shutil
import unittest

from tests.test_wall_template_merge import run_node


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class NamesInAnyScriptTests(unittest.TestCase):

    def test_two_cyrillic_types_are_not_the_same_type(self):
        r = run_node("""
          wallTypes = [{ id: 'wt-a', name: 'Стена' }, { id: 'wt-b', name: 'Дверь' }];
          const res = mergeTemplateTypes([{ id: 't-1', name: 'Окно' },
                                          { id: 't-2', name: 'Пол' }]);
          console.log(JSON.stringify({ res, types: wallTypes }));
        """)
        by_id = {t["id"]: t["name"] for t in r["types"]}
        self.assertEqual(by_id.get("wt-a"), "Стена", r)
        self.assertEqual(by_id.get("wt-b"), "Дверь", r)
        self.assertEqual(sorted(t["name"] for t in r["types"]),
                         sorted(["Стена", "Дверь", "Окно", "Пол"]))
        self.assertEqual((r["res"]["added"], r["res"]["updated"]), (2, 0))

    def test_the_same_cyrillic_name_still_matches(self):
        """Case and punctuation are still folded away in any script."""
        r = run_node("""
          wallTypes = [{ id: 'wt-a', name: 'Стена' }, { id: 'wt-g', name: 'Τοίχος' }];
          const res = mergeTemplateTypes([{ id: 't-1', name: 'стена!', color: '#112233' },
                                          { id: 't-2', name: 'ΤΟΊΧΟΣ', color: '#445566' }]);
          console.log(JSON.stringify({ res, types: wallTypes }));
        """)
        self.assertEqual(len(r["types"]), 2, r)
        by_id = {t["id"]: t for t in r["types"]}
        self.assertEqual(by_id["wt-a"]["color"], "#112233")
        self.assertEqual(by_id["wt-g"]["color"], "#445566")

    def test_a_name_with_no_letters_matches_nothing(self):
        r = run_node("""
          wallTypes = [{ id: 'wt-dash', name: '—' }];
          const res = mergeTemplateTypes([{ id: 't-1', name: '***' }]);
          console.log(JSON.stringify({ res, types: wallTypes }));
        """)
        self.assertEqual([t["name"] for t in r["types"]], ["—", "***"], r)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class AnAddedTypeGetsAFreeIdTests(unittest.TestCase):

    def test_a_taken_id_is_replaced(self):
        r = run_node("""
          wallTypes = [{ id: 'wt-r', name: 'Invented Rack Renamed' }];
          mergeTemplateTypes([{ id: 'wt-r', name: 'Invented Rack' }]);
          console.log(JSON.stringify(wallTypes));
        """)
        self.assertEqual(len(r), 2, r)
        self.assertEqual(r[0], {"id": "wt-r", "name": "Invented Rack Renamed"})
        self.assertNotEqual(r[1]["id"], "wt-r")
        self.assertTrue(r[1]["id"])

    def test_a_free_id_is_kept(self):
        r = run_node("""
          wallTypes = [{ id: 'wt-x', name: 'Invented Wall' }];
          mergeTemplateTypes([{ id: 'wt-new', name: 'Invented Pod' }]);
          console.log(JSON.stringify(wallTypes));
        """)
        self.assertEqual([t["id"] for t in r], ["wt-x", "wt-new"])

    def test_two_template_types_sharing_an_id_get_two_ids(self):
        r = run_node("""
          wallTypes = [];
          mergeTemplateTypes([{ id: 'same', name: 'Invented One' },
                              { id: 'same', name: 'Invented Two' }]);
          console.log(JSON.stringify(wallTypes));
        """)
        self.assertEqual(len({t["id"] for t in r}), 2, r)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ACustomTypeNeverTakesAKeyTests(unittest.TestCase):

    SETUP = """
      globalThis._ekahauDefaults = { wallTypes: [
        { key: 'Concrete', name: 'Wall, Concrete' } ] };
      wallTypes = [{ id: 'wt-c', key: 'Concrete', name: 'Wall, Concrete' },
                   { id: 'wt-x', key: 'InventedWall', name: 'Invented Wall' }];
    """

    def test_a_stock_or_taken_key_is_not_reused(self):
        r = run_node(self.SETUP + """
          console.log(JSON.stringify({
            concrete: customKeyFor('Concrete'),
            invented: customKeyFor('Invented-Wall'),
            fresh: customKeyFor('Invented Pod'),
          }));
        """)
        self.assertNotIn(r["concrete"], ("", "Concrete", "InventedWall"), r)
        self.assertNotIn(r["invented"], ("", "Concrete", "InventedWall"), r)
        self.assertEqual(r["fresh"], "InventedPod")

    def test_a_stock_key_is_refused_even_when_the_project_lacks_the_type(self):
        r = run_node("""
          globalThis._ekahauDefaults = { wallTypes: [{ key: 'Concrete', name: 'Wall, Concrete' }] };
          wallTypes = [];
          console.log(JSON.stringify(customKeyFor('Concrete')));
        """)
        self.assertNotIn(r, ("", "Concrete"))

    def test_names_with_no_latin_letters_get_distinct_keys(self):
        r = run_node(self.SETUP + """
          const a = customKeyFor('Стена');
          wallTypes.push({ id: 'n1', key: a, name: 'Стена' });
          const b = customKeyFor('Дверь');
          console.log(JSON.stringify([a, b]));
        """)
        a, b = r
        self.assertTrue(a and b, r)
        self.assertNotEqual(a, b)

    def test_a_template_stock_type_does_not_overwrite_the_custom_one(self):
        """The end of the chain: with the derived key, applying a template that
        carries the stock type overwrote the custom type named after it."""
        r = run_node("""
          globalThis._ekahauDefaults = { wallTypes: [{ key: 'Concrete', name: 'Wall, Concrete' }] };
          wallTypes = [{ id: 'wt-mine', name: 'Concrete', color: '#0000AA' }];
          wallTypes[0].key = customKeyFor('Concrete', wallTypes[0]);
          mergeTemplateTypes([{ id: 'z', key: 'Concrete', name: 'Wall, Concrete',
                                color: '#00FF00' }]);
          console.log(JSON.stringify(wallTypes));
        """)
        mine = [t for t in r if t["id"] == "wt-mine"]
        self.assertEqual(len(mine), 1, r)
        self.assertEqual(mine[0]["name"], "Concrete")
        self.assertEqual(mine[0]["color"], "#0000AA")
        self.assertEqual(len(r), 2)


if __name__ == "__main__":
    unittest.main()
