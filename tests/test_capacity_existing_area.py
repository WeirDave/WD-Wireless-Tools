"""Capacity and an area the user drew himself.

Reported from live use: "capacity does not seem to work when you have an
existing floor plan that has an existing area that you've defined manually — it
doesn't want to write in the devices."

The skip rule was written to stop a hand-drawn area being replaced, and it was
drawn too wide. It treated *any* area carrying a `requirementId` as "this floor
already has a requirement area" and skipped the floor — so an area he had drawn
by hand, sixteen vertices of real work, could never be filled in. Drawing that
area is precisely how he says "use this shape, not your computed one"; the
template was then refused on the strength of it.

Three cases now, and only the last of them discards anything:

    nothing drawn         create an area from the computed extent
    an area, no capacity  fill it in, his outline untouched
    an area with capacity leave alone unless replacement is asked for

No area is deleted in any of them. Where one exists the items are written into
it and the polygon, name, colour and notes are left exactly as drawn — that is
true of the replace case too, which used to delete and re-create.
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tools import capacity_profiles as cap  # noqa: E402
from test_capacity_profiles import FLOOR, LAPTOP, NORMAL, build_esx  # noqa: E402

# Sixteen vertices enclosing real space - the shape of a hand-drawn
# requirement area, not a zigzag. Its size matters: one test picks between
# two drawn areas by which encloses more.
HAND_DRAWN = [
    {"x": round(700.0 + 500.0 * math.cos(i * math.pi / 8), 2),
     "y": round(600.0 + 380.0 * math.sin(i * math.pi / 8), 2)}
    for i in range(16)
]


def areas_of(path):
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read("areas.json").decode("utf-8"))["areas"]


class ThreeCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        src = Path(build_esx(self.dir / "src.esx"))
        got = cap.extract(src)
        self.template = cap.derive_template(got, 500, "Office")
        self.assertTrue(self.template["ok"])

    def tearDown(self):
        self.tmp.cleanup()

    def project(self, name, areas):
        return Path(build_esx(self.dir / name, areas=areas))

    def apply(self, esx, out="out.esx", replace=False):
        return cap.apply_to(esx, self.dir / out, self.template, 200,
                            replace_existing=replace)

    # ── case 2: his case, and the one that was broken ───────────────────────

    def test_an_area_he_drew_gets_the_devices_written_into_it(self):
        esx = self.project("drawn.esx", [
            {"id": "his-area", "name": "Warehouse", "floorPlanId": FLOOR,
             "requirementId": "req-1", "area": HAND_DRAWN}])
        r = self.apply(esx)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["floorsWritten"], ["Level 1"])
        self.assertEqual(r["areasPopulated"], 1)
        self.assertEqual(r["areasReplaced"], 0)

    def test_his_outline_comes_through_untouched(self):
        """The whole reason he drew it. Vertex for vertex, and the name too."""
        esx = self.project("drawn.esx", [
            {"id": "his-area", "name": "Warehouse", "floorPlanId": FLOOR,
             "requirementId": "req-1", "color": "#abcdef", "area": HAND_DRAWN}])
        self.apply(esx)
        after = [a for a in areas_of(self.dir / "out.esx") if a["id"] == "his-area"][0]
        self.assertEqual(after["area"], HAND_DRAWN)
        self.assertEqual(after["name"], "Warehouse")
        self.assertEqual(after["color"], "#abcdef")

    def test_no_second_area_is_created_beside_his(self):
        esx = self.project("drawn.esx", [
            {"id": "his-area", "floorPlanId": FLOOR, "requirementId": "req-1",
             "area": HAND_DRAWN}])
        self.apply(esx)
        on_floor = [a for a in areas_of(self.dir / "out.esx")
                    if a.get("floorPlanId") == FLOOR]
        self.assertEqual(len(on_floor), 1)

    def test_the_items_actually_land_on_it(self):
        esx = self.project("drawn.esx", [
            {"id": "his-area", "floorPlanId": FLOOR, "requirementId": "req-1",
             "area": HAND_DRAWN}])
        r = self.apply(esx)
        after = [a for a in areas_of(self.dir / "out.esx") if a["id"] == "his-area"][0]
        self.assertEqual(len(after["capacityItems"]), 6)
        self.assertEqual(sum(i["deviceCount"] for i in after["capacityItems"]),
                         r["totalDevices"])

    def test_an_area_with_no_requirement_id_is_still_filled_in(self):
        """He may draw the shape before marking it a requirement area."""
        esx = self.project("plain.esx", [
            {"id": "plain", "floorPlanId": FLOOR, "area": HAND_DRAWN}])
        r = self.apply(esx)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["areasPopulated"], 1)

    def test_the_largest_drawn_area_is_the_one_chosen(self):
        """A requirement area covers the space; small ones are annotations."""
        small = [{"x": 10.0, "y": 10.0}, {"x": 20.0, "y": 10.0}, {"x": 20.0, "y": 20.0}]
        esx = self.project("two.esx", [
            {"id": "small", "floorPlanId": FLOOR, "area": small},
            {"id": "big", "floorPlanId": FLOOR, "area": HAND_DRAWN}])
        self.apply(esx)
        out = {a["id"]: a for a in areas_of(self.dir / "out.esx")}
        self.assertTrue(out["big"].get("capacityItems"))
        self.assertFalse(out["small"].get("capacityItems"))

    def test_an_area_already_marked_as_a_requirement_wins_over_a_bigger_one(self):
        huge = [{"x": 0.0, "y": 0.0}, {"x": 1900.0, "y": 0.0}, {"x": 1900.0, "y": 1400.0}]
        esx = self.project("flagged.esx", [
            {"id": "huge", "floorPlanId": FLOOR, "area": huge},
            {"id": "flagged", "floorPlanId": FLOOR, "requirementId": "req-1",
             "area": HAND_DRAWN}])
        self.apply(esx)
        out = {a["id"]: a for a in areas_of(self.dir / "out.esx")}
        self.assertTrue(out["flagged"].get("capacityItems"))
        self.assertFalse(out["huge"].get("capacityItems"))

    # ── case 3: the one that really is destructive ──────────────────────────

    def test_an_area_that_already_has_capacity_is_left_alone(self):
        esx = self.project("full.esx", [
            {"id": "full", "floorPlanId": FLOOR, "requirementId": "req-1",
             "capacityItems": [{"deviceCount": 42, "deviceProfileId": LAPTOP,
                                "usageProfileId": NORMAL}],
             "area": HAND_DRAWN}])
        r = self.apply(esx, out="nope.esx")
        self.assertTrue(r["ok"])
        self.assertEqual(r["floorsWritten"], [])
        self.assertFalse((self.dir / "nope.esx").exists())

    def test_the_skip_says_how_many_items_would_be_overwritten(self):
        esx = self.project("full.esx", [
            {"id": "full", "floorPlanId": FLOOR, "requirementId": "req-1",
             "capacityItems": [{"deviceCount": 42, "deviceProfileId": LAPTOP,
                                "usageProfileId": NORMAL}],
             "area": HAND_DRAWN}])
        plan = cap.plan_application(esx, self.template, 200)
        floor = [f for f in plan["floors"] if f["floorPlanId"] == FLOOR][0]
        self.assertEqual(floor["mode"], "replace")
        self.assertIn("already has 1 capacity items", floor["action"])

    def test_replacing_keeps_his_outline_rather_than_redrawing_it(self):
        """Replace used to delete the area and create a fresh rectangle."""
        esx = self.project("full.esx", [
            {"id": "full", "floorPlanId": FLOOR, "requirementId": "req-1",
             "capacityItems": [{"deviceCount": 42, "deviceProfileId": LAPTOP,
                                "usageProfileId": NORMAL}],
             "area": HAND_DRAWN}])
        r = self.apply(esx, replace=True)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["areasReplaced"], 1)
        after = [a for a in areas_of(self.dir / "out.esx") if a["id"] == "full"][0]
        self.assertEqual(after["area"], HAND_DRAWN)
        self.assertEqual(len(after["capacityItems"]), 6)

    # ── case 1, and the wording of the plan ─────────────────────────────────

    def test_a_floor_with_nothing_drawn_still_gets_an_area_made(self):
        esx = self.project("empty.esx", [])
        r = self.apply(esx)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["areasPopulated"], 0)
        self.assertEqual(len(areas_of(self.dir / "out.esx")), 1)

    def test_the_plan_says_which_of_the_three_it_is_in_his_words(self):
        cases = {
            "empty.esx": ([], "create an area from"),
            "drawn.esx": ([{"id": "a", "floorPlanId": FLOOR, "area": HAND_DRAWN}],
                          "your area"),
            "full.esx": ([{"id": "b", "floorPlanId": FLOOR,
                           "capacityItems": [{"deviceCount": 1,
                                              "deviceProfileId": LAPTOP,
                                              "usageProfileId": NORMAL}],
                           "area": HAND_DRAWN}], "already has"),
        }
        for name, (areas, phrase) in cases.items():
            with self.subTest(case=name):
                esx = self.project(name, areas)
                plan = cap.plan_application(esx, self.template, 200)
                floor = [f for f in plan["floors"] if f["floorPlanId"] == FLOOR][0]
                self.assertIn(phrase, floor["action"])

    def test_the_populate_plan_says_the_outline_is_not_changed(self):
        esx = self.project("drawn.esx", [
            {"id": "a", "floorPlanId": FLOOR, "area": HAND_DRAWN}])
        plan = cap.plan_application(esx, self.template, 200)
        floor = [f for f in plan["floors"] if f["floorPlanId"] == FLOOR][0]
        self.assertIn("your outline is not changed", floor["action"])
        self.assertEqual(floor["targetVertexCount"], 16)

    def test_another_zone_on_the_same_floor_is_reported_untouched(self):
        esx = self.project("mixed.esx", [
            {"id": "lobby", "floorPlanId": FLOOR, "requirementId": "req-1",
             "area": [{"x": 5.0, "y": 5.0}, {"x": 9.0, "y": 5.0}, {"x": 9.0, "y": 9.0}]},
            {"id": "main", "floorPlanId": FLOOR, "requirementId": "req-1",
             "area": HAND_DRAWN}])
        r = self.apply(esx)
        self.assertEqual(r["areasPopulated"], 1)
        self.assertEqual(r["areasLeftInPlace"], 1)
        out = {a["id"]: a for a in areas_of(self.dir / "out.esx")}
        self.assertFalse(out["lobby"].get("capacityItems"))


if __name__ == "__main__":
    unittest.main()
