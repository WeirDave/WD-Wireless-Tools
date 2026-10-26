"""A file or folder picker returns a path that cannot be written in cp1252.

The pickers run Tk in a child interpreter and read the chosen path off its
stdout. Both ends used the locale encoding - cp1252 on Windows - so choosing a
folder with a Polish, Czech or CJK name made the child die with
`UnicodeEncodeError`, and the page reported that the picker "closed
immediately".

The child here is made to start with a cp1252 console (`PYTHONIOENCODING`) so
the fault shows on any platform, not only on a Windows machine whose code page
happens to be one. The path is invented.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from tools import cloud_manager, folder_organizer

#: Not representable in cp1252: Polish, Czech and Japanese letters.
NAME = "Zażółć gęślą jaźń \u30d5\u30a9\u30eb\u30c0"
PRINT_IT = "print(%r)" % NAME


class TheDialogChildSpeaksUtf8(unittest.TestCase):

    def setUp(self):
        patcher = patch.dict(os.environ, {"PYTHONIOENCODING": "cp1252",
                                          "PYTHONUTF8": "0"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_organizer_dialog_returns_the_name_intact(self):
        res = folder_organizer._tk_dialog_result(PRINT_IT, timeout=60)
        self.assertTrue(res["ran"], res)
        self.assertEqual(NAME, res["path"])

    def test_the_cloud_manager_folder_dialog_returns_the_name_intact(self):
        real_run = subprocess.run

        def run(cmd, *args, **kwargs):
            # Same call, same options; only the Tk script is swapped for one
            # that prints the name.
            self.assertEqual(sys.executable, cmd[0])
            return real_run([cmd[0], "-c", PRINT_IT], *args, **kwargs)

        with patch.object(cloud_manager.subprocess, "run", run):
            self.assertEqual(NAME, cloud_manager.pick_folder_dialog(""))

    def test_a_dialog_that_fails_still_says_why(self):
        res = folder_organizer._tk_dialog_result("raise SystemExit('no window')",
                                                 timeout=60)
        self.assertFalse(res["ran"])
        self.assertIn("closed immediately", res["why"])


if __name__ == "__main__":
    unittest.main()
