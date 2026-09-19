""""Empty" has to mean empty, because what follows it is `rmtree`.

The merge dialog carries "Delete the source folder afterward if it ends up
empty", ticked by default, and when the server says the source is empty the
page deletes it with no dialog at all - `pyApi('delete_local', ...)`, which is
`shutil.rmtree` on a directory.

The question is what "empty" was measured with. `_walk_files` exists for
*scanning*, and it deliberately skips `output`, `outputs`, `archive`,
`archives` and `backups` so a folder of finished exports is not reported as
work to do. That is right for a scan and wrong for this: a folder holding
nothing but `Output/` and `Archive/` answered "empty", and was then deleted
whole.

Since v2.141.0 nothing in the suite copies a file aside first, so there is no
second copy of any of it anywhere. The exports and the archived surveys are
simply gone, and nothing on screen ever named them.

Deleting a folder that really is empty needs no ceremony - nothing is lost.
So the fix is the measurement, not another prompt.

Every project, site and address here is invented.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tools import cloud_manager as cm


class _Manager(cm.CloudManager):
    def __init__(self, out_dir):
        self.api = None
        self.config = {"output_dir": str(out_dir)}

    def _ensure(self):
        return True


class EmptyMeansEmpty(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.src = self.root / "SITE1 Riverside"
        self.dst = self.root / "SITE1 Riverside North"
        self.src.mkdir()
        self.dst.mkdir()
        self.mgr = _Manager(self.root)

    def _survey(self, folder: Path, name: str) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        f = folder / name
        f.write_bytes(b"PK\x05\x06" + b"\0" * 18)
        return f

    def _merge_everything(self):
        """Move the one .esx across, leaving whatever else is in the folder."""
        return self.mgr.merge_execute(
            str(self.src), str(self.dst),
            [{"rel": "SITE1 Riverside Baseline.esx", "action": "move"}])

    def test_a_folder_of_exports_is_not_reported_empty(self):
        """`Output/` is where the reports he sends out are kept."""
        self._survey(self.src, "SITE1 Riverside Baseline.esx")
        (self.src / "Output").mkdir()
        (self.src / "Output" / "SITE1 Riverside Report.pdf").write_bytes(b"%PDF-1.4")

        out = self._merge_everything()

        self.assertTrue(out.get("ok"), out)
        self.assertFalse(out.get("srcEmpty"),
                         "a folder holding exported reports was reported empty, "
                         "and the page deletes that with no dialog")

    def test_a_folder_of_archived_surveys_is_not_reported_empty(self):
        self._survey(self.src, "SITE1 Riverside Baseline.esx")
        self._survey(self.src / "Archive", "SITE1 Riverside 2025.esx")

        out = self._merge_everything()

        self.assertTrue(out.get("ok"), out)
        self.assertFalse(out.get("srcEmpty"),
                         "a folder holding archived surveys was reported empty")

    def test_a_folder_that_really_is_empty_still_says_so(self):
        """Refusing is only correct if it refuses the right thing - otherwise
        the tidy-up he asked for never happens."""
        self._survey(self.src, "SITE1 Riverside Baseline.esx")

        out = self._merge_everything()

        self.assertTrue(out.get("ok"), out)
        self.assertTrue(out.get("srcEmpty"),
                        "the source really was left empty and was not offered "
                        "for cleanup")

    def test_an_empty_subfolder_does_not_hold_the_cleanup_back(self):
        """A folder tree with no files in it has nothing to lose."""
        self._survey(self.src, "SITE1 Riverside Baseline.esx")
        (self.src / "Output").mkdir()

        out = self._merge_everything()

        self.assertTrue(out.get("srcEmpty"),
                        "an empty Output/ folder is not a reason to keep the "
                        "source folder around")


class TheDeleteWarningCountsWhatIsActuallyThere(unittest.TestCase):
    """The other half of the same skip list, on the other route to `rmtree`.

    When the merge does not auto-delete, the page opens the ordinary local
    delete confirm, which warns "This folder holds N source files ... Deleting
    removes the only copy." N comes from `folder_inventory`, which skips the
    same folders - so the sentence that exists to say what will be destroyed
    was blind to the archive it was about to destroy.

    Skipping is right for the peek and the badge: he does not want a year of
    archived surveys listed every time he looks at a site folder. So the
    inventory keeps its list and gains an honest total beside it.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.folder = self.root / "SITE1 Riverside"
        (self.folder / "Archive").mkdir(parents=True)
        (self.folder / "Output").mkdir(parents=True)

    def test_files_in_skipped_folders_are_counted_somewhere(self):
        (self.folder / "SITE1 Riverside Baseline.esx").write_bytes(b"PK\x05\x06" + b"\0" * 18)
        (self.folder / "Archive" / "SITE1 Riverside 2025.esx").write_bytes(b"PK\x05\x06" + b"\0" * 18)
        (self.folder / "Output" / "SITE1 Riverside Report.pdf").write_bytes(b"%PDF-1.4")

        inv = cm.folder_inventory(self.folder)

        self.assertEqual(1, inv["total"],
                         "the listed set should still skip archives")
        self.assertEqual(2, inv.get("tuckedCount"),
                         "the archived survey and the exported report were "
                         "invisible to the delete warning")
        self.assertTrue(inv.get("tuckedSizeH"))

    def test_a_folder_with_nothing_tucked_away_says_zero(self):
        (self.folder / "SITE1 Riverside Baseline.esx").write_bytes(b"PK\x05\x06" + b"\0" * 18)
        inv = cm.folder_inventory(self.folder)
        self.assertEqual(0, inv.get("tuckedCount"))


if __name__ == "__main__":
    unittest.main()
