"""Deleting duplicates never spends his copies to keep a colleague's.

* **Keep newest / Delete all extras** kept the cluster's newest copy whoever
  owned it. In a cloud-only cluster where a colleague's copy was newest, every
  copy he owned was deleted and the one kept was not his - and Ekahau would
  not have let him delete it anyway.
* **The other way round**, colleagues' copies were offered for deletion and
  Ekahau answered 403.

The copy kept is now the newest of those he can act on; a colleague's copy is
left out of every delete, named in the dialog, and kept out of the toolbar
count. Unproven ownership is still attempted, as everywhere else.

Driven through the real cloud.js: the cluster's own controls and the toolbar
button, with the deletes they send recorded. Every address is invented.
"""
from __future__ import annotations

import json
import unittest

from tests import cloud_vm

ME = "pat@example.invalid"
MATE = "sam@example.invalid"


def _cloud(i, mtime, owner):
    return {"side": "cloud", "id": i, "name": "Invented Survey", "mtime": mtime,
            "size": 10, "owner": owner, "matched": False}


CLUSTERS = [
    # A colleague's copy is the newest.
    {"key": "theirs-newest", "shape": "cloud-only", "sides": {"cloud": 3, "local": 0}, "newestId": "c3", "largestId": "c3",
     "items": [_cloud("c1", 100, ME), _cloud("c2", 200, ME), _cloud("c3", 300, MATE)]},
    # His copy is the newest; a colleague's older one sits beside it.
    {"key": "mine-newest", "shape": "cloud-only", "sides": {"cloud": 2, "local": 0}, "newestId": "d2", "largestId": "d2",
     "items": [_cloud("d1", 100, MATE), _cloud("d2", 200, ME)]},
    # Every copy is somebody else's.
    {"key": "all-theirs", "shape": "cloud-only", "sides": {"cloud": 2, "local": 0}, "newestId": "e2", "largestId": "e2",
     "items": [_cloud("e1", 100, MATE), _cloud("e2", 200, MATE)]},
]

PROBE = r"""
const D = JSON.parse(%s);
s.__set('currentTab', 'duplicates');
s.__set('dupData', D);
s.__set('data', null);
s.document.getElementById('searchBox').value = '';
const deleted = [];
s.pyApi = async (m, ...args) => {
  if (m === 'delete_cloud') deleted.push(args[1]);
  return { ok: true };
};
const run = async (fn) => { deleted.length = 0; s.confirms.length = 0; s.toasts.length = 0;
  await fn(); for (let i = 0; i < 4; i++) await settle();
  return { deleted: [...deleted].sort(), asked: s.confirms.map(c => text(c.body)).join(' '),
           toasts: s.toasts.map(t => t[1]).join(' | ') }; };
const r = {};
r.keepNewestTheirs = await run(() => s.dupKeep('theirs-newest', 'newest'));
r.keepNewestMine = await run(() => s.dupKeep('mine-newest', 'newest'));
r.keepNewestAllTheirs = await run(() => s.dupKeep('all-theirs', 'newest'));
r.deleteAllExtras = await run(() => s.dupDeleteAllExtras());
s.renderDuplicates();
r.toolbarCount = String(s.document.getElementById('dupDeleteAllToolbarCount').textContent);
out(r);
"""


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class TheCopyKeptIsOneHeCanKeepTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        payload = {"clusters": CLUSTERS, "currentUser": ME, "summary": {}}
        cls.r = cloud_vm.run(PROBE % json.dumps(json.dumps(payload)))

    def test_keep_newest_keeps_his_newest_when_a_colleagues_is_newer(self):
        got = self.r["keepNewestTheirs"]
        self.assertEqual(["c1"], got["deleted"], got)

    def test_a_colleagues_copy_is_left_out_and_named(self):
        got = self.r["keepNewestMine"]
        self.assertEqual([], got["deleted"], got)
        self.assertIn("sam@example.invalid", got["toasts"] + got["asked"], got)

    def test_a_cluster_of_nobody_but_colleagues_deletes_nothing_and_says_why(self):
        got = self.r["keepNewestAllTheirs"]
        self.assertEqual([], got["deleted"], got)
        self.assertIn("owner", got["toasts"], got)

    def test_delete_all_extras_touches_only_his_copies(self):
        got = self.r["deleteAllExtras"]
        self.assertEqual(["c1"], got["deleted"], got)

    def test_the_toolbar_counts_only_what_it_would_delete(self):
        self.assertEqual("1", self.r["toolbarCount"])


class TheDuplicatesListingSaysWhoIsAskingTests(unittest.TestCase):
    """The tab is often opened before any other, with no file listing loaded
    to read the signed-in account from - so its own payload carries it."""

    def test_get_duplicates_carries_the_current_user(self):
        import tempfile
        from tools import cloud_manager as cm

        class _Api:
            user_email = "Pat@Example.invalid"

            def get_dataset_listing(self):
                return []

            def get_projects(self):
                return []

        with tempfile.TemporaryDirectory(prefix="wd-dups-") as root:
            mgr = cm.CloudManager.__new__(cm.CloudManager)
            mgr.api, mgr.config = _Api(), {"output_dir": root}
            mgr._ensure = lambda: True
            got = mgr.get_duplicates()
        self.assertEqual(ME, got.get("currentUser"), got)


if __name__ == "__main__":
    unittest.main()
