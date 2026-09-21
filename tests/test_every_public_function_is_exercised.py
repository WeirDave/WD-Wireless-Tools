"""A public function in `tools/` that no test mentions fails the suite.

This is backlog item 12's ratchet, and the reason it exists is one defect:
`zip_update` - the function that replaces a user's install - had no test of any
kind, so a variable shadowing that pointed the whole install at the temp
directory passed a suite of 2869 tests. Thirty more functions were in the same
state when the audit was first run, among them the startup settings migration
and every piece of PlanTrim's crop arithmetic.

**What this measures, and what it does not.** It asks whether any test file
*mentions the name*. That is weaker than coverage and deliberately so:
instrumentation roughly doubles the suite's runtime, and this takes under a
second, so it can run on every commit instead of on a good intention. Two
consequences worth stating plainly, because a reader who assumes otherwise will
trust it too far:

* A function called only indirectly by something a test runs still has to be
  named somewhere. That is the cost of the cheap check, and it is a small one -
  naming it in the test that exercises it through its caller is honest.
* **A name in a comment satisfies it.** So this cannot tell a real test from a
  mention, and it is not trying to. `tests/test_a_test_must_be_able_to_fail.py`
  is the guard for test quality; this one is the guard for test *existence*.
  Answering a failure here by writing the name into a docstring would satisfy
  the letter of it and leave the function exactly as untested as before.

**Why a baseline rather than a hard zero.** The same reasoning as
`source_string_assertion_baseline.json`: a gap somebody has looked at and
decided to leave is different from a gap nobody knows about, and a file that
can record that decision is one people keep using. It is currently **empty**,
which is the strongest state it can be in - anything new fails.

Methods are out of scope on purpose. A class is normally reached through its
constructor, so a method nobody names is much weaker evidence than a
module-level function nobody names, and including them would fill the baseline
with noise until nobody read it.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).resolve().parent / "functions_never_named_baseline.json"

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "_wd_fn_audit", ROOT / "scripts" / "audit_functions_never_named_by_a_test.py")
_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_audit)


def allowed() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))["allowed"]


def key(row) -> str:
    return "tools/%s::%s" % (row["module"], row["name"])


#: The survey reads every test file in the repository, which is a second or two.
#: Doing that once per test method turned this file into the slowest in the
#: suite for no gain - nothing here writes to the tree, so one survey is the
#: same answer every time.
_SURVEY = None


def survey_once():
    global _SURVEY
    if _SURVEY is None:
        _SURVEY = _audit.survey()
    return _SURVEY


class EveryPublicFunctionIsNamedBySomeTestTests(unittest.TestCase):

    def setUp(self):
        self.rows = survey_once()
        self.missing = {key(r): r for r in self.rows if not r["named_by_a_test"]}
        self.allowed = allowed()

    def test_the_survey_really_looked_at_something(self):
        """A check that silently surveyed nothing is a comment.

        If `tools/` moved, or the script stopped parsing, every assertion
        below would pass on an empty list and this file would go on reporting
        success forever.
        """
        self.assertGreater(len(self.rows), 100,
                           "the audit found almost no functions - it is "
                           "probably looking in the wrong place")

    def test_no_public_function_is_without_a_test(self):
        new = sorted(set(self.missing) - set(self.allowed))
        self.assertEqual(
            [], new,
            "these public functions in tools/ are named by no test:\n  "
            + "\n  ".join(new)
            + "\n\nWrite a test that RUNS the function. If one genuinely does "
              "not belong under test, add it to "
              "tests/functions_never_named_baseline.json with the reason - "
              "but that file is empty today, and keeping it empty is the "
              "point of it.")

    def test_the_baseline_holds_nothing_that_is_already_covered(self):
        """A ratchet only ratchets if a stale entry is a failure.

        An entry left behind after the gap was closed quietly raises the
        ceiling again: the next function to land on that name inherits the
        exemption without anybody deciding to give it one.
        """
        stale = sorted(set(self.allowed) - set(self.missing))
        self.assertEqual(
            [], stale,
            "these baseline entries are no longer needed - remove them:\n  "
            + "\n  ".join(stale))

    def test_every_baseline_entry_gives_a_reason(self):
        blank = sorted(k for k, v in self.allowed.items()
                       if not str(v or "").strip())
        self.assertEqual([], blank,
                         "a baseline entry with no reason is a gap nobody "
                         "decided on: %r" % (blank,))

    def test_anything_a_browser_can_reach_is_never_exempt(self):
        """A route `server.py` exposes is reachable from the page.

        Those are the ones where an untested function is not a tidiness
        question - `api_trim_to` and `migrate_legacy` were both in this
        category when the audit was first run.
        """
        reachable = sorted(k for k, r in self.missing.items()
                           if r["called_by_the_server"] and k in self.allowed)
        self.assertEqual(
            [], reachable,
            "these are reachable from server.py and must not be exempt:\n  "
            + "\n  ".join(reachable))


class TheCheckCanActuallyFailTests(unittest.TestCase):
    """Mutating the repository to prove a guard works is not an option here,
    so the survey is run against a function name that cannot exist."""

    def test_a_name_no_test_mentions_would_be_reported(self):
        """Assembled from pieces, because this file is itself in `tests/`.

        Writing the probe name as one literal put it in a test file, which is
        exactly the condition being probed for - the first version of this
        failed on its own existence. Joining it at runtime means the whole
        name appears nowhere on disk.
        """
        import re
        invented = "_".join(["a", "function", "no", "test", "could",
                             "possibly", "mention", "xyzzy"])
        self.assertNotIn(invented, {r["name"] for r in survey_once()})

        test_text = "\n".join(
            p.read_text(encoding="utf-8", errors="ignore")
            for p in sorted((ROOT / "tests").glob("*.py")))
        self.assertIsNone(re.search(r"\b%s\b" % invented, test_text),
                          "the invented name turned up in a test file, so "
                          "this probe proves nothing")

    def test_a_name_every_test_mentions_is_not_reported(self):
        """The other direction: the matcher must not report a covered
        function, or the baseline would fill with false positives and stop
        being read."""
        rows = {r["name"]: r for r in survey_once()}
        self.assertIn("zip_update", rows)
        self.assertTrue(rows["zip_update"]["named_by_a_test"],
                        "zip_update is covered by "
                        "test_release_archive_paths_are_contained.py")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
