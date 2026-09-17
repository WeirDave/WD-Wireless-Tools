"""The Antenna Aim Sheet table has to fit the sheet, whatever is in it.

What went wrong, measured off a printed PDF rather than read off the source:
with `table-layout: fixed` and no column widths, nine columns each got a ninth
of the sheet. Tilt - four characters - had as much room as an external
antenna's part number, and "BLDG01-FL01-AP003" did not fit the AP name column.
Because a table cell's overflow is visible by default, the name did not wrap or
clip; it left its cell and printed on top of the Floor value beside it. Every
one of the twenty-four rows was affected. The sheet is what an installer aims
antennas from, so a row whose AP name and floor are printed over each other is
a row they cannot use.

Two things make it impossible, and both are asserted here:

  * every column has a declared width, so no column can be starved
  * cells clip, so even a value nothing can break cannot reach its neighbour

The acceptance test is neither of those - it is that no text is printed on top
of any other text in the PDF. That needs a browser, so it lives in the report
sweep rather than in CI; see `analyse_pdf.py` in the session scratchpad, which
reports 24 overlapping spans on the old build and 0 on this one.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"
CSS = ROOT / "web" / "assets" / "wd-tools.css"


class AimTableColumns(unittest.TestCase):
    def setUp(self):
        self.js = REPORT_JS.read_text(encoding="utf-8")

    def test_every_column_has_a_declared_width(self):
        """Nine columns sharing the sheet evenly is what starved the AP name
        column. The counts have to match the header row, or a width lands on
        the wrong column - which is worse than none at all."""
        block = self.js[self.js.index("var cols = showSignOff"):]
        block = block[:block.index("var table =")]
        found = re.findall(r"\[([0-9,\s]+)\]", block)
        self.assertEqual(len(found), 2, "expected a with- and without-sign-off set")
        with_signoff = [int(n) for n in found[0].split(",")]
        without = [int(n) for n in found[1].split(",")]

        self.assertEqual(len(with_signoff), 9,
                         "the sign-off table has nine columns")
        self.assertEqual(len(without), 7,
                         "without sign-off it has seven")
        for name, widths in (("with sign-off", with_signoff), ("without", without)):
            self.assertEqual(sum(widths), 100,
                             "%s: widths must be a whole sheet, got %d%%"
                             % (name, sum(widths)))

    def test_the_long_columns_get_the_room(self):
        """An AP name and an antenna model are long; a tilt is four
        characters. Widths that do not reflect that are how this broke."""
        block = self.js[self.js.index("var cols = showSignOff"):]
        block = block[:block.index("var table =")]
        w = [int(n) for n in re.findall(r"\[([0-9,\s]+)\]", block)[0].split(",")]
        num, name, floor, azimuth, tilt, height, antenna = w[:7]
        self.assertGreater(name, tilt * 2, "AP name needs more room than Tilt")
        self.assertGreater(antenna, tilt * 2, "Antenna model needs more room than Tilt")
        self.assertGreater(name, num * 3, "AP name needs more room than the index")

    def test_a_colgroup_is_actually_emitted(self):
        self.assertIn("<colgroup>", self.js)
        self.assertIn("rep-ap-table rep-aim-table", self.js)


class CellsCannotReachTheirNeighbour(unittest.TestCase):
    def test_print_cells_clip(self):
        """The widths are the fix; this is the guarantee. A value with no
        legal break point used to leave its cell and paint over the column
        next to it, and no set of widths can rule that out for every possible
        AP name."""
        css = CSS.read_text(encoding="utf-8")
        i = css.index("@media print")
        block = css[i:]
        rule = block[block.index(".rep-ap-table th, .rep-ap-table td {"):]
        rule = rule[:rule.index("}")]
        # the declarations only - the comment above them names the value this
        # rule must not go back to
        rule = re.sub(r"/\*.*?\*/", "", rule, flags=re.S)
        self.assertIn("overflow: hidden", rule,
                      "a print cell must clip, or it bleeds into the next column")
        self.assertIn("overflow-wrap: break-word", rule,
                      "a long value should wrap before it is clipped")
        # The lesson from v2.29.0, which must not be undone by the above:
        # breaking at *any* character drove rows hundreds of points tall.
        self.assertNotIn("overflow-wrap: anywhere", rule)
        self.assertIn("word-break: normal", rule)


if __name__ == "__main__":
    unittest.main()
