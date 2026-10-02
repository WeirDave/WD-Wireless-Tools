"""What a row and its dialogs say is true, said once, and keeps his ticks.

* **"&" showed as "&amp;".** The row band's sentences are escaped where they
  land and `rdAction` escapes its title, and three values were escaped again
  on the way in, so a folder called "R&D Lab" read "R&amp;D Lab".
* **The local delete promised a way back that was not there.** "Can be
  undone by downloading the cloud copy again" was on every local file,
  including the ones with no cloud copy.
* **"None of these" pointed at "Not a match in Settings"**, which does not
  exist. The control is "Manage Not-a-Match" in the main menu.
* **A live refresh cleared the Duplicates ticks.** Those live in the page,
  not in `selected`, so the busy check never saw them.

Driven through the real cloud.js (`tests/cloud_vm.py`). Every name is
invented.
"""
from __future__ import annotations

import unittest

from tests import cloud_vm
from tests.delegated import DELEGATED_JS

COMMON = r"""
s.__set('currentTab', 'projects');
s.__set('data', { currentUser: 'pat@example.invalid', matched: [], cloudOnly: [], localOnly: [] });
const unattr = v => String(v).replace(/&quot;/g, '"').replace(/&#39;/g, "'")
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
"""


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class EscapedOnce(unittest.TestCase):

    PROBE = COMMON + r"""
const rejected = s.rowDetailHtml({ status: 'orphan', kind: 'projects', local: null,
  cloud: { id: 'uuid-9', name: 'Invented India', owner: 'pat@example.invalid', rejectedPairing: true,
           rejectedLocalName: 'R&D Lab', rejectedLocalPath: 'C:/w/R&D Lab/R&D Lab.esx' } }, false);
const collision = s.rowDetailHtml({ status: 'orphan', kind: 'projects', local: null,
  cloud: { id: 'uuid-8', name: 'Invented Juliet', owner: 'pat@example.invalid',
           nameCollision: true, collidingLocalName: 'R&D Juliet' } }, false);
const textOf = h => unattr((h.match(/<span class="rd-text">([^<]*)<\/span>/) || [, ''])[1]);
const titleOf = h => unattr((h.match(/title="(Pair these two again[^"]*)"/) || [, ''])[1]);
out({ rejectedText: textOf(rejected), rejectedTitle: titleOf(rejected),
      collisionText: textOf(collision) });
"""

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(cls.PROBE)

    def test_the_sentence_shows_the_name_as_written(self):
        self.assertIn("marked this and R&D Lab as not a match", self.r["rejectedText"])
        self.assertIn("already on disk: R&D Juliet.", self.r["collisionText"])

    def test_the_tooltip_shows_the_path_as_written(self):
        self.assertEqual("Pair these two again. C:/w/R&D Lab/R&D Lab.esx",
                         self.r["rejectedTitle"])


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class TheLocalDeleteSaysWhetherThereIsAWayBack(unittest.TestCase):

    PROBE = COMMON + DELEGATED_JS + r"""
const local = { path: 'C:/w/Invented Kilo.esx', name: 'Invented Kilo', isDir: false };
const titleOf = (r) => {
  const hit = delegated(s.localCell(r, new Set()), 'startDelete');
  if (!hit) throw new Error('no delete control on the row');
  return unattr((hit.tag.match(/title="([^"]*)"/) || [, ''])[1]);
};
out({ alone: titleOf({ status: 'orphan', kind: 'projects', key: 'l:x', cloud: null, local }),
      paired: titleOf({ status: 'synced', kind: 'projects', key: 'p:uuid-k',
                        cloud: { id: 'uuid-k', name: 'Invented Kilo' }, local }) });
"""

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(cls.PROBE)

    def test_no_cloud_copy_no_promise(self):
        self.assertNotIn("downloading the cloud copy", self.r["alone"])
        self.assertIn("cannot be undone", self.r["alone"])

    def test_a_paired_file_keeps_its_way_back(self):
        self.assertIn("downloading the cloud copy again", self.r["paired"])


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class NoneOfTheseNamesARealControl(unittest.TestCase):
    """Every control the dialog names in bold is a menu item on the page whose
    handlers exist - read off the page's markup and looked up in the running
    script, not matched as a phrase."""

    PROBE = COMMON + r"""
const page = require('fs').readFileSync(process.argv[1].replace(/assets[\\/]js[\\/]wd-shared\.js$/, 'cloud.html'), 'utf8');
if (!/<html/i.test(page)) throw new Error('cloud.html was not the file read');
const group = { local: { path: 'C:/w/Invented Lima.esx', name: 'Invented Lima' },
                candidates: [{ cloud: { id: 'uuid-l', name: 'Invented Lima 2' } }] };
s._collectHeldBack = () => [];
s._groupHeldBack = () => [group];
s.buildPassOwner = () => null;
s.showConfirmModal = async (t, body) => { s.confirms.push({ title: t, body }); return false; };
await s.heldBackNoneOfThese('C:/w/Invented Lima.esx');
const body = (s.confirms[0] || {}).body || '';
const named = [...body.matchAll(/<b>([^<]*)<\/b>/g)].map(m => unattr(m[1]))
  .filter(n => n !== 'Invented Lima');
const controls = named.map(n => {
  const tag = [...page.matchAll(/<(?:button|a)\b[^>]*>([^<]*)<\/(?:button|a)>/g)]
    .find(m => unattr(m[1]).replace(/^·\s*/, '').trim() === n);
  const fns = tag ? ((tag[0].match(/data-fn="([^"]*)"/) || [, ''])[1]).split(',').filter(Boolean) : [];
  return { name: n, found: !!tag, fns, defined: fns.map(f => typeof s[f] === 'function') };
});
out({ named, controls });
"""

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(cls.PROBE)

    def test_it_names_a_control(self):
        self.assertTrue(self.r["named"], self.r)

    def test_every_control_it_names_exists_and_works(self):
        for c in self.r["controls"]:
            with self.subTest(c["name"]):
                self.assertTrue(c["found"], "no control on the page is labelled %r"
                                % c["name"])
                self.assertTrue(c["fns"], c)
                self.assertTrue(all(c["defined"]), c)


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class ALiveRefreshKeepsTheDuplicateTicks(unittest.TestCase):

    PROBE = COMMON + r"""
let refreshed = 0;
s.refreshData = () => { refreshed++; };
const res = {};
for (const ticked of [false, true]) {
  s.document.querySelector = (sel) => (ticked && sel === '.dup-item-check:checked') ? {} : null;
  s.__get('selected').clear();
  refreshed = 0;
  s.__set('liveCountdown', 1);
  s.liveTick();
  res[ticked ? 'ticked' : 'clear'] = { busy: s.liveBusy(), refreshed };
}
out(res);
"""

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(cls.PROBE)

    def test_a_ticked_duplicate_holds_the_refresh(self):
        self.assertEqual({"busy": True, "refreshed": 0}, self.r["ticked"])

    def test_nothing_ticked_still_refreshes(self):
        """The check can fail: with no tick the same tick refreshes."""
        self.assertEqual({"busy": False, "refreshed": 1}, self.r["clear"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
