"""Starting the server does not load the browser cookie reader.

`import server` imported `browser_cookie3`, which on Windows imports win32com,
whose type-library cache is a file two processes starting together can catch
half-written. CI did exactly that - `EOFError: Ran out of input` raised from
`import server` in a test that only wanted the app. The reader is loaded the
first time Cloud Manager reads browser cookies instead.
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


class TheServerStartsWithoutIt(unittest.TestCase):
    def test_importing_the_server_leaves_it_unloaded(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, WD_USER_DIR=d)
            r = subprocess.run(
                [sys.executable, "-c",
                 "import sys, server; print('browser_cookie3' in sys.modules)"],
                cwd=ROOT, env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=120)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        self.assertEqual(r.stdout.strip().splitlines()[-1], "False")


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
