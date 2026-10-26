""""Fix names inside files" on a selection leaves no row marked busy.

`bulkFixInternalNames` called `fixInternalName(localPath, cloudName, label)` -
three arguments - and the function takes the project id fourth. Without it the
row was marked under a key with no project id, and every path that clears the
mark was guarded by `if (cloudId)`. So each file in the selection left a mark
that nothing cleared, and 30 seconds later the ceiling timer fired a "That is
taking longer than expected" error toast for work that had finished, one per
file.

This runs the real `fixInternalName`, `bulkFixInternalNames`, `_setRowBusy` and
`settlePair`, with a queue that marks the row at the start of the work exactly
as `opEnqueue` does, and asks what is left over once every operation has
settled: marks still set, and timers still armed (a timer is a toast waiting to
happen). Every path and name is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"

PROGRAM = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const mode = process.argv[2];

function cut(marker) {
  const a = src.indexOf(marker);
  if (a < 0) throw new Error('moved: ' + marker);
  let b = src.indexOf('{', a), depth = 0;
  for (; b < src.length; b++) {
    if (src[b] === '{') depth++;
    else if (src[b] === '}' && --depth === 0) { b++; break; }
  }
  return src.slice(a, b);
}

// Armed timers, so a mark that is never cleared shows up as a pending toast.
const armed = new Map(); let nextTimer = 1;
globalThis.setTimeout = (fn) => { const id = nextTimer++; armed.set(id, fn); return id; };
globalThis.clearTimeout = (id) => { armed.delete(id); };

const toasts = [];
function toast(m, kind) { toasts.push([m, kind || '']); }
function renderRows() {}
function _scheduleOpRefresh() {}
function clearSelection() {}
const _compareResults = new Map();
function _compareKey(c, l) { return String(c) + '\u0000' + String(l).toLowerCase(); }
const _answeredHere = new Set();
function _pairMtimes() { return null; }
function _clearStaleness() {}

let serverFails = mode === 'server-error';
async function pyApi(name) {
  if (name === 'set_internal_project_name') {
    return serverFails ? { error: 'the file is read-only' } : { ok: true };
  }
  return {};   // compare_with_cloud
}

// The queue, as far as these functions can tell: mark the row when the work
// starts (spec.busyRow), run it, hand back its promise.
const pending = [];
function opEnqueue(spec) {
  const promise = (async () => {
    await null;
    if (spec.busyRow) {
      _setRowBusy(spec.busyRow.cloudId, spec.busyRow.localPath, spec.busyRow.label);
    }
    const r = await spec.run('op-1', { aborted: false });
    if (r && r.error) throw new Error(r.error);
    return r;
  })();
  pending.push(promise.catch(() => {}));
  return { promise };
}

const ROWS = [
  { kind: 'pair', cloudId: 'c-1', cloudName: 'Invented One', localName: 'one',
    localPath: 'C:/invented/one.esx' },
  { kind: 'pair', cloudId: 'c-2', cloudName: 'Invented Two', localName: 'two',
    localPath: 'C:/invented/two.esx' },
  { kind: 'pair', cloudId: 'c-3', cloudName: 'Invented Three', localName: 'three',
    localPath: 'C:/invented/three.esx' },
];
function selectedSyncItems() { return ROWS; }

eval([
  'const _rowBusy = new Map();',
  cut('function _rowKey'),
  'const ROW_BUSY_CEILING_MS = 30000; const _rowBusyTimers = new Map();',
  cut('function _setRowBusy'),
  cut('async function settlePair'),
  cut('function fixInternalName'),
  cut('function bulkFixInternalNames'),
  'globalThis.__t = { fixInternalName, bulkFixInternalNames, busy: () => [..._rowBusy.keys()] };',
].join('\n'));

(async () => {
  if (mode === 'single-without-a-project-id') {
    __t.fixInternalName('C:/invented/solo.esx', 'Invented Solo', 'solo');
  } else {
    __t.bulkFixInternalNames();
  }
  // Let every queued operation, and what follows it, settle.
  for (let i = 0; i < 5; i++) {
    await Promise.all(pending);
    await new Promise(r => setImmediate(r));
  }
  console.log(JSON.stringify({
    marksLeft: __t.busy().length,
    timersLeft: armed.size,
    errorToasts: toasts.filter(t => t[1] === 'error').length,
  }));
})();
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class BulkFixNamesLeavesNoRowMarkedTests(unittest.TestCase):

    def run_mode(self, mode):
        r = subprocess.run(["node", "-e", PROGRAM, str(CLOUD_JS), mode],
                           capture_output=True, encoding="utf-8", timeout=60)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_selection_that_succeeds_leaves_nothing_marked(self):
        out = self.run_mode("success")
        self.assertEqual({"marksLeft": 0, "timersLeft": 0, "errorToasts": 0}, out)

    def test_a_selection_where_every_file_fails_leaves_nothing_marked(self):
        out = self.run_mode("server-error")
        self.assertEqual(0, out["marksLeft"])
        self.assertEqual(0, out["timersLeft"])

    def test_a_row_with_no_project_id_is_cleared_as_well(self):
        out = self.run_mode("single-without-a-project-id")
        self.assertEqual(0, out["marksLeft"])
        self.assertEqual(0, out["timersLeft"])


if __name__ == "__main__":
    unittest.main()
