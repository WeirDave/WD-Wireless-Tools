"""A shipped wall type carries a height only when its name states one.

This file used to assert the opposite, and the reversal is the point.

v2.44.0 gave "Bookshelf", "Cubicle", "Shelf, Retail" and "Shelf, Warehouse" an
``upperEdge`` on the reasoning that furniture stops short of the ceiling. The
reasoning is right and the action was wrong, for two separate reasons.

The first is that we do not know the number. A cubicle is 1.2 m in one office
and 1.7 m in the next; warehouse racking varies more than that again. Shipping
a guess changes every project that opens the template, silently, in a direction
nobody chose - and the person who notices is the one whose AP count moved.
``tools/wall_audit.py`` already reports partial-height types drawn on Auto, by
name, per project. A report the user can argue with beats a default they cannot
see.

The second is where the numbers came from. Ekahau does model partial-height
furniture with an upper edge, but on *attenuation areas* - a different
primitive, with polygon geometry and both edges - not on wall types. Before
v2.44.0 ``ekahau_defaults.json`` carried no ``upperEdge`` at all, on any type.
So the 1.5 and 2.5 we matched "so our template and theirs agree" were taken
from Ekahau's area types and written onto walls, and the agreement asserted by
the old test was with a file we had just edited ourselves.

What survives is the half that was never a guess: a type whose own name says
how tall it is can be set with certainty, and must be, or the name lies.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"

FT = 0.3048

# A height stated in the type's own name - "Warehouse Rack Wall - 16ft".
NAME_STATES_HEIGHT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:ft|foot|feet|')\b", re.I)

# Anything that stands on the floor and stops short of the ceiling. Kept in step
# with tools/wall_audit.py, which is what reports these to the user.
PARTIAL_HEIGHT = re.compile(
    r"shelf|shelv|rack|cubicle|bookshelf|partition|pod|booth|counter", re.I)


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

    def test_a_height_is_only_shipped_when_the_name_states_one(self):
        """The rule, stated as a test: no name, no number."""
        for path, types in _templates():
            for w in types:
                if "upperEdge" not in w:
                    continue
                name = w.get("name") or "?"
                with self.subTest(template=path.name, wall=name):
                    self.assertRegex(
                        name, NAME_STATES_HEIGHT,
                        f"{name!r} ships a height its name does not state. "
                        "Guessing furniture heights for someone else's building "
                        "is what v2.44.0 got wrong - leave it on Auto and let "
                        "tools/wall_audit.py report it per project.")

    def test_a_stated_height_matches_the_name(self):
        """"Warehouse Rack Wall - 16ft" is 16 feet, or the name lies."""
        checked = 0
        for path, types in _templates():
            for w in types:
                name = w.get("name") or ""
                m = NAME_STATES_HEIGHT.search(name)
                if not m:
                    continue
                with self.subTest(template=path.name, wall=name):
                    self.assertIn("upperEdge", w,
                                  f"{name!r} states a height in its name but "
                                  "ships on Auto")
                    self.assertAlmostEqual(
                        float(w["upperEdge"]), float(m.group(1)) * FT, places=4,
                        msg=f"{name!r} says {m.group(1)} ft but its upperEdge "
                            "says otherwise")
                    checked += 1
        self.assertGreater(checked, 0, "no name-stated heights found to check")

    def test_the_two_named_heights_are_exact(self):
        """The values, spelled out, so a refactor cannot drift them."""
        expected = {
            "Walls, Steel 12ft": 3.6576,          # 12 ft
            "Warehouse Rack Wall - 12ft": 3.6576,  # 12 ft
            "Warehouse Rack Wall - 16ft": 4.8768,  # 16 ft
        }
        seen = {}
        for path, types in _templates():
            for w in types:
                name = w.get("name") or ""
                if name in expected and "upperEdge" in w:
                    seen[name] = float(w["upperEdge"])
        for name, value in expected.items():
            with self.subTest(wall=name):
                self.assertIn(name, seen, f"{name!r} lost its height")
                self.assertAlmostEqual(seen[name], value, places=4)

    def test_the_guessed_heights_stayed_reverted(self):
        """The four types v2.44.0 guessed at must ship on Auto."""
        guessed = {"Bookshelf", "Cubicle", "Shelf, Retail", "Shelf, Warehouse"}
        for path, types in _templates():
            for w in types:
                name = w.get("name") or ""
                if name not in guessed:
                    continue
                with self.subTest(template=path.name, wall=name):
                    self.assertNotIn(
                        "upperEdge", w,
                        f"{name!r} is back to a guessed height. Its real height "
                        "depends on the building, so it ships on Auto and the "
                        "audit reports it.")

    def test_ekahau_defaults_ship_no_heights_at_all(self):
        """That file mirrors Ekahau's own defaults; it is not ours to improve.

        Ekahau puts an upper edge on attenuation areas, not on wall types, and
        this file had none before v2.44.0 edited it.
        """
        path = TEMPLATES / "ekahau_defaults.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        offenders = [w.get("name") for w in doc.get("wallTypes") or []
                     if "upperEdge" in w]
        self.assertEqual(offenders, [],
                         "the Ekahau Defaults mirror must match what Ekahau "
                         "ships, not what we would prefer")

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

    def test_partial_height_types_without_a_stated_height_are_left_on_auto(self):
        """Auto here is the deliberate answer, and the audit is the backstop."""
        found = 0
        for path, types in _templates():
            for w in types:
                name = w.get("name") or ""
                if not PARTIAL_HEIGHT.search(name):
                    continue
                if NAME_STATES_HEIGHT.search(name):
                    continue
                found += 1
                with self.subTest(template=path.name, wall=name):
                    self.assertNotIn("upperEdge", w)
        self.assertGreater(found, 0, "expected some furniture types on Auto")


if __name__ == "__main__":
    unittest.main()
