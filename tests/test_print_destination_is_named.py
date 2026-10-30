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
        const host = { innerHTML: '' };
        const ids = JSON.parse(process.argv[2]);
        global.document = {
          getElementById: (id) => (ids.indexOf(id) > -1 ? host : null),
        };
        // The note about sheet sizes belongs to Firefox 158 and later; this
        // is the text every other browser reads.
        var window = {};
        var navigator = { userAgent: 'node' };
        eval(slice('  function sheetsFollowTheDialog() {'));
        eval(slice('  function sheetSizeHint() {'));
        eval(slice('  function renderPrintHint() {'));
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


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class PressingPrintPutsTheNameOnTheClipboard(unittest.TestCase):
    """Microsoft Print to PDF leaves the File name box empty and a page cannot
    fill it, so Print / Save PDF copies the name for a Ctrl+V. The real
    `printReport` is run against recording stubs."""

    PROBE = r"""
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
        const copyFn = slice('  function copyDocNameForSaveDialog() {');
        const printFn = slice('  window.printReport = async function () {');
        const mode = process.argv[2];
        const calls = [];
        global.window = { print: () => calls.push('print') };
        global.WD = { toast: (m) => calls.push('toast:' + m) };
        global.document = {
          title: 'Report - AP Installation - Invented Site - v1',
          getElementById: () => ({ querySelectorAll: () => [] }),
        };
        // Node 21+ makes `navigator` a read-only getter on global.
        Object.defineProperty(global, 'navigator', { configurable: true, value:
          mode === 'none' ? {} : { clipboard: { writeText: (t) => {
            calls.push('copy:' + t);
            return mode === 'refuse' ? Promise.reject(new Error('denied')) : Promise.resolve();
          } } } });
        global.syncDocTitle = () => calls.push('sync');
        global.collectOpts = () => ({});
        global.applyAntennaSegmentCrop = () => Promise.resolve();
        eval(copyFn);
        eval(printFn);
        (async () => {
          await window.printReport();
          await new Promise((r) => setTimeout(r, 20));
          console.log(JSON.stringify(calls));
        })().catch((e) => { console.error(e); process.exit(1); });
    """

    def run_print(self, mode):
        r = subprocess.run(
            ["node", "-e", self.PROBE, str(REPORT_JS), mode],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_title_is_copied_after_it_is_settled_and_before_the_dialog(self):
        calls = self.run_print("ok")
        title = "Report - AP Installation - Invented Site - v1"
        self.assertIn("copy:" + title, calls)
        self.assertLess(calls.index("sync"), calls.index("copy:" + title))
        self.assertLess(calls.index("copy:" + title), calls.index("print"))

    def test_it_says_it_was_copied(self):
        self.assertTrue(any(c.startswith("toast:") and "Ctrl+V" in c
                            for c in self.run_print("ok")))

    def test_a_refused_clipboard_never_stops_the_print(self):
        calls = self.run_print("refuse")
        self.assertIn("print", calls)
        self.assertFalse(any(c.startswith("toast:") for c in calls),
                         "claimed a copy that was refused")

    def test_no_clipboard_api_never_stops_the_print(self):
        self.assertIn("print", self.run_print("none"))


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
