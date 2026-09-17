"""Comparing the two copies instead of guessing from timestamps.

Staleness was two `history.modifiedAt` values, one from inside the local file
and one from the cloud's project record. A rename moves that timestamp, so
renaming sixty projects into a new naming convention produced sixty rows
claiming there was newer work in the cloud, and the truthful answer to "is it
safe to pull them all" was that the tool could not tell.

"I don't know why we can't just compare a local file with the cloud file ...
seems like basic engineering, man." Correct, and the objection that had been
holding it up was aimed at the wrong thing: non-deterministic ZIP assembly
rules out hashing the *archive*, not comparing the *contents*.

The cases below are the ones that decide whether the answer is trustworthy:
a rename must read as a rename, a moved access point must read as a real
change, and a re-cropped floor plan - his normal PlanTrim workflow - must not
slip through a document-only comparison.
"""
from __future__ import annotations

import io
import json
import unittest
import zipfile

from tools.esx_compare import compare_esx


def esx(project_name="SITE1 Survey", modified="2026-01-01T00:00:00Z",
        aps=None, image=b"PNGDATA-original", extra=None, walls=2):
    """A minimal archive shaped like the real thing."""
    aps = aps if aps is not None else [
        {"id": "ap-1", "name": "AP 1", "x": 10, "y": 20},
        {"id": "ap-2", "name": "AP 2", "x": 30, "y": 40},
    ]
    members = {
        "version": b"2.0",
        "project.json": {"project": {
            "id": "proj-uuid", "name": project_name,
            "history": {"createdBy": "someone", "modifiedAt": modified,
                        "modifiedBy": "someone"},
        }},
        "projectHistorys.json": {"projectHistorys": [
            {"id": "h-1", "modifiedAt": modified},
        ]},
        "accessPoints.json": {"accessPoints": aps},
        "floorPlans.json": {"floorPlans": [
            {"id": "fp-1", "name": "Floor 1", "imageId": "img-1"},
        ]},
        "wallSegments.json": {"wallSegments": [
            {"id": "w-%d" % i, "type": "brick"} for i in range(walls)
        ]},
    }
    if extra:
        members.update(extra)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, value in members.items():
            zf.writestr(name, value if isinstance(value, bytes)
                        else json.dumps(value))
        zf.writestr("image-img-1", image)
    return buf.getvalue()


class TheComparisonTellsRenamesFromRealChangesTests(unittest.TestCase):

    def test_the_same_project_twice_is_identical(self):
        r = compare_esx(esx(), esx())
        self.assertTrue(r["identical"])
        self.assertFalse(r["designDiffers"])
        self.assertIn("Identical", r["summary"])

    def test_a_different_modified_timestamp_alone_is_not_a_change(self):
        """The whole point. This is the case that produced sixty false alarms:
        the clock moved and nothing else did."""
        r = compare_esx(esx(modified="2026-01-01T00:00:00Z"),
                        esx(modified="2026-09-17T12:00:00Z"))
        self.assertTrue(r["identical"])
        self.assertFalse(r["designDiffers"])

    def test_a_rename_reads_as_a_rename_and_not_as_newer_work(self):
        r = compare_esx(esx(project_name="SITE1 Old Name"),
                        esx(project_name="SITE1 New Convention",
                            modified="2026-09-17T12:00:00Z"))
        self.assertTrue(r["renamedOnly"])
        self.assertFalse(r["designDiffers"])
        self.assertIn("Same design", r["summary"])

    def test_it_says_which_of_the_three_names_differs(self):
        """"A different name on each side" was useless to him, because he was
        looking at two identical names while being told they differed.

        Three names are in play: the file on disk, the project name inside
        `project.json`, and the cloud project's name. Renaming a file does not
        touch the one inside it, so after renaming a fleet to a new convention
        the two he can see agree and the hidden one does not.
        """
        r = compare_esx(
            esx(project_name="SITE1 Old Name"),
            esx(project_name="SITE1 New Convention"),
            local_file_stem="SITE1 New Convention")
        self.assertEqual("internal_only", r["nameState"])
        self.assertIn("project name inside the file", r["summary"])
        self.assertIn("file names match", r["summary"])

    def test_a_file_renamed_on_disk_alone_is_named_as_that(self):
        r = compare_esx(
            esx(project_name="SITE1 Shared Name"),
            esx(project_name="SITE1 Shared Name"),
            local_file_stem="something-else")
        self.assertEqual("file_only", r["nameState"])
        self.assertIn("file on disk", r["summary"])

    def test_both_names_differing_says_both(self):
        r = compare_esx(
            esx(project_name="SITE1 Old Name"),
            esx(project_name="SITE1 New Convention"),
            local_file_stem="SITE1 Older Still")
        self.assertEqual("both", r["nameState"])

    def test_everything_agreeing_reports_no_name_difference(self):
        r = compare_esx(esx(project_name="SITE1 Survey"),
                        esx(project_name="SITE1 Survey"),
                        local_file_stem="SITE1 Survey")
        self.assertEqual("same", r["nameState"])
        self.assertTrue(r["identical"])

    def test_without_the_file_name_it_does_not_guess(self):
        """The caller may not know the file name. Reporting `internal_only`
        on an assumption would be a fact he could check and find wrong."""
        r = compare_esx(esx(project_name="A"), esx(project_name="B"))
        self.assertIn(r["nameState"], ("internal_only", "both"))
        self.assertTrue(r["renamedOnly"])

    def test_a_moved_access_point_is_a_real_change(self):
        moved = [{"id": "ap-1", "name": "AP 1", "x": 999, "y": 20},
                 {"id": "ap-2", "name": "AP 2", "x": 30, "y": 40}]
        r = compare_esx(esx(), esx(aps=moved))
        self.assertTrue(r["designDiffers"])
        self.assertFalse(r["renamedOnly"])
        self.assertIn("accessPoints", r["summary"])
        self.assertIn("1 changed", r["summary"])

    def test_it_counts_what_differs_rather_than_only_that_something_does(self):
        """"3 access points differ" is a fact he can act on; "this file is
        different" is another label to distrust."""
        added = [{"id": "ap-1", "name": "AP 1", "x": 10, "y": 20},
                 {"id": "ap-3", "name": "AP 3", "x": 50, "y": 60}]
        r = compare_esx(esx(), esx(aps=added))
        summary = r["summary"]
        self.assertIn("1 added", summary)
        self.assertIn("1 removed", summary)

    def test_a_recropped_floor_plan_image_is_detected(self):
        """The blind spot a document-only comparison would have, and it is his
        normal workflow - PlanTrim re-crops the plan and every JSON member
        stays byte-identical."""
        r = compare_esx(esx(image=b"PNGDATA-original"),
                        esx(image=b"PNGDATA-recropped-smaller"))
        self.assertTrue(r["designDiffers"])
        self.assertIn("floor plan image", r["summary"])
        self.assertEqual(1, r["imagesCompared"])

    def test_a_rename_and_a_real_change_together_report_both(self):
        """A rename must not mask a redesign hiding behind it."""
        moved = [{"id": "ap-1", "name": "AP 1", "x": 777, "y": 20}]
        r = compare_esx(esx(project_name="Old"),
                        esx(project_name="New", aps=moved))
        self.assertTrue(r["designDiffers"])
        self.assertFalse(r["renamedOnly"])
        self.assertIn("also renamed", r["summary"])

    def test_walls_are_compared_too(self):
        r = compare_esx(esx(walls=2), esx(walls=5))
        self.assertTrue(r["designDiffers"])
        self.assertIn("wallSegments", r["summary"])

    def test_a_member_present_on_only_one_side_counts(self):
        r = compare_esx(esx(), esx(extra={"areas.json": {"areas": [
            {"id": "a-1", "name": "Requirement"}]}}))
        self.assertTrue(r["designDiffers"])

    def test_revision_history_alone_is_not_a_design_change(self):
        """`projectHistorys` grows on every save, including a rename. Treating
        it as a design difference would put every project back in the pile
        this exists to empty."""
        other = esx(extra={"projectHistorys.json": {"projectHistorys": [
            {"id": "h-1", "modifiedAt": "2026-01-01T00:00:00Z"},
            {"id": "h-2", "modifiedAt": "2026-09-17T12:00:00Z"},
        ]}})
        r = compare_esx(esx(), other)
        self.assertFalse(r["designDiffers"])
        self.assertIn("No design change", r["summary"])

    def test_a_corrupt_archive_is_reported_rather_than_raising(self):
        r = compare_esx(b"not a zip at all", esx())
        self.assertIn("error", r)

    def test_it_never_reports_a_value_from_the_project(self):
        """Counts, ids and member names only. A comparison that printed the
        project's own strings would put site data into a log, a toast and a
        support screenshot."""
        r = compare_esx(esx(project_name="SITE1 Old Name"),
                        esx(project_name="SITE1 New Convention",
                            aps=[{"id": "ap-1", "name": "Lobby North", "x": 1}]))
        blob = json.dumps(r)
        self.assertNotIn("Lobby North", blob)
        self.assertNotIn("SITE1 Old Name", blob)
        self.assertNotIn("SITE1 New Convention", blob)


if __name__ == "__main__":
    unittest.main()
