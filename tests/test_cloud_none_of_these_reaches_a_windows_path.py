""""None of these" on a held-back file works for a Windows path.

The button's argument is the local path written through `p()`, which turns
backslashes into forward slashes, while the group it looks up holds the path as
the server sent it - `str(Path)`, backslashes on Windows. The two were compared
with `===`, so on Windows the lookup found nothing and the button returned
without a word. The existing test used `C:/w/...`, a spelling the server never
sends, so it could not fail.

This renders the real section from a path spelled the way Windows spells it,
reads the button's handler and argument back out of the markup, and runs it.
Every name and path here is invented.
"""
from __future__ import annotations

import unittest

from tests import cloud_vm
from tests.delegated import DELEGATED_JS


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class NoneOfTheseReachesAWindowsPath(unittest.TestCase):

    PROBE = DELEGATED_JS + r"""
s.__set('currentTab', 'projects');
s.__set('data', { currentUser: 'pat@example.invalid', matched: [], cloudOnly: [], localOnly: [] });
const PATH = 'C:\\invented\\folder\\Invented Mike.esx';          // as the server sends it
const list = [
  { kind: 'projects', reason: 'two equally good names',
    local: { path: PATH, name: 'Invented Mike', isDir: false },
    cloud: { id: 'uuid-m1', name: 'Invented Mike A' } },
  { kind: 'projects', reason: 'two equally good names',
    local: { path: PATH, name: 'Invented Mike', isDir: false },
    cloud: { id: 'uuid-m2', name: 'Invented Mike B' } },
];
s._collectHeldBack = () => list;
s.buildPassOwner = () => null;

const html = s.renderHeldBackSection(list);
const hit = delegated(html, 'heldBackNoneOfThese');
if (!hit) throw new Error('the section has no "None of these" control');

const dismissed = [];
s.markNotMatch = async (cloudId, localPath, cloudName, localName, opts) => {
  dismissed.push({ cloudId, localPath, silent: !!(opts && opts.silent) });
};
s.confirms.length = 0;
await s[hit.fn].apply(null, hit.args);
await settle();
out({ argument: hit.args[0], asked: s.confirms.length,
      dismissed: dismissed.map(d => d.cloudId) });
"""

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(cls.PROBE)

    def test_it_asks_and_dismisses_every_candidate(self):
        self.assertEqual(1, self.r["asked"], self.r)
        self.assertEqual(["uuid-m1", "uuid-m2"], self.r["dismissed"], self.r)

    def test_the_button_still_carries_a_forward_slashed_path(self):
        """The spelling the rest of the page and the server agree on."""
        self.assertEqual("C:/invented/folder/Invented Mike.esx", self.r["argument"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
