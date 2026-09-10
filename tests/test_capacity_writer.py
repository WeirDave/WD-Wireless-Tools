"""The Capacity writer — the only code in the tool that changes a project.

Every test here corresponds to a rule in the safety posture the writer was
specified under: don't touch the source, don't overwrite somebody's drawn area
without being asked, don't leave dangling profile references, and don't
overwrite a real project without a copy of it surviving.
"""
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tools import capacity_profiles as cap  # noqa: E402
from test_capacity_profiles import DEAD_FLOOR, FLOOR, build_esx  # noqa: E402


def members_of(path):
    with zipfile.ZipFile(path) as zf:
        return {n: json.loads(zf.read(n).decode("utf-8"))
                for n in zf.namelist() if n.endswith(".json")}


def capacity_areas(path):
    areas = (members_of(path).get("areas.json") or {}).get("areas", [])
    return [a for a in areas if a.get("capacityItems")]


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = Path(build_esx(self.dir / "src.esx"))
        # The source fixture's one live floor already carries a requirement
        # area, so a plain apply to it correctly writes nothing. Content tests
        # need a project with the profiles present but no areas drawn.
        self.blank = Path(build_esx(self.dir / "blank.esx", areas=[]))
        self.template = self._template()

    def tearDown(self):
        self.tmp.cleanup()

    def _template(self, occupants=500):
        got = cap.extract(self.src)
        tpl = cap.derive_template(got, occupants, "Office")
        self.assertTrue(tpl["ok"], tpl.get("error"))
        return tpl

    def _apply(self, dest=None, occupants=200, replace=False, template=None,
               src=None):
        dest = dest or (self.dir / "out.esx")
        r = cap.apply_to(src or self.src, dest, template or self.template,
                         occupants, replace_existing=replace)
        return r, dest

    def _apply_blank(self, occupants=200):
        """Apply to a project with nothing drawn on it, so a write happens."""
        r, dest = self._apply(dest=self.dir / "blank-out.esx",
                              occupants=occupants, src=self.blank)
        self.assertTrue(r["ok"], r.get("error"))
        return r, dest

    # ── the source is never touched ──────────────────────────────────────────

    def test_the_source_project_is_not_modified(self):
        before = self.src.read_bytes()
        r, _ = self._apply()
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(self.src.read_bytes(), before)

    # ── what it writes ───────────────────────────────────────────────────────

    def test_it_writes_an_openable_project_with_capacity_on_it(self):
        r, dest = self._apply_blank()
        self.assertTrue(zipfile.is_zipfile(dest))
        self.assertEqual(len(capacity_areas(dest)), 1)
        self.assertEqual(r["floorsWritten"], ["Level 1"])

    def test_every_row_survives_the_round_trip_unmerged(self):
        """Six rows in, six rows out - the same rule the capture side has."""
        r, dest = self._apply_blank()
        area = capacity_areas(dest)[0]
        self.assertEqual(len(area["capacityItems"]), 6)

    def test_counts_scale_to_the_headcount(self):
        r, dest = self._apply_blank(occupants=200)
        # 3 devices per person at 500 people; 200 people is 600 devices.
        self.assertEqual(r["totalDevices"], 600)
        area = capacity_areas(dest)[0]
        self.assertEqual(sum(i["deviceCount"] for i in area["capacityItems"]), 600)

    def test_written_items_carry_the_four_fields_ekahau_reads(self):
        _, dest = self._apply_blank()
        for item in capacity_areas(dest)[0]["capacityItems"]:
            self.assertEqual(sorted(item),
                             ["deviceCount", "deviceProfileId", "identifier", "usageProfileId"])

    def test_the_area_has_a_polygon_and_a_floor(self):
        _, dest = self._apply_blank()
        area = capacity_areas(dest)[0]
        self.assertEqual(len(area["area"]), 4)
        self.assertTrue(area["floorPlanId"])
        for vertex in area["area"]:
            self.assertEqual(sorted(vertex), ["x", "y"])

    # ── no dangling references ───────────────────────────────────────────────

    def test_no_capacity_item_points_at_a_profile_that_is_not_in_the_file(self):
        """The failure this guards against opens fine and is quietly wrong."""
        _, dest = self._apply_blank()
        members = members_of(dest)
        ids = set()
        for body in members.values():
            if not isinstance(body, dict):
                continue
            for val in body.values():
                if isinstance(val, list):
                    ids |= {o["id"] for o in val
                            if isinstance(o, dict) and isinstance(o.get("id"), str)}
        for area in capacity_areas(dest):
            if area.get("requirementId"):
                self.assertIn(area["requirementId"], ids)
            for item in area["capacityItems"]:
                self.assertIn(item["deviceProfileId"], ids)
                self.assertIn(item["usageProfileId"], ids)

    def test_applying_to_a_project_without_the_profiles_injects_them(self):
        bare = Path(build_esx(self.dir / "bare.esx", with_capacity=False))
        r = cap.apply_to(bare, self.dir / "bare-out.esx", self.template, 100)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertTrue(r["profilesCreated"])
        out = members_of(self.dir / "bare-out.esx")
        names = set()
        for body in out.values():
            for key, val in (body or {}).items():
                if key in ("deviceProfiles", "usageProfiles") and isinstance(val, list):
                    names |= {o.get("name") for o in val}
        self.assertTrue(any("Laptop" in (n or "") for n in names))

    def test_injected_profiles_get_new_ids_not_the_sources(self):
        """Applying a template to the project it came from must not collide."""
        bare = Path(build_esx(self.dir / "bare.esx", with_capacity=False))
        r = cap.apply_to(bare, self.dir / "bare-out.esx", self.template, 100)
        self.assertTrue(r["ok"], r.get("error"))
        source_ids = set()
        for chain in (self.template["profileDefs"]["devices"] or {}).values():
            source_ids |= {link["obj"]["id"] for link in chain}
        out = capacity_areas(self.dir / "bare-out.esx")[0]
        written = {i["deviceProfileId"] for i in out["capacityItems"]}
        self.assertFalse(written & source_ids)

    def test_a_template_with_no_definitions_and_no_match_refuses(self):
        """Refusing beats writing a project that is quietly wrong."""
        bare = Path(build_esx(self.dir / "bare.esx", with_capacity=False))
        stripped = json.loads(json.dumps(self.template))
        stripped["profileDefs"] = {}
        r = cap.apply_to(bare, self.dir / "nope.esx", stripped, 100)
        self.assertFalse(r["ok"])
        self.assertTrue(r["missing"])
        self.assertFalse((self.dir / "nope.esx").exists())

    def test_existing_profiles_are_reused_not_duplicated(self):
        _, dest = self._apply_blank()
        out = members_of(dest)
        devices = []
        for body in out.values():
            for key, val in (body or {}).items():
                if key == "deviceProfiles" and isinstance(val, list):
                    devices += [o.get("name") for o in val]
        self.assertEqual(len(devices), len(set(devices)))

    # ── somebody's drawn area ────────────────────────────────────────────────

    def test_a_floor_that_already_has_a_requirement_area_is_left_alone(self):
        r, dest = self._apply(replace=False)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["floorsWritten"], [])
        self.assertTrue(r["floorsSkipped"])
        self.assertEqual(r["areasReplaced"], 0)

    def test_an_apply_that_skips_every_floor_writes_no_file_at_all(self):
        """Nothing to do means nothing written, not a copy that looks changed."""
        r, dest = self._apply(replace=False)
        self.assertTrue(r["ok"])
        self.assertIsNone(r["written"])
        self.assertFalse(dest.exists())
        self.assertIn("not changed", r["note"])

    def test_profiles_are_not_injected_when_no_area_will_be_written(self):
        """The bug this guards: 5 profiles added to a project, used by nothing."""
        no_capacity_but_has_areas = Path(build_esx(
            self.dir / "zoned.esx",
            areas=[{"id": "zone-1", "floorPlanId": FLOOR, "requirementId": "req-1",
                    "area": [{"x": 10.0, "y": 10.0}, {"x": 20.0, "y": 20.0}]}]))
        r = cap.apply_to(no_capacity_but_has_areas, self.dir / "zoned-out.esx",
                         self.template, 100)
        self.assertTrue(r["ok"])
        self.assertEqual(r["profilesCreated"], [])
        self.assertFalse((self.dir / "zoned-out.esx").exists())

    def test_a_coverage_zone_with_no_capacity_is_not_deleted_by_a_replace(self):
        """Replacing a capacity template is not permission to delete a zone."""
        mixed = Path(build_esx(self.dir / "mixed.esx", areas=[
            {"id": "cap-area", "floorPlanId": FLOOR, "requirementId": "req-1",
             "capacityItems": [{"deviceCount": 10, "deviceProfileId": "dev-laptop",
                                "usageProfileId": "use-normal"}],
             "area": [{"x": 10.0, "y": 10.0}, {"x": 20.0, "y": 20.0}]},
            {"id": "lobby", "name": "Lobby", "floorPlanId": FLOOR,
             "requirementId": "req-1",
             "area": [{"x": 30.0, "y": 30.0}, {"x": 40.0, "y": 40.0}]},
        ]))
        r = cap.apply_to(mixed, self.dir / "mixed-out.esx", self.template, 100,
                         replace_existing=True)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["areasReplaced"], 1)
        self.assertEqual(r["areasLeftInPlace"], 1)
        surviving = (members_of(self.dir / "mixed-out.esx")["areas.json"]["areas"])
        self.assertIn("lobby", [a["id"] for a in surviving])

    def test_replacement_happens_only_when_it_is_asked_for(self):
        r, dest = self._apply(replace=True)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertTrue(r["floorsWritten"])
        self.assertEqual(r["areasReplaced"], 1)

    def test_replacing_does_not_leave_the_old_area_behind(self):
        r, dest = self._apply(replace=True, occupants=200)
        live = [a for a in capacity_areas(dest) if a["floorPlanId"] == FLOOR]
        self.assertEqual(len(live), 1)
        self.assertEqual(sum(i["deviceCount"] for i in live[0]["capacityItems"]), 600)

    def test_replacing_leaves_the_orphaned_area_alone(self):
        """It belongs to a deleted floor. Reported, ignored, not deleted."""
        before = [a for a in capacity_areas(self.src) if a["floorPlanId"] == DEAD_FLOOR]
        r, dest = self._apply(replace=True)
        self.assertEqual(r["orphanAreasIgnored"], 1)
        after = [a for a in capacity_areas(dest) if a["floorPlanId"] == DEAD_FLOOR]
        self.assertEqual(after, before)

    def test_areas_on_other_floors_are_not_disturbed_by_a_replace(self):
        bare = Path(build_esx(self.dir / "two.esx", with_capacity=True, extra_floor=True))
        r = cap.apply_to(bare, self.dir / "two-out.esx", self.template, 100,
                         replace_existing=True)
        self.assertTrue(r["ok"], r.get("error"))
        # Both floors get one area each and neither ends up with two.
        by_floor = {}
        for a in capacity_areas(self.dir / "two-out.esx"):
            by_floor.setdefault(a["floorPlanId"], []).append(a)
        for fid, got in by_floor.items():
            self.assertEqual(len(got), 1, fid)

    # ── overwriting a real project ───────────────────────────────────────────

    def test_overwriting_an_existing_file_keeps_a_copy_of_it(self):
        dest = self.dir / "existing.esx"
        dest.write_bytes(self.src.read_bytes())
        original = dest.read_bytes()
        r, _ = self._apply(dest=dest, replace=True)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertTrue(r["backup"])
        backup = Path(r["backup"])
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_bytes(), original)
        self.assertNotEqual(dest.read_bytes(), original)

    def test_backup_can_be_turned_off_deliberately(self):
        dest = self.dir / "existing.esx"
        dest.write_bytes(self.src.read_bytes())
        r = cap.apply_to(self.src, dest, self.template, 100,
                         replace_existing=True, backup=False)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertIsNone(r["backup"])

    def test_a_refusal_leaves_no_temporary_files_behind(self):
        bare = Path(build_esx(self.dir / "bare.esx", with_capacity=False))
        stripped = json.loads(json.dumps(self.template))
        stripped["profileDefs"] = {}
        before = sorted(p.name for p in self.dir.iterdir())
        cap.apply_to(bare, self.dir / "nope.esx", stripped, 100)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), before)

    # ── non-JSON members ─────────────────────────────────────────────────────

    def test_the_floor_plan_image_is_carried_across_untouched(self):
        """An .esx is mostly bitmaps; losing them would be catastrophic."""
        with zipfile.ZipFile(self.blank) as zf:
            originals = {n: zf.read(n) for n in zf.namelist() if not n.endswith(".json")}
        self.assertTrue(originals, "fixture should carry at least one non-JSON member")
        _, dest = self._apply_blank()
        with zipfile.ZipFile(dest) as zf:
            for name, blob in originals.items():
                self.assertIn(name, zf.namelist())
                self.assertEqual(zf.read(name), blob)

    # ── a bad headcount ──────────────────────────────────────────────────────

    def test_zero_people_is_refused_before_anything_is_written(self):
        r = cap.apply_to(self.src, self.dir / "zero.esx", self.template, 0)
        self.assertFalse(r["ok"])
        self.assertFalse((self.dir / "zero.esx").exists())


if __name__ == "__main__":
    unittest.main()
