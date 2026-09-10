"""AP Labeler colour ordering, and the marker contrast that makes it usable.

Numbering by colour group existed in v2.20.0 and was disconnected by the
v2.39.0 redesign: the `by-color` case was replaced with a comment and
`sortByColorGroup` was left in the file, unreachable. This pins it back in.

The sequence is the engineer's, not a fixed palette order, because it mirrors
how the work is done - hang all the blues, come back for the oranges. The
ordering only changes which APs are handed to the numbering pass and in what
order; the pass in generatePreview() remains the one place a number is decided.

Driven through the real functions in Node, not by reading the source.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AP_JS = ROOT / "web" / "assets" / "js" / "ap-rename.js"
AP_HTML = ROOT / "web" / "ap-rename.html"
SHARED_JS = ROOT / "web" / "assets" / "js" / "wd-shared.js"

NODE_TIMEOUT_S = 120

NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const shared = fs.readFileSync(process.argv[2], 'utf8');
function cut(text, from, to) {
  const a = text.indexOf(from);
  const b = text.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return text.slice(a, b);
}
function slice(from, to) { return cut(source, from, to); }

// The palette itself lives in wd-shared.js so the Report can read it too,
// so the real one is loaded here rather than restated.
const WD = {};
eval(cut(shared, '  WD.EKAHAU_COLORS = {', '  /* ── Legibility on a user-chosen'));

const block = slice('/* ── Ekahau color palette', '/* ── naming mode')
            + slice('  function sortByColorGroup(aps, colorOrder) {', '  /* Proximity:');

// Within a colour group the spatial ordering does the work; these tests are
// about which group comes first, so the inner sort is held constant.
globalThis.sortNearestNeighbor = (a) => a.slice();

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
function names(aps) { return aps.map(a => a.name).join(','); }
"""


def _js(text: str) -> str:
    return json.dumps(text)


def run_node(program: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["node", "-e", program, str(AP_JS), str(SHARED_JS)],
                              capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"node did not finish within {NODE_TIMEOUT_S}s. That is a Node "
            f"startup timeout, not a failure of the code under test."
        ) from exc


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ColorOrdering(unittest.TestCase):

    def run_block(self, checks: str):
        program = NODE_PRELUDE + "eval(block + " + _js(checks) + ");"
        result = run_node(program)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).strip())

    APS = """
      var aps = [
        {name:'a', color:'ORANGE'}, {name:'b', color:'BLUE'},
        {name:'c', color:null},     {name:'d', color:'BLUE'},
        {name:'e', color:'RED'},    {name:'f', color:'ORANGE'}
      ];
    """

    def test_the_chosen_sequence_decides_the_group_order(self):
        self.run_block(self.APS + """
          var out = sortByColorGroup(aps, ['blue', 'orange']);
          check('blues first, then oranges, then the rest: ' + names(out),
                names(out) === 'b,d,a,f,e,c');
          done();
        """)

    def test_reversing_the_sequence_reverses_the_groups(self):
        self.run_block(self.APS + """
          var out = sortByColorGroup(aps, ['orange', 'blue']);
          check('oranges first this time: ' + names(out),
                names(out) === 'a,f,b,d,e,c');
          done();
        """)

    def test_colours_not_chosen_follow_the_chosen_ones(self):
        """Nothing is silently dropped just because it was not listed."""
        self.run_block(self.APS + """
          var out = sortByColorGroup(aps, ['red']);
          // red chosen; orange then blue follow in palette order; none last
          check('red, then palette order, then unmarked: ' + names(out),
                names(out) === 'e,a,f,b,d,c');
          done();
        """)

    def test_an_empty_sequence_falls_back_to_palette_order(self):
        self.run_block(self.APS + """
          var out = sortByColorGroup(aps, []);
          check('palette order is orange, red, blue: ' + names(out),
                names(out) === 'a,f,e,b,d,c');
          done();
        """)

    def test_aps_with_no_colour_are_numbered_last(self):
        """They are the ones nobody marked; putting them first would push every
        deliberate group down the sequence."""
        self.run_block("""
          var aps = [{name:'x', color:null}, {name:'y', color:'BLUE'},
                     {name:'z', color:null}];
          var out = sortByColorGroup(aps, ['blue']);
          check('unmarked go last: ' + names(out), names(out) === 'y,x,z');
          done();
        """)

    def test_a_colour_in_the_sequence_that_the_project_does_not_use_is_harmless(self):
        self.run_block(self.APS + """
          var out = sortByColorGroup(aps, ['magenta', 'blue']);
          check('a missing colour just does not appear: ' + names(out),
                names(out) === 'b,d,a,f,e,c');
          done();
        """)

    def test_hex_colours_are_grouped_with_their_palette_name(self):
        self.run_block("""
          var aps = [{name:'p', color:'#0068FF'}, {name:'q', color:'BLUE'},
                     {name:'r', color:'ORANGE'}];
          var out = sortByColorGroup(aps, ['blue']);
          check('a hex blue sorts with blue: ' + names(out),
                names(out).indexOf('r') === names(out).length - 1);
          done();
        """)


class LabelerUsesTheSharedContrastHelper(unittest.TestCase):
    """Contrast lives in wd-shared.js and is covered by test_color_contrast.py.
    The labeler must not grow its own copy again - that is how green ended up
    readable here and unreadable in the report at the same time."""

    def test_the_marker_asks_wd_for_its_ink_and_its_outline(self):
        source = AP_JS.read_text(encoding="utf-8")
        block = source[source.index("var resolved = resolveColor(ap.color);"):]
        block = block[:block.index("var tip =")]
        self.assertIn("WD.readableOn(", block)
        self.assertIn("WD.outlineOn(", block)

    def test_the_labeler_has_no_luminance_maths_of_its_own(self):
        source = AP_JS.read_text(encoding="utf-8")
        self.assertNotIn("0.2126", source)
        self.assertNotIn("* 299", source)


class ColorOrderingIsOffered(unittest.TestCase):
    """It was implemented and then unreachable for eleven minor versions."""

    def test_sort_aps_actually_dispatches_to_the_colour_grouping(self):
        source = AP_JS.read_text(encoding="utf-8")
        self.assertIn("case 'by-color':", source,
                      "sortByColorGroup is unreachable again")
        self.assertNotIn("by-color reserved for a future scope feature", source)

    def test_the_ordering_dropdown_offers_it(self):
        html = AP_HTML.read_text(encoding="utf-8")
        self.assertIn('value="by-color"', html)

    def test_the_colour_sequence_panel_exists(self):
        html = AP_HTML.read_text(encoding="utf-8")
        self.assertIn('id="arColorPanel"', html)

    def test_unnumbered_markers_carry_their_ap_colour(self):
        """Manual mode is where you pick APs by colour, and it was the one view
        that drew every marker the same white with a dashed ring."""
        source = AP_JS.read_text(encoding="utf-8")
        block = source[source.index("is-unnumbered is-clickable"):]
        block = block[:block.index("box.appendChild(m)")]
        self.assertIn("resolveColor(ap.color)", block)


if __name__ == "__main__":
    unittest.main()
