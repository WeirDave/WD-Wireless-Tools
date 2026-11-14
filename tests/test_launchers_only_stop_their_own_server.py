"""The launchers stop a stale WD Wireless Tools - not whatever is on port 8675.

Both launchers ran `taskkill /F` (Windows) or `kill -9` (macOS) on **every**
listener on port 8675 before starting. That has two faults the README's own
advice runs into: a second window started with `PORT=8676` still killed the
first instance it was meant to leave running, and an unrelated program that
happened to hold 8675 was killed with it.

Each test runs the real launcher against stand-ins for the programs it calls and
reads back what it tried to stop. Nothing real is touched: on Windows the
`netstat` and `powershell` it calls are stand-ins first on PATH, and on
macOS/Linux `kill` is a function a BASH_ENV file defines, so a signal is logged
and never sent.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAT = ROOT / "Start WD Wireless Tools.bat"
COMMAND = ROOT / "Start WD Wireless Tools.command"

CSC = (Path(os.environ.get("SystemRoot", "C:/Windows")) / "Microsoft.NET"
       / "Framework64" / "v4.0.30319" / "csc.exe")

#: A stand-in for powershell.exe that records its arguments and does nothing. It
#: has to be a real executable: a batch file called without `call` never hands
#: control back to the launcher that ran it.
POWERSHELL_STUB = r"""
using System; using System.IO;
class P { static int Main(string[] a) {
  File.AppendAllText(Environment.GetEnvironmentVariable("FAKE_LOG"),
                     "powershell " + string.Join(" ", a) + "\r\n");
  return 0; } }
"""


@unittest.skipUnless(os.name == "nt" and CSC.is_file(),
                     "the batch launcher runs on Windows, and the stand-in "
                     "powershell.exe is built with the compiler Windows ships")
class TheBatchLauncherTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-bat-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.log = self.tmp / "calls.log"
        shutil.copy2(BAT, self.tmp / BAT.name)
        # The launcher cds into its own folder and runs `python -m tools.x` and
        # `python server.py` from there, so stand-ins for those live beside it.
        tools = self.tmp / "tools"
        tools.mkdir()
        (tools / "__init__.py").write_text("", encoding="utf-8")
        # Exit 1 means "stay in this window".
        (tools / "terminal_tab.py").write_text("import sys\nsys.exit(1)\n",
                                               encoding="utf-8")
        # Exit 0 means every dependency is current.
        (tools / "deps.py").write_text("import sys\nsys.exit(0)\n",
                                       encoding="utf-8")
        (self.tmp / "server.py").write_text(
            "import os, sys\n"
            "open(os.environ['FAKE_LOG'], 'a').write('python server.py\\n')\n"
            "sys.exit(int(os.environ['FAKE_SERVER_RC']))\n", encoding="utf-8")
        # Two listeners: this app's usual port and another one.
        (self.tmp / "netstat.bat").write_bytes((
            "@echo off\r\n"
            "echo   TCP    0.0.0.0:8675           0.0.0.0:0              LISTENING       111\r\n"
            "echo   TCP    0.0.0.0:9123           0.0.0.0:0              LISTENING       222\r\n"
        ).encode("ascii"))
        src = self.tmp / "stub.cs"
        src.write_text(POWERSHELL_STUB, encoding="utf-8")
        built = subprocess.run(
            [str(CSC), "/nologo", "/out:" + str(self.tmp / "powershell.exe"),
             str(src)], capture_output=True, text=True, timeout=120)
        self.assertEqual(0, built.returncode, built.stdout + built.stderr)

    def _run(self, port=None, server_rc=75):
        env = dict(os.environ)
        env.pop("PORT", None)
        if port:
            env["PORT"] = str(port)
        env.update(FAKE_LOG=str(self.log), FAKE_SERVER_RC=str(server_rc),
                   PATH=str(self.tmp) + os.pathsep + env.get("PATH", ""))
        r = subprocess.run(["cmd", "/c", str(self.tmp / BAT.name)], env=env,
                           cwd=str(self.tmp), stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=90)
        lines = (self.log.read_text(encoding="utf-8", errors="replace")
                 .splitlines() if self.log.exists() else [])
        return r, lines

    def test_it_stops_a_server_on_the_default_port_and_only_that_one(self):
        r, lines = self._run()
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        stops = [l for l in lines if l.startswith("powershell")]
        self.assertEqual(1, len(stops), lines)
        self.assertIn("ProcessId=111", stops[0])
        self.assertNotIn("ProcessId=222", stops[0])
        self.assertIn("server.py", stops[0],
                      "the stop must check what the process is running")

    def test_it_leaves_the_default_port_alone_when_told_to_use_another(self):
        r, lines = self._run(port=9123)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        stops = [l for l in lines if l.startswith("powershell")]
        self.assertEqual(1, len(stops), lines)
        self.assertIn("ProcessId=222", stops[0])
        self.assertNotIn("ProcessId=111", stops[0])

    def test_the_server_is_started_after_the_stop(self):
        r, lines = self._run()
        started = [i for i, l in enumerate(lines)
                   if l.strip() == "python server.py"]
        stopped = [i for i, l in enumerate(lines) if l.startswith("powershell")]
        self.assertTrue(started and stopped, lines)
        self.assertGreater(started[0], stopped[0])

    def test_a_restart_exit_closes_the_window_without_a_pause(self):
        # 75 is "restarted: a new tab is already running". A `pause` here would
        # time the subprocess out, because nothing is there to press a key.
        r, _ = self._run(server_rc=75)
        self.assertEqual(0, r.returncode)
        self.assertNotIn("closed normally", r.stdout)


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class TheCommandLauncherTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-cmd-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.log = self.tmp / "calls.log"
        script = self.tmp / "launcher.command"
        script.write_bytes(COMMAND.read_bytes().replace(b"\r\n", b"\n"))
        (self.tmp / "python3").write_text(
            '#!/bin/sh\necho "python3 $*" >> "$FAKE_LOG"\nexit 0\n',
            encoding="utf-8", newline="\n")
        (self.tmp / "lsof").write_text(
            '#!/bin/sh\necho "lsof $*" >> "$FAKE_LOG"\n'
            'echo 111\necho 222\n', encoding="utf-8", newline="\n")
        (self.tmp / "ps").write_text(
            '#!/bin/sh\n'
            'case "$2" in\n'
            '  111) echo "python3 server.py" ;;\n'
            '  *)   echo "some-other-program --listen" ;;\n'
            'esac\n', encoding="utf-8", newline="\n")
        for n in ("python3", "lsof", "ps"):
            (self.tmp / n).chmod(0o755)
        # `kill` is a builtin, which a PATH stand-in cannot replace. A function
        # from BASH_ENV can - and means a signal is logged, never sent.
        (self.tmp / "env.sh").write_text(
            'kill() { echo "kill $*" >> "$FAKE_LOG"; [ "$1" = "-0" ] && return 1; return 0; }\n'
            'sleep() { :; }\n', encoding="utf-8", newline="\n")
        self.script = script

    def _run(self, port=None):
        env = dict(os.environ)
        env.pop("PORT", None)
        if port:
            env["PORT"] = str(port)
        env.update(FAKE_LOG=str(self.log), BASH_ENV=str(self.tmp / "env.sh"),
                   PATH=str(self.tmp) + os.pathsep + env.get("PATH", ""))
        r = subprocess.run([shutil.which("bash"), str(self.script)], env=env,
                           cwd=str(self.tmp), stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
        lines = (self.log.read_text(encoding="utf-8").splitlines()
                 if self.log.exists() else [])
        return r, lines

    def test_it_signals_only_a_process_running_server_py(self):
        r, lines = self._run()
        kills = [l for l in lines if l.startswith("kill")]
        self.assertTrue(any(l == "kill 111" for l in kills), lines)
        self.assertFalse(any("222" in l for l in kills),
                         "an unrelated program on the port was signalled")

    def test_it_asks_about_the_port_the_app_will_use(self):
        _, lines = self._run(port=9123)
        asked = [l for l in lines if l.startswith("lsof")]
        self.assertTrue(asked and "tcp:9123" in asked[0], lines)

    def test_it_asks_about_8675_by_default(self):
        _, lines = self._run()
        asked = [l for l in lines if l.startswith("lsof")]
        self.assertTrue(asked and "tcp:8675" in asked[0], lines)

    def test_it_terminates_politely_before_it_forces(self):
        _, lines = self._run()
        kills = [l for l in lines if l.startswith("kill") and "111" in l]
        self.assertEqual("kill 111", kills[0],
                         "the first signal was not a plain TERM")

    def test_the_server_is_started_after_the_stop(self):
        _, lines = self._run()
        started = [i for i, l in enumerate(lines) if l == "python3 server.py"]
        stopped = [i for i, l in enumerate(lines) if l == "kill 111"]
        self.assertTrue(started and stopped, lines)
        self.assertGreater(started[0], stopped[0])


if __name__ == "__main__":
    unittest.main()
