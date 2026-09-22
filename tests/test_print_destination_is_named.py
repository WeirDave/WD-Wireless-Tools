"""The Print step says which destination keeps the file name.

He printed a report through **Microsoft Print to PDF**: the document came out
correctly and the file name was not filled in. The name comes from
`document.title`, and only the destinations that read the page use it -
Firefox's own "Save to PDF" and "Save as PDF" in Chrome and Edge. "Microsoft
Print to PDF" and "Adobe PDF" are *printers*, and the Save dialog a printer
puts up names the file from the Windows print job, not from the page.

**It cannot be fixed from inside the page** - a page does not get to name a
printer's output file - so the fix is to say so where the choice is made. That
is worth more than silence about a difference he otherwise meets after saving.

What is held here: the hint exists, it is rendered rather than merely defined,
it names both halves - the destinations that keep the name and the ones that do
not - and it is not printed onto the report itself.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
REPORT_JS = WEB / "assets" / "js" / "report.js"
REPORT_HTML = WEB / "report.html"
CSS = WEB / "assets" / "wd-tools.css"
NODE_TIMEOUT_S = 120


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheHintSaysWhichDestinationKeepsTheName(unittest.TestCase):
    """`renderPrintHint` run for real, and the text read back out of it."""

    PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('  function renderPrintHint() {');
        if (a < 0) throw new Error('renderPrintHint moved');
        let b = a, depth = 0, seen = false;
        while (b < src.length && !(seen && depth === 0)) {
          if (src[b] === '{') { depth++; seen = true; }
          else if (src[b] === '}') depth--;
          b++;
        }
        const host = { innerHTML: '' };
        const ids = JSON.parse(process.argv[2]);
        global.document = {
          getElementById: (id) => (ids.indexOf(id) > -1 ? host : null),
        };
        eval(src.slice(a, b));
        renderPrintHint();
        console.log(JSON.stringify(host.innerHTML));
    """

    def hint(self, ids=None):
        if ids is None:
            ids = sorted(set(re.findall(r'id="([^"]+)"',
                                        REPORT_HTML.read_text(encoding="utf-8"))))
        r = subprocess.run(
            ["node", "-e", self.PROBE, str(REPORT_JS), json.dumps(ids)],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_it_renders_into_an_element_the_page_really_has(self):
        """Run against only the ids `report.html` contains, so a hint written
        into an element nobody renders fails here rather than being invisible
        on screen."""
        self.assertTrue(
            self.hint(),
            "the hint renders nothing - either the element is missing from "
            "report.html or the id does not match")

    def test_it_names_the_destinations_that_keep_the_name(self):
        text = self.hint()
        for token in ("Save to PDF", "Save as PDF", "Firefox", "Chrome", "Edge"):
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_it_names_the_ones_that_do_not(self):
        """Naming only the good path leaves him to discover the other after
        saving, which is what happened."""
        text = self.hint()
        for token in ("Microsoft Print to PDF", "Adobe PDF"):
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_it_says_the_document_is_still_correct(self):
        """The printers produce the right report - only the name differs. A
        hint that reads as "do not use those" would send him back to a path he
        has no reason to avoid."""
        self.assertRegex(self.hint(), r"(?i)same document|produces the same")

    def test_no_escape_sequence_reaches_the_screen(self):
        """A single escape inside a JS string is an em dash by the time it
        renders and is fine; a doubled one is the defect this repository has
        hit three ways. Checked on the rendered text, which is the only place
        the difference shows."""
        text = self.hint()
        self.assertNotIn("\\u", text)
        self.assertIn("—", text, "the em dash did not survive")


class TheHintIsOnScreenAndNotOnThePaper(unittest.TestCase):
    def test_it_is_marked_not_to_print(self):
        """It sits beside the Print button, so without this it prints onto the
        report it is describing."""
        html = REPORT_HTML.read_text(encoding="utf-8")
        i = html.index('id="repPrintHint"')
        tag = html[html.rindex("<", 0, i):html.index(">", i) + 1]
        self.assertIn("noprint", tag,
                      "the print hint would print onto the report: " + tag)

    def test_it_has_a_style_of_its_own(self):
        """The rule, not a substring of one: renaming the selector to
        `.rep-print-hint-x` still contains `.rep-print-hint`, so the loose form
        passed while the hint had no styling at all."""
        css = CSS.read_text(encoding="utf-8")
        self.assertRegex(
            css, r"\.rep-print-hint\s*\{",
            "the print hint has no style rule, so it renders unstyled")


if __name__ == "__main__":
    unittest.main()
