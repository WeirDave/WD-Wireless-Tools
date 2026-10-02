""""Delete all N extras" deletes extras - never the last copy, never off-screen.

Three things were wrong with the Duplicates toolbar button, and the first is
data loss:

* it deleted every **unmatched** item in a cluster. In a cloud-only or
  local-only cluster nothing is matched, so that was every copy - the project
  was gone from both places it existed. The cluster's own "Keep newest"
  already knew better; the toolbar now keeps the same newest copy;
* it walked **every cluster in the account** while the list showed the ones
  the chip and the search left, so the dialog could name things he could not
  see on the page;
* with nothing left in the filtered list it kept the **old count**.

Driven through the real cloud.js (`tests/cloud_vm.py`); the server is a
recorder. Every name is invented.
"""
from __future__ import annotations

import unittest

from tests import cloud_vm

SETUP = r"""
s.__set('data', { currentUser: 'pat@example.invalid', matched: [], cloudOnly: [], localOnly: [] });
s.__set('dupData', { clusters: [
  { key: 'inventedfoxtrot', displayName: 'Invented Foxtrot', shape: 'cloud-only',
    sides: { cloud: 2, local: 0 },
    items: [ { side: 'cloud', id: 'uuid-f1', name: 'Invented Foxtrot', matched: false, mtime: 1700000000, size: 10 },
             { side: 'cloud', id: 'uuid-f2', name: 'Invented Foxtrot', matched: false, mtime: 1700000100, size: 12 } ],
    newestId: 'uuid-f2', largestId: 'uuid-f2' },
  { key: 'inventedgolf', displayName: 'Invented Golf', shape: 'local-only',
    sides: { cloud: 0, local: 2 },
    items: [ { side: 'local', path: 'C:/w/A/Invented Golf.esx', name: 'Invented Golf', matched: false, mtime: 1, size: 1 },
             { side: 'local', path: 'C:/w/B/Invented Golf.esx', name: 'Invented Golf', matched: false, mtime: 2, size: 1 } ],
    newestId: 'C:/w/B/Invented Golf.esx', largestId: 'C:/w/A/Invented Golf.esx' },
  { key: 'inventedhotel', displayName: 'Invented Hotel', shape: 'mixed',
    sides: { cloud: 2, local: 1 },
    items: [ { side: 'cloud', id: 'uuid-h1', name: 'Invented Hotel', matched: true, mtime: 5, size: 1 },
             { side: 'local', path: 'C:/w/H/Invented Hotel.esx', name: 'Invented Hotel', matched: true, mtime: 5, size: 1 },
             { side: 'cloud', id: 'uuid-h2', name: 'Invented Hotel', matched: false, mtime: 9, size: 1 } ],
    newestId: 'uuid-h2', largestId: 'uuid-h1' } ] });
async function press(filter, search) {
  s.calls.length = 0; s.confirms.length = 0;
  s.__set('activeFilter', filter);
  s.document.getElementById('searchBox').value = search;
  s.renderDuplicates();
  const btn = s.document.getElementById('dupDeleteAllToolbarBtn');
  const shown = { hidden: btn.hidden,
                  count: String(s.document.getElementById('dupDeleteAllToolbarCount').textContent) };
  s.dupDeleteAllExtras();
  for (let i = 0; i < 5; i++) await settle();
  return { shown, deleted: s.calls.map(c => c.m + ' ' + c.args[c.args.length - 1]),
           dialog: s.confirms.map(c => text(c.body)).join(' | ') };
}
"""


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class DeleteAllExtras(unittest.TestCase):

    def press(self, filter_, search):
        return cloud_vm.run(SETUP + "out(await press(%r, %r));" % (filter_, search))

    def test_an_unmatched_cluster_keeps_its_newest_copy(self):
        r = self.press("all", "")
        self.assertNotIn("delete_cloud uuid-f2", r["deleted"], r)
        self.assertNotIn("delete_local C:/w/B/Invented Golf.esx", r["deleted"], r)
        self.assertEqual(sorted(["delete_cloud uuid-f1",
                                 "delete_local C:/w/A/Invented Golf.esx",
                                 "delete_cloud uuid-h2"]), sorted(r["deleted"]), r)

    def test_the_count_is_what_will_be_deleted(self):
        r = self.press("all", "")
        self.assertEqual("3", r["shown"]["count"], r)
        self.assertFalse(r["shown"]["hidden"], r)

    def test_only_the_clusters_on_screen_are_touched(self):
        r = self.press("dup-cloud", "foxtrot")
        self.assertEqual(["delete_cloud uuid-f1"], r["deleted"], r)
        self.assertEqual("1", r["shown"]["count"], r)

    def test_the_dialog_names_what_goes(self):
        r = self.press("dup-cloud", "foxtrot")
        self.assertIn("Invented Foxtrot", r["dialog"], r)
        self.assertNotIn("Invented Golf", r["dialog"], r)
        self.assertNotIn("Invented Hotel", r["dialog"], r)

    def test_an_empty_list_hides_the_button(self):
        r = self.press("dup-local", "foxtrot")
        self.assertTrue(r["shown"]["hidden"], r)
        self.assertEqual([], r["deleted"], r)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
