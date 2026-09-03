"""Tests for tools.reveal.

The reveal itself launches a file browser, so these patch the launcher and
assert on the command that would run. The point of interest is Windows:
Explorer parses ``/select,<path>`` as a single token, and passing "/select,"
and the path as separate argv entries silently drops the path and opens the
default folder instead - which is how this was written before.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools import reveal as reveal_tool


class RevealTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.file = self.dir / "project.esx"
        self.file.write_bytes(b"PK\x03\x04")

    def test_missing_path_reports_without_launching_anything(self):
        with patch.object(subprocess, "Popen") as popen:
            result = reveal_tool.reveal(self.dir / "nope.esx")
        self.assertIn("error", result)
        popen.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "Windows argv shape")
    def test_windows_selects_the_file_with_one_token(self):
        with patch.object(subprocess, "Popen") as popen, \
                patch("os.startfile", create=True):
            result = reveal_tool.reveal(self.file)
        self.assertEqual(result, {"ok": True})
        argv = popen.call_args[0][0]
        # exe + exactly one argument, and the path must be joined onto the flag
        self.assertEqual(len(argv), 2, argv)
        self.assertTrue(argv[1].startswith("/select,"), argv)
        self.assertIn(str(self.file.resolve()), argv[1])

    @unittest.skipUnless(sys.platform == "win32", "Windows folder handling")
    def test_windows_opens_a_folder_directly(self):
        with patch.object(subprocess, "Popen") as popen, \
                patch("os.startfile", create=True) as startfile:
            result = reveal_tool.reveal(self.dir)
        self.assertEqual(result, {"ok": True})
        startfile.assert_called_once()
        popen.assert_not_called()

    @unittest.skipUnless(sys.platform == "darwin", "macOS argv shape")
    def test_macos_reveals_a_file_with_dash_r(self):
        with patch.object(subprocess, "Popen") as popen:
            reveal_tool.reveal(self.file)
        self.assertEqual(popen.call_args[0][0][:2], ["open", "-R"])

    def test_a_failure_is_reported_rather_than_raised(self):
        with patch.object(subprocess, "Popen", side_effect=OSError("boom")), \
                patch("os.startfile", create=True, side_effect=OSError("boom")):
            result = reveal_tool.reveal(self.file)
        self.assertIn("error", result)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
