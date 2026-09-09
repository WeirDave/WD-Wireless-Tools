"""Capacity profile templates: extraction, ratios, and where the area lands.

The fixture reproduces the configuration these were built against - 1500
devices across 500 occupants, two device profiles crossed with three usage
profiles - so the numbers in these assertions are the numbers off a real
Capacity panel rather than invented ones.
"""
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import capacity_profiles as cap  # noqa: E402


LAPTOP = "dev-laptop"
PHONE = "dev-phone"
NORMAL = "use-normal"
CONF = "use-conf"
BACKGROUND = "use-bg"

FLOOR = "floor-live"
DEAD_FLOOR = "floor-deleted"

# 450+50 laptop, 250+250+450+50 smartphone = 1500 devices for 500 people.
CAPACITY_ITEMS = [
    {"deviceCount": 450, "deviceProfileId": LAPTOP, "usageProfileId": NORMAL},
    {"deviceCount": 50, "deviceProfileId": LAPTOP, "usageProfileId": CONF},
    {"deviceCount": 250, "deviceProfileId": PHONE, "usageProfileId": NORMAL},
    {"deviceCount": 250, "deviceProfileId": PHONE, "usageProfileId": BACKGROUND},
    {"deviceCount": 450, "deviceProfileId": PHONE, "usageProfileId": BACKGROUND},
    {"deviceCount": 50, "deviceProfileId": PHONE, "usageProfileId": NORMAL},
]


def build_esx(path, *, walls=True, aps=True, areas=None, mpu=0.05,
              width=2000.0, height=1500.0):
    members = {
        "project.json": {"project": {"id": "p", "name": "Capacity Fixture"}},
        "floorPlans.json": {"floorPlans": [
            {"id": FLOOR, "name": "Level 1", "width": width, "height": height,
             "metersPerUnit": mpu, "bitmapImageId": "img-1"},
        ]},
        # Profiles deliberately live in files this code does not name, to prove
        # the id resolver does not depend on a filename.
        "surprisingProfileHome.json": {"deviceProfiles": [
            {"id": LAPTOP, "name": "Generic Wi-Fi 6E Laptop, Wi-Fi 6 2x2:2 160MHz"},
            {"id": PHONE, "name": "Generic Wi-Fi 6E Smartphone, Wi-Fi 6 2x2:2 160MHz"},
        ]},
        "alsoUnexpected.json": {"usageProfiles": [
            {"id": NORMAL, "name": "Normal SLA"},
            {"id": CONF, "name": "Conferencing"},
            {"id": BACKGROUND, "name": "Background Sync"},
        ]},
        "requirements.json": {"requirements": [
            {"id": "req-1", "name": "Ekahau Best Practices", "isDefault": True},
        ]},
    }
    if areas is None:
        areas = [{"id": "area-2", "floorPlanId": FLOOR, "requirementId": "req-1",
                  "capacityItems": CAPACITY_ITEMS,
                  "area": [{"x": 100.0, "y": 100.0}, {"x": 400.0, "y": 100.0}]},
                 # Orphan: its floor plan no longer exists.
                 {"id": "area-1", "floorPlanId": DEAD_FLOOR, "requirementId": "req-1",
                  "capacityItems": [{"deviceCount": 99, "deviceProfileId": LAPTOP,
                                     "usageProfileId": NORMAL}]}]
    members["areas.json"] = {"areas": areas}

    if walls:
        # A tight cluster of walls in one corner of a large canvas: the whole
        # point is that the requirement should follow the building, not the page.
        members["wallPoints.json"] = {"wallPoints": [
            {"id": "wp1", "location": {"floorPlanId": FLOOR, "coord": {"x": 200.0, "y": 300.0}}},
            {"id": "wp2", "location": {"floorPlanId": FLOOR, "coord": {"x": 800.0, "y": 300.0}}},
            {"id": "wp3", "location": {"floorPlanId": FLOOR, "coord": {"x": 800.0, "y": 700.0}}},
            {"id": "wp4", "location": {"floorPlanId": FLOOR, "coord": {"x": 200.0, "y": 700.0}}},
            # Stray point far away, joined to nothing - must not stretch the box.
            {"id": "wp-orphan", "location": {"floorPlanId": FLOOR,
                                             "coord": {"x": 1950.0, "y": 1450.0}}},
        ]}
        members["wallSegments.json"] = {"wallSegments": [
            {"id": "ws1", "wallPoints": ["wp1", "wp2"]},
            {"id": "ws2", "wallPoints": ["wp2", "wp3"]},
            {"id": "ws3", "wallPoints": ["wp3", "wp4"]},
        ]}
    if aps:
        members["accessPoints.json"] = {"accessPoints": [
            {"id": "ap1", "name": "AP1",
             "location": {"floorPlanId": FLOOR, "coord": {"x": 300.0, "y": 400.0}}},
            {"id": "ap2", "name": "AP2",
             "location": {"floorPlanId": FLOOR, "coord": {"x": 700.0, "y": 600.0}}},
        ]}

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in members.items():
            z.writestr(name, json.dumps(body))
    return path


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.esx = build_esx(Path(self.tmp.name) / "src.esx")

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_the_capacity_rows_off_the_project(self):
        got = cap.extract(self.esx)
        self.assertTrue(got["ok"])
        self.assertEqual(got["totalDevices"], 1500)
        # Two device profiles, three usage profiles - the six rows are the
        # cross, not six kinds of hardware.
        self.assertEqual(got["deviceProfileCount"], 2)
        self.assertEqual(got["usageProfileCount"], 3)

    def test_resolves_profile_names_from_a_file_it_does_not_know(self):
        rows = cap.extract(self.esx)["rows"]
        names = {r["device"] for r in rows}
        self.assertIn("Generic Wi-Fi 6E Laptop, Wi-Fi 6 2x2:2 160MHz", names)
        self.assertIn("Normal SLA", {r["usage"] for r in rows})

    def test_rows_are_kept_as_authored_not_merged(self):
        # A work phone and a personal phone are the same hardware on the same
        # usage tier in different proportions. Summing them to one 700-device
        # row would lose the split the designer decided on, and the captured
        # template would stop matching the panel it was read from.
        rows = cap.extract(self.esx)["rows"]
        self.assertEqual(len(rows), 6)
        bg = [r for r in rows if "Smartphone" in r["device"] and r["usage"] == "Background Sync"]
        self.assertEqual(sorted(r["deviceCount"] for r in bg), [250, 450])

    def test_an_area_on_a_deleted_floor_is_reported_not_counted(self):
        got = cap.extract(self.esx)
        self.assertEqual(got["orphanAreasSkipped"], 1)
        self.assertEqual(got["totalDevices"], 1500)   # the orphan's 99 excluded

    def test_requirement_name_comes_through(self):
        self.assertEqual(cap.extract(self.esx)["requirementName"], "Ekahau Best Practices")


class RatioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.extracted = cap.extract(build_esx(Path(self.tmp.name) / "src.esx"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_ratios_are_per_occupant_not_raw_counts(self):
        tpl = cap.derive_template(self.extracted, 500, "Office")
        self.assertTrue(tpl["ok"])
        self.assertEqual(tpl["devicesPerOccupant"], 3.0)
        laptop_normal = [i for i in tpl["items"]
                         if "Laptop" in i["device"] and i["usage"] == "Normal SLA"][0]
        self.assertEqual(laptop_normal["perOccupant"], 0.9)

    def test_a_template_scales_to_a_smaller_building(self):
        tpl = cap.derive_template(self.extracted, 500, "Office")
        got = cap.apply_headcount(tpl, 200)
        self.assertTrue(got["ok"])
        self.assertEqual(got["totalDevices"], 600)      # 3 per person
        laptop_normal = [r for r in got["rows"]
                         if "Laptop" in r["device"] and r["usage"] == "Normal SLA"][0]
        self.assertEqual(laptop_normal["deviceCount"], 180)   # 0.9 * 200

    def test_occupants_must_be_given(self):
        self.assertFalse(cap.derive_template(self.extracted, 0, "x")["ok"])
        self.assertFalse(cap.derive_template(self.extracted, None, "x")["ok"])

    def test_nothing_to_capture_is_an_explained_refusal(self):
        empty = {"rows": [], "totalDevices": 0, "source": "x.esx"}
        got = cap.derive_template(empty, 500, "x")
        self.assertFalse(got["ok"])
        self.assertIn("Ekahau", got["error"])


class AreaBasisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _members(self, **kw):
        path = build_esx(Path(self.tmp.name) / "a.esx", **kw)
        with zipfile.ZipFile(path) as z:
            return cap._read_members(z), path

    def _floor(self, members):
        return members["floorPlans.json"]["floorPlans"][0]

    def test_walls_are_the_basis_and_the_area_is_the_building_not_the_page(self):
        members, _ = self._members()
        got = cap.area_for_floor(members, self._floor(members))
        self.assertEqual(got["basis"], "walls")
        # Walls span 600x400 of a 2000x1500 canvas: without this the
        # requirement would cover roughly seven times the building.
        self.assertLess(got["fractionOfCanvas"], 0.15)

    def test_a_wall_point_joined_to_nothing_does_not_stretch_the_area(self):
        members, _ = self._members()
        got = cap.area_for_floor(members, self._floor(members))
        # The stray point sits at 1950,1450; the segments stop at 800,700.
        self.assertLess(got["polygon"][2]["x"], 900)

    def test_padding_is_half_a_metre_in_plan_units(self):
        members, _ = self._members()
        got = cap.area_for_floor(members, self._floor(members))
        # 0.5 m at 0.05 m/unit is 10 units either side of the 200..800 span.
        self.assertAlmostEqual(got["polygon"][0]["x"], 190.0, places=3)
        self.assertEqual(got["padMeters"], 0.5)

    def test_size_is_reported_in_feet(self):
        members, _ = self._members()
        got = cap.area_for_floor(members, self._floor(members))
        # 620 units * 0.05 m = 31 m = 101.7 ft
        self.assertAlmostEqual(got["widthFt"], 101.7, places=1)

    def test_falls_back_to_ap_extent_when_there_are_no_walls(self):
        members, _ = self._members(walls=False)
        got = cap.area_for_floor(members, self._floor(members))
        self.assertEqual(got["basis"], "aps")

    def test_falls_back_to_the_canvas_when_there_is_nothing_else(self):
        members, _ = self._members(walls=False, aps=False)
        got = cap.area_for_floor(members, self._floor(members))
        self.assertEqual(got["basis"], "canvas")
        self.assertEqual(got["fractionOfCanvas"], 1.0)

    def test_without_a_scale_the_pad_is_left_off_rather_than_guessed(self):
        members, _ = self._members(mpu=None)
        got = cap.area_for_floor(members, self._floor(members))
        self.assertEqual(got["padMeters"], 0.0)
        self.assertAlmostEqual(got["polygon"][0]["x"], 200.0, places=3)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.esx = build_esx(Path(self.tmp.name) / "src.esx")
        self.tpl = cap.derive_template(cap.extract(self.esx), 500, "Office")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_floor_with_a_hand_drawn_area_is_skipped_by_default(self):
        got = cap.plan_application(self.esx, self.tpl, 200)
        self.assertTrue(got["ok"])
        self.assertEqual(got["willSkip"], 1)
        self.assertEqual(got["willWrite"], 0)
        self.assertIn("already has", got["floors"][0]["action"])

    def test_replacing_is_possible_but_has_to_be_asked_for(self):
        got = cap.plan_application(self.esx, self.tpl, 200, replace_existing=True)
        self.assertEqual(got["willWrite"], 1)
        self.assertEqual(got["floors"][0]["action"], "replace existing")

    def test_a_floor_with_no_requirement_is_created(self):
        path = build_esx(Path(self.tmp.name) / "bare.esx", areas=[])
        got = cap.plan_application(path, self.tpl, 200)
        self.assertEqual(got["willWrite"], 1)
        self.assertEqual(got["floors"][0]["action"], "create")

    def test_the_preview_carries_the_counts_that_would_be_written(self):
        got = cap.plan_application(self.esx, self.tpl, 200)
        self.assertEqual(got["totalDevices"], 600)
        self.assertEqual(len(got["rows"]), 6)

    def test_an_orphaned_area_never_claims_a_live_floor(self):
        got = cap.plan_application(self.esx, self.tpl, 200)
        self.assertEqual(got["orphanAreasIgnored"], 1)
        self.assertEqual(len(got["floors"]), 1)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = cap.USER_DIR
        cap.USER_DIR = Path(self.tmp.name) / "capacity"

    def tearDown(self):
        cap.USER_DIR = self._orig
        self.tmp.cleanup()

    def test_templates_are_saved_outside_the_install_tree(self):
        # The install folder is replaced wholesale by an update; anything the
        # user made has to sit somewhere else.
        self.assertNotIn(str(ROOT), str(self._orig))
        self.assertIn(".wd_wireless_tools", str(self._orig))

    def test_save_and_list_round_trip(self):
        tpl = {"name": "My Office", "items": [{"device": "d", "usage": "u", "perOccupant": 1.0}]}
        saved = cap.save_template(tpl)
        self.assertTrue(saved["ok"])
        names = [t["name"] for t in cap.list_templates()["templates"]]
        self.assertIn("My Office", names)

    def test_an_empty_template_is_refused(self):
        self.assertFalse(cap.save_template({"name": "x", "items": []})["ok"])

    def test_delete_refuses_to_escape_the_folder(self):
        got = cap.delete_template("../../etc/passwd")
        self.assertFalse(got["ok"])


if __name__ == "__main__":
    unittest.main()
