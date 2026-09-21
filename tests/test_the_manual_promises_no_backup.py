"""The User Guide must not promise a copy that nothing writes.

`NothingPromisesACopyThatIsNoLongerKeptTests` in `test_cloud_ops_queue.py`
holds this for the app's dialogs, and has since v2.141.0 removed backups from
the whole suite. **It reads `cloud.js` and nothing else**, so the User Guide
went on promising them for four months.

Found on 2026-09-20. The guide said, in three places:

* *"every tool that changes files shows you a preview first, and most keep a
  backup"*
* *"Cloud Manager keeps a backup of the local file it replaces, in a `backups`
  folder"*
* *"Every file is backed up first."*

— while a later section of the same document said *"Nothing in this suite keeps
a copy of a file before overwriting it, and that is deliberate. There is no
backups folder, no retention setting and no `.previous-` copy."*

That is the failure the original guard was written for, in the document a user
is more likely to read than a dialog: **a promise of a copy that does not exist
is how somebody overwrites a file believing they can get it back.** The guide is
also where somebody looks *before* doing something, which is the moment the
promise does its damage.

This is the same shape as backlog item 9 - a suite-wide rule enforced on one
file - and the fix is the same: ask it of the document too.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANUAL = ROOT / "docs" / "USER_MANUAL.md"

#: Sentences that tell a reader a copy is kept. Written as patterns rather than
#: exact strings because the guide is prose and will be reworded; what must not
#: come back is the *claim*.
PROMISES = [
    (r"keeps? a backup", "says something keeps a backup"),
    (r"backed[- ]up first", "says a file is backed up first"),
    (r"\bmakes? a backup\b", "says a backup is made"),
    (r"\bbackup (?:is|are) kept\b", "says a backup is kept"),
    (r"\.previous-", "names a .previous- copy"),
    (r"\bretention\b", "refers to a retention setting"),
]

#: Where the word is legitimate. The updater really does copy the install
#: folder aside before replacing it, and settings import really does keep three
#: dated copies - both are named in the guide on purpose, and both are about
#: something other than a project file.
ALLOWED_CONTEXT = re.compile(
    r"install|installed from a zip|settings\.json|settings file|"
    r"suite settings|import|uninstall|version before 2\.141|"
    r"is from a version|no backups folder|there is no backup",
    re.I)


def offending_lines():
    out = []
    lines = MANUAL.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines, 1):
        for pattern, why in PROMISES:
            if not re.search(pattern, line, re.I):
                continue
            # A sentence can run across a wrapped line, so the neighbours count
            # as context - "no backups folder" on the line below still means
            # this line is denying backups rather than promising one.
            window = " ".join(lines[max(0, i - 3):i + 2])
            if ALLOWED_CONTEXT.search(window):
                continue
            if re.search(r"\bno\b[^.]{0,40}$", line[:line.lower().find(
                    re.search(pattern, line, re.I).group(0).lower())] or ""):
                continue
            out.append((i, why, line.strip()[:100]))
    return out


class TheGuideDoesNotPromiseACopyTests(unittest.TestCase):

    def test_nothing_in_the_guide_says_a_project_file_is_backed_up(self):
        found = offending_lines()
        self.assertEqual(
            [], found,
            "the User Guide promises a copy that nothing writes:\n  "
            + "\n  ".join("line %d: %s\n    %s" % f for f in found)
            + "\n\nBackups were removed from the whole suite in v2.141.0. If "
              "this is about the installer or the settings file, widen "
              "ALLOWED_CONTEXT; otherwise the sentence is wrong.")

    @staticmethod
    def flowed():
        """The guide as sentences rather than as lines.

        It is hard-wrapped, so any phrase long enough to be worth asserting on
        is split across a newline somewhere. Searching the raw text finds
        nothing and reads as the sentence being absent.
        """
        return re.sub(r"\s+", " ", MANUAL.read_text(encoding="utf-8")).lower()

    def test_the_guide_still_says_plainly_that_there_are_none(self):
        """Saying nothing would be the other failure.

        A replace with no stated safety net reads as data loss. The guide has
        to say there is no copy *and* what stands in its place, which for a
        pull is that Ekahau is still holding the other one.
        """
        text = self.flowed()
        self.assertIn("nothing in this suite keeps a copy of a file before "
                      "overwriting it", text)
        self.assertIn("no second copy is kept", text)

    def test_the_guide_explains_what_replaces_a_backup(self):
        """Atomicity and the cloud copy are the two answers, and both are
        claims a reader can act on."""
        text = self.flowed()
        self.assertIn("entirely the old one or entirely the new one", text)
        self.assertIn("still there afterwards", text)


class TheAppGuardStillExistsTests(unittest.TestCase):
    """This widens the rule to the guide; it does not replace the original."""

    def test_the_dialog_guard_is_still_in_the_suite(self):
        import importlib
        mod = importlib.import_module("tests.test_cloud_ops_queue")
        cls = getattr(mod, "NothingPromisesACopyThatIsNoLongerKeptTests", None)
        self.assertIsNotNone(cls, "the dialog-wording guard has gone")
        self.assertTrue([n for n in dir(cls) if n.startswith("test_")])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
