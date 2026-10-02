"""A download lands in the folder the site is paired with, and an upload lands
in the site the file's folder is paired with.

* **Sync everything on Sites** treated `data.cloudOnly` as projects. On the
  Sites tab it is sites, so each site id went to `download_project`. And the
  fresh downloads returned their `{error}` instead of throwing it, so the run
  counted refusals as work done: "2 updated - local and cloud now match".
* **A matched site with a differently named folder** - paired by code, or
  linked by hand - had its cloud projects downloaded into a new folder named
  after the cloud site. The row's Download, bulk Sync and Sync everything all
  took the cloud site's name as the destination.
* **The row's Upload** passed only the path and the name, so a file sitting in
  a site's folder went up unassigned.

Driven through the real cloud.js (`tests/cloud_vm.py`); the row controls are
read back out of the rendered markup with `tests/delegated.py` and run. Every
name is invented.
"""
from __future__ import annotations

import unittest

from tests import cloud_vm
from tests.delegated import DELEGATED_JS

ME = "pat@example.invalid"

#: One matched site whose folder is named differently from the cloud site,
#: holding a cloud-only project and a local-only file.
SITES = r"""
const ME = 'pat@example.invalid';
const SITES = { currentUser: ME, summary: {}, cloudOnly: [], localOnly: [], orphans: { cloudOnly: [] },
  matched: [{ matchType: 'code', namesDiffer: true,
    cloud: { id: 'site-M', name: 'Invented Main Campus', owner: ME,
             children: { matched: [], localOnly: [],
                         cloudOnly: [{ id: 'proj-M1', name: 'Invented Building 2', owner: ME }] } },
    local: { path: 'C:/w/Invented Main Campus (old)', name: 'Invented Main Campus (old)', isDir: true,
             children: { matched: [], cloudOnly: [],
                         localOnly: [{ path: 'C:/w/Invented Main Campus (old)/Invented Annex.esx',
                                       name: 'Invented Annex', isDir: false }] } } }] };
"""

#: Pressing OK on the Sync everything dialog with every fresh row ticked.
PRESS_SYNC_EVERYTHING = r"""
async function syncEverythingTickingFresh() {
  const plan = s.syncEverythingPlan();
  s._syncPicked = (k) => (k === 'fresh' ? plan.fresh.map((_, i) => i) : []);
  s._syncPickUpdate = () => {};
  const okBtn = s.document.getElementById('confirmActionOkBtn');
  okBtn.addEventListener = (ev, f) => { okBtn._grab = f; };
  s.showConfirmModal = async () => { if (okBtn._grab) okBtn._grab(); return true; };
  await s.syncEverything();
  for (let i = 0; i < 5; i++) await settle();
  return plan;
}
"""


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class SyncEverythingOnSites(unittest.TestCase):

    PROBE = PRESS_SYNC_EVERYTHING + r"""
s.__set('currentTab', 'sites');
s.__set('data', { currentUser: 'pat@example.invalid', summary: {}, matched: [], localOnly: [],
  orphans: { cloudOnly: [] },
  cloudOnly: [{ id: 'site-H', name: 'Invented Hotel', owner: 'pat@example.invalid',
    children: { matched: [], localOnly: [],
                cloudOnly: [{ id: 'proj-H1', name: 'Invented Hotel Survey', owner: 'pat@example.invalid' }] } }] });
s.pyApi = async (m, ...a) => { s.calls.push({ m, args: a });
  return { error: "'Invented Hotel Survey.esx' already exists", code: 'exists' }; };
const plan = await syncEverythingTickingFresh();
out({ fresh: plan.fresh.map(f => f.id),
      downloads: s.calls.filter(c => c.m === 'download_project').map(c => c.args[0]),
      toasts: s.toasts.map(t => t[0] + ' ' + t[1]) });
"""

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(cls.PROBE)

    def test_a_site_is_not_downloaded_as_a_project(self):
        self.assertEqual(["proj-H1"], self.r["fresh"], self.r)
        self.assertEqual(["proj-H1"], self.r["downloads"], self.r)

    def test_a_refused_download_is_not_reported_as_done(self):
        joined = " | ".join(self.r["toasts"])
        self.assertNotIn("updated", joined, self.r)
        self.assertIn("failed", joined, self.r)


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class ADownloadLandsInThePairedFolder(unittest.TestCase):

    PROBE = SITES + PRESS_SYNC_EVERYTHING + r"""
const res = {};
s.__set('currentTab', 'sites'); s.__set('data', SITES); s.indexRowData();
s.pyApi = async (m, ...a) => { s.calls.push({ m, args: a }); return { ok: true, name: 'Invented Building 2', path: 'x' }; };
s.runWithProgress = async (o, f) => f('op-1');
s._setRowBusy = () => {};

// The row's own Download.
s.calls.length = 0; s.confirms.length = 0;
await s.downloadThenMove('proj-M1', 'Invented Building 2');
res.row = { dest: s.calls.filter(c => c.m === 'download_project').map(c => c.args[1]),
            asked: s.confirms.map(c => c.body).join(' ') };

// Bulk Sync, Cloud -> Local, with the project ticked.
s.calls.length = 0;
const sel = s.__get('selected'); sel.clear(); sel.add('ct:proj-M1');
await s.bulkSync('to-local');
for (let i = 0; i < 5; i++) await settle();
res.bulk = s.calls.filter(c => c.m === 'download_project').map(c => c.args[1]);

// Sync everything.
s.calls.length = 0;
await syncEverythingTickingFresh();
res.everything = s.calls.filter(c => c.m === 'download_project').map(c => c.args[1]);
out(res);
"""

    FOLDER = "Invented Main Campus (old)"

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(cls.PROBE)

    def test_the_row_download_lands_in_the_paired_folder(self):
        self.assertEqual([self.FOLDER], self.r["row"]["dest"], self.r)

    def test_the_row_download_asks_about_the_real_folder(self):
        self.assertIn('"%s"' % self.FOLDER, self.r["row"]["asked"], self.r)

    def test_bulk_sync_lands_in_the_paired_folder(self):
        self.assertEqual([self.FOLDER], self.r["bulk"], self.r)

    def test_sync_everything_lands_in_the_paired_folder(self):
        self.assertEqual([self.FOLDER], self.r["everything"], self.r)


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class TheRowUploadAssignsToTheSite(unittest.TestCase):
    """Both Upload controls on a local-only file inside a site's folder: the
    ghost button in the empty cloud cell and the one in the detail band."""

    PROBE = SITES + DELEGATED_JS + r"""
s.__set('currentTab', 'sites'); s.__set('data', SITES); s.indexRowData();
const site = SITES.matched[0];
const html = s.renderTreeChildren(
  { matched: [], cloudOnly: [], localOnly: site.local.children.localOnly },
  null, null, site.cloud.id, site.cloud.name, null);
const uploads = [];
s.runWithProgress = async (o, f) => f('op-1');
s.pyApi = async (m, ...a) => { if (m === 'upload_project') uploads.push(a.slice(0, 2)); return { ok: true }; };
const found = [];
let rest = html;
for (;;) {
  const hit = delegated(rest, 'uploadFromLocal');
  if (!hit) break;
  found.push(hit.args);
  await s.uploadFromLocal.apply(null, hit.args);
  rest = rest.slice(rest.indexOf(hit.tag) + hit.tag.length);
}
out({ found, uploads });
"""

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(cls.PROBE)

    def test_both_controls_are_rendered(self):
        self.assertEqual(2, len(self.r["found"]), self.r)

    def test_each_uploads_into_the_site(self):
        path = "C:/w/Invented Main Campus (old)/Invented Annex.esx"
        self.assertEqual([[path, "site-M"], [path, "site-M"]], self.r["uploads"], self.r)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
