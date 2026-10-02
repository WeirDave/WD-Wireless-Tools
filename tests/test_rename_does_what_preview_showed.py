"""Squirrel → Rename: what the preview promises, the rename and its undo keep.

One class per defect a review found by running the code:

* Undo reverted whatever the last log of the *current tab's* kind held, in
  whatever folder that was - the log never said which folder, so an old bulk
  rename elsewhere could be reverted from here;
* undo renamed over a file saved since, and threw away the entries it could
  not revert;
* a case-only rename never applied on Windows, because NTFS says the target
  "exists" - it is the file itself;
* the preview compared new names only with each other, case-sensitively, and
  not with names already on disk, and the Rules tab checked nothing;
* a crafted request could rename a file out of the root;
* a folder picker that could not open read as a cancel;
* the gap report and the CSV prefill listed Squirrel's own folders as sites.

Folder and file names are invented.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import tools.folder_organizer as organizer_module  # noqa: E402
import tools.rename_manager as rm_module  # noqa: E402
from tools.rename_manager import RenameManager, _check_collisions  # noqa: E402

CSV = """Site_ID,Site_Name
Alpha Site,Alpha
Bravo Site,Bravo
"""


def _case_insensitive_exists():
    """`Path.exists` the way NTFS answers it. CI runs this suite on Linux as
    well as Windows and macOS, so the file system's behaviour is emulated."""
    real = Path.exists

    def exists(path, *a, **k):
        try:
            return any(c.name.casefold() == path.name.casefold()
                       for c in path.parent.iterdir())
        except OSError:
            return real(path, *a, **k)
    return patch.object(Path, "exists", exists)


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        state = base / "state"
        state.mkdir()
        self.patchers = [
            patch.object(rm_module, "CONFIG_DIR", state),
            patch.object(rm_module, "DIRECTORY_PATH", state / "site_directory.json"),
            patch.object(rm_module, "PROFILES_PATH", state / "rename_profiles.json"),
            patch.object(rm_module, "UNDO_DIR", state / "undo"),
            patch.object(rm_module, "_LEGACY_PROFILES_PATH", state / "old.json"),
            patch.object(rm_module, "_LEGACY_UNDO_DIR", state / "old_undo"),
            patch.object(organizer_module, "CONFIG_DIR", state),
            patch.object(organizer_module, "ORGANIZER_CONFIG",
                         state / "organizer_config.json"),
            patch.object(organizer_module, "UNDO_DIR", state / "org_undo"),
        ]
        for p in self.patchers:
            p.start()
        self.base = base
        self.root = base / "projects"
        self.root.mkdir()
        self.mgr = RenameManager()

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()
        self.tmp.cleanup()

    def bulk(self, root, rules):
        pv = self.mgr.preview_bulk_rename(str(root), rules)
        return self.mgr.execute_bulk_rename(
            [i for i in pv["items"] if i["status"] == "rename"], str(root))


class UndoRevertsOnlyARenameMadeInThisFolder(_Base):

    def test_every_log_records_its_folder(self):
        site = self.root / "Alpha Site"
        site.mkdir()
        (site / "a b.png").write_text("x")
        self.mgr.execute_folder_rename(str(self.root),
                                       [{"current": "Alpha Site",
                                         "new_name": "Alpha Site 2"}])
        self.mgr.execute_file_rename(str(self.root),
                                     [{"folder": "Alpha Site 2",
                                       "current": "a b.png",
                                       "new_name": "c d.png"}])
        self.bulk(self.root, {"separator": "underscore"})
        for kind in ("folders", "files", "bulk"):
            with self.subTest(kind=kind):
                log = json.loads((rm_module.UNDO_DIR / f"{kind}_last.json")
                                 .read_text(encoding="utf-8"))
                self.assertEqual(log["root"], str(self.root))

    def test_an_undo_for_another_folder_is_refused(self):
        other = self.base / "elsewhere"
        (other / "Kilo Site").mkdir(parents=True)
        (other / "Kilo Site" / "photo one.png").write_text("x")
        self.bulk(other, {"separator": "underscore"})

        r = self.mgr.undo_last("bulk", str(self.root))
        self.assertIn("error", r)
        self.assertIn("not in the folder shown here", r["error"])
        self.assertTrue((other / "Kilo Site" / "photo_one.png").is_file(),
                        "the other folder's rename must be left alone")

        r = self.mgr.undo_last("bulk", str(other))
        self.assertEqual(r["reverted"], 1)
        self.assertTrue((other / "Kilo Site" / "photo one.png").is_file())

    def test_the_route_passes_the_folder_through(self):
        import server
        server.app.config["TESTING"] = True
        client = server.app.test_client()
        other = self.base / "elsewhere"
        (other / "Kilo Site").mkdir(parents=True)
        (other / "Kilo Site" / "photo one.png").write_text("x")
        hdr = {"X-WD-Wireless-Tools": "1"}
        pv = client.post("/api/rename/preview_bulk_rename", headers=hdr,
                         json={"root": str(other),
                               "rules": {"separator": "underscore"}}).get_json()
        client.post("/api/rename/execute_bulk_rename", headers=hdr,
                    json={"root": str(other), "items": pv["items"]})
        r = client.post("/api/rename/undo_last", headers=hdr,
                        json={"type": "bulk", "root": str(self.root)}).get_json()
        self.assertIn("error", r)
        self.assertTrue((other / "Kilo Site" / "photo_one.png").is_file())


class UndoNeverOverwritesAndKeepsWhatItCouldNotDo(_Base):

    def test_a_file_saved_since_under_the_old_name_survives(self):
        site = self.root / "Kilo Site"
        site.mkdir()
        (site / "photo one.png").write_text("ORIGINAL")
        self.bulk(self.root, {"separator": "underscore"})
        (site / "photo one.png").write_text("NEW WORK")

        r = self.mgr.undo_last("bulk", str(self.root))
        self.assertEqual(r["reverted"], 0)
        self.assertEqual(len(r["skipped"]), 1)
        self.assertEqual((site / "photo one.png").read_text(), "NEW WORK")
        self.assertEqual((site / "photo_one.png").read_text(), "ORIGINAL")

        # Kept in the log: once the way is clear, Undo finishes the job.
        (site / "photo one.png").unlink()
        r = self.mgr.undo_last("bulk", str(self.root))
        self.assertEqual(r["reverted"], 1)
        self.assertEqual((site / "photo one.png").read_text(), "ORIGINAL")
        self.assertFalse((rm_module.UNDO_DIR / "bulk_last.json").exists())

    def test_folder_undo_does_not_land_on_a_new_folder(self):
        (self.root / "Lima Site").mkdir()
        self.mgr.execute_folder_rename(str(self.root),
                                       [{"current": "Lima Site",
                                         "new_name": "Lima Site 2"}])
        (self.root / "Lima Site").mkdir()
        (self.root / "Lima Site" / "keep.txt").write_text("k")
        r = self.mgr.undo_last("folders", str(self.root))
        self.assertEqual(r["reverted"], 0)
        self.assertEqual(r["remaining"], 1)
        self.assertTrue((self.root / "Lima Site" / "keep.txt").is_file())
        self.assertTrue((self.root / "Lima Site 2").is_dir())


class ACaseOnlyRenameApplies(_Base):

    def test_rules(self):
        site = self.root / "November Site"
        site.mkdir()
        (site / "Floor Plan.png").write_text("x")
        pv = self.mgr.preview_bulk_rename(str(self.root), {"case": "lower"})
        self.assertEqual([i["status"] for i in pv["items"]], ["rename"])
        with _case_insensitive_exists():
            r = self.mgr.execute_bulk_rename(pv["items"], str(self.root))
        self.assertEqual(r["renamed"], 1, r)
        self.assertEqual(os.listdir(site), ["floor plan.png"])

    def test_file_convention(self):
        site = self.root / "November Site"
        site.mkdir()
        (site / "Floor Plan.png").write_text("x")
        with _case_insensitive_exists():
            r = self.mgr.execute_file_rename(
                str(self.root), [{"folder": "November Site",
                                  "current": "Floor Plan.png",
                                  "new_name": "FLOOR PLAN.png"}])
        self.assertEqual(r["renamed"], 1, r)
        self.assertEqual(os.listdir(site), ["FLOOR PLAN.png"])

    def test_folder_convention(self):
        (self.root / "November Site").mkdir()
        with _case_insensitive_exists():
            r = self.mgr.execute_folder_rename(
                str(self.root), [{"current": "November Site",
                                  "new_name": "november site"}])
        self.assertEqual(r["renamed"], 1, r)
        self.assertEqual(os.listdir(self.root), ["november site"])

    def test_a_real_second_file_is_still_a_collision(self):
        site = self.root / "November Site"
        site.mkdir()
        (site / "Floor Plan.png").write_text("1")
        (site / "floor plan.png").write_text("2")
        # On a case-insensitive disk (Windows, macOS) the second write lands
        # on the first file, so the other file has to differ by more than
        # case; it is still a different file the rename must not replace.
        other = "floor plan.png"
        if (site / "Floor Plan.png").read_text() == "2":
            other = "Floor-Plan.png"
            (site / other).write_text("2")
        r = self.mgr.execute_bulk_rename(
            [{"path": str(site / "Floor Plan.png"),
              "new_name": other}], str(self.root))
        self.assertEqual(r["renamed"], 0)
        self.assertEqual((site / other).read_text(), "2")


class ThePreviewSeesNamesAlreadyOnDisk(_Base):

    def test_a_folder_name_taken_by_an_existing_folder(self):
        (self.root / "Mike").mkdir()
        (self.root / "Mike - 2026").mkdir()
        pv = self.mgr.preview_folder_rename(str(self.root), "{folder} - 2026",
                                            manual_values={})
        status = {r["current"]: r["status"] for r in pv["renames"]}
        self.assertEqual(status["Mike"], "collision")
        self.assertEqual(status["Mike - 2026"], "rename")
        ok = [r for r in pv["renames"] if r["status"] == "rename"]
        done = self.mgr.execute_folder_rename(str(self.root), ok)
        self.assertEqual(done["errors"], [])

    def test_the_rules_tab_marks_a_file_already_there(self):
        site = self.root / "Oscar Site"
        site.mkdir()
        (site / "photo one.png").write_text("1")
        (site / "photo_one.png").write_text("2")
        pv = self.mgr.preview_bulk_rename(str(self.root),
                                          {"separator": "underscore"})
        self.assertEqual([(i["old_name"], i["status"]) for i in pv["items"]],
                         [("photo one.png", "collision")])

    def test_names_differing_only_in_case_collide(self):
        rows = [{"folder": "x", "current": "a.png", "new_name": "Plan.png",
                 "status": "rename"},
                {"folder": "x", "current": "b.png", "new_name": "plan.png",
                 "status": "rename"}]
        _check_collisions(rows)
        self.assertEqual([r["status"] for r in rows], ["collision"] * 2)

    def test_a_name_freed_by_an_earlier_row_is_free(self):
        site = self.root / "Papa Site"
        site.mkdir()
        (site / "b.png").write_text("b")
        rows = [{"folder": "Papa Site", "current": "b.png",
                 "new_name": "c.png", "status": "rename"},
                {"folder": "Papa Site", "current": "a.png",
                 "new_name": "b.png", "status": "rename"}]
        _check_collisions(rows, lambda r: self.root / r["folder"])
        self.assertEqual([r["status"] for r in rows], ["rename", "rename"])


class ARenameStaysInsideTheRoot(_Base):

    def test_a_file_name_with_a_path_in_it_is_refused(self):
        site = self.root / "Quebec Site"
        site.mkdir()
        (site / "a.png").write_text("x")
        outside = self.base / "outside"
        outside.mkdir()
        r = self.mgr.execute_file_rename(
            str(self.root), [{"folder": "Quebec Site", "current": "a.png",
                              "new_name": "../../outside/a.png"}])
        self.assertEqual(r["renamed"], 0)
        self.assertEqual(os.listdir(outside), [])
        self.assertTrue((site / "a.png").is_file())

    def test_a_folder_that_climbs_out_is_refused(self):
        outside = self.base / "outside"
        (outside / "Romeo Site").mkdir(parents=True)
        (outside / "Romeo Site" / "a.png").write_text("x")
        r = self.mgr.execute_file_rename(
            str(self.root), [{"folder": "../outside/Romeo Site",
                              "current": "a.png", "new_name": "b.png"}])
        self.assertEqual(r["renamed"], 0)
        self.assertTrue((outside / "Romeo Site" / "a.png").is_file())

    def test_a_folder_rename_with_a_path_is_refused(self):
        (self.root / "Sierra Site").mkdir()
        r = self.mgr.execute_folder_rename(
            str(self.root), [{"current": "Sierra Site",
                              "new_name": "../Sierra Site"}])
        self.assertEqual(r["renamed"], 0)
        self.assertTrue((self.root / "Sierra Site").is_dir())
        self.assertFalse((self.base / "Sierra Site").exists())


class TheFolderPickerSaysWhenItCannotOpen(_Base):

    def test_a_dialog_that_never_opened(self):
        broken = {"path": "", "ran": False, "why": "it closed immediately"}
        with mock.patch("tools.folder_organizer._tk_dialog_result",
                        return_value=broken):
            r = self.mgr.pick_folder()
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "picker_unavailable")
        self.assertIn("closed immediately", r["error"])

    def test_a_cancel_is_still_the_cancel(self):
        with mock.patch("tools.folder_organizer._tk_dialog_result",
                        return_value={"path": "", "ran": True, "why": ""}):
            self.assertEqual(self.mgr.pick_folder()["error"],
                             "No folder selected")
        with mock.patch("tools.folder_organizer._tk_dialog_result",
                        return_value={"path": "/x/y", "ran": True, "why": ""}):
            self.assertEqual(self.mgr.pick_folder()["path"], "/x/y")


class SquirrelsOwnFoldersAreNotSites(_Base):

    def setUp(self):
        super().setUp()
        for name in ("Alpha Site", "Bravo Site", "images", "backups", ".cache"):
            (self.root / name).mkdir()

    def test_gap_report(self):
        self.mgr.load_directory(CSV, {"primary": "Site_ID"})
        r = self.mgr.gap_report(str(self.root))
        listed = {e["folder"] for k in ("has_data", "empty", "orphans")
                  for e in r[k]}
        self.assertEqual(listed, {"Alpha Site", "Bravo Site"})

    def test_csv_prefill(self):
        r = self.mgr.prefill_from_folders(str(self.root))
        self.assertEqual(r["folder_count"], 2)
        rows = r["csv_text"].splitlines()[1:]
        self.assertEqual([row.split(",")[0] for row in rows],
                         ["Alpha Site", "Bravo Site"])


if __name__ == "__main__":
    unittest.main()
