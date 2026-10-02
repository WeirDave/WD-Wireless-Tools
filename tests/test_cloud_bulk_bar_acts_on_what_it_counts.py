"""The bulk bar counts what its actions will act on, and only what can work.

Three faults of one shape - the bar asked a different question from the
action behind it:

* **Pairs were counted by row kind.** Every matched row now gives each side
  its own checkbox (`s-c:`/`s-l:`, `ct-c:`/`ct-l:`), and those rows are kind
  cloud or local, so a count of `kind === 'pair'` found nothing. "Make
  matching pairs agree…" could never be pressed, and Verify was dead on the
  Flat tab - while `bulkReconcile` itself resolved the same ticks to a pair.
* **Bulk Share listed ids and offered sites.** A cloud side's row carries
  `name`, not `cloudName`, so the dialog listed `uuid-…`; and a ticked site
  enabled "Share 1 project" and sent the site's id.
* **Bulk Move and Delete had no ownership gate**, while the row menu refuses
  both on a colleague's project ("A filter is a view, not a permission").
  They are now left out by name, as Share already does.

Driven through the real cloud.js (`tests/cloud_vm.py`); the server is a
recorder. Every name and address is invented.
"""
from __future__ import annotations

import unittest

from tests import cloud_vm

ME = "pat@example.invalid"
OTHER = "lee@example.invalid"

COMMON = r"""
const ME = 'pat@example.invalid', OTHER = 'lee@example.invalid';
function pick(tab, data, keys) {
  s.__set('currentTab', tab); s.__set('data', data); s.indexRowData();
  const sel = s.__get('selected'); sel.clear(); keys.forEach(k => sel.add(k));
  s.updateBulkBar();
}
const off = id => s.document.getElementById(id).classList.contains('is-disabled');
const pair = { matchType: 'exact',
  cloud: { id: 'uuid-k', name: 'Invented Kilo', owner: ME, mtime: 2 },
  local: { path: 'C:/w/Kilo/Invented Kilo.esx', name: 'Invented Kilo', isDir: false, mtime: 1 } };
const projects = { currentUser: ME, matched: [pair], cloudOnly: [], localOnly: [] };
const sites = { currentUser: ME, cloudOnly: [], localOnly: [], matched: [{ matchType: 'exact',
  cloud: { id: 'site-K', name: 'Kilo', owner: ME, children: { matched: [pair], cloudOnly: [], localOnly: [] } },
  local: { path: 'C:/w/Kilo', name: 'Kilo', isDir: true, children: { matched: [], cloudOnly: [], localOnly: [] } } }] };
"""


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class APairTickedBySideIsAPair(unittest.TestCase):
    """Either side's checkbox, on either tab, stands for its pair."""

    PROBE = COMMON + r"""
const res = {};
const reconciled = [];
s.reconcilePairs = (list) => { reconciled.push(list); };
for (const [label, tab, data, keys] of [
    ['projects, both sides', 'projects', projects, ['s-c:uuid-k', 's-l:C:/w/Kilo/Invented Kilo.esx']],
    ['projects, cloud side', 'projects', projects, ['s-c:uuid-k']],
    ['projects, local side', 'projects', projects, ['s-l:C:/w/Kilo/Invented Kilo.esx']],
    ['sites, both sides', 'sites', sites, ['ct-c:uuid-k', 'ct-l:C:/w/Kilo/Invented Kilo.esx']]]) {
  pick(tab, data, keys);
  const state = { reconcile: !off('bulkReconcileBtn'), verify: !off('bulkVerifyBtn') };
  reconciled.length = 0; s.calls.length = 0;
  s.bulkReconcile();
  pick(tab, data, keys);
  await s.bulkVerifyNameMatches();
  for (let i = 0; i < 5; i++) await settle();
  res[label] = { state, reconciled: reconciled.slice(),
                 verify: s.calls.filter(c => c.m === 'verify_replace_local').map(c => c.args) };
}
// A matched *site* is not a pair either action can use.
pick('sites', sites, ['s-c:site-K', 's-l:C:/w/Kilo']);
res['a site'] = { reconcile: !off('bulkReconcileBtn'), verify: !off('bulkVerifyBtn') };
out(res);
"""

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(cls.PROBE)

    def test_both_actions_are_offered_and_reach_the_pair(self):
        for label in ("projects, both sides", "projects, cloud side",
                      "projects, local side", "sites, both sides"):
            with self.subTest(label):
                got = self.r[label]
                self.assertEqual({"reconcile": True, "verify": True}, got["state"], got)
                self.assertEqual([[{"cloudId": "uuid-k", "name": "Invented Kilo"}]],
                                 got["reconciled"], got)
                self.assertEqual([["uuid-k", "C:/w/Kilo/Invented Kilo.esx"]],
                                 got["verify"], got)

    def test_a_matched_site_is_not_offered_as_a_pair(self):
        self.assertEqual({"reconcile": False, "verify": False}, self.r["a site"])


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class BulkShareNamesProjectsAndOnlyProjects(unittest.TestCase):

    PROBE = COMMON + r"""
const shared = [];
s.openManageShares = async (...args) => { shared.push(args); };
const res = {};
pick('projects', { currentUser: ME, localOnly: [],
  matched: [{ matchType: 'exact', cloud: { id: 'uuid-1', name: 'Invented Bravo', owner: ME },
              local: { path: 'C:/p/Invented Bravo.esx', name: 'Invented Bravo', isDir: false } }],
  cloudOnly: [{ id: 'uuid-2', name: 'Invented Charlie', owner: ME },
              { id: 'uuid-3', name: 'Invented Delta', owner: OTHER }] },
  ['s-c:uuid-1', 'c:uuid-2', 'c:uuid-3']);
await s.openBulkShare();
res.projects = shared.pop();
// The cloud side of a matched site, alone.
pick('sites', { currentUser: ME, cloudOnly: [], localOnly: [], matched: [{ matchType: 'exact',
  cloud: { id: 'site-A', name: 'Invented Alpha', owner: ME, children: { matched: [], localOnly: [],
           cloudOnly: [{ id: 'proj-1', name: 'Invented Alpha Survey', owner: ME }] } },
  local: { path: 'C:/p/Invented Alpha', name: 'Invented Alpha', isDir: true,
           children: { matched: [], cloudOnly: [], localOnly: [] } } }] }, ['s-c:site-A']);
res.siteOffered = !off('bulkShareBtn');
await s.openBulkShare();
res.siteShared = shared.length;
out(res);
"""

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(cls.PROBE)

    def test_the_dialog_is_given_names_not_ids(self):
        ids, owned, not_mine = self.r["projects"][2:5]
        self.assertEqual(["uuid-1", "uuid-2"], ids)
        self.assertEqual([{"id": "uuid-1", "name": "Invented Bravo"},
                          {"id": "uuid-2", "name": "Invented Charlie"}], owned)
        self.assertEqual([{"id": "uuid-3", "name": "Invented Delta",
                           "owner": "lee@example.invalid"}], not_mine)

    def test_a_site_is_not_shared_as_a_project(self):
        self.assertFalse(self.r["siteOffered"])
        self.assertEqual(0, self.r["siteShared"])


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class AColleaguesProjectIsLeftOutByName(unittest.TestCase):

    PROBE = COMMON + r"""
const data = { currentUser: ME, matched: [], localOnly: [{ path: 'C:/p/Invented Echo.esx', name: 'Invented Echo', isDir: false }],
  cloudOnly: [{ id: 'uuid-3', name: 'Invented Delta', owner: OTHER },
              { id: 'uuid-4', name: 'Invented Foxtrot', owner: ME }] };
const res = {};
let picked = null;
s._openMoveToSitePicker = async () => { picked = s.__get('_moveToSiteTargets').map(t => t.id || t.path); };

// Only the colleague's project ticked.
pick('projects', data, ['c:uuid-3']);
res.onlyTheirs = { move: !off('bulkMoveBtn'), del: !off('bulkDeleteBtn'),
                   why: s.document.getElementById('bulkDeleteBtn').title };
s.toasts.length = 0;
await s.bulkMoveToSite();
s.bulkDelete();
res.onlyTheirs.toasts = s.toasts.map(t => t[1]);
res.onlyTheirs.picked = picked;

// Theirs, mine, and a local file.
pick('projects', data, ['c:uuid-3', 'c:uuid-4', 'l:C:/p/Invented Echo.esx']);
s.toasts.length = 0; picked = null;
await s.bulkMoveToSite();
res.mixed = { picked, moveToasts: s.toasts.map(t => t[1]) };
s.calls.length = 0;
pick('projects', data, ['c:uuid-3', 'c:uuid-4', 'l:C:/p/Invented Echo.esx']);
s.bulkDelete();
res.mixed.dialog = text(s.document.getElementById('deleteSub').innerHTML)
  + ' ' + text(s.document.getElementById('deleteWhat').innerHTML);
await s.confirmDelete();
for (let i = 0; i < 5; i++) await settle();
res.mixed.deleted = s.calls.map(c => c.m + ' ' + c.args[c.args.length - 1]);
out(res);
"""

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(cls.PROBE)

    def test_nothing_of_his_selected_means_neither_is_offered(self):
        got = self.r["onlyTheirs"]
        self.assertFalse(got["move"], got)
        self.assertFalse(got["del"], got)
        self.assertIn("owned by someone else", got["why"])
        self.assertIsNone(got["picked"], got)

    def test_pressing_it_anyway_says_who_owns_it(self):
        joined = " ".join(self.r["onlyTheirs"]["toasts"])
        self.assertIn("Invented Delta", joined)
        self.assertIn(OTHER, joined)

    def test_move_takes_his_and_names_theirs(self):
        got = self.r["mixed"]
        self.assertEqual(["uuid-4", "C:/p/Invented Echo.esx"], got["picked"], got)
        self.assertIn("Invented Delta", " ".join(got["moveToasts"]), got)

    def test_delete_takes_his_and_names_theirs(self):
        got = self.r["mixed"]
        self.assertEqual(sorted(["delete_cloud uuid-4",
                                 "delete_local C:/p/Invented Echo.esx"]),
                         sorted(got["deleted"]), got)
        self.assertIn("left out", got["dialog"])
        self.assertIn("Invented Delta", got["dialog"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
