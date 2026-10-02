"""A pairing decision follows the file when it moves or is renamed.

"Not a match" and the manual links are filed under the local path. Rename,
Flag for review (a rename to `!name`), Move to site and Merge all move the
file, and none of them told the stores - so a pair he had split came back
paired after Move to site, and a link he had made broke on the next rename.

Each test runs the operation and then reads the store and the matcher, which
is what "the operation writes it" means: a store that can hold the new path is
no use if nothing puts it there.

Every project, folder and address here is invented.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tools import cloud_manager as cm


class _Mgr(cm.CloudManager):
    def __init__(self, root):
        self.api = None
        self.config = {"output_dir": str(root)}

    def _ensure(self):
        return True


def _local(p):
    return {"path": str(p), "name": Path(p).stem, "code": "", "mtime": 1000,
            "projectId": ""}


class _Case(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wd-follow-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.mgr = _Mgr(self.root)
        for save in (cm.save_not_matches, cm.save_manual_matches,
                     cm.save_external_overrides):
            save([])
            self.addCleanup(save, [])
        (self.root / "Unsorted").mkdir()

    def _file(self, rel):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    @staticmethod
    def _paths(pairs):
        return [p["localPath"] for p in pairs]


class NotAMatchFollowsTests(_Case):
    CLOUD = [{"id": "cid-harbour", "name": "Harbour Survey", "code": "", "mtime": 1000}]

    def test_move_to_site_keeps_the_pair_split(self):
        f = self._file("Unsorted/Harbour Survey.esx")
        self.mgr.mark_not_match("cid-harbour", str(f), "Harbour Survey", "Harbour Survey")
        mv = self.mgr.move_local_to_site(str(f), "Harbour")
        self.assertTrue(mv.get("ok"), mv)
        self.assertEqual([mv["newPath"]], self._paths(cm.load_not_matches()))
        r = cm.build_matches(self.CLOUD, [_local(mv["newPath"])],
                             cm.not_matches_set(), cm.manual_matches_map()[0])
        self.assertEqual([], r["matched"], "the split pair was paired again")

    def test_renaming_the_folder_carries_every_file_in_it(self):
        f = self._file("Old Pier/Harbour Survey.esx")
        self.mgr.mark_not_match("cid-harbour", str(f))
        rn = self.mgr.rename_local(str(self.root / "Old Pier"), "New Pier")
        self.assertTrue(rn.get("ok"), rn)
        self.assertEqual([str(self.root / "New Pier" / "Harbour Survey.esx")],
                         self._paths(cm.load_not_matches()))


class ManualLinkFollowsTests(_Case):
    CLOUD = [{"id": "cid-pier", "name": "Pier Four Final", "code": "", "mtime": 1000}]

    def _matched(self, path):
        r = cm.build_matches(self.CLOUD, [_local(path)], cm.not_matches_set(),
                             cm.manual_matches_map()[0])
        return [m["matchType"] for m in r["matched"]]

    def test_flag_for_review_keeps_the_link(self):
        g = self._file("Unsorted/Old Draft.esx")
        self.mgr.mark_manual_match("cid-pier", str(g), "Pier Four Final", "Old Draft")
        self.assertEqual(["manual"], self._matched(g))
        rn = self.mgr.rename_local(str(g), "!Old Draft")
        self.assertTrue(rn.get("ok"), rn)
        self.assertEqual([rn["newPath"]], self._paths(cm.load_manual_matches()))
        self.assertEqual(["manual"], self._matched(rn["newPath"]))

    def test_a_merge_carries_the_link_to_where_the_file_lands(self):
        g = self._file("Unsorted/Old Draft.esx")
        (self.root / "Pier").mkdir()
        self.mgr.mark_manual_match("cid-pier", str(g))
        res = self.mgr.merge_execute(str(self.root / "Unsorted"), str(self.root / "Pier"),
                                     [{"rel": "Old Draft.esx", "action": "move"}])
        self.assertEqual(1, res.get("moved"), res)
        self.assertEqual([str(self.root / "Pier" / "Old Draft.esx")],
                         self._paths(cm.load_manual_matches()))

    def test_an_unrelated_file_is_not_touched(self):
        g = self._file("Unsorted/Old Draft.esx")
        h = self._file("Unsorted/Old Draft Two.esx")
        self.mgr.mark_manual_match("cid-pier", str(h))
        self.mgr.rename_local(str(g), "Renamed")
        self.assertEqual([str(h)], self._paths(cm.load_manual_matches()))


class LocalOnlyMarkFollowsTests(_Case):

    def test_an_external_mark_on_a_local_only_file_follows_a_rename(self):
        g = self._file("Unsorted/Guest Plan.esx")
        self.mgr.set_external_override([{"localPath": str(g), "label": "Guest Plan"}],
                                       "external")
        rn = self.mgr.rename_local(str(g), "Guest Plan v2")
        self.assertEqual("external",
                         cm.external_overrides_map().get(cm._ov_key("", rn["newPath"])))


class RepointPairingsTests(_Case):

    def test_two_decisions_landing_on_one_path_become_one(self):
        cm.save_not_matches([
            {"cloudId": "cid-a", "localPath": r"C:\w\Old\Quay.esx"},
            {"cloudId": "cid-a", "localPath": "C:/w/New/Quay.esx"},
        ])
        cm.repoint_pairings([(r"C:\w\Old", "C:/w/New")])
        self.assertEqual(["C:/w/New/Quay.esx"], self._paths(cm.load_not_matches()))

    def test_a_store_that_cannot_be_written_does_not_fail_the_move(self):
        cm.save_manual_matches([{"cloudId": "cid-a", "localPath": "/w/Old.esx"}])
        original = cm.save_manual_matches
        def refuse(_pairs):
            raise OSError("disk full")
        cm.save_manual_matches = refuse
        self.addCleanup(setattr, cm, "save_manual_matches", original)
        cm.repoint_pairings([("/w/Old.esx", "/w/New.esx")])   # must not raise



class AFileUnderARenamedFolderKeepsItsSeparatorsTests(unittest.TestCase):
    """A Windows CI run stored "...\\New Pier/Harbour Survey.esx": the part
    under the renamed folder was glued on with "/". Spelled with Windows
    separators here so every platform runs it."""

    def test_a_windows_path_stays_a_windows_path(self):
        got = cm._repoint_one(r"C:\P\Old Pier\Harbour Survey.esx",
                              [(r"C:\P\Old Pier", r"C:\P\New Pier")])
        self.assertEqual(got, r"C:\P\New Pier\Harbour Survey.esx")

    def test_a_posix_path_stays_a_posix_path(self):
        got = cm._repoint_one("/p/Old Pier/a/b.esx", [("/p/Old Pier", "/p/New Pier")])
        self.assertEqual(got, "/p/New Pier/a/b.esx")

if __name__ == "__main__":
    unittest.main()
