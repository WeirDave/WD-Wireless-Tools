"""Auditing projects for furniture modelled floor-to-ceiling.

The report has to be trustworthy in both directions: it must not miss a
warehouse full of racking on Auto height, and it must not cry wolf about a wall
type that is merely defined and never drawn - his projects contain several of
those, named "Walls, Steel 12ft" and the like, with no segments at all.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.wall_audit import audit_folder, audit_project, repair_project  # noqa: E402

FT = 0.3048


def _wall_type(name, db_per_m, thickness, upper=None, tid=None):
    w = {
        "name": name, "key": name.replace(" ", ""), "color": "#888888",
        "propagationProperties": [
            {"band": b, "attenuationFactor": db_per_m,
             "reflectionCoefficient": 0.1, "diffractionCoefficient": 11.0}
            for b in ("FIVE", "SIX", "TWO")
        ],
        "thickness": thickness, "lowerEdge": 0.0,
        "id": tid or name.replace(" ", "-").lower(), "status": "CREATED",
    }
    if upper is not None:
        w["upperEdge"] = upper
    return w


def _project(path: Path, types, segment_counts):
    segs = []
    n = 0
    for tid, count in segment_counts.items():
        for _ in range(count):
            n += 1
            segs.append({"point1Id": f"p{n}a", "point2Id": f"p{n}b",
                         "wallTypeId": tid, "id": f"s{n}", "status": "CREATED"})
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("wallTypes.json", json.dumps({"wallTypes": types}))
        z.writestr("wallSegments.json", json.dumps({"wallSegments": segs}))
        z.writestr("floorPlans.json", json.dumps({"floorPlans": [
            {"id": "f1", "name": "1", "width": 100.0, "height": 80.0,
             "metersPerUnit": 0.05}]}))
        z.writestr("project.json", json.dumps({"project": {"name": path.stem}}))


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-wallaudit-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_racking_on_auto_height_is_reported(self):
        p = self.tmp / "warehouse.esx"
        _project(p, [_wall_type("Shelf, Warehouse", 18.0, 1.5, tid="sw")],
                 {"sw": 52})
        r = audit_project(p)
        self.assertEqual(len(r.findings), 1)
        f = r.findings[0]
        self.assertEqual(f.wall_type, "Shelf, Warehouse")
        self.assertEqual(f.segments, 52)
        self.assertAlmostEqual(f.db_total, 27.0)
        self.assertAlmostEqual(f.severity, 27.0 * 52)

    def test_a_type_that_already_has_a_height_is_left_alone(self):
        p = self.tmp / "ok.esx"
        _project(p, [_wall_type("Shelf, Warehouse", 18.0, 1.5, upper=10.0, tid="sw")],
                 {"sw": 52})
        self.assertEqual(audit_project(p).findings, [])

    def test_a_type_defined_but_never_drawn_is_not_reported(self):
        """His projects carry several of these; reporting them is noise."""
        p = self.tmp / "unused.esx"
        _project(p, [_wall_type("Walls, Steel 12ft", 45.71, 0.35, tid="steel"),
                     _wall_type("Wall, Concrete", 24.0, 0.5, tid="conc")],
                 {"conc": 8})
        self.assertEqual(audit_project(p).findings, [])

    def test_an_ordinary_wall_is_not_reported(self):
        p = self.tmp / "walls.esx"
        _project(p, [_wall_type("Wall, Concrete", 24.0, 0.5, tid="c")], {"c": 30})
        self.assertEqual(audit_project(p).findings, [])

    def test_a_height_in_the_name_beats_a_lookup(self):
        p = self.tmp / "named.esx"
        _project(p, [_wall_type("Warehouse Rack Wall - 16ft", 45.71, 0.35, tid="r")],
                 {"r": 6})
        f = audit_project(p).findings[0]
        self.assertAlmostEqual(f.suggested_m, round(16 * FT, 4), places=3)
        self.assertIn("stated in the name", f.suggestion_source)

    def test_no_height_is_invented_when_nothing_says_one(self):
        p = self.tmp / "unknown.esx"
        _project(p, [_wall_type("Warehouse Rack Wall", 45.71, 0.35, tid="r")],
                 {"r": 6})
        f = audit_project(p).findings[0]
        self.assertIsNone(f.suggested_m,
                          "inventing a height is what put wrong values in the "
                          "shipped templates")
        self.assertIn("needs a decision", f.suggestion_source)

    def test_the_worst_project_sorts_first(self):
        big = self.tmp / "warehouse.esx"
        small = self.tmp / "office.esx"
        _project(big, [_wall_type("Shelf, Warehouse", 18.0, 1.5, tid="sw")], {"sw": 52})
        _project(small, [_wall_type("Cubicle", 10.0, 0.1, tid="cu")], {"cu": 4})
        order = [r.path.name for r in audit_folder(self.tmp)]
        self.assertEqual(order[0], "warehouse.esx",
                         "1404 dB-segments should outrank 4")

    def test_an_unreadable_project_is_reported_not_skipped(self):
        bad = self.tmp / "broken.esx"
        bad.write_bytes(b"this is not a zip")
        r = audit_project(bad)
        self.assertTrue(r.error)
        self.assertEqual(r.findings, [])


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-wallfix-"))
        self.p = self.tmp / "warehouse.esx"
        _project(self.p, [_wall_type("Shelf, Warehouse", 18.0, 1.5, tid="sw"),
                          _wall_type("Wall, Concrete", 24.0, 0.5, tid="c")],
                 {"sw": 52, "c": 10})
        self.before = self._members()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _members(self):
        with zipfile.ZipFile(self.p) as z:
            return {n: z.read(n) for n in z.namelist()}

    def test_it_sets_the_height_and_keeps_the_previous_copy(self):
        res = repair_project(self.p, {"Shelf, Warehouse": 10.0})
        self.assertTrue(res.get("ok"), res)

        with zipfile.ZipFile(self.p) as z:
            types = json.loads(z.read("wallTypes.json"))["wallTypes"]
        by_name = {w["name"]: w for w in types}
        self.assertEqual(by_name["Shelf, Warehouse"]["upperEdge"], 10.0)
        self.assertNotIn("upperEdge", by_name["Wall, Concrete"])

        backups = list(self.tmp.glob("*.previous-*"))
        self.assertEqual(len(backups), 1)
        with zipfile.ZipFile(backups[0]) as z:
            kept = json.loads(z.read("wallTypes.json"))["wallTypes"]
        self.assertNotIn("upperEdge", {w["name"]: w for w in kept}["Shelf, Warehouse"])

    def test_everything_except_the_wall_types_is_byte_identical(self):
        repair_project(self.p, {"Shelf, Warehouse": 10.0})
        after = self._members()
        self.assertEqual(set(after), set(self.before), "a member appeared or vanished")
        for name in self.before:
            if name == "wallTypes.json":
                continue
            with self.subTest(member=name):
                self.assertEqual(after[name], self.before[name])

    def test_metersperunit_survives(self):
        repair_project(self.p, {"Shelf, Warehouse": 10.0})
        with zipfile.ZipFile(self.p) as z:
            fp = json.loads(z.read("floorPlans.json"))["floorPlans"][0]
        self.assertEqual(fp["metersPerUnit"], 0.05,
                         "scale drift ruins every attenuation downstream")

    def test_a_type_that_already_has_a_height_is_not_overwritten(self):
        repair_project(self.p, {"Shelf, Warehouse": 10.0})
        res = repair_project(self.p, {"Shelf, Warehouse": 3.0})
        self.assertTrue(res.get("error"), "there was nothing left to change")
        with zipfile.ZipFile(self.p) as z:
            types = {w["name"]: w for w in
                     json.loads(z.read("wallTypes.json"))["wallTypes"]}
        self.assertEqual(types["Shelf, Warehouse"]["upperEdge"], 10.0)

    def test_a_top_below_the_floor_is_refused(self):
        res = repair_project(self.p, {"Shelf, Warehouse": 0.0})
        self.assertIn("not above", res.get("error", ""))
        self.assertEqual(self._members(), self.before)
        self.assertEqual(list(self.tmp.glob("*.previous-*")), [])

    def test_a_name_that_is_not_in_the_project_is_reported(self):
        res = repair_project(self.p, {"Nonexistent Type": 2.0})
        self.assertTrue(res.get("error"))
        self.assertIn("nonexistent type", [n for n in res.get("notFound", [])])
        self.assertEqual(self._members(), self.before)

    def test_no_temp_file_is_left_behind(self):
        repair_project(self.p, {"Shelf, Warehouse": 10.0})
        self.assertEqual(list(self.tmp.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
