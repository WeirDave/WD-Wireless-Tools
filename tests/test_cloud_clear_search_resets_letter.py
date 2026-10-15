"""The x in Cloud Manager's search box puts the A-Z letter back to All.

A letter picked on the A-Z bar narrows the list the same way the search does.
Clearing the search left the letter in place, so the list stayed narrowed to
one letter and looked as if rows had gone missing. The x now clears both.

The real `clearSearch` is cut out of `cloud.js` (brace-counted) and run against
recording stubs: it must empty the box, drop the letter, redraw once, and send
the list back to the top. The letter alone is enough to trigger it - the box
can already be empty when the x is pressed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 60

NODE_SCRIPT = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('function clearSearch() {');
if (a < 0) throw new Error('clearSearch moved');
let b = a, depth = 0, seen = false;
while (b < src.length && !(seen && depth === 0)) {
  if (src[b] === '{') { depth++; seen = true; }
  else if (src[b] === '}') depth--;
  b++;
}
const body = src.slice(a, b);

function run(box, letter) {
  const calls = [];
  const sb = { value: box, focus: () => calls.push('focus') };
  const rc = { scrollTop: 99 };
  const document = { getElementById: id => (id === 'searchBox' ? sb : id === 'rowsContainer' ? rc : null) };
  const f = new Function('document', 'renderRows', 'calls',
    'let activeLetter = ' + JSON.stringify(letter) + ';\n' + body +
    '\nclearSearch(); return () => activeLetter;');
  const get = f(document, () => calls.push('render'), calls);
  return { box: sb.value, letter: get(), calls, scrollTop: rc.scrollTop };
}

console.log(JSON.stringify({
  both: run('abc', 'D'),
  letterOnly: run('', 'D'),
  searchOnly: run('abc', null),
  neither: run('', null),
}));
"""


@unittest.skipUnless(shutil.which("node"), "node is required")
class ClearSearchResetsLetterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", NODE_SCRIPT, str(CLOUD_JS)],
                           capture_output=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout)

    def test_x_clears_the_box_and_the_letter_together(self):
        o = self.out["both"]
        self.assertEqual(o["box"], "")
        self.assertIsNone(o["letter"])
        self.assertEqual(o["calls"], ["render", "focus"])
        self.assertEqual(o["scrollTop"], 0)

    def test_a_letter_alone_is_cleared_with_the_box_already_empty(self):
        o = self.out["letterOnly"]
        self.assertIsNone(o["letter"])
        self.assertEqual(o["calls"], ["render", "focus"])

    def test_clearing_search_with_no_letter_still_redraws(self):
        o = self.out["searchOnly"]
        self.assertEqual(o["box"], "")
        self.assertEqual(o["calls"], ["render", "focus"])

    def test_nothing_to_clear_redraws_nothing(self):
        o = self.out["neither"]
        self.assertEqual(o["calls"], ["focus"])
        self.assertEqual(o["scrollTop"], 99)


if __name__ == "__main__":
    unittest.main()
