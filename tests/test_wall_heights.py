"""Partial-height wall types must carry a height.

An Ekahau wall type with no ``upperEdge`` is Auto - floor to ceiling. That is
right for a wall and wrong for furniture, and the difference is not cosmetic:
"Shelf, Warehouse" is 18 dB/m over 1.5 m, so shipping it on Auto models 27 dB
of steel racking from the slab to the roof of a high-bay. Signal that in reality
goes straight over the top is predicted as blocked, which changes AP counts.

Both shipped templates had this on every type. Found by auditing 108 real
projects: one of them had 52 segments drawn with "Shelf, Warehouse" on Auto.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"

# Anything that stands on the floor and stops short of the ceiling.
PARTIAL_HEIGHT = re.compile(
    r"shelf|shelv|rack|cubicle|bookshelf|partition|pod|booth|counter", re.I)

# Types deliberately left on Auto, and why. Guessing a height for something
# whose name does not state one is how the original fault was introduced, so
# the audit reports these rather than this file inventing a number.
NO_HEIGHT_ON_PURPose = {
    "Warehouse Rack Wall": "name states no height and racking varies too much "
                           "to guess; the project audit reports it instead",
    "Framery Pod": "a sealed pod with a metal roof and floor - height-limiting "
                   "it would let a ceiling AP drop in over the top at no loss, "
                   "which is the opposite of what a steel roof does",
}

FT = 0.3048


def _templates():
    for path in sorted(TEMPLATES.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(doc, dict) and doc.get("wallTypes"):
            yield path, doc["wallTypes"]


class WallHeightTests(unittest.TestCase):
    def test_templates_exist(self):
        self.assertTrue(list(_templates()), "no wall templates found to check")

    def test_partial_height_types_carry_a_height(self):
        for path, types in _templates():
            for w in types:
                name = w.get("name") or ""
                if not PARTIAL_HEIGHT.search(name):
                    continue
                if name in NO_HEIGHT_ON_PURPose:
                    continue
                with self.subTest(template=path.name, wall=name):
                    self.assertIn(
                        "upperEdge", w,
                        f"{name!r} stands on the floor and stops short of the "
                        "ceiling; without upperEdge Ekahau models it "
                        "floor-to-ceiling")

    def test_a_height_is_above_the_floor_and_plausible(self):
        for path, types in _templates():
            for w in types:
                if "upperEdge" not in w:
                    continue
                name = w.get("name") or "?"
                with self.subTest(template=path.name, wall=name):
                    lower = float(w.get("lowerEdge", 0.0))
                    upper = float(w["upperEdge"])
                    self.assertGreater(upper, lower,
                                       "the top of a wall is above its bottom")
                    self.assertLessEqual(upper, 30.0,
                                         "a wall taller than 30 m is a unit "
                                         "mistake - these are metres, not feet")

    def test_the_named_rack_heights_match_their_names(self):
        """"Warehouse Rack Wall - 12ft" should be twelve feet tall."""
        for path, types in _templates():
            for w in types:
                name = w.get("name") or ""
                m = re.search(r"(\d+)\s*ft", name, re.I)
                if not m or "upperEdge" not in w:
                    continue
                with self.subTest(template=path.name, wall=name):
                    self.assertAlmostEqual(
                        float(w["upperEdge"]), int(m.group(1)) * FT, places=3,
                        msg=f"{name!r} says {m.group(1)} ft but its upperEdge "
                            "says otherwise")

    def test_heights_match_ekahau_where_ekahau_ships_an_equivalent(self):
        """Same name, same height, so our template and theirs agree."""
        expected = {"Cubicle": 1.5, "Shelf, Retail": 2.5, "Shelf, Warehouse": 10.0}
        seen = set()
        for path, types in _templates():
            for w in types:
                name = w.get("name") or ""
                if name in expected and "upperEdge" in w:
                    seen.add(name)
                    with self.subTest(template=path.name, wall=name):
                        self.assertAlmostEqual(float(w["upperEdge"]), expected[name],
                                               places=3)
        self.assertEqual(seen, set(expected),
                         "a type Ekahau also ships lost its height")


if __name__ == "__main__":
    unittest.main()
