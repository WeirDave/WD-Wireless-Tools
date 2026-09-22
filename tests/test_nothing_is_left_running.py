"""Nothing this suite starts is allowed to outlive it.

The browser case is written up in `test_a_browser_is_really_stopped.py`: a
teardown that reads as unconditional, a `quit()` that raises when the driver
has stopped answering, a `suppress` that swallows it, and three headless
Firefox processes left on a machine with 2 GB free.

Auditing the rest of the suite for that shape found two more, and neither was
a browser:

* **Seven server teardowns put both calls in one `suppress`.**

      with contextlib.suppress(Exception):
          server.shutdown()
          server.server_close()

  `server_close()` is the one that releases the listening socket, and it is
  inside the same block as the call before it - so a `shutdown()` that raises
  takes it with it and the port stays held. Worse than the browser case, in
  that one failure loses both.

* **Two suites handed `driver.quit` over as a callable**,
  `addClassCleanup(cls.driver.quit)`. Identical defect, and the sweep written
  the day before looked for a *call* and went straight past them.

`scripts/audit_test_resources.py` is the inventory. It reads the tests rather
than running them, which is the only way to ask this question of a suite that
takes a quarter of an hour, and it reports two things: acquired and never
released, and released only where a failure is swallowed.

`TheAuditCanFail` is the important class here. A guard for a defect that has
already been fixed proves nothing unless it is shown to fail on that defect,
so it reconstructs both shapes and requires each to be caught.
"""
from __future__ import annotations

import socket
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.audit_test_resources import audit, scan  # noqa: E402
from tests import browsers  # noqa: E402


class NothingIsLeftRunning(unittest.TestCase):

    def test_every_process_server_and_browser_is_really_released(self):
        rows = audit()
        self.assertEqual(
            [], rows,
            "these start something and do not reliably stop it:\n  "
            + "\n  ".join(f"{f}:{line} {scope}() holds {var!r} ({kind}) - {how}"
                          for f, line, scope, var, kind, how in rows))


class TheAuditCanFail(unittest.TestCase):
    """Both shapes, reconstructed. If these stop failing, the audit is inert."""

    def _scan(self, source):
        # `TemporaryDirectory` with `addCleanup`, not `enterContext` - that
        # arrived in Python 3.11 and the suite still runs on 3.10, where every
        # test in this class errored while 3.14 passed.
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "test_probe.py"
        path.write_text(textwrap.dedent(source), encoding="utf-8")
        return scan(path)

    def test_a_browser_that_is_never_quit_is_caught(self):
        rows = self._scan("""
            class T:
                @classmethod
                def setUpClass(cls):
                    cls.driver = webdriver.Firefox(options=o)
        """)
        self.assertEqual(1, len(rows), rows)
        self.assertEqual("never", rows[0][5])
        self.assertEqual("browser", rows[0][4])

    def test_the_suppressed_quit_that_started_this_is_caught(self):
        """The original. It reads as cleanup and is not."""
        rows = self._scan("""
            class T:
                @classmethod
                def setUpClass(cls):
                    cls.driver = webdriver.Firefox(options=o)

                @classmethod
                def tearDownClass(cls):
                    with contextlib.suppress(Exception):
                        cls.driver.quit()
        """)
        self.assertEqual(1, len(rows), rows)
        self.assertEqual("suppressed", rows[0][5])

    def test_the_coupled_server_teardown_is_caught(self):
        """Both calls in one suppress: a failing shutdown() keeps the port."""
        rows = self._scan("""
            class T:
                @classmethod
                def setUpClass(cls):
                    cls.server = ThreadingHTTPServer(addr, handler)

                @classmethod
                def tearDownClass(cls):
                    with contextlib.suppress(Exception):
                        cls.server.shutdown()
                        cls.server.server_close()
        """)
        self.assertEqual(1, len(rows), rows)
        self.assertEqual("suppressed", rows[0][5])
        self.assertEqual("server", rows[0][4])

    def test_a_try_except_pass_counts_as_swallowing_it(self):
        rows = self._scan("""
            def go():
                proc = subprocess.Popen(cmd)
                try:
                    proc.kill()
                except Exception:
                    pass
        """)
        self.assertEqual(1, len(rows), rows)
        self.assertEqual("suppressed", rows[0][5])

    def test_a_plain_release_passes(self):
        self.assertEqual([], self._scan("""
            class T:
                @classmethod
                def setUpClass(cls):
                    cls.driver = webdriver.Firefox(options=o)

                @classmethod
                def tearDownClass(cls):
                    _browsers.shut_down(cls.driver)
        """))

    def test_a_registered_cleanup_passes(self):
        """`addCleanup` is the better form - unittest runs it on the failure
        path too, and a cleanup that raises is reported rather than lost."""
        self.assertEqual([], self._scan("""
            class T:
                @classmethod
                def setUpClass(cls):
                    cls.server = ThreadingHTTPServer(addr, handler)
                    cls.addClassCleanup(cls.server.server_close)
        """))

    def test_a_with_statement_passes(self):
        """Nobody has to remember a context manager."""
        self.assertEqual([], self._scan("""
            def go():
                with subprocess.Popen(cmd) as proc:
                    proc.communicate()
        """))


class StopServerReallyReleasesThePort(unittest.TestCase):
    """Run rather than read. The claim is about a socket, so a socket is what
    is bound, closed and bound again."""

    def _server(self):
        from http.server import HTTPServer, BaseHTTPRequestHandler
        srv = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        self.addCleanup(lambda: browsers.stop_server(srv))
        return srv

    def test_the_port_comes_free(self):
        srv = self._server()
        address = srv.server_address
        self.assertTrue(browsers.port_held(srv), "it never bound the port")
        self.assertTrue(browsers.stop_server(srv))
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(probe.close)
        probe.bind(address)          # raises if the socket is still held

    def test_a_failing_shutdown_still_closes_the_socket(self):
        """The defect. `server_close()` sat after `shutdown()` inside one
        suppress, so it never ran when the first call raised."""
        srv = self._server()
        address = srv.server_address

        def boom():
            raise RuntimeError("shutdown did not work")

        srv.shutdown = boom
        browsers.stop_server(srv)
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(probe.close)
        probe.bind(address)

    def test_it_says_when_the_port_is_still_held(self):
        """A teardown that cannot tell success from failure is the whole
        problem, so this one answers."""
        srv = self._server()
        real_close = srv.server_close
        # This test deliberately holds the port, so it has to hand it back
        # itself - a check for leaks that leaks is not a check.
        self.addCleanup(real_close)
        srv.shutdown = lambda: None
        srv.server_close = lambda: None      # releases nothing
        self.assertFalse(browsers.stop_server(srv),
                         "it reported success while still holding the port")


class NoSuiteHandsOverABareQuit(unittest.TestCase):
    """The sweep in `test_a_browser_is_really_stopped.py` looks for `.quit()`.
    Two suites passed `.quit` to `addClassCleanup` without calling it, which
    is the same defect wearing no parentheses."""

    def test_no_cleanup_is_registered_with_a_bare_quit(self):
        """Parsed rather than read line by line, for the same reason the
        `.quit()` sweep next door is: a fixture inside a string is not code,
        and a guard that cannot tell the difference fails on the examples
        written to prove it works."""
        import ast
        offenders = []
        for path in sorted((ROOT / "tests").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("addCleanup", "addClassCleanup")):
                    for arg in node.args:
                        if (isinstance(arg, ast.Attribute)
                                and arg.attr == "quit"):
                            offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual([], offenders,
                         "these register a quit that nothing checks: "
                         + ", ".join(offenders))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
