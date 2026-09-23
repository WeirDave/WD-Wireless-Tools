"""A site's header counts the rows underneath it, not the site.

"at the top it says three files, one needs a decision, and I only see one
file. So where are the three files? I don't get what that's about."

With "out of sync" applied, the site header said `3 files · 1 needs a decision`
while exactly one row was drawn. The other two were in sync and correctly
hidden - so the header was true about the site and false about the screen, and
the screen is the thing he is reading. He was left doing arithmetic against a
list that could not produce the number.

`siteDigest` counted every child; `renderTreeChildren` drew the ones that
survived `passOwner` and `passFilter`. Two different questions sharing one
line.

Driven through the **real** `renderSitesTree`, with the real filters, and the
header is read back out of the rendered markup and compared against the rows
rendered beneath it. Asserting that the digest calls a filter would pass with
the counting still wrong.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120

PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const FILTER = process.argv[2];

function fakeEl() {
  return {
    innerHTML: '', textContent: '', value: '', checked: false, hidden: false,
    dataset: {}, style: {},
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){}, removeEventListener(){}, setAttribute(){},
    getAttribute(){ return null; }, removeAttribute(){}, closest(){ return null; },
    querySelector(){ return null; }, querySelectorAll(){ return []; },
    appendChild(){}, remove(){}, focus(){}, click(){}, scrollIntoView(){},
    getBoundingClientRect(){ return { top: 0, left: 0, width: 0, height: 0 }; },
    children: [], parentElement: null, offsetWidth: 0, offsetHeight: 0,
  };
}
const sandbox = {
  console, JSON, Math, Date, Map, Set, Promise, RegExp, Intl,
  setTimeout, clearTimeout, setInterval, clearInterval,
  document: {
    getElementById(){ return fakeEl(); }, querySelector(){ return fakeEl(); },
    querySelectorAll(){ return []; }, createElement(){ return fakeEl(); },
    addEventListener(){}, body: fakeEl(), documentElement: fakeEl(),
  },
  navigator: { platform: 'Win32', clipboard: { writeText: async () => {} } },
  location: { href: 'file:///cloud.html', search: '', hash: '' },
  localStorage: { getItem: () => null, setItem(){}, removeItem(){} },
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  alert(){}, confirm(){ return true; }, prompt(){ return null; },
  requestAnimationFrame: (f) => setTimeout(f, 0),
  WD: {
    esc: s => String(s == null ? '' : s).replace(/[&<>"]/g,
      c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])),
    applyVersions(){}, toast(){},
  },
};
sandbox.WD.escAttr = sandbox.WD.esc;
sandbox.WD.escJsStr = s => String(s == null ? '' : s).replace(/['\\]/g, '\\$&');
sandbox.window = sandbox;
vm.createContext(sandbox);
try {
  vm.runInContext(source, sandbox, { filename: 'cloud.js' });
} catch (err) {
  if (!/addEventListener|null|undefined/.test(err.message)) throw err;
}

// ------------------------------------------------ the site he was looking at
const OWNER = 'survey.lead@example.invalid';
const SITE = 'A100 Riverside Block';
const proj = (n, stale, how) => ({
  cloud: { id: 'c' + n, name: SITE + ' - Survey ' + n, owner: OWNER,
           hasSite: true, meta: '2 hr ago', siteName: SITE, sharedWith: [] },
  local: { path: 'D:\\Ekahau\\' + SITE + '\\' + SITE + ' - Survey ' + n + '.esx',
           name: SITE + ' - Survey ' + n, folder: SITE, meta: '14 Aug' },
  matchType: how || 'id', staleness: stale || null, namesDiffer: false,
  differenceKind: null,
});

/* Three files in the site; one is out of sync and one is paired on its name
   alone. Two different filters therefore hide two different pairs of rows,
   which is what makes this a test about the counting rather than about one
   filter. */
const children = { matched: [proj(1, null), proj(2, 'cloud_newer'),
                             proj(3, null, 'exact')],
                   cloudOnly: [], localOnly: [] };
// `MANY` makes the site look like the list he is actually working through, so
// the band that offers the whole open question at once has something to offer.
if (process.argv[3] === 'many') {
  for (let n = 10; n < 16; n++) children.matched.push(proj(n, 'cloud_newer'));
}
const site = { id: 's1', name: SITE, owner: OWNER, hasSite: true,
               meta: '2 hr ago', children, sharedWith: [] };

vm.runInContext(
  'data = ' + JSON.stringify({
    currentUser: OWNER, summary: { matched: 1 },
    matched: [{ cloud: site,
                local: { path: 'D:\\Ekahau\\' + SITE, name: SITE, isDir: true,
                         meta: '14 Aug', children },
                matchType: 'id', staleness: null, namesDiffer: false }],
    cloudOnly: [], localOnly: [], orphans: { cloudOnly: [], localOnly: [] },
  }) + ';'
  + "currentTab = 'sites'; activeFilter = '" + FILTER + "'; activeLetter = '';"
  + 'collapsed = new Set();',
  sandbox);

const html = vm.runInContext('renderLedger(function () { return true; })', sandbox);

const strip = (s) => s.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&')
                      .replace(/&middot;|·/g, '·').replace(/\s+/g, ' ').trim();

const digest = (() => {
  const m = /<span class="cell-meta site-digest[^"]*"[^>]*>([\s\S]*?)<\/span>\s*(?=<)/.exec(html);
  return m ? strip(m[1]) : '';
})();

// Count the project rows actually drawn under the site.
const childRows = (html.match(/<div class="ledger-row tree-child /g) || []).length;

// The band offering the whole open question at once.
const barMatch = /<div class="uncompared-bar">([\s\S]*?)<\/div>\s*<div class="ledger/.exec(html);
const bar = barMatch ? strip(barMatch[1]) : '';

console.log(JSON.stringify({
  digest,
  childRows,
  numbersInDigest: (digest.match(/\d+/g) || []).map(Number),
  saysNeedsADecision: /needs? a decision/.test(digest),
  bar,
  barIsAboveTheLedger: html.indexOf('uncompared-bar') >= 0
    && html.indexOf('uncompared-bar') < html.indexOf('<div class="ledger'),
  barRunsAComparison: /data-fn="checkAllUncompared"/.test(html),
  uncomparedPairs: vm.runInContext('_uncomparedNow.length', sandbox),
}));
"""


def _render(active_filter: str, many: bool = False) -> dict:
    node = shutil.which("node")
    if not node:  # pragma: no cover
        raise unittest.SkipTest("node is not available")
    r = subprocess.run([node, "-e", PROGRAM, str(CLOUD_JS), active_filter,
                        "many" if many else "few"],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError("render failed:\n" + (r.stderr or "")[-3000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


class TheHeaderCountsWhatIsOnScreenTests(unittest.TestCase):

    def test_with_no_filter_it_counts_the_whole_site(self):
        """Unfiltered, the site and the screen are the same thing."""
        got = _render("all")
        self.assertEqual(3, got["childRows"])
        self.assertEqual(got["childRows"], got["numbersInDigest"][0])
        self.assertIn("3 files", got["digest"])
        self.assertNotIn(" of ", got["digest"],
                         "nothing is being filtered, so nothing is a selection")
        self.assertTrue(got["saysNeedsADecision"], got["digest"])

    def test_under_a_filter_no_number_exceeds_the_rows_on_screen(self):
        """The defect, stated as the arithmetic he tried to do.

        He read `3 files · 1 needs a decision` above a single row. Whatever the
        line says, he must be able to find every number in it by looking down
        the list.
        """
        got = _render("stale")
        self.assertEqual(1, got["childRows"], "the fixture should hide two rows")
        # The first number in the line is the one he reads as "how many files
        # am I looking at", so that is the one that has to be the rows.
        self.assertEqual(
            got["childRows"], got["numbersInDigest"][0],
            f"the header opens with {got['numbersInDigest'][0]} over "
            f"{got['childRows']} row(s): {got['digest']!r}",
        )

    def test_under_a_filter_it_says_it_is_showing_a_selection(self):
        """Dropping the site total would answer the arithmetic and lose the
        context. Both numbers stay, and the line says which is which."""
        got = _render("stale")
        self.assertRegex(
            got["digest"], r"\b1 of 3 files\b",
            f"the header does not say it is showing a selection: {got['digest']!r}",
        )

    def test_the_decision_count_is_also_about_the_visible_rows(self):
        """`1 needs a decision` happens to be right here because the filter is
        the decision filter. It has to be right because it was counted from the
        rows, not because the two agreed by luck."""
        got = _render("name-matches")
        self.assertEqual(
            got["childRows"], got["numbersInDigest"][0],
            f"{got['digest']!r} over {got['childRows']} row(s)")
        # And nothing in the line claims more decisions than there are rows.
        for n in got["numbersInDigest"][1:]:
            if n != 3:  # 3 is the site total, which the line labels as such
                self.assertLessEqual(n, got["childRows"], got["digest"])


class TheWholeOpenQuestionIsOfferedOnceTests(unittest.TestCase):
    """"not compared yet" is honest and it is not a place to leave him across
    ninety projects. He has said he will not recheck things twice, and being
    told the answer is unknown row after row is a version of that.

    It is **offered**, not done: a comparison downloads that project's cloud
    copy, so running it automatically over a list this size would pull tens or
    hundreds of megabytes off Ekahau, on a work network, unasked. Read-only is
    not the same as free.
    """

    def test_a_list_of_open_questions_gets_one_control_for_all_of_them(self):
        got = _render("stale", many=True)
        self.assertEqual(7, got["uncomparedPairs"],
                         "the fixture's open rows were not collected")
        self.assertIn("Check all 7", got["bar"], got["bar"])
        self.assertTrue(got["barRunsAComparison"],
                        "the band names no action")

    def test_the_band_says_how_many_and_what_is_unknown(self):
        got = _render("stale", many=True)
        self.assertIn("7", got["bar"])
        self.assertIn("unknown", got["bar"].lower(), got["bar"])

    def test_it_sits_above_the_list_rather_than_in_it(self):
        """The held-back band made this mistake first: rendered inside the
        ledger, the DOM said it was one of the rows and it read as one."""
        got = _render("stale", many=True)
        self.assertTrue(got["barIsAboveTheLedger"])

    def test_one_open_row_gets_no_banner(self):
        """Its own button is closer than a banner about it."""
        got = _render("stale")
        self.assertEqual(1, got["uncomparedPairs"])
        self.assertEqual("", got["bar"], got["bar"])

    def test_rows_that_have_been_answered_are_not_offered_again(self):
        """Rechecking what is already settled is the complaint this is
        supposed to relieve, not repeat. With nothing stale and nothing
        unanswered there is nothing to offer."""
        got = _render("name-matches")
        self.assertEqual(0, got["uncomparedPairs"])
        self.assertEqual("", got["bar"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
