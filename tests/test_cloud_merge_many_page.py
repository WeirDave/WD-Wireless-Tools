"""The bulk merge as the page drives it: the handlers, sliced out and run.

``test_cloud_merge_many`` settles what the server does with real files. This is
the other half - whether the page ever reaches it, and with what. A control can
render perfectly and be inert; that is how the `Local -> Cloud` button shipped,
and it is why a substring assertion is not evidence.

The argument worth watching is the action on a *cross-source* clash. "Keep
newer" cannot compare against a file that has not moved yet, so guessing there
would silently drop one of two copies - the one outcome a merge must never
produce on a comparison it could not make.

Every folder and site name here is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
CLOUD_HTML = ROOT / "web" / "cloud.html"

NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
globalThis.window = globalThis;

const e = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const a = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/'/g, '&#39;').replace(/"/g, '&quot;')
  .replace(/</g, '&lt;').replace(/>/g, '&gt;');
const np = s => String(s == null ? '' : s).replace(/\\/g, '/');
const p = s => a(np(s));
globalThis.e = e; globalThis.a = a; globalThis.np = np; globalThis.p = p;

/* ── what the sliced handlers reach for ─────────────────────────────────── */
globalThis.calls = [];
globalThis.toasts = [];
globalThis.queued = [];
globalThis.EXEC_RESULT = { ok: true, moved: 0, results: [] };
globalThis.FOLDERS = [];
globalThis.destHtml = '';
globalThis.summaryHtml = '';

async function pyApi(method, ...args) {
  calls.push([method, ...args]);
  if (method === 'merge_preview_many') {
    return { sources: [], refused: [], nClean: 0, nConflicts: 0, nCrossSource: 0 };
  }
  if (method === 'merge_execute_many') return EXEC_RESULT;
  return { ok: true };
}
function toast(msg) { toasts.push(String(msg)); }
function opEnqueue(op) { queued.push(op); }
function refreshData() {}
function _scheduleOpRefresh() {}
function startDelete(kind, path, name) { queued.push({ title: 'delete ' + name }); }
function closeModal() {}
function showModal() {}
function localFolders() { return FOLDERS; }
function localByPath(p) { return FOLDERS.find(f => f.path === p) || null; }
function mergeRule() { return 'ask'; }
function setMergeRule() {}
function _fuzzySim() { return 0; }
function _extractSiteCode() { return ''; }
function mtimeCmp() { return 'times'; }
globalThis.selected = new Set();
globalThis.rowData = {};

/* A DOM just big enough for these handlers: the elements they write to, and
   the checkbox list they read the ticks back out of. */
const boxes = [];
const els = {
  mergeTitle: {}, mergeSummary: {}, mergeConflictWrap: { style: {} },
  mergeBtn: {}, mergeFileList: {}, mergeDestSearch: { value: '' },
  mergeDestList: {}, mergeDestTitle: {}, mergeRemember: { checked: false },
  mergeDeleteSrc: { checked: true },
};
globalThis.document = {
  getElementById: (id) => els[id] || null,
  querySelectorAll: (sel) => {
    if (sel.indexOf('mfile-chk') !== -1) return boxes;
    if (sel.indexOf('mrule') !== -1) return [];
    return [];
  },
  querySelector: (sel) => {
    if (sel.indexOf('mrule') !== -1) return { value: globalThis.RULE || 'newer' };
    return null;
  },
};
Object.defineProperty(els.mergeFileList, 'innerHTML', {
  get() { return this._h || ''; },
  set(h) {
    this._h = h;
    // Rebuild the tick list from the markup the handler just wrote, so the
    // ticks under test are the ones it really rendered.
    boxes.length = 0;
    const re = /data-s="(\d+)" data-i="(\d+)"/g;
    let m;
    while ((m = re.exec(h))) {
      boxes.push({ checked: true, dataset: { s: m[1], i: m[2] } });
    }
  },
});
Object.defineProperty(els.mergeSummary, 'innerHTML', {
  get() { return globalThis.summaryHtml; },
  set(h) { globalThis.summaryHtml = h; },
});
Object.defineProperty(els.mergeDestList, 'innerHTML', {
  get() { return globalThis.destHtml; },
  set(h) { globalThis.destHtml = h; },
});

function setRule(r) { globalThis.RULE = r; }
function setPreview(prev) {
  globalThis.mergeState = {
    srcs: (prev.sources || []).map(s => ({ path: s.srcPath, name: s.srcName })),
    srcPath: (prev.sources[0] || {}).srcPath,
    srcName: (prev.sources[0] || {}).srcName,
    dstPath: 'D', dstName: 'Destination',
    preview: prev,
  };
  showMergeModal(prev);
  calls.length = 0;
}
function untick(si, i) {
  boxes.forEach(b => {
    if (b.dataset.s === String(si) && b.dataset.i === String(i)) b.checked = false;
  });
}
globalThis.setRule = setRule;
globalThis.setPreview = setPreview;
globalThis.untick = untick;

// The real handlers, exactly as shipped.
// Ends at closeMainMenu: `toggleMainMenu` was a two-line wrapper around
// WD.toggleMenu and went with the hamburger in v2.170.0.
eval(slice('function startMerge(path, name)', '\nfunction closeMainMenu('));

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function eq(what, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) failures.push(what + '\n     got:  ' + g + '\n     want: ' + w);
}
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ThePageBuildsTheRequestTests(unittest.TestCase):

    def run_checks(self, checks: str):
        body = "(async () => {\n" + checks + "\n})().catch(err => {"
        body += " console.error(err && err.stack || err); process.exit(1); });"
        program = PRELUDE + "eval(" + json.dumps(body) + ");"
        try:
            # encoding is explicit: the labels carry arrows and a middle dot,
            # and decoding with the locale codec reads them as mojibake on
            # Windows and intact in CI - the inversion that wastes most time.
            proc = subprocess.run(["node", "-e", program, str(CLOUD_JS)],
                                  capture_output=True, text=True,
                                  encoding="utf-8", timeout=NODE_TIMEOUT_S)
        except subprocess.TimeoutExpired as exc:
            raise AssertionError("node did not finish") from exc
        if proc.returncode != 0:
            self.fail((proc.stderr or proc.stdout or "node failed").strip())

    def test_the_preview_asks_for_every_selected_folder(self):
        self.run_checks(r"""
          mergeState = { srcs: [{ path: 'A', name: 'A' }, { path: 'B', name: 'B' }],
                         dstPath: 'D' };
          await runMergePreview();
          eq('one call', calls.length, 1);
          eq('to the bulk preview', calls[0][0], 'merge_preview_many');
          eq('with both folders', calls[0][1], ['A', 'B']);
          eq('and the destination', calls[0][2], 'D');
          done();
        """)

    def test_one_folder_goes_down_the_same_path(self):
        """The single merge is the bulk merge with one source in it.

        Two implementations of the preview, the conflict rules and the cleanup
        would mean the half he uses less is the half that drifts.
        """
        self.run_checks(r"""
          mergeState = { srcs: [{ path: 'A', name: 'A' }], dstPath: 'D' };
          await runMergePreview();
          eq('still the bulk call', calls[0][0], 'merge_preview_many');
          eq('with one folder', calls[0][1], ['A']);
          done();
        """)

    def test_a_cross_source_clash_keeps_both_under_the_keep_newer_rule(self):
        """There is no file to compare against yet - the other copy has not
        moved. Dropping one on a comparison that could not be made is the one
        outcome a merge must never produce."""
        self.run_checks(r"""
          setPreview({
            sources: [
              { srcPath: 'A', srcName: 'A', files: [{ rel: 'r.pdf', conflict: false }] },
              { srcPath: 'B', srcName: 'B',
                files: [{ rel: 'r.pdf', conflict: true, fromSource: 'A', newer: 'unknown' }] },
            ],
            nClean: 1, nConflicts: 1, nCrossSource: 1, refused: [],
          });
          setRule('newer');
          await confirmMerge();
          const call = calls.find(c => c[0] === 'merge_execute_many');
          check('the bulk execute was called', !!call);
          eq('two sources', call[1].length, 2);
          eq('the first moves', call[1][0].ops[0].action, 'move');
          eq('and the clash keeps both', call[1][1].ops[0].action, 'keepboth');
          done();
        """)

    def test_unticking_a_file_only_affects_its_own_source(self):
        """One flat index across several folders unticks the wrong file."""
        self.run_checks(r"""
          setPreview({
            sources: [
              { srcPath: 'A', srcName: 'A', files: [{ rel: 'x', conflict: false }] },
              { srcPath: 'B', srcName: 'B', files: [{ rel: 'y', conflict: false }] },
            ],
            nClean: 2, nConflicts: 0, nCrossSource: 0, refused: [],
          });
          untick(1, 0);
          await confirmMerge();
          const call = calls.find(c => c[0] === 'merge_execute_many');
          eq('the first folder still moves', call[1][0].ops[0].action, 'move');
          eq('the second is skipped', call[1][1].ops[0].action, 'skip');
          done();
        """)

    def test_an_ordinary_conflict_still_follows_the_chosen_rule(self):
        self.run_checks(r"""
          setPreview({
            sources: [{ srcPath: 'A', srcName: 'A',
                        files: [{ rel: 'x', conflict: true, newer: 'src' }] }],
            nClean: 0, nConflicts: 1, nCrossSource: 0, refused: [],
          });
          setRule('newer');
          await confirmMerge();
          let call = calls.find(c => c[0] === 'merge_execute_many');
          eq('incoming is newer, so it overwrites', call[1][0].ops[0].action, 'overwrite');

          calls.length = 0;
          setPreview({
            sources: [{ srcPath: 'A', srcName: 'A',
                        files: [{ rel: 'x', conflict: true, newer: 'src' }] }],
            nClean: 0, nConflicts: 1, nCrossSource: 0, refused: [],
          });
          setRule('skip');
          await confirmMerge();
          call = calls.find(c => c[0] === 'merge_execute_many');
          eq('skip means skip', call[1][0].ops[0].action, 'skip');
          done();
        """)

    def test_the_destination_picker_excludes_every_source(self):
        """Offering a source as the destination produces a merge the server
        refuses - a control that cannot work, offered anyway."""
        self.run_checks(r"""
          mergeState = { srcs: [{ path: 'A', name: 'Alpha' }, { path: 'B', name: 'Beta' }] };
          FOLDERS.length = 0;
          FOLDERS.push({ path: 'A', name: 'Alpha' }, { path: 'B', name: 'Beta' },
                       { path: 'C', name: 'Gamma' });
          renderMergeDests();
          check('Alpha is not offered', destHtml.indexOf('Alpha') === -1);
          check('Beta is not offered', destHtml.indexOf('Beta') === -1);
          check('Gamma is offered', destHtml.indexOf('Gamma') !== -1);
          done();
        """)

    def test_a_folder_that_cannot_be_merged_is_named_on_the_page(self):
        """Selecting eight and merging seven, silently, is how one gets left
        behind and nobody notices until they go looking for it."""
        self.run_checks(r"""
          mergeState = { dstName: 'Destination' };
          showMergeModal({
            sources: [{ srcPath: 'A', srcName: 'A', files: [{ rel: 'x', conflict: false }] }],
            refused: [{ name: 'SITE9 Nowhere', reason: 'Source folder not found' }],
            nClean: 1, nConflicts: 0, nCrossSource: 0,
          });
          check('it is named: ' + summaryHtml,
                summaryHtml.indexOf('SITE9 Nowhere') !== -1);
          check('with the reason', summaryHtml.indexOf('not found') !== -1);
          done();
        """)

    def test_the_summary_explains_a_cross_source_clash_in_words(self):
        self.run_checks(r"""
          mergeState = { dstName: 'Destination' };
          showMergeModal({
            sources: [{ srcPath: 'A', srcName: 'A', files: [{ rel: 'x', conflict: false }] },
                      { srcPath: 'B', srcName: 'B',
                        files: [{ rel: 'x', conflict: true, fromSource: 'A' }] }],
            refused: [], nClean: 1, nConflicts: 1, nCrossSource: 1,
          });
          check('it says what a cross-source clash is: ' + summaryHtml,
                /same file/.test(summaryHtml)
                && /nothing is in the destination yet/.test(summaryHtml));
          done();
        """)

    def test_the_row_says_which_folder_a_clash_is_with(self):
        self.run_checks(r"""
          mergeState = { dstName: 'Destination' };
          showMergeModal({
            sources: [{ srcPath: 'A', srcName: 'SITE9 East',
                        files: [{ rel: 'x', conflict: false }] },
                      { srcPath: 'B', srcName: 'SITE9 West',
                        files: [{ rel: 'x', conflict: true, fromSource: 'SITE9 East' }] }],
            refused: [], nClean: 1, nConflicts: 1, nCrossSource: 1,
          });
          const h = document.getElementById('mergeFileList').innerHTML;
          check('the other folder is named on the row: ' + h,
                h.indexOf('SITE9 East') !== -1 && /moves first/.test(h));
          done();
        """)

    def test_every_emptied_folder_is_offered_for_cleanup_not_just_the_first(self):
        self.run_checks(r"""
          setPreview({
            sources: [{ srcPath: 'A', srcName: 'A', files: [{ rel: 'x', conflict: false }] },
                      { srcPath: 'B', srcName: 'B', files: [{ rel: 'y', conflict: false }] }],
            nClean: 2, nConflicts: 0, nCrossSource: 0, refused: [],
          });
          queued.length = 0;
          EXEC_RESULT = { ok: true, moved: 2, results: [
            { srcPath: 'A', srcName: 'A', srcEmpty: true },
            { srcPath: 'B', srcName: 'B', srcEmpty: true },
          ] };
          await confirmMerge();
          eq('both are queued for cleanup', queued.length, 2);
          check('and each is named',
                queued.every(q => /"A"|"B"/.test(q.title)));
          done();
        """)

    def test_a_failed_folder_is_named_in_the_result(self):
        """"3 errors" over eight folders leaves him to work out which three,
        and the answer is nowhere else on screen."""
        self.run_checks(r"""
          setPreview({
            sources: [{ srcPath: 'A', srcName: 'A', files: [{ rel: 'x', conflict: false }] }],
            nClean: 1, nConflicts: 0, nCrossSource: 0, refused: [],
          });
          toasts.length = 0;
          EXEC_RESULT = { ok: true, moved: 0, results: [
            { srcPath: 'A', srcName: 'SITE9 East', error: 'Folder not found' },
          ] };
          await confirmMerge();
          check('the result names it: ' + toasts.join(' | '),
                toasts.some(t => t.indexOf('SITE9 East') !== -1));
          done();
        """)

    def test_only_local_folders_are_collected_from_a_selection(self):
        """A cloud project and a loose .esx are not folders to merge."""
        self.run_checks(r"""
          rowData['a'] = { kind: 'local', path: 'A', name: 'A', isDir: true };
          rowData['b'] = { kind: 'local', path: 'B.esx', name: 'B', isDir: false };
          rowData['c'] = { kind: 'cloud', id: 'c1', name: 'C' };
          selected.add('a'); selected.add('b'); selected.add('c');
          FOLDERS.length = 0;
          bulkMergeFolders();
          eq('only the folder', mergeState.srcs.map(s => s.path), ['A']);
          done();
        """)

    def test_nothing_selected_says_so_rather_than_opening_an_empty_picker(self):
        self.run_checks(r"""
          selected.clear();
          toasts.length = 0;
          bulkMergeFolders();
          check('it says what to do: ' + toasts.join(' | '),
                toasts.some(t => /Tick the local folders/.test(t)));
          done();
        """)


class TheControlIsOfferedTests(unittest.TestCase):
    """A handler nothing calls is a handler nobody can reach.

    The button is taken off the parsed page rather than matched as text, and
    its ``onclick`` is executed: a label and a handler that belong to two
    different buttons satisfy every substring check and still leave the
    control inert.
    """

    def setUp(self):
        from tests.test_cloud_external_override import buttons_on
        self.buttons = buttons_on(CLOUD_HTML)

    def test_the_selection_bar_offers_it_and_says_what_it_does(self):
        btn = self.buttons.get("bulkMergeBtn")
        self.assertIsNotNone(btn, "no merge-folders control on the page")
        self.assertEqual("Merge folders into one…", btn["label"])

    def test_the_tooltip_says_nothing_moves_until_it_is_confirmed(self):
        self.assertIn("Nothing moves until you confirm",
                      self.buttons["bulkMergeBtn"]["title"])

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_clicking_it_collects_the_selected_folders(self):
        """Run the button's own onclick, not a name taken from it."""
        btn = self.buttons["bulkMergeBtn"]
        # The control is delegated: call its named handler with its own
        # arguments, rather than evaluating a string it no longer carries.
        click = json.dumps("%s.apply(null, %s)"
                           % (btn["fn"], json.dumps(btn["args"])))
        body = ("(async () => {\n"
                "  rowData['a'] = { kind: 'local', path: 'A', name: 'A', isDir: true };\n"
                "  selected.add('a');\n"
                "  FOLDERS.length = 0;\n"
                "  eval(" + click + ");\n"
                "  eq('the picker opened on the ticked folder',\n"
                "     (mergeState.srcs || []).map(s => s.path), ['A']);\n"
                "  done();\n"
                "})().catch(err => { console.error(err); process.exit(1); });")
        program = PRELUDE + "eval(" + json.dumps(body) + ");"
        proc = subprocess.run(["node", "-e", program, str(CLOUD_JS)],
                              capture_output=True, text=True,
                              encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            self.fail((proc.stderr or proc.stdout or "node failed").strip())

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_both_bulk_calls_are_routed(self):
        program = PRELUDE + "eval(" + json.dumps(
            "eval(slice('const API_MAP = {', '\\nasync function pyApi(')"
            " + ';globalThis.API_MAP = API_MAP;');\n"
            "eq('preview', API_MAP.merge_preview_many, "
            "['merge_preview_many', ['srcs', 'dst']]);\n"
            "eq('execute', API_MAP.merge_execute_many, "
            "['merge_execute_many', ['merges', 'dst']]);\n"
            "done();") + ");"
        proc = subprocess.run(["node", "-e", program, str(CLOUD_JS)],
                              capture_output=True, text=True,
                              encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            self.fail((proc.stderr or proc.stdout or "node failed").strip())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
