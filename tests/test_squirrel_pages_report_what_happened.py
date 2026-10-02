"""Squirrel's pages say what the server did - run, not read.

The real functions are sliced out of ``organizer.js`` and ``rename.js`` and run
in Node against recording stubs, with the real ``WD.esc``/``WD.escAttr``.
Where the input is a server answer, it comes from the real server code run
against an invented folder tree, not from a hand-written dict.

* Organize's result screen printed ``m.target + '/'``, so a folder that could
  not be organized at all would have read "null/".
* Preview now names the folders the scan could not read.
* Rename's Undo picked its kind from the tab on screen, so renaming folders,
  switching to Rules and pressing Undo reverted an older bulk rename; it now
  undoes the operation it just ran, in the folder it ran in, and goes away
  when the tab or folder changes.
* Undo's toast says what it skipped instead of only "Reverted N".
* A folder picker that could not open now says so.
* The Rules tab does not send a row the preview marked as a collision.

Folder and file names are invented.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools.folder_organizer as organizer_module
from tools.folder_organizer import FolderOrganizer

ROOT = Path(__file__).resolve().parent.parent
SHARED_JS = ROOT / "web" / "assets" / "js" / "wd-shared.js"
ORGANIZER_JS = ROOT / "web" / "assets" / "js" / "organizer.js"
RENAME_JS = ROOT / "web" / "assets" / "js" / "rename.js"
NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const shared = fs.readFileSync(process.argv[1], 'utf8');
const src = fs.readFileSync(process.argv[2], 'utf8');
const input = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));

function between(text, from, to) {
  const a = text.indexOf(from);
  if (a < 0) throw new Error('not found: ' + from);
  const b = text.indexOf(to, a);
  if (b < 0) throw new Error('no end for: ' + from);
  return text.slice(a, b);
}
// Brace-counted, so whatever sits between two functions is not swallowed.
function fn(sig) {
  const a = src.indexOf(sig);
  if (a < 0) throw new Error(sig + ' moved');
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}

const WD = {};
eval(between(shared, '  WD.esc = function', '  WD.applyVersions'));
globalThis.WD = WD;
function esc(s) { return WD.esc(s); }
function escAttr(s) { return WD.escAttr(s); }

const els = {};
function el(id) {
  if (!els[id]) {
    els[id] = { id, innerHTML: '', textContent: '', hidden: false,
                disabled: false, value: '', title: '',
                classList: { add() {}, remove() {}, toggle() {} } };
  }
  return els[id];
}
// WD.esc writes textContent and reads innerHTML; a browser escapes &, < and >
// on the way, which is all this stand-in does.
function textDiv() {
  let t = '';
  return {
    set textContent(v) { t = String(v); },
    get innerHTML() {
      return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },
  };
}
globalThis.document = {
  createElement: textDiv,
  getElementById: el,
  querySelector: () => null,
  querySelectorAll: () => [],
};
const toasts = [];
function toast(msg, kind) { toasts.push({ msg: String(msg), kind: kind || '' }); }
globalThis.localStorage = { setItem() {}, getItem() { return null; } };
"""


def _node(script: str, src: Path, data) -> dict:
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    with tempfile.TemporaryDirectory() as tmp:
        data_file = Path(tmp) / "input.json"
        data_file.write_text(json.dumps(data), encoding="utf-8")
        r = subprocess.run(
            [node, "-e", PRELUDE + script, str(SHARED_JS), str(src),
             str(data_file)],
            capture_output=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout.strip().splitlines()[-1])


class _ServerAnswers(unittest.TestCase):
    """Real scan/execute answers over an invented tree with one bad folder."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.root = base / "projects"
        for site, f in (("Alpha Site", "a.png"), ("Zulu Site", "z.png")):
            (self.root / site).mkdir(parents=True)
            (self.root / site / f).write_text(f)
        state = base / "state"
        self.patchers = [
            patch.object(organizer_module, "CONFIG_DIR", state),
            patch.object(organizer_module, "ORGANIZER_CONFIG",
                         state / "organizer_config.json"),
            patch.object(organizer_module, "UNDO_DIR", state / "undo"),
        ]
        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()
        self.temp.cleanup()


ORGANIZER_STUBS = r"""
let scanData = null, cachedConfig = {}, undoAvailable = false, undoCount = 0;
let _lastChecked = null;
function showScreen() {}
function advancedOn() { return false; }
function applyAdvancedUI() {}
function applyDetailsUI() {}
function renderSuggestBanner() { return ''; }
function renderDupSection() { return ''; }
eval(fn('function destinationList(cfg) {'));
eval(fn('function destinationCssClass(key) {'));
eval(fn('function subfolderDisplayOrder(cfg) {'));
eval(fn('function esxBadges(s) {'));
eval(fn('function fmtSize(bytes) {'));
eval(fn('function unreadableNotice(list) {'));
"""


class OrganizeResultsNameAFolderThatFailed(_ServerAnswers):

    def test_a_whole_folder_error_reads_as_one(self):
        real_mkdir = Path.mkdir

        def refusing(path, *a, **k):
            if path.parent.name == "Zulu Site":
                raise PermissionError(13, "Access is denied", str(path))
            return real_mkdir(path, *a, **k)

        with patch.object(Path, "mkdir", refusing):
            answer = FolderOrganizer().execute(str(self.root), [], [])
        out = _node(ORGANIZER_STUBS + r"""
eval(fn('function renderResults(r) {'));
renderResults(input);
console.log(JSON.stringify({ html: el('resultScreen').innerHTML, toasts }));
""", ORGANIZER_JS, answer)
        html = out["html"]
        zulu = html[html.index("Zulu Site"):]
        self.assertNotIn("null/", html)
        self.assertNotIn("<td>/", html)
        self.assertIn("All files in this folder", zulu)
        self.assertIn("access to it was denied", zulu)
        self.assertIn("images/", html[html.index("Alpha Site"):html.index("Zulu Site")])


class PreviewNamesTheFoldersItSkipped(_ServerAnswers):

    def test_an_unreadable_folder_is_named_with_its_reason(self):
        real = Path.iterdir

        def iterdir(path):
            if path.name == "Zulu Site":
                raise PermissionError(13, "Access is denied", str(path))
            return real(path)

        with patch.object(Path, "iterdir", iterdir):
            answer = FolderOrganizer().scan(str(self.root))
        out = _node(ORGANIZER_STUBS + r"""
eval(fn('function renderPreview() {'));
scanData = input;
renderPreview();
console.log(JSON.stringify({ html: el('siteList').innerHTML }));
""", ORGANIZER_JS, answer)
        html = out["html"]
        self.assertIn("1 folder was skipped because it could not be read", html)
        self.assertIn("<b>Zulu Site</b> - access to it was denied", html)
        self.assertIn("Alpha Site", html)


RENAME_STUBS = r"""
let _renameState = { root: '/invented/one', tab: 'folders', items: [] };
const calls = [];
let replies = {};
async function renameApi(action, body) {
  calls.push({ action, body: body || {} });
  const r = replies[action];
  return typeof r === 'function' ? r(body) : (r || { ok: true });
}
WD.api = async () => ({ ok: true });
function _renderManualFields() {}
function updateRenamePreview() {}
async function _runRenamePreview() {}
function _updateRenameExample() {}
function _getRuleValues() { return {}; }
eval(fn('function _forgetRenameUndo() {'));
eval(fn('function switchRenameTab(tab) {'));
eval(fn('async function pickRenameRoot() {'));
eval(fn('async function doRename() {'));
eval(fn('async function renameUndo() {'));
const undoBtn = el('renameUndoBtn');
undoBtn.hidden = true;
async function folderRenameDone() {
  _renameState.tab = 'folders';
  _renameState.items = [{ status: 'rename', current: 'Alpha Site', new_name: 'Alpha Site 2' }];
  replies.execute_folder_rename = { ok: true, renamed: 1, errors: [] };
  await doRename();
}
function undoCalls() { return calls.filter(c => c.action === 'undo_last').map(c => c.body); }
"""


class _RenamePage(unittest.TestCase):

    def run_js(self, body: str) -> dict:
        return _node(RENAME_STUBS + "(async () => {" + body
                     + "})().catch(e => { console.error(e.stack || e); process.exit(1); });",
                     RENAME_JS, {})


class RenameUndoRevertsWhatItJustDid(_RenamePage):

    def test_undo_sends_the_operation_and_folder_it_ran_in(self):
        out = self.run_js(r"""
await folderRenameDone();
const shown = !undoBtn.hidden;
_renameState.tab = 'rules';            // nothing switches the tab here
await renameUndo();
console.log(JSON.stringify({ shown, undo: undoCalls() }));
""")
        self.assertTrue(out["shown"])
        self.assertEqual(out["undo"], [{"type": "folders",
                                        "root": "/invented/one"}])

    def test_switching_tab_takes_the_undo_away(self):
        out = self.run_js(r"""
await folderRenameDone();
switchRenameTab('rules');
const hidden = undoBtn.hidden;
await renameUndo();
console.log(JSON.stringify({ hidden, undo: undoCalls() }));
""")
        self.assertTrue(out["hidden"])
        self.assertEqual(out["undo"], [],
                         "an undo after a tab switch must not revert anything")

    def test_picking_another_folder_takes_the_undo_away(self):
        out = self.run_js(r"""
await folderRenameDone();
replies.pick_folder = { ok: true, path: '/invented/two' };
await pickRenameRoot();
console.log(JSON.stringify({ hidden: undoBtn.hidden, root: _renameState.root }));
""")
        self.assertTrue(out["hidden"])
        self.assertEqual(out["root"], "/invented/two")

    def test_the_toast_says_what_was_left_and_undo_stays_offered(self):
        out = self.run_js(r"""
await folderRenameDone();
replies.undo_last = { ok: true, reverted: 1,
  skipped: ['Alpha Site exists again, so Alpha Site 2 was left as it is'],
  errors: [], remaining: 1 };
await renameUndo();
console.log(JSON.stringify({ toasts, hidden: undoBtn.hidden }));
""")
        last = out["toasts"][-1]
        self.assertIn("Reverted 1 item", last["msg"])
        self.assertIn("1 left as they are", last["msg"])
        self.assertIn("Alpha Site exists again", last["msg"])
        self.assertFalse(out["hidden"], "what is left can be retried")

    def test_a_complete_undo_takes_the_button_away(self):
        out = self.run_js(r"""
await folderRenameDone();
replies.undo_last = { ok: true, reverted: 1, skipped: [], errors: [], remaining: 0 };
await renameUndo();
console.log(JSON.stringify({ toasts, hidden: undoBtn.hidden }));
""")
        self.assertTrue(out["hidden"])
        self.assertEqual(out["toasts"][-1]["msg"], "Reverted 1 item")


class RulesTabSendsOnlyWhatCanRename(_RenamePage):

    def test_a_collision_row_is_not_sent(self):
        out = self.run_js(r"""
_renameState.tab = 'rules';
_renameState.items = [
  { path: '/invented/one/a b.png', new_name: 'a_b.png', status: 'rename' },
  { path: '/invented/one/c d.png', new_name: 'c_d.png', status: 'collision' },
];
replies.execute_bulk_rename = { ok: true, renamed: 1, skipped: 0 };
await doRename();
await renameUndo();
console.log(JSON.stringify({
  sent: calls.filter(c => c.action === 'execute_bulk_rename').map(c => c.body),
  undo: undoCalls() }));
""")
        self.assertEqual(out["sent"][0]["root"], "/invented/one")
        self.assertEqual([i["new_name"] for i in out["sent"][0]["items"]],
                         ["a_b.png"])
        self.assertEqual(out["undo"], [{"type": "bulk", "root": "/invented/one"}])


class TheFolderPickerFailureIsShown(_RenamePage):

    def test_unavailable_is_toasted_and_cancel_is_not(self):
        out = self.run_js(r"""
replies.pick_folder = { ok: false, code: 'picker_unavailable',
  error: 'Could not open the folder picker — it closed immediately.' };
await pickRenameRoot();
const afterBroken = toasts.length;
replies.pick_folder = { ok: false, code: 'cancelled', error: 'No folder selected' };
await pickRenameRoot();
console.log(JSON.stringify({ toasts, afterBroken, root: _renameState.root }));
""")
        self.assertEqual(out["afterBroken"], 1)
        self.assertIn("closed immediately", out["toasts"][0]["msg"])
        self.assertEqual(len(out["toasts"]), 1, "a cancel stays silent")
        self.assertEqual(out["root"], "/invented/one")


if __name__ == "__main__":
    unittest.main()
