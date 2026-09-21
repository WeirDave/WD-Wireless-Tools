"""Which public functions in `tools/` does no test so much as mention?

Written after `zip_update` - the one function that replaces a user's install -
turned out to have no test at all, which is how a variable shadowing that
pointed the whole install at the temp directory passed a full green suite. The
suite had 2853 tests and none of them had ever run it.

**This is a name search, not coverage.** A function called only indirectly by
something a test does run will be listed here although it executes, and that is
the deliberate trade: coverage instrumentation doubles the suite's runtime and
this takes under a second, so it can be run on a whim. Treat the output as a
list to read rather than as a verdict - the question to ask of each line is
"if this were wrong, what would fail?", and "nothing" is the answer worth
acting on.

It is also the weaker of the two possible checks in one specific way: a
function whose *name* a test mentions only in a comment or an assertion string
counts as reached. That is the same weakness the source-string assertions have,
and it is why the answer to a line here is a test that runs the function rather
than one that names it.

    python scripts/audit_functions_never_named_by_a_test.py

Add `--all` to list every public function with its status instead of only the
unnamed ones.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
TESTS = ROOT / "tests"
SERVER = ROOT / "server.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def public_functions(module: Path):
    """Top-level, non-underscore functions only.

    Methods are left out on purpose: a class is normally reached through its
    constructor, so a method nobody names is much weaker evidence than a
    module-level function nobody names.
    """
    tree = ast.parse(_read(module))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                yield node.name, node.lineno


def survey():
    test_text = "\n".join(_read(p) for p in sorted(TESTS.glob("*.py")))
    server_text = _read(SERVER) if SERVER.exists() else ""
    rows = []
    for module in sorted(TOOLS.glob("*.py")):
        if module.name == "__init__.py":
            continue
        for name, line in public_functions(module):
            word = re.compile(r"\b%s\b" % re.escape(name))
            rows.append({
                "module": module.name,
                "name": name,
                "line": line,
                "named_by_a_test": bool(word.search(test_text)),
                "called_by_the_server": bool(word.search(server_text)),
            })
    return rows


def main(argv) -> int:
    rows = survey()
    show_all = "--all" in argv
    shown = rows if show_all else [r for r in rows if not r["named_by_a_test"]]

    missing = [r for r in rows if not r["named_by_a_test"]]
    print("%d of %d public functions in tools/ are named by no test.\n"
          % (len(missing), len(rows)))

    current = None
    for row in shown:
        if row["module"] != current:
            current = row["module"]
            print(current)
        flags = []
        if show_all and row["named_by_a_test"]:
            flags.append("named by a test")
        if row["called_by_the_server"]:
            flags.append("reachable from server.py")
        suffix = ("  (%s)" % ", ".join(flags)) if flags else ""
        print("    %-38s :%d%s" % (row["name"], row["line"], suffix))

    reachable = [r for r in missing if r["called_by_the_server"]]
    if reachable:
        print("\nOf those, %d are reachable from server.py, which means a "
              "browser can call them:" % len(reachable))
        for row in reachable:
            print("    %s.%s" % (row["module"], row["name"]))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
