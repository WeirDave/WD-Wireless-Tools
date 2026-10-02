"""A download from the Projects tab lands in the folder its site is paired with.

The Sites tab learned this first: a cloud site paired with a folder of another
name - by code, or linked by hand - had its projects downloaded into a new
folder named after the cloud site. The Projects tab kept doing it, because its
payload carried only the cloud site's name, and both its row Download and
Sync everything took that as the destination.

The server now resolves the pairing (`siteFolder` on each cloud project) with
the matcher the Sites tab uses, and the page lands downloads there. Driven
from the server's real payload through the real cloud.js. Every name here is
invented.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import cloud_vm
from tools import cloud_manager as cm

ME = "pat@example.invalid"


class _Api:
    user_email = ME

    def get_sites(self):
        return [{"siteId": "site-m", "name": "Invented Main Campus"}]

    def get_dataset_listing(self):
        return [{"id": "proj-1", "siteName": "Invented Main Campus", "siteId": "site-m",
                 "type": "SIMULATED_PROJECT",
                 "datasetUsers": [{"username": ME, "role": "OWNER"}]}]

    def get_projects(self):
        return [{"id": "proj-1", "name": "Invented Annex Survey",
                 "history": {"createdBy": ME, "modifiedAt": "2026-01-02T03:04:05Z"}}]


class _Case(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wd-proj-dl-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.folder = self.root / "Old Campus Folder"
        self.folder.mkdir()
        cm.save_manual_matches([])
        cm.save_not_matches([])
        self.addCleanup(cm.save_manual_matches, [])
        mgr = cm.CloudManager.__new__(cm.CloudManager)
        mgr.api, mgr.config = None, {}
        # He linked the site to its differently named folder by hand.
        mgr.mark_manual_match("site-m", str(self.folder))
        self.payload = cm.build_projects_data(_Api(), str(self.root))
        self.payload["currentUser"] = ME


class ThePayloadNamesTheFolderTests(_Case):

    def test_a_cloud_project_carries_its_sites_paired_folder(self):
        proj = self.payload["cloudOnly"][0]
        self.assertEqual("Invented Main Campus", proj["siteName"])
        self.assertEqual("Old Campus Folder", proj["siteFolder"])


DOWNLOAD = r"""
const P = JSON.parse(%s);
s.__set('currentTab', 'projects');
s.__set('data', P);
s.indexRowData();
s._setRowBusy = () => {};
s.runWithProgress = async (spec, fn) => fn('op-1');
const dl = [];
s.pyApi = async (m, ...args) => {
  if (m === 'download_project') { dl.push(args[1]); return { ok: true, name: 'x', path: 'x' }; }
  return { ok: true };
};
await s.downloadThenMove('proj-1', 'Invented Annex Survey');
const plan = s.syncEverythingPlan();
out({ rowDownload: dl, syncEverything: plan.fresh.map(f => f.siteName) });
"""


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class EveryDownloadPathUsesItTests(_Case):

    def _run(self):
        return cloud_vm.run(DOWNLOAD % json.dumps(json.dumps(self.payload)))

    def test_the_row_download_and_sync_everything_land_in_the_paired_folder(self):
        r = self._run()
        self.assertEqual(["Old Campus Folder"], r["rowDownload"], r)
        self.assertEqual(["Old Campus Folder"], r["syncEverything"], r)


if __name__ == "__main__":
    unittest.main()
