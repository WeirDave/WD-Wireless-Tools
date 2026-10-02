"""Renaming a local .esx writes the name inside the file it moved to.

The rename dialog renames the file on disk, optionally its cloud partner, and
then sets `project.name` inside the archive so the pair does not come back
reading "renamed". That last write was handed the path from **before**
`rename_local` moved the file, so it always failed with "Local file not
found" - on a local rename, a both-sides rename, and a cloud-first rename that
took its local partner along.

Driven through the real cloud.js (`tests/cloud_vm.py`) against a recorder that
keeps a pretend disk, so a write to a path that no longer exists fails the way
the server would. Every name is invented.
"""
from __future__ import annotations

import unittest

from tests import cloud_vm

PROBE = r"""
const OLD = 'C:/work/Invented Site/Invented Old.esx';
const NEW = 'C:/work/Invented Site/Invented New.esx';
s.__set('currentTab', 'projects');
s.__set('data', { currentUser: 'pat@example.invalid', cloudOnly: [], localOnly: [],
  matched: [{ matchType: 'exact',
    cloud: { id: 'uuid-1', name: 'Invented Old', owner: 'pat@example.invalid' },
    local: { path: OLD, name: 'Invented Old', isDir: false } }] });
const disk = new Set();
s.pyApi = async (m, ...args) => {
  s.calls.push({ m, args });
  if (m === 'rename_local') {
    if (!disk.has(args[0])) return { error: 'not found' };
    disk.delete(args[0]); disk.add(NEW); return { ok: true, newPath: NEW };
  }
  if (m === 'set_internal_project_name') {
    return disk.has(args[0]) ? { ok: true } : { error: 'Local file not found: ' + args[0] };
  }
  return { ok: true };
};
let pending = [];
s.opEnqueue = (spec) => { const promise = Promise.resolve().then(() => spec.run('op-1'));
                          pending.push(promise.catch(e => e)); return { id: 'op-1', promise }; };
const results = {};
for (const [label, side, both] of [['local', 'local', false],
                                   ['local, both', 'local', true],
                                   ['cloud, both', 'cloud', true]]) {
  disk.clear(); disk.add(OLD); s.calls.length = 0; s.toasts.length = 0;
  if (side === 'local') s.startRename('local', OLD, 'Invented Old', 'projects');
  else s.startRename('cloud', 'uuid-1', 'Invented Old', 'projects');
  s.document.getElementById('renamePairBoth').checked = both;
  s.document.getElementById('renameInput').value = 'Invented New';
  s.confirmRename();
  await Promise.all(pending); pending = [];
  results[label] = {
    inside: s.calls.filter(c => c.m === 'set_internal_project_name').map(c => c.args),
    warnings: s.toasts.filter(t => t[0] === 'warn' || t[0] === 'error').map(t => t[1]),
  };
}
out(results);
"""


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class TheInsideNameFollowsTheFile(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(PROBE)

    def check(self, label):
        got = self.r[label]
        self.assertEqual([["C:/work/Invented Site/Invented New.esx", "Invented New"]],
                         got["inside"], got)
        self.assertEqual([], got["warnings"], got)

    def test_a_local_rename(self):
        self.check("local")

    def test_a_both_sides_rename_started_locally(self):
        self.check("local, both")

    def test_a_both_sides_rename_started_in_the_cloud(self):
        self.check("cloud, both")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
