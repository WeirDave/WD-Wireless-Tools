"""Scale reads a dimension the way a drawing writes it.

On an architectural sheet ``4'-6"`` is four feet six inches: the dash joins the
feet to the inches. ``parseImperial`` read it as four feet and *minus* six
inches - 42 inches instead of 54 - so a reference measured off a dimension
string put the scale out by the difference, silently.

It also read only the parts a pattern recognised and ignored the rest, so a
common form came out wrong rather than refused: ``5ft6in`` as 5 inches,
``4 1/2'`` as 24, a bare ``1 1/2`` as 1.5 inches although a bare number is
feet, and on the metric side ``1,500 mm`` as 1.5 mm. Every form the manual's
Scale table promises is checked here, and text with anything left over is
refused rather than half read.

The real function is sliced out of ``scale.js`` by counting braces and run in
Node, so this tests what ships.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCALE_JS = ROOT / "web" / "assets" / "js" / "scale.js"

PROBE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(head) {
  const a = src.indexOf(head);
  if (a < 0) throw new Error(head + ' moved');
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
const m = /var IN_PER_FT = (\d+);/.exec(src);
if (!m) throw new Error('IN_PER_FT moved');
var IN_PER_FT = Number(m[1]);
eval(slice('  function parseImperial(raw) {'));
eval(slice('  function parseMetric(raw) {'));
const cases = JSON.parse(process.argv[2]);
const parse = process.argv[3] === 'metric' ? parseMetric : parseImperial;
const out = {};
for (const s of cases) out[s] = parse(s);
console.log(JSON.stringify(out));
"""

CASES = {
    "4'-6\"": 54,
    "4'-6 1/2\"": 54.5,
    "4' - 6\"": 54,
    "12'-0\"": 144,
    "4' 6\"": 54,
    "536'4\"": 6436,
    "4 ft 6 in": 54,
    "-4'-6\"": -54,
    "-4' 6\"": -54,
    "6\"": 6,
    "-6\"": -6,
    # The rest of the manual's table.
    "4' 6-1/2\"": 54.5,
    "4' 6 1/2\"": 54.5,
    "536.333'": 536.333 * 12,
    "6436\"": 6436,
    "536": 536 * 12,
    "12 feet": 144,
    "6 inches": 6,
    "24’ 7 1/2”": 295.5,
    # Read wrongly before, with no error.
    "5ft6in": 66,
    "5ft 6in": 66,
    "4 1/2'": 54,
    "4-1/2'": 54,
    "1 1/2": 18,
    "10 ft 6": 126,
}

#: Text with something the parser did not read is refused, not half read.
REFUSED = ["4' 6\" 3", "6'6\"x", "--6", "abc", "4 6\""]

METRIC = {
    "12m 500mm": 12500,
    "163.475m": 163475,
    "163.475": 163475,
    "163475mm": 163475,
    "1250cm": 12500,
    "1m 20cm": 1200,
    "2 metres": 2000,
    "12m500mm": 12500,
    # A comma before exactly three digits groups thousands; any other comma is
    # the decimal point.
    "1,500 mm": 1500,
    "1,500,000 mm": 1500000,
    "1,500.5 mm": 1500.5,
    "1,5 m": 1500,
    "163,4755 m": 163475.5,
}

METRIC_REFUSED = ["12 m abc", "3m50", "2.5m3"]


def _run(cases, side="imperial"):
    r = subprocess.run(["node", "-e", PROBE, str(SCALE_JS), json.dumps(list(cases)), side],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class FeetDashInches(unittest.TestCase):
    def test_each_dimension_reads_as_drawn(self):
        got = _run(CASES)
        for text, want in CASES.items():
            with self.subTest(text=text):
                self.assertIsNotNone(got[text])
                self.assertAlmostEqual(got[text], want)

    def test_text_with_something_left_over_is_refused(self):
        got = _run(REFUSED)
        for text in REFUSED:
            with self.subTest(text=text):
                self.assertIsNone(got[text])

    def test_each_metric_measurement_reads_as_written(self):
        got = _run(METRIC, "metric")
        for text, want in METRIC.items():
            with self.subTest(text=text):
                self.assertIsNotNone(got[text])
                self.assertAlmostEqual(got[text], want)

    def test_metric_text_with_something_left_over_is_refused(self):
        got = _run(METRIC_REFUSED, "metric")
        for text in METRIC_REFUSED:
            with self.subTest(text=text):
                self.assertIsNone(got[text])


if __name__ == "__main__":
    unittest.main()
