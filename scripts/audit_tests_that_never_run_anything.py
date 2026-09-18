"""Which test files assert on source text and never execute the thing.

A file that slices a function out of `report.js` and runs it in Node is doing
the right thing even if it also checks a string or two. A file whose every
assertion is "the source contains this" cannot fail when the behaviour is
removed, which is the whole problem.

Run: python scripts/audit_tests_that_never_run_anything.py
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

#: signs that a file actually runs the code under test
EXECUTES = re.compile(
    r"subprocess\.(run|check_output|Popen)"      # node, or a CLI
    r"|test_client\(\)|app\.test_client"          # flask
    r"|importlib\.import_module"
    r"|^\s*from tools\.|^\s*import tools\b"       # the module itself
    r"|webdriver\.|print_page\("
    , re.M)


def main() -> int:
    audit = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "audit_source_string_tests.py"), "--csv"],
        capture_output=True, text=True, errors="replace")
    counts: dict[str, int] = {}
    for line in audit.stdout.splitlines()[1:]:
        name = line.split(",", 1)[0]
        if name.endswith(".py"):
            counts[name] = counts.get(name, 0) + 1

    pure, mixed = [], []
    for name, n in counts.items():
        text = (TESTS / name).read_text(encoding="utf-8", errors="replace")
        (mixed if EXECUTES.search(text) else pure).append((name, n))

    pure.sort(key=lambda kv: -kv[1])
    mixed.sort(key=lambda kv: -kv[1])

    print("Files that assert on source text and NEVER execute anything")
    print("=" * 72)
    for name, n in pure:
        print("  %-52s %4d assertions" % (name, n))
    print("  %-52s %4d assertions in %d files"
          % ("SUBTOTAL", sum(n for _, n in pure), len(pure)))
    print()
    print("Files that do execute, but also assert on source text")
    print("=" * 72)
    for name, n in mixed[:15]:
        print("  %-52s %4d assertions" % (name, n))
    print("  %-52s %4d assertions in %d files"
          % ("SUBTOTAL", sum(n for _, n in mixed), len(mixed)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
