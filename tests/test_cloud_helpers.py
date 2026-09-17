from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.cloud_manager import (
    _assert_inside,
    _dup_key,
    _esx_meta,
    _esx_project_type,
    build_matches,
    discriminators_reason,
    extract_site_code,
    fuzzy_similarity,
)

from tests.esx_factory import PROJECT_ID, make_esx


def cloud(name, project_id="", mtime=0):
    return {"id": project_id, "name": name, "mtime": mtime,
            "code": extract_site_code(name)}


def local(name, path, project_id="", project_name=None, mtime=0):
    """`project_name` is the name stored *inside* the .esx, which is a record
    of what the cloud called the project when this copy was taken. Defaults to
    the file name so existing tests keep describing an in-sync pair."""
    return {"name": name, "path": path, "projectId": project_id,
            "projectName": name if project_name is None else project_name,
            "mtime": mtime,
            "code": extract_site_code(name)}


class ARenameIsNotNewerWorkTests(unittest.TestCase):
    """Renaming a project must not read as somebody redesigning it.

    The comparison used to be two `history.modifiedAt` values and nothing
    else, so a rename - which is metadata, not the project - moved the clock
    and the row said "cloud newer". Renaming a hundred cloud projects to a new
    naming convention therefore produced a hundred rows that were
    indistinguishable from a hundred projects with newer work in them, and the
    only truthful answer to "is a bulk download safe" was that the tool could
    not tell.

    The discriminator is the name stored *inside* the .esx. A local copy
    records what the cloud called the project at download time, so a
    divergence means one side has been renamed since.
    """

    HOUR = 3600

    def test_a_cloud_rename_reports_itself_as_a_rename(self):
        """The case he is sitting in front of: renamed cloud-side, untouched
        locally, and the clock moved because of the rename."""
        clouds = [cloud("SITE1 New Convention", PROJECT_ID, mtime=2 * self.HOUR)]
        locals_ = [local("SITE1 Old Name", "C:/a.esx", PROJECT_ID,
                         project_name="SITE1 Old Name", mtime=self.HOUR)]
        pair = build_matches(clouds, locals_)["matched"][0]
        self.assertEqual(pair["staleness"], "cloud_newer")
        self.assertEqual(pair["differenceKind"], "renamed")

    def test_real_newer_work_still_reports_as_content(self):
        """The distinction is only worth having if the other case survives it.
        Same name on both sides, cloud ahead - that is real work."""
        clouds = [cloud("SITE1 Same Name", PROJECT_ID, mtime=2 * self.HOUR)]
        locals_ = [local("SITE1 Same Name", "C:/a.esx", PROJECT_ID,
                         project_name="SITE1 Same Name", mtime=self.HOUR)]
        pair = build_matches(clouds, locals_)["matched"][0]
        self.assertEqual(pair["staleness"], "cloud_newer")
        self.assertEqual(pair["differenceKind"], "content")

    def test_a_rename_in_ekahau_locally_is_recognised_too(self):
        """Renaming inside Ekahau bumps the local clock and the internal name
        together, so the same evidence reads in the other direction."""
        clouds = [cloud("SITE1 Old Name", PROJECT_ID, mtime=self.HOUR)]
        locals_ = [local("SITE1 Old Name", "C:/a.esx", PROJECT_ID,
                         project_name="SITE1 Renamed In Ekahau",
                         mtime=2 * self.HOUR)]
        pair = build_matches(clouds, locals_)["matched"][0]
        self.assertEqual(pair["staleness"], "local_newer")
        self.assertEqual(pair["differenceKind"], "renamed")

    def test_an_unreadable_internal_name_says_nothing(self):
        """An older file, or one whose project.json would not parse, has no
        internal name to compare. Reporting that as "content" would be a false
        alarm and as "renamed" a false reassurance, so it reports neither."""
        clouds = [cloud("SITE1 Anything", PROJECT_ID, mtime=2 * self.HOUR)]
        locals_ = [local("SITE1 Anything", "C:/a.esx", PROJECT_ID,
                         project_name="", mtime=self.HOUR)]
        pair = build_matches(clouds, locals_)["matched"][0]
        self.assertEqual(pair["staleness"], "cloud_newer")
        self.assertIsNone(pair["differenceKind"])

    def test_a_pair_in_sync_has_no_difference_to_classify(self):
        clouds = [cloud("SITE1 Same", PROJECT_ID, mtime=self.HOUR)]
        locals_ = [local("SITE1 Same", "C:/a.esx", PROJECT_ID,
                         project_name="SITE1 Same", mtime=self.HOUR)]
        pair = build_matches(clouds, locals_)["matched"][0]
        self.assertIsNone(pair["staleness"])
        self.assertIsNone(pair["differenceKind"])

    def test_case_and_padding_do_not_invent_a_rename(self):
        """Ekahau and the file can disagree about case or trailing space
        without anybody having renamed anything."""
        clouds = [cloud("SITE1 Same Name", PROJECT_ID, mtime=2 * self.HOUR)]
        locals_ = [local("SITE1 Same Name", "C:/a.esx", PROJECT_ID,
                         project_name="  site1 same name ", mtime=self.HOUR)]
        pair = build_matches(clouds, locals_)["matched"][0]
        self.assertEqual(pair["differenceKind"], "content")

    def test_the_internal_name_is_read_off_a_real_esx(self):
        """The whole mechanism rests on project.json carrying the name, so
        that is asserted against an actual archive rather than a dict."""
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "renamed-on-disk.esx"
            make_esx(f)
            meta = _esx_meta(f, int(f.stat().st_mtime))
            self.assertEqual(meta["projectName"], "Sample Project")
            self.assertNotEqual(meta["projectName"], f.stem)


class CloudHelperTests(unittest.TestCase):
    def test_path_containment(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inside = root / "site" / "project.esx"
            inside.parent.mkdir()
            inside.touch()
            _assert_inside(inside, root)
            with self.assertRaises(ValueError):
                _assert_inside(root.parent / "outside.esx", root)

    def test_name_helpers(self):
        self.assertEqual(extract_site_code("SITE42 - Sample"), "SITE42")
        self.assertIsNone(extract_site_code("Sample Site"))
        self.assertGreater(fuzzy_similarity("SITE1 Sample Building", "SITE1 Sample"), 0.5)
        self.assertEqual(_dup_key("Sample_Project-(A).esx"), "sample project a")

    def test_discriminator_conflicts(self):
        self.assertIn("Building", discriminators_reason("SITE1 Building 2", "SITE1 Building 3"))
        self.assertIn("Street", discriminators_reason("SITE1 100 Example Ave", "SITE1 200 Example Ave"))
        self.assertIn("phases", discriminators_reason("SITE1 Baseline", "SITE1 Remediation"))

    def test_equivalent_building_abbreviations_do_not_conflict(self):
        self.assertIsNone(discriminators_reason("SITE1 Building 2", "SITE1 Bldg 2"))

    def test_matching_prefers_project_id_over_name(self):
        clouds = [cloud("Old Name", PROJECT_ID)]
        locals_ = [local("Completely New Name.esx", "C:/sample.esx", PROJECT_ID)]
        result = build_matches(clouds, locals_)
        self.assertEqual(result["summary"]["matched"], 1)
        self.assertEqual(result["matched"][0]["matchType"], "id")
        self.assertTrue(result["matched"][0]["namesDiffer"])

    def test_exact_manual_excluded_and_held_back_matching(self):
        exact = build_matches(
            [cloud("SITE1 Sample")],
            [local("SITE1 Sample", "C:/exact.esx")],
        )
        self.assertEqual(exact["matched"][0]["matchType"], "exact")

        manual = build_matches(
            [cloud("Cloud Name", "cloud-1")],
            [local("Local Name", "C:/manual.esx")],
            manual_map={"cloud-1": "c:/manual.esx"},
        )
        self.assertEqual(manual["matched"][0]["matchType"], "manual")

        excluded_key = "cloud-2||c:/blocked.esx"
        blocked = build_matches(
            [cloud("Same Name", "cloud-2")],
            [local("Same Name", "C:/blocked.esx")],
            excluded={excluded_key},
        )
        self.assertEqual(blocked["summary"]["matched"], 0)

        held = build_matches(
            [cloud("SITE9 Building 2 Baseline")],
            [local("SITE9 Building 3 Baseline", "C:/held.esx")],
        )
        self.assertEqual(held["summary"]["heldBack"], 1)
        self.assertIn("Building", held["heldBack"][0]["reason"])

    def test_generated_esx_cloud_metadata_and_project_type(self):
        with tempfile.TemporaryDirectory() as td:
            path = make_esx(Path(td) / "sample.esx", project_type="Hybrid")
            mtime = path.stat().st_mtime
            meta = _esx_meta(path, mtime)
            self.assertEqual(meta["author"], "engineer@example.com")
            self.assertEqual(meta["projectId"], PROJECT_ID)
            self.assertGreater(meta["internalMtime"], 0)
            self.assertEqual(_esx_project_type(path, mtime), "Hybrid")


if __name__ == "__main__":
    unittest.main()
