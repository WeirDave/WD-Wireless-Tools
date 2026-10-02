"""Scale reads a dimension the way a drawing writes it.

On an architectural sheet ``4'-6"`` is four feet six inches: the dash joins the
feet to the inches. ``parseImperial`` read it as four feet and *minus* six
inches - 42 inches instead of 54 - so a reference measured off a dimension
string put the scale out by the difference, silently.

The real function is sliced out of ``scale.js`` by counting braces and run in
Node, so this tests what ships.
"""
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
const cases = JSON.parse(process.argv[2]);
const out = {};
for (const s of cases) out[s] = parseImperial(s);
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
}


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class FeetDashInches(unittest.TestCase):
    def test_each_dimension_reads_as_drawn(self):
        import json
        r = subprocess.run(["node", "-e", PROBE, str(SCALE_JS), json.dumps(list(CASES))],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        got = json.loads(r.stdout)
        for text, want in CASES.items():
            with self.subTest(text=text):
                self.assertAlmostEqual(got[text], want)


if __name__ == "__main__":
    unittest.main()
