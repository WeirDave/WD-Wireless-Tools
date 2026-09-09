"""Warn before printing a mixed-orientation report on an engine that cannot.

Mixing orientations within one document is delivered by named `@page` rules.
Chromium implements them - six pages and three switches, verified against a
generated PDF, with the base margins inherited. Firefox implements none of it:
every sheet takes the print dialog's orientation, so a page laid out for the
other one loses its right-hand edge.

That failure is silent. It cost a day, and a drawing with access points missing
off the side nearly reached a construction crew. The release note is not where
that warning belongs - it belongs at the moment someone presses Print.

Three things keep it from becoming a nag:

* it asks the **engine**, not the user agent - the question is what the browser
  can do, not what it is called;
* it only fires when the document **actually mixes**, so a uniform report is
  silent everywhere; and
* it says nothing when the capability cannot be *determined* - a CSS.supports
  that throws is an unknown, and warning on an unknown teaches people to click
  through warnings. A browser with no CSS API at all is not an unknown: it
  definitely cannot do this, so it is warned.

On Chrome nobody ever sees it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"
NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
const block = slice('function enginePrintsOneOrientationOnly()',
                    '\n  window.printReport');

// A host whose pages we can shape per case.
function hostWith(landscape, portrait) {
  const pages = [];
  for (let i = 0; i < landscape; i++) pages.push({ classList: { contains: () => true } });
  for (let i = 0; i < portrait; i++) pages.push({ classList: { contains: () => false } });
  return { querySelectorAll: () => pages };
}
globalThis.window = globalThis;

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
"""


def run(checks: str) -> subprocess.CompletedProcess:
    program = PRELUDE + "eval(block + " + json.dumps(checks) + ");"
    return subprocess.run(["node", "-e", program, str(REPORT_JS)],
                          capture_output=True, text=True, timeout=NODE_TIMEOUT_S)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class MixedOrientationWarning(unittest.TestCase):
    def check(self, body: str):
        r = run(body)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr).strip())

    def test_chromium_is_never_warned(self):
        """It can mix, so there is nothing to say - however mixed the report."""
        self.check("""
          globalThis.CSS = { supports: () => true };
          check('warned a browser that can mix',
                mixedOrientationWarning(hostWith(5, 3)) === '');
          done();
        """)

    def test_an_engine_that_cannot_mix_is_warned_with_the_counts(self):
        self.check("""
          globalThis.CSS = { supports: () => false };
          const w = mixedOrientationWarning(hostWith(5, 3));
          check('no warning on an engine that cannot mix: ' + w, !!w);
          check('did not say how many of each: ' + w,
                /5 landscape/.test(w) && /3 portrait/.test(w));
          check('did not name the consequence: ' + w, /cut off/.test(w));
          check('did not point at the way out: ' + w, /Match all pages/.test(w));
          check('did not name a browser that can: ' + w, /Chrome or Edge/.test(w));
          done();
        """)

    def test_a_uniform_report_is_silent_everywhere(self):
        """The whole point of "Match all pages" is to reach this state, so
        reaching it must stop the warning."""
        self.check("""
          globalThis.CSS = { supports: () => false };
          check('warned about an all-landscape report',
                mixedOrientationWarning(hostWith(6, 0)) === '');
          check('warned about an all-portrait report',
                mixedOrientationWarning(hostWith(0, 6)) === '');
          check('warned about a report with no orientable pages',
                mixedOrientationWarning(hostWith(0, 0)) === '');
          done();
        """)

    def test_it_asks_the_engine_not_the_user_agent(self):
        self.check("""
          let askedFor = null;
          globalThis.CSS = { supports: (p, v) => { askedFor = p + ':' + v; return true; } };
          enginePrintsOneOrientationOnly();
          check('did not feature-test the page property: ' + askedFor,
                askedFor === 'page:auto');
          done();
        """)

    def test_an_unanswerable_question_says_nothing(self):
        """A throwing CSS.supports is an unknown, and warning on an unknown is
        how people learn to click through warnings."""
        self.check("""
          globalThis.CSS = { supports: () => { throw new Error('nope'); } };
          check('nagged when the capability could not be determined',
                mixedOrientationWarning(hostWith(2, 2)) === '');
          done();
        """)

    def test_a_browser_with_no_css_api_is_warned(self):
        """Not the same as an unknown. No CSS API means it definitely cannot
        mix, so the warning is the correct answer rather than a guess."""
        self.check("""
          globalThis.CSS = undefined;
          const w = mixedOrientationWarning(hostWith(2, 2));
          check('stayed silent on a browser that certainly cannot mix', !!w);
          done();
        """)


class WarningIsWired(unittest.TestCase):
    def test_print_asks_before_it_prints(self):
        js = REPORT_JS.read_text(encoding="utf-8")
        start = js.index("window.printReport = async function ()")
        body = js[start:js.index("window.print()", start)]
        self.assertIn("mixedOrientationWarning(", body)
        self.assertIn("window.confirm(", body)
        self.assertIn("return;", body,
                      "declining the warning has to actually stop the print")


if __name__ == "__main__":
    unittest.main()
