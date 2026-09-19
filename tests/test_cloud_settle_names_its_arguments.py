"""The pair a finished action re-checks has to be the pair it just changed.

Every write in Cloud Manager ends by re-comparing the pair and redrawing the
row, so the row states the outcome of the thing he just did - "obviously I
shouldn't have to recheck twice - once to tell me what's wrong and another one
after I've done the action." `settlePair` is that mechanism, and it is reached
from the internal-name fix, from a push, and from a pull.

It sent its two arguments the wrong way round. `pyApi` maps positionally onto
`['path', 'cloudId', 'opId']`, so the cloud id arrived as `path` and the local
path arrived as `cloudId`; the server takes `(local_path, cloud_project_id)`
and `_assert_inside` refused a cloud UUID as a path. So the confirmation could
not succeed for anybody, on any row, and every action ended with a red toast
reading "Could not confirm the result: Local path is outside the configured
folder" - the folder the tool is configured with, blamed for a caller that
passed a UUID.

**This asserts the keys the server reads, not the order they were written in.**
The test that covered this before checked `calls[1][2]` - the third positional
argument - which is the local path only while the arguments are swapped. A
position is not a contract; `path` and `cloudId` are, because those are the
names `server.py` looks up. Asserting the position pinned the defect in place,
which is the same shape as pinning a sentence.

Every project, site and path here is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 60

CLOUD_ID = "3f2a9c14-7b6d-4e51-9a02-8c55d1e7b430"
LOCAL_PATH = "D:/Ekahau Projects/SITE1 Riverside/SITE1 Riverside Baseline.esx"

PROGRAM = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');

function cut(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}

globalThis.window = globalThis;
globalThis.document = { getElementById: () => null, querySelectorAll: () => [],
                        querySelector: () => null };
const WD = { esc: s => String(s == null ? '' : s) };
WD.escAttr = WD.esc;
WD.escJsStr = WD.esc;
globalThis.WD = WD;
function toast() {}
function renderRows() {}
function _clearStaleness() {}
const _compareResults = new Map();
const _rowBusy = new Map();
const _rowBusyTimers = new Map();
function _compareKey(c, l) {
  return String(c || '') + '\u0000' + String(l || '').replace(/\\/g, '/').toLowerCase();
}
function _setRowBusy() {}

/* The real request builder and the real mapping table, so the keys under test
   are the keys the server will be handed. */
eval(cut('const API_MAP = {', '\nconst _ops = new Map();'));

const sent = [];
globalThis.fetch = async (url, opts) => {
  sent.push({ url, body: JSON.parse(opts.body) });
  return { ok: true, json: async () => ({ designDiffers: false, nameState: 'ok' }) };
};

/* The function under test, taken whole out of the shipped file. */
eval(cut('async function settlePair(', '\nfunction checkRealDifference('));

(async () => {
  await settlePair(process.argv[2], process.argv[3], { quiet: true });
  process.stdout.write(JSON.stringify({ sent }));
})();
"""


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class SettlePairSendsThePairItWasGiven(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        #: `node -e`, so argv[1] is the first argument we pass rather than a
        #: script path - and so nothing is written into `tests/`, where two
        #: concurrent suite runs would collide over the same filename.
        out = subprocess.run(
            ["node", "-e", PROGRAM, str(CLOUD_JS), CLOUD_ID, LOCAL_PATH],
            capture_output=True, text=True, encoding="utf-8",
            timeout=NODE_TIMEOUT_S,
        )
        if out.returncode != 0:
            raise AssertionError("probe failed:\n" + out.stderr)
        cls.sent = json.loads(out.stdout)["sent"]

    def test_it_asks_the_server_once(self):
        self.assertEqual(1, len(self.sent), self.sent)
        self.assertTrue(self.sent[0]["url"].endswith("/api/cloud/compare_with_cloud"),
                        self.sent[0]["url"])

    def test_the_local_file_is_sent_as_the_path(self):
        """`server.py` reads `d["path"]` and hands it to `compare_with_cloud`
        as `local_path`, which `_assert_inside` checks against the configured
        folder. A cloud id here is refused, and the refusal names his folder."""
        self.assertEqual(LOCAL_PATH, self.sent[0]["body"].get("path"))

    def test_the_cloud_project_is_sent_as_the_cloud_id(self):
        self.assertEqual(CLOUD_ID, self.sent[0]["body"].get("cloudId"))


if __name__ == "__main__":
    unittest.main()
