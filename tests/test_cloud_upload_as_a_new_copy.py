"""A paired local file can go up as a second cloud project, not only over one.

He kept an older copy of a project, carried on working in a new one, and wanted
the older copy back in Ekahau Cloud as a separate project for the same site.
Upload was drawn only on a local file with nothing opposite it; once the file
was paired, the row offered download or replace and nothing else, so keeping
both had no control at all.

Driven, not asserted: the row is rendered by the real `rowDetailHtml`, the
control is read back out of that markup, and the real `uploadAsNewCopy` runs
against recording stubs. What arrives at the server is the assertion - the
rename first, then the upload of the *renamed* path into the paired project's
site, and no call that touches the existing cloud project.
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
function fnSlice(head) {
  const a = source.indexOf(head);
  if (a < 0) throw new Error('could not find ' + head);
  let b = a, depth = 0, seen = false;
  while (b < source.length && !(seen && depth === 0)) {
    if (source[b] === '{') { depth++; seen = true; }
    else if (source[b] === '}') depth--;
    b++;
  }
  return source.slice(a, b);
}
const block = slice('function comparisonIsSettled(', '\nfunction isOutOfSync(')
            + slice('const ICONS = {', '\nfunction siteDigest(')
            + slice('const MATCH_BADGE_SPEC = {', '\nfunction gutCell(r)')
            + '\n' + fnSlice('async function uploadAsNewCopy(');

const WD = { esc: s => String(s == null ? '' : s),
             escAttr: s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/'/g, '&#39;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
             escJsStr: s => String(s == null ? '' : s) };
function e(s) { return WD.esc(s); }
function a(s) { return WD.escAttr(s); }
function np(s) { return String(s == null ? '' : s).replace(/\\/g, '/'); }
function p(s) { return a(np(s)); }
let currentTab = 'projects';

const calls = [];
const toasts = [];
const prompts = [];
let promptAnswer = null;
let refreshed = 0;
function prompt(msg, def) { prompts.push({ msg: String(msg), def: String(def) }); return promptAnswer; }
function toast(msg, kind) { toasts.push({ msg: String(msg), kind: kind }); }
async function pyApi(...args) {
  calls.push(args);
  if (args[0] === 'rename_local') return { ok: true, newPath: 'C:\\projects\\SITE1\\' + args[2] + '.esx' };
  return { ok: true, uploaded: true, datasetId: 'n1', syncedBack: true };
}
async function runWithProgress(opts, fn) { return fn('op1'); }
function refreshData() { refreshed++; }
function opEnqueue() { return { id: 'op1', promise: Promise.resolve() }; }
async function showConfirmModal() { return true; }
function _clearStaleness() {}
function _scheduleOpRefresh() {}
function selectedSyncItems() { return []; }
function clearSelection() {}
function renderRows() {}

const fn = new Function('WD','e','a','p','np','currentTab','opEnqueue','toast','pyApi','showConfirmModal','_clearStaleness','_scheduleOpRefresh','selectedSyncItems','clearSelection','renderRows','prompt','runWithProgress','refreshData',
  block + '\nreturn { rowDetailHtml, uploadAsNewCopy };');
const api = fn(WD,e,a,p,np,currentTab,opEnqueue,toast,pyApi,showConfirmModal,_clearStaleness,_scheduleOpRefresh,selectedSyncItems,clearSelection,renderRows,prompt,runWithProgress,refreshData);

const row = (staleness) => ({
  kind: 'projects', matchType: 'id', staleness: staleness,
  differenceKind: staleness ? 'content' : null,
  cloud: { id: 'c1', name: 'SITE1 Survey', mtime: 200, siteId: 's9', siteName: 'SITE1' },
  local: { path: 'C:/projects/SITE1/SITE1 Survey.esx', name: 'SITE1 Survey', mtime: 100 },
});

async function click(html) {
  const hit = delegated(html, 'uploadAsNewCopy');
  if (!hit) return false;
  await api.uploadAsNewCopy.apply(null, hit.args);
  return true;
}
function reset() { calls.length = 0; toasts.length = 0; prompts.length = 0; refreshed = 0; }

(async () => {
  const out = {};

  // his case: the cloud side reads newer and the band offers only a download
  const band = api.rowDetailHtml(row('cloud_newer'), false);
  const hit = delegated(band, 'uploadAsNewCopy');
  out.offered = !!hit;
  out.writesCloud = !!hit && /data-writes="cloud"/.test(hit.tag);
  out.args = hit ? hit.args : null;

  reset(); promptAnswer = 'SITE1 Survey - original';
  out.clicked = await click(band);
  out.prompt = prompts.slice();
  out.calls = calls.slice();
  out.toasts = toasts.slice();
  out.refreshed = refreshed;

  // cancelling the name does nothing
  reset(); promptAnswer = null;
  await click(band);
  out.cancelCalls = calls.length;

  // keeping the name already in the cloud is refused before anything moves
  reset(); promptAnswer = 'SITE1 Survey.esx';
  await click(band);
  out.sameNameCalls = calls.length;
  out.sameNameToasts = toasts.slice();

  // an in-step pair has no band for it to sit in
  out.inStepBand = api.rowDetailHtml(row(null), false);

  process.stdout.write(JSON.stringify(out));
  process.exit(0);
})().catch(err => { process.stderr.write(String(err && err.stack || err)); process.exit(1); });
"""


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class UploadAsANewCopyTests(unittest.TestCase):

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

    def test_a_paired_row_offers_it_on_the_cloud_side(self):
        self.assertTrue(self.out["offered"])
        self.assertTrue(self.out["writesCloud"])

    def test_it_suggests_a_name_that_differs_from_the_cloud_project(self):
        self.assertEqual(1, len(self.out["prompt"]))
        self.assertEqual("SITE1 Survey (copy)", self.out["prompt"][0]["def"])
        self.assertIn("stays in Ekahau Cloud", self.out["prompt"][0]["msg"])

    def test_it_renames_then_uploads_the_renamed_file_into_the_same_site(self):
        calls = self.out["calls"]
        self.assertEqual(["rename_local", "upload_project"], [c[0] for c in calls])
        self.assertEqual(["rename_local", "C:/projects/SITE1/SITE1 Survey.esx",
                          "SITE1 Survey - original"], calls[0])
        self.assertEqual("C:/projects/SITE1/SITE1 Survey - original.esx", calls[1][1])
        self.assertEqual("s9", calls[1][2])

    def test_the_existing_cloud_project_is_never_touched(self):
        for c in self.out["calls"]:
            self.assertNotIn("c1", c, c)

    def test_it_reports_success_and_refreshes(self):
        self.assertEqual("success", self.out["toasts"][-1]["kind"])
        self.assertIn("unchanged", self.out["toasts"][-1]["msg"])
        self.assertEqual(1, self.out["refreshed"])

    def test_cancelling_does_nothing(self):
        self.assertEqual(0, self.out["cancelCalls"])

    def test_the_cloud_projects_own_name_is_refused_before_anything_moves(self):
        self.assertEqual(0, self.out["sameNameCalls"])
        self.assertEqual("error", self.out["sameNameToasts"][-1]["kind"])

    def test_an_in_step_pair_gets_no_band_for_it(self):
        self.assertNotIn("uploadAsNewCopy", self.out["inStepBand"])


if __name__ == "__main__":
    unittest.main()
