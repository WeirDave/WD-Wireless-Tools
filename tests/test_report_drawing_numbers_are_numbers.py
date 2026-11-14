"""Report concatenates floor-plan sizes and AP coordinates into SVG attributes.

`'viewBox="0 0 ' + fp.width + ' ' + fp.height + '"'` is a string built from
numbers read out of the `.esx`. In a real project they are numbers. In a crafted
one `width` can be a string holding a quote, which closes the attribute and lets
the file write markup and CSS into the report. The strict CSP stops script, so
this is spoofed report content rather than code execution - but a spoofed report
is one somebody prints and hands over.

The fix is at the single place the values enter, `coerceDrawingNumbers`. This
test pulls that function out of the real `report.js` and runs it over a hostile
project, then builds the attribute the way the page does and checks nothing
escaped it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"


def _run(target: dict) -> dict:
    """Run the real functions on *target*; return the coerced object and the
    attribute strings built from it."""
    probe = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(marker) {
  const a = src.indexOf(marker);
  if (a < 0) throw new Error(marker + ' moved');
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
eval(slice('function finiteOrZero(v)'));
eval(slice('function coerceDrawingNumbers(target)'));
const target = JSON.parse(process.argv[2]);
coerceDrawingNumbers(target);
const fp = target.floorPlans[0];
const ap = target.accessPoints[0];
const attr = '<svg viewBox="0 0 ' + fp.width + ' ' + fp.height + '" style="--w:' + fp.width + '">' +
             '<circle cx="' + ap.location.coord.x + '" cy="' + ap.location.coord.y + '"/>';
process.stdout.write(JSON.stringify({ target, attr }));
"""
    r = subprocess.run(["node", "-e", probe, str(REPORT_JS), json.dumps(target)],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=60)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout)


@unittest.skipUnless(shutil.which("node"), "needs node")
class DrawingNumbersAreNumbersTests(unittest.TestCase):

    HOSTILE = {
        "floorPlans": [{"id": "f", "width": '100" onmouseover="x', "height":
                        '5;} body{display:none', "metersPerUnit": "<b>"}],
        "accessPoints": [{"location": {"coord": {"x": '1"/><script>', "y": None}}}],
    }

    def test_a_string_that_is_not_a_number_cannot_leave_the_attribute(self):
        out = _run(json.loads(json.dumps(self.HOSTILE)))
        attr = out["attr"]
        for needle in ('onmouseover', 'display:none', '<script', '<b>', "'"):
            self.assertNotIn(needle, attr)
        self.assertEqual(
            '<svg viewBox="0 0 0 0" style="--w:0"><circle cx="0" cy="0"/>', attr)

    def test_real_numbers_and_numeric_strings_survive(self):
        out = _run({"floorPlans": [{"id": "f", "width": 1234.5, "height": "800",
                                    "metersPerUnit": 0.0125}],
                    "accessPoints": [{"location": {"coord": {"x": 10, "y": "20.5"}}}]})
        fp = out["target"]["floorPlans"][0]
        self.assertEqual((1234.5, 800, 0.0125),
                         (fp["width"], fp["height"], fp["metersPerUnit"]))
        c = out["target"]["accessPoints"][0]["location"]["coord"]
        self.assertEqual((10, 20.5), (c["x"], c["y"]))

    def test_infinity_and_nan_become_zero(self):
        out = _run({"floorPlans": [{"id": "f", "width": "Infinity", "height": "NaN"}],
                    "accessPoints": [{"location": {"coord": {"x": "1e999", "y": 3}}}]})
        self.assertEqual("0", str(out["target"]["floorPlans"][0]["width"]))
        self.assertEqual(0, out["target"]["floorPlans"][0]["height"])
        self.assertEqual(0, out["target"]["accessPoints"][0]["location"]["coord"]["x"])

    def test_an_ap_without_a_location_is_left_alone(self):
        out = _run({"floorPlans": [{"id": "f", "width": 1, "height": 1}],
                    "accessPoints": [{"location": {"coord": {"x": 1, "y": 1}}},
                                     {"name": "no location"}]})
        self.assertEqual({"name": "no location"},
                         out["target"]["accessPoints"][1])


if __name__ == "__main__":
    unittest.main()
