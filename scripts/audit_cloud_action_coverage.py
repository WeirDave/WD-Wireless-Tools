#!/usr/bin/env python3
"""Which of Cloud Manager's server actions no test ever names.

The whole-tool audit of 2026-09-18 counted this, and backlog item 4 carried the
number forward for five releases - but **the counting was never committed**, so
nobody could reproduce it and the item had to say so: *"the audit's counting
method was never committed as a script, so the two are not the same measurement
and the difference is not a trend."*

A number nobody can re-derive is not a measurement, it is a memory. This is the
script, so the figure in the item can be checked rather than believed.

**What counts as covered is deliberately generous**: the action's name appearing
anywhere in `tests/`. That over-reports - a name in a docstring counts, and
`delete_cloud` spent the whole audit period appearing in exactly one docstring
and nowhere else - and over-reporting is the right direction for a *gap* list.
Anything this calls uncovered is uncovered by any reading.

Usage:
    python scripts/audit_cloud_action_coverage.py [--json]
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server.py"
TESTS = ROOT / "tests"


def cloud_actions() -> list[str]:
    """The keys of CLOUD_ACTIONS, read from the parsed module.

    Parsed rather than grepped: the table is a dict literal of lambdas, and a
    regex over it would also match every action name mentioned in the comments
    around it.
    """
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "CLOUD_ACTIONS":
                    if isinstance(node.value, ast.Dict):
                        return [k.value for k in node.value.keys
                                if isinstance(k, ast.Constant)]
    raise SystemExit("CLOUD_ACTIONS is not a dict literal in server.py any more")


def named_in_tests() -> set[str]:
    """Every word that appears anywhere under tests/."""
    words: set[str] = set()
    for path in sorted(TESTS.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        words |= set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text))
    return words


def main() -> int:
    actions = cloud_actions()
    words = named_in_tests()
    missing = sorted(a for a in actions if a not in words)
    covered = len(actions) - len(missing)

    if "--json" in sys.argv:
        print(json.dumps({"total": len(actions), "covered": covered,
                          "uncovered": missing}, indent=2))
        return 0

    print("Cloud Manager server actions")
    print("=" * 62)
    print("%-40s %d" % ("actions in CLOUD_ACTIONS", len(actions)))
    print("%-40s %d" % ("named somewhere in tests/", covered))
    print("%-40s %d" % ("named nowhere in tests/", len(missing)))
    if missing:
        print()
        for a in missing:
            print("  " + a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
