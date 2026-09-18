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
import shutil
import tempfile
import threading
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from tools import applog


class _Isolated(unittest.TestCase):
    """Each test gets its own user directory and a clean logging state."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
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

    def _handler(self):
        applog.install()
        found = [h for h in logging.getLogger().handlers
                 if isinstance(h, applog.DailyCappedFileHandler)]
        self.assertTrue(found, "expected the daily capped handler")
        return found[0]

    def test_it_keeps_a_week_and_cannot_pass_its_ceiling(self):
        """He asked how large it can get. The answer has to be enforced."""
        self._handler()
        self.assertEqual(7, applog.RETAIN_DAYS)
        self.assertEqual(applog.MAX_TOTAL_BYTES + applog.MAX_FILE_BYTES,
                         applog.HARD_CEILING_BYTES)
        self.assertLessEqual(applog.HARD_CEILING_BYTES, 10_000_000)

    def test_it_appends_and_never_truncates_on_startup(self):
        """The one that cost a traceback.

        A handler opening in "w" destroys the evidence at exactly the moment
        someone restarts to see whether the fault recurs - which is the
        sequence that happened.
        """
        handler = self._handler()
        self.assertEqual("a", handler.mode)
        applog.note_failure("first run", OSError("before the restart"))
        logging.getLogger().removeHandler(handler)
        handler.close()

        applog._installed = False
        self._handler()          # a second "launch" of the app
        applog.note_failure("second run", OSError("after the restart"))

        body = self.text()
        self.assertIn("before the restart", body,
                      "restarting destroyed the previous run's log")
        self.assertIn("after the restart", body)

    def test_a_file_older_than_the_window_is_dropped(self):
        handler = self._handler()
        stale = applog.log_dir() / "wd-wireless-tools.2020-01-01.log"
        recent = (applog.log_dir() /
                  f"wd-wireless-tools.{date.today() - timedelta(days=2)}.log")
        for f in (stale, recent):
            f.write_text("x", encoding="utf-8")
        handler.prune()
        self.assertFalse(stale.exists(), "a file past the window was kept")
        self.assertTrue(recent.exists(), "a file inside the window was dropped")

    def test_going_over_the_ceiling_drops_the_oldest_first(self):
        handler = self._handler()
        made = []
        for days_ago in (6, 5, 4):
            f = (applog.log_dir() /
                 f"wd-wireless-tools.{date.today() - timedelta(days=days_ago)}.log")
            f.write_text("y" * 400_000, encoding="utf-8")
            made.append(f)
        handler._max_total_bytes = 600_000
        handler.prune()
        self.assertFalse(made[0].exists(), "the oldest should have gone first")
        self.assertTrue(made[-1].exists(), "the newest should have been kept")

    def test_a_new_day_moves_yesterday_aside_under_its_own_date(self):
        handler = self._handler()
        applog.note_failure("yesterday", OSError("older entry"))
        yesterday = str(date.today() - timedelta(days=1))
        handler._day = yesterday          # pretend the process ran overnight
        applog.note_failure("today", OSError("newer entry"))

        archived = applog.log_dir() / f"wd-wireless-tools.{yesterday}.log"
        self.assertTrue(archived.exists(), "yesterday was not filed by date")
        self.assertIn("older entry", archived.read_text(encoding="utf-8"))
        self.assertIn("newer entry", self.text())
        self.assertNotIn("older entry", self.text())

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

        with patch.object(applog, "console"):
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

    def test_the_panel_can_open_the_folder_without_naming_a_path(self):
        """The route takes no argument, so a page cannot aim it somewhere."""
        import server
        seen = []
        with patch.object(server.reveal_tool, "reveal",
                          side_effect=lambda t: seen.append(Path(t)) or {"ok": True}):
            res = self.client.post("/api/logs/reveal",
                                   headers={"X-WD-Wireless-Tools": "1"},
                                   json={"path": "C:/somewhere/else"})
        self.assertEqual(200, res.status_code)
        self.assertTrue(json.loads(res.data).get("ok"))
        self.assertEqual(1, len(seen))
        self.assertNotIn("somewhere", str(seen[0]),
                         "the client managed to choose the folder")
        self.assertIn("logs", str(seen[0]))

    def test_the_version_route_states_the_limits(self):
        body = json.loads(self.client.get("/api/version").data)
        self.assertEqual(7, body["logRetentionDays"])
        self.assertLessEqual(body["logMaxBytes"], 10_000_000)

    def test_the_about_panel_renders_it(self):
        js = (Path(__file__).resolve().parent.parent / "web" / "assets" / "js"
              / "wd-shared.js").read_text(encoding="utf-8")
        self.assertIn("wdAboutLogPath", js)
        self.assertIn("wdAboutLogOpen", js)
        self.assertIn("_renderLogPath", js)
        self.assertIn("/api/version", js)
        self.assertIn("/api/logs/reveal", js)


if __name__ == "__main__":
    unittest.main()
