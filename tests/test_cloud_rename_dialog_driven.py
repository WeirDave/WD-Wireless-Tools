"""The rename dialog, built by running it rather than by reading its source.

This is the A34 conversion of `TheRenameDialogStandsOnItsOwnTests` in
`test_cloud_modals_are_self_sufficient.py` - the file the 2026-09-18 audit
named first, with fifteen assertions against the text of `cloud.js`,
`cloud.html` and `wd-tools.css`.

Those assertions were not wrong about what they wanted. They were checking that
the dialog is **self-sufficient** - that everything needed to finish the job is
inside it, because the backdrop is dimmed on purpose and the row he is renaming
may not be on screen at all:

    "I click on the pencil to rename it and of course it blurs out the
    background again and I can't see what I'm doing in order to rename it."

What they could not check is whether any of it reaches the screen. `assertIn`
on `'id="renameWhat"'` passes on an element that nothing ever writes to, and
`assertIn("Folder / site name", source)` passes on a label built into a string
that is never assigned anywhere.

So `startRename` runs here against a DOM small enough to read back, and the
assertions are about what it *put on screen*: the two labelled facts, the full
path, the field's value, and where the caret ended up. `_renameInsert` and
`_renamePreview` are executed too, because "showing it saves him nothing if he
still has to type it" is a claim about behaviour.

Every name and path here is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from delegated import DELEGATED_JS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"

NODE_TIMEOUT_S = 120

SITE_FOLDER = "SITE4 Northgate"
LOCAL_PATH = r"C:\Projects\SITE4 Northgate\SITE4 - Design.esx"
LOCAL_NAME = "SITE4 - Design"

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
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');
/* cloud.js's own escaping helpers, by the names it uses: `e` for text, `a`
   for an attribute value, `j`/`pj` for a value going into an inline handler.
   The real `j` is used rather than a stub, because a project named with an
   apostrophe is exactly what turns a rendered button into a dead one. */
const a = e;
const j = s => String(s == null ? '' : s).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
const pj = j;
globalThis.e = e; globalThis.a = a; globalThis.j = j; globalThis.pj = pj;
globalThis.currentTab = 'projects';

/* A DOM with exactly the elements the dialog writes to. Anything it reaches
   for that is missing throws, which is the point: an element the markup has
   dropped shows up here as a failure rather than as a silent no-op. */
function mk(id) {
  return {
    id: id, _html: '', textContent: '', hidden: false, checked: false,
    value: '', selectionStart: 0, selectionEnd: 0,
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = v; },
    setSelectionRange(a, b) { this.selectionStart = a; this.selectionEnd = b; },
    focus() { this.focused = true; },
    select() { this.selectedAll = true; },
  };
}
const els = {};
['renameTitle', 'renameWhat', 'renameSub', 'renameInsert', 'renamePair',
 'renamePairBoth', 'renamePairLabel', 'renameInput', 'renamePreview',
 'renameModal'].forEach(id => { els[id] = mk(id); });
globalThis.els = els;
globalThis.document = {
  getElementById: (id) => {
    if (!(id in els)) throw new Error('the dialog wrote to #' + id
      + ', which this harness does not know about - add it or the markup lost it');
    return els[id];
  },
  querySelector: () => null,
  querySelectorAll: () => [],
};

let shown = null;
function showModal(id) { shown = id; }
globalThis.getShown = () => shown;

/* The ledger the dialog reads its facts from. */
globalThis.data = { matched: [], cloudOnly: [], localOnly: [] };
function _cloudDetailsById(id) {
  return id === 'proj-1' ? { siteName: 'Northgate Campus' } : null;
}
function localByPath() { return null; }
function _renamePartner() { return null; }

// The real functions, exactly as shipped.
eval(slice('function startRename(side, idOrPath, name, kind)',
           '\n/* The site or folder this thing sits in'));
eval(slice('function _renameContainerName(side, idOrPath, kind)',
           '\n/* He renames the file on disk'));
eval(slice('function _renameSuffix(side, kind)', '\nfunction _renameInsert('));
eval(slice('function _renameInsert(', '\nfunction _renamePreview('));
// Single-newline boundaries throughout: cloud.js is CRLF, so a blank line is
// "\r\n\r\n" and a "\n\n" marker matches nothing anywhere in the file.
eval(slice('function _renamePreview(', '\nfunction _renameSentenceCase('));
// Real too: it decides whether the .esx suffix is part of the fact on screen,
// which is one of the things under test.
eval(slice('function _renameLocalEsx(rt)', '\n/* Bring the third name'));

function textOf(html) {
  return String(html).replace(/<[^>]*>/g, ' ')
    .replace(/&amp;/g, '&').replace(/&quot;/g, '"')
    .replace(/&ldquo;|&rdquo;/g, '"')
    .replace(/\s+/g, ' ').trim();
}
globalThis.textOf = textOf;

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


def run_node(checks: str) -> subprocess.CompletedProcess:
    program = DELEGATED_JS + PRELUDE + "eval(" + json.dumps(checks) + ");"
    try:
        # encoding is explicit: the dialog's labels carry curly quotes, and
        # decoding the child with the locale codec reads them as mojibake on
        # Windows and intact in CI.
        return subprocess.run(["node", "-e", program, str(CLOUD_JS)],
                              capture_output=True, text=True,
                              encoding="utf-8", timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError("node did not finish") from exc


LOCAL = "startRename('local', %s, %s, 'projects');" % (
    json.dumps(LOCAL_PATH), json.dumps(LOCAL_NAME))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TheDialogCarriesTheFactsItNeedsTests(unittest.TestCase):

    def run_checks(self, checks: str):
        proc = run_node(checks)
        if proc.returncode != 0:
            self.fail((proc.stderr or proc.stdout or "node failed").strip())

    def test_it_says_what_is_being_renamed(self):
        self.run_checks(LOCAL + r"""
          check('the dialog opened', getShown() === 'renameModal');
          const t = textOf(els.renameWhat.innerHTML + ' ' + els.renameSub.textContent);
          check('it says what is being renamed: ' + t, /You are renaming/.test(t));
          check('and names the type', /Local \.esx File/.test(els.renameTitle.textContent));
          done();
        """)

    def test_the_folder_and_the_current_name_are_both_on_screen(self):
        """His own answer to which name he meant was "folder / site name".

        Both labelled, both at rest. The folder used to be a lowercase aside on
        the end of the name line - where a fact goes when it has been thought
        of as context rather than as the string he is trying to type.
        """
        self.run_checks(LOCAL + r"""
          const what = els.renameWhat.innerHTML;
          const t = textOf(what);
          check('the folder is labelled: ' + t, /Folder \/ site name/.test(t));
          check('and carries the folder name', t.indexOf('SITE4 Northgate') !== -1);
          check('the current name is labelled', /Current file name/.test(t));
          check('and carries it with its extension',
                t.indexOf('SITE4 - Design.esx') !== -1);
          done();
        """)

    def test_a_local_item_shows_its_full_path(self):
        """Two sites can own a folder of the same name; the path settles it."""
        self.run_checks(LOCAL + r"""
          const t = textOf(els.renameWhat.innerHTML);
          check('the path is labelled: ' + t, /Full path/.test(t));
          check('and it is the whole path',
                t.indexOf('C:/Projects/SITE4 Northgate/SITE4 - Design.esx') !== -1);
          done();
        """)

    def test_a_cloud_project_shows_its_site_rather_than_a_path(self):
        self.run_checks(r"""
          startRename('cloud', 'proj-1', 'Northgate Survey', 'projects');
          const t = textOf(els.renameWhat.innerHTML);
          check('labelled as a cloud site: ' + t, /Cloud site/.test(t));
          check('and names it', t.indexOf('Northgate Campus') !== -1);
          check('with no path row', !/Full path/.test(t));
          check('and named as a project', /Current project name/.test(t));
          done();
        """)

    def test_nothing_it_shows_is_cut_short(self):
        """"it would be better if it was easily readable and lengthy than if
        it's brief." The dialog is widened rather than the strings shortened,
        so the values reach the markup whole."""
        self.run_checks(r"""
          const longName = 'SITE4 - Design - North Wing - Phase Two Revision C';
          startRename('local',
            'C:\\Projects\\SITE4 Northgate Business Park\\' + longName + '.esx',
            longName, 'projects');
          const t = textOf(els.renameWhat.innerHTML);
          check('the whole name is there', t.indexOf(longName) !== -1);
          check('and the whole folder', t.indexOf('SITE4 Northgate Business Park') !== -1);
          check('nothing was ellipsised', t.indexOf('\u2026') === -1);
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TheFieldIsReadyToTypeIntoTests(unittest.TestCase):

    def run_checks(self, checks: str):
        proc = run_node(checks)
        if proc.returncode != 0:
            self.fail((proc.stderr or proc.stdout or "node failed").strip())

    def test_the_field_opens_prefilled_with_the_caret_at_the_end(self):
        """Not select-all. He is adding to a name, not replacing one.

        "I had a whole bunch that were named with just the prefix and didn't
        add additional information on facilities, and now I need to do that."
        With the whole value selected the first keystroke deletes the prefix
        that was already correct.
        """
        self.run_checks(LOCAL + r"""
          const input = els.renameInput;
          eq('prefilled with the current name', input.value, 'SITE4 - Design');
          eq('caret at the end', [input.selectionStart, input.selectionEnd],
             [input.value.length, input.value.length]);
          check('nothing was select-all-ed', !input.selectedAll);
          check('and it has focus', !!input.focused);
          done();
        """)

    def test_inserting_the_folder_adds_to_the_name_rather_than_replacing_it(self):
        """Caught originally by driving it: the first version wiped the name.

        The field used to open with everything selected, so the insert button
        replaced the selection - turning "SITE4 - Design" into "SITE4
        Northgate", which is the opposite of "I want to use the folder name as
        part of the name".
        """
        self.run_checks(LOCAL + r"""
          const input = els.renameInput;
          const before = input.value;
          // The button's own onclick, pulled back out of the markup it
          // rendered and run - a handler that takes the wrong argument
          // renders perfectly and does nothing.
          const m = delegated(els.renameInsert.innerHTML, '_renameInsert');
          check('the insert button has a handler', !!m);
          globalThis._renameInsert.apply(null, m.args);
          check('the name he already had survived: ' + input.value,
                input.value.indexOf(before) !== -1);
          check('and the folder name is now in it',
                input.value.indexOf('SITE4 Northgate') !== -1);
          check('it grew', input.value.length > before.length);
          done();
        """)

    def test_inserting_at_the_caret_does_not_eat_a_selection(self):
        """A selection in the middle is a cursor position, not a thing to
        overwrite - the whole-value case above is the one that bit."""
        self.run_checks(LOCAL + r"""
          const input = els.renameInput;
          input.value = 'SITE4 - Design';
          input.selectionStart = input.selectionEnd = input.value.length;
          const m2 = delegated(els.renameInsert.innerHTML, '_renameInsert');
          globalThis._renameInsert.apply(null, m2.args);
          check('the original is intact: ' + input.value,
                input.value.indexOf('SITE4 - Design') === 0);
          done();
        """)

    def test_only_one_thing_is_offered_to_click(self):
        """One button, doing the one thing he asked for.

        "no just skip that idea for now, I just need you to add the site name
        to the rename modal." Two passes built more than that and both were
        cut back.
        """
        self.run_checks(LOCAL + r"""
          const html = els.renameInsert.innerHTML;
          const buttons = (html.match(/<button/g) || []).length;
          eq('exactly one button', buttons, 1);
          check('and it names what it will insert: ' + textOf(html),
                textOf(html).indexOf('SITE4 Northgate') !== -1);
          done();
        """)

    def test_a_thing_with_no_folder_offers_no_insert(self):
        """A site is not inside anything, so there is nothing to offer."""
        self.run_checks(r"""
          startRename('cloud', 'site-1', 'Northgate', 'sites');
          eq('no button at all', els.renameInsert.innerHTML, '');
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ThePreviewShowsTheOutcomeTests(unittest.TestCase):

    def run_checks(self, checks: str):
        proc = run_node(checks)
        if proc.returncode != 0:
            self.fail((proc.stderr or proc.stdout or "node failed").strip())

    def test_the_preview_is_already_filled_when_the_dialog_opens(self):
        """At rest, before he types anything.

        Every other test here calls `_renamePreview()` itself, so none of them
        noticed when `startRename` stopped calling it - the mutation that
        removed that one line passed the whole file. An empty preview panel
        under a pre-filled field reads as the dialog not working yet.
        """
        self.run_checks(LOCAL + r"""
          const t = textOf(els.renamePreview.innerHTML);
          check('the preview is not empty on open: ' + JSON.stringify(t), !!t);
          // "Unchanged" rather than the name twice, which is the right answer
          // to "what will this do" before anything has been typed.
          check('and it says nothing has changed yet: ' + t, /Unchanged/.test(t));
          done();
        """)

    def test_it_shows_the_name_before_and_after(self):
        self.run_checks(LOCAL + r"""
          els.renameInput.value = 'SITE4 - As Built';
          _renamePreview();
          const t = textOf(els.renamePreview.innerHTML);
          check('the old name is shown: ' + t, t.indexOf('SITE4 - Design') !== -1);
          check('and the new one', t.indexOf('SITE4 - As Built') !== -1);
          done();
        """)

    def test_the_preview_carries_the_extension_for_a_local_file(self):
        """He renames the file on disk, so the suffix is part of the outcome."""
        self.run_checks(LOCAL + r"""
          els.renameInput.value = 'SITE4 - As Built';
          _renamePreview();
          const t = textOf(els.renamePreview.innerHTML);
          check('both sides carry .esx: ' + t,
                (t.match(/\.esx/g) || []).length >= 2);
          done();
        """)

    def test_a_cloud_project_gets_no_invented_extension(self):
        """A cloud project is not a file, and calling it one is the small
        wrongness that makes a reader stop and wonder which list they are in.
        """
        self.run_checks(r"""
          startRename('cloud', 'proj-1', 'Northgate Survey', 'projects');
          els.renameInput.value = 'Northgate As Built';
          _renamePreview();
          const t = textOf(els.renamePreview.innerHTML);
          check('no extension anywhere: ' + t, t.indexOf('.esx') === -1);
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TheApparatusHeCutIsNotOnScreenTests(unittest.TestCase):
    """"No just skip that idea for now, I just need you to add the site name
    to the rename modal."

    Two passes read more into "folder / site name" than was there - first that
    the file name should equal the folder name, then a whole
    prefix-and-descriptor scheme - and he cut both.

    **Asserted as absence from the rendered dialog rather than absence from the
    source.** A `assertNotIn("_renameMatch", CLOUD_JS)` is the same shape as
    the assertions this file exists to replace, and it answers a weaker
    question: a symbol can be gone while the apparatus is rebuilt under another
    name, and it can be present and unreachable. What he asked for is that the
    dialog does not do it.
    """

    def run_checks(self, checks: str):
        proc = run_node(checks)
        if proc.returncode != 0:
            self.fail((proc.stderr or proc.stdout or "node failed").strip())

    def test_the_dialog_offers_nothing_but_the_one_insert(self):
        self.run_checks(LOCAL + r"""
          const html = els.renameWhat.innerHTML + els.renameInsert.innerHTML
                     + els.renamePreview.innerHTML;
          const t = textOf(html).toLowerCase();
          ['prefix', 'descriptor', 'separator', 'match the folder',
           'matches the folder'].forEach(function (word) {
            check('the dialog offers "' + word + '", which he cut',
                  t.indexOf(word) === -1);
          });
          const controls = (html.match(/<(button|select|input)[ >]/g) || []).length;
          eq('one control, and it is the insert', controls, 1);
          done();
        """)

    def test_it_does_not_judge_the_name_he_types(self):
        """No verdict on whether the name "matches" - it shows and gets out of
        the way."""
        self.run_checks(LOCAL + r"""
          els.renameInput.value = 'something completely unrelated';
          _renamePreview();
          const t = textOf(els.renamePreview.innerHTML).toLowerCase();
          ['does not match', 'mismatch', 'should be', 'expected']
            .forEach(function (word) {
              check('the preview judges the name ("' + word + '")',
                    t.indexOf(word) === -1);
            });
          done();
        """)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
