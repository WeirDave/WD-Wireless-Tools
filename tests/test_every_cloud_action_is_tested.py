"""Every Cloud Manager server action is named by some test, and stays that way.

This is the close of backlog item 4 and of the 2026-09-18 whole-tool audit.
Twenty of the fifty-one actions were named in no test file when the audit was
written; the destructive ones were covered in v2.148.0, the sharing group in
v2.153.0, and the last eleven here.

**It can be an absolute rather than a baseline**, unlike the source-string
ratchet next door, because the number is zero. A baseline that tolerates
existing debt is the right shape when there is debt; there is none, so the
check is simply that a new action arrives with a test.

**What counts as covered is deliberately generous** - the action's name
appearing anywhere under `tests/`. That over-reports: a name in a docstring
counts, and `delete_cloud` spent the whole audit period appearing in exactly
one docstring and nowhere else, which is how the gap stayed invisible. Over-
reporting is the right direction for a guard against *forgetting*, and the
wrong direction for judging whether a test is any good - that is what
`test_a_test_must_be_able_to_fail.py` is for, and the two work together rather
than one standing in for the other.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.audit_cloud_action_coverage import cloud_actions, named_in_tests


class EveryActionIsNamedSomewhereTests(unittest.TestCase):

    def test_the_table_is_still_readable(self):
        """The audit is run off the parsed table.

        If `CLOUD_ACTIONS` ever stops being a dict literal the script raises,
        and a guard that cannot read its subject has to say so rather than
        report zero problems.
        """
        actions = cloud_actions()
        self.assertGreater(len(actions), 40,
                           "the action table looks far too short - has it "
                           "moved, or stopped being a dict literal?")

    def test_no_action_is_without_a_test(self):
        actions = cloud_actions()
        words = named_in_tests()
        missing = sorted(a for a in actions if a not in words)
        self.assertEqual(
            [], missing,
            "these Cloud Manager actions are named in no test file:\n  "
            + "\n  ".join(missing)
            + "\n\nA server action nobody exercises is one the page can call "
              "and nothing has ever run. Add a test that executes it - and "
              "pin its route in CLOUD_ACTIONS separately, because a lambda "
              "reading the wrong key hands a perfect method the wrong "
              "argument.")

    def test_the_count_is_reported_the_same_way_the_script_reports_it(self):
        """The script and this test must not be able to disagree.

        Backlog item 4 carried a number for five releases that nobody could
        re-derive, because the audit's counting was never committed. Both ends
        read the same two functions now, so the figure in the item is a
        measurement rather than a memory.
        """
        actions = cloud_actions()
        words = named_in_tests()
        covered = sum(1 for a in actions if a in words)
        self.assertEqual(len(actions), covered)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
