"""The Report's "Back to top" button.

Print lives in the bar above the first sheet, and a report runs to dozens of
sheets, so reaching Print from the bottom meant scrolling the whole document
back up. A floating button appears once that bar has scrolled away and takes
the page back to it.

What is held here, by running the real code rather than reading it:

* the handler the button's `data-fn` names is defined by `report.js`, and
  calling it scrolls the window to the top;
* it appears only on the review stage, and only once scrolled past the bar;
* it is `noprint` - a `position: fixed` element otherwise prints on sheet one.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"
REPORT_HTML = ROOT / "web" / "report.html"
NODE = shutil.which("node")


class _FindButton(HTMLParser):
    def __init__(self):
        super().__init__()
        self.attrs = None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if d.get("id") == "repToTop":
            self.attrs = d


def _button():
    p = _FindButton()
    p.feed(REPORT_HTML.read_text(encoding="utf-8"))
    if p.attrs is None:
        raise AssertionError("report.html has no #repToTop")
    return p.attrs


PROBE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(marker) {
  const a = src.indexOf(marker);
  if (a < 0) throw new Error('moved: ' + marker);
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
const a = src.indexOf('  var TO_TOP_AFTER_PX');
if (a < 0) throw new Error('TO_TOP_AFTER_PX moved');
const constLine = src.slice(a, src.indexOf('\n', a));

const scrolls = [], listeners = {};
const btn = { hidden: true };
const stages = {};
['stageTemplate', 'stageConfigure', 'stageReview'].forEach(id => {
  stages[id] = { setAttribute() {}, removeAttribute() {} };
});
const window = {
  scrollY: 0,
  scrollTo(o) { scrolls.push(o); },
  addEventListener(ev, fn) { listeners[ev] = fn; },
};
const document = {
  getElementById(id) { return id === 'repToTop' ? btn : (stages[id] || null); },
};
var currentStage = 'template', configureDirty = false;
var STAGE_ORDER = ['template', 'configure', 'review'], STAGE_ELS = {};
function updateStepper() {}
function renderReport() {}
function syncDocTitle() {}

eval(constLine);
eval(slice('  function showStage(name) {'));
eval(slice('  function syncToTopButton() {'));
eval(slice('  window.scrollReportToTop = function () {'));
eval("window.addEventListener('scroll', syncToTopButton, { passive: true });");

const out = {};
showStage('review');
out.reviewAtTop = btn.hidden;
window.scrollY = 3000; listeners.scroll();
out.reviewScrolled = btn.hidden;
window.scrollY = 50; listeners.scroll();
out.reviewBackUp = btn.hidden;
window.scrollY = 3000; showStage('configure');
out.configureScrolled = btn.hidden;
scrolls.length = 0;
const fn = process.argv[2];
if (typeof window[fn] !== 'function') throw new Error('data-fn names nothing: ' + fn);
window[fn]();
out.clickScrolls = scrolls;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "node is required")
class BackToTopRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run([NODE, "-e", PROBE, str(REPORT_JS),
                            _button().get("data-fn", "")],
                           capture_output=True, encoding="utf-8", timeout=60)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_hidden_on_review_until_scrolled_past_the_bar(self):
        self.assertTrue(self.out["reviewAtTop"])
        self.assertFalse(self.out["reviewScrolled"])
        self.assertTrue(self.out["reviewBackUp"])

    def test_hidden_on_other_stages_however_far_scrolled(self):
        self.assertTrue(self.out["configureScrolled"])

    def test_the_buttons_own_handler_scrolls_to_the_top(self):
        self.assertEqual(len(self.out["clickScrolls"]), 1)
        self.assertEqual(self.out["clickScrolls"][0]["top"], 0)


class TheButtonIsWired(unittest.TestCase):
    def test_it_is_a_call_action(self):
        self.assertEqual(_button().get("data-action"), "call")

    def test_it_starts_hidden_and_never_prints(self):
        b = _button()
        self.assertIn("hidden", b)
        self.assertIn("noprint", b.get("class", "").split())


if __name__ == "__main__":
    unittest.main()
