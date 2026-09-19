"""Which way the data moves - measured by running the control, not by reading it.

Two reports, one root cause: the page knew things it was not saying on screen.

**The arrows.** "I just realized the sync buttons are arrows pointing
backwards... when I hover over it it says 'pull cloud to local'." The arrows
were in fact consistent with the layout - the ledger puts **Cloud on the left
and Local on the right** - but the buttons said only `Sync →`, so the only way
to learn the direction was to hover, immediately before an operation that
overwrites a file.

**The dead label.** "it says local newer but I can't click it to do anything,
and then I hit the checkbox and I can't sync it either. I thought we fixed
that." `replace_cloud_project` had shipped in v2.104.6 with its server route
and nothing calling it.

**Why this file was rewritten.** Its assertions were of the form
`assertIn("pushLocalOverCloud(", block)` - the markup contains the name of a
handler. That is true whether or not the handler is reachable, whether or not
the arguments are right, and whether or not clicking it does anything, and it
was green for the whole period he could not use the control. A test that would
pass with the feature deleted is not a test.

So these render the real row, pull the `onclick` back out of the rendered
markup, run it with the handlers stubbed, and assert **the call that arrives**:
its name, its arguments, their order, and what happens on the pairing that is
supposed to refuse. The escaping is the real `WD.escJsStr`, because a project
named with an apostrophe or a path with a backslash is the case that turns a
present button into a dead one.

Every project, site and path here is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
SHARED_JS = ROOT / "web" / "assets" / "js" / "wd-shared.js"
CLOUD_HTML = ROOT / "web" / "cloud.html"
CSS = ROOT / "web" / "assets" / "wd-tools.css"
NODE_TIMEOUT_S = 120

#: The real escapers, the real pairing rules, and the real renderer. Nothing
#: here is a paraphrase of the code under test - it is the code under test.
PRELUDE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const shared = fs.readFileSync(process.argv[2], 'utf8');

function slice(text, from, to) {
  const a = text.indexOf(from);
  if (a < 0) throw new Error('not found: ' + from);
  const b = to ? text.indexOf(to, a) : text.length;
  if (b < 0) throw new Error('no end for: ' + from);
  return text.slice(a, b);
}

// the genuine escapers - argument escaping is half of what can break here
const WD = {};
eval(slice(shared, '  WD.esc = function', '  WD.applyVersions'));
globalThis.WD = WD;
function e(s) { return WD.esc(s); }
function a(s) { return WD.escAttr(s); }
function j(s) { return WD.escJsStr(s); }
function pj(s) { return j(String(s == null ? '' : s).replace(/\\/g, '/')); }

// stand-ins for presentation only, so a glyph set cannot fail a wiring test
function ic(name) { return '<i data-ic="' + name + '"></i>'; }
let currentTab = 'projects';
function compareResultFor() { return null; }
function rdAction(icon, label, call, opts) {
  opts = opts || {};
  return '<button class="rd-btn' + (opts.primary ? ' primary' : '')
       + '" title="' + a(opts.title || '') + '" onclick="event.stopPropagation();'
       + call + '">' + ic(icon) + '<span>' + label + '</span></button>';
}

// `stalenessBadgeHtml` asks this whether the row has anything left to do.
eval(slice(src, 'function comparisonIsSettled(', 'function isOutOfSync('));
eval(slice(src, 'const PULLABLE_MATCH_TYPES', 'function compareResultFor('));
eval(slice(src, 'function rdUnavailable(', 'function stalenessBadgeHtml('));
eval(slice(src, 'function stalenessBadgeHtml(', '\nfunction gutCell'));

/* Pull every handler back out of rendered markup and run it. This is the
   whole point: an onclick is a string until something evaluates it. */
const calls = [];
function record(name) {
  globalThis[name] = function () {
    calls.push({ name: name, args: Array.prototype.slice.call(arguments) });
  };
}
['pushLocalOverCloud', 'markManualMatch', 'verifyReplaceLocal', 'syncRow',
 'checkRealDifference', 'fixInternalName'].forEach(record);
globalThis.event = { stopPropagation() {} };

function buttons(html) {
  const out = [];
  const re = /<button\b([^>]*)>([\s\S]*?)<\/button>/g;
  let m;
  while ((m = re.exec(html))) {
    const attrs = m[1];
    const onclick = (attrs.match(/onclick="([\s\S]*?)"/) || [])[1] || '';
    out.push({
      label: m[2].replace(/<[^>]*>/g, '').trim(),
      onclick: onclick.replace(/&#39;/g, "'").replace(/&quot;/g, '"')
                      .replace(/&amp;/g, '&').replace(/&lt;/g, '<'),
      disabled: /aria-disabled="true"/.test(attrs),
      title: (attrs.match(/title="([\s\S]*?)"/) || [])[1] || '',
    });
  }
  return out;
}

function click(button) {
  calls.length = 0;
  eval(button.onclick);
  return calls.slice();
}
"""

PAIR = r"""
function pair(matchType, staleness, extra) {
  return Object.assign({
    kind: 'projects',
    status: 'synced',
    matchType: matchType,
    staleness: staleness,
    cloud: { id: 'cloud-77', name: "Ridge O'Neill Survey", mtime: 1000 },
    local: { path: 'C:\\Projects\\Ridge\\Ridge O\'Neill Survey.esx',
             name: "Ridge O'Neill Survey", mtime: 2000 },
  }, extra || {});
}
"""


def node(body: str) -> dict:
    program = PRELUDE + PAIR + body
    r = subprocess.run(["node", "-e", program, str(CLOUD_JS), str(SHARED_JS)],
                       capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout.strip().splitlines()[-1])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ClickingTheControlCallsTheRightThing(unittest.TestCase):
    """The assertion this file used to make was that the markup contained
    `pushLocalOverCloud(`. These run it."""

    def test_a_proven_pair_reaches_the_push_handler_with_the_right_arguments(self):
        got = node(r"""
          const html = stalenessBadgeHtml(pair('id', 'local_newer'));
          const bs = buttons(html);
          const live = bs.filter(b => !b.disabled);
          console.log(JSON.stringify({
            labels: bs.map(b => b.label),
            calls: live.map(b => ({ label: b.label, got: click(b) })),
          }));
        """)
        pushes = [c for c in got["calls"]
                  if any(x["name"] == "pushLocalOverCloud" for x in c["got"])]
        self.assertEqual(len(pushes), 1,
                         "exactly one control should push local over cloud; "
                         "rendered labels were %s" % (got["labels"],))
        call = [x for x in pushes[0]["got"] if x["name"] == "pushLocalOverCloud"][0]

        # argument order is the contract with the server route, and an
        # apostrophe or a backslash in either is what breaks it
        self.assertEqual(
            call["args"],
            ["cloud-77",
             "C:/Projects/Ridge/Ridge O'Neill Survey.esx",
             "Ridge O'Neill Survey",
             "Ridge O'Neill Survey",
             "id"],
            "the handler was reached but with the wrong arguments - "
            "cloud id, local path, local name, cloud name, match type")

    def test_the_label_and_the_handler_agree_about_the_direction(self):
        """A label reading one direction over a handler doing the other is the
        defect worth catching, and only running it can catch it."""
        got = node(r"""
          const out = {};
          ['local_newer', 'cloud_newer'].forEach(function (s) {
            const bs = buttons(stalenessBadgeHtml(pair('id', s)));
            out[s] = bs.filter(b => !b.disabled)
                       .map(b => ({ label: b.label, calls: click(b).map(c => c.name) }));
          });
          console.log(JSON.stringify(out));
        """)
        up = [b for b in got["local_newer"] if "pushLocalOverCloud" in b["calls"]]
        self.assertTrue(up, "local_newer offered nothing that pushes up")
        self.assertIn("replace cloud", up[0]["label"].lower(),
                      "the control that replaces the cloud copy does not say so")

        down = [b for b in got["cloud_newer"]
                if "verifyReplaceLocal" in b["calls"] or "syncRow" in b["calls"]]
        for b in down:
            self.assertNotIn("pushLocalOverCloud", b["calls"],
                             "a cloud-newer control pushed local up")

    def test_an_exact_pair_is_offered_because_it_is_the_normal_case(self):
        """A project built locally and uploaded carries Ekahau's id only in the
        cloud copy, so "local newer with no shared id" is the ordinary state of
        a project he has worked on. Excluding `exact` made the control unusable
        for the case he actually has."""
        got = node(r"""
          const bs = buttons(stalenessBadgeHtml(pair('exact', 'local_newer')));
          console.log(JSON.stringify(bs.filter(b => !b.disabled)
            .map(b => ({ label: b.label, calls: click(b).map(c => c.name) }))));
        """)
        self.assertTrue(
            any("pushLocalOverCloud" in b["calls"] for b in got),
            "an exact-name pair got no working push control: %s" % (got,))


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class AGuessedPairRefusesAndSaysHow(unittest.TestCase):
    """Refused, not absent - and the control that lifts the refusal has to be
    the one on screen. The old wording named the Link button, which is only
    ever drawn on an *unpaired* row."""

    def test_a_guessed_pair_cannot_reach_the_push_handler(self):
        got = node(r"""
          const bs = buttons(stalenessBadgeHtml(pair('code', 'local_newer')));
          console.log(JSON.stringify(bs.map(b => ({
            label: b.label, disabled: b.disabled,
            calls: b.onclick ? click(b).map(c => c.name) : [],
          }))));
        """)
        for b in got:
            self.assertNotIn("pushLocalOverCloud", b["calls"],
                             "a guessed pair reached the push handler, and a "
                             "cloud delete does not come back")
        named = [b for b in got if "local" in b["label"].lower()
                 and "cloud" in b["label"].lower()]
        self.assertTrue(named, "the refused action is not shown at all: %s" % (got,))
        self.assertTrue(named[0]["disabled"],
                        "the refused action is not marked unavailable")

    def test_the_control_that_lifts_the_refusal_runs_and_promotes_this_pair(self):
        got = node(r"""
          const bs = buttons(stalenessBadgeHtml(pair('code', 'local_newer')));
          const confirm = bs.filter(b => !b.disabled && b.onclick);
          console.log(JSON.stringify(confirm.map(b => ({
            label: b.label, got: click(b),
          }))));
        """)
        marks = [c for c in got
                 if any(x["name"] == "markManualMatch" for x in c["got"])]
        self.assertEqual(len(marks), 1,
                         "no runnable control promotes the pair: %s" % (got,))
        call = [x for x in marks[0]["got"] if x["name"] == "markManualMatch"][0]
        self.assertEqual(call["args"][0], "cloud-77")
        self.assertEqual(call["args"][1], "C:/Projects/Ridge/Ridge O'Neill Survey.esx")

    def test_promoting_the_pair_actually_unlocks_the_push(self):
        """The promise the refusal makes, kept end to end: confirm the pair and
        the control becomes usable. Asserted by re-rendering as a manual match
        and running what comes back."""
        got = node(r"""
          const before = buttons(stalenessBadgeHtml(pair('code', 'local_newer')))
            .filter(b => b.onclick).map(b => click(b).map(c => c.name));
          const after = buttons(stalenessBadgeHtml(pair('manual', 'local_newer')))
            .filter(b => !b.disabled && b.onclick).map(b => click(b).map(c => c.name));
          console.log(JSON.stringify({ before: before, after: after }));
        """)
        flat = lambda rows: [n for row in rows for n in row]
        self.assertNotIn("pushLocalOverCloud", flat(got["before"]))
        self.assertIn("pushLocalOverCloud", flat(got["after"]),
                      "confirming the pair did not unlock the push it promised")


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheRefusalExplainsRatherThanDoingNothing(unittest.TestCase):

    def test_the_disabled_control_carries_its_reason(self):
        """Not the wording - the property. It has to say it cannot be undone
        and it has to name a control that is on this row."""
        got = node(r"""
          const bs = buttons(stalenessBadgeHtml(pair('code', 'local_newer')));
          console.log(JSON.stringify({
            disabled: bs.filter(b => b.disabled).map(b => b.title),
            labels: bs.map(b => b.label),
          }));
        """)
        self.assertTrue(got["disabled"], "nothing is marked unavailable")
        why = " ".join(got["disabled"]).lower()
        self.assertIn("cannot be undone", why)
        named = [w for w in ("confirm this pair", "link") if w in why]
        self.assertTrue(named, "the reason names no way forward")
        if "confirm this pair" in why:
            self.assertIn("Confirm this pair", got["labels"],
                          "the reason names a control that is not on this row")


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheBulkPathAgreesWithTheRow(unittest.TestCase):
    """The other half of his report, and it is still broken.

    Verbatim: "it says local newer but I can't click it to do anything, **and
    then I hit the checkbox and I can't sync it either.**" The row was wired to
    `replace_cloud_project` in v2.104.6 and the bulk planner was not, so the
    two now disagree: the row draws a working control for a proven pair while
    `syncPlan` counts the same row as a blocked push and plans nothing.

    Measured, not inferred - `syncPlan([{matchType:'id', staleness:
    'local_newer', ...}], 'to-cloud')` returns `total: 0`, `pairs: 0`,
    `blockedPushes: 1`.

    No source-string test could see this. They asserted that the row block
    contains `canPushToCloud(r)` and `pushLocalOverCloud(`, both of which are
    true; nothing ever asked the planner what it does with the same row.

    Fixed in v2.117.0: both planners take the same two predicates the row
    takes, so there is one answer to "may this pair move in this direction"
    rather than two. The expected-failure marker is off; if the planner ever
    stops asking, this goes red where it used to go quietly green.

    Checking the rest of the agreement, as the report asked, found the mirror
    image and it was the more dangerous one: the bulk *pull* had no match-type
    test at all, so ticking a guessed pair and pressing Sync pulled the cloud
    copy down over a local file the row would have refused to touch.
    """

    def _plan(self, match_type: str) -> dict:
        program = r"""
          const fs = require('fs');
          const src = fs.readFileSync(process.argv[1], 'utf8');
          const a = src.indexOf('function syncPlan(items, dir) {');
          const b = src.indexOf('function selectedSyncItems(');
          // The planner consults the same sets the row does, and they sit
          // above it - see the note in test_cloud_sync_plan.py.
          const ca = src.indexOf('const PULLABLE_MATCH_TYPES');
          const cb = src.indexOf('function canPushToCloud(');
          function isProjectSyncItem(d) { return d && !d.isDir; }
          // One evaluation: `const` is block-scoped to its own eval.
          eval(src.slice(ca, cb) + src.slice(a, b));
          const row = { kind: 'pair', matchType: process.argv[2],
                        staleness: 'local_newer',
                        localPath: 'C:/Projects/Ridge/Ridge.esx', name: 'Ridge' };
          const plan = syncPlan([row], 'to-cloud');
          console.log(JSON.stringify({ total: plan.total,
                                       pairs: plan.pairs.length,
                                       blocked: plan.blockedPushes.length }));
        """
        r = subprocess.run(["node", "-e", program, str(CLOUD_JS), match_type],
                           capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_pair_the_row_can_push_is_not_blocked_in_bulk(self):
        plan = self._plan("id")
        self.assertEqual(
            plan["blocked"], 0,
            "the row offers a working push for this pair and the bulk plan "
            "calls it blocked, which is the checkbox half of his report")
        self.assertGreater(plan["total"], 0, plan)

    def test_a_guessed_pair_is_still_blocked_in_bulk(self):
        """The half that is right, and must stay right: a name-only guess is
        not pushed in bulk either."""
        plan = self._plan("code")
        self.assertEqual(plan["blocked"], 1)
        self.assertEqual(plan["total"], 0)

    def test_a_name_matched_pair_moves_in_bulk_exactly_as_it_does_on_the_row(self):
        """`exact` is the case the row was originally refused for, and the one
        that made the feature unreachable: a project built locally and uploaded
        carries Ekahau's id in the *cloud* copy only, so "newer locally, no
        shared id" is the ordinary state of work in progress.

        The row allows it and asks once. The plan allows it and asks once, in
        the dialog, where every project it will delete is named.
        """
        plan = self._plan("exact")
        self.assertEqual(plan["blocked"], 0)
        self.assertGreater(plan["total"], 0, plan)


class TheDirectionIsReadableWithoutHovering(unittest.TestCase):
    """The two things that are genuinely properties of the page rather than of
    a behaviour: the column order the arrows have to agree with, and that a
    bare glyph is never the whole label."""

    def setUp(self):
        self.html = CLOUD_HTML.read_text(encoding="utf-8")

    def _button(self, element_id: str) -> str:
        import re
        m = re.search(r'<button[^>]*id="%s".*?</button>' % element_id,
                      self.html, re.S)
        self.assertIsNotNone(m, element_id + " is missing")
        return m.group(0)

    def test_the_columns_are_cloud_left_and_local_right(self):
        legend = self.html[self.html.index('class="col-legend"'):]
        legend = legend[:legend.index("</div>")]
        self.assertLess(legend.index("legCloud"), legend.index("legLocal"))

    def test_each_bulk_button_names_its_direction_in_words(self):
        import re
        for element_id, first, second in (("bulkSyncTo", "Cloud", "Local"),
                                          ("bulkSyncFrom", "Local", "Cloud")):
            with self.subTest(button=element_id):
                markup = self._button(element_id)
                label = re.sub(r"<[^>]+>", "", markup)
                label = label.replace("&#8594;", "").replace("&#8592;", "").strip()
                self.assertTrue(label, "nothing but an arrow")
                self.assertNotEqual("Sync", label)
                self.assertLess(markup.index(first), markup.index(second),
                                "the label reads the opposite direction")

    def test_the_greyed_control_is_styled_as_unavailable(self):
        self.assertIn(".gut-arrow.is-disabled", CSS.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
