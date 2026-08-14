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


def cloud(name, project_id=""):
    return {"id": project_id, "name": name, "code": extract_site_code(name)}


def local(name, path, project_id=""):
    return {"name": name, "path": path, "projectId": project_id,
            "code": extract_site_code(name)}


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
