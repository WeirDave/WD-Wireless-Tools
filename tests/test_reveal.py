"""Tests for tools.reveal.

The reveal itself launches a file browser, so these patch the launcher and
assert on the command that would run. The point of interest is Windows, where
the same path has now been got wrong twice in opposite directions:

* ``/select,`` and the path as **separate argv entries** - Explorer parses
  ``/select,<path>`` as one token, so the path was silently dropped and the
  default folder opened.
* the two joined into one **list element** - correct until the path contains a
  space, at which point ``list2cmdline`` wraps the whole token in quotes and
  Explorer will not read a switch that begins inside one. Same symptom, and it
  works on every path without a space, which is why it survived.

So the shape asserted here is the command line as a string, with the quotes
around the path and nothing else. This test pinned the second form and went
red when it was fixed - see ``test_reveal_highlights_the_file.py``, which
asserts the same contract without needing Windows to run.
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

    @unittest.skipUnless(sys.platform == "win32", "Windows command-line shape")
    def test_windows_selects_the_file_with_the_switch_outside_the_quotes(self):
        with patch.object(subprocess, "Popen") as popen, \
                patch("os.startfile", create=True):
            result = reveal_tool.reveal(self.file)
        self.assertEqual(result, {"ok": True})
        cmd = popen.call_args[0][0]

        # A string, so CreateProcess gets it verbatim. A list would be run
        # through list2cmdline, which is the bug this shape exists to avoid.
        self.assertIsInstance(cmd, str, cmd)
        # The switch leads and is not inside a quote - Explorer ignores one
        # that is, and opens its default folder instead.
        self.assertTrue(cmd.startswith('explorer /select,"'), cmd)
        # The path is quoted as a whole, so a space in it is not a separator.
        self.assertTrue(cmd.endswith('"'), cmd)
        self.assertIn(str(self.file.resolve()), cmd)
        # Exactly one pair of quotes: around the path, nowhere else.
        self.assertEqual(2, cmd.count('"'), cmd)

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
