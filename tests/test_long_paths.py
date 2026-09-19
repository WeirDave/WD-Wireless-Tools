"""A write that crosses MAX_PATH still lands, and says so plainly when it does not.

Reported from a live machine: "Set the name inside the file to match" failed with

    [WinError 3] The system cannot find the path specified

on a project whose folder existed and whose .esx opened perfectly. The path was
the problem and nothing said so.

    src .esx                232 characters   opened fine
    the rewrite's temp file 246 characters   over the limit

`<name>.esx.wd-rename.tmp` adds 14 characters to the longest name in the tree,
and a survey project is named after its site, so the temp file is the first path
in the whole operation to cross 260. The refusal was correct - a half-written
.esx is worse - but it was also a dead end: every retry failed identically, so
the feature did not work at all for the longest-named projects, which are the
ones a naming convention produces most of.

**Why it was never caught here.** The 260-character limit is off by default and
a machine with `LongPathsEnabled=1` in the registry copies a 295-character path
without complaint. That is a developer's machine, and it is this one - so the
end-to-end test below passes here whether or not the fix is present. It is kept
because it fails on a machine with the default, and because on POSIX it is a
plain regression test. The test that holds the fix on *any* machine is
`TheDecisionIsMadeBeforeAnyIO`, which asks `write_path` what form it picked.

This file outlived `tools/backups.py`. The limit was first hit by a backup copy,
but none of this was ever about backups - `_rewrite_project_json` still writes a
temp file beside a project named after its site, and that is what these hold.
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

from tools import longpath as L


class LongPathForm(unittest.TestCase):
    """The string transformation, which is where the whole thing turns."""

    @unittest.skipUnless(os.name == "nt", "the prefix is a Windows idea")
    def test_a_drive_path_gets_the_prefix(self):
        self.assertEqual(r"\\?\C:\Users\x\a.esx",
                         L.long_path(r"C:\Users\x\a.esx"))

    @unittest.skipUnless(os.name == "nt", "the prefix is a Windows idea")
    def test_a_unc_path_takes_the_unc_form(self):
        """`\\\\?\\\\server\\share` is not a path Windows accepts; the UNC form
        is. Getting this wrong turns a working network path into a broken one,
        which is worse than the bug being fixed."""
        self.assertEqual(r"\\?\UNC\server\share\a.esx",
                         L.long_path(r"\\server\share\a.esx"))

    @unittest.skipUnless(os.name == "nt", "the prefix is a Windows idea")
    def test_it_is_not_applied_twice(self):
        self.assertEqual(r"\\?\C:\x\a.esx", L.long_path(r"\\?\C:\x\a.esx"))

    @unittest.skipUnless(os.name == "nt", "the prefix is a Windows idea")
    def test_the_path_is_made_absolute_first(self):
        """The prefix turns off the normalisation that would otherwise resolve
        `..`, so a path carrying one has to be resolved before it is applied or
        the result names somewhere that does not exist."""
        got = L.long_path(r"C:\Users\x\..\y\a.esx")
        self.assertEqual(r"\\?\C:\Users\y\a.esx", got)
        self.assertNotIn("..", got)

    @unittest.skipIf(os.name == "nt", "POSIX has no such limit")
    def test_posix_is_left_alone(self):
        self.assertEqual("/home/x/a.esx", L.long_path("/home/x/a.esx"))


class TheDecisionIsMadeBeforeAnyIO(unittest.TestCase):
    """`write_path` picks the form from the length, and only from the length.

    A copy could try the plain path and retry, because a failed copy leaves
    nothing behind. A write cannot: by the time it fails there may be a
    half-built archive at the destination. So there is nothing to observe after
    the fact - the assertion is on what form was chosen, which is why this one
    holds on a machine where the real write would have succeeded anyway.
    """

    @unittest.skipUnless(os.name == "nt", "the limit is a Windows one")
    def test_a_path_over_the_limit_is_written_through_the_prefix(self):
        long = "C:\\x\\" + ("P" * 300) + ".esx"
        self.assertGreaterEqual(len(long), L.MAX_PATH)
        self.assertTrue(L.write_path(long).startswith("\\\\?\\"),
                        "an over-length write was not given the extended form")

    @unittest.skipUnless(os.name == "nt", "the limit is a Windows one")
    def test_an_ordinary_path_keeps_the_ordinary_form(self):
        """The prefixed form is not identical - it bypasses normalisation, and
        some network redirectors dislike it - so it is for the paths that need
        it rather than for everything."""
        self.assertEqual("C:\\x\\a.esx", L.write_path("C:\\x\\a.esx"))

    @unittest.skipIf(os.name == "nt", "POSIX has no such limit")
    def test_posix_never_gets_a_prefix_however_long_the_path(self):
        long = "/x/" + ("P" * 400) + ".esx"
        self.assertEqual(long, L.write_path(long))

    @unittest.skipUnless(os.name == "nt", "the limit is a Windows one")
    def test_the_boundary_is_the_limit_itself(self):
        """260 is the first length Windows refuses, not the last it accepts.
        Off by one here means the longest working path stops working.

        Windows-only, and skipped rather than trivially satisfied on POSIX:
        `and os.name == "nt"` folded into the expectation would make this pass
        here whatever `write_path` does, which is the shape CLAUDE.md calls a
        test that cannot fail. CI runs windows-latest, so it runs there.
        """
        for n, want_prefix in ((L.MAX_PATH - 1, False), (L.MAX_PATH, True)):
            p = "C:\\" + "P" * (n - 3)
            self.assertEqual(n, len(p))
            self.assertEqual(want_prefix, L.write_path(p).startswith("\\\\?\\"),
                             f"wrong form chosen at {n} characters")


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
            src, lambda proj, doc: (proj.__setitem__("name", "New Name"), True)[1])

        self.assertNotIn("error", out, out.get("error", ""))
        with zipfile.ZipFile(src) as z:
            doc = json.loads(z.read("project.json"))
        self.assertEqual("New Name", doc["project"]["name"])

    def test_nothing_is_left_beside_the_project_afterwards(self):
        """The temp file is renamed over the top, so a successful rewrite adds
        no file to the folder. A stray `.wd-rename.tmp` would be picked up by
        the next scan as a project nobody made."""
        from tools import cloud_manager as cm

        base = Path(tempfile.mkdtemp(prefix="wd-long-"))
        self.addCleanup(shutil.rmtree, base, True)
        folder = base / "Projects" / "Example Site"
        folder.mkdir(parents=True)
        src = folder / "Example Site - Survey.esx"
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("project.json", json.dumps({"project": {"name": "Old"}}))

        cm._rewrite_project_json(
            src, lambda proj, doc: (proj.__setitem__("name", "New"), True)[1])

        self.assertEqual([src.name], sorted(p.name for p in folder.iterdir()))


class TheMessageLeadsSomewhere(unittest.TestCase):
    """If it does fail anyway, the sentence has to name the reason.

    "[WinError 3] The system cannot find the path specified" sends someone to
    look for a missing folder that is sitting right there. The length is the
    fact that explains it.
    """

    @unittest.skipUnless(os.name == "nt", "the limit is a Windows one")
    def test_an_over_length_path_says_so_and_says_what_to_do(self):
        target = "C:\\" + ("x" * 300) + ".esx"
        msg = L.describe_failure(
            OSError(errno.ENOENT, "The system cannot find the path specified"),
            target)
        self.assertIn(str(len(target)), msg)
        self.assertIn(str(L.MAX_PATH), msg)
        self.assertRegex(msg, r"[Ss]horten|nearer the top")

    def test_an_ordinary_failure_is_not_dressed_up_as_a_length_problem(self):
        msg = L.describe_failure(OSError(13, "Permission denied"), "C:\\short.esx")
        self.assertIn("Permission denied", msg)
        self.assertNotIn(str(L.MAX_PATH), msg)


if __name__ == "__main__":
    unittest.main()
