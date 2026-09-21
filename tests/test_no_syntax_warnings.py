"""Every Python file in this repository compiles without a warning.

Found on 2026-09-20 in the one place nobody reads: a full suite run printed

    <unknown>:49: SyntaxWarning: invalid escape sequence '\\`'

above 2869 passing dots, and `<unknown>` is what `compile()` reports when the
source came from a string rather than a file - so the message named neither the
file nor a line anybody could act on. It had been printed on every run for
however long, in the position most likely to be scrolled past.

**Four of them, and two were a dated fault rather than a cosmetic one.**
`tests/test_aim_table_fits.py` and `tests/test_column_grid_in_tables.py` embed
JavaScript regexes in Python strings, and `/width:([\\d.]+)%/` was written in a
non-raw string. `\\d` is not a Python escape, and Python's behaviour today is to
leave an unrecognised escape exactly as written - which is why those probes
work and have always worked.

That behaviour is deprecated. It is a `SyntaxWarning` in 3.12 and is scheduled
to become a `SyntaxError`, at which point those two files stop importing and
take the suite with them. The fix is one character each: an `r` in front of the
opening quotes.

The other two were `\\?\\` - the Windows long-path prefix - written out in prose
in a non-raw docstring, where it rendered as `\\?\\` with one backslash missing,
in a file whose subject is a message that had too many backslashes in it.

This is the ratchet. It compiles every tracked `.py` and fails on any warning,
naming the file and the line - which is the part the original message could
not do.
"""
from __future__ import annotations

import subprocess
import unittest
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def tracked_python_files():
    """From `git ls-files`, not a walk.

    A walk picks up `.venv`, build output and anything a session left lying
    about, none of which this repository is responsible for. It also matches
    what CI checks out, which is the tree whose result means anything.
    """
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT,
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:  # pragma: no cover - not a git checkout
        raise unittest.SkipTest("not a git checkout")
    return [ROOT / line for line in out.stdout.splitlines() if line.strip()]


class NothingCompilesWithAWarningTests(unittest.TestCase):

    def test_the_scan_really_found_files(self):
        """A check that silently scanned nothing is a comment.

        `git ls-files` returning empty - wrong directory, not a checkout -
        would make every assertion below pass on an empty list.
        """
        self.assertGreater(len(tracked_python_files()), 100)

    def test_no_file_raises_a_syntax_warning(self):
        found = []
        for path in tracked_python_files():
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:  # pragma: no cover - listed but unreadable
                continue
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                try:
                    compile(source, str(path), "exec")
                except SyntaxError as exc:  # pragma: no cover
                    found.append("%s:%s SyntaxError: %s"
                                 % (path.relative_to(ROOT), exc.lineno, exc.msg))
                    continue
                for item in caught:
                    found.append("%s:%s %s: %s"
                                 % (path.relative_to(ROOT), item.lineno,
                                    item.category.__name__, item.message))
        self.assertEqual(
            [], found,
            "Python files compile with warnings:\n  " + "\n  ".join(found)
            + "\n\nAn invalid escape sequence is usually a regex or a Windows "
              "path in a string that should be raw - prefix it with r. It "
              "works today and is a SyntaxError in a future Python.")


class TheWarningWouldHaveBeenSeenTests(unittest.TestCase):
    """The check has to be able to fail, so make it fail on purpose.

    Not a mutation of the repository: a string with the same defect, compiled
    the same way. If Python ever stops warning about this, the assertion below
    goes red and says so, rather than the check above quietly passing forever.
    """

    def test_an_invalid_escape_still_warns(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            compile('x = "width:([\\d.]+)%"', "<probe>", "exec")
        self.assertTrue(
            [c for c in caught if c.category is SyntaxWarning],
            "Python no longer warns about an unrecognised escape, so the "
            "check above can never fail and is measuring nothing")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
