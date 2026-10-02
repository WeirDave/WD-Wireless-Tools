"""Under Mine, a project he owns is his - whoever created it.

The owner filter, the dashboard counts and External all fell back to the
local file's creator (`history.createdBy`). A project a colleague created and
transferred to him was hidden under Mine, shown under Others and counted
External, though the cloud says plainly that he owns it. Ownership can be
transferred and the creator does not move with it.

So wherever there is a cloud side, its owner decides alone; the creator
answers only for a local-only file, which has nothing else. Same three-state
rule as `test_cloud_ownership_is_three_states`: an unknown cloud owner is not
somebody else's.

Driven through the real cloud.js. Every address is invented.
"""
from __future__ import annotations

import unittest

from tests import cloud_vm

PROBE = r"""
const ME = 'pat@example.invalid', MATE = 'sam@example.invalid';
s.__set('data', { currentUser: ME, matched: [], cloudOnly: [], localOnly: [],
                  orphans: { cloudOnly: [] } });
const rows = {
  transferredToMe: { cloud: { id: 'p1', owner: ME }, local: { path: '/w/A/One.esx', owner: MATE } },
  hisOwnCopyOfTheirs: { cloud: { id: 'p2', owner: MATE }, local: { path: '/w/A/Two.esx', owner: ME } },
  cloudOwnerUnknown: { cloud: { id: 'p3', owner: '' }, local: { path: '/w/A/Three.esx', owner: MATE } },
  localOnlyByMate: { cloud: null, local: { path: '/w/A/Four.esx', owner: MATE } },
  localOnlyByMe: { cloud: null, local: { path: '/w/A/Five.esx', owner: ME } },
};
const res = {};
for (const [k, r] of Object.entries(rows)) {
  s.ownerFilter = () => 'mine';
  const countsMine = s._passOwnerForCounts(r.cloud, r.local);
  s.ownerFilter = () => 'others';
  const countsOthers = s._passOwnerForCounts(r.cloud, r.local);
  res[k] = {
    mine: s.buildPassOwner('mine', ME)(r),
    others: s.buildPassOwner('others', ME)(r),
    countsMine, countsOthers,
    external: s._isExternal(r.cloud, r.local),
  };
}
out(res);
"""


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class TheCloudOwnerDecidesTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(PROBE)

    def _is_mine(self, key):
        got = self.r[key]
        self.assertEqual({"mine": True, "others": False, "countsMine": True,
                          "countsOthers": False, "external": False}, got, key)

    def _is_theirs(self, key):
        got = self.r[key]
        self.assertEqual({"mine": False, "others": True, "countsMine": False,
                          "countsOthers": True, "external": True}, got, key)

    def test_a_project_transferred_to_him_is_his(self):
        self._is_mine("transferredToMe")

    def test_a_colleagues_project_is_theirs_whoever_made_the_local_file(self):
        self._is_theirs("hisOwnCopyOfTheirs")

    def test_an_unknown_cloud_owner_is_not_somebody_elses(self):
        self._is_mine("cloudOwnerUnknown")

    def test_a_local_only_file_still_goes_by_its_creator(self):
        self._is_theirs("localOnlyByMate")
        self._is_mine("localOnlyByMe")


if __name__ == "__main__":
    unittest.main()
