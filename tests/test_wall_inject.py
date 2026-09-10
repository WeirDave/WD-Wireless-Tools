"""Putting a wall-type template into an .esx from Python.

Quick Walls has always done this in the browser. That is the wrong place for a
preparation pass that also trims the canvas and injects a requirement area,
because both of those are Python - the file would bounce to the server and back
mid-pass, which is the round trip the pass exists to remove.

Two decisions this file holds.

**Adding, not swapping.** `wallSegments.json` is never touched. Quick Walls
remaps drawn segments from one type to another; preparation just makes the types
available to draw with. Nothing already drawn changes.

**A type already in the project wins.** Replacing a "Concrete" that the project
already has would silently change the attenuation of every wall already drawn
with it - a design change wearing the clothes of a setup step. It is skipped,
and the skip is reported.
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

from tools import wall_inject  # noqa: E402


def wall_type(name, attenuation=5.0, wt_id=None):
    return {
        "name": name,
        "key": name,
        "color": "#B07842",
        "propagationProperties": [
            {"band": b, "attenuationFactor": attenuation,
             "reflectionCoefficient": 0.25, "diffractionCoefficient": 11}
            for b in ("TWO", "FIVE", "SIX")
        ],
        "thickness": 0.1,
        "lowerEdge": 0,
        "id": wt_id or ("id-" + name.lower().replace(" ", "-")),
    }


def make_esx(path: Path, types, extra=None):
    members = {
        "project.json": json.dumps({"project": {"name": "Fixture"}}),
        "wallTypes.json": json.dumps({"wallTypes": types}),
        "wallSegments.json": json.dumps({"wallSegments": [
            {"id": "seg-1", "wallTypeId": types[0]["id"] if types else "x"}]}),
        "floorPlans.json": json.dumps({"floorPlans": [
            {"id": "f1", "name": "Floor 1", "width": 1000, "height": 800,
             "metersPerUnit": 0.0251}]}),
    }
    members.update(extra or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, blob in members.items():
            z.writestr(name, blob)
    return path


def read_member(path, name):
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read(name))


class WallInjection(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-inject-"))
        self.esx = make_esx(self.tmp / "Project.esx",
                            [wall_type("Concrete", 30.0), wall_type("Drywall", 3.0)])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_types_are_added(self):
        report = wall_inject.inject(
            self.esx, [wall_type("Framery Pod"), wall_type("Glass")])
        self.assertTrue(report.get("ok"), report)
        names = [w["name"] for w in read_member(self.esx, "wallTypes.json")["wallTypes"]]
        self.assertEqual(names, ["Concrete", "Drywall", "Framery Pod", "Glass"])

    def test_a_type_the_project_already_has_is_left_alone(self):
        """Its attenuation belongs to walls already drawn with it."""
        report = wall_inject.inject(self.esx, [wall_type("Concrete", 3.0)])
        self.assertEqual(report["add"], [])
        self.assertEqual([s["name"] for s in report["skip"]], ["Concrete"])
        kept = [w for w in read_member(self.esx, "wallTypes.json")["wallTypes"]
                if w["name"] == "Concrete"][0]
        self.assertEqual(kept["propagationProperties"][0]["attenuationFactor"], 30.0,
                         "the project's own value was overwritten")

    def test_matching_is_by_name_not_by_id(self):
        """A template captured from another project carries that project's ids,
        and two projects will never agree on them."""
        report = wall_inject.inject(
            self.esx, [wall_type("  concrete  ", 3.0, wt_id="totally-different")])
        self.assertEqual(report["add"], [], "a name match was missed")

    def test_nothing_but_the_wall_types_member_changes(self):
        """metersPerUnit, the segments and everything else pass through."""
        before = {}
        with zipfile.ZipFile(self.esx) as z:
            for n in z.namelist():
                before[n] = z.read(n)
        wall_inject.inject(self.esx, [wall_type("Framery Pod")])
        with zipfile.ZipFile(self.esx) as z:
            after = {n: z.read(n) for n in z.namelist()}
        self.assertEqual(set(before), set(after), "a member was added or lost")
        for name in before:
            if name == "wallTypes.json":
                continue
            with self.subTest(member=name):
                self.assertEqual(before[name], after[name],
                                 f"{name} was rewritten and should not have been")

    def test_drawn_walls_are_never_remapped(self):
        """This adds types; it does not swap what is already drawn."""
        before = read_member(self.esx, "wallSegments.json")
        wall_inject.inject(self.esx, [wall_type("Framery Pod")])
        self.assertEqual(read_member(self.esx, "wallSegments.json"), before)

    def test_a_backup_is_taken_before_writing_in_place(self):
        wall_inject.inject(self.esx, [wall_type("Framery Pod")])
        backups = list(self.tmp.glob("Project.previous-*.esx"))
        self.assertEqual(len(backups), 1, "no backup was kept")
        self.assertEqual(
            [w["name"] for w in read_member(backups[0], "wallTypes.json")["wallTypes"]],
            ["Concrete", "Drywall"], "the backup is not the original")

    def test_writing_to_a_destination_leaves_the_source_untouched(self):
        """How the preparation pass chains steps without a backup per step."""
        dest = self.tmp / "Prepared.esx"
        report = wall_inject.inject(self.esx, [wall_type("Framery Pod")], dest=dest)
        self.assertTrue(report["ok"])
        self.assertIsNone(report["backup"])
        self.assertEqual(
            len(read_member(self.esx, "wallTypes.json")["wallTypes"]), 2)
        self.assertEqual(
            len(read_member(dest, "wallTypes.json")["wallTypes"]), 3)

    def test_a_colliding_id_gets_a_fresh_one(self):
        """Two projects can legitimately carry the same id. Overwriting
        whatever already answers to it is not an option."""
        report = wall_inject.inject(
            self.esx, [wall_type("Framery Pod", wt_id="id-concrete")])
        self.assertTrue(report["ok"])
        types = read_member(self.esx, "wallTypes.json")["wallTypes"]
        ids = [w["id"] for w in types]
        self.assertEqual(len(ids), len(set(ids)), "duplicate ids were written")
        pod = [w for w in types if w["name"] == "Framery Pod"][0]
        self.assertNotEqual(pod["id"], "id-concrete")

    def test_the_preview_and_the_write_describe_themselves_identically(self):
        """A preview that is a second description of the work drifts from it."""
        types = [wall_type("Framery Pod"), wall_type("Concrete", 3.0)]
        preview = wall_inject.plan_injection(self.esx, types)
        report = wall_inject.inject(self.esx, types)
        self.assertEqual(preview["add"], report["add"])
        self.assertEqual(preview["skip"], report["skip"])

    def test_a_second_run_adds_nothing_and_writes_nothing(self):
        """Re-runnable: running the pass again must not pile up duplicates."""
        types = [wall_type("Framery Pod")]
        wall_inject.inject(self.esx, types)
        again = wall_inject.inject(self.esx, types)
        self.assertTrue(again["ok"])
        self.assertFalse(again["written"], "it rewrote the file for no change")
        self.assertEqual(
            len(read_member(self.esx, "wallTypes.json")["wallTypes"]), 3)

    def test_it_refuses_what_it_cannot_verify(self):
        broken = make_esx(self.tmp / "NoTypes.esx", [])
        with zipfile.ZipFile(broken, "w") as z:
            z.writestr("project.json", "{}")
        self.assertIn("error", wall_inject.inject(broken, [wall_type("X")]))

        garbled = self.tmp / "Garbled.esx"
        with zipfile.ZipFile(garbled, "w") as z:
            z.writestr("wallTypes.json", "{not json")
        self.assertIn("error", wall_inject.inject(garbled, [wall_type("X")]))

        self.assertIn("error", wall_inject.inject(self.tmp / "absent.esx", []))

    def test_an_unnamed_template_entry_is_skipped_with_a_reason(self):
        report = wall_inject.inject(self.esx, [{"thickness": 0.1}])
        self.assertEqual(report["add"], [])
        self.assertIn("no name", report["skip"][0]["why"])


if __name__ == "__main__":
    unittest.main()
