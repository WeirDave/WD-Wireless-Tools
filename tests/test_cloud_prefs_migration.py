"""Cloud Manager's merge rule and refresh interval live in one store.

They used to sit in localStorage while the Suite Settings page read and wrote
the same two values in settings.json, with nothing joining the two. The
Settings page therefore displayed a value that was not in force, and saving
there changed nothing at all -- a control that looked like it worked and did
not.

The move to server-side storage is only safe if the value already in this
browser survives it. The browser copy is what the machine was actually doing,
so it wins and is written through; the server default must not be allowed to
quietly overwrite a deliberate choice. A previous settings migration in this
repo dropped a field on the way across, which is why that case is pinned here
rather than left to review.

Driven through the real functions in Node, not by reading the source.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
SETTINGS_PY = ROOT / "tools" / "settings.py"

NODE_TIMEOUT_S = 120

# The block under test, plus a fake browser for the bits it reaches for.
NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
// liveMs() is declared up with the live-refresh timer rather than beside the
// rest of the preference code, so it has to be pulled in separately.
const block = slice('const MERGE_RULES', '\nfunction localFolders')
            + slice('function liveMs()', '\nlet liveTimer');

globalThis.store = {};
globalThis.localStorage = {
  getItem: (k) => (k in globalThis.store ? globalThis.store[k] : null),
  setItem: (k, v) => { globalThis.store[k] = String(v); },
  removeItem: (k) => { delete globalThis.store[k]; },
};

globalThis.saved = { cloud: {} };
globalThis.writes = [];
globalThis.writeFails = false;
globalThis.WD = {
  api: (action, body) => {
    if (action === 'settings/get') {
      return Promise.resolve({ ok: true, settings: { cloud: { ...globalThis.saved.cloud } } });
    }
    if (action === 'settings/update') {
      globalThis.writes.push(JSON.parse(JSON.stringify(body)));
      if (globalThis.writeFails) return Promise.resolve({ ok: false, error: 'nope' });
      Object.assign(globalThis.saved.cloud, body.patch.cloud);
      return Promise.resolve({ ok: true });
    }
    return Promise.resolve({ ok: true });
  },
};
globalThis.window = globalThis;

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
"""


def _js_string(text: str) -> str:
    return json.dumps(text)


def run_node(program: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["node", "-e", program, str(CLOUD_JS)],
                              capture_output=True, text=True,
                              timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"node did not finish within {NODE_TIMEOUT_S}s. That is a Node "
            f"startup timeout, not a failure of the code under test."
        ) from exc


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class CloudPrefsMigration(unittest.TestCase):

    def run_block(self, checks: str):
        program = NODE_PRELUDE + "eval(block + " + _js_string(checks) + ");"
        result = run_node(program)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_a_value_already_in_this_browser_survives_the_move(self):
        """The case the last settings migration got wrong."""
        self.run_block("""
          store['wd-merge-rule'] = 'skip';
          store['wd-live-ms'] = '120000';
          saved.cloud = { merge_rule: 'ask', live_interval_ms: 30000 };
          loadCloudPrefs().then(() => {
            check('browser merge rule must win over the server default',
                  mergeRule() === 'skip');
            check('browser interval must win over the server default',
                  liveMs() === 120000);
            check('the server must now hold the migrated merge rule',
                  saved.cloud.merge_rule === 'skip');
            check('the server must now hold the migrated interval',
                  saved.cloud.live_interval_ms === 120000);
            done();
          });
        """)

    def test_the_browser_copy_is_dropped_once_the_server_has_it(self):
        self.run_block("""
          store['wd-merge-rule'] = 'newer';
          store['wd-live-ms'] = '15000';
          saved.cloud = {};
          loadCloudPrefs().then(() => {
            check('the old merge-rule key must be gone',
                  store['wd-merge-rule'] === undefined);
            check('the old interval key must be gone',
                  store['wd-live-ms'] === undefined);
            done();
          });
        """)

    def test_a_failed_write_keeps_the_browser_copy(self):
        """Deleting before the write lands would lose the setting outright."""
        self.run_block("""
          store['wd-merge-rule'] = 'both';
          saved.cloud = { merge_rule: 'ask' };
          writeFails = true;
          loadCloudPrefs().then(() => {
            check('the browser copy must survive a failed write',
                  store['wd-merge-rule'] === 'both');
            check('the value in force is still the browser one',
                  mergeRule() === 'both');
            done();
          });
        """)

    def test_the_saved_value_is_used_when_the_browser_has_none(self):
        self.run_block("""
          store = {};
          saved.cloud = { merge_rule: 'skip', live_interval_ms: 60000 };
          loadCloudPrefs().then(() => {
            check('merge rule comes from the settings file', mergeRule() === 'skip');
            check('interval comes from the settings file', liveMs() === 60000);
            check('nothing needed writing', writes.length === 0);
            done();
          });
        """)

    def test_nothing_saved_anywhere_falls_back_to_the_shipped_defaults(self):
        self.run_block("""
          store = {};
          saved.cloud = {};
          loadCloudPrefs().then(() => {
            check('merge rule defaults to ask', mergeRule() === 'ask');
            check('interval defaults to 30s', liveMs() === 30000);
            done();
          });
        """)

    def test_a_nonsense_browser_value_does_not_win(self):
        self.run_block("""
          store['wd-merge-rule'] = 'banana';
          store['wd-live-ms'] = 'soon';
          saved.cloud = { merge_rule: 'newer', live_interval_ms: 60000 };
          loadCloudPrefs().then(() => {
            check('a junk rule falls back to the saved one', mergeRule() === 'newer');
            check('a junk interval falls back to the saved one', liveMs() === 60000);
            done();
          });
        """)

    def test_changing_the_rule_writes_it_to_the_settings_file(self):
        """The bug was that this only ever reached localStorage."""
        self.run_block("""
          store = {}; saved.cloud = {};
          setMergeRule('skip');
          setLiveMs(15000);
          setTimeout(() => {
            check('merge rule reached the settings file',
                  saved.cloud.merge_rule === 'skip');
            check('interval reached the settings file',
                  saved.cloud.live_interval_ms === 15000);
            check('nothing was written to the browser',
                  Object.keys(store).length === 0);
            done();
          }, 0);
        """)

    def test_an_invalid_rule_is_refused_rather_than_saved(self):
        self.run_block("""
          store = {}; saved.cloud = { merge_rule: 'ask' };
          setMergeRule('banana');
          setLiveMs(0);
          setTimeout(() => {
            check('an unknown rule is not written', saved.cloud.merge_rule === 'ask');
            check('a zero interval is not written',
                  saved.cloud.live_interval_ms === undefined);
            done();
          }, 0);
        """)


class OneStoreOnly(unittest.TestCase):
    """Source-level guards. These are the cheap version of the bug that shipped."""

    def test_cloud_js_no_longer_reads_or_writes_the_old_keys(self):
        source = CLOUD_JS.read_text(encoding="utf-8")
        for key in ("wd-merge-rule", "wd-live-ms"):
            # The migration constants naming them are fine; a get/set is not.
            for call in (f"getItem('{key}')", f"setItem('{key}'"):
                with self.subTest(key=key, call=call):
                    self.assertNotIn(call, source)

    def test_both_settings_are_declared_server_side(self):
        source = SETTINGS_PY.read_text(encoding="utf-8")
        self.assertIn('"merge_rule"', source)
        self.assertIn('"live_interval_ms"', source)


if __name__ == "__main__":
    unittest.main()
