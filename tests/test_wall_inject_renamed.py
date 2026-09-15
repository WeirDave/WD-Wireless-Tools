"""Ekahau renamed its stock wall types, and Prep was adding a second copy.

Found by running the whole Prep pipeline in Firefox on a real design project
and opening what came out: **43 wall types where there should have been 33**,
with ten near-duplicate pairs — `Dry Wall` beside `Wall, Dry`, `Thin Door`
beside `Door, Thin`, `Thick Window` beside `Window, Thick`.

Ekahau renamed these between releases. A project made in an older release
carries the old names; the template carries the new ones; matching on the exact
name sees two different types and injects the second. The result opens, works,
and presents a wall-type list twice as long as it should be with no way to tell
which of each pair to draw with.

The rule: **same words, in any order, punctuation ignored, is the same type.**
Different words stay different, so `Wall, Dry` and `Wall, Dry, Hollow` remain
two types — and none of his own five collides with anything Ekahau ships.

Deliberately conservative. It only ever causes Prep to skip *more*; it never
deletes, never modifies, and never touches a wall already drawn.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import wall_inject  # noqa: E402

# The pairs observed in a real project, old name first.
RENAMED = [
    ("Dry Wall", "Wall, Dry"),
    ("Dry Wall (hollow)", "Wall, Dry, Hollow"),
    ("Brick Wall", "Wall, Brick"),
    ("Thick Window", "Window, Thick"),
    ("Thin Door", "Door, Thin"),
    ("Hollow wood door", "Door, Hollow Wood"),
    ("Solid wood door", "Door, Solid Wood"),
    ("Interior office door", "Door, Interior Office"),
    ("Steel fire/exit door", "Door, Steel Fire/Exit"),
    ("Steel rollup door", "Door, Steel Rollup"),
]

HIS_OWN = ["Framery Pod", "Walls, Steel 12ft", "Warehouse Rack Wall",
           "Warehouse Rack Wall - 12ft", "Warehouse Rack Wall - 16ft"]


def members(existing_names):
    return {wall_inject.MEMBER: json.dumps({
        "wallTypes": [{"name": n, "key": n.replace(" ", ""), "id": "id-%d" % i}
                      for i, n in enumerate(existing_names)]
    }).encode("utf-8")}


def template(names):
    return [{"name": n, "key": n.replace(" ", ""), "id": "t-%d" % i}
            for i, n in enumerate(names)]


class EkahausRenaming(unittest.TestCase):
    def test_every_observed_pair_is_recognised_as_one_type(self):
        for old, new in RENAMED:
            with self.subTest(old=old, new=new):
                self.assertEqual(wall_inject._words(old), wall_inject._words(new))

    def test_a_renamed_type_is_not_added_again(self):
        for old, new in RENAMED:
            with self.subTest(old=old):
                plan = wall_inject.plan_into_members(members([old]), template([new]))
                self.assertEqual(plan["add"], [])
                self.assertIn("older name", plan["skip"][0]["why"])
                self.assertIn(old, plan["skip"][0]["why"])

    def test_the_skip_names_the_type_it_matched(self):
        """He has to be able to see why his type was not added."""
        plan = wall_inject.plan_into_members(members(["Dry Wall"]),
                                             template(["Wall, Dry"]))
        self.assertIn("Dry Wall", plan["skip"][0]["why"])


class DistinctTypesStayDistinct(unittest.TestCase):
    def test_hollow_is_not_the_same_type_as_plain(self):
        """The extra word is the whole difference between them."""
        self.assertNotEqual(wall_inject._words("Wall, Dry"),
                            wall_inject._words("Wall, Dry, Hollow"))
        plan = wall_inject.plan_into_members(members(["Wall, Dry"]),
                                             template(["Wall, Dry, Hollow"]))
        self.assertEqual([a["name"] for a in plan["add"]], ["Wall, Dry, Hollow"])

    def test_none_of_his_own_types_collides_with_a_stock_one(self):
        stock = [old for old, _ in RENAMED] + [
            "Bookshelf", "Cubicle", "Elevator Shaft", "Marble", "Concrete", "Window"]
        plan = wall_inject.plan_into_members(members(stock), template(HIS_OWN))
        self.assertEqual(sorted(a["name"] for a in plan["add"]), sorted(HIS_OWN))

    def test_the_rack_walls_are_three_separate_types(self):
        """12ft and 16ft differ by one token and must both survive."""
        plan = wall_inject.plan_into_members(
            members(["Warehouse Rack Wall"]),
            template(["Warehouse Rack Wall - 12ft", "Warehouse Rack Wall - 16ft"]))
        self.assertEqual(len(plan["add"]), 2)


class TheRealProjectShape(unittest.TestCase):
    """The counts measured on the project that produced the report."""

    OLD_PROJECT = [old for old, _ in RENAMED] + [
        "Bookshelf", "Concrete", "Cubicle", "Elevator Shaft", "Marble", "Window",
        "HollowWoodDoor (4dB)", "InteriorOfficeDoor (4dB)", "SolidWoodDoor (6dB)",
        "SteelFire/ExitDoor (13dB)", "SteelRollupDoor (11dB)",
    ]

    def test_the_renamed_ten_are_all_skipped(self):
        tpl = template([new for _, new in RENAMED] + HIS_OWN)
        plan = wall_inject.plan_into_members(members(self.OLD_PROJECT), tpl)
        renamed_skips = [s for s in plan["skip"] if "older name" in s["why"]]
        self.assertEqual(len(renamed_skips), 10)
        self.assertEqual(sorted(a["name"] for a in plan["add"]), sorted(HIS_OWN))

    def test_a_template_naming_the_same_type_twice_only_adds_it_once(self):
        plan = wall_inject.plan_into_members(
            members([]), template(["Wall, Dry", "Dry Wall"]))
        self.assertEqual(len(plan["add"]), 1)
        self.assertIn("twice", plan["skip"][0]["why"])


if __name__ == "__main__":
    unittest.main()
