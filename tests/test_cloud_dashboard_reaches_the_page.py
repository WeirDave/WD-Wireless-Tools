"""The summary line ran against the page it actually has to write into.

"At least before I understood what was going on even if it was ugly."

Every number at the top of Cloud Manager read `-` from v2.113.0 to v2.117.0.
`updateDashboard` set `.hidden` on `dDupAllCard`, `dDupMixedCard`,
`dDupLocalCard`, `dDupCloudCard` and `dUnassignedCard`; the header redesign
replaced those wrappers with buttons and menu items and the ids went with them.
Four statements in, `null.hidden` throws, and not one count is ever written.
The active-filter highlight went the same way - it was `.dash-card.active`, and
there are no `.dash-card`s - so narrowing the list to seven of a hundred rows
left nothing on screen saying a filter was on.

**Every test stayed green for four releases.** They had to: each one reads
cloud.js or cloud.html on its own, and neither file is wrong on its own. The
ids exist in the function. The buttons exist in the page. Only the relationship
between them was broken, and a relationship is not visible in either half.

So this runs the real function against the real markup. The DOM shim below is
deliberately thin and deliberately *strict*: `getElementById` returns an
element only for ids that genuinely appear in `web/cloud.html`, and null for
everything else, exactly as a browser does. That single property is the whole
test - anything the code reaches for and the page does not have, fails here.
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
CLOUD_HTML = ROOT / "web" / "cloud.html"
NODE_TIMEOUT_S = 120

PROGRAM = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const html = fs.readFileSync(process.argv[2], 'utf8');

function cut(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}

/* A DOM the size of the question.

   It is built from the real cloud.html, so an id the code reaches for exists
   here only if it exists on the page - which is the one property this test is
   for. Everything else is the minimum needed to let the real function run. */
function parse(markup) {
  const els = [];
  const tagRe = /<(button|span|div|input|details|summary|label)\b([^>]*)>/g;
  let m;
  while ((m = tagRe.exec(markup)) !== null) {
    const attrs = m[2];
    const id = (/\bid="([^"]+)"/.exec(attrs) || [])[1] || null;
    const filter = (/\bdata-filter="([^"]+)"/.exec(attrs) || [])[1] || null;
    const cls = ((/\bclass="([^"]+)"/.exec(attrs) || [])[1] || '').split(/\s+/).filter(Boolean);
    els.push(makeEl(m[1].toUpperCase(), id, filter, cls, m.index));
  }
  return els;
}

function makeEl(tag, id, filter, cls, at) {
  const classes = new Set(cls);
  const el = {
    tagName: tag, id: id || '', _at: at,
    dataset: filter ? { filter } : {},
    hidden: false, textContent: '-', _attrs: {},
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c),
      toggle: (c, on) => { if (on === undefined) on = !classes.has(c);
                           if (on) classes.add(c); else classes.delete(c); return on; },
    },
    _classes: classes,
    setAttribute: (k, v) => { el._attrs[k] = v; },
    getAttribute: (k) => (k in el._attrs ? el._attrs[k] : null),
    /* Scoped to this element, approximated by "everything up to the next
       element of the same kind". A menu item is a <button>, so the next
       <button> ends it; the filters menu is a <details>, so it runs to the end
       of the line. Enough for the queries the real code makes, and it fails
       loudly rather than quietly if that ever stops being true. */
    querySelector: (sel) => {
      for (const other of ELS) {
        if (other._at <= el._at) continue;
        if (other.tagName === el.tagName) break;
        if (matches(other, sel)) return other;
      }
      return null;
    },
  };
  return el;
}

const ELS = parse(html);
const byId = new Map(ELS.filter(e => e.id).map(e => [e.id, e]));

function matches(el, sel) {
  if (sel === '[data-filter]') return !!el.dataset.filter;
  let m = /^\[data-filter="([^"]+)"\]$/.exec(sel);
  if (m) return el.dataset.filter === m[1];
  m = /^\[data-filter\]\.([\w-]+)$/.exec(sel);
  if (m) return !!el.dataset.filter && el._classes.has(m[1]);
  if (sel.startsWith('.')) {
    return sel.slice(1).split('.').every(c => el._classes.has(c));
  }
  return false;
}

globalThis.document = {
  // Strict, exactly like a browser: an id the page does not carry is null.
  getElementById: (id) => byId.get(id) || null,
  querySelectorAll: (sel) => ELS.filter(e => matches(e, sel)),
  querySelector: (sel) => ELS.find(e => matches(e, sel)) || null,
};

globalThis.window = globalThis;
let currentTab = 'sites';
let activeFilter = 'all';
let dupData = null;
const _compareResults = new Map();
function _compareKey(c, l) {
  return String(c || '') + '\u0000' + String(l || '').replace(/\\/g, '/').toLowerCase();
}
function ownerFilter() { return 'all'; }
function renderOwnerFilterNotice() {}
// setFilter redraws the list; the shim has no list, only the header.
function renderRows() {}

function cloudOf(id, name, extra) {
  return Object.assign({ id, name, mtime: 200, owner: OWNER, siteName: '' }, extra || {});
}
function localOf(name, extra) {
  return Object.assign({ name, path: 'D:/E/' + name + '.esx', mtime: 100 }, extra || {});
}
let OWNER = 'me@example.com';

function pairOf(n, staleness, matchType, namesDiffer, extra) {
  return { cloud: cloudOf('c' + n, 'Project ' + n,
             Object.assign({ projectType: 'Measured' }, extra || {})),
           local: localOf('Project ' + n),
           matchType: matchType || 'id', staleness: staleness || null,
           namesDiffer: !!namesDiffer };
}

function listing(opts) {
  const o = opts || {};
  const kids = {
    matched: [pairOf(1), pairOf(2, 'cloud_newer'), pairOf(3, 'local_newer'),
              pairOf(4, null, 'exact'), pairOf(5, null, 'id', true)],
    cloudOnly: [cloudOf('co1', 'Cloud only 1')],
    localOnly: [localOf('Local only 1')],
    heldBack: [],
  };
  return {
    currentUser: ('currentUser' in o) ? o.currentUser : OWNER,
    summary: { matched: 2 },
    matched: [
      { cloud: cloudOf('s1', 'Site One', { children: kids }),
        local: localOf('Site One', { isDir: true, children: kids }),
        matchType: 'exact', namesDiffer: false, staleness: null },
    ],
    cloudOnly: [cloudOf('s3', 'Site Three', { children: kids })],
    localOnly: [localOf('Site Four', { isDir: true, children: kids })],
    orphans: { cloudOnly: [] },
  };
}

let data = listing();

eval(cut('function _markActiveFilter(', '\nfunction setFilter('));

const out = { runs: {} };

function run(label, mutate) {
  if (mutate) mutate();
  let threw = null;
  try { updateDashboard(); } catch (err) { threw = String((err && err.message) || err); }
  const counters = {};
  byId.forEach((el, id) => {
    if (/^d[A-Z]/.test(id)) counters[id] = String(el.textContent);
  });
  const active = ELS.filter(e => e._classes.has('active') && e.dataset.filter)
                    .map(e => e.dataset.filter);
  const hiddenFilters = ELS.filter(e => e.dataset.filter && e.hidden)
                           .map(e => e.dataset.filter);
  out.runs[label] = { threw, counters, active, hiddenFilters };
}

run('sites');
run('projects', () => { currentTab = 'projects'; });
run('duplicates', () => {
  currentTab = 'duplicates';
  dupData = { summary: { total: 6, mixed: 1, localOnly: 3, cloudOnly: 2 } };
});
run('filtered', () => {
  currentTab = 'sites'; dupData = null; activeFilter = 'stale';
});
run('menu-filter', () => { activeFilter = 'orphans-cloud'; });
run('no-current-user', () => {
  activeFilter = 'all';
  data = listing({ currentUser: '' });
});

/* Clicking a filter is what he actually does, so that is what is run. */
out.clicks = [];
function clickFilter(key) {
  setFilter(key);
  out.clicks.push({
    key,
    active: ELS.filter(e => e._classes.has('active') && e.dataset.filter)
               .map(e => e.dataset.filter),
    /* Through `.sum-more` itself: the shim resolves a descendant against an
       element, not a two-part selector string. */
    menuLabel: (() => {
      const more = document.querySelector('.sum-more');
      const btn = more && more.querySelector('.wd-menu-btn');
      return btn ? String(btn.textContent) : '';
    })(),
  });
}
activeFilter = 'all';
eval(cut('function setFilter(f) {', '\nfunction charDiff('));
clickFilter('stale');
clickFilter('mismatches');
clickFilter('orphans-cloud');     // one that lives in the dropdown
clickFilter('orphans-cloud');     // clicking it again clears it

console.log(JSON.stringify(out));
"""


def probe():
    """Run the header once and share the result.

    Module-level and cached, rather than one class's setUpClass reading an
    attribute off another test class - that only works while the classes happen
    to run in alphabetical order, and this repo has fallen into it three times.
    (Described rather than written out: the guard against that form matches its
    own documentation, which is how this docstring failed the first time.)
    """
    if getattr(probe, "_cache", None) is None:
        r = subprocess.run(["node", "-e", PROGRAM, str(CLOUD_JS), str(CLOUD_HTML)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        probe._cache = json.loads(r.stdout.strip().splitlines()[-1])
    return probe._cache


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheCountersActuallyReachThePage(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.runs = probe()["runs"]

    def test_it_does_not_throw_on_any_tab(self):
        """The whole defect in one assertion.

        It threw on `document.getElementById('dDupAllCard').hidden` and every
        count below that line was never written. Nothing caught it, nothing
        logged it, and the page looked fine apart from being full of dashes.
        """
        for label, run in self.runs.items():
            with self.subTest(tab=label):
                self.assertIsNone(run["threw"], "%s: %s" % (label, run["threw"]))

    def test_no_counter_is_left_as_a_dash_on_its_own_tab(self):
        """`-` is the markup's placeholder. A number means the code reached it."""
        expected = {
            "sites": ["dAll", "dMismatches", "dStale", "dNameMatches", "dOrphans",
                      "dCloudOnly", "dLocalOnly", "dExternal", "dUnshared",
                      "dTypeDesign", "dTypeMeasured", "dTypeHybrid"],
            "projects": ["dAll", "dUnassigned"],
            "duplicates": ["dDupAll", "dDupMixed", "dDupLocal", "dDupCloud"],
        }
        for tab, ids in expected.items():
            counters = self.runs[tab]["counters"]
            for i in ids:
                with self.subTest(tab=tab, counter=i):
                    self.assertIn(i, counters, i + " is not on the page at all")
                    self.assertNotEqual("-", counters[i],
                                        i + " was never written on the " + tab + " tab")

    def test_the_filter_in_force_is_marked_on_the_page(self):
        """It was `.dash-card.active` and there are no `.dash-card`s, so for
        four releases he could narrow a hundred rows to seven with nothing on
        screen saying why."""
        self.assertEqual(["all"], self.runs["sites"]["active"])
        self.assertEqual(["stale"], self.runs["filtered"]["active"])

    def test_a_filter_chosen_inside_the_menu_is_marked_too(self):
        """Otherwise it is invisible the moment the dropdown closes."""
        self.assertEqual(["orphans-cloud"], self.runs["menu-filter"]["active"])

    def test_the_duplicate_filters_are_hidden_off_their_own_tab(self):
        hidden = self.runs["sites"]["hiddenFilters"]
        for key in ("dup-all", "dup-mixed", "dup-local", "dup-cloud"):
            with self.subTest(filter=key):
                self.assertIn(key, hidden)

    def test_no_site_filter_is_offered_where_it_means_nothing(self):
        """`unassigned` is a projects-tab question - a site has no site."""
        self.assertIn("unassigned", self.runs["sites"]["hiddenFilters"])
        self.assertNotIn("unassigned", self.runs["projects"]["hiddenFilters"])

    def test_not_shared_hides_when_we_do_not_know_who_he_is(self):
        """Without a current user "yours" is unanswerable, so the filter would
        silently mean something else."""
        self.assertIn("unshared", self.runs["no-current-user"]["hiddenFilters"])
        self.assertNotIn("unshared", self.runs["sites"]["hiddenFilters"])

    def test_the_unshared_count_is_taken_through_the_owner_filter(self):
        """Otherwise the number on the control and the rows in the list
        disagree, which is the same lie in a smaller place."""
        src = CLOUD_JS.read_text(encoding="utf-8")
        block = src[src.index("let unsharedCount = 0;"):]
        block = block[:block.index("_setCount('dUnshared'")]
        self.assertIn("_passOwnerForCounts", block)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ClickingAFilterMovesTheHighlight(unittest.TestCase):
    """"when you click those it doesn't highlight that you're on those either
    ... some buttons where the highlights don't move."

    He read that as a half-finished design. It was a defect in the v2.118.0
    fix: the dead `.dash-card` line existed in *three* places and I converted
    two. The one I missed was `setFilter`, which is the one that runs on every
    click - so the highlight was painted correctly on load and then never moved
    again.
    """

    @classmethod
    def setUpClass(cls):
        cls.clicks = probe()["clicks"]

    def test_the_clicked_filter_becomes_the_marked_one(self):
        self.assertEqual(["stale"], self.clicks[0]["active"])
        self.assertEqual(["mismatches"], self.clicks[1]["active"])

    def test_only_one_filter_is_ever_marked(self):
        for c in self.clicks:
            with self.subTest(clicked=c["key"]):
                self.assertLessEqual(len(c["active"]), 1, c)

    def test_a_filter_that_used_to_live_in_the_dropdown_marks_itself(self):
        """"if you use the dropdown filters you don't know where you are."

        There is no dropdown. Every filter is a chip carrying its own count,
        and the one in force is the one that is highlighted - which is the
        answer he was asking for rather than a label on a closed menu.
        """
        self.assertEqual(["orphans-cloud"], self.clicks[2]["active"])

    def test_clicking_it_again_clears_it(self):
        """Single select: the active chip is a toggle back to All. He did not
        ask to combine filters, and the chips are shaped so they do not look
        as though he could."""
        self.assertEqual(["all"], self.clicks[3]["active"])


class NoSelectorAddressesSomethingThatIsNotThere(unittest.TestCase):
    """Why a fix aimed at exactly this bug missed three of its five sites.

    A class name in JavaScript is a relationship between two files, and every
    test in this suite reads one file at a time. `.dash-card` was removed from
    the markup in v2.113.0 and left in five places in the code, where it went
    on matching nothing - silently, because matching nothing is what
    `querySelectorAll` does when it has nothing to say.

    This checks the relationship instead: every class the ledger code selects
    on has to exist in the page it selects from.
    """

    JS = CLOUD_JS.read_text(encoding="utf-8")
    HTML = CLOUD_HTML.read_text(encoding="utf-8")

    @staticmethod
    def _code_only(js: str) -> str:
        """Comments explain what a selector used to be, which is not a use.

        This module's own note about `querySelectorAll('.dash-card')` was the
        first thing the check reported, which is funny once and useless twice.
        """
        js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
        return re.sub(r"(?m)^\s*//.*$", "", js)

    def test_no_dead_class_is_selected_on(self):
        """Every class the code looks for has to be one that exists.

        Deliberately not an allowlist of "classes we render" - that rots, and a
        rotted allowlist is how `.dash-card` survived. A class exists if the
        page carries it or if this file writes it, and both halves are read
        from the source rather than maintained by hand.
        """
        code = self._code_only(self.JS)
        written = set(re.findall(r"class=\"([^\"$]*)", code))
        written |= set(re.findall(r"class=\"([^\"$]*)", self.HTML))
        exists = set()
        for chunk in written:
            exists.update(chunk.split())
        # `classList.add('x')` and friends put a class on an element too.
        exists.update(re.findall(r"classList\.(?:add|toggle)\(\s*'([\w-]+)'", code))

        selected = set()
        for m in re.finditer(r"querySelector(?:All)?\(\s*'([^']+)'", code):
            selected.update(re.findall(r"\.([a-zA-Z][\w-]*)", m.group(1)))

        dead = sorted(selected - exists)
        self.assertEqual(
            [], dead,
            "the code selects on classes nothing ever has, so these match "
            "nothing and fail silently: " + ", ".join(dead))

    def test_dash_card_in_particular_is_gone(self):
        """The one that cost him the counters, the filter highlight, the
        keyboard route and the Duplicates tab's filter list."""
        live = [ln.strip() for ln in self._code_only(self.JS).splitlines()
                if "dash-card" in ln and "querySelector" in ln]
        self.assertEqual([], live, "; ".join(live))


class NoCountGoesThroughAnUncheckedElement(unittest.TestCase):
    """The shape of the bug, banned rather than fixed once.

    Every write went `document.getElementById(x).textContent = y`, so any one
    of twenty-one ids going stale took the whole function down with it. They go
    through `_setCount`, which survives a missing element - one stale id then
    costs that one number instead of all of them.
    """

    def test_the_counters_are_written_through_one_helper(self):
        src = CLOUD_JS.read_text(encoding="utf-8")
        body = src[src.index("function updateDashboard() {"):]
        body = body[:body.index("\nfunction setFilter(")]
        bare = [ln.strip() for ln in body.split("\n")
                if "getElementById(" in ln and "textContent" in ln]
        self.assertEqual([], bare,
                         "a count still writes straight into getElementById(): "
                         + "; ".join(bare))

    def test_no_filter_is_hidden_through_a_wrapper_id(self):
        """`dDupAllCard` was the id of the *box round* a filter. Boxes change;
        what a filter filters does not, so that is what it is found by."""
        src = CLOUD_JS.read_text(encoding="utf-8")
        body = src[src.index("function updateDashboard() {"):]
        body = body[:body.index("\nfunction setFilter(")]
        self.assertNotIn("Card')", body)
        self.assertIn("_showFilter(", body)


if __name__ == "__main__":
    unittest.main()
