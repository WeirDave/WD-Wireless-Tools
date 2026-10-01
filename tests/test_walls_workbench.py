"""Quick Walls in the workbench shell.

Part of the suite-wide refresh: "this style of layout is probably absolutely
how the rest of the tools should look as well". The 1-9 shortcuts are on the
rail, the wall types fill the middle, the template controls are in the panel
on the right, and "Save the *.esx" is in a footer that never scrolls away,
beside a sentence saying what it will write.

* Each piece is where the shell puts it, read from the page as built.
* The footer's sentence is the real `willWriteText`, run in Node: it names
  the file Save writes, counts the wall types and only the shortcuts that
  Save keeps (1-9), and promises a copy.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "web" / "walls.html"
JS = ROOT / "web" / "assets" / "js" / "walls.js"


class _Parents(HTMLParser):
    VOID = {"input", "br", "img", "meta", "link", "hr", "source"}

    def __init__(self):
        super().__init__()
        self.stack, self.where = [], {}

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        name = (d.get("class") or "").split(" ")[0] or d.get("id") or tag
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
    def test_the_shortcuts_are_on_the_rail(self):
        self.assertIn("pb-rail", _where()["hotkeySlots"])

    def test_the_wall_types_are_in_the_middle(self):
        self.assertIn("pb-main", _where()["wallList"])

    def test_the_template_controls_are_in_the_panel(self):
        w = _where()
        for ident in ("templateSelect", "tplApplyBtn", "autoApplyCheck"):
            with self.subTest(id=ident):
                self.assertIn("pb-panel", w[ident])

    def test_save_is_in_the_footer_outside_the_columns(self):
        w = _where()
        self.assertIn("pb-footer", w["saveBtn"])
        self.assertNotIn("pb-body", w["<footer>"])


PROBE = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('function willWriteText(name, types) {');
if (a < 0) throw new Error('willWriteText moved');
let b = a, depth = 0, seen = false;
while (b < src.length && !(seen && depth === 0)) {
  if (src[b] === '{') { depth++; seen = true; } else if (src[b] === '}') depth--;
  b++;
}
eval(src.slice(a, b));
const t = k => ({ keybindNumber: k });
console.log(JSON.stringify({
  none: willWriteText('', [t(1)]),
  some: willWriteText('invented.esx', [t(1), t(2), t(0), t(12), {}]),
  one: willWriteText('invented.esx', [t(3)]),
}));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheFooterSaysWhatSaveWrites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", PROBE, str(JS)], capture_output=True,
                           encoding="utf-8", timeout=60)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_nothing_open_says_nothing(self):
        self.assertEqual(self.out["none"], "")

    def test_it_names_the_file_save_writes(self):
        self.assertIn("invented_modified.esx", self.out["some"])

    def test_it_counts_only_the_shortcuts_save_keeps(self):
        """Save drops a keybind outside 1-9, so the sentence does not count one."""
        self.assertIn("5 wall types and 2 shortcuts", self.out["some"])
        self.assertIn("1 wall type and 1 shortcut.", self.out["one"])

    def test_it_promises_only_a_copy(self):
        self.assertIn("Your file is not changed", self.out["some"])


if __name__ == "__main__":
    unittest.main()
