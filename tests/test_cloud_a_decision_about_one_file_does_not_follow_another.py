"""A decision he made, or a safety record, must not outlive the thing it was
about, and a delete must not be chosen by a heuristic that ignores identity.

Six independent holes found in a review of the code around matching, each
shaped the same way - something keyed on a name or a path went on applying
after the file or project behind it had changed:

* a manual link is made about a file; delete that file, download a *different*
  project into the same path, and the link paired the new file with the old
  project, as `manual`, which outranks Ekahau's id and is pushable unasked;
* manual links were not one-to-one: removing the newest silently resurrected
  an older link for the same project;
* the Duplicates tab matched without the project id, the links or the
  not-a-matches, so it could mark the proven project as the extra to delete;
* it also clustered by file name alone, so two projects of the same name in
  two sites' folders were offered as duplicates of each other;
* a merge's "keep newer" compared filesystem dates, which a sync client moves,
  and deleted the loser with no copy;
* the sync-point prune believed any listing, so an empty or partial answer
  erased the record the both-sides-changed guards read.

Every name, id and path here is invented and lives in a temporary directory.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import cloud_manager as cm  # noqa: E402
from tools import sync_state  # noqa: E402


def _esx(path: Path, project_id: str, modified: str = "2026-09-01T08:00:00.000Z",
         name: str | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps({"project": {
            "id": project_id, "name": name or path.stem,
            "title": name or path.stem,
            "history": {"modifiedAt": modified}}}))
    return path


class _Stores:
    """The decision stores, pointed at a directory of the test's own."""

    def _stores(self):
        d = Path(tempfile.mkdtemp(prefix="wd-decisions-"))
        self.addCleanup(shutil.rmtree, d, True)
        patches = {"CONFIG_DIR": d, "NOT_MATCH_FILE": d / "nm.json",
                   "MANUAL_MATCH_FILE": d / "mm.json"}
        for k, v in patches.items():
            real = getattr(cm, k)
            setattr(cm, k, v)
            self.addCleanup(setattr, cm, k, real)
        real_state = sync_state.STATE_FILE
        sync_state.STATE_FILE = d / "sync_state.json"
        self.addCleanup(setattr, sync_state, "STATE_FILE", real_state)
        cm._ESX_META_CACHE.clear()
        self.addCleanup(cm._ESX_META_CACHE.clear)
        return d


def _mgr(root):
    m = cm.CloudManager.__new__(cm.CloudManager)
    m.config = {"output_dir": str(root)}
    return m


class AManualLinkIsAboutTheFileItWasMadeOnTests(_Stores, unittest.TestCase):

    def setUp(self):
        self._stores()
        self.root = Path(tempfile.mkdtemp(prefix="wd-decisions-root-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _match(self, local_id):
        local = [{"path": str(self.file), "name": self.file.stem, "code": None,
                  "projectId": local_id}]
        cloud = [{"id": "cx", "name": "Alpha", "code": None},
                 {"id": "cz", "name": "Alpha", "code": None}]
        mm, _ = cm.manual_matches_map()
        return cm.build_matches(cloud, local, set(), mm)

    def test_a_different_project_downloaded_to_the_same_path_is_not_the_link(self):
        self.file = _esx(self.root / "Site" / "Alpha.esx", "local-1")
        _mgr(self.root).mark_manual_match("cx", str(self.file), "Alpha", "Alpha")
        # the file is deleted and another cloud project is downloaded there,
        # carrying its own id
        self.file.unlink()
        _esx(self.file, "cz")
        cm._ESX_META_CACHE.clear()

        out = self._match("cz")

        pair = {m["cloud"]["id"]: m for m in out["matched"]}
        self.assertEqual("id", pair["cz"]["matchType"], out["matched"])
        self.assertNotIn("cx", pair,
                         "the old link paired the new file with the old project")

    def test_the_link_still_holds_for_the_file_it_was_made_on(self):
        self.file = _esx(self.root / "Site" / "Alpha.esx", "local-1")
        _mgr(self.root).mark_manual_match("cx", str(self.file), "Alpha", "Alpha")
        out = self._match("local-1")
        pair = {m["cloud"]["id"]: m for m in out["matched"]}
        self.assertEqual("manual", pair["cx"]["matchType"])

    def test_a_link_made_before_ids_were_kept_still_applies(self):
        self.file = _esx(self.root / "Site" / "Alpha.esx", "local-1")
        cm.save_manual_matches([{"cloudId": "cx", "localPath": str(self.file),
                                 "cloudName": "Alpha", "localName": "Alpha"}])
        out = self._match("local-1")
        pair = {m["cloud"]["id"]: m for m in out["matched"]}
        self.assertEqual("manual", pair["cx"]["matchType"])


class ManualLinksAreOneToOneTests(_Stores, unittest.TestCase):

    def setUp(self):
        self._stores()
        self.root = Path(tempfile.mkdtemp(prefix="wd-decisions-root-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.old = _esx(self.root / "Old.esx", "o-1")
        self.new = _esx(self.root / "New.esx", "n-1")

    def test_linking_again_replaces_and_unlinking_does_not_resurrect(self):
        m = _mgr(self.root)
        m.mark_manual_match("cx", str(self.old))
        m.mark_manual_match("cx", str(self.new))
        by_cloud, pairs = cm.manual_matches_map()
        self.assertEqual(1, len(pairs), pairs)
        m.unmark_manual_match("cx", str(self.new))
        by_cloud, pairs = cm.manual_matches_map()
        self.assertNotIn("cx", by_cloud,
                         "removing the newest link brought the old one back")

    def test_two_projects_cannot_claim_one_file(self):
        m = _mgr(self.root)
        m.mark_manual_match("cx", str(self.old))
        m.mark_manual_match("cy", str(self.old))
        by_cloud, pairs = cm.manual_matches_map()
        self.assertEqual({"cy"}, set(by_cloud), by_cloud)


class TheDuplicatesTabAgreesWithTheProjectsTabTests(_Stores, unittest.TestCase):

    def setUp(self):
        self._stores()
        self.root = Path(tempfile.mkdtemp(prefix="wd-decisions-dups-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _api(self, projects):
        class Api:
            def get_dataset_listing(s):
                return []

            def get_projects(s):
                return projects
        return Api()

    def _clusters(self, projects):
        return cm.build_duplicates_data(self._api(projects), str(self.root))

    def test_the_project_the_file_carries_is_the_one_kept(self):
        """Two cloud projects named alike, the local file is `cy`'s. The order
        Ekahau lists them in must not decide which is the extra."""
        _esx(self.root / "Site" / "Alpha.esx", "cy")
        cx = {"id": "cx", "name": "Alpha"}
        cy = {"id": "cy", "name": "Alpha"}
        for order in ([cx, cy], [cy, cx]):
            cm._ESX_META_CACHE.clear()
            data = self._clusters(order)
            items = {i["id"]: i for c in data["clusters"]
                     for i in c["items"] if i["side"] == "cloud"}
            self.assertTrue(items["cy"]["matched"],
                            "the proven project was marked as the extra")
            self.assertFalse(items["cx"]["matched"])

    def test_his_manual_link_and_split_decisions_count_here_too(self):
        """A link he made is the pairing, on every tab."""
        f = _esx(self.root / "Site" / "Alpha.esx", "local-1")
        _mgr(self.root).mark_manual_match("cy", str(f), "Alpha", "Alpha")
        cm._ESX_META_CACHE.clear()
        data = self._clusters([{"id": "cx", "name": "Alpha"},
                               {"id": "cy", "name": "Alpha"}])
        items = {i["id"]: i for c in data["clusters"] for i in c["items"]
                 if i["side"] == "cloud"}
        self.assertTrue(items["cy"]["matched"])
        self.assertFalse(items["cx"]["matched"])

    def test_same_named_files_of_different_projects_are_not_duplicates(self):
        _esx(self.root / "Alpha Site" / "Baseline.esx", "p-1")
        _esx(self.root / "Beta Site" / "Baseline.esx", "p-2")
        data = self._clusters([])
        self.assertEqual([], data["clusters"],
                         "two projects were offered as duplicates of each other")

    def test_copies_of_one_project_still_cluster(self):
        _esx(self.root / "Alpha Site" / "Baseline.esx", "p-1")
        _esx(self.root / "Alpha Site" / "Baseline (copy).esx", "p-1",
             name="Baseline")
        _esx(self.root / "Beta Site" / "Baseline.esx", "p-1")
        data = self._clusters([])
        self.assertEqual(1, len(data["clusters"]), data["clusters"])
        self.assertGreaterEqual(len(data["clusters"][0]["items"]), 2)


class AMergeKeepsTheNewerSaveNotTheNewerTouchTests(_Stores, unittest.TestCase):

    def setUp(self):
        self._stores()
        self.root = Path(tempfile.mkdtemp(prefix="wd-decisions-merge-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.src = self.root / "From"
        self.dst = self.root / "To"
        self.src.mkdir()
        self.dst.mkdir()

    def _run(self, src_saved, dst_saved, src_touch, dst_touch):
        s = _esx(self.src / "A.esx", "p-1", src_saved)
        d = _esx(self.dst / "A.esx", "p-1", dst_saved)
        os.utime(s, (src_touch, src_touch))
        os.utime(d, (dst_touch, dst_touch))
        cm._ESX_META_CACHE.clear()
        res = _mgr(self.root).merge_execute(
            str(self.src), str(self.dst), [{"rel": "A.esx", "action": "newer"}])
        return s, d, res

    def test_a_re_synced_older_file_does_not_replace_newer_work(self):
        """The incoming file is older work with a later file date (a sync
        client touched it). The destination holds the newer save."""
        now = time.time()
        s, d, res = self._run("2026-08-01T08:00:00.000Z",
                              "2026-09-01T08:00:00.000Z",
                              src_touch=now, dst_touch=now - 86400 * 30)
        self.assertEqual(1, res["skipped"], res)
        self.assertEqual(0, res["overwritten"], res)
        self.assertTrue(s.exists(), "the incoming file was consumed")
        self.assertIn("2026-09-01", zipfile.ZipFile(d).read("project.json").decode())

    def test_a_genuinely_newer_incoming_file_still_wins(self):
        now = time.time()
        s, d, res = self._run("2026-09-05T08:00:00.000Z",
                              "2026-09-01T08:00:00.000Z",
                              src_touch=now - 86400 * 30, dst_touch=now)
        self.assertEqual(1, res["overwritten"], res)
        self.assertIn("2026-09-05", zipfile.ZipFile(d).read("project.json").decode())
        self.assertEqual([], [p for p in self.dst.iterdir() if p.name != "A.esx"],
                         "a merge left a temporary file behind")


class AWrongListingDoesNotEraseTheSafetyRecordTests(_Stores, unittest.TestCase):

    def setUp(self):
        self._stores()
        self.root = Path(tempfile.mkdtemp(prefix="wd-decisions-prune-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        _esx(self.root / "Site" / "Alpha.esx", "local-1")

    def _projects(self, listing):
        class Api:
            def get_projects(s):
                return listing

            def get_dataset_listing(s):
                return []

            def get_sites(s):
                return []
        return cm.build_projects_data(Api(), str(self.root))

    def test_an_empty_listing_prunes_nothing(self):
        """Old enough that only the empty-listing rule can save it - the
        grace period would otherwise hide a missing guard."""
        sync_state.record("c-1", str(self.root / "Site" / "Alpha.esx"), 100, 100)
        pairs = sync_state.load()
        pairs["c-1"]["syncedAt"] = int(time.time()) - 60 * 24 * 3600
        sync_state.save(pairs)
        self._projects([])
        self.assertIn("c-1", sync_state.load(),
                      "an empty answer erased the record the guards read")

    def test_a_recent_record_for_a_missing_project_is_kept(self):
        sync_state.record("c-1", "x/y.esx", 100, 100)
        self._projects([{"id": "c-other", "name": "Other"}])
        self.assertIn("c-1", sync_state.load())

    def test_an_old_record_for_a_project_that_is_gone_goes(self):
        sync_state.record("c-1", "x/y.esx", 100, 100)
        pairs = sync_state.load()
        pairs["c-1"]["syncedAt"] = int(time.time()) - 60 * 24 * 3600
        sync_state.save(pairs)
        self._projects([{"id": "c-other", "name": "Other"}])
        self.assertNotIn("c-1", sync_state.load())



class MatchingIsAFunctionOfTheDataTests(unittest.TestCase):
    """What pairs with what must not depend on the order Ekahau lists things
    in, on which of two copies a scan met first, or on how an accent was
    typed. Each of these paired the wrong file, or nothing, silently."""

    def _pairs(self, cloud, local):
        out = cm.build_matches(cloud, local, set(), {})
        return {m["cloud"]["id"]: m for m in out["matched"]}, out

    def test_same_named_projects_pair_with_their_own_sites_folder_either_order(self):
        local = [
            {"path": "/r/Site A/Survey.esx", "name": "Survey", "folder": "Site A",
             "projectId": "", "code": None},
            {"path": "/r/Site B/Survey.esx", "name": "Survey", "folder": "Site B",
             "projectId": "", "code": None},
        ]
        #: cx is deliberately the one in the *second* folder, so a pairing by
        #: id order or scan order alone gets it wrong.
        cx = {"id": "cx", "name": "Survey", "siteFolder": "Site B", "code": None}
        cy = {"id": "cy", "name": "Survey", "siteFolder": "Site A", "code": None}
        for order in ([cx, cy], [cy, cx]):
            pairs, _ = self._pairs([dict(c) for c in order],
                                   [dict(l) for l in local])
            self.assertEqual("/r/Site B/Survey.esx", pairs["cx"]["local"]["path"])
            self.assertEqual("/r/Site A/Survey.esx", pairs["cy"]["local"]["path"])

    def test_with_no_site_to_go_on_the_listing_order_still_does_not_decide(self):
        local = [
            {"path": "/r/Site A/Survey.esx", "name": "Survey", "folder": "Site A",
             "projectId": "", "code": None},
            {"path": "/r/Site B/Survey.esx", "name": "Survey", "folder": "Site B",
             "projectId": "", "code": None},
        ]
        cx = {"id": "cx", "name": "Survey", "code": None}
        cy = {"id": "cy", "name": "Survey", "code": None}
        seen = set()
        for order in ([cx, cy], [cy, cx]):
            pairs, _ = self._pairs([dict(c) for c in order],
                                   [dict(l) for l in local])
            seen.add((pairs["cx"]["local"]["path"], pairs["cy"]["local"]["path"]))
        self.assertEqual(1, len(seen),
                         "the pairing changed with the order Ekahau listed them")

    def test_of_two_copies_of_one_project_the_one_he_worked_on_is_the_pair(self):
        """Both carry the cloud project's id. The unedited copy is nearer the
        cloud's date; the edited one is the work, and it must be the visible
        side so a newer-local push is on offer."""
        cloud = [{"id": "cx", "name": "Alpha", "mtime": 1_000_000, "code": None}]
        local = [
            {"path": "/r/Site Old/Alpha.esx", "name": "Alpha", "projectId": "cx",
             "mtime": 1_000_000, "code": None},
            {"path": "/r/Site/Alpha.esx", "name": "Alpha", "projectId": "cx",
             "mtime": 1_000_000 + 36_000, "code": None},
        ]
        pairs, out = self._pairs(cloud, local)
        self.assertEqual("/r/Site/Alpha.esx", pairs["cx"]["local"]["path"])
        self.assertEqual("local_newer", pairs["cx"]["staleness"])
        self.assertEqual(["/r/Site Old/Alpha.esx"],
                         [l["path"] for l in out["localOnly"]])

    def test_an_accent_typed_two_ways_is_still_the_same_name(self):
        composed = "Café Survey"
        decomposed = "Café Survey"
        pairs, out = self._pairs(
            [{"id": "cx", "name": composed, "code": None}],
            [{"path": "/r/x/a.esx", "name": decomposed, "projectId": "",
              "code": None}])
        self.assertIn("cx", pairs, "the same name read as two different ones")
        self.assertEqual("exact", pairs["cx"]["matchType"])


_NODE_CONTENTS = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
const a = source.indexOf('function localFolderContentsText(');
const b = source.indexOf('\nfunction startDelete(', a);
if (a < 0 || b < 0) throw new Error('localFolderContentsText moved');
const folders = {
  '/r/Full': { src: { total: 6, esx: 3, srcCount: 3, tuckedCount: 2 } },
  '/r/Bare': { src: { total: 0, esx: 0 } },
  '/r/Plain': { src: { total: 1, esx: 1 } },
};
const localByPath = (p) => folders[p] || null;
const fn = new Function('localByPath',
  source.slice(a, b) + '\nreturn localFolderContentsText;')(localByPath);
console.log(JSON.stringify({
  full: fn('/r/Full'), bare: fn('/r/Bare'), plain: fn('/r/Plain'),
  unknown: fn('/r/Nowhere'),
}));
"""


class ADeleteDialogNamesTheProjectsAFolderHoldsTests(unittest.TestCase):
    """The dialog counted floor plans and images and never the .esx projects -
    the files that are most often the only copy - and the bulk dialog named
    a folder and nothing about what is in it."""

    @classmethod
    def setUpClass(cls):
        import subprocess
        if not shutil.which("node"):
            raise unittest.SkipTest("node is not installed")
        d = Path(tempfile.mkdtemp(prefix="wd-contents-node-"))
        try:
            script = d / "probe.js"
            script.write_text(_NODE_CONTENTS, encoding="utf-8")
            r = subprocess.run(
                ["node", str(script),
                 str(ROOT / "web" / "assets" / "js" / "cloud.js")],
                capture_output=True, encoding="utf-8", timeout=120)
        finally:
            shutil.rmtree(d, True)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_projects_are_counted(self):
        self.assertIn("3 .esx projects", self.out["full"])
        self.assertIn("3 other files", self.out["full"])
        self.assertIn("2 in archive/output/backup subfolders", self.out["full"])

    def test_a_single_project_is_singular(self):
        self.assertEqual("1 .esx project", self.out["plain"])

    def test_no_inventory_claims_nothing(self):
        """Unknown is not the same as empty."""
        self.assertEqual("", self.out["bare"])
        self.assertEqual("", self.out["unknown"])


if __name__ == "__main__":
    unittest.main()
