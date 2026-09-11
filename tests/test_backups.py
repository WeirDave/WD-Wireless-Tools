"""Backup retention: a policy with a visible cost, not a promise to hoard.

Six places in this suite copy a file before overwriting it and, until this,
not one of them ever deleted anything. That is right for a single deliberate
action and wrong as a standing policy - an `.esx` runs to megabytes, a sync
touches many projects, and keeping every generation forever fills a disk
rather than protecting anything.

The rule that does not bend: **pruning happens after a successful write, and
never removes the copy belonging to the operation in progress.** Everything
else here is a preference.

Two naming conventions exist and both are recognised. `capacity_profiles`
writes `.backup-<stamp>`, everything else writes `.previous-<stamp>`. A
cleanup that only knew one would quietly leave the other on disk, which is
how a cleanup feature stops being trustworthy.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tools import backups


class ClassifyingWhatIsOnDisk(unittest.TestCase):

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def _f(self, name, size=10):
        p = self.d / name
        p.write_bytes(b"x" * size)
        return p

    def test_both_naming_conventions_are_recognised(self):
        """capacity_profiles is the odd one out and must not be missed."""
        prev = self._f("Site.previous-20260901-120000.esx")
        cap = self._f("Site.backup-20260901-130000.esx")
        for p in (prev, cap):
            with self.subTest(name=p.name):
                info = backups.classify(p)
                self.assertIsNotNone(info, f"{p.name} not seen as a backup")
                self.assertEqual(info["kind"], "file")
                self.assertEqual(Path(info["owner"]).name, "Site.esx")

    def test_an_ordinary_project_is_not_a_backup(self):
        """Deleting a real project would be the worst possible bug here."""
        self.assertIsNone(backups.classify(self._f("Site.esx")))
        self.assertIsNone(backups.classify(self._f("Site-previous.esx")))
        self.assertIsNone(backups.classify(self._f("Backup of Site.esx")))

    def test_an_install_backup_is_a_directory_not_a_file(self):
        d = self.d / "WD-Wireless-Tools.previous-v2.92.6-20260911-141500"
        d.mkdir()
        info = backups.classify(d)
        self.assertIsNotNone(info)
        self.assertEqual(info["kind"], "install")

    def test_scan_adds_up_what_they_cost(self):
        """The size is the point - "delete backups" with no number attached
        tells nobody whether it is worth doing."""
        self._f("A.previous-20260901-120000.esx", 1000)
        self._f("B.backup-20260902-120000.esx", 2000)
        self._f("A.esx", 50)
        found = backups.scan([str(self.d)])
        self.assertEqual(found["count"], 2)
        self.assertEqual(found["bytes"], 3000)

    def test_an_install_backups_contents_are_not_counted_twice(self):
        d = self.d / "app.previous-v1.0.0-20260901-120000"
        (d / "inner").mkdir(parents=True)
        (d / "inner" / "thing.previous-20260801-120000.esx").write_bytes(b"y" * 500)
        found = backups.scan([str(self.d)])
        self.assertEqual(found["count"], 1, "the folder's contents were counted separately")
        self.assertEqual(found["items"][0]["kind"], "install")


class PruningKeepsTheOneThatMatters(unittest.TestCase):

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.target = self.d / "Site.esx"
        self.target.write_bytes(b"live")
        self.gens = []
        for stamp in ("20260901-120000", "20260902-120000", "20260903-120000",
                      "20260904-120000", "20260905-120000"):
            p = self.d / f"Site.previous-{stamp}.esx"
            p.write_bytes(b"z" * 100)
            self.gens.append(p)

    def test_the_copy_from_this_run_is_never_deleted(self):
        """The rule that does not bend. Pruning runs after the write; removing
        the generation belonging to the operation in progress would defeat the
        reason the copy was taken at all."""
        newest = self.gens[-1]
        backups.prune_for(self.target, keep=0, protect=str(newest))
        self.assertTrue(newest.exists(), "deleted the backup for this very run")

    def test_off_means_off_apart_from_that_one(self):
        newest = self.gens[-1]
        backups.prune_for(self.target, keep=0, protect=str(newest))
        left = [p for p in self.gens if p.exists()]
        self.assertEqual(left, [newest])

    def test_keeping_three_leaves_three_newest(self):
        newest = self.gens[-1]
        backups.prune_for(self.target, keep=3, protect=str(newest))
        left = sorted(p.name for p in self.gens if p.exists())
        self.assertEqual(left, [
            "Site.previous-20260903-120000.esx",
            "Site.previous-20260904-120000.esx",
            "Site.previous-20260905-120000.esx",
        ])

    def test_the_protected_copy_counts_towards_the_quota(self):
        """"Keep 3" should leave three afterwards, not four."""
        backups.prune_for(self.target, keep=3, protect=str(self.gens[-1]))
        self.assertEqual(len([p for p in self.gens if p.exists()]), 3)

    def test_another_project_in_the_same_folder_is_untouched(self):
        """Retention is per project. Five backups of one must not consume the
        allowance of another sitting beside it."""
        other = self.d / "Other.previous-20260101-120000.esx"
        other.write_bytes(b"k" * 10)
        backups.prune_for(self.target, keep=1, protect=str(self.gens[-1]))
        self.assertTrue(other.exists())

    def test_the_project_itself_is_never_touched(self):
        backups.prune_for(self.target, keep=0, protect=str(self.gens[-1]))
        self.assertTrue(self.target.exists())
        self.assertEqual(self.target.read_bytes(), b"live")

    def test_pruning_reports_what_it_freed(self):
        res = backups.prune_for(self.target, keep=1, protect=str(self.gens[-1]))
        self.assertEqual(len(res["deleted"]), 4)
        self.assertEqual(res["freed"], 400)


class PurgingAcrossEverything(unittest.TestCase):

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / "site-a").mkdir()
        (self.d / "site-b").mkdir()
        for i, stamp in enumerate(("20260901-120000", "20260902-120000")):
            (self.d / "site-a" / f"A.previous-{stamp}.esx").write_bytes(b"a" * 100)
            (self.d / "site-b" / f"B.backup-{stamp}.esx").write_bytes(b"b" * 200)
        (self.d / "site-a" / "A.esx").write_bytes(b"live")
        self.install = self.d / "app.previous-v1.0.0-20260901-120000"
        self.install.mkdir()
        (self.install / "f.txt").write_bytes(b"i" * 50)

    def test_purge_clears_project_backups_and_says_what_it_freed(self):
        res = backups.purge([str(self.d)], keep=0)
        self.assertEqual(res["count"], 4)
        self.assertEqual(res["freed"], 600)
        self.assertTrue((self.d / "site-a" / "A.esx").exists())

    def test_purge_can_keep_the_newest_of_each(self):
        res = backups.purge([str(self.d)], keep=1)
        self.assertEqual(res["count"], 2)
        left = sorted(p.name for p in (self.d / "site-a").iterdir())
        self.assertIn("A.previous-20260902-120000.esx", left)
        self.assertNotIn("A.previous-20260901-120000.esx", left)

    def test_a_previous_install_is_left_alone_unless_asked_for(self):
        """That folder is the way back from a bad update. A cleanup that took
        it would remove the one copy that matters at the moment it matters."""
        backups.purge([str(self.d)], keep=0)
        self.assertTrue(self.install.exists())

    def test_but_it_is_counted_so_the_total_is_honest(self):
        found = backups.scan([str(self.d)])
        kinds = {i["kind"] for i in found["items"]}
        self.assertIn("install", kinds)
        self.assertEqual(found["bytes"], 600 + 50)


class TheSettingIsRealAndReachable(unittest.TestCase):

    def test_it_has_a_default_in_the_settings_file(self):
        from tools import settings as suite_settings
        self.assertIn("backup_keep", suite_settings.DEFAULTS["global"])

    def test_every_writer_prunes_only_after_the_write(self):
        """Pruning before or during would be removing a safety net while
        standing on it."""
        root = Path(__file__).resolve().parent.parent
        cases = {
            "tools/cloud_manager.py": "os.replace(tmp, src)",
            "tools/wall_inject.py": "tmp.replace(target)",
            "tools/wall_audit.py": "tmp.replace(path)",
            "tools/capacity_profiles.py": "os.replace(tmp_name, str(dest_path))",
            "tools/prep_pipeline.py": "shutil.move(str(cur), str(target))",
        }
        for name, write_marker in cases.items():
            with self.subTest(tool=name):
                src = (root / name).read_text(encoding="utf-8")
                self.assertIn("_prune_backups", src, f"{name} never prunes")
                self.assertLess(
                    src.index(write_marker), src.index("_prune_backups(", src.index(write_marker)),
                    f"{name} prunes before the file is safely written")

    def test_pruning_never_fails_the_operation(self):
        """A project written correctly must not report an error because
        tidying up afterwards did not work."""
        root = Path(__file__).resolve().parent.parent
        src = (root / "tools" / "cloud_manager.py").read_text(encoding="utf-8")
        block = src[src.index("def _prune_backups"):]
        block = block[:block.index("\ndef ", 1)]
        self.assertIn("except Exception", block)


if __name__ == "__main__":
    unittest.main()
