"""The log exists so that the next fault outlives the window it appears in.

Something went wrong in his terminal on a machine three hours away, printed a
wall of traceback, and was gone as soon as the window closed. Everything here
is about that: the detail goes to a file under the user data directory, the
terminal gets a sentence, and the path is on screen in About so that "send me
the log" is one action rather than a hunt through a hidden folder.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import applog


class _Isolated(unittest.TestCase):
    """Each test gets its own user directory and a clean logging state."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self._patch = patch.object(applog, "user_dir", lambda: self.home)
        self._patch.start()
        self.addCleanup(self._patch.stop)

        root = logging.getLogger()
        old_handlers = list(root.handlers)
        old_level = root.level
        old_installed = applog._installed
        old_hooks = (sys.excepthook, threading.excepthook)

        def restore():
            for handler in list(root.handlers):
                if handler not in old_handlers:
                    try:
                        handler.close()
                    except Exception:
                        pass
            root.handlers = old_handlers
            root.setLevel(old_level)
            applog._installed = old_installed
            sys.excepthook, threading.excepthook = old_hooks

        self.addCleanup(restore)
        applog._installed = False

    def text(self) -> str:
        p = applog.log_path()
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


class WhereTheLogLivesTests(_Isolated):

    def test_it_sits_under_the_user_data_directory(self):
        """Not a second home for state - the user directory already exists."""
        self.assertEqual(self.home, applog.log_path().parent.parent)
        self.assertEqual("logs", applog.log_dir().name)

    def test_it_is_not_inside_the_install_tree(self):
        root = Path(__file__).resolve().parent.parent
        self.assertNotIn(str(root), str(applog.log_path()))

    def test_it_rotates_so_it_cannot_grow_without_bound(self):
        applog.install()
        handlers = [h for h in logging.getLogger().handlers
                    if isinstance(h, logging.handlers.RotatingFileHandler)]
        self.assertTrue(handlers, "expected a rotating handler")
        handler = handlers[0]
        self.assertGreater(handler.maxBytes, 0)
        self.assertGreater(handler.backupCount, 0)
        ceiling = handler.maxBytes * (handler.backupCount + 1)
        self.assertLessEqual(ceiling, 8_000_000,
                             "the log has no sensible ceiling")

    def test_install_survives_a_directory_it_cannot_create(self):
        """A log that cannot be written is not a reason to refuse to start."""
        with patch.object(applog, "_file_handler",
                          side_effect=OSError("read-only")):
            self.assertIsNone(applog.install())


class WhatReachesTheFileTests(_Isolated):

    def test_an_unhandled_exception_is_recorded_with_its_traceback(self):
        applog.install()
        # The console line is asserted elsewhere; silence it here so the test
        # run's own output stays readable.
        with patch.object(applog, "console"):
            try:
                raise ValueError("the thing that went wrong")
            except ValueError:
                sys.excepthook(*sys.exc_info())
        body = self.text()
        self.assertIn("the thing that went wrong", body)
        self.assertIn("Traceback", body)

    def test_a_background_thread_is_recorded_too(self):
        """The one that gets missed.

        `sys.excepthook` never sees a thread. Its traceback goes to stderr
        through `threading.excepthook`, the process carries on serving, and
        the evidence scrolls away without anything having failed loudly
        enough to notice.
        """
        applog.install()

        def boom():
            raise RuntimeError("raised on a background thread")

        thread = threading.Thread(target=boom, name="probe")
        thread.start()
        thread.join(timeout=10)
        body = self.text()
        self.assertIn("raised on a background thread", body)
        self.assertIn("probe", body)
        self.assertIn("Traceback", body)

    def test_the_console_gets_one_line_that_points_at_the_file(self):
        """What he sees at the terminal: a sentence and a path, not a stack."""
        printed = []
        with patch("builtins.print", lambda *a, **kw: printed.append(" ".join(map(str, a)))):
            applog.console("update check failed: git could not be run")
        text = " ".join(printed)
        self.assertIn("update check failed", text)
        self.assertIn(str(applog.log_path()), text)
        self.assertNotIn("Traceback", text)

    def test_the_file_exists_before_anything_goes_wrong(self):
        """About points at this path, so it must not point at nothing.

        It also answers the first question anyone asks of a report: which
        version was running when it happened.
        """
        applog.install(app_version="9.9.9")
        self.assertTrue(applog.log_path().exists(),
                        "About would be pointing at a file that is not there")
        body = self.text()
        self.assertIn("started", body)
        self.assertIn("9.9.9", body)

    def test_a_carried_on_failure_reads_as_a_sentence(self):
        applog.install()
        applog.note_failure("update check", OSError("git could not be run"))
        body = self.text()
        self.assertIn("update check failed", body)
        self.assertIn("git could not be run", body)

    def test_every_line_carries_a_timestamp(self):
        applog.install()
        applog.note_failure("update check", OSError("nope"))
        first = [l for l in self.text().splitlines() if l.strip()][0]
        self.assertRegex(first, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


class TheLogStaysOnHisMachineTests(unittest.TestCase):
    """It records real paths and hostnames, which is rule zero's material."""

    def setUp(self):
        self.root = Path(__file__).resolve().parent.parent

    def test_logs_are_gitignored(self):
        body = (self.root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("logs/", body)
        self.assertIn("*.log", body)

    def test_no_log_file_is_tracked(self):
        out = subprocess.run(["git", "ls-files"], cwd=str(self.root),
                             capture_output=True, text=True)
        if out.returncode != 0:
            self.skipTest("git unavailable")
        tracked = [p for p in out.stdout.split() if p.endswith(".log")]
        self.assertEqual([], tracked)

    def test_the_log_is_not_in_the_release_payload(self):
        from tools import updater
        names = (list(updater.CONFIG.payload_files)
                 + list(updater.CONFIG.payload_dirs))
        self.assertNotIn("logs", names)


class TheTerminalStaysCalmTests(_Isolated):
    """A route failing writes a stack to the file and a sentence to screen."""

    def setUp(self):
        super().setUp()
        from server import app
        self.app = app
        self.client = app.test_client()

    def _break_a_real_route(self):
        """Make an ordinary route raise, without adding one.

        Flask refuses new routes once the app has served a request, and it has
        - other tests in this suite share the module. Reaching into what a
        real route calls is also the more honest simulation: this is how a
        route fails in production, somewhere down the stack rather than at the
        top of the view.
        """
        import server
        return patch.object(server, "_on_disk_suite_version",
                            side_effect=RuntimeError(
                                "deliberate failure for the test"))

    def test_a_failing_route_answers_json_and_not_an_html_error_page(self):
        applog.install()
        with self._break_a_real_route():
            res = self.client.get("/api/version")
        self.assertEqual(500, res.status_code)
        body = json.loads(res.data)          # an HTML error page would not parse
        self.assertFalse(body["ok"])
        self.assertNotIn("Traceback", body["error"])
        self.assertEqual(1, len(body["error"].splitlines()))
        self.assertIn("logPath", body)

    def test_the_traceback_goes_to_the_file(self):
        applog.install()
        with self._break_a_real_route():
            self.client.get("/api/version")
        body = self.text()
        self.assertIn("deliberate failure for the test", body)
        self.assertIn("Traceback", body)

    def test_a_404_is_still_an_ordinary_404(self):
        """The catch-all must not swallow normal HTTP errors."""
        res = self.client.get("/api/definitely-not-a-route")
        self.assertEqual(404, res.status_code)


class AboutCanFindTheLogTests(unittest.TestCase):

    def setUp(self):
        from server import app
        self.client = app.test_client()

    def test_the_version_route_carries_the_path(self):
        """`/api/version` is local-only, so it answers when the check cannot."""
        body = json.loads(self.client.get("/api/version").data)
        self.assertTrue(body.get("logPath"))
        self.assertTrue(body["logPath"].endswith(".log"))

    def test_the_about_panel_renders_it(self):
        js = (Path(__file__).resolve().parent.parent / "web" / "assets" / "js"
              / "wd-shared.js").read_text(encoding="utf-8")
        self.assertIn("wdAboutLogPath", js)
        self.assertIn("_renderLogPath", js)
        self.assertIn("/api/version", js)


if __name__ == "__main__":
    unittest.main()
