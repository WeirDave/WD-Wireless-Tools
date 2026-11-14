"""The launchers ask whether the packages are current, not whether they import.

`Start WD Wireless Tools.bat` and `.command` decided on this::

    python -c "import flask, waitress, requests, browser_cookie3,
               cryptography, keyring, PIL"

and ran pip only when it failed - and without `--upgrade`, so pip then kept an
old package that merely satisfied the name. The installers had been fixed for
exactly this (see `test_dependency_floors_are_checked.py`); the launchers, which
are what is double-clicked every day, were not. The `.command` also left PIL
out of the probe, so a machine without Pillow started and failed on the first
floor plan.

They now run `python -m tools.deps`: 0 is current, 1 is something missing, 2 is
everything installed with something older than a floor. This runs the real
dependency step out of each launcher against a stand-in interpreter that logs
its arguments and answers with a chosen exit code, and asserts what was
called and whether the launcher went on to start the app.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import deps

BAT = ROOT / "Start WD Wireless Tools.bat"
COMMAND = ROOT / "Start WD Wireless Tools.command"


def _block(path: Path, start: str, end: str) -> str:
    """The text from the line holding `start` to the line holding `end`.

    Raises when either marker has moved: a probe that quietly ran an empty
    block would pass every assertion of absence.
    """
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    a = text.find(start)
    b = text.find(end, a + 1)
    if a < 0 or b < 0:
        raise AssertionError(f"{path.name}: markers {start!r} / {end!r} moved")
    return text[a:b]


class DepsExitCodes(unittest.TestCase):
    """What the launchers branch on."""

    def _exit(self, missing, outdated):
        result = {"ok": not (missing or outdated),
                  "missing": [{"name": n, "need": "1"} for n in missing],
                  "outdated": [{"name": n, "need": "2", "have": "1"}
                               for n in outdated],
                  "current": [], "checked": 7}
        with mock.patch.object(deps, "check", return_value=result):
            return deps.main([])

    def test_current_is_zero(self):
        self.assertEqual(0, self._exit([], []))

    def test_missing_is_one(self):
        self.assertEqual(1, self._exit(["pillow"], []))

    def test_older_than_a_floor_is_two(self):
        self.assertEqual(2, self._exit([], ["pillow"]))

    def test_missing_wins_over_older(self):
        """A launcher may carry on with an old package, never a missing one."""
        self.assertEqual(1, self._exit(["flask"], ["pillow"]))


class _Harness(unittest.TestCase):
    """A stand-in interpreter on PATH, and a way to run a launcher's block."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-launcher-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.log = self.tmp / "calls.log"

    def _run(self, argv, deps_rc, pip_rc):
        env = dict(os.environ)
        env.update(FAKE_LOG=str(self.log), FAKE_DEPS=str(deps_rc),
                   FAKE_PIP=str(pip_rc),
                   PATH=str(self.tmp) + os.pathsep + env.get("PATH", ""))
        r = subprocess.run(argv, env=env, cwd=str(ROOT), stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
        # Not called `calls`: the source-string audit reads a name assigned
        # from read_text as a source file, and this is a log the stand-in
        # interpreter wrote, which is an execution.
        logged = (self.log.read_text(encoding="utf-8").splitlines()
                  if self.log.exists() else [])
        return r, logged, "REACHED" in r.stdout

    def _pip_calls(self, calls):
        return [c for c in calls if "pip" in c]

    def _assert_behaviour(self, run):
        """The same four outcomes for either launcher."""
        r, calls, reached = run(deps_rc=0, pip_rc=0)
        self.assertEqual([], self._pip_calls(calls),
                         "pip ran although everything was current")
        self.assertTrue(reached)

        for deps_rc in (1, 2):
            with self.subTest(deps=deps_rc, case="pip succeeds"):
                self.log.unlink(missing_ok=True)
                r, calls, reached = run(deps_rc=deps_rc, pip_rc=0)
                pips = self._pip_calls(calls)
                self.assertEqual(1, len(pips), calls)
                self.assertIn("--upgrade", pips[0])
                self.assertIn("requirements.txt", pips[0])
                self.assertTrue(reached)

        self.log.unlink(missing_ok=True)
        r, calls, reached = run(deps_rc=2, pip_rc=1)
        self.assertEqual(1, len(self._pip_calls(calls)))
        self.assertTrue(reached, "an old package still runs the app; a failed "
                        "update (offline) must not stop the launcher\n" + r.stdout)

        self.log.unlink(missing_ok=True)
        r, calls, reached = run(deps_rc=1, pip_rc=1)
        self.assertFalse(reached, "a missing package cannot start the app")
        self.assertEqual(1, r.returncode)


@unittest.skipUnless(os.name == "nt", "cmd.exe only exists on Windows")
class TheBatchFileDependencyStep(_Harness):

    def setUp(self):
        super().setUp()
        (self.tmp / "python.cmd").write_text(
            '@echo off\r\n'
            'echo %*>>"%FAKE_LOG%"\r\n'
            'echo %* | findstr /c:"tools.deps" >nul && exit /b %FAKE_DEPS%\r\n'
            'echo %* | findstr /c:"pip" >nul && exit /b %FAKE_PIP%\r\n'
            'exit /b 0\r\n', encoding="utf-8")
        block = _block(BAT, "python -m tools.deps", "REM Everything from here is one parenthesised block")
        # A .cmd only returns control to its caller when it is `call`ed; the
        # real launcher runs python.exe, which always does.
        block = re.sub(r"(?m)^(\s*)python ", r"\1call python ", block)
        script = self.tmp / "step.cmd"
        script.write_text("@echo off\r\n" + block.replace("\n", "\r\n")
                          + "\r\necho REACHED\r\n", encoding="utf-8")
        self.script = script

    def test_the_step_does_what_the_exit_code_says(self):
        self._assert_behaviour(lambda deps_rc, pip_rc: self._run(
            ["cmd.exe", "/c", str(self.script)], deps_rc, pip_rc))


@unittest.skipUnless(os.name == "nt", "cmd.exe only exists on Windows")
class TheTabSaysItCameUp(_Harness):
    """The window that opened the tab waits to hear from it.

    `tests/test_terminal_tab.py` holds the waiting; this holds the other half,
    that the launcher running inside the tab actually speaks.
    """

    def setUp(self):
        super().setUp()
        (self.tmp / "python.cmd").write_text(
            '@echo off\r\n'
            'echo %*>>"%FAKE_LOG%"\r\n'
            'exit /b 0\r\n', encoding="utf-8")
        # "\n:" so the end is the label itself, not the `goto :launcher_ready`
        # inside the block.
        block = _block(BAT, 'if /i "%~1"=="--in-tab"', "\n:launcher_ready")
        block = re.sub(r"(?m)^(\s*)python ", r"\1call python ", block)
        self.script = self.tmp / "tab.cmd"
        self.script.write_text(
            "@echo off\r\n" + block.replace("\n", "\r\n")
            + "\r\n:launcher_ready\r\necho REACHED\r\n", encoding="utf-8")

    def test_inside_the_tab_the_first_act_is_to_say_so(self):
        r, calls, reached = self._run(
            ["cmd.exe", "/c", str(self.script), "--in-tab"], 0, 0)
        self.assertTrue(reached, r.stdout)
        self.assertEqual(1, len([c for c in calls if "terminal_tab" in c]), calls)
        self.assertIn("--ack", calls[0])

    def test_the_window_that_opens_the_tab_does_not_say_it(self):
        r, calls, _ = self._run(["cmd.exe", "/c", str(self.script)], 0, 0)
        self.assertEqual([], [c for c in calls if "--ack" in c], calls)


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class TheCommandFileDependencyStep(_Harness):

    def setUp(self):
        super().setUp()
        fake = self.tmp / "python3"
        fake.write_text(
            '#!/bin/sh\n'
            'echo "$*" >> "$FAKE_LOG"\n'
            'case "$*" in\n'
            '  *tools.deps*) exit "$FAKE_DEPS" ;;\n'
            '  *pip*) exit "$FAKE_PIP" ;;\n'
            'esac\n'
            'exit 0\n', encoding="utf-8", newline="\n")
        fake.chmod(0o755)
        block = _block(COMMAND, "python3 -m tools.deps", "# One function, called last")
        script = self.tmp / "step.sh"
        script.write_text(block + "\necho REACHED\n", encoding="utf-8",
                          newline="\n")
        self.script = script

    def test_the_step_does_what_the_exit_code_says(self):
        bash = shutil.which("bash")
        self._assert_behaviour(lambda deps_rc, pip_rc: self._run(
            [bash, str(self.script)], deps_rc, pip_rc))


if __name__ == "__main__":
    unittest.main()
