"""Click the control and watch the operation happen.

He asked for local -> cloud roughly half a dozen times. The backend shipped in
v2.104.6, the row control in v2.108.0, and he still could not use it: a gate
added the same morning allowed the push only on a pair sharing Ekahau's id or
one he had linked by hand, and refused a pair matched on its name.

That refused exactly his case. A project built locally and uploaded gets the id
stamped into the *cloud* copy - the local file does not carry it until the
project is downloaded back. "Local is newer and there is no shared id" is
therefore the normal state of a project he has worked on since the last
download, and it was the one thing the gate would not allow.

Every earlier test here asserted that the markup contained
`pushLocalOverCloud(`. It did. The control was on screen and did nothing for
him, and the tests were green throughout - the same shape as the three defects
that shipped green yesterday.

**So this drives it.** The row is rendered by the real function, the `onclick`
is pulled back out of that HTML, and *that string is executed*. If the handler
is missing, misspelled, takes different arguments, or bails before reaching the
server, this fails. Nothing here asserts that a substring exists.

The one thing it cannot do is talk to Ekahau: `pyApi` is a recorder. So this
proves the control reaches the server call with the right arguments, not that
the live account behaves - that run is his.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120

NODE_SCRIPT = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
const block = slice('const MATCH_BADGE_SPEC = {', '\nfunction gutCell(r)');

const WD = { esc: s => String(s == null ? '' : s),
             escAttr: s => String(s == null ? '' : s),
             escJsStr: s => String(s == null ? '' : s) };
function e(s) { return WD.esc(s); }
function a(s) { return WD.escAttr(s); }
function j(s) { return WD.escJsStr(s); }
function pj(s) { return j(String(s == null ? '' : s).replace(/\\/g, '/')); }
let currentTab = 'projects';

const calls = [];
const toasts = [];
const confirms = [];
let confirmAnswer = true;
let apiResult = { ok: true, newId: 'n1', oldId: 'c1', name: 'Project', deletedOld: true };

const queued = [];
function opEnqueue(spec) { queued.push(spec); return { id: 'op1', promise: Promise.resolve() }; }
function toast(msg, kind) { toasts.push(String(msg)); }
async function pyApi(...args) { calls.push(args); return apiResult; }
async function showConfirmModal(title, body, label) {
  confirms.push({ title: String(title), body: String(body), label: String(label) });
  return confirmAnswer;
}
function _clearStaleness() {}
function _scheduleOpRefresh() {}
// `_compareResults` and `_compareKey` are declared inside the slice itself
// since v2.110.0, so passing them in again is a redeclaration.
const fn = new Function('WD','e','a','j','pj','currentTab','opEnqueue','toast','pyApi','showConfirmModal','_clearStaleness','_scheduleOpRefresh',
  block + '\nreturn { stalenessBadgeHtml, pushLocalOverCloud, canPushToCloud };');
const api = fn(WD,e,a,j,pj,currentTab,opEnqueue,toast,pyApi,showConfirmModal,_clearStaleness,_scheduleOpRefresh);

const row = (matchType) => ({
  kind: 'projects', matchType,
  staleness: 'local_newer', differenceKind: 'content',
  cloud: { id: 'c1', name: 'SITE1 Survey', mtime: 100 },
  local: { path: 'C:/projects/SITE1/SITE1 Survey.esx', name: 'SITE1 Survey', mtime: 200 },
});

/* Pull the handler back out of the rendered row and run it. This is the step
   that would have caught a control that renders and does nothing. */
function clickTheControl(html) {
  const m = /onclick="event\.stopPropagation\(\);(pushLocalOverCloud\([^"]*\))"/.exec(html);
  if (!m) throw new Error('no push handler in the rendered row: ' + html.slice(0, 200));
  const invoke = new Function('pushLocalOverCloud', 'return ' + m[1] + ';');
  return invoke(api.pushLocalOverCloud);
}

(async () => {
  const out = {};

  // --- a name-only pair: the case he actually has --------------------------
  const exactHtml = api.stalenessBadgeHtml(row('exact'));
  out.exactOffersTheControl = /pushLocalOverCloud\(/.test(exactHtml);
  out.exactIsNotDisabled = !/aria-disabled="true"/.test(exactHtml);

  calls.length = 0; confirms.length = 0; toasts.length = 0; queued.length = 0;
  await clickTheControl(exactHtml);
  out.exactAsked = confirms.length;
  out.exactConfirmBody = confirms.length ? confirms[0].body : '';
  out.exactQueued = queued.length;
  if (queued.length) out.exactRunResult = await queued[0].run('op1');
  out.exactCalls = calls.slice();
  out.exactToasts = toasts.slice();

  // --- and if he says no, nothing happens ---------------------------------
  confirmAnswer = false;
  calls.length = 0; queued.length = 0;
  await clickTheControl(api.stalenessBadgeHtml(row('exact')));
  out.declinedQueued = queued.length;
  out.declinedCalls = calls.length;
  confirmAnswer = true;

  // --- a proven pair runs straight away -----------------------------------
  const idHtml = api.stalenessBadgeHtml(row('id'));
  calls.length = 0; confirms.length = 0; queued.length = 0;
  await clickTheControl(idHtml);
  out.idAsked = confirms.length;
  out.idQueued = queued.length;
  if (queued.length) await queued[0].run('op1');
  out.idCalls = calls.slice();

  // --- a guessed pair is still refused ------------------------------------
  const fuzzyHtml = api.stalenessBadgeHtml(row('fuzzy'));
  out.fuzzyOffersTheControl = /pushLocalOverCloud\(/.test(fuzzyHtml);
  out.fuzzyIsDisabled = /aria-disabled="true"/.test(fuzzyHtml);

  process.stdout.write(JSON.stringify(out));
  process.exit(0);
})().catch(err => { process.stderr.write(String(err && err.stack || err)); process.exit(1); });
"""


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheControlIsReachableAndRunsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "probe.js"
            script.write_text(NODE_SCRIPT, encoding="utf-8")
            proc = subprocess.run(["node", str(script), str(CLOUD_JS)],
                                  capture_output=True, timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError(
                "node failed: " + proc.stderr.decode("utf-8", "replace"))
        cls.out = json.loads(proc.stdout.decode("utf-8", "replace"))

    def test_a_name_matched_pair_gets_a_live_control(self):
        """The regression that made this unusable. His local-newer files have
        no shared id, because the id lives in the cloud copy until he downloads
        the project back."""
        self.assertTrue(self.out["exactOffersTheControl"])
        self.assertTrue(self.out["exactIsNotDisabled"])

    def test_clicking_it_reaches_the_server_with_the_right_arguments(self):
        """Executed out of the rendered HTML, not asserted as a substring.

        `replace_cloud_project` takes the local path and the cloud id in that
        order; getting them the wrong way round would look identical in the
        markup and destroy the wrong thing."""
        calls = self.out["exactCalls"]
        self.assertEqual(1, len(calls), "the server was not called once")
        self.assertEqual("replace_cloud_project", calls[0][0])
        self.assertEqual("C:/projects/SITE1/SITE1 Survey.esx", calls[0][1])
        self.assertEqual("c1", calls[0][2])

    def test_it_asks_once_before_replacing_on_a_name_only_pair(self):
        """Unrecoverable earns friction. The question is which project gets
        deleted, so the dialog names it."""
        self.assertEqual(1, self.out["exactAsked"])
        body = self.out["exactConfirmBody"]
        self.assertIn("SITE1 Survey", body)
        self.assertIn("cannot be undone", body)

    def test_saying_no_does_nothing_at_all(self):
        self.assertEqual(0, self.out["declinedQueued"])
        self.assertEqual(0, self.out["declinedCalls"])

    def test_a_proven_pair_runs_without_a_dialog(self):
        """He does this constantly; a prompt in front of the normal case is the
        kind of guard he has said is worse than useless."""
        self.assertEqual(0, self.out["idAsked"])
        self.assertEqual(1, self.out["idQueued"])
        self.assertEqual("replace_cloud_project", self.out["idCalls"][0][0])

    def test_the_run_reports_success_to_him(self):
        joined = " ".join(self.out["exactToasts"])
        self.assertIn("replaced", joined)

    def test_a_guessed_pair_is_still_refused(self):
        """Same site code or similar wording is not the same name. There is
        nothing for him to confirm against, so Link stays the route."""
        self.assertFalse(self.out["fuzzyOffersTheControl"])
        self.assertTrue(self.out["fuzzyIsDisabled"])


class TheAppOnlyPointsAtControlsThatExistTests(unittest.TestCase):
    """Telling him to use a control that is not there is worse than omitting it.

    The Sync dialog said "use **Local newer - replace cloud** on each" while
    that button was greyed out for every pair he had. He went looking, could
    not make it work, and reasonably concluded the tool was lying to him:
    "It also says we can go from local to cloud and yet I don't seem to be able
    to get that to work."

    So every control named in bold inside instructional prose has to exist as a
    label on something that renders. This is a wording check against the source
    because that is what the text is - there is no behaviour to drive - and it
    fails loudly if an instruction outlives its button or gets renamed away
    from it.
    """

    #: A control named in prose is bolded and carries its arrow glyph. Keying
    #: off "use <b>" does not work: the sentence is assembled from several
    #: string literals, so "use " and the tag land in different ones.
    NAMED = re.compile(r"<b>((?:&#\d+;|[^<])*?)</b>")
    ARROWS = ("&#11014;", "&#11015;")

    def test_every_control_the_text_names_is_a_real_label(self):
        js = CLOUD_JS.read_text(encoding="utf-8")
        named = {m.strip() for m in self.NAMED.findall(js)
                 if any(arrow in m for arrow in self.ARROWS)}
        self.assertTrue(named, "no instructional references found at all - "
                               "has the phrasing changed?")
        missing = [n for n in named if (">" + n + "<") not in js]
        self.assertEqual(
            [], missing,
            "the app tells him to use a control that nothing renders: "
            + ", ".join(missing)
            + ". Either wire it or stop naming it.")


if __name__ == "__main__":
    unittest.main()
