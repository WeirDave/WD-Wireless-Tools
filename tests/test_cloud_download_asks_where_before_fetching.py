"""A colleague's projects can be ticked, downloaded in bulk, and sent
somewhere he chose - with the full path on screen before anything is fetched.

He pulled several designs down from a colleague's account and found three
things at once. The Unassigned Projects group in the tree - where every
project a colleague shares sits, since only the owner can put a project in a
site - drew no checkbox, so nothing there could be ticked and Select all
passed over it. The row's Download saved into a new folder named after the
project and only then asked where it should have gone, once per file. And the
bulk route queued downloads with no question and no path anywhere on screen.

Run against the real cloud.js (`tests/cloud_vm.py`): the tree is rendered by
the shipping function, the dialog is the shipping dialog, and the only things
replaced are the server (`pyApi`, a recorder) and the modal (the probe picks a
folder the way a click on its select would). Every name here is invented.
"""
from __future__ import annotations

import unittest

from tests import cloud_vm

DATA = r"""
const ME = 'pat@example.invalid', THEM = 'colleague@example.invalid';
const DATA = {
  currentUser: ME, summary: {}, matched: [], cloudOnly: [], localOnly: [
    { path: '/invented/projects/Colleague Designs', name: 'Colleague Designs', isDir: true,
      children: { matched: [], cloudOnly: [], localOnly: [] } } ],
  orphans: { cloudOnly: [
    { id: 'p-1', name: 'Invented Annex', owner: THEM },
    { id: 'p-2', name: 'Invented Depot', owner: THEM },
    { id: 'p-3', name: 'My Own Unfiled', owner: ME } ] },
};
s.__set('currentTab', 'sites');
s.__set('_outputDir', '/invented/projects');
s.__set('data', DATA);
s.indexRowData();
// What the dialog's controls hold when he has chosen. `showConfirmModal` is
// the boundary: it runs once the dialog body is on screen.
function choose(dest, exists, newName) {
  s.showConfirmModal = async (title, body) => {
    s.confirms.push({ title, body });
    s.document.getElementById('dlDest').value = dest;
    s.document.getElementById('dlExists').value = exists || 'keepboth';
    if (newName !== undefined) s.document.getElementById('dlNew').value = newName;
    s._dlUpdate();
    s.previews.push(s.document.getElementById('dlPreview').innerHTML);
    return true;
  };
}
s.previews = [];
const downloads = () => s.calls.filter(c => c.m === 'download_project')
                              .map(c => ({ id: c.args[0], folder: c.args[1], exists: c.args[3] }));
s.pyApi = async (m, ...a) => { s.calls.push({ m, args: a });
  if (m === 'get_data') return DATA;
  return { ok: true }; };
"""


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class UnassignedProjectsCanBeTickedTests(unittest.TestCase):

    PROBE = DATA + r"""
const html = s.renderSitesTree(() => true, () => true, () => true, false, () => true);
const boxes = [...html.matchAll(/class="rowchk" data-k="([^"]+)"/g)].map(m => m[1]);
out({ boxes, row: s.__get('rowData')['op:p-1'] || null });
"""

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(cls.PROBE)

    def test_each_unassigned_project_draws_a_checkbox(self):
        for pid in ("p-1", "p-2", "p-3"):
            self.assertIn("op:" + pid, self.r["boxes"], self.r)

    def test_that_checkbox_names_a_row_the_actions_understand(self):
        row = self.r["row"]
        self.assertEqual("cloud", row["kind"], self.r)
        self.assertEqual("p-1", row["id"], self.r)
        self.assertEqual("projects", row["entityKind"], self.r)


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class BulkDownloadTests(unittest.TestCase):

    PROBE = DATA + r"""
const sel = s.__get('selected');
const res = {};

// A colleague's two and one of his own, into a folder that has no cloud site.
['op:p-1', 'op:p-2', 'op:p-3'].forEach(k => sel.add(k));
choose('Colleague Designs', 'keepboth');
await s.bulkDownload();
for (let i = 0; i < 5; i++) await settle();
res.picked = downloads();
res.shown = s.previews[s.previews.length - 1];
res.title = s.confirms[s.confirms.length - 1].title;
res.cleared = s.__get('selected').size;

// Cancelled: nothing is fetched.
s.calls.length = 0; s.confirms.length = 0;
sel.clear(); sel.add('op:p-1');
s.showConfirmModal = async () => false;
await s.bulkDownload();
for (let i = 0; i < 5; i++) await settle();
res.cancelled = downloads();

// A new folder, and skip-if-present: a file already there is not an error.
s.calls.length = 0;
sel.clear(); sel.add('op:p-2');
choose('__new__', 'refuse', 'Brand New Folder');
s.pyApi = async (m, ...a) => { s.calls.push({ m, args: a });
  if (m === 'get_data') return DATA;
  return { error: 'exists', code: 'exists' }; };
await s.bulkDownload();
for (let i = 0; i < 5; i++) await settle();
res.fresh = downloads();
res.toast = s.toasts.map(t => t[0] + ' ' + t[1]).join(' | ');

// A folder name nothing may be written to is not accepted.
s.calls.length = 0; s.confirms.length = 0;
sel.clear(); sel.add('op:p-1');
let btn = s.document.getElementById('confirmActionOkBtn');
s.showConfirmModal = async (t, b) => {
  s.document.getElementById('dlDest').value = '__new__';
  s.document.getElementById('dlNew').value = '..';
  s._dlUpdate();
  res.okDisabledForDots = btn.disabled;
  return true;
};
await s.bulkDownload();
for (let i = 0; i < 5; i++) await settle();
res.dots = downloads();
out(res);
"""

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(cls.PROBE)

    def test_a_colleagues_projects_download_with_the_rest(self):
        self.assertEqual(
            [("p-1", "Colleague Designs"), ("p-2", "Colleague Designs"),
             ("p-3", "Colleague Designs")],
            [(d["id"], d["folder"]) for d in self.r["picked"]], self.r)

    def test_the_full_path_is_on_screen_before_anything_is_fetched(self):
        self.assertIn("/invented/projects/Colleague Designs/Invented Annex.esx",
                      self.r["shown"], self.r)

    def test_the_choice_about_an_existing_file_is_passed_on(self):
        self.assertTrue(all(d["exists"] == "keepboth" for d in self.r["picked"]), self.r)

    def test_cancelling_fetches_nothing(self):
        self.assertEqual([], self.r["cancelled"], self.r)

    def test_a_new_folder_is_the_name_he_typed(self):
        self.assertEqual([("p-2", "Brand New Folder", "refuse")],
                         [(d["id"], d["folder"], d["exists"]) for d in self.r["fresh"]], self.r)

    def test_skipping_an_existing_file_is_reported_as_skipped_not_failed(self):
        self.assertIn("1 skipped", self.r["toast"], self.r)
        self.assertNotIn("failed", self.r["toast"], self.r)

    def test_a_name_that_cannot_be_a_folder_does_not_enable_the_button(self):
        self.assertTrue(self.r["okDisabledForDots"], self.r)


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class TheRowDownloadAsksWhereFirstTests(unittest.TestCase):

    PROBE = DATA + r"""
choose('Colleague Designs', 'keepboth');
s._setRowBusy = () => {};
let picker = 0;
s._openMoveToSitePicker = async () => { picker++; };
await s.downloadThenMove('p-1', 'Invented Annex');
for (let i = 0; i < 5; i++) await settle();
out({ downloads: downloads(), picker,
      asked: s.previews.join(' ') });
"""

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(cls.PROBE)

    def test_it_lands_where_he_chose_and_is_not_sorted_afterwards(self):
        self.assertEqual([("p-1", "Colleague Designs")],
                         [(d["id"], d["folder"]) for d in self.r["downloads"]], self.r)
        self.assertEqual(0, self.r["picker"], self.r)

    def test_the_path_was_shown(self):
        self.assertIn("/invented/projects/Colleague Designs/Invented Annex.esx",
                      self.r["asked"], self.r)


if __name__ == "__main__":
    unittest.main()
