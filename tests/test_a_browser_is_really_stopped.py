"""Tearing a browser down has to survive the driver having stopped answering.

Every browser suite here ends the same way:

    with contextlib.suppress(Exception):
        driver.quit()

which reads as unconditional cleanup and is not. When the driver has gone
unresponsive - which is what happens under memory pressure, precisely when a
leak is doing the most damage - `quit()` raises, the `suppress` swallows it,
and the browser process outlives the run.

**Measured on 2026-09-21.** Three headless Firefox processes were left behind
by a suite whose teardown looks correct, with 2 GB of 32 GB free, and the next
browser run died with `ConnectionResetError` before reaching its first
assertion. Same shape as the 307 processes and 22.5 GB already recorded in
CLAUDE.md, arriving through a door that had been closed once already.

`browsers.shut_down` reads the browser's own pid *before* quitting and kills it
afterwards if it is still there. These tests use a real child process of their
own rather than a browser, so the claim - "a failing quit() still leaves
nothing behind" - is executed rather than described, and they run anywhere.
"""
from __future__ import annotations

import subprocess
import sys
import time
import unittest

from tests import browsers


def _sleeper():
    """A real process to stand in for a browser, and a real pid to kill."""
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class FakeDriver:
    """Only what `shut_down` reads: capabilities, a service, and quit()."""

    def __init__(self, browser_pid=0, service_pid=0, quit_raises=False):
        self.capabilities = {"moz:processID": browser_pid} if browser_pid else {}
        self.service = type("S", (), {"process": type("P", (), {"pid": service_pid})()})()
        self._raises = quit_raises
        self.quit_called = False

    def quit(self):
        self.quit_called = True
        if self._raises:
            raise RuntimeError("the driver stopped answering")


def _gone(pid, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if not browsers._pid_alive(pid):
            return True
        time.sleep(0.15)
    return False


class AFailingQuitStillLeavesNothingBehind(unittest.TestCase):

    def test_the_browser_is_killed_when_quit_raises(self):
        """The defect. This is what the old teardown could not do."""
        proc = _sleeper()
        self.addCleanup(proc.kill)
        self.assertTrue(browsers._pid_alive(proc.pid), "the stand-in never started")

        driver = FakeDriver(browser_pid=proc.pid, quit_raises=True)
        killed = browsers.shut_down(driver)

        self.assertTrue(driver.quit_called, "quit() was not even attempted")
        self.assertIn(proc.pid, killed, "it did not report killing anything")
        self.assertTrue(_gone(proc.pid),
                        "the browser outlived a teardown that reported success")

    def test_a_raising_quit_does_not_raise_out(self):
        """Teardown must not turn one failure into two."""
        driver = FakeDriver(quit_raises=True)
        self.assertEqual([], browsers.shut_down(driver))

    def test_the_driver_process_is_killed_too(self):
        """Chromium reports no browser pid, so the driver is the parent that
        has to go - otherwise the browser it started has nothing to end it."""
        proc = _sleeper()
        self.addCleanup(proc.kill)
        driver = FakeDriver(service_pid=proc.pid, quit_raises=True)
        killed = browsers.shut_down(driver)
        self.assertIn(proc.pid, killed)
        self.assertTrue(_gone(proc.pid))

    def test_a_clean_quit_kills_nothing(self):
        """When quit() works, the process is already gone and there is nothing
        to do. Killing anyway would be a teardown that fights the driver."""
        proc = _sleeper()
        self.addCleanup(proc.kill)
        driver = FakeDriver(browser_pid=proc.pid)

        def stop():
            proc.kill()
            proc.wait(timeout=5)

        driver.quit = stop
        self.assertEqual([], browsers.shut_down(driver),
                         "it killed something a clean quit had already ended")

    def test_it_copes_with_a_driver_that_reports_no_pids_at_all(self):
        self.assertEqual([], browsers.shut_down(FakeDriver()))


class EveryBrowserSuiteUsesIt(unittest.TestCase):
    """One suite left calling `quit()` directly is one suite still leaking,
    and it would be the quietest possible regression - nothing fails, the
    machine just fills up."""

    def test_no_suite_quits_a_driver_by_hand(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent
        offenders = []
        for path in sorted(root.glob("*.py")):
            if path.name in ("browsers.py", Path(__file__).name):
                continue
            text = path.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if stripped.endswith(".quit()") and "shut_down" not in stripped:
                    offenders.append(f"{path.name}:{i}")
        self.assertEqual([], offenders,
                         "these stop a browser without making sure it stopped: "
                         + ", ".join(offenders))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
