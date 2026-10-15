"""Sync all is of your own work, not of everything the account can see.

The "Download N cloud projects you have no local copy of" section took every
cloud-only project in the list, whoever owned it. On an account that can see
colleagues' projects that put dozens of other people's drawings into a sync
that was meant to be the user's own, each ticked by default.

A project that is provably someone else's is now left out of the run and
counted in a sentence instead. One with no owner recorded stays in: a missing
owner field is not evidence of anything (see `ownershipOf`).

Driven through the real `syncEverythingPlan` and `syncEverything` in Node.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8').split('\r\n').join('\n');
function cut(from, to) {
  const a = source.indexOf(from), b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
function e(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
const said = [];
function toast(msg) { said.push(msg); }
// One evaluation: `const` is block-scoped to its own eval.
eval(cut('function ownershipBlock(', '\nfunction _isExternal(')
   + cut('const PULLABLE_MATCH_TYPES', 'function canPushToCloud(')
   + cut('function syncEverythingPlan() {', 'function _syncSiteRowsHtml(')
   + cut('async function syncEverything() {', '\n}\n') + '\n}');
const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
const ME = 'me@example.com';
function cloudOnly(id, owner) { return { id: id, name: id, owner: owner, mtime: 200 }; }
"""


def run_node(checks: str) -> None:
    program = PRELUDE + checks
    r = subprocess.run(["node", "-e", program, str(CLOUD_JS)],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class SyncAllLeavesOutOtherPeoplesProjects(unittest.TestCase):

    def test_only_my_cloud_only_projects_are_offered_for_download(self):
        run_node("""
          data = { summary: {}, currentUser: ME, matched: [], cloudOnly: [
            cloudOnly('mine-1', ME), cloudOnly('theirs-1', 'other@example.com'),
            cloudOnly('mine-2', ME.toUpperCase()), cloudOnly('theirs-2', 'third@example.org')] };
          var p = syncEverythingPlan();
          check('mine come down: ' + p.fresh.map(x => x.id),
                p.fresh.map(x => x.id).sort().join() === 'mine-1,mine-2');
          check('theirs are counted, not downloaded: ' + p.othersFresh.map(x => x.id),
                p.othersFresh.map(x => x.id).sort().join() === 'theirs-1,theirs-2');
          done();
        """)

    def test_a_project_with_no_recorded_owner_stays_in(self):
        run_node("""
          data = { summary: {}, currentUser: ME, matched: [], cloudOnly: [
            cloudOnly('no-owner', ''), cloudOnly('odd-owner', 'not-an-email')] };
          var p = syncEverythingPlan();
          check('an unproven owner is kept: ' + p.fresh.length, p.fresh.length === 2);
          check('nothing left out', p.othersFresh.length === 0);
          done();
        """)

    def test_those_inside_a_site_are_held_to_the_same_rule(self):
        run_node("""
          data = { summary: {}, currentUser: ME, matched: [{
            cloud: { id: 'site-1', name: 'Site One', children: { matched: [],
              cloudOnly: [cloudOnly('in-mine', ME), cloudOnly('in-theirs', 'other@example.com')] } },
            local: { name: 'Site One', path: '/local/Site One' }, staleness: null }] };
          var p = syncEverythingPlan();
          check('mine: ' + p.fresh.map(x => x.id), p.fresh.map(x => x.id).join() === 'in-mine');
          check('theirs: ' + p.othersFresh.map(x => x.id),
                p.othersFresh.map(x => x.id).join() === 'in-theirs');
          done();
        """)

    def test_when_only_other_peoples_projects_are_new_it_says_so_and_does_nothing(self):
        run_node("""
          data = { summary: {}, currentUser: ME, matched: [], cloudOnly: [
            cloudOnly('t1', 'other@example.com'), cloudOnly('t2', 'other@example.com')] };
          syncEverything().then(() => {
            check('one toast: ' + said.length, said.length === 1);
            check('it names other people: ' + said[0],
                  /2 cloud projects belong to other people/.test(said[0]));
            done();
          });
        """)


if __name__ == "__main__":
    unittest.main()
