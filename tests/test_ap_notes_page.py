"""AP notes on the placement map.

Notes an engineer types against an AP on site had no way out of the project.
This page is the way out, and these tests hold the two things that are easy to
get wrong and invisible until it is printed.

**The data model, verified against a real project rather than assumed.** There
is no `pictureNotes.json`. Every note lives in `notes.json` as
`{id, text, imageIds[]}`, and an access point points at them through
`noteIds`. A note is a "picture note" when `imageIds` is non-empty - and such a
note can carry **no text at all**, which is exactly the case that would render
a blank row if the text were treated as the only content worth showing.

**It has to reach paper.** A page that renders on screen and not in print costs
a site visit, so the print rules are asserted here alongside the markup: its
own sheet, and a note that never splits across two of them.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"
CSS = ROOT / "web" / "assets" / "wd-tools.css"

NODE_TIMEOUT_S = 120

# The notes block, lifted out of report.js and run for real. Everything it
# leans on from the rest of the file is stubbed to something recognisable, so a
# failure points at the notes code rather than at a stub.
NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const a = source.indexOf('  function notesForAp(ap, ctx) {');
const b = source.indexOf('  function renderPlacementReport(aps, opts, ctx) {');
if (a < 0 || b < 0) throw new Error('the AP notes block moved');

const WD = {
  esc: s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                     .replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  escAttr: s => String(s).replace(/"/g, '&quot;'),
};
function apLabel(ap, mode) { return (ap && ap.name) || ''; }
function segFloorHeading(o) { return 'FLOOR ' + o.floorNumber; }
function floorNumberFor(fp) { return fp.number || '1'; }
function orientPickerHtml(key) { return '<!--orient:' + key + '-->'; }
function renderReportFooter() { return '<footer></footer>'; }

eval(source.slice(a, b));

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}

// The shapes taken from the real project: a plain text note, a second text
// note on the same AP, and an image-only note carrying no text.
function ctxWith(notes) { return { proj: { notes: notes } }; }
const FLOOR = { id: 'f1', name: 'Office', number: '1' };
"""


def _js(text: str) -> str:
    return json.dumps(text)


def run_node(checks: str) -> subprocess.CompletedProcess:
    program = NODE_PRELUDE + "eval(" + _js(checks) + ");"
    try:
        return subprocess.run(["node", "-e", program, str(REPORT_JS)],
                              capture_output=True, text=True,
                              timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"node did not finish within {NODE_TIMEOUT_S}s. That is a Node "
            f"startup timeout, not a failure of the code under test."
        ) from exc


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class NotesRendering(unittest.TestCase):
    def run_block(self, checks: str):
        result = run_node(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_a_text_note_reaches_the_page(self):
        self.run_block(r"""
        const ctx = ctxWith({
          n1: { id: 'n1', text: 'Mounted above the door frame', imageIds: [] },
        });
        const ap = { name: 'Cisco: Entrance', noteIds: ['n1'] };
        const html = renderApNotesSection(FLOOR, [ap], {}, ctx, 0);
        check('the note text is printed', html.includes('Mounted above the door frame'));
        check('the AP is named', html.includes('Cisco: Entrance'));
        done();
        """)

    def test_an_image_only_note_is_listed_not_dropped(self):
        """The real file has one: imageIds of length 1 and an empty text."""
        self.run_block(r"""
        const ctx = ctxWith({
          n1: { id: 'n1', text: '', imageIds: ['img-1'] },
        });
        const ap = { name: 'Cisco: Entrance', noteIds: ['n1'] };
        const html = renderApNotesSection(FLOOR, [ap], {}, ctx, 0);
        check('the AP still appears', html.includes('Cisco: Entrance'));
        check('the attachment is declared', html.includes('Image attached'));
        check('it says the image is not shown', html.includes('not shown'));
        check('an empty note says so rather than rendering blank',
              html.includes('No text on this note'));
        done();
        """)

    def test_an_ap_carrying_both_kinds_shows_both(self):
        """'Cisco: Entrance' in the sample has exactly this pair."""
        self.run_block(r"""
        const ctx = ctxWith({
          n1: { id: 'n1', text: 'Check the conduit run', imageIds: [] },
          n2: { id: 'n2', text: '', imageIds: ['img-1'] },
        });
        const ap = { name: 'Cisco: Entrance', noteIds: ['n1', 'n2'] };
        const html = renderApNotesSection(FLOOR, [ap], {}, ctx, 0);
        check('text note present', html.includes('Check the conduit run'));
        check('picture note present', html.includes('Image attached'));
        const items = html.split('rep-note-item').length - 1;
        check('two notes rendered, got ' + items, items === 2);
        done();
        """)

    def test_no_image_is_ever_emitted(self):
        """There is no image layout path and there must not accidentally be one."""
        self.run_block(r"""
        const ctx = ctxWith({
          n1: { id: 'n1', text: 'x', imageIds: ['img-1', 'img-2'] },
        });
        const ap = { name: 'AP1', noteIds: ['n1'] };
        const html = renderApNotesSection(FLOOR, [ap], {}, ctx, 0);
        check('no img tag', !html.includes('<img'));
        check('no background-image', !html.includes('background-image'));
        check('no image id leaked into the page', !html.includes('img-1'));
        check('the count is shown for two images', html.includes('×2'));
        done();
        """)

    def test_an_ap_with_no_notes_is_left_off_the_page(self):
        self.run_block(r"""
        const ctx = ctxWith({ n1: { id: 'n1', text: 'note', imageIds: [] } });
        const withNote = { name: 'HasNote', noteIds: ['n1'] };
        const without  = { name: 'NoNote', noteIds: [] };
        const html = renderApNotesSection(FLOOR, [withNote, without], {}, ctx, 0);
        check('the AP with a note is listed', html.includes('HasNote'));
        check('the AP without one is not', !html.includes('NoNote'));
        done();
        """)

    def test_a_dangling_note_id_does_not_crash_the_report(self):
        """A note deleted from the project leaves its id on the AP."""
        self.run_block(r"""
        const ctx = ctxWith({});
        const ap = { name: 'AP1', noteIds: ['gone'] };
        const html = renderApNotesSection(FLOOR, [ap], {}, ctx, 0);
        check('the floor contributes no page at all', html === '');
        done();
        """)

    def test_a_whitespace_only_note_is_not_a_note(self):
        self.run_block(r"""
        const ctx = ctxWith({ n1: { id: 'n1', text: '   \n  ', imageIds: [] } });
        const html = renderApNotesSection(FLOOR, [{ name: 'AP1', noteIds: ['n1'] }], {}, ctx, 0);
        check('nothing is rendered for an empty note', html === '');
        done();
        """)

    def test_note_text_is_escaped(self):
        """Notes are free text typed on a phone; they are not markup."""
        self.run_block(r"""
        const ctx = ctxWith({
          n1: { id: 'n1', text: '<script>alert(1)</script> & "quoted"', imageIds: [] },
        });
        const html = renderApNotesSection(FLOOR, [{ name: 'AP1', noteIds: ['n1'] }], {}, ctx, 0);
        check('no raw script tag', !html.includes('<script>'));
        check('escaped instead', html.includes('&lt;script&gt;'));
        done();
        """)

    def test_the_checkbox_gates_the_pages(self):
        self.run_block(r"""
        const ctx = ctxWith({ n1: { id: 'n1', text: 'note', imageIds: [] } });
        const aps = [{ name: 'AP1', noteIds: ['n1'] }];
        check('off by default', wantsApNotes(aps, {}, ctx) === false);
        check('on when ticked', wantsApNotes(aps, { apNotes: true }, ctx) === true);
        check('ticked but nothing to show stays off',
              wantsApNotes([{ name: 'AP2', noteIds: [] }], { apNotes: true }, ctx) === false);
        done();
        """)

    def test_the_page_carries_the_floor_heading_the_map_uses(self):
        """A note belongs with the plan it was written on."""
        self.run_block(r"""
        const ctx = ctxWith({ n1: { id: 'n1', text: 'note', imageIds: [] } });
        const html = renderApNotesSection(FLOOR, [{ name: 'AP1', noteIds: ['n1'] }], {}, ctx, 0);
        check('floor heading present', html.includes('FLOOR 1'));
        check('floor name present', html.includes('Office'));
        check('it is a page section', html.includes('rep-notes-page'));
        check('it takes part in orientation', html.includes('rep-oriented'));
        done();
        """)


class NotesReachPaper(unittest.TestCase):
    """A notes page that renders on screen and not on paper costs a site visit."""

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8")
        self.js = REPORT_JS.read_text(encoding="utf-8")

    def _print_block(self) -> str:
        start = self.css.index(".rep-notes-page { page-break-before: always;")
        return self.css[start:start + 1200]

    def test_the_notes_page_starts_its_own_sheet(self):
        block = self._print_block()
        self.assertIn("break-before: page", block)

    def test_a_note_is_not_split_across_two_sheets(self):
        block = self._print_block()
        self.assertIn("break-inside: avoid", block)

    def test_the_print_rules_are_inside_a_media_print_block(self):
        """The bug this guards: styling that only ever applies on screen."""
        idx = self.css.index(".rep-notes-page { page-break-before: always;")
        before = self.css[:idx]
        opened = before.rindex("@media print")
        # No closing brace at column 0 between that @media and the rule
        # means the rule is still inside the block.
        # A line that is exactly a closing brace between that @media and
        # the rule would mean the block had already ended.
        between = before[opened:].splitlines()
        self.assertNotIn("}", [ln.strip() for ln in between],
                         "the notes print rules fell outside @media print")

    def test_note_text_prints_in_a_readable_colour(self):
        block = self._print_block()
        self.assertIn("#111 !important", block)

    def test_long_notes_wrap_rather_than_being_clipped(self):
        """Unlike the label reference, this text is read, not transcribed."""
        start = self.css.index(".rep-note-text {")
        rule = self.css[start:self.css.index("}", start)]
        self.assertIn("overflow-wrap: anywhere", rule)
        self.assertIn("pre-wrap", rule)

    def test_the_option_sits_directly_below_the_compass_one(self):
        """Where he looked for it, and did not find it.

        The two "add a reference page" controls are the compass page and this
        one; they belong together at the foot of the list. It first shipped up
        beside the label-reference select, which is defensible and is not where
        anybody goes looking.
        """
        import re
        start = self.js.index("    placement: {")
        end_marker = "\n    },\n"
        block = self.js[start:self.js.index(end_marker,
                                            self.js.index("sidebar: [", start))]
        ids = re.findall(r"\{ id: '([a-zA-Z]+)'", block)
        self.assertIn("apNotes", ids)
        self.assertEqual(ids[ids.index("compassRef") + 1], "apNotes")

    def test_the_checkbox_is_never_conditional_on_finding_notes(self):
        """An absent control looks like a feature that did not ship.

        The pages are gated on notes existing; the control must not be. A
        visible checkbox that produces nothing explains itself - a missing one
        costs somebody a phone call.
        """
        start = self.js.index("id: 'apNotes'")
        entry = self.js[start:start + 900]
        for gate in ("disabledWhen", "hiddenWhen", "if ("):
            self.assertNotIn(gate, entry.split("},")[0])

    def test_notes_are_independent_of_the_label_reference_setting(self):
        """Whether notes print has nothing to do with whether markers show numbers.

        The two controls sat next to each other and were read as one: the
        label-reference select shows "Auto - when the plan shows numbers", so
        the notes checkbox under it looked like part of that decision. They are
        separate keys read in separate places and must stay that way - including
        notes is an audience and privacy call, not a formatting one.
        """
        self.assertIn("opts.apNotes", self.js)
        self.assertIn("opts.nameKey", self.js)
        # Neither gate may mention the other.
        end_of_fn = "\n  }"
        notes_gate = self.js[self.js.index("function wantsApNotes"):]
        notes_gate = notes_gate[:notes_gate.index(end_of_fn)]
        self.assertNotIn("nameKey", notes_gate)
        key_gate = self.js[self.js.index("function wantsNameKey"):]
        key_gate = key_gate[:key_gate.index(end_of_fn)]
        self.assertNotIn("apNotes", key_gate)

    def test_the_notes_option_says_why_it_is_off(self):
        """His reason for wanting it separate, kept where the choice is made."""
        start = self.js.index("id: 'apNotes'")
        entry = self.js[start:start + 900]
        self.assertIn("not always meant for a client", entry)
        self.assertIn("independent of every other option", entry)

    def test_the_choice_persists_with_the_other_report_options(self):
        """It is swept up by the per-report defaults button like any checkbox.

        Guards the two lists that would silently exclude it.
        """
        self.assertNotIn("'apNotes'", self.js[self.js.index("var SETTING_IDS"):
                                              self.js.index("var SETTING_FIELD")])
        start = self.js.index("var PERSON_LEVEL_OPTS")
        line_end = self.js.index("\n", start)
        self.assertNotIn("apNotes", self.js[start:line_end])

    def test_the_option_is_registered_on_the_placement_report(self):
        self.assertIn("id: 'apNotes'", self.js)
        idx = self.js.index("id: 'apNotes'")
        block = self.js[idx:idx + 900]
        self.assertIn("default: false", block)
        self.assertIn("Text only", block)

    def test_notes_are_read_from_the_project(self):
        """No pictureNotes.json: it does not exist in a real file."""
        self.assertIn("readJson('notes.json')", self.js)
        self.assertNotIn("readJson('pictureNotes.json')", self.js)


if __name__ == "__main__":
    unittest.main()
