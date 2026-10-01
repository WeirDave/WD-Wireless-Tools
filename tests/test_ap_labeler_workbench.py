"""AP Labeler in the workbench shell Prep and PlanTrim use.

Asked for as part of the suite-wide refresh, once the shell was seen in Prep:
"this style of layout is probably absolutely how the rest of the tools should
look as well". AP Labeler already had the plan and a resizable naming panel;
what it gained is the floors on a rail rather than tabs across the top, and
Download in a footer that says what it will write rather than in the header.

* The footer sits beside the workbench row, never inside a scrolling column,
  and holds the one verb.
* The floors are on the rail.
* The footer's sentence is the real `willWriteText`, run in Node: it counts
  what changes, names duplicates, and says plainly when nothing would.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "web" / "ap-rename.html"
JS = ROOT / "web" / "assets" / "js" / "ap-rename.js"


class _Parents(HTMLParser):
    VOID = {"input", "br", "img", "meta", "link", "hr", "source"}

    def __init__(self):
        super().__init__()
        self.stack, self.where = [], {}

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        name = d.get("id") or (d.get("class") or "").split(" ")[0] or tag
        if d.get("id"):
            self.where[d["id"]] = list(self.stack)
        if tag == "footer":
            self.where["<footer>"] = list(self.stack)
        if tag not in self.VOID:
            self.stack.append(name)

    def handle_endtag(self, tag):
        if tag not in self.VOID and self.stack:
            self.stack.pop()


def _where():
    p = _Parents()
    p.feed(HTML.read_text(encoding="utf-8"))
    return p.where


class TheShell(unittest.TestCase):
    def test_download_is_in_the_footer(self):
        self.assertIn("pb-footer", _where()["arDownloadBtn"])

    def test_the_footer_is_beside_the_columns_not_in_one(self):
        self.assertEqual(_where()["<footer>"][-1], "ar-main")

    def test_the_floors_are_on_the_rail(self):
        self.assertIn("pb-rail", _where()["arFloorTabs"])


PROBE = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('  function willWriteText(items, dupes) {');
if (a < 0) throw new Error('willWriteText moved');
let b = a, depth = 0, seen = false;
while (b < src.length && !(seen && depth === 0)) {
  if (src[b] === '{') { depth++; seen = true; } else if (src[b] === '}') depth--;
  b++;
}
eval(src.slice(a, b));
const it = (o, n) => ({ oldName: o, newName: n });
console.log(JSON.stringify({
  empty: willWriteText([], 0),
  none: willWriteText([it('A', 'A'), it('B', 'B')], 0),
  some: willWriteText([it('A', 'X1'), it('B', 'B'), it('C', 'X2')], 0),
  one: willWriteText([it('A', 'X1')], 0),
  dupes: willWriteText([it('A', 'X'), it('B', 'X')], 1),
}));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheFooterSaysWhatItWillWrite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", PROBE, str(JS)], capture_output=True,
                           encoding="utf-8", timeout=60)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_nothing_loaded_says_nothing(self):
        self.assertEqual(self.out["empty"], "")

    def test_it_counts_only_what_changes(self):
        self.assertTrue(self.out["some"].startswith("2 of 3 access points will be renamed"))
        self.assertTrue(self.out["one"].startswith("1 of 1 access point will be renamed"))

    def test_nothing_to_change_is_said_plainly(self):
        self.assertIn("Nothing to rename", self.out["none"])

    def test_duplicates_are_counted_in_the_sentence(self):
        self.assertIn("1 name used more than once", self.out["dupes"])

    def test_it_promises_only_a_copy(self):
        self.assertIn("your file is not changed", self.out["some"])


if __name__ == "__main__":
    unittest.main()
