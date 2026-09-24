"""Squirrel → Rename previews the files Squirrel has already filed away.

Squirrel moves everything but the ``.esx`` into ``images/``, ``floorplans/``,
``reports/`` and any custom destination. The Rename page scanned only the site
folder itself, and never told the server about those subfolders, so on any
tree Squirrel had organised the File Cleanup Rules preview read "No files
change" and File Convention showed the ``.esx`` and nothing else - or, with no
CSV loaded, refused outright even for ``{original}``.

These go through the routes the page calls, with the bodies the page sends
(no ``skip`` or ``subfolder_names``), because the defect was in what the page
left out rather than in what the manager could do when asked.
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


class RenameSeesOrganizedSubfoldersTests(unittest.TestCase):
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

        self.root = base / "projects"
        site = self.root / "Alpha Site"
        for sub in ("images", "floorplans", "reports"):
            (site / sub).mkdir(parents=True)
        (site / "survey.esx").write_bytes(b"x")
        (site / "images" / "IMG_0001.JPG").write_bytes(b"x")
        (site / "floorplans" / "Level 1.pdf").write_bytes(b"x")

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()
        self.tmp.cleanup()

    def post(self, action, body):
        r = self.client.post("/api/rename/" + action, json=body, headers=HDR)
        return r.get_json()

    def test_cleanup_rules_preview_finds_files_in_squirrel_subfolders(self):
        r = self.post("preview_bulk_rename", {
            "root": str(self.root),
            "rules": {"case": "lower"},
        })
        self.assertTrue(r["ok"], r)
        got = {(Path(i["dir"]).name, i["old_name"], i["new_name"])
               for i in r["items"]}
        self.assertEqual(got, {
            ("images", "IMG_0001.JPG", "img_0001.JPG"),
            ("floorplans", "Level 1.pdf", "level 1.pdf"),
        })

    def test_cleanup_rules_does_not_treat_a_subfolder_as_a_site(self):
        """With the site folder itself as the root, ``images/`` is Squirrel's,
        not a site of its own, so the rows must not be labelled with it."""
        r = self.post("preview_bulk_rename", {
            "root": str(self.root / "Alpha Site"),
            "rules": {"case": "lower"},
        })
        self.assertEqual({i["site"] for i in r["items"]}, {"Alpha Site"})
        self.assertEqual(len(r["items"]), 2)

    def test_file_convention_previews_subfolder_files_without_a_csv(self):
        r = self.post("preview_file_rename", {
            "root": str(self.root), "format": "{original} - {folder}",
        })
        self.assertTrue(r.get("ok"), r)
        got = {(x["folder"], x["current"]): x["new_name"] for x in r["renames"]}
        self.assertEqual(got, {
            ("Alpha Site", "survey.esx"): "survey - Alpha Site.esx",
            ("Alpha Site/images", "IMG_0001.JPG"): "IMG_0001 - Alpha Site.JPG",
            ("Alpha Site/floorplans", "Level 1.pdf"): "Level 1 - Alpha Site.pdf",
        })

    def test_file_convention_names_the_token_that_needs_a_csv(self):
        r = self.post("preview_file_rename", {
            "root": str(self.root), "format": "{site_code} - {original}",
        })
        self.assertNotIn("ok", r)
        self.assertIn("{site_code}", r["error"])

    def test_applying_the_file_preview_renames_inside_the_subfolder_and_undoes(self):
        prev = self.post("preview_file_rename", {
            "root": str(self.root), "format": "{original} v2",
        })
        renames = [x for x in prev["renames"] if x["status"] == "rename"]
        done = self.post("execute_file_rename",
                         {"root": str(self.root), "renames": renames})
        self.assertEqual(done["renamed"], 3, done)
        img = self.root / "Alpha Site" / "images"
        self.assertEqual(sorted(p.name for p in img.iterdir()),
                         ["IMG_0001 v2.JPG"])

        self.post("undo_last", {"type": "files"})
        self.assertEqual(sorted(p.name for p in img.iterdir()),
                         ["IMG_0001.JPG"])

    def test_folder_convention_previews_with_no_csv_and_no_manual_tokens(self):
        """The page sends ``manual_values: {}`` when no CSV is loaded and the
        format uses only ``{folder}``; empty is still the no-CSV mode."""
        r = self.post("preview_folder_rename", {
            "root": str(self.root), "format": "{folder} (old)",
            "manual_values": {},
        })
        self.assertTrue(r.get("ok"), r)
        self.assertEqual([x["new_name"] for x in r["renames"]],
                         ["Alpha Site (old)"])


    # Picking the site folder itself as the root, rather than its parent.

    def test_file_convention_from_the_site_folder_renames_its_own_files(self):
        site = self.root / "Alpha Site"
        r = self.post("preview_file_rename", {
            "root": str(site), "format": "{original} - {folder}",
        })
        self.assertTrue(r.get("ok"), r)
        got = {(x["folder"], x["current"]): x["new_name"] for x in r["renames"]}
        self.assertEqual(got, {
            (".", "survey.esx"): "survey - Alpha Site.esx",
            ("images", "IMG_0001.JPG"): "IMG_0001 - Alpha Site.JPG",
            ("floorplans", "Level 1.pdf"): "Level 1 - Alpha Site.pdf",
        })
        done = self.post("execute_file_rename", {
            "root": str(site),
            "renames": [x for x in r["renames"] if x["status"] == "rename"],
        })
        self.assertEqual(done["renamed"], 3, done)
        self.assertTrue((site / "survey - Alpha Site.esx").is_file())

    def test_folder_convention_never_offers_squirrels_subfolders(self):
        r = self.post("preview_folder_rename", {
            "root": str(self.root / "Alpha Site"), "format": "{folder} X",
            "manual_values": {},
        })
        self.assertNotIn("renames", r)
        self.assertIn("site folder", r["error"])
        for sub in ("images", "floorplans", "reports"):
            self.assertTrue((self.root / "Alpha Site" / sub).is_dir())

    def test_folder_convention_leaves_squirrel_subfolders_out_beside_sites(self):
        (self.root / "images").mkdir()
        r = self.post("preview_folder_rename", {
            "root": str(self.root), "format": "{folder} X",
            "manual_values": {},
        })
        self.assertEqual([x["current"] for x in r["renames"]], ["Alpha Site"])


if __name__ == "__main__":
    unittest.main()
