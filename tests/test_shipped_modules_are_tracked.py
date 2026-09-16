"""Every module the shipped code imports has to be a file git actually has.

v2.102.0 shipped `tools/settings.py` importing `tools.user_dir` while
`tools/user_dir.py` sat untracked on the author's disk. The suite passed
locally - the file was right there - and every one of the 911 tests in CI
errored with `No module named 'tools.user_dir'`. The tag and the release went
out anyway, so the release ZIP was never built and anyone who ran `git pull`
got a server that could not start: `server.py` imports `tools.settings` at
module scope, so the traceback arrived instead of the app.

A missing import is invisible to every other test in this suite, because every
other test runs against a working tree where the file exists. The only
question that catches it is whether the file is *tracked*, which is what this
asks. It fails on the machine the commit is made on, before the push.
"""
from __future__ import annotations

import ast
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _tracked() -> set[str] | None:
    """Repo-relative paths git has, or None when git cannot answer."""
    try:
        proc = subprocess.run(["git", "ls-files"], cwd=str(ROOT),
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def _first_party_packages(tracked: set[str]) -> set[str]:
    """Top-level directories of this repo that hold tracked Python."""
    return {p.split("/", 1)[0] for p in tracked
            if "/" in p and p.endswith(".py")}


def _imported_modules(source: str) -> set[str]:
    """Dotted module names imported by `source`, absolute imports only."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # `from . import x` is relative and resolves by location, not name.
            if node.level == 0 and node.module:
                names.add(node.module)
    return names


def _candidates(module: str) -> tuple[str, str]:
    path = module.replace(".", "/")
    return path + ".py", path + "/__init__.py"


class EveryImportedModuleIsTrackedTests(unittest.TestCase):

    def test_no_tracked_file_imports_a_module_git_does_not_have(self):
        tracked = _tracked()
        if tracked is None:
            self.skipTest("git is unavailable, so trackedness cannot be read")
        packages = _first_party_packages(tracked)
        self.assertIn("tools", packages,
                      "expected tools/ to hold tracked Python")

        missing = []
        for rel in sorted(p for p in tracked if p.endswith(".py")):
            text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
            for module in sorted(_imported_modules(text)):
                if module.split(".", 1)[0] not in packages:
                    continue        # stdlib or a dependency, not ours to ship
                if any(c in tracked for c in _candidates(module)):
                    continue
                on_disk = any((ROOT / c).exists() for c in _candidates(module))
                missing.append(
                    f"{rel} imports {module}, which git does not have"
                    + (" (it exists untracked on this machine - `git add` it)"
                       if on_disk else " (no such file anywhere)"))

        self.assertEqual([], missing, "\n".join([""] + missing))


if __name__ == "__main__":
    unittest.main()
