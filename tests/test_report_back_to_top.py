"""The Report's floating "Back to top" and "Print / Save PDF" buttons.

Print lives in the bar above the first sheet, and a report runs to dozens of
sheets, so reaching Print from the bottom meant scrolling the whole document
back up. Once that bar has scrolled away, a floating pair stands in for it:
Back to top, and a Print that runs the same handler as the bar's.

What is held here, by running the real code rather than reading it:

* the handler Back to top's `data-fn` names is defined by `report.js`, and
  calling it scrolls the window to the top;
* the floating Print calls exactly what the review bar's Print calls;
* the pair appears only on the review stage, and only once scrolled past the
  bar;
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


class _Markup(HTMLParser):
    """The floating group, its buttons, and the review bar's buttons."""

    def __init__(self):
        super().__init__()
        self.group = None
        self.floating, self.bar = [], []
        self._in = []  # stack of (tag, which) for open divs

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "div":
            which = None
            if d.get("id") == "repFloatActions":
                self.group, which = d, "floating"
            elif "rep-review-bar" in d.get("class", "").split():
                which = "bar"
            self._in.append(which or (self._in[-1] if self._in else None))
        elif tag == "button" and self._in and self._in[-1]:
            getattr(self, self._in[-1]).append(d)

    def handle_endtag(self, tag):
        if tag == "div" and self._in:
            self._in.pop()


def _markup():
    p = _Markup()
    p.feed(REPORT_HTML.read_text(encoding="utf-8"))
    if p.group is None:
        raise AssertionError("report.html has no #repFloatActions")
    return p


def _floating(label):
    m = _markup()
    hits = [b for b in m.floating if b.get("data-fn") and label(b)]
    if len(hits) != 1:
        raise AssertionError("expected one floating button, got %r" % hits)
    return hits[0]


def _to_top():
    return _floating(lambda b: b.get("data-fn") != _bar_print().get("data-fn"))


def _bar_print():
    hits = [b for b in _markup().bar if "btn-blue" in b.get("class", "").split()]
    if len(hits) != 1:
        raise AssertionError("expected one Print in the review bar, got %r" % hits)
    return hits[0]


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
  getElementById(id) { return id === 'repFloatActions' ? btn : (stages[id] || null); },
};
var currentStage = 'template', configureDirty = false;
var STAGE_ORDER = ['template', 'configure', 'review'], STAGE_ELS = {};
function updateStepper() {}
function renderReport() {}
function syncDocTitle() {}

eval(constLine);
eval(slice('  function showStage(name) {'));
eval(slice('  function syncFloatActions() {'));
eval(slice('  window.scrollReportToTop = function () {'));
eval("window.addEventListener('scroll', syncFloatActions, { passive: true });");

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
                            _to_top().get("data-fn", "")],
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


class TheButtonsAreWired(unittest.TestCase):
    def test_there_are_exactly_two(self):
        self.assertEqual(len(_markup().floating), 2)

    def test_back_to_top_is_a_call_action(self):
        self.assertEqual(_to_top().get("data-action"), "call")

    def test_floating_print_calls_what_the_bars_print_calls(self):
        bar = _bar_print()
        floating = [b for b in _markup().floating
                    if b.get("data-fn") == bar.get("data-fn")]
        self.assertEqual(len(floating), 1, "no floating Print")
        for k in ("data-action", "data-fn", "data-arg"):
            self.assertEqual(floating[0].get(k), bar.get(k), k)

    def test_the_group_starts_hidden_and_never_prints(self):
        g = _markup().group
        self.assertIn("hidden", g)
        self.assertIn("noprint", g.get("class", "").split())


if __name__ == "__main__":
    unittest.main()
