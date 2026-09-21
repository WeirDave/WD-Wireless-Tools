"""Is this path inside that folder - asked of every implementation there is.

Two guards in this suite confined a write to a directory with
``str(target).startswith(str(root))``, and that is wrong the same way in both:
a **sibling whose name begins with the root's name** passes it. With a root of
``.../extracted``, a member resolving to ``.../extracted-elsewhere/x`` starts
with the root string and is not inside the root.

Where they were:

* ``tools/updater.py`` - the release archive guard. Behind a checksum, so
  reaching it with a hostile member means already controlling the release;
  the audit recorded it as not independently exploitable and it was fixed in
  v2.156.0, inline, by another pass that found it the same week. Its
  behaviour is driven end to end in
  ``tests/test_zip_update_installs_only_what_it_verified.py`` rather than
  compared here, because what matters about it is what the extractor does
  with a real archive.
* ``tools/settings_backup.py`` - the settings-import guard, and **this one
  was not behind anything**. A bundle is a file he can be handed - it is how
  a setting gets from the machine at home to the one at work - and one
  naming ``../.wd_wireless_tools_elsewhere/x`` was written outside the user
  directory. That is the finding this module exists for.

Two implementations remain and each has a reason: ``safe_path.is_within`` is
the rule, and ``safe_path.is_within_unresolved`` is the textual form a survey
walking thousands of entries needs, because ``Path.resolve()`` opens every
one of them. They must agree, and neither may accept the sibling.

**Checked against the bug**: restoring the ``startswith`` spelling in either
of them fails ``test_the_sibling_prefix_is_refused``.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.safe_path import is_within, is_within_unresolved


class Containment(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-contain-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(
            self.tmp, ignore_errors=True))
        self.root = self.tmp / "extracted"
        self.root.mkdir()
        # The sibling has to exist for the resolved forms to have anything to
        # resolve, and its existence is the whole point: this is a real
        # directory a real write would land in.
        (self.tmp / "extracted-elsewhere").mkdir()

    def cases(self):
        """(path, expected_inside, what it is)."""
        r = self.root
        return [
            (r,                              True,  "the root itself"),
            (r / "a.txt",                    True,  "a file in the root"),
            (r / "sub" / "a.txt",            True,  "a file below the root"),
            (r / "sub" / ".." / "a.txt",     True,  "a climb that lands back inside"),
            (r / ".." / "a.txt",             False, "one level out"),
            (r / ".." / "extracted-elsewhere" / "a.txt",
                                             False, "the sibling prefix"),
            (self.tmp / "extracted-elsewhere" / "a.txt",
                                             False, "the sibling, spelled directly"),
            (self.tmp,                       False, "the parent"),
        ]

    def test_the_sibling_prefix_is_refused(self):
        """The finding itself, asked of every implementation.

        `str(sibling).startswith(str(root))` is True for this pair - that is
        what makes it the case worth naming - so any implementation that
        answers by string prefix fails here.
        """
        sibling = self.tmp / "extracted-elsewhere" / "a.txt"
        self.assertTrue(
            str(sibling).startswith(str(self.root)),
            "the fixture is wrong: this pair must have the shared prefix that "
            "the old spelling was fooled by")
        for name, fn in (("safe_path.is_within", is_within),
                         ("safe_path.is_within_unresolved", is_within_unresolved)):
            with self.subTest(implementation=name):
                self.assertFalse(
                    fn(sibling, self.root),
                    f"{name} let a sibling directory through")

    def test_every_implementation_gives_the_same_answer(self):
        for path, expected, what in self.cases():
            for name, fn in (("safe_path.is_within", is_within),
                             ("safe_path.is_within_unresolved",
                              is_within_unresolved)):
                with self.subTest(case=what, implementation=name):
                    self.assertEqual(
                        expected, fn(path, self.root),
                        f"{name} disagreed about {what}: {path}")

    def test_a_hostile_name_answers_rather_than_raising(self):
        """A guard that raises is a guard with no answer.

        These are names the platform may refuse to describe - a NUL byte, a
        name past `MAX_PATH`. Whatever each implementation decides about them,
        it has to *decide*: an exception here reaches a caller that has no
        handler for it, and on the import path that is a traceback instead of
        a refusal.

        Note what is *not* asserted: that these are outside the root. A name
        containing a NUL byte under the root is still a child of the root, and
        saying otherwise would be pinning a wrong answer.
        """
        for bad in ("\0", "\0/x", "x" * 5000, "x" * 5000 + "/y"):
            for name, fn in (("safe_path.is_within", is_within),
                             ("safe_path.is_within_unresolved",
                              is_within_unresolved)):
                with self.subTest(path=repr(bad)[:24], implementation=name):
                    self.assertIsInstance(fn(self.root / bad, self.root), bool)

    def test_an_absolute_entry_cannot_override_the_root(self):
        """`root / "C:/Windows/x"` is `C:/Windows/x`, not a child of root.

        This is the shape a bundle or an archive uses to write anywhere at
        all, and pathlib's join silently hands it the whole answer - so the
        containment check is the only thing standing in front of it.
        """
        absolute = Path(self.tmp.anchor) / "Windows" / "System32" / "x"
        for name, fn in (("safe_path.is_within", is_within),
                         ("safe_path.is_within_unresolved",
                          is_within_unresolved)):
            with self.subTest(implementation=name):
                self.assertFalse(fn(self.root / absolute, self.root))


if __name__ == "__main__":
    unittest.main()
