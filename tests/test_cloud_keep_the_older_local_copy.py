"""Replacing a newer cloud copy with an older local file, on purpose.

"I started off working on one file ... made a copy of that file and started
working on that ... now I want to take the local copy that was before my
changes and overwrite it on the cloud."

A "Cloud newer" row offered only the download. The replace was drawn only on
a local-newer row, and the server refused a newer cloud copy outright. Now the
row carries "Replace cloud with local…", which asks once - naming the project
and both dates - and only then sends the one flag that lets the server past
its newer-copy refusal.

Driven: the real row is rendered, the control is read back out of that markup
and run against recording stubs. Every name is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from delegated import DELEGATED_JS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120

NODE_SCRIPT = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
const block = slice('function ownershipBlock(', '\nfunction _isExternal(')
            + slice('function comparisonIsSettled(', '\nfunction isOutOfSync(')
            + slice('function fmtExactDate(ts)', '\nfunction toggleFolder(')
            + slice('const ICONS = {', '\nfunction siteDigest(')
            + slice('const MATCH_BADGE_SPEC = {', '\nfunction gutCell(r)');

const WD = { esc: s => String(s == null ? '' : s),
             escAttr: s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/'/g, '&#39;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
             escJsStr: s => String(s == null ? '' : s) };
function e(s) { return WD.esc(s); }
function a(s) { return WD.escAttr(s); }
function np(s) { return String(s == null ? '' : s).replace(/\\/g, '/'); }
function p(s) { return a(np(s)); }
let currentTab = 'projects';
let data = { currentUser: 'me@example.com' };

const calls = [];
const confirms = [];
const queued = [];
let confirmAnswer = true;
function opEnqueue(spec) { queued.push(spec); return { id: 'op1', promise: Promise.resolve() }; }
function toast() {}
async function pyApi(...args) { calls.push(args); return { ok: true, name: 'Alpha Survey', deletedOld: true }; }
async function showConfirmModal(title, body, label) {
  confirms.push({ title: String(title), body: String(body), label: String(label) });
  return confirmAnswer;
}
function _clearStaleness() {}
function _scheduleOpRefresh() {}

const fn = new Function('WD','e','a','p','np','currentTab','data','opEnqueue','toast','pyApi','showConfirmModal','_clearStaleness','_scheduleOpRefresh',
  block + '\nreturn { stalenessBadgeHtml, replaceNewerCloudWithLocal };');
const api = fn(WD,e,a,p,np,currentTab,data,opEnqueue,toast,pyApi,showConfirmModal,_clearStaleness,_scheduleOpRefresh);

const row = (owner, id) => ({
  kind: 'projects', matchType: 'id', staleness: 'cloud_newer', differenceKind: 'content',
  cloud: { id: id || 'c1', name: 'Alpha Survey', mtime: 1772355600, owner: owner, role: owner === 'me@example.com' ? 'OWNER' : 'READER' },
  local: { path: 'C:\\projects\\SITE1\\' + (id ? 'Bravo' : 'Alpha') + ' Survey.esx', name: 'Alpha Survey', mtime: 1767258000 },
});

(async () => {
  const out = {};
  const html = api.stalenessBadgeHtml(row('me@example.com'));
  const hit = delegated(html, 'replaceNewerCloudWithLocal');
  out.offered = !!hit;
  out.enabled = !!hit && !hit.disabled;
  out.writesCloud = !!hit && /data-writes="cloud"/.test(hit.tag);
  out.downloadStillOffered = !!delegated(html, 'verifyReplaceLocal');

  await api.replaceNewerCloudWithLocal.apply(null, hit.args);
  out.confirm = confirms[0] || null;
  out.queued = queued.length;
  if (queued.length) await queued[0].run('op1');
  out.calls = calls.slice();

  confirmAnswer = false; confirms.length = 0; queued.length = 0; calls.length = 0;
  await api.replaceNewerCloudWithLocal.apply(null, hit.args);
  out.declinedQueued = queued.length;
  out.declinedCalls = calls.length;

  // Its own id: the confirmed replace above marks row c1 busy, and a busy row
  // renders no actions at all.
  const other = api.stalenessBadgeHtml(row('someone@example.org', 'c2'));
  out.othersProjectOffersLiveControl = !!delegated(other, 'replaceNewerCloudWithLocal');
  out.othersProjectNamesIt = /Replace cloud with local/.test(other);

  process.stdout.write(JSON.stringify(out));
  process.exit(0);
})().catch(err => { process.stderr.write(String(err && err.stack || err)); process.exit(1); });
"""


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class KeepTheOlderLocalCopyTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "probe.js"
            script.write_text(DELEGATED_JS + NODE_SCRIPT, encoding="utf-8")
            proc = subprocess.run(["node", str(script), str(CLOUD_JS)],
                                  capture_output=True, timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError(
                "node failed: " + (proc.stdout + proc.stderr).decode("utf-8", "replace"))
        cls.out = json.loads(proc.stdout.decode("utf-8", "replace"))

    def test_a_cloud_newer_row_offers_it_beside_the_download(self):
        self.assertTrue(self.out["offered"])
        self.assertTrue(self.out["enabled"])
        self.assertTrue(self.out["writesCloud"])
        self.assertTrue(self.out["downloadStillOffered"])

    def test_it_asks_once_naming_the_project_and_that_cloud_changes_are_lost(self):
        c = self.out["confirm"]
        self.assertIsNotNone(c)
        self.assertIn("Alpha Survey", c["body"])
        self.assertIn("lost", c["body"])
        self.assertIn("cannot be undone", c["body"])
        self.assertIn("2026", c["body"], "the dates are not in the dialog")

    def test_confirming_sends_the_replace_with_the_override(self):
        ops = [x for x in self.out["calls"] if x[0] == "replace_cloud_project"]
        self.assertEqual(1, len(ops), self.out["calls"])
        self.assertEqual("C:/projects/SITE1/Alpha Survey.esx", ops[0][1])
        self.assertEqual("c1", ops[0][2])
        self.assertIs(True, ops[0][4])

    def test_saying_no_does_nothing(self):
        self.assertEqual(0, self.out["declinedQueued"])
        self.assertEqual(0, self.out["declinedCalls"])

    def test_someone_elses_project_names_it_but_does_not_offer_it(self):
        self.assertFalse(self.out["othersProjectOffersLiveControl"])
        self.assertTrue(self.out["othersProjectNamesIt"])


if __name__ == "__main__":
    unittest.main()
