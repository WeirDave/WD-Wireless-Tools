"""Names, patterns, lists and versions that are not what they claim to be.

One section per fault, each driven through the real function:

* **A rename rule is a regular expression typed into a box**, and Python's `re`
  cannot be interrupted. `(a+)+$` against a long name pinned a request thread.
* **Bulk rename checked containment against the file's own folder**, which can
  never fail, so any file the request named could be renamed.
* **A pasted recipient list was parsed with a quadratic pattern**: 0.9 s at
  8,000 characters, minutes at 100,000, on a request thread.
* **Stored counts were cast with `int()`**, so one damaged field raised out of the
  share that had already succeeded.
* **A version compare padded nothing**: `12.3` was older than `12.3.0`, and the
  release-candidate number counted as a patch level.
* **A template name with a colon** is a drive-relative path on Windows.
* **`open(path, "w")` truncates first**, so a failure mid-write destroyed the
  file it was replacing.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import atomic_write, deps, rename_manager, share_recipients, template_store


class ARenameRuleCannotHangAThreadTests(unittest.TestCase):

    LONG = "a" * 64 + "!.png"

    def test_a_catastrophic_pattern_returns_at_once_and_is_ignored(self):
        for rule in ({"regex_from": "(a+)+$", "regex_to": "Z"},
                     {"strip_prefix": "(a*)*b"},
                     {"strip_suffix": "(a|aa)+$"}):
            started = time.monotonic()
            out = rename_manager.apply_file_rules(self.LONG, "x", rule)
            self.assertLess(time.monotonic() - started, 2.0, rule)
            self.assertEqual(self.LONG, out, f"{rule} should have been ignored")

    def test_the_patterns_people_write_still_work(self):
        r = rename_manager.apply_file_rules
        self.assertEqual("001.png", r("IMG_001.png", "x", {"strip_prefix": "IMG_"}))
        self.assertEqual("001.png", r("IMG_001.png", "x",
                                      {"strip_prefix": "(IMG|DSC)_"}))
        self.assertEqual("A-001.png", r("IMG_001.png", "x", {
            "regex_from": r"^IMG_(\d+)$", "regex_to": r"A-\1"}))

    def test_an_overlong_pattern_is_ignored(self):
        rule = {"strip_prefix": "x" * 201}
        self.assertEqual("xxx.png", rename_manager.apply_file_rules(
            "xxx.png", "x", rule))

    def test_what_counts_as_unsafe(self):
        safe = rename_manager.is_safe_rule_pattern
        for bad in ("(a+)+", "(.*)*", "(a|b)+x", "(a|b){2,}"):
            self.assertFalse(safe(bad), bad)
        for good in ("IMG_", r"\d{3}", "(abc)", "^(IMG|DSC)_", "a+b*"):
            self.assertTrue(safe(good), good)


class BulkRenameStaysInTheShownFolderTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-rn-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.shown = self.tmp / "shown"
        self.elsewhere = self.tmp / "elsewhere"
        self.shown.mkdir()
        self.elsewhere.mkdir()
        self.inside = self.shown / "a.txt"
        self.outside = self.elsewhere / "b.txt"
        self.inside.write_text("a")
        self.outside.write_text("b")
        user = self.tmp / "user"
        user.mkdir()
        p = mock.patch.object(rename_manager, "CONFIG_DIR", user)
        p.start()
        self.addCleanup(p.stop)
        p2 = mock.patch.object(rename_manager, "_undo_path",
                               lambda kind: user / f"undo-{kind}.json")
        p2.start()
        self.addCleanup(p2.stop)

    def test_a_file_outside_the_folder_is_not_renamed(self):
        mgr = rename_manager.RenameManager()
        out = mgr.execute_bulk_rename(
            [{"path": str(self.inside), "new_name": "a2.txt"},
             {"path": str(self.outside), "new_name": "b2.txt"}],
            root=str(self.shown))
        self.assertEqual(1, out["renamed"], out)
        self.assertTrue((self.shown / "a2.txt").is_file())
        self.assertTrue(self.outside.is_file(), "the outside file was renamed")
        self.assertFalse((self.elsewhere / "b2.txt").exists())
        reasons = [d.get("reason") for d in out["details"]]
        self.assertIn("outside the folder being renamed", reasons)

    def test_without_a_root_nothing_changes_for_existing_callers(self):
        mgr = rename_manager.RenameManager()
        out = mgr.execute_bulk_rename(
            [{"path": str(self.outside), "new_name": "b2.txt"}])
        self.assertEqual(1, out["renamed"])


class APastedListIsParsedInLinearTimeTests(unittest.TestCase):

    def test_a_long_run_with_one_stray_bracket_is_fast(self):
        text = "a" * 20000 + "<" + "b" * 20000
        started = time.monotonic()
        share_recipients.split_addresses(text)
        self.assertLess(time.monotonic() - started, 2.0)

    def test_names_and_brackets_still_reduce_to_addresses(self):
        got = share_recipients.split_addresses(
            'Some One <A@example.com>, "Li, Wei" <w@example.com>; c@example.org')
        self.assertEqual(["a@example.com", "w@example.com", "c@example.org"], got)


class ADamagedRecipientsFileStillLoadsTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-sr-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = self.tmp / "share_recipients.json"
        p = mock.patch.object(share_recipients, "store_path", lambda: self.path)
        p.start()
        self.addCleanup(p.stop)

    def test_unreadable_numbers_become_defaults_instead_of_raising(self):
        for bad in ("many", None, [], 1e999, {"x": 1}):
            self.path.write_text(json.dumps({"recipients": [
                {"email": "a@example.com", "count": bad, "seq": bad}]},
                allow_nan=True), encoding="utf-8")
            got = share_recipients.recent()
            self.assertTrue(any(e == "a@example.com" or
                                (isinstance(e, dict) and e.get("email") == "a@example.com")
                                for e in got), (bad, got))
            share_recipients.remember(["b@example.com"])
            share_recipients.forget("b@example.com")


class VersionsCompareByNumberTests(unittest.TestCase):

    def test_a_shorter_version_is_padded(self):
        self.assertTrue(deps._at_least("12.3", "12.3.0"))
        self.assertTrue(deps._at_least("12.3.0", "12.3"))

    def test_the_candidate_number_is_not_a_patch_level(self):
        self.assertFalse(deps._at_least("12.3rc1", "12.3.1"))
        self.assertTrue(deps._at_least("12.3.0rc1", "12.3.0"))

    def test_ordinary_ordering(self):
        self.assertTrue(deps._at_least("13.0.0", "12.3.0"))
        self.assertFalse(deps._at_least("12.2.9", "12.3.0"))
        self.assertFalse(deps._at_least("1.2", "1.10"))

    def test_the_check_uses_it(self):
        with mock.patch.object(deps, "floors", lambda path=None: {"x": "12.3.0"}), \
                mock.patch.object(deps, "installed_version", lambda n: "12.3"):
            self.assertTrue(deps.check()["ok"])
        with mock.patch.object(deps, "floors", lambda path=None: {"x": "12.3.1"}), \
                mock.patch.object(deps, "installed_version", lambda n: "12.3rc1"):
            self.assertFalse(deps.check()["ok"])


class ATemplateNameIsOnePlainFileNameTests(unittest.TestCase):

    def test_names_with_separators_dots_or_colons_are_refused(self):
        for bad in ("../x.json", "a/b.json", "a\\b.json", "C:x.json", "",
                    "  ", None, "..", "x:y"):
            self.assertTrue(template_store._bad_template_name(bad), bad)
        self.assertFalse(template_store._bad_template_name("Mine_walltemplate.json"))

    def test_reset_and_delete_refuse_them(self):
        store = template_store.TemplateStore()
        for bad in ("C:x_walltemplate.json", "../x_walltemplate.json"):
            self.assertFalse(store.reset(bad)["ok"])
            self.assertFalse(store.delete(bad)["ok"])


class AWriteIsTheOldFileOrTheNewOneTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-aw-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = self.tmp / "data.json"
        self.path.write_text('{"old": true}', encoding="utf-8")

    def test_a_value_that_cannot_be_serialised_leaves_the_file_alone(self):
        with self.assertRaises(TypeError):
            atomic_write.write_json(self.path, {"bad": object()})
        self.assertEqual({"old": True}, json.loads(self.path.read_text("utf-8")))
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["data.json"])

    def test_a_failure_in_the_rename_leaves_the_file_and_no_temp(self):
        with mock.patch.object(os, "replace", side_effect=OSError("locked")):
            with self.assertRaises(OSError):
                atomic_write.write_json(self.path, {"new": True})
        self.assertEqual({"old": True}, json.loads(self.path.read_text("utf-8")))
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["data.json"])

    def test_a_good_write_replaces_it_completely(self):
        atomic_write.write_json(self.path, {"new": [1, 2]})
        self.assertEqual({"new": [1, 2]}, json.loads(self.path.read_text("utf-8")))
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["data.json"])

    def test_the_stores_that_used_to_truncate_now_write_atomically(self):
        user = self.tmp / "user"
        user.mkdir()
        with mock.patch.object(template_store, "USER_DIR", user):
            template_store._save_hidden({"a_walltemplate.json"})
            good = (user / template_store.HIDDEN_NAME).read_text("utf-8")
            with mock.patch.object(os, "replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    template_store._save_hidden({"b_walltemplate.json"})
            self.assertEqual(
                good, (user / template_store.HIDDEN_NAME).read_text("utf-8"),
                "a failed save damaged the file it was replacing")


if __name__ == "__main__":
    unittest.main()
