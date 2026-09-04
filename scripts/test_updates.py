#!/usr/bin/env python3
"""Run the update-path harness on its own, with a readable summary.

    python scripts/test_updates.py
    python scripts/test_updates.py -v

Every scenario builds a throwaway install in a temp directory and upgrades it
against a local fixture remote. Nothing here touches GitHub, and nothing here
touches the install you are running from — so it is safe to run repeatedly on a
working machine.

The full test suite runs these too (`python -m unittest discover -s tests`);
this exists so the update mechanism can be exercised on its own while it is
being changed, which is when it matters most.
"""
from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SCENARIOS = """
  fresh git install            -> update
  already newest               -> no change, says so
  update twice                 -> second release picked up
  ZIP install -> convert       -> update -> update      (the reported bug)
  already detached HEAD        -> updates cleanly
  left on a branch             -> moves to the release tag
  dirty tracked file           -> refused, in plain words
  untracked .esx present       -> update proceeds, file kept
  customized wall template     -> rescued, not blocked
  no network                   -> plain message, nothing moved
  git missing                  -> reported, not a crash
  origin missing               -> repaired automatically
  ZIP install                  -> not mistaken for git
  shipped launchers            -> contain no `git pull`
  detached + `git pull`        -> reproduces the original failure
"""


def main() -> int:
    if shutil.which("git") is None:
        print("git is not installed - the update harness needs it.")
        return 2

    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    print("WD Wireless Tools - update path harness")
    print("Throwaway installs in a temp dir, against a local fixture remote.")
    print(SCENARIOS)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames([
        "tests.test_update_paths",
        "tests.test_updater",
    ])
    runner = unittest.TextTestRunner(verbosity=2 if verbose else 1)
    result = runner.run(suite)

    print()
    if result.wasSuccessful():
        print(f"OK - {result.testsRun} checks passed. "
              "Every update path ends on a release tag and says something a "
              "person can act on.")
        return 0
    print(f"FAILED - {len(result.failures)} failure(s), {len(result.errors)} error(s) "
          f"out of {result.testsRun}.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
