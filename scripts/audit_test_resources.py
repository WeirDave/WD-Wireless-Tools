#!/usr/bin/env python3
"""Resources the test suite starts, and whether they are really stopped.

The Firefox leak is the shape this looks for. A browser suite ended with

    with contextlib.suppress(Exception):
        driver.quit()

which reads as unconditional cleanup and is not: when the driver has stopped
answering - which happens under memory pressure, exactly when a leak costs the
most - `quit()` raises, the `suppress` that was put there to make teardown
reliable swallows it, and the browser outlives the run. Three headless Firefox
processes and 2 GB of 32 GB free, measured on 2026-09-21, and the next run died
before its first assertion.

So there are two findings, and the second is the one nobody looks for:

  **never**      acquired and no release call anywhere in that scope
  **suppressed** released only inside a `try/except: pass` or a
                 `contextlib.suppress`, so a failed release is indistinguishable
                 from a successful one

Only things that cost something when they leak are tracked - a process, a
listening socket, a browser. A suppressed `file.close()` is not interesting and
would bury the ones that are.

Temporary directories have their own ratchet in
`tests/test_housekeeping.py::TheSuiteCleansUpAfterItself`, so they are left to
it rather than reported twice.

Run it for the inventory; `tests/test_nothing_is_left_running.py` is the guard.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

#: What counts as taking hold of something expensive, and what lets it go.
#: The call is matched on its last attribute - `subprocess.Popen` and a bare
#: `Popen` are the same acquisition.
ACQUIRE = {
    "Popen": ("process", ("kill", "terminate", "wait", "communicate",
                          "__exit__", "shut_down")),
    "HTTPServer": ("server", ("shutdown", "server_close", "close", "stop_server")),
    "ThreadingHTTPServer": ("server", ("shutdown", "server_close", "close", "stop_server")),
    "TCPServer": ("server", ("shutdown", "server_close", "close", "stop_server")),
    "Firefox": ("browser", ("quit", "shut_down")),
    "Chrome": ("browser", ("quit", "shut_down")),
    "Edge": ("browser", ("quit", "shut_down")),
    "Remote": ("browser", ("quit", "shut_down")),
}

#: A release named as an argument rather than called on the object -
#: `browsers.shut_down(driver)` releases `driver`.
RELEASE_FUNCS = {"shut_down", "stop_server", "kill", "terminate"}


def _tail(node: ast.AST) -> str:
    """`subprocess.Popen` -> 'Popen'; `Popen` -> 'Popen'."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _target_names(node: ast.AST) -> list:
    out = []
    for t in getattr(node, "targets", []) or []:
        if isinstance(t, ast.Name):
            out.append(t.id)
        elif isinstance(t, ast.Attribute):
            out.append(t.attr)
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        out.append(node.target.id)
    return out


class Scope:
    """One function or class body: what it took, and what it let go of."""

    def __init__(self, name):
        self.name = name
        self.acquired = {}        # name -> (kind, lineno, verbs)
        self.released = {}        # name -> True if any release is unguarded


def _suppressed(stack) -> bool:
    """Is this statement inside something that swallows a failure?"""
    for node in stack:
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                body = handler.body
                if len(body) == 1 and isinstance(body[0], (ast.Pass, ast.Continue)):
                    return True
        if isinstance(node, ast.With):
            for item in node.items:
                call = item.context_expr
                if isinstance(call, ast.Call) and _tail(call.func) == "suppress":
                    return True
    return False


def scan(path: Path) -> list:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"),
                     filename=str(path))
    findings = []

    class Walker(ast.NodeVisitor):
        def __init__(self):
            self.stack = []
            self.scopes = []

        # ---- scopes -------------------------------------------------
        def _enter(self, node, label):
            scope = Scope(label)
            self.scopes.append(scope)
            self.stack.append(node)
            self.generic_visit(node)
            self.stack.pop()
            self.scopes.pop()
            return scope

        def visit_ClassDef(self, node):
            # A class body is one scope: setUpClass takes it, tearDownClass
            # lets it go, and neither sees the other's locals.
            scope = self._enter(node, node.name)
            self._report(path, scope)

        def visit_FunctionDef(self, node):
            if self.scopes:
                # A method inside a class shares the class scope.
                self.stack.append(node)
                self.generic_visit(node)
                self.stack.pop()
                return
            scope = self._enter(node, node.name)
            self._report(path, scope)

        visit_AsyncFunctionDef = visit_FunctionDef

        # ---- statements ---------------------------------------------
        def visit_Assign(self, node):
            self._maybe_acquire(node)
            self.generic_visit(node)

        def visit_AnnAssign(self, node):
            self._maybe_acquire(node)
            self.generic_visit(node)

        def _maybe_acquire(self, node):
            if not self.scopes or not isinstance(node.value, ast.Call):
                return
            kind_verbs = ACQUIRE.get(_tail(node.value.func))
            if not kind_verbs:
                return
            # `with Popen(...) as p:` releases on exit; only a bare assignment
            # is a thing somebody has to remember.
            if any(isinstance(n, ast.With) and
                   any(i.context_expr is node.value for i in n.items)
                   for n in self.stack):
                return
            for name in _target_names(node):
                self.scopes[-1].acquired.setdefault(
                    name, (kind_verbs[0], node.lineno, kind_verbs[1]))

        def visit_Call(self, node):
            if self.scopes:
                self._maybe_release(node)
            self.generic_visit(node)

        def _maybe_release(self, node):
            scope = self.scopes[-1]
            guarded = _suppressed(self.stack)
            # `x.quit()` / `cls.driver.quit()`
            if isinstance(node.func, ast.Attribute):
                verb = node.func.attr
                owner = node.func.value
                name = _tail(owner)
                if name:
                    known = scope.acquired.get(name)
                    if known and verb in known[2]:
                        scope.released[name] = (scope.released.get(name, False)
                                                or not guarded)
            # `browsers.shut_down(driver)` / `kill(proc)`
            if _tail(node.func) in RELEASE_FUNCS:
                for arg in node.args:
                    name = _tail(arg)
                    if name and name in scope.acquired:
                        scope.released[name] = (scope.released.get(name, False)
                                                or not guarded)
            # `addCleanup(server.server_close)` and
            # `addClassCleanup(browsers.shut_down, driver)`. unittest runs these
            # itself, on the failure path too, so registering counts as
            # releasing - and it is the better form, because a cleanup that
            # raises is reported rather than swallowed.
            if _tail(node.func) in ("addCleanup", "addClassCleanup"):
                for arg in node.args:
                    if isinstance(arg, ast.Attribute):
                        owner = _tail(arg.value)
                        known = scope.acquired.get(owner)
                        if known and arg.attr in known[2]:
                            scope.released[owner] = True
                    name = _tail(arg)
                    if name in scope.acquired:
                        scope.released[name] = True

        # ---- with-statement acquisitions ----------------------------
        def visit_With(self, node):
            self.stack.append(node)
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncWith = visit_With
        visit_Try = visit_With

        def _report(self, path, scope):
            for name, (kind, lineno, _verbs) in scope.acquired.items():
                if name not in scope.released:
                    findings.append((path.name, lineno, scope.name, name,
                                     kind, "never"))
                elif not scope.released[name]:
                    findings.append((path.name, lineno, scope.name, name,
                                     kind, "suppressed"))

    Walker().visit(tree)
    return findings


def audit() -> list:
    out = []
    for path in sorted(TESTS.glob("*.py")):
        out.extend(scan(path))
    return sorted(out)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    rows = audit()
    never = [r for r in rows if r[5] == "never"]
    guarded = [r for r in rows if r[5] == "suppressed"]
    print(f"{len(rows)} findings: {len(never)} never released, "
          f"{len(guarded)} released only where a failure is swallowed")
    for name, lineno, scope, var, kind, how in rows:
        print(f"  [{how:>10}] {name}:{lineno} {scope}() holds {var!r} ({kind})")
    return 1 if rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
