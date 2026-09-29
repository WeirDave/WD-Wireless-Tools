"""Squirrel → Rename renames ``.esx`` project files in place.

Browsing to a projects folder and choosing File Cleanup Rules found no
``.esx`` at all: the rules preview skipped the extension outright, so a
folder of project files read as though it held nothing to rename. And with
site folders under the root, loose files at the top level - a batch of
``.esx`` dropped straight into the projects folder - were never scanned by
either File Cleanup Rules or File Convention.

Driven through the routes the page calls, with the bodies it sends, then
applied and read back off disk. Every name here is invented.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
import tools.rename_manager as rm_module  # noqa: E402

HDR = {"X-WD-Wireless-Tools": "1"}


class RenameFindsEsxFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        state = base / "state"
        state.mkdir()
        self.patchers = [
            patch.object(rm_module, "CONFIG_DIR", state),
            patch.object(rm_module, "DIRECTORY_PATH", state / "site_directory.json"),
            patch.object(rm_module, "UNDO_DIR", state / "undo"),
        ]
        for p in self.patchers:
            p.start()
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()

        self.root = base / "Projects"
        (self.root / "Alpha Site").mkdir(parents=True)
        (self.root / "Alpha Site" / "Alpha_Predictive_v1.esx").write_bytes(b"x")
        (self.root / "Bravo Site").mkdir()
        (self.root / "Bravo Site" / "Bravo_Survey.esx").write_bytes(b"x")
        (self.root / "Loose_Project.esx").write_bytes(b"x")
        (self.root / "backups").mkdir()
        (self.root / "backups" / "Old_Copy.esx").write_bytes(b"x")

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()
        self.tmp.cleanup()

    def post(self, action, body):
        r = self.client.post("/api/rename/" + action, json=body, headers=HDR)
        return r.get_json()

    def test_cleanup_rules_preview_lists_every_esx_including_loose_ones(self):
        r = self.post("preview_bulk_rename", {
            "root": str(self.root),
            "rules": {"separator": "space"},
        })
        self.assertTrue(r["ok"], r)
        got = {i["old_name"]: i["new_name"] for i in r["items"]}
        self.assertEqual(got, {
            "Alpha_Predictive_v1.esx": "Alpha Predictive v1.esx",
            "Bravo_Survey.esx": "Bravo Survey.esx",
            "Loose_Project.esx": "Loose Project.esx",
        })

    def test_cleanup_rules_apply_renames_the_esx_on_disk(self):
        r = self.post("preview_bulk_rename", {
            "root": str(self.root),
            "rules": {"separator": "space"},
        })
        done = self.post("execute_bulk_rename", {"items": r["items"]})
        self.assertEqual(done["renamed"], 3, done)
        self.assertTrue((self.root / "Alpha Site" / "Alpha Predictive v1.esx").is_file())
        self.assertTrue((self.root / "Loose Project.esx").is_file())
        self.assertFalse((self.root / "Loose_Project.esx").exists())
        self.assertTrue((self.root / "backups" / "Old_Copy.esx").is_file())

    def test_an_empty_rule_set_still_reports_what_it_found(self):
        """The page says how many files it looked at, so a blank rule set
        reads as "nothing changes yet", not as "no files here"."""
        r = self.post("preview_bulk_rename", {"root": str(self.root), "rules": {}})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["items"], [])
        self.assertEqual(r["scanned"], 3)

    def test_file_convention_includes_loose_files_next_to_site_folders(self):
        r = self.post("preview_file_rename", {
            "root": str(self.root),
            "format": "{original} - {folder}",
        })
        self.assertTrue(r["ok"], r)
        got = {(i["folder"], i["current"]): i["new_name"] for i in r["renames"]}
        self.assertEqual(got[(".", "Loose_Project.esx")],
                         "Loose_Project - Projects.esx")
        self.assertEqual(got[("Alpha Site", "Alpha_Predictive_v1.esx")],
                         "Alpha_Predictive_v1 - Alpha Site.esx")
        self.assertNotIn(("backups", "Old_Copy.esx"), got)

        rows = [i for i in r["renames"] if i["status"] == "rename"]
        done = self.post("execute_file_rename", {"root": str(self.root),
                                                 "renames": rows})
        self.assertEqual(done["renamed"], 3, done)
        self.assertTrue((self.root / "Loose_Project - Projects.esx").is_file())


if __name__ == "__main__":
    unittest.main()
