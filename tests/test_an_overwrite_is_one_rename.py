"""Overwriting a finished project is one rename, never a copy over the top.

`shutil.move` onto a file that already exists falls back, on Windows, to
copying straight into it, and a failure part-way leaves a truncated `.esx`
where the last good one was. PlanTrim and Prep both overwrite the previous
"(trimmed)" / "(prepared)" file the user may have drawn in, so the rename is
the only thing standing between a failed write and that file.

The check is on behaviour: the final rename onto the destination is made to
fail, and the existing file has to come through byte for byte, with nothing
left beside it. Every project here is invented.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tools import esx_trimmer, prep_pipeline  # noqa: E402
from test_trim_writes_what_it_cut import FLOOR, Image, build  # noqa: E402

BOX = [100, 100, 500, 400]
PREVIOUS = b"the previous finished project, which must survive"


def _failing_final_rename(destination: Path):
    """os.replace that fails only for the destination, so staging still works."""
    real = os.replace

    def replace(src, dst, *a, **kw):
        if os.fspath(dst) == os.fspath(destination):
            raise OSError("simulated failure on the final rename")
        return real(src, dst, *a, **kw)
    return patch("os.replace", replace)


@unittest.skipIf(Image is None, "Pillow is required to trim a floor plan")
class AnOverwriteIsOneRenameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-overwrite-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = build(self.tmp / "in.esx", 1000, 800, {},
                         frame=(100, 100, 500, 400))
        self.out = self.tmp / "out.esx"
        self.out.write_bytes(PREVIOUS)

    def _leftovers(self):
        return sorted(p.name for p in self.tmp.iterdir()
                      if p.name not in ("in.esx", "out.esx"))

    def test_trim_replaces_an_existing_file_and_leaves_nothing_beside_it(self):
        report = esx_trimmer.trim(self.src, self.out, boxes={FLOOR: BOX})
        self.assertTrue(report.written)
        self.assertNotEqual(PREVIOUS, self.out.read_bytes())
        self.assertEqual([], self._leftovers())

    def test_trim_that_cannot_finish_the_rename_keeps_the_existing_file(self):
        with _failing_final_rename(self.out):
            with self.assertRaises(OSError):
                esx_trimmer.trim(self.src, self.out, boxes={FLOOR: BOX})
        self.assertEqual(PREVIOUS, self.out.read_bytes())
        self.assertEqual([], self._leftovers())

    def test_trim_that_fails_while_writing_leaves_no_partial_file(self):
        with patch("zipfile.ZipFile.writestr", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                esx_trimmer.trim(self.src, self.out, boxes={FLOOR: BOX})
        self.assertEqual(PREVIOUS, self.out.read_bytes())
        self.assertEqual([], self._leftovers())

    def test_prep_replaces_an_existing_file_and_leaves_nothing_beside_it(self):
        r = prep_pipeline.run(str(self.src), dest=str(self.out), steps=["trim"],
                              boxes={FLOOR: BOX})
        self.assertTrue(r["ok"] and r["written"], r)
        self.assertNotEqual(PREVIOUS, self.out.read_bytes())
        self.assertEqual([], self._leftovers())

    def test_prep_that_cannot_finish_the_rename_keeps_the_existing_file(self):
        with _failing_final_rename(self.out):
            with self.assertRaises(OSError):
                prep_pipeline.run(str(self.src), dest=str(self.out),
                                  steps=["trim"], boxes={FLOOR: BOX})
        self.assertEqual(PREVIOUS, self.out.read_bytes())
        self.assertEqual([], self._leftovers())


if __name__ == "__main__":
    unittest.main()
