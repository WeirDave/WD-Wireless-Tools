"""A second launch attaches to a healthy server and never stops one that is working.

`tools/relaunch.py` is the launchers' first question. It asks the server on the
port, and the server answers for itself through `/api/version`: whether it is
busy, whether it is about to restart, whether the code on disk has moved on.

These tests run the real Flask app on a real socket and ask it with the real
probe, because the two ways this goes wrong are both about the join between
them: a server that reports itself idle while a request is open (and so is
killed mid-write), and a restart that the new launcher takes for a healthy
server (and so attaches to a process that is about to exit).
"""
from __future__ import annotations

import os
import tempfile
import threading
import unittest
from unittest import mock

_TMP = tempfile.TemporaryDirectory(prefix="wd-relaunch-")
os.environ.setdefault("WD_USER_DIR", _TMP.name)

import server  # noqa: E402
from tools import relaunch  # noqa: E402

_GATE = threading.Event()
_ENTERED = threading.Event()


# Registered before any request is served, which Flask insists on.
@server.app.route("/api/_test_slow_work", methods=["GET"])
def _slow_work():
    _ENTERED.set()
    _GATE.wait(10)
    return "done"


def _dead_port() -> int:
    """A port that was just served and is not any more, so nothing answers on it.
    Bound at port 0 and read back - a probed port can be taken by someone else."""
    from werkzeug.serving import make_server
    httpd = make_server("127.0.0.1", 0, server.app)
    port = httpd.server_port
    httpd.server_close()
    return port


class _Live(unittest.TestCase):
    """The real app on a loopback port."""

    @classmethod
    def setUpClass(cls):
        from werkzeug.serving import make_server
        cls.httpd = make_server("127.0.0.1", 0, server.app, threaded=True)
        cls.port = cls.httpd.server_port
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.thread.join(5)

    def setUp(self):
        _GATE.clear()
        _ENTERED.clear()
        server._restarting = False

    def tearDown(self):
        _GATE.set()
        server._restarting = False


class TheServerReportsItself(_Live):

    def test_an_idle_server_is_not_busy(self):
        info = relaunch.probe(self.port)
        self.assertIs(False, info["busy"])
        self.assertIs(False, info["restarting"])

    def test_a_request_in_progress_makes_it_busy_and_finishing_clears_it(self):
        import urllib.request
        t = threading.Thread(target=lambda: urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/api/_test_slow_work", timeout=15).read())
        t.start()
        self.assertTrue(_ENTERED.wait(5), "the slow request never started")
        self.assertIs(True, relaunch.probe(self.port)["busy"],
                      "a server in the middle of a request said it was idle")
        _GATE.set()
        t.join(10)
        self.assertIs(False, relaunch.probe(self.port)["busy"],
                      "the count did not come back down when the request ended")

    def test_asking_the_server_is_not_itself_work(self):
        # The launcher's own question must never make the answer "busy".
        for _ in range(5):
            self.assertIs(False, relaunch.probe(self.port)["busy"])

    def test_a_refused_request_does_not_leave_the_count_up(self):
        # The API guard refuses this one before any route runs.
        import urllib.request
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/walls/audit", data=b"{}",
            method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass
        self.assertIs(False, relaunch.probe(self.port)["busy"])

    def test_a_reported_operation_makes_it_busy(self):
        with server._progress_lock:
            server._progress["op-1"] = {"stage": "upload"}
        try:
            self.assertIs(True, relaunch.probe(self.port)["busy"])
        finally:
            with server._progress_lock:
                server._progress.pop("op-1", None)
        self.assertIs(False, relaunch.probe(self.port)["busy"])

    def test_a_restart_marks_the_server_before_the_new_launcher_exists(self):
        launched = {}

        def spawn(*a, **k):
            # The new launcher asks this very process, so what it would hear
            # at the moment of launching is what matters.
            launched["heard"] = relaunch.probe(self.port)
            return True

        with mock.patch.object(server.terminal_tab, "restart_in_tab", spawn),                 mock.patch.object(server.subprocess, "Popen", spawn),                 mock.patch.object(server, "_close_old_launcher_window"),                 mock.patch.object(server.os, "_exit", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                server._restart_in_new_console()
        self.assertIn("heard", launched, "no launcher was started")
        self.assertIs(True, launched["heard"]["restarting"])


class TheLauncherDecides(unittest.TestCase):

    CURRENT = {"versions": {"suite": "1.0.0"}, "restartReady": False,
               "busy": False, "restarting": False}

    def test_a_current_idle_server_is_attached_to(self):
        self.assertEqual(relaunch.ATTACH, relaunch.decide(self.CURRENT)[0])

    def test_a_current_busy_server_is_attached_to_not_replaced(self):
        info = dict(self.CURRENT, busy=True)
        self.assertEqual(relaunch.ATTACH, relaunch.decide(info)[0],
                         "work in progress was put at risk by opening a tab")

    def test_nothing_on_the_port_is_replaced(self):
        self.assertEqual(relaunch.REPLACE, relaunch.decide(None)[0])

    def test_something_else_on_the_port_is_not_taken_for_this_app(self):
        self.assertEqual(relaunch.REPLACE, relaunch.decide({"hello": 1})[0])
        self.assertEqual(relaunch.REPLACE,
                         relaunch.decide({"versions": {}})[0])

    def test_a_restarting_server_is_never_attached_to(self):
        info = dict(self.CURRENT, restarting=True)
        self.assertEqual(relaunch.REPLACE, relaunch.decide(info)[0])

    def test_old_code_that_is_idle_is_replaced(self):
        info = dict(self.CURRENT, restartReady=True)
        self.assertEqual(relaunch.REPLACE, relaunch.decide(info)[0])

    def test_old_code_in_the_middle_of_work_is_left_alone_and_says_why(self):
        info = dict(self.CURRENT, restartReady=True, busy=True)
        code, why = relaunch.decide(info)
        self.assertEqual(relaunch.WAIT, code)
        self.assertIn("WD_FORCE_RESTART", why)

    def test_force_replaces_even_a_busy_old_server(self):
        info = dict(self.CURRENT, restartReady=True, busy=True)
        self.assertEqual(relaunch.REPLACE, relaunch.decide(info, force=True)[0])


class TheAppIsRecognisedByWhatItSays(unittest.TestCase):

    def test_is_this_app_wants_a_suite_version(self):
        self.assertTrue(relaunch.is_this_app({"versions": {"suite": "1.2.3"}}))
        for other in (None, {}, {"versions": {}}, {"versions": {"suite": ""}},
                      {"versions": "x"}, "text"):
            self.assertFalse(relaunch.is_this_app(other), other)


class TheEntryPoint(_Live):

    def _main(self, port, **env):
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(relaunch.webbrowser, "open") as opened:
            code = relaunch.main([str(port)])
        return code, opened

    def test_it_opens_a_tab_on_a_healthy_server_and_reports_attached(self):
        code, opened = self._main(self.port)
        self.assertEqual(relaunch.ATTACH, code)
        opened.assert_called_once_with(f"http://localhost:{self.port}/")

    def test_it_opens_nothing_when_it_is_going_to_replace(self):
        server._restarting = True
        code, opened = self._main(self.port)
        self.assertEqual(relaunch.REPLACE, code)
        opened.assert_not_called()

    def test_with_no_server_it_falls_through_to_the_old_path(self):
        code, opened = self._main(_dead_port())
        self.assertEqual(relaunch.REPLACE, code)
        opened.assert_not_called()

    def test_a_port_that_is_not_a_number_falls_through(self):
        self.assertEqual(relaunch.REPLACE, relaunch.main(["not-a-port"]))

    def test_a_stale_busy_server_stops_the_launcher_and_force_overrides(self):
        stale = {"on_disk": "9.9.9"}
        with mock.patch.object(server, "_on_disk_suite_version",
                               return_value=stale["on_disk"]), \
                mock.patch.object(server, "_busy", return_value=True):
            code, opened = self._main(self.port)
            self.assertEqual(relaunch.WAIT, code)
            opened.assert_not_called()
            code, _ = self._main(self.port, WD_FORCE_RESTART="1")
            self.assertEqual(relaunch.REPLACE, code)


if __name__ == "__main__":
    unittest.main()
