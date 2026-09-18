"""A backup that cannot be written stops the write, so it had better be writable.

Reported from a live machine: "Set the name inside the file to match" failed with

    Could not back the file up, so nothing was changed:
    [WinError 3] The system cannot find the path specified

on a project whose folder existed, whose .esx opened, and whose backup folder
had just been created successfully. The path was the problem and nothing said so.

    src .esx                232 characters   opened fine
    backups/<site>/         147 characters   created fine
    the backup file         265 characters   over the limit

`<stem>.previous-<stamp><ext>` adds 25 characters to the longest name in the
tree, and a survey project is named after its site, so the backup is the first
path in the whole operation to cross 260. The refusal was correct - a rewrite
with no way back is worse - but it was also a dead end: every retry failed
identically, so the feature did not work at all for the longest-named projects,
which are the ones a naming convention produces most of.

**Why it was never caught here.** The 260-character limit is off by default and
a machine with `LongPathsEnabled=1` in the registry copies a 295-character path
without complaint. That is a developer's machine, and it is this one - so the
end-to-end test below passes here whether or not the fix is present. It is kept
because it fails on a machine with the default, and because on POSIX it is a
plain regression test. The test that actually holds the fix on *any* machine is
`TheRetryHappens`, which makes the short form fail the way Windows makes it fail
and asserts that the long form is then tried.

Six places in the suite copy a file before overwriting it. All six go through
one helper now, because the four that were not reported have the same shape -
a sibling backup of an .esx named after its site - and would have failed the
same way on a slightly longer name.
"""
from __future__ import annotations

import errno
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import backups as B


class LongPathForm(unittest.TestCase):
    """The string transformation, which is where the whole thing turns."""

    @unittest.skipUnless(os.name == "nt", "the prefix is a Windows idea")
    def test_a_drive_path_gets_the_prefix(self):
        self.assertEqual(r"\\?\C:\Users\x\a.esx",
                         B.long_path(r"C:\Users\x\a.esx"))

    @unittest.skipUnless(os.name == "nt", "the prefix is a Windows idea")
    def test_a_unc_path_takes_the_unc_form(self):
        """`\\\\?\\\\server\\share` is not a path Windows accepts; the UNC form
        is. Getting this wrong turns a working network path into a broken one,
        which is worse than the bug being fixed."""
        self.assertEqual(r"\\?\UNC\server\share\a.esx",
                         B.long_path(r"\\server\share\a.esx"))

    @unittest.skipUnless(os.name == "nt", "the prefix is a Windows idea")
    def test_it_is_not_applied_twice(self):
        self.assertEqual(r"\\?\C:\x\a.esx", B.long_path(r"\\?\C:\x\a.esx"))

    @unittest.skipUnless(os.name == "nt", "the prefix is a Windows idea")
    def test_the_path_is_made_absolute_first(self):
        """The prefix turns off the normalisation that would otherwise resolve
        `..`, so a path carrying one has to be resolved before it is applied or
        the result names somewhere that does not exist."""
        got = B.long_path(r"C:\Users\x\..\y\a.esx")
        self.assertEqual(r"\\?\C:\Users\y\a.esx", got)
        self.assertNotIn("..", got)

    @unittest.skipIf(os.name == "nt", "POSIX has no such limit")
    def test_posix_is_left_alone(self):
        self.assertEqual("/home/x/a.esx", B.long_path("/home/x/a.esx"))


class TheRetryHappens(unittest.TestCase):
    """Windows' own failure, staged, so the fix is exercised on any machine.

    `WinError 3` is what an over-length path raises. The plain call is made to
    raise it and the prefixed call to succeed, which is exactly the split on the
    reporting machine - so this fails if the retry is removed, on a developer's
    box where the real path would have copied anyway.
    """

    def setUp(self):
        self.calls = []
        self.real = shutil.copy2
        self.addCleanup(setattr, shutil, "copy2", self.real)

    def _staged(self, fail_plain=True):
        def fake(src, dest):
            self.calls.append((str(src), str(dest)))
            if fail_plain and not str(dest).startswith("\\\\?\\"):
                raise OSError(errno.ENOENT, "The system cannot find the path specified")
            return dest
        return fake

    @unittest.skipUnless(os.name == "nt", "the retry is a Windows path")
    def test_the_long_form_is_tried_when_the_short_one_fails(self):
        shutil.copy2 = self._staged()
        B.copy_for_backup(r"C:\x\a.esx", r"C:\x\a.previous-20260918-151900.esx")
        self.assertEqual(2, len(self.calls), "the retry did not happen")
        self.assertFalse(self.calls[0][1].startswith("\\\\?\\"),
                         "the plain path should be tried first")
        self.assertTrue(self.calls[1][1].startswith("\\\\?\\"),
                        "the retry should use the extended-length form")

    def test_the_ordinary_case_is_left_alone(self):
        """A path that copies is copied once, with the path it was given. The
        prefixed form is not identical - it bypasses normalisation and some
        network redirectors dislike it - so it is a fallback, not the default."""
        shutil.copy2 = self._staged(fail_plain=False)
        B.copy_for_backup("/x/a.esx", "/x/a.previous-20260918-151900.esx")
        self.assertEqual(1, len(self.calls))
        self.assertNotIn("?", self.calls[0][1])

    @unittest.skipUnless(os.name == "nt", "the retry is a Windows path")
    def test_the_caller_is_handed_back_a_path_a_person_can_use(self):
        r"""`prune_for` matches on this path and the UI shows it to the person
        whose file it is. `\\?\C:\...` is not somewhere to tell anyone to go
        and look, and it would not match either."""
        shutil.copy2 = self._staged()
        dest = r"C:\x\a.previous-20260918-151900.esx"
        self.assertEqual(dest, B.copy_for_backup(r"C:\x\a.esx", dest))


class TheNameIsNeverShortened(unittest.TestCase):
    """Trimming the stem to fit would orphan the backup from its own retention.

    `classify` reads the owner back out of the filename. A shortened stem names
    a file that does not exist, `prune_for` never matches it again, and the
    result is a backup that is correct, invisible to retention and kept for
    ever - on exactly the projects that produce the largest files.
    """

    def test_a_backup_keeps_the_whole_stem_so_pruning_still_finds_it(self):
        base = Path(tempfile.mkdtemp(prefix="wd-backup-"))
        self.addCleanup(shutil.rmtree, base, True)
        stem = "S" * 90 + " - Power Level Adjustment"
        src = base / (stem + ".esx")
        src.write_bytes(b"x")
        dest = base / f"{stem}.previous-20260918-151900.esx"
        B.copy_for_backup(src, dest)

        self.assertTrue(dest.exists(), "the backup was not written")
        info = B.classify(dest)
        self.assertIsNotNone(info, "the backup no longer looks like a backup")
        self.assertEqual(str(src), info["owner"],
                         "the backup no longer points at the file it is a backup of")


class TheWriteGoesThroughEndToEnd(unittest.TestCase):
    """The reported operation, on real files, at the reported length.

    On a machine with long paths enabled this passes either way - see the module
    docstring. It is the regression guard for one with the default, and on POSIX
    it simply checks the rewrite still works.
    """

    def test_setting_the_name_inside_a_deeply_nested_esx(self):
        from tools import cloud_manager as cm

        base = Path(tempfile.mkdtemp(prefix="wd-long-"))
        self.addCleanup(shutil.rmtree, base, True)

        # Invented throughout, and shaped like the real thing: a site-named
        # folder holding a project named after the same site.
        site = "ABCD1 - AB-99 - 100 Example Road, Anytown, Example State 0000"
        root = base / "CloudDrive - Example Org" / "Documents" / "Survey" / "Projects"
        (root / site).mkdir(parents=True)
        src = root / site / (site + " - Power Level Adjustment.esx")
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("project.json", json.dumps({"project": {"name": "Old Name"}}))

        out = cm._rewrite_project_json(
            src, lambda proj, doc: (proj.__setitem__("name", "New Name"), True)[1],
            str(root), keep_backups=True)

        self.assertNotIn("error", out, out.get("error", ""))
        self.assertTrue(out.get("backup"), "no backup path was reported")
        self.assertTrue(Path(B.long_path(out["backup"])).exists(),
                        "the backup was reported but is not on disk")

        with zipfile.ZipFile(src) as z:
            doc = json.loads(z.read("project.json"))
        self.assertEqual("New Name", doc["project"]["name"])


class TheMessageLeadsSomewhere(unittest.TestCase):
    """If it does fail anyway, the sentence has to name the reason.

    "[WinError 3] The system cannot find the path specified" sends someone to
    look for a missing folder that is sitting right there. The length is the
    fact that explains it.
    """

    @unittest.skipUnless(os.name == "nt", "the limit is a Windows one")
    def test_an_over_length_path_says_so_and_says_what_to_do(self):
        from tools import cloud_manager as cm
        target = "C:\\" + ("x" * 300) + ".esx"
        msg = cm._backup_failure(
            target, OSError(errno.ENOENT, "The system cannot find the path specified"))
        self.assertIn(str(len(target)), msg)
        self.assertIn(str(B.MAX_PATH), msg)
        self.assertRegex(msg, r"[Ss]horten|nearer the top")

    def test_an_ordinary_failure_is_not_dressed_up_as_a_length_problem(self):
        from tools import cloud_manager as cm
        msg = cm._backup_failure("C:\\short.esx", OSError(13, "Permission denied"))
        self.assertIn("Permission denied", msg)
        self.assertNotIn(str(B.MAX_PATH), msg)
