"""AP Labeler: the row / column guide lines, with Line Spacing on Auto and
while a number is being typed.

* With the box empty ("Auto") no line was drawn at all, so the one setting
  that decides where a row ends could not be seen working until a number was
  typed. Auto now draws the breaks the sort really uses.
* Typing "120" passes through "1": one guide per pixel of the plan - a
  thousand lines on a large drawing, rebuilt per key - which read as the box
  refusing the number. Below the box's own minimum it means Auto until the
  number is finished, for the sort and the guides alike.

Driven in Node against the real functions, sliced out of ap-rename.js by
counting braces, with a recording stand-in for the plan box. Everything here
is invented.
"""
from __future__ import annotations

import shutil
import unittest

from tests.test_ap_labeler_numbers_what_it_shows import run_node

PROBE = r"""
var MIN = Number((src.match(/var MIN_SPACING_PX = (\d+);/) || [])[1]);
if (!MIN) throw new Error('MIN_SPACING_PX moved');
var MIN_SPACING_PX = MIN;
var S = { floors: [], aps: [], imageRes: {}, currentFloor: 'fl' };
var SPACING = { value: '' };
var IMG = { naturalWidth: 4000, naturalHeight: 4000 };
function $(id) { return id === 'arSpacing' ? SPACING : id === 'arPlanImg' ? IMG : null; }
var _nesting = 'floor', _colorOrder = [], _scope = 'all';
function ap(id, x, y, fl) { return { id: id, floorPlanId: fl || 'fl', x: x, y: y }; }
var FLOOR = { id: 'fl', width: 1000, height: 1000 };
// Three rows (y about 100, 300, 500) and three columns (x about 100, 500, 900).
S.aps = [ap('a', 100, 100), ap('b', 500, 102), ap('c', 900, 100),
         ap('d', 100, 300), ap('e', 500, 305), ap('f', 900, 300),
         ap('g', 100, 500), ap('h', 500, 500), ap('i', 900, 500),
         ap('other', 5, 999, 'elsewhere')];
eval(load([
  '  function getFloorAPs(', '  function spacingPx(', '  function getSpacingUnits(',
  '  function clusterByAxis(', '  function avg(', '  function autoBreaks(',
  '  function renderGuideLines(',
]));
function draw(order, spacing) {
  SPACING.value = spacing;
  var made = [];
  var box = { querySelectorAll: function () { return []; },
              appendChild: function (el) { made.push(el); } };
  global.document = { createElement: function () { return { className: '', style: {}, remove: function () {} }; } };
  renderGuideLines(box, FLOOR, order);
  return made.map(function (el) {
    return (el.className.indexOf('ar-guide-h') >= 0 ? 'h ' + el.style.top : 'v ' + el.style.left);
  });
}
const out = {};
out.autoRows   = draw('row-ltr', '');
out.autoSnake  = draw('row-snake', '');
out.autoCols   = draw('col-btt', '');
out.autoNotOrdered = draw('proximity', '');
out.typed1     = draw('row-ltr', '1');
out.typed12    = draw('row-ltr', '12');
out.typed120   = draw('row-ltr', '120');
SPACING.value = '5';  out.unitsFive = getSpacingUnits('y', FLOOR);
SPACING.value = '10'; out.unitsTen = getSpacingUnits('y', FLOOR);
S.aps = [ap('only', 100, 100)];
out.oneRow = draw('row-ltr', '');
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class GuideLinesInAutoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = run_node(PROBE)

    def test_auto_draws_a_line_between_each_pair_of_rows(self):
        # Midway across each gap: (102+300)/2 and (305+500)/2 of a 1000 plan.
        self.assertEqual(self.got["autoRows"], ["h 20.100%", "h 40.250%"], self.got)

    def test_auto_draws_them_for_zigzag_rows_too(self):
        self.assertEqual(self.got["autoSnake"], self.got["autoRows"], self.got)

    def test_auto_draws_column_breaks_for_column_orders(self):
        self.assertEqual(self.got["autoCols"], ["v 30.000%", "v 70.000%"], self.got)

    def test_an_order_without_rows_draws_nothing(self):
        self.assertEqual(self.got["autoNotOrdered"], [], self.got)

    def test_one_row_has_nothing_to_separate(self):
        self.assertEqual(self.got["oneRow"], [], self.got)

    def test_a_half_typed_number_is_auto_not_a_line_per_pixel(self):
        # "1" would be 4000 lines on this plan. "12" is at the minimum and is real.
        self.assertEqual(self.got["typed1"], self.got["autoRows"], self.got)
        self.assertEqual(len(self.got["typed12"]), 333, self.got)  # floor(4000 / 12): 12 is a real spacing

    def test_a_finished_number_fixes_the_spacing(self):
        lines = self.got["typed120"]
        self.assertEqual(len(lines), 33, self.got)      # floor(4000 / 120)
        self.assertEqual(lines[0], "h 3.000%", self.got)

    def test_the_sort_ignores_what_the_guides_ignore(self):
        self.assertEqual(self.got["unitsFive"], 0, self.got)
        self.assertGreater(self.got["unitsTen"], 0, self.got)


if __name__ == "__main__":
    unittest.main()
