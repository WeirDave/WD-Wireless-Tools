"""A broken browser cookie reader does not stop the server starting.

`import server` imports `browser_cookie3`, which on Windows imports win32com,
whose type-library cache is a file two processes starting together can catch
half-written. CI did exactly that - `EOFError: Ran out of input` raised from
`import server` in a test that only wanted the app. Such a failure is now
logged and the reader is tried again at sign-in.

Loading it only at sign-in, inside a request thread, was tried first and hung
CI's Windows / Python 3.10 job, so it is still loaded at start.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


class TheServerStartsWithABrokenReader(unittest.TestCase):
    def test_a_reader_that_fails_to_load_leaves_the_server_running(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "fake"
            fake.mkdir()
            (fake / "browser_cookie3.py").write_text(
                'raise EOFError("Ran out of input")\n', encoding="utf-8")
            env = dict(os.environ, WD_USER_DIR=str(Path(d) / "user"),
                       PYTHONPATH=os.pathsep.join([str(fake), str(ROOT)]))
            r = subprocess.run(
                [sys.executable, "-c",
                 "import server; from tools import cloud_manager as cm; "
                 "print(cm.browser_cookie3 is cm._NOT_LOADED)"],
                cwd=ROOT, env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=120)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        self.assertEqual(r.stdout.strip().splitlines()[-1], "True")


class ItLoadsWhenCookiesAreRead(unittest.TestCase):
    def setUp(self):
        from tools import cloud_manager as cm
        self.cm = cm
        self.saved = cm.browser_cookie3
        self.addCleanup(setattr, cm, "browser_cookie3", self.saved)

    def test_the_first_read_loads_it(self):
        fake = mock.Mock()
        fake.chrome.side_effect = Exception("no jar")
        fake.firefox.side_effect = Exception("no jar")
        fake.edge.side_effect = Exception("no jar")
        fake.opera.side_effect = Exception("no jar")
        self.cm.browser_cookie3 = self.cm._NOT_LOADED
        with mock.patch.dict(sys.modules, {"browser_cookie3": fake}):
            self.assertIsNone(self.cm.try_browser_cookies())
        self.assertIs(self.cm.browser_cookie3, fake)
        fake.chrome.assert_called_once()

    def test_a_broken_load_is_tried_again_next_time(self):
        self.cm.browser_cookie3 = self.cm._NOT_LOADED
        real_import = __import__

        def broken(name, *a, **k):
            if name == "browser_cookie3":
                raise EOFError("Ran out of input")
            return real_import(name, *a, **k)

        with mock.patch("builtins.__import__", side_effect=broken):
            self.assertIsNone(self.cm._cookie_reader())
        self.assertIs(self.cm.browser_cookie3, self.cm._NOT_LOADED,
                      "a transient failure was remembered as 'not installed'")

    def test_not_installed_is_remembered(self):
        self.cm.browser_cookie3 = self.cm._NOT_LOADED
        real_import = __import__

        def missing(name, *a, **k):
            if name == "browser_cookie3":
                raise ImportError("no module")
            return real_import(name, *a, **k)

        with mock.patch("builtins.__import__", side_effect=missing):
            self.assertIsNone(self.cm._cookie_reader())
        self.assertIsNone(self.cm.browser_cookie3)


if __name__ == "__main__":
    unittest.main()
