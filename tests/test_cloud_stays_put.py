"""The morning it stopped loading, and the three things around it.

"load failed can't access properly hidden document get element by ID is null"

`updateDashboard` set `.hidden` on five ids that v2.113.0 had deleted. It sits
between the data arriving and the list being drawn, so the throw took
`renderRows()` with it and the page stopped at "Loading" under a header. Four
releases, on the build he installs.

**Why it looked intermittent.** `refreshData` fires `get_data` and
`refreshDupIndex()` in parallel, and the duplicate-index handler ends with its
own `renderRows()`. That call was never meant to draw the list - it exists to
colour duplicate hints - but with `onData` throwing first it was the only thing
that ever did. Whether the page came up depended on which of two requests
answered second. With ninety-eight sites `get_data` is the slow one, so mostly
it did not.

**Why it came up on All.** The only other path that draws the list is the
owner-filter reset, which runs before the throw.

Everything below is one of those threads, driven rather than read.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
CLOUD_HTML = ROOT / "web" / "cloud.html"
NODE_TIMEOUT_S = 120

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function cut(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}

const said = [];
const logged = [];
globalThis.console = Object.assign({}, console, {
  error: (...a) => logged.push(a.map(String).join(' ')),
  warn: (...a) => logged.push(a.map(String).join(' ')),
});
function toast(m) { said.push(String(m)); }

const bar = { hidden: true, _text: '', querySelector: () => bar._msg };
bar._msg = { get textContent() { return bar._text; },
             set textContent(v) { bar._text = v; } };
const rows = { innerHTML: '' };
globalThis.document = {
  getElementById: (id) => (id === 'staleDataBar' ? bar
                        : id === 'rowsContainer' ? rows : null),
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  scrollingElement: { scrollTop: 0 },
  documentElement: { scrollTop: 0 },
};
globalThis.window = globalThis;

let currentTab = 'sites';
let data = null;
const drawn = [];
"""


def run(body: str, extra: str = "") -> dict:
    program = HARNESS + extra + "\n" + body
    r = subprocess.run(["node", "-e", program, str(CLOUD_JS), str(CLOUD_HTML)],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout.strip().splitlines()[-1])


needs_node = unittest.skipUnless(shutil.which("node"), "Node.js is not installed")


@needs_node
class ABackgroundPollNeverTakesAwayWhatHeIsReading(unittest.TestCase):
    """"I set it on Mine, and when I set it on Mine there was some files up top
    that needed to be assigned, and I was reading through them and then it
    automatically just had those files go away."

    Live re-pulls every nine seconds and the list was rebuilt from whatever came
    back. The held-back candidates are recomputed by the matcher on every call,
    so the rows he was working through could simply stop existing mid-sentence.
    He had not clicked anything.

    And fixing the load throw made this *more* likely, not less: with the throw
    gone, the background re-render now happens reliably every nine seconds
    instead of dying before it.
    """

    SETUP = r"""
eval(cut('let _pendingData = null;', '\nfunction onDuplicates(')
   .replace(/indexRowData/g, 'stubIndex')
   .replace(/reconcileOwnerFilterWithData/g, 'stubReconcile')
   .replace(/closeSitesOnFirstSight/g, 'stubClose')
   .replace(/updateDashboard/g, 'stubDash')
   .replace(/renderRows/g, 'stubRender'));
function stubIndex() {} function stubReconcile() {} function stubClose() {}
function stubDash() {}
function stubRender() { drawn.push(_viewFingerprint(data)); }
function _step(what, fn) { fn(); }

function payload(heldBackIds) {
  return JSON.stringify({
    currentUser: 'me@example.com',
    matched: [{ cloud: { id: 's1', name: 'Site', children: {
                  matched: [], cloudOnly: [], localOnly: [],
                  heldBack: heldBackIds.map(i => ({ cloud: { id: i },
                                                    local: { path: '/l/a.esx' } })) } },
                local: { path: '/l/Site', name: 'Site' },
                matchType: 'exact', namesDiffer: false, staleness: null }],
    cloudOnly: [], localOnly: [], orphans: {},
  });
}
"""

    def test_a_poll_that_found_nothing_new_does_not_redraw(self):
        out = run("""
          onData('sites', payload(['a', 'b']));            // the first real load
          const after = drawn.length;
          onData('sites', payload(['a', 'b']), { background: true });
          console.log(JSON.stringify({ first: after, then: drawn.length,
                                       bar: bar.hidden }));
        """, self.SETUP)
        self.assertEqual(1, out["first"])
        self.assertEqual(1, out["then"], "an identical poll redrew the list anyway")
        self.assertTrue(out["bar"], "it offered changes that do not exist")

    def test_a_poll_that_found_something_waits_to_be_asked(self):
        """The rows stay exactly as they are until he says otherwise."""
        out = run("""
          onData('sites', payload(['a', 'b']));
          onData('sites', payload(['a']), { background: true });   // one vanished
          console.log(JSON.stringify({
            drawn: drawn.length,
            stillShowing: _viewFingerprint(data),
            bar: bar.hidden, text: bar._text,
          }));
        """, self.SETUP)
        self.assertEqual(1, out["drawn"], "the background poll rewrote the page")
        self.assertIn("ha", out["stillShowing"],
                      "the row he was reading was dropped from what is drawn")
        self.assertFalse(out["bar"], "nothing told him there was anything new")
        self.assertTrue(out["text"].strip(), "the bar says nothing")

    def test_and_applies_it_the_moment_he_asks(self):
        out = run("""
          onData('sites', payload(['a', 'b']));
          onData('sites', payload(['a']), { background: true });
          applyPendingData();
          console.log(JSON.stringify({ drawn: drawn.length,
                                       showing: _viewFingerprint(data),
                                       bar: bar.hidden }));
        """, self.SETUP)
        self.assertEqual(2, out["drawn"])
        self.assertNotIn("hb", out["showing"])
        self.assertTrue(out["bar"])

    def test_a_load_he_asked_for_still_renders_immediately(self):
        """Switching tab, pressing refresh, finishing an operation - those are
        his own actions and must not queue up behind a bar."""
        out = run("""
          onData('sites', payload(['a']));
          onData('sites', payload(['a', 'b']));      // no background flag
          console.log(JSON.stringify({ drawn: drawn.length, bar: bar.hidden }));
        """, self.SETUP)
        self.assertEqual(2, out["drawn"])
        self.assertTrue(out["bar"])


class TheListIsNotHostageToTheCountersAboveIt(unittest.TestCase):
    """One stale element id cost him the whole tool for four releases, because
    five calls sat in a row on the only path to the list."""

    JS = CLOUD_JS.read_text(encoding="utf-8")

    def test_every_step_of_the_load_runs_on_its_own(self):
        body = self.JS[self.JS.index("function onData(kind, jsonStr, opts)"):]
        body = body[:body.index("\nfunction _step(")]
        for step in ("indexRowData", "reconcileOwnerFilterWithData",
                     "closeSitesOnFirstSight", "updateDashboard", "renderRows"):
            with self.subTest(step=step):
                self.assertIn("_step(", body)
                self.assertRegex(body, r"_step\([^)]*,\s*" + step + r"\)")

    def test_a_step_that_fails_is_reported_rather_than_swallowed(self):
        """Silence is how a broken counter survived four releases."""
        block = self.JS[self.JS.index("function _step(what, fn)"):]
        block = block[:block.index("\n}\n")]
        self.assertIn("console.error", block)
        self.assertIn("toast(", block)

    def test_it_does_not_shout_the_same_failure_every_nine_seconds(self):
        """Live polls. A toast per poll would be its own denial of service."""
        block = self.JS[self.JS.index("function _step(what, fn)"):]
        block = block[:block.index("\n}\n")]
        self.assertIn("_stepFailures", block)

    def test_the_duplicate_index_no_longer_draws_the_list(self):
        """It was never meant to. With `onData` throwing it became the only
        thing that did, and whether the page appeared came down to which of two
        parallel requests answered second."""
        block = self.JS[self.JS.index("function refreshDupIndex()"):]
        block = block[:block.index("\n}")]
        self.assertIn("!_pendingData", block)


@needs_node
class TheWholeSiteRowOpensTheSite(unittest.TestCase):
    """"it seems the only way I can expand a site is to use the chevron, which
    really seems crazy."

    Ninety-eight sites, a 20px target, and the most frequent action there is.
    """

    SETUP = r"""
const listeners = {};
globalThis.document.addEventListener = (kind, fn) => {
  (listeners[kind] = listeners[kind] || []).push(fn);
};
const toggled = [];
function toggleFolder(k) { toggled.push(k); }

eval(cut('function _wireRowToggle()', '\nfunction _wireDisabledBulkReasons('));
// The slice ends with cloud.js's own `_wireRowToggle();`, so calling it
// again would register every listener twice - and every click would open
// the site and close it straight back.

/* A target that reports what it is inside, the way `closest` does. */
function target(chain, toggleKey) {
  return {
    closest: (sel) => {
      if (sel.indexOf('.ledger-row.is-openable') === 0) {
        return toggleKey ? { dataset: { toggle: toggleKey } } : null;
      }
      return chain.some(c => sel.indexOf(c) >= 0) ? {} : null;
    },
  };
}
function fire(kind, ev) { (listeners[kind] || []).forEach(fn => fn(ev)); }
function evt(t, extra) {
  return Object.assign({ target: t, preventDefault() { this._d = true; },
                         stopPropagation() { this._s = true; } }, extra || {});
}
"""

    def test_a_click_anywhere_on_the_row_opens_it(self):
        out = run("""
          fire('click', evt(target([], 'site:s1')));
          console.log(JSON.stringify({ toggled }));
        """, self.SETUP)
        self.assertEqual(["site:s1"], out["toggled"])

    def test_it_does_not_swallow_the_controls_inside_it(self):
        """The checkbox, the row menu and every button already mean something.
        A control that sometimes does its job and sometimes opens a site is
        worse than no control."""
        for inside in ("input", "button", "a", "label", "summary", ".row-menu"):
            with self.subTest(control=inside):
                out = run("""
                  fire('click', evt(target(['%s'], 'site:s1')));
                  console.log(JSON.stringify({ toggled }));
                """ % inside, self.SETUP)
                self.assertEqual([], out["toggled"], inside + " was swallowed")

    def test_the_keyboard_opens_it_too(self):
        """It is the primary control on the page now."""
        out = run("""
          fire('keydown', evt(target([], 'site:s1'), { key: 'Enter' }));
          fire('keydown', evt(target([], 'site:s2'), { key: ' ' }));
          fire('keydown', evt(target([], 'site:s3'), { key: 'a' }));
          console.log(JSON.stringify({ toggled }));
        """, self.SETUP)
        self.assertEqual(["site:s1", "site:s2"], out["toggled"])

    def test_a_double_click_does_not_toggle_twice(self):
        """Twice lands back where it started, which reads as nothing
        happening."""
        out = run("""
          const ev = evt(target([], 'site:s1'));
          fire('dblclick', ev);
          console.log(JSON.stringify({ toggled, prevented: !!ev._d }));
        """, self.SETUP)
        self.assertEqual([], out["toggled"])
        self.assertTrue(out["prevented"])

    def test_a_row_that_cannot_open_is_left_alone(self):
        """File rows are not sites and have nothing to expand."""
        out = run("""
          fire('click', evt(target([], null)));
          console.log(JSON.stringify({ toggled }));
        """, self.SETUP)
        self.assertEqual([], out["toggled"])


class TheRowLooksLikeSomethingYouCanPress(unittest.TestCase):
    """He found the chevron because it was the only thing that looked like a
    control. A row that acts like a button has to say that it is one.

    The stylesheet half - pointer cursor, hover, focus ring - is checked by
    looking at it in a browser rather than by asserting that three strings
    appear in a CSS file. A rule can be present and overridden, or present and
    invisible, and the assertion would pass either way; that is the shape
    `test_a_test_must_be_able_to_fail` exists to keep out.

    What is asserted here is the part that is a fact about the row rather than
    about its paint, and that assistive technology and the tooltip depend on.
    """

    JS = CLOUD_JS.read_text(encoding="utf-8")

    def test_it_says_what_it_is_to_a_screen_reader_and_a_tooltip(self):
        block = self.JS[self.JS.index('h += `<div class="ledger-row tree-parent is-openable'):]
        block = block[:block.index("${_det}`;")]
        self.assertIn('role="button"', block)
        self.assertIn('tabindex="0"', block)
        self.assertIn("aria-expanded=", block)
        self.assertIn("click anywhere on the row", block)


if __name__ == "__main__":
    unittest.main()
