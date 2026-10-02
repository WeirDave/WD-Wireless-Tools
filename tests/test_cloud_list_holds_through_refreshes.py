"""What he did to the list survives the refreshes that follow.

* **Expand all on the Sites tab** cleared the record of which sites had been
  decided, so the refresh after his next action closed them all again. And
  any change in a count looked like a new data set, which shut the sites he
  had opened by hand. Each site is now decided once per visit, and Expand all
  / Collapse all hold until he leaves the tab.
* **Out-of-order refreshes.** Two actions finishing close together each ask
  for the list; when the first, slower answer arrived last, it was drawn last
  and showed the list as it was before the second action. An answer older
  than one already applied is dropped - and a newer background answer stands
  in for an older one he asked for, so his action's result is not left behind
  the "changed" bar.

Driven through the real cloud.js. Every name is invented.
"""
from __future__ import annotations

import json
import unittest

from tests import cloud_vm


def _site(i, n_kids=1):
    kids = [{"cloud": {"id": f"p{i}-{k}", "name": f"Dock {i} {k}", "mtime": 1},
             "local": {"path": f"/o/Dock {i}/Dock {i} {k}.esx", "name": f"Dock {i} {k}",
                       "mtime": 1},
             "status": "synced", "matchType": "exact"} for k in range(n_kids)]
    ch = {"matched": kids, "cloudOnly": [], "localOnly": []}
    return {"cloud": {"id": f"s{i}", "name": f"Dock {i}", "children": ch},
            "local": {"path": f"/o/Dock {i}", "name": f"Dock {i}", "isDir": True,
                      "children": ch},
            "status": "synced", "matchType": "exact"}


def _payload(*sites):
    return {"matched": list(sites), "cloudOnly": [], "localOnly": [],
            "orphans": {"cloudOnly": []}, "currentUser": "pat@example.invalid"}


TREE = r"""
s.__set('currentTab', 'sites');
s.__set('_treeOpenMode', 'attention');
// onData takes the payload as JSON text, as refreshData hands it over.
const A = %s, B = %s, C = %s;
const shut = () => [...s.__get('collapsed')].sort();
s.onData('sites', A, { background: false });
const afterLoad = shut();
s.expandAllSites();
s.onData('sites', A, { background: false });
const expandThenSameData = shut();
s.onData('sites', C, { background: false });
const expandThenNewSite = shut();
// A fresh visit: the default applies again; then he opens one by hand.
s.__set('currentTab', 'projects'); s.onData('projects', A, { background: false });
s.__set('currentTab', 'sites');
s.onData('sites', A, { background: false });
s.__get('collapsed').delete('site:s1');
s.onData('sites', B, { background: false });   // only a count changed
const openedByHandThenCountsChange = shut();
out({ afterLoad, expandThenSameData, expandThenNewSite, openedByHandThenCountsChange });
"""


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class ExpandAllHoldsForTheVisitTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        a = _payload(_site(1), _site(2))
        b = _payload(_site(1, 2), _site(2))
        c = _payload(_site(1), _site(2), _site(3))
        dumps = [json.dumps(json.dumps(p)) for p in (a, b, c)]
        cls.r = cloud_vm.run(TREE % tuple(dumps))

    def test_finished_sites_start_closed(self):
        self.assertEqual(["site:s1", "site:s2"], self.r["afterLoad"])

    def test_expand_all_survives_the_next_refresh(self):
        self.assertEqual([], self.r["expandThenSameData"])

    def test_a_site_that_appears_after_expand_all_opens_too(self):
        self.assertEqual([], self.r["expandThenNewSite"])

    def test_a_site_opened_by_hand_stays_open_when_a_count_changes(self):
        self.assertEqual(["site:s2"], self.r["openedByHandThenCountsChange"])


ORDER = r"""
s.__set('currentTab', 'projects');
const pending = [];
s.pyApi = (m, ...args) => {
  if (m !== 'get_data') return Promise.resolve({ ok: true });
  return new Promise(res => pending.push(res));
};
s.refreshDupIndex = () => {};
// The harness stubs refreshData; this is the shipping one, evaluated in
// cloud.js's own scope so it sees the file's own state.
const csrc = fs.readFileSync(cloudPath, 'utf8');
const a0 = csrc.indexOf('function refreshData(silent, opts) {');
if (a0 < 0) throw new Error('refreshData moved');
let b0 = a0, dp = 0, sn = false;
while (b0 < csrc.length && !(sn && dp === 0)) {
  if (csrc[b0] === '{') { dp++; sn = true; } else if (csrc[b0] === '}') dp--; b0++;
}
s.refreshData = s.__get('(' + csrc.slice(a0, b0) + ')');
const list = (name) => ({ matched: [], cloudOnly: [], orphans: { cloudOnly: [] },
  localOnly: [{ path: '/o/A/' + name + '.esx', name, mtime: 1 }],
  currentUser: 'pat@example.invalid' });
const shown = () => s.__get('data').localOnly.map(x => x.name);
const bar = () => !s.document.getElementById('staleDataBar').hidden;
const flush = async () => { for (let i = 0; i < 4; i++) await settle(); };

// 1. Two of his own refreshes; the older answer arrives last.
s.refreshData(true, { background: false });
s.refreshData(true, { background: false });
pending[1](list('Quay North')); await flush();
pending[0](list('Quay')); await flush();
const outOfOrder = { shown: shown(), bar: bar() };

// 2. His refresh, then a background poll that answers first and newer.
pending.length = 0;
s.refreshData(true, { background: false });
s.refreshData(true, { background: true });
pending[1](list('Quay East')); await flush();
pending[0](list('Quay')); await flush();
const pollStandsIn = { shown: shown(), bar: bar() };

// 3. A background poll on its own still waits behind the bar.
pending.length = 0;
s.refreshData(true, { background: true });
pending[0](list('Quay West')); await flush();
const pollAlone = { shown: shown(), bar: bar() };
out({ outOfOrder, pollStandsIn, pollAlone });
"""


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class TheNewestAnswerWinsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(ORDER)

    def test_an_older_answer_arriving_last_is_not_drawn(self):
        self.assertEqual({"shown": ["Quay North"], "bar": False}, self.r["outOfOrder"])

    def test_a_newer_poll_answer_lands_for_the_refresh_he_asked_for(self):
        self.assertEqual({"shown": ["Quay East"], "bar": False}, self.r["pollStandsIn"])

    def test_a_poll_on_its_own_still_waits_behind_the_bar(self):
        self.assertEqual({"shown": ["Quay East"], "bar": True}, self.r["pollAlone"])


if __name__ == "__main__":
    unittest.main()
