"""Undo in the Organizer takes back one run at a time, newest first.

The undo log was one file per root and every Organize or Group replaced it, so
running Group and then Organize left the grouping impossible to undo - the
Undo button only ever reached the latest run, and the earlier moves were lost
from the log. The log now holds each run, and Undo drops the one it reversed.

Each test runs the real Organize, Group and Undo over real files and asks the
disk where they ended up.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import folder_organizer as fo
from tools.folder_organizer import FolderOrganizer


class _Base(unittest.TestCase):

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="wd-undo-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.state = self.base / "state"
        for target, value in (("CONFIG_DIR", self.state),
                              ("ORGANIZER_CONFIG", self.state / "cfg.json"),
                              ("UNDO_DIR", self.state / "undo"),
                              ("ACORN_STATE_DIR", self.state / "acorn")):
            p = patch.object(fo, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.org = FolderOrganizer()
        self.flat = self.base / "downloads"
        self.flat.mkdir()
        for name in ("SITE1-plan.pdf", "SITE1-photo.jpg", "other.png"):
            (self.flat / name).write_text(name, encoding="utf-8")

    def group(self):
        return self.org.apply_grouping(str(self.flat), [{
            "prefix": "SITE1", "folder_name": "SITE1 - Sample",
            "files": ["SITE1-plan.pdf", "SITE1-photo.jpg"]}])


class EveryRunCanBeUndoneTests(_Base):

    def test_organize_after_group_leaves_the_grouping_undoable(self):
        grouped = self.group()
        self.assertEqual(2, grouped["moved"])
        organized = self.org.execute(str(self.flat))
        self.assertTrue(organized["undo_available"])

        first = self.org.undo(str(self.flat))
        self.assertTrue(first["ok"])
        # The grouping is still waiting to be undone.
        self.assertTrue(first["undo_available"])
        self.assertTrue((self.flat / "SITE1 - Sample" / "SITE1-plan.pdf").is_file())
        self.assertTrue((self.flat / "SITE1 - Sample" / "SITE1-photo.jpg").is_file())

        second = self.org.undo(str(self.flat))
        self.assertEqual(2, second["restored"])
        self.assertFalse(second["undo_available"])
        self.assertTrue((self.flat / "SITE1-plan.pdf").is_file())
        self.assertFalse((self.flat / "SITE1 - Sample").exists())

    def test_the_count_is_the_run_undo_will_take_back(self):
        self.group()
        organized = self.org.execute(str(self.flat))
        self.assertEqual(organized["undo_count"],
                         self.org.has_undo(str(self.flat))["count"])
        self.org.undo(str(self.flat))
        self.assertEqual(2, self.org.has_undo(str(self.flat))["count"])

    def test_a_run_that_moves_nothing_keeps_the_runs_before_it(self):
        self.group()
        before = self.org.has_undo(str(self.flat))
        self.org.apply_grouping(str(self.flat), [{
            "prefix": "NONE", "folder_name": "NONE", "files": ["not-there.pdf"]}])
        self.assertEqual(before, self.org.has_undo(str(self.flat)))

    def test_an_undone_run_cannot_be_undone_twice(self):
        self.group()
        self.org.undo(str(self.flat))
        again = self.org.undo(str(self.flat))
        self.assertFalse(again["ok"])


class TheLogIsBoundedAndCompatibleTests(_Base):

    def test_a_log_in_the_old_single_run_shape_still_undoes(self):
        (self.flat / "box").mkdir()
        moved = self.flat / "box" / "a.txt"
        moved.write_text("a", encoding="utf-8")
        original = self.flat / "a.txt"
        undo_file = fo._undo_path(self.flat)
        undo_file.parent.mkdir(parents=True)
        undo_file.write_text(json.dumps({
            "root": str(self.flat), "created_dirs": [],
            "moves": [{"from": str(original), "to": str(moved)}]}),
            encoding="utf-8")
        self.assertEqual(1, self.org.has_undo(str(self.flat))["count"])
        self.assertEqual(1, self.org.undo(str(self.flat))["restored"])
        self.assertTrue(original.is_file())

    def test_the_log_keeps_only_the_newest_runs(self):
        with patch.object(fo, "MAX_UNDO_RUNS", 2):
            for n in range(4):
                name = f"f{n}.txt"
                (self.flat / name).write_text(name, encoding="utf-8")
                self.org.apply_grouping(str(self.flat), [{
                    "prefix": "G", "folder_name": f"G{n}", "files": [name]}])
        self.assertEqual(2, self.org.has_undo(str(self.flat))["runs"])

    def test_an_unreadable_log_does_not_stop_a_new_run_being_recorded(self):
        undo_file = fo._undo_path(self.flat)
        undo_file.parent.mkdir(parents=True)
        undo_file.write_text("{not json", encoding="utf-8")
        self.group()
        self.assertEqual(2, self.org.has_undo(str(self.flat))["count"])


if __name__ == "__main__":
    unittest.main()
