"""A release ZIP is the one published thing that cannot be edited afterwards.

`build_release.py` walked the working tree with `rglob` over `tools/`,
`web/`, `templates/` and `docs/`, so **anything untracked sitting in one of
those went into the download**: a session's scratch output, a screenshot, a
draft, an `.esx` somebody dropped in to reproduce a fault.

In CI that is harmless - a release is built from a fresh checkout of a tag
and there is nothing untracked in it. It matters for a build made by hand,
on the machine where the work happens, and rule zero is explicit that a
public repository is not a place anything can be quietly un-published:
"release notes can be edited, but ZIP assets, forks, clones and commit
history cannot be taken back the same way".

So the payload is now what git tracks. The tests here drive the real
`iter_release_files` against a real stray file rather than reading the
source, because "the function mentions ls-files" and "the function excludes
the file" are different claims and only one of them is the point.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import build_release


def _in_a_git_checkout() -> bool:
    try:
        subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--git-dir"],
                       capture_output=True, check=True, timeout=30)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


@unittest.skipUnless(_in_a_git_checkout(),
                     "the payload is defined by git, so this needs a checkout")
class OnlyTrackedFilesShip(unittest.TestCase):

    def payload(self):
        return {relative.as_posix()
                for _path, relative in build_release.iter_release_files()}

    def test_the_payload_is_not_empty(self):
        """A guard that excluded everything would pass every test below."""
        names = self.payload()
        self.assertGreater(len(names), 50, "the payload has collapsed")
        self.assertIn("server.py", names)
        self.assertIn("web/assets/versions.json", names)

    def test_a_stray_file_under_web_does_not_ship(self):
        stray = ROOT / "web" / "assets" / "zz-stray-for-this-test.txt"
        stray.write_text("a session left this behind\n", encoding="utf-8")
        self.addCleanup(stray.unlink, missing_ok=True)
        self.assertNotIn("web/assets/zz-stray-for-this-test.txt", self.payload())

    def test_a_stray_file_under_tools_does_not_ship(self):
        stray = ROOT / "tools" / "zz_stray_for_this_test.py"
        stray.write_text("# scratch\n", encoding="utf-8")
        self.addCleanup(stray.unlink, missing_ok=True)
        self.assertNotIn("tools/zz_stray_for_this_test.py", self.payload())

    def test_a_stray_project_file_does_not_ship(self):
        """The category rule zero is actually about.

        A `.esx` is gitignored, so it was never going to be tracked - and
        the old walk did not ask whether it was tracked.
        """
        stray = ROOT / "templates" / "zz-stray-for-this-test.esx"
        stray.write_bytes(b"PK\x03\x04not really\n")
        self.addCleanup(stray.unlink, missing_ok=True)
        self.assertNotIn("templates/zz-stray-for-this-test.esx", self.payload())

    def test_every_shipped_file_is_tracked(self):
        tracked = build_release.tracked_files()
        for name in self.payload():
            with self.subTest(path=name):
                self.assertIn(name, tracked)

    def test_the_documented_exclusions_still_apply(self):
        """`docs/releases` is tracked and deliberately not shipped."""
        names = self.payload()
        self.assertFalse([n for n in names if n.startswith("docs/releases/")],
                         "the internal changelog is in the download again")
        self.assertFalse([n for n in names if "__pycache__" in n])
        self.assertFalse([n for n in names if n.endswith((".pyc", ".pyo"))])

    def test_a_missing_required_file_is_still_an_error(self):
        """The check that a release is complete must survive the new one."""
        original = build_release.ROOT_FILES
        build_release.ROOT_FILES = original + ("no-such-file.txt",)
        try:
            with self.assertRaises(FileNotFoundError):
                list(build_release.iter_release_files())
        finally:
            build_release.ROOT_FILES = original

    def test_a_required_file_that_is_not_tracked_is_an_error(self):
        """Untracked is skipped in a directory and refused at the root.

        Different answers on purpose: a stray file in `web/` is noise to
        leave out, and an untracked `server.py` is v2.102.0 - a release
        whose server could not start, because the file was present locally
        and absent from the clean checkout CI built from.
        """
        stray = ROOT / "zz-stray-root-file.txt"
        stray.write_text("x\n", encoding="utf-8")
        self.addCleanup(stray.unlink, missing_ok=True)
        original = build_release.ROOT_FILES
        build_release.ROOT_FILES = original + ("zz-stray-root-file.txt",)
        try:
            with self.assertRaises(FileNotFoundError) as caught:
                list(build_release.iter_release_files())
            self.assertIn("not tracked", str(caught.exception))
        finally:
            build_release.ROOT_FILES = original


class ItRefusesRatherThanGuessing(unittest.TestCase):
    """A build that cannot ask git has to stop.

    Falling back to walking the tree would leave the build unprotected in
    exactly the case that is not CI.
    """

    def test_no_git_is_a_refusal(self):
        from unittest import mock
        with mock.patch.object(build_release.subprocess, "run",
                               side_effect=OSError("git not found")):
            with self.assertRaises(RuntimeError) as caught:
                build_release.tracked_files()
        self.assertIn("checkout", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
