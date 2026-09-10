"""Quick Walls preferences moved out of the browser, without resetting anyone.

Units, the default wall template and auto-apply were per-browser because Quick
Walls also ran hosted on GitHub Pages with no server to save to. Hosted mode is
retired, so all three are ordinary preferences in settings.json.

The move is only safe if the value already in the browser survives it. That
value is what the machine was actually using, so it wins over the saved default
and is written through; the local key is deleted only once the write succeeds.
A previous settings migration in this repo dropped a field on the way across,
which is why every branch of that is pinned here rather than left to review.

Driven through the real functions in Node, not by reading the source.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WALLS_JS = ROOT / "web" / "assets" / "js" / "walls.js"
SETTINGS_PY = ROOT / "tools" / "settings.py"

NODE_TIMEOUT_S = 120

NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
// detectDefaultUnits is the locale fallback wallUnits() drops back to, and the
// template getters live further down the file beside the template bar.
const block = slice('function detectDefaultUnits()', '/* Quick Walls preferences')
            + slice('const LEGACY_UNITS_KEY', '\nfunction mToDisplay')
            + slice('// Backed by settings.json; loaded once by loadWallsPrefs().', '\nlet _ekahauDefaults');

globalThis.store = {};
globalThis.localStorage = {
  getItem: (k) => (k in globalThis.store ? globalThis.store[k] : null),
  setItem: (k, v) => { globalThis.store[k] = String(v); },
  removeItem: (k) => { delete globalThis.store[k]; },
};

globalThis.saved = { walls: {} };
globalThis.writeFails = false;
globalThis.writes = [];
globalThis.WD = {
  api: (action, body) => {
    if (action === 'settings/get') {
      return Promise.resolve({ ok: true, settings: { walls: { ...globalThis.saved.walls } } });
    }
    if (action === 'settings/update') {
      globalThis.writes.push(JSON.parse(JSON.stringify(body)));
      if (globalThis.writeFails) return Promise.resolve({ ok: false });
      Object.assign(globalThis.saved.walls, body.patch.walls);
      return Promise.resolve({ ok: true });
    }
    return Promise.resolve({ ok: true });
  },
};
globalThis.window = globalThis;
globalThis.navigator = { language: 'en-GB' };   // metric, so an unset unit is visible
globalThis.syncUnitToggleUI = () => {};
globalThis.refreshTemplateBar = () => {};
globalThis.showToast = () => {};
globalThis.document = { getElementById: () => ({ checked: false }) };

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
        return subprocess.run(["node", "-e", program, str(WALLS_JS)],
                              capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"node did not finish within {NODE_TIMEOUT_S}s. That is a Node "
            f"startup timeout, not a failure of the code under test."
        ) from exc


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class WallsPrefsMigration(unittest.TestCase):

    def run_block(self, checks: str):
        program = NODE_PRELUDE + "eval(block + " + _js_string(checks) + ");"
        result = run_node(program)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).strip())

    def test_values_already_in_this_browser_survive_the_move(self):
        """The case the last settings migration got wrong."""
        self.run_block("""
          store['wd-walls-units'] = 'imperial';
          store['ekahau-default-template'] = JSON.stringify('WD Template');
          store['ekahau-auto-apply'] = 'true';
          saved.walls = {};
          loadWallsPrefs().then(() => {
            check('units must survive', wallUnits() === 'imperial');
            check('default template must survive', getDefaultTemplate() === 'WD Template');
            check('auto-apply must survive', getAutoApply() === true);
            check('units reached the settings file', saved.walls.units === 'imperial');
            check('template reached the settings file',
                  saved.walls.default_template === 'WD Template');
            check('auto-apply reached the settings file',
                  saved.walls.auto_apply_template === true);
            done();
          });
        """)

    def test_the_browser_copy_wins_over_a_different_saved_value(self):
        self.run_block("""
          store['wd-walls-units'] = 'imperial';
          saved.walls = { units: 'metric' };
          loadWallsPrefs().then(() => {
            check('the browser value is the one in force', wallUnits() === 'imperial');
            check('and it is written through', saved.walls.units === 'imperial');
            done();
          });
        """)

    def test_the_browser_copies_are_dropped_once_the_server_has_them(self):
        self.run_block("""
          store['wd-walls-units'] = 'metric';
          store['ekahau-auto-apply'] = 'true';
          saved.walls = {};
          loadWallsPrefs().then(() => {
            check('units key gone', store['wd-walls-units'] === undefined);
            check('auto-apply key gone', store['ekahau-auto-apply'] === undefined);
            done();
          });
        """)

    def test_a_failed_write_keeps_the_browser_copies(self):
        """Deleting before the write lands would lose the settings outright."""
        self.run_block("""
          store['wd-walls-units'] = 'imperial';
          saved.walls = {};
          writeFails = true;
          loadWallsPrefs().then(() => {
            check('the browser copy survives a failed write',
                  store['wd-walls-units'] === 'imperial');
            check('the value in force is still the browser one', wallUnits() === 'imperial');
            done();
          });
        """)

    def test_the_saved_value_is_used_when_the_browser_has_none(self):
        self.run_block("""
          store = {};
          saved.walls = { units: 'imperial', default_template: 'Site A',
                          auto_apply_template: true };
          loadWallsPrefs().then(() => {
            check('units from the settings file', wallUnits() === 'imperial');
            check('template from the settings file', getDefaultTemplate() === 'Site A');
            check('auto-apply from the settings file', getAutoApply() === true);
            check('nothing needed writing', writes.length === 0);
            done();
          });
        """)

    def test_nothing_saved_anywhere_falls_back_to_the_locale(self):
        # Asserted against detectDefaultUnits() rather than a hard-coded
        # 'metric': Node supplies its own navigator, so pinning a locale here
        # would test the host rather than the fallback.
        self.run_block("""
          store = {}; saved.walls = {};
          loadWallsPrefs().then(() => {
            check('units fall back to the locale default',
                  wallUnits() === detectDefaultUnits());
            check('and nothing was written for an unset unit',
                  saved.walls.units === undefined);
            check('no default template', getDefaultTemplate() === null);
            check('auto-apply off', getAutoApply() === false);
            done();
          });
        """)

    def test_the_old_template_name_is_carried_across(self):
        """'Recommended by WD' was renamed to 'WD Template'; the rename has to
        survive the move or a saved default silently stops matching."""
        self.run_block("""
          store['ekahau-default-template'] = JSON.stringify('Recommended by WD');
          saved.walls = {};
          loadWallsPrefs().then(() => {
            check('the old name maps to the new one',
                  getDefaultTemplate() === 'WD Template');
            check('and the new name is what gets saved',
                  saved.walls.default_template === 'WD Template');
            done();
          });
        """)

    def test_a_nonsense_browser_value_does_not_win(self):
        self.run_block("""
          store['wd-walls-units'] = 'furlongs';
          store['ekahau-default-template'] = 'not json';
          saved.walls = { units: 'imperial', default_template: 'Site A' };
          loadWallsPrefs().then(() => {
            check('junk units fall back to the saved value', wallUnits() === 'imperial');
            check('junk template falls back to the saved value',
                  getDefaultTemplate() === 'Site A');
            done();
          });
        """)

    def test_changing_a_preference_writes_it_to_the_settings_file(self):
        self.run_block("""
          store = {}; saved.walls = {};
          setLastTemplate('Site B');
          setTimeout(() => {
            check('template reached the settings file',
                  saved.walls.default_template === 'Site B');
            check('nothing was written to the browser',
                  Object.keys(store).length === 0);
            done();
          }, 0);
        """)


class HostedModeIsGone(unittest.TestCase):
    """Source-level guards. Hosted mode is what forced the two-store design."""

    def test_walls_js_has_no_hosted_template_store(self):
        source = WALLS_JS.read_text(encoding="utf-8")
        for marker in ("_hostedTplApi", "WD_HOSTED", "wd-hosted-templates"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, source)

    def test_walls_js_no_longer_reads_or_writes_the_retired_keys(self):
        source = WALLS_JS.read_text(encoding="utf-8")
        for key in ("wd-walls-units", "ekahau-default-template", "ekahau-auto-apply"):
            for call in (f"getItem('{key}')", f"setItem('{key}'"):
                with self.subTest(call=call):
                    self.assertNotIn(call, source)

    def test_the_three_preferences_are_declared_server_side(self):
        source = SETTINGS_PY.read_text(encoding="utf-8")
        for key in ('"units"', '"default_template"', '"auto_apply_template"'):
            with self.subTest(key=key):
                self.assertIn(key, source)


if __name__ == "__main__":
    unittest.main()
