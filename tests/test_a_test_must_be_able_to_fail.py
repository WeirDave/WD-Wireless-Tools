"""A test that would pass with the feature deleted is not a test.

Five shipped defects were green the whole time they were broken, all the same
shape - the test asserted that the *source contained* something rather than
that the *code did* something:

  * **Apply-to-all** reported "Applied to 1 floor" while discarding the work.
  * **The match line label** test asserted the label was *rotated*. It passed
    for the entire period the installer sheets were unusable.
  * **`↑ Local newer · replace cloud`** - the tests asserted the markup
    contained `pushLocalOverCloud(`, and it did. He could not use it for days.
  * **Prep's wall step** was verified 1 → 26 on fixtures while doing nothing
    visible on his machine.
  * **The backups wording** was pinned by a test requiring a particular
    sentence, so five dialogs told him the wrong place to find a file he had
    just overwritten. A test that pins the phrasing pins the bug with it.

This file holds the two properties that keep the shape from spreading. It does
not try to fix the existing debt - `tests/source_string_assertion_baseline.json`
records that, per file, and this fails when a number goes **up**. Lower one
when you convert a test to one that executes; never raise one.

The pattern to convert to is in `tests/test_cloud_sync_direction.py`: render
the real thing, pull the handler back out of the rendered markup, run it, and
assert the call that arrives - its name, its arguments, their order, and what
happens on the path that is supposed to refuse.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "source_string_assertion_baseline.json"
AUDIT = ROOT / "scripts" / "audit_source_string_tests.py"
HANDLERS = ROOT / "scripts" / "audit_handlers_exist.py"
TIMEOUT_S = 180


def _counts() -> dict[str, int]:
    r = subprocess.run([sys.executable, str(AUDIT), "--csv"],
                       capture_output=True, text=True, errors="replace",
                       timeout=TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError(r.stderr.strip())
    out: dict[str, int] = {}
    for line in r.stdout.splitlines()[1:]:
        name = line.split(",", 1)[0]
        if name.endswith(".py"):
            out[name] = out.get(name, 0) + 1
    return out


class EveryClickableControlReachesSomethingThatExists(unittest.TestCase):
    """The `pushLocalOverCloud` shape, caught for the whole suite at once.

    A name in an `onclick` is a string until something calls it, so asserting
    that the markup contains one proves nothing. This collects every handler
    named in every event attribute - in the pages and in the markup the JS
    builds - and fails on any that nothing defines.
    """

    def test_no_event_attribute_names_a_handler_that_does_not_exist(self):
        r = subprocess.run([sys.executable, str(HANDLERS)],
                           capture_output=True, text=True, errors="replace",
                           timeout=TIMEOUT_S)
        self.assertEqual(r.returncode, 0,
                         "a control on screen calls something undefined:\n"
                         + r.stdout.strip())
        self.assertIn("nothing defines: 0", r.stdout)


class TheSourceStringShapeDoesNotGrow(unittest.TestCase):

    def setUp(self):
        self.baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

    def test_no_file_gains_assertions_against_its_own_source(self):
        now = _counts()
        base = self.baseline["files"]
        worse = {name: (base.get(name, 0), n)
                 for name, n in now.items() if n > base.get(name, 0)}
        self.assertEqual(
            worse, {},
            "these test files gained assertions that read a source file "
            "instead of running it - see this module's docstring for the "
            "pattern to use instead: "
            + ", ".join("%s %d→%d" % (k, v[0], v[1])
                        for k, v in sorted(worse.items())))

    def test_the_baseline_is_not_quietly_raised(self):
        """The ratchet only works in one direction."""
        now = _counts()
        self.assertLessEqual(
            sum(now.values()), self.baseline["total"],
            "the total went up; convert a test rather than recording more debt")

    def test_converting_a_file_is_worth_recording(self):
        """Not a failure - a note. A file that is better than the baseline is
        somebody's good deed, and failing their build over bookkeeping is how a
        ratchet earns a reputation for getting in the way. The tightening comes
        from the two checks above; this only says where the slack is."""
        now = _counts()
        better = {name: (n, now.get(name, 0))
                  for name, n in self.baseline["files"].items()
                  if n > now.get(name, 0)}
        if better:
            note = ", ".join("%s %d→%d" % (k, v[0], v[1])
                             for k, v in sorted(better.items()))
            print("  baseline slack, lower these when convenient: " + note)


if __name__ == "__main__":
    unittest.main()
