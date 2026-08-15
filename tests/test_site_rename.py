from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools.site_rename as rename_module
from tools.site_rename import SiteRenameManager


SAMPLE_CSV = """\
Site_ID,Site_Name,Address,City,Deprecated_Names
ACME-001,Downtown Office,123 Main St,Springfield,Old Downtown;Main St Office
ACME-002,North Campus,456 University Ave,Springfield,
ACME-003,Airport Terminal,789 Aviation Blvd,Capital City,Airport Site
"""


class SiteRenameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.state = self.base / "state"
        self.root = self.base / "projects"
        self.root.mkdir()
        self.state.mkdir()
        self.patchers = [
            patch.object(rename_module, "CONFIG_DIR", self.state),
            patch.object(rename_module, "DIRECTORY_PATH", self.state / "site_directory.json"),
            patch.object(rename_module, "PROFILES_PATH", self.state / "site_rename_profiles.json"),
            patch.object(rename_module, "UNDO_DIR", self.state / "undo"),
        ]
        for p in self.patchers:
            p.start()
        self.mgr = SiteRenameManager()

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()
        self.temp.cleanup()

    def _load_sample(self):
        return self.mgr.load_directory(SAMPLE_CSV, {
            "primary": "Site_ID",
            "address": "Address",
            "deprecated": "Deprecated_Names",
        })

    def _make_folders(self, *names):
        for n in names:
            (self.root / n).mkdir(exist_ok=True)

    # ── load_directory ──

    def test_load_directory_success(self):
        r = self._load_sample()
        self.assertTrue(r["ok"])
        self.assertEqual(r["site_count"], 3)
        self.assertIn("Site_ID", r["tokens"])
        self.assertIn("City", r["tokens"])

    def test_load_directory_empty_csv(self):
        r = self.mgr.load_directory("", {})
        self.assertIn("error", r)

    def test_load_directory_bad_primary(self):
        r = self.mgr.load_directory(SAMPLE_CSV, {"primary": "Nonexistent"})
        self.assertIn("error", r)

    # ── get_directory ──

    def test_get_directory_before_load(self):
        r = self.mgr.get_directory()
        self.assertFalse(r["loaded"])

    def test_get_directory_after_load(self):
        self._load_sample()
        r = self.mgr.get_directory()
        self.assertTrue(r["loaded"])
        self.assertEqual(r["site_count"], 3)

    # ── match_folders ──

    def test_match_exact(self):
        self._load_sample()
        self._make_folders("ACME-001", "ACME-002", "Unknown")
        r = self.mgr.match_folders(str(self.root))
        self.assertTrue(r["ok"])
        self.assertEqual(r["matched_count"], 2)
        matches = {m["folder"]: m for m in r["matches"]}
        self.assertEqual(matches["ACME-001"]["method"], "exact")
        self.assertEqual(matches["Unknown"]["method"], "unmatched")

    def test_match_deprecated(self):
        self._load_sample()
        self._make_folders("Old Downtown")
        r = self.mgr.match_folders(str(self.root))
        matches = {m["folder"]: m for m in r["matches"]}
        self.assertEqual(matches["Old Downtown"]["method"], "deprecated")
        self.assertEqual(matches["Old Downtown"]["site_id"], "ACME-001")

    def test_match_address(self):
        self._load_sample()
        self._make_folders("123 Main St")
        r = self.mgr.match_folders(str(self.root))
        matches = {m["folder"]: m for m in r["matches"]}
        self.assertEqual(matches["123 Main St"]["method"], "address")

    # ── preview_folder_rename ──

    def test_preview_folder_rename(self):
        self._load_sample()
        self._make_folders("ACME-001", "ACME-002")
        r = self.mgr.preview_folder_rename(str(self.root), "{Site_ID} - {Site_Name}")
        self.assertTrue(r["ok"])
        renames = {x["current"]: x for x in r["renames"]}
        self.assertEqual(renames["ACME-001"]["new_name"], "ACME-001 - Downtown Office")
        self.assertEqual(renames["ACME-001"]["status"], "rename")

    def test_preview_already_correct(self):
        self._load_sample()
        self._make_folders("ACME-001 - Downtown Office")
        r = self.mgr.preview_folder_rename(str(self.root), "{Site_ID} - {Site_Name}")
        renames = {x["current"]: x for x in r["renames"]}
        self.assertEqual(renames["ACME-001 - Downtown Office"]["status"], "already_correct")

    # ── execute_folder_rename ──

    def test_execute_folder_rename(self):
        self._load_sample()
        self._make_folders("ACME-001")
        renames = [{"current": "ACME-001", "new_name": "ACME-001 - Downtown Office"}]
        r = self.mgr.execute_folder_rename(str(self.root), renames)
        self.assertTrue(r["ok"])
        self.assertEqual(r["renamed"], 1)
        self.assertTrue((self.root / "ACME-001 - Downtown Office").is_dir())
        self.assertFalse((self.root / "ACME-001").exists())

    def test_execute_skips_same_name(self):
        self._make_folders("ACME-001")
        r = self.mgr.execute_folder_rename(str(self.root), [
            {"current": "ACME-001", "new_name": "ACME-001"}
        ])
        self.assertEqual(r["renamed"], 0)

    def test_execute_target_exists(self):
        self._make_folders("src", "dst")
        r = self.mgr.execute_folder_rename(str(self.root), [
            {"current": "src", "new_name": "dst"}
        ])
        self.assertEqual(r["renamed"], 0)
        self.assertTrue(len(r["errors"]) > 0)

    # ── undo ──

    def test_undo_folders(self):
        self._load_sample()
        self._make_folders("ACME-001")
        self.mgr.execute_folder_rename(str(self.root), [
            {"current": "ACME-001", "new_name": "Renamed"}
        ])
        self.assertTrue((self.root / "Renamed").is_dir())
        r = self.mgr.undo_last("folders")
        self.assertTrue(r["ok"])
        self.assertEqual(r["reverted"], 1)
        self.assertTrue((self.root / "ACME-001").is_dir())
        self.assertFalse((self.root / "Renamed").exists())

    def test_undo_no_log(self):
        r = self.mgr.undo_last("folders")
        self.assertIn("error", r)

    # ── file rename ──

    def test_preview_file_rename(self):
        self._load_sample()
        folder = self.root / "ACME-001"
        folder.mkdir()
        (folder / "survey.esx").write_text("fake")
        r = self.mgr.preview_file_rename(str(self.root), "{Site_ID} - {Site_Name}")
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["renames"]), 1)
        self.assertEqual(r["renames"][0]["new_name"], "ACME-001 - Downtown Office.esx")

    def test_execute_file_rename(self):
        self._load_sample()
        folder = self.root / "ACME-001"
        folder.mkdir()
        (folder / "survey.esx").write_text("fake")
        renames = [{"folder": "ACME-001", "current": "survey.esx",
                     "new_name": "ACME-001 - Downtown Office.esx"}]
        r = self.mgr.execute_file_rename(str(self.root), renames)
        self.assertTrue(r["ok"])
        self.assertEqual(r["renamed"], 1)
        self.assertTrue((folder / "ACME-001 - Downtown Office.esx").exists())

    # ── gap_report ──

    def test_gap_report(self):
        self._load_sample()
        d1 = self.root / "ACME-001"
        d1.mkdir()
        (d1 / "project.esx").write_text("fake")
        d2 = self.root / "ACME-002"
        d2.mkdir()
        d3 = self.root / "Random"
        d3.mkdir()
        r = self.mgr.gap_report(str(self.root))
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["has_data"]), 1)
        self.assertEqual(len(r["empty"]), 1)
        self.assertEqual(len(r["orphans"]), 1)
        self.assertEqual(len(r["not_started"]), 1)

    # ── profiles ──

    def test_save_and_list_profiles(self):
        self.mgr.save_profile("Standard", "{Site_ID} - {Site_Name}", "{Site_ID}", " - ")
        r = self.mgr.list_profiles()
        self.assertIn("Standard", r["profiles"])
        self.assertEqual(r["profiles"]["Standard"]["folder_format"], "{Site_ID} - {Site_Name}")

    def test_delete_profile(self):
        self.mgr.save_profile("Temp", "x", "y", "-")
        self.mgr.delete_profile("Temp")
        r = self.mgr.list_profiles()
        self.assertNotIn("Temp", r["profiles"])

    # ── token list ──

    def test_get_token_list(self):
        self._load_sample()
        r = self.mgr.get_token_list()
        self.assertIn("Site_ID", r["tokens"])
        self.assertIn("Address", r["tokens"])


if __name__ == "__main__":
    unittest.main()
