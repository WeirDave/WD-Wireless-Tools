"""Every server a test starts in-process binds port 0.

The browser modules used to probe for a free port from a fixed hint and then
bind it. The hints' ranges overlapped, four modules run at once in CI, and on
Windows `SO_REUSEADDR` (which `http.server` sets) lets a second server bind a
port already in use - so the page under test could be answered by another
module's stub. It surfaced as failures in whichever module lost the race:
AP Labeler's floors never loading, in Edge and then Chrome; Cloud menu items
"drawn" nowhere. See `tests/browsers.ExclusiveServer`.

Port 0 is assigned by the OS, atomically, so it cannot collide. Read from the
parsed source of every test module: each `ThreadingHTTPServer`, `HTTPServer`,
`ExclusiveServer`, `QuietServer` and werkzeug `make_server` call must be given
the literal port 0.

Not covered, deliberately: `test_the_dev_gate_works_end_to_end.py` starts
`server.py` as its own process and has to tell it a port number up front.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SERVERS = {"ThreadingHTTPServer", "HTTPServer", "ExclusiveServer", "QuietServer"}


def _name(func) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _port_arg(call: ast.Call):
    name = _name(call.func)
    if name == "make_server":
        return call.args[1] if len(call.args) > 1 else None
    if name in SERVERS and call.args and isinstance(call.args[0], ast.Tuple):
        elts = call.args[0].elts
        return elts[1] if len(elts) > 1 else None
    return None


def _offenders():
    found, calls = [], 0
    for path in sorted(TESTS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _name(node.func) not in SERVERS | {"make_server"}:
                continue
            port = _port_arg(node)
            if port is None:
                continue
            calls += 1
            if not (isinstance(port, ast.Constant) and port.value == 0):
                found.append("%s:%d" % (path.name, node.lineno))
    return found, calls


class EveryStubServerHasAPortOfItsOwn(unittest.TestCase):
    def test_there_are_servers_to_check(self):
        """A scan that finds nothing passes every assertion of absence."""
        self.assertGreaterEqual(_offenders()[1], 15)

    def test_every_one_binds_port_zero(self):
        found, _ = _offenders()
        self.assertEqual(found, [], "bind port 0 and read the port back - "
                         "a probed port can be shared: " + ", ".join(found))


if __name__ == "__main__":
    unittest.main()
