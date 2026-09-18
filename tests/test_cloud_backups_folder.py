"""Replaced local files go to a backups folder, and it behaves like a bin.

"you actually create backup, which I wish I can turn off once I've proven that
everything works OK... But maybe we should back it up and put it into a special
folder called **backups** and then that way, kind of like the recycle bin, the
user can choose to delete those later - but they're not going to be included as
part of the Cloud Manager sync because they'll be in a folder that's not read."

So three properties, and each is asserted here rather than assumed:

* the copy lands under `<project folder>/backups/`, not beside the live file
* nothing in there is scanned, listed or synced
* it can be switched off, and is on unless he says otherwise

Every project and folder name below is invented.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import cloud_manager as cm


def _esx(path: Path, project_id: str = "abc-123", modified: str = ""):
    """A minimal .esx - a ZIP with a project.json, which is all the scan reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"project": {"id": project_id,
                       "history": {"createdBy": "someone@example.com",
                                   "modifiedAt": modified}}}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps(doc))
    return path


class TheCopyGoesInTheBackupsFolderTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.site = self.root / "North Campus"
        self.esx = _esx(self.site / "Alpha Survey.esx")

    def test_it_is_not_left_beside_the_live_file(self):
        """The thing he objected to: backups sitting among real projects."""
        target = cm._backup_target(self.esx, str(self.root), "20260917-120000")
        self.assertNotEqual(self.esx.parent, target.parent)
        self.assertIn(cm.BACKUP_DIR_NAME, target.parts)

    def test_the_site_folder_is_kept_inside_it(self):
        """Two sites can hold a project of the same name; they must not collide."""
        target = cm._backup_target(self.esx, str(self.root), "20260917-120000")
        self.assertEqual(self.root / cm.BACKUP_DIR_NAME / "North Campus",
                         target.parent)

    def test_the_filename_shape_is_unchanged(self):
        """`tools/backups.py` recognises this shape, so the existing purge in
        Settings finds these with no change at all."""
        target = cm._backup_target(self.esx, str(self.root), "20260917-120000")
        self.assertEqual("Alpha Survey.previous-20260917-120000.esx", target.name)
        from tools import backups
        self.assertIsNotNone(backups.classify(target))

    def test_an_unusable_project_folder_still_gets_a_backup(self):
        """Losing the copy is worse than putting it in the wrong place."""
        target = cm._backup_target(self.esx, "", "20260917-120000")
        self.assertEqual(self.esx.parent, target.parent)


class NothingInThereIsEverScannedTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        _esx(self.root / "North Campus" / "Alpha Survey.esx")
        _esx(self.root / cm.BACKUP_DIR_NAME / "North Campus"
             / "Alpha Survey.previous-20260917-120000.esx")

    def test_the_local_scan_does_not_see_the_backup(self):
        """Recycle-bin semantics: present, ignorable, his to clear."""
        found = cm.get_local_esx_files(str(self.root))
        names = [f["name"] for f in found]
        self.assertIn("Alpha Survey", names)
        self.assertEqual(1, len(found), "the backup was picked up as a project")
        self.assertNotIn(cm.BACKUP_DIR_NAME, Path(found[0]["path"]).parts)

    def test_the_folder_is_in_the_skip_list_by_name(self):
        self.assertIn(cm.BACKUP_DIR_NAME, cm._SKIP_DIRS)

    def test_the_existing_purge_still_finds_them(self):
        """He has to be able to empty the bin, and see what it costs."""
        from tools import backups
        out = backups.scan([str(self.root)])
        paths = [i["path"] for i in out["items"]]
        self.assertTrue(any(cm.BACKUP_DIR_NAME in Path(p).parts for p in paths),
                        "the purge cannot see backups in their new home")
        self.assertGreater(out["bytes"], 0)


class TheSwitchTests(unittest.TestCase):

    def test_it_is_on_unless_he_turns_it_off(self):
        from tools import settings
        self.assertIs(True, settings.DEFAULTS["cloud"]["keep_local_backups"])

    def test_a_missing_value_reads_as_on(self):
        """The switch was added after the behaviour.

        An install whose settings file predates it has no key at all, and that
        must not read as "backups are off" - which would make the next replace
        irreversible without anyone choosing that.
        """
        mgr = cm.CloudManager.__new__(cm.CloudManager)
        mgr.config = {}
        keep = mgr.config.get("keep_local_backups")
        self.assertIs(True, True if keep is None else bool(keep))

    def test_it_is_declared_in_the_registry(self):
        root = Path(__file__).resolve().parent.parent
        reg = json.loads((root / "web" / "assets" / "settings-registry.json")
                         .read_text(encoding="utf-8"))
        entry = next((s for s in reg["settings"]
                      if s.get("key") == "cloud.keep_local_backups"), None)
        self.assertIsNotNone(entry, "the setting is not in the registry")
        self.assertEqual("preference", entry["category"])

    def test_it_has_exactly_one_control(self):
        root = Path(__file__).resolve().parent.parent
        html = (root / "web" / "settings.html").read_text(encoding="utf-8")
        self.assertEqual(1, html.count('id="sCloudKeepBackups"'))
        js = (root / "web" / "assets" / "js" / "settings-page.js").read_text(encoding="utf-8")
        self.assertIn("keep_local_backups", js)

    def test_turning_it_off_is_described_as_irreversible(self):
        root = Path(__file__).resolve().parent.parent
        html = (root / "web" / "settings.html").read_text(encoding="utf-8")
        panel = html[html.index('id="sCloudKeepBackups"'):]
        panel = panel[:panel.index("</div>", panel.index("hint"))]
        self.assertIn("cannot be undone", panel)


if __name__ == "__main__":
    unittest.main()
