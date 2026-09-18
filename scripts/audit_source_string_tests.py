"""Find tests that assert a source file *contains* something.

The shape: `assertIn("someFunction(", js)` where `js` is the text of a file
read off disk. It passes whether or not the code does anything, which is how
five defects shipped green - see the CLAUDE.md section this belongs to.

What counts as a source haystack: any name assigned from `.read_text(`,
`open(...).read()`, `Path(...).read_text()` or `git show`, plus `self.<name>`
of the same. Rendered output, subprocess stdout and parsed JSON do not count -
those are executions, which is what we want more of.

Run: python scripts/audit_source_string_tests.py [--csv]
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

READS_SOURCE = re.compile(
    r"read_text\(|\.read\(\)|read_bytes\(|git\s+show|ls-files", re.I)

#: A haystack name that is a rendered/executed result rather than a file.
EXECUTED_HINTS = ("html", "out", "output", "rendered", "result", "stdout",
                  "body", "resp", "payload", "doc", "page")


class FileAudit(ast.NodeVisitor):
    def __init__(self, path: Path, src: str):
        self.path = path
        self.src = src
        self.lines = src.splitlines()
        self.source_names: set[str] = set()
        self.findings: list[tuple[int, str, str]] = []

    # names assigned from something that reads a file
    def visit_Assign(self, node: ast.Assign):
        seg = ast.get_source_segment(self.src, node) or ""
        if READS_SOURCE.search(seg):
            for t in node.targets:
                for name in self._names(t):
                    self.source_names.add(name)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        seg = ast.get_source_segment(self.src, node) or ""
        if node.value is not None and READS_SOURCE.search(seg):
            for name in self._names(node.target):
                self.source_names.add(name)
        self.generic_visit(node)

    @staticmethod
    def _names(target) -> list[str]:
        if isinstance(target, ast.Name):
            return [target.id]
        if isinstance(target, ast.Attribute):
            return [target.attr]
        if isinstance(target, (ast.Tuple, ast.List)):
            out = []
            for e in target.elts:
                out += FileAudit._names(e)
            return out
        return []

    def visit_Call(self, node: ast.Call):
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr in (
                "assertIn", "assertNotIn", "assertRegex", "assertNotRegex"):
            if len(node.args) >= 2:
                hay = self._hay_name(node.args[1])
                if hay and hay in self.source_names:
                    needle = ast.get_source_segment(self.src, node.args[0]) or "?"
                    self.findings.append(
                        (node.lineno, hay, needle.strip().replace("\n", " ")[:70]))
        self.generic_visit(node)

    @staticmethod
    def _hay_name(node) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Subscript):
            return FileAudit._hay_name(node.value)
        return None


def main() -> int:
    rows = []
    module_level_sources: dict[Path, set[str]] = {}
    for path in sorted(TESTS.glob("test_*.py")):
        src = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            print("!! could not parse %s: %s" % (path.name, e))
            continue
        a = FileAudit(path, src)
        a.visit(tree)
        module_level_sources[path] = a.source_names
        for line, hay, needle in a.findings:
            rows.append((path.name, line, hay, needle))

    by_file: dict[str, int] = {}
    for name, _, _, _ in rows:
        by_file[name] = by_file.get(name, 0) + 1

    if "--csv" in sys.argv:
        print("file,line,haystack,needle")
        for name, line, hay, needle in rows:
            print('%s,%d,%s,"%s"' % (name, line, hay, needle.replace('"', "'")))
        return 0

    print("Assertions against the text of a source file")
    print("=" * 72)
    print("%-52s %s" % ("file", "count"))
    for name, n in sorted(by_file.items(), key=lambda kv: -kv[1]):
        print("%-52s %5d" % (name, n))
    print("-" * 72)
    print("%-52s %5d  in %d files" % ("TOTAL", len(rows), len(by_file)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
