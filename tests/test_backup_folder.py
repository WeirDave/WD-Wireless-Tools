"""The backups folder, as something that can be read and put back.

Six places in this suite copy a file aside before overwriting it. Until the
Backup Folder tab there was no way to reach any of them from inside the tool -
"I know we have no window to it right now" - and while nobody was looking, two
things about that folder had quietly stopped being true.

**Retention was inert.** Backups moved out of the project folder and into
`<project folder>/backups/<site>/`, which is what he asked for, and pruning
went on looking beside the live `.esx`, where there is now nothing at all. So
"keep 3" kept every generation ever taken, of every project a sync had
replaced, since the day that folder appeared. `test_retention_reaches_the_
folder_the_backups_are_filed_in` writes four generations with keep=2 and counts
what is left; it fails on the code it replaced.

**And the owner of a filed backup is not where it came from.** `classify`
reports the owner as the same filename *inside the backups folder* - a path
that has never existed - because that value groups generations for retention
rather than naming a live file. A restore that trusted it would write the
recovered project into the folder the sync deliberately does not read, and
report success. The file would be safe, invisible, and not where he went to
look for it.

Nothing here asserts that a source file contains a string. Every test runs the
function against real files on disk and reads the bytes back afterwards.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tools import backups
from tools import cloud_manager as cm


class BackupFolderTestCase(unittest.TestCase):
    """A project folder with one site in it, and a live project inside that."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wd-backup-folder-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.site = self.root / "NORTHWIND"
        self.site.mkdir()
        self.live = self.site / "Northwind Survey.esx"
        self.live.write_bytes(b"the original")

    def take(self, stamp, body=None):
        """One generation, written exactly the way Cloud Manager writes them."""
        if body is not None:
            self.live.write_bytes(body)
        dest = cm._backup_target(self.live, str(self.root), stamp)
        return Path(backups.copy_for_backup(self.live, dest))

    def filed(self):
        return sorted(p.name for p in (self.root / "backups").rglob("*.esx"))


class WhereABackupGoesAndComesBackFromTests(BackupFolderTestCase):

    def test_the_two_copies_of_the_backup_folder_name_agree(self):
        """One name, in two modules, and only one of them can be wrong.

        `cloud_manager` decides where a backup is filed and `backups` has to
        walk that mapping backwards to restore it. If the names drifted apart,
        every restore would silently fall back to the sibling shape and put
        the file in the backups folder.
        """
        self.assertEqual(backups.BACKUP_DIR_NAME, cm.BACKUP_DIR_NAME)

    def test_a_filed_backup_restores_to_the_live_project_not_to_the_folder(self):
        backup = self.take("20260101-090000")
        self.assertEqual(backup.parent, self.root / "backups" / "NORTHWIND")

        # What `classify` says the owner is - and why it must not be trusted
        # as a restore destination.
        owner = Path(backups.classify(backup)["owner"])
        self.assertFalse(owner.exists())

        target = backups.restore_target(backup, [str(self.root)])
        self.assertEqual(target, self.live)

    def test_a_sibling_backup_restores_to_the_file_beside_it(self):
        """The older shape, still on disk wherever no project folder was set."""
        sibling = self.site / "Northwind Survey.previous-20260101-090000.esx"
        shutil.copy2(self.live, sibling)
        self.assertEqual(backups.restore_target(sibling, [str(self.root)]), self.live)

    def test_something_that_is_not_a_backup_has_nowhere_to_go_back_to(self):
        self.assertIsNone(backups.restore_target(self.live, [str(self.root)]))


class RetentionReachesTheFolderTests(BackupFolderTestCase):

    def test_retention_reaches_the_folder_the_backups_are_filed_in(self):
        """Four generations, keep two, and two must actually go.

        This is the assertion the shipped code fails: `prune_for` looked only
        in `target.parent`, found nothing, and deleted nothing, for every
        backup Cloud Manager has written since the folder was introduced.
        """
        for stamp in ("20260101-000000", "20260102-000000",
                      "20260103-000000", "20260104-000000"):
            last = self.take(stamp)

        self.assertEqual(len(self.filed()), 4)
        res = backups.prune_for(self.live, keep=2, protect=str(last),
                                extra_dirs=(last.parent,))
        self.assertEqual(len(res["deleted"]), 2)
        self.assertEqual(self.filed(), [
            "Northwind Survey.previous-20260103-000000.esx",
            "Northwind Survey.previous-20260104-000000.esx",
        ])

    def test_the_oldest_go_first(self):
        for stamp in ("20260101-000000", "20260105-000000", "20260103-000000"):
            last = self.take(stamp)
        backups.prune_for(self.live, keep=1, extra_dirs=(last.parent,))
        self.assertEqual(self.filed(),
                         ["Northwind Survey.previous-20260105-000000.esx"])

    def test_a_backup_of_another_file_is_not_counted_against_this_one(self):
        """Five of one project must not hide the only copy of another."""
        other = self.site / "Northwind Design.esx"
        other.write_bytes(b"another project")
        other_backup = Path(backups.copy_for_backup(
            other, cm._backup_target(other, str(self.root), "20250101-000000")))

        for stamp in ("20260101-000000", "20260102-000000", "20260103-000000"):
            last = self.take(stamp)
        backups.prune_for(self.live, keep=1, extra_dirs=(last.parent,))

        self.assertTrue(other_backup.is_file())

    def test_the_sibling_folder_is_still_pruned_when_that_is_where_they_are(self):
        """No project folder set, so the copy lands beside the .esx."""
        for stamp in ("20260101-000000", "20260102-000000", "20260103-000000"):
            dest = cm._backup_target(self.live, "", stamp)
            backups.copy_for_backup(self.live, dest)
        self.assertEqual(len(list(self.site.glob("*.previous-*"))), 3)
        backups.prune_for(self.live, keep=1)
        self.assertEqual(len(list(self.site.glob("*.previous-*"))), 1)


class PuttingOneBackTests(BackupFolderTestCase):

    def test_restoring_puts_the_bytes_back_and_keeps_what_it_replaced(self):
        backup = self.take("20260101-090000")          # holds b"the original"
        self.live.write_bytes(b"what a sync wrote over it")

        res = backups.restore(str(backup), [str(self.root)], stamp="20260202-120000")

        self.assertTrue(res.get("ok"), res)
        self.assertEqual(res["restored"], str(self.live))
        self.assertEqual(self.live.read_bytes(), b"the original")
        self.assertTrue(res["replaced"])

        # The copy that was there is not gone - it is a backup now, so the
        # restore itself can be undone the same way.
        kept = Path(res["kept"])
        self.assertTrue(kept.is_file())
        self.assertEqual(kept.read_bytes(), b"what a sync wrote over it")
        self.assertEqual(kept.parent, backup.parent)

        # And the backup that was restored is still on disk. Putting a copy
        # back is not the same as spending it.
        self.assertTrue(backup.is_file())

    def test_the_restore_lands_where_the_caller_was_told_it_would(self):
        """The page quotes `restoreTo` in the confirm before anything is
        written. If the write went anywhere else, the dialog would be a lie
        of exactly the kind that has been paid for here before."""
        backup = self.take("20260101-090000")
        listed = backups.browse([str(self.root)])
        item = listed["groups"][0]["items"][0]

        res = backups.restore(item["path"], [str(self.root)])
        self.assertEqual(res["restored"], item["restoreTo"])

    def test_restoring_a_file_whose_original_is_gone_puts_it_back(self):
        backup = self.take("20260101-090000")
        self.live.unlink()

        res = backups.restore(str(backup), [str(self.root)])
        self.assertTrue(res.get("ok"), res)
        self.assertFalse(res["replaced"])
        self.assertIsNone(res["kept"])
        self.assertEqual(self.live.read_bytes(), b"the original")

    def test_restoring_recreates_a_site_folder_that_has_gone(self):
        backup = self.take("20260101-090000")
        shutil.rmtree(self.site)

        res = backups.restore(str(backup), [str(self.root)])
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(self.live.read_bytes(), b"the original")

    def test_a_path_outside_the_folders_we_look_after_is_refused(self):
        """The browser hands this path in. A page that can name any path on
        the disk is a page that can restore over any file on it."""
        outside = Path(tempfile.mkdtemp(prefix="wd-elsewhere-"))
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        stray = outside / "Something.previous-20260101-090000.esx"
        stray.write_bytes(b"not ours")
        victim = outside / "Something.esx"
        victim.write_bytes(b"untouched")

        res = backups.restore(str(stray), [str(self.root)])
        self.assertIn("error", res)
        self.assertEqual(victim.read_bytes(), b"untouched")

    def test_a_file_that_is_not_a_backup_is_refused(self):
        res = backups.restore(str(self.live), [str(self.root)])
        self.assertIn("error", res)

    def test_a_backup_that_has_gone_since_the_page_drew_it_is_refused(self):
        backup = self.take("20260101-090000")
        backup.unlink()
        res = backups.restore(str(backup), [str(self.root)])
        self.assertIn("error", res)


class DeletingTests(BackupFolderTestCase):

    def test_the_named_copies_go_and_the_original_does_not(self):
        first = self.take("20260101-090000")
        second = self.take("20260102-090000")

        res = backups.remove([str(first)], [str(self.root)])
        self.assertEqual(res["count"], 1)
        self.assertFalse(first.exists())
        self.assertTrue(second.is_file())
        self.assertTrue(self.live.is_file())

    def test_a_path_that_is_not_a_backup_is_skipped_rather_than_deleted(self):
        """The list the page holds can be minutes old, so the server decides
        again at delete time - the same rule the realign action follows."""
        res = backups.remove([str(self.live)], [str(self.root)])
        self.assertEqual(res["count"], 0)
        self.assertEqual(len(res["skipped"]), 1)
        self.assertTrue(self.live.is_file())

    def test_a_path_outside_the_folders_we_look_after_is_skipped(self):
        outside = Path(tempfile.mkdtemp(prefix="wd-elsewhere-"))
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        stray = outside / "Something.previous-20260101-090000.esx"
        stray.write_bytes(b"not ours")

        res = backups.remove([str(stray)], [str(self.root)])
        self.assertEqual(res["count"], 0)
        self.assertTrue(stray.is_file())

    def test_what_was_freed_is_what_the_files_weighed(self):
        first = self.take("20260101-090000", body=b"x" * 500)
        second = self.take("20260102-090000", body=b"y" * 300)
        res = backups.remove([str(first), str(second)], [str(self.root)])
        self.assertEqual(res["freed"], 800)


class BrowseTests(BackupFolderTestCase):

    def test_generations_of_one_file_arrive_as_one_group_newest_first(self):
        self.take("20260101-090000")
        self.take("20260103-090000")
        self.take("20260102-090000")

        listed = backups.browse([str(self.root)])
        self.assertEqual(len(listed["groups"]), 1)
        group = listed["groups"][0]
        self.assertEqual(group["name"], "Northwind Survey.esx")
        self.assertEqual(group["target"], str(self.live))
        self.assertTrue(group["exists"])
        self.assertEqual([i["stamp"] for i in group["items"]],
                         ["20260103-090000", "20260102-090000", "20260101-090000"])
        self.assertEqual(listed["count"], 3)

    def test_a_group_says_whether_the_file_it_belongs_to_is_still_there(self):
        self.take("20260101-090000")
        self.live.unlink()
        group = backups.browse([str(self.root)])["groups"][0]
        self.assertFalse(group["exists"])
        self.assertFalse(group["items"][0]["targetExists"])

    def test_two_projects_of_the_same_name_in_different_sites_stay_apart(self):
        """The backups folder mirrors the site folders for this reason."""
        other_site = self.root / "SOUTHWIND"
        other_site.mkdir()
        other = other_site / "Northwind Survey.esx"
        other.write_bytes(b"a different project that shares a name")
        backups.copy_for_backup(
            other, cm._backup_target(other, str(self.root), "20260101-090000"))
        self.take("20260101-090000")

        groups = backups.browse([str(self.root)])["groups"]
        self.assertEqual(len(groups), 2)
        self.assertEqual(sorted(g["target"] for g in groups),
                         sorted([str(self.live), str(other)]))

    def test_an_install_backup_is_listed_and_is_not_offered_a_restore(self):
        """Rolling an install back is the updater's job - it has to stop the
        server first - so this refuses rather than half-doing it."""
        install = self.root / "WD-Wireless-Tools.previous-v2.136.3-20260101-090000"
        (install / "web").mkdir(parents=True)
        (install / "web" / "cloud.html").write_bytes(b"x" * 40)

        listed = backups.browse([str(self.root)])
        kinds = {g["kind"] for g in listed["groups"]}
        self.assertIn("install", kinds)

        res = backups.restore(str(install), [str(self.root)])
        self.assertIn("error", res)
        self.assertTrue(install.is_dir())


class ThroughTheServerTests(BackupFolderTestCase):
    """The page only ever reaches this through `/api/backups/<action>`.

    A list that the server cannot produce, or a restore the dispatch table has
    no entry for, is a tab that renders perfectly and does nothing - which is
    the shape of defect this repository keeps paying for.
    """

    def setUp(self):
        super().setUp()
        os.environ.setdefault("WD_USER_DIR", tempfile.mkdtemp(prefix="wd-user-"))
        import server
        self.server = server
        self._roots = server._backup_roots
        server._backup_roots = lambda: [str(self.root)]
        self.addCleanup(setattr, server, "_backup_roots", self._roots)
        self.client = server.app.test_client()

    def post(self, action, payload=None):
        return self.client.post("/api/backups/" + action, json=payload or {},
                                headers={"X-WD-Wireless-Tools": "1"}).get_json()

    def test_the_tab_can_list_restore_and_delete_through_the_api(self):
        first = self.take("20260101-090000")
        self.take("20260102-090000", body=b"a later state")

        listed = self.post("list")
        self.assertTrue(listed.get("ok"), listed)
        self.assertEqual(listed["count"], 2)
        self.assertEqual(len(listed["groups"]), 1)
        self.assertTrue(listed["human"])

        restored = self.post("restore", {"path": str(first)})
        self.assertTrue(restored.get("ok"), restored)
        self.assertEqual(self.live.read_bytes(), b"the original")

        deleted = self.post("delete", {"paths": [str(first)]})
        self.assertTrue(deleted.get("ok"), deleted)
        self.assertEqual(deleted["count"], 1)
        self.assertFalse(first.exists())

    def test_the_api_refuses_a_path_outside_the_folders_it_looks_after(self):
        outside = Path(tempfile.mkdtemp(prefix="wd-elsewhere-"))
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        stray = outside / "Something.previous-20260101-090000.esx"
        stray.write_bytes(b"not ours")

        for action in ("restore", "reveal"):
            res = self.post(action, {"path": str(stray)})
            self.assertIn("error", res, action)
        self.assertTrue(stray.is_file())

    def test_the_retention_number_travels_with_the_list(self):
        """The first question anyone asks a list like this is why there are
        three of something and not thirty, so the answer is on the page."""
        self.take("20260101-090000")
        listed = self.post("list")
        self.assertIn("keep", listed)
        self.assertIsInstance(listed["keep"], int)


if __name__ == "__main__":
    unittest.main()
