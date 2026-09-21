"""The bulk share dialog can be made to share something.

"I select the filter, I show the files, then I hit select cloud side, then I
hit the move / share / mark / override button and put it on Share. The dialog
box appears but there is no Apply. I add both the recent names and the only
option is Add or Close."

**The handler was wired.** `_shareAdd()` called `bulk_share` and the bulk path
worked. What was missing was a control named after the operation: the dialog's
whole interaction is putting recipients on a list, clicking a remembered name
already does that without sharing, so a button called "Add" reads as the step
he had just done twice. Every sibling dialog in the same menu - Move, Merge,
Create, Sync selected - names its own action. This one did not.

So the two jobs are two controls now: **Add to list** stages a recipient, and
a primary states what it will do with the real counts - "Share 12 projects
with 2 people" - and is disabled until there is somebody to share with.

Two further faults were found in the same path and are covered here.

**The selection was narrowed silently.** Projects he does not own are dropped
before the dialog opens, because Ekahau only lets an owner add shares. Fifteen
selected became "Sharing 12 projects" with nothing to account for the other
three - which is the auto-assign lesson pointing the other way: excluding what
cannot work is right, doing it without saying so is not.

**The result was invented.** `bulk_share` set `emailsAdded` to the addresses
he *typed* and discarded Ekahau's `responsePerEmailAddress`, so one refusal in
five was invisible and the refused address was written into Recent Recipients
- the one thing that store exists to avoid. The single-project path has parsed
that answer since the sharing audit; the bulk path never did.

Nothing here touches a real account: the API is stubbed and every address,
project and person is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from tools import cloud_manager as cm

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120

ME = "me@example.invalid"
MATE = "colleague@example.invalid"
GOOD = "newstarter@example.invalid"
BAD = "typo@example.invalid"


class _Resp:
    def __init__(self, code=200, payload=None, text="{}"):
        self.status_code = code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class _StubApi:
    """Answers the two calls `bulk_share` makes. Records what it was asked."""

    def __init__(self, owners, per_email=None, raise_on_share=None):
        self.user_email = ME
        self._owners = owners
        self._per_email = per_email or {}
        self._raise = raise_on_share
        self.shared = []

    def list_project_shares(self, pid):
        return {pid: [{"username": self._owners.get(pid, ME), "role": "OWNER"}]}

    def bulk_add_shares(self, project_ids, emails, role):
        if self._raise:
            raise RuntimeError(self._raise)
        self.shared.append((list(project_ids), list(emails), role))
        return [{"responsePerEmailAddress":
                 {e: self._per_email.get(e, "") for e in emails}}]


class TheResultIsEkahausAnswerTests(unittest.TestCase):

    def setUp(self):
        self.remembered = []
        self._real = cm.share_recipients.remember
        cm.share_recipients.remember = lambda e: self.remembered.extend(e)
        self.addCleanup(lambda: setattr(cm.share_recipients, "remember",
                                        self._real))

    def _mgr(self, api):
        mgr = cm.CloudManager.__new__(cm.CloudManager)
        mgr._ensure = lambda: True
        mgr.api = api
        return mgr

    def test_a_recipient_ekahau_accepted_is_reported_as_added(self):
        api = _StubApi({"p1": ME})
        out = self._mgr(api).bulk_share(["p1"], [GOOD])
        self.assertEqual([GOOD], out["emailsAdded"])
        self.assertTrue(out["ok"])

    def test_a_recipient_ekahau_refused_is_not_reported_as_added(self):
        """The defect. `emailsAdded` was the list he typed, so this said
        both had access when one had not."""
        api = _StubApi({"p1": ME}, per_email={BAD: "No such user"})
        out = self._mgr(api).bulk_share(["p1"], [GOOD, BAD])
        self.assertEqual([GOOD], out["emailsAdded"])
        self.assertIn(BAD, out["emailsRefused"])

    def test_the_refusal_is_reported_per_recipient_with_ekahaus_words(self):
        api = _StubApi({"p1": ME}, per_email={BAD: "No such user"})
        out = self._mgr(api).bulk_share(["p1"], [GOOD, BAD])
        by_email = {r["email"]: r for r in out["recipients"]}
        self.assertTrue(by_email[GOOD]["ok"])
        self.assertFalse(by_email[BAD]["ok"])
        self.assertEqual("No such user", by_email[BAD]["message"])

    def test_a_refused_address_is_not_remembered(self):
        """Recent Recipients exists so he stops retyping addresses. Putting
        a rejected one in offers it back as though it had worked."""
        api = _StubApi({"p1": ME}, per_email={BAD: "No such user"})
        self._mgr(api).bulk_share(["p1"], [GOOD, BAD])
        self.assertIn(GOOD, self.remembered)
        self.assertNotIn(BAD, self.remembered)

    def test_every_address_refused_is_a_failure_not_a_success(self):
        """Ekahau reports this per recipient rather than as a status, so
        nothing raised and the run came back `ok`."""
        api = _StubApi({"p1": ME},
                       per_email={GOOD: "No such user", BAD: "No such user"})
        out = self._mgr(api).bulk_share(["p1"], [GOOD, BAD])
        self.assertIn("error", out)
        self.assertNotEqual(True, out.get("ok"))

    def test_a_project_he_does_not_own_is_excluded_with_a_reason(self):
        api = _StubApi({"p1": ME, "p2": MATE})
        out = self._mgr(api).bulk_share(["p1", "p2"], [GOOD])
        self.assertEqual(1, out["ownedCount"])
        self.assertEqual(["p1"], out["ownedIds"])
        self.assertEqual(1, len(out["skipped"]))
        self.assertEqual("p2", out["skipped"][0]["projectId"])

    def test_only_the_projects_he_owns_are_sent(self):
        api = _StubApi({"p1": ME, "p2": MATE})
        self._mgr(api).bulk_share(["p1", "p2"], [GOOD])
        self.assertEqual([(["p1"], [GOOD], "READ_USER")], api.shared)

    def test_none_of_them_his_is_refused_before_anything_is_sent(self):
        api = _StubApi({"p1": MATE})
        out = self._mgr(api).bulk_share(["p1"], [GOOD])
        self.assertIn("error", out)
        self.assertEqual([], api.shared)


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheDialogCanBeAppliedTests(unittest.TestCase):
    """The real functions out of the shipped file, run."""

    PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
function fakeEl() {
  return { innerHTML: '', textContent: '', value: '', checked: false,
    hidden: false, disabled: false, dataset: {}, style: {}, children: [],
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){}, removeEventListener(){}, setAttribute(){},
    getAttribute(){ return null; }, removeAttribute(){}, closest(){ return null; },
    querySelector(){ return null; }, querySelectorAll(){ return []; },
    appendChild(){}, remove(){}, focus(){}, click(){} };
}
const els = {};
function el(id) { if (!els[id]) els[id] = fakeEl(); return els[id]; }
const sandbox = {
  console, JSON, Math, Date, Map, Set, Promise, RegExp, Intl,
  setTimeout, clearTimeout, setInterval, clearInterval,
  document: { getElementById: el, querySelector(){ return fakeEl(); },
    querySelectorAll(){ return []; }, createElement(){ return fakeEl(); },
    addEventListener(){}, body: fakeEl(), documentElement: fakeEl() },
  navigator: { platform: 'Win32', clipboard: { writeText: async () => {} } },
  location: { href: 'file:///cloud.html', search: '', hash: '' },
  localStorage: { getItem: () => null, setItem(){}, removeItem(){} },
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  alert(){}, confirm(){ return true; }, prompt(){ return null; },
  requestAnimationFrame: (f) => setTimeout(f, 0),
  WD: { esc: s => String(s == null ? '' : s).replace(/[&<>"]/g,
          c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
        applyVersions(){}, toast(){} },
};
sandbox.WD.escAttr = sandbox.WD.esc;
sandbox.WD.escJsStr = s => String(s == null ? '' : s).replace(/['\\]/g, '\\$&');
sandbox.window = sandbox;
vm.createContext(sandbox);
try { vm.runInContext(source, sandbox, { filename: 'cloud.js' }); }
catch (err) { if (!/addEventListener|null|undefined/.test(err.message)) throw err; }

const spec = JSON.parse(process.argv[2]);

// The dialog, in the state he had it in: a bulk selection and some chips.
vm.runInContext('_shareCtx = ' + JSON.stringify(spec.ctx) + ';', sandbox);
vm.runInContext('_shareChips = ' + JSON.stringify(
  (spec.chips || []).map(e => ({ email: e, valid: true }))) + ';', sandbox);
el('shareEmail').value = spec.typed || '';

/* Did staging start the share? It must not - that was the whole confusion.
   Watching `pyApi` is not enough and looked like it was: the bulk path goes
   through the ops queue, so the request is made a tick later and a probe
   that counts calls straight afterwards reads zero whatever happens. The
   queue is the thing `_shareAdd` reaches for first, so that is what is
   watched. */
const calls = [];
sandbox.pyApi = async (...a) => { calls.push(a); return {}; };
sandbox.opEnqueue = (spec) => {
  calls.push(['opEnqueue', spec && spec.title]);
  return { id: 'op-test', promise: Promise.resolve({}) };
};
if (spec.stage) vm.runInContext('_shareStage()', sandbox);

const label = vm.runInContext('_shareApplyLabel()', sandbox);
const out = {
  label: label,
  targets: vm.runInContext('_shareSelectionHtml()', sandbox),
  chips: vm.runInContext('_shareChips.map(c => c.email)', sandbox),
  calls: calls.length,
};
if (spec.result) {
  vm.runInContext('_shareCtx.lastResult = ' + JSON.stringify(spec.result) + ';',
                  sandbox);
  out.resultHtml = vm.runInContext('_shareSelectionHtml()', sandbox);
}
process.stdout.write(JSON.stringify(out));
"""

    @staticmethod
    def _ctx(nprojects=12, notmine=0):
        names = [f"SITE{i} Riverside Baseline" for i in range(1, nprojects + 1)]
        return {
            "projectId": None, "projectName": None,
            "bulkProjectIds": [f"p{i}" for i in range(1, nprojects + 1)],
            "bulkProjects": [{"id": f"p{i}", "name": n}
                             for i, n in enumerate(names, 1)],
            #: Named from the invented codes the rule-zero scanner already
            #: knows, rather than generated. Appending a loop index to one of
            #: them produced a token of the site-code shape that nobody had
            #: declared, and the scanner is right to stop that whether it was
            #: invented or not - the comment explaining it has to avoid
            #: writing the token down too, which is the same trap one step
            #: along.
            "notMine": [{"id": f"x{i}", "name": f"{code} Harbour Survey",
                         "owner": MATE}
                        for i, code in enumerate(
                            ["SITE4", "SITE5", "SITE7"][:notmine])],
            "users": [], "group": None, "groupPanelOpen": False,
        }

    def run_js(self, spec):
        r = subprocess.run(
            ["node", "-e", self.PROGRAM, str(CLOUD_JS), json.dumps(spec)],
            capture_output=True, text=True, encoding="utf-8",
            timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError("probe failed:\n" + (r.stderr or "")[-2500:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    # -- the control that was missing -----------------------------------

    def test_with_no_recipients_the_action_is_disabled_and_says_why(self):
        got = self.run_js({"ctx": self._ctx(), "chips": []})
        self.assertFalse(got["label"]["enabled"])
        self.assertIn("at least one person", got["label"]["why"])

    def test_with_recipients_the_action_names_what_it_will_do(self):
        """He has said repeatedly that a control should state its effect,
        and this one writes to live cloud projects."""
        got = self.run_js({"ctx": self._ctx(12), "chips": [GOOD, MATE]})
        self.assertTrue(got["label"]["enabled"])
        self.assertEqual("Share 12 projects with 2 people", got["label"]["text"])

    def test_one_of_each_reads_as_one_of_each(self):
        got = self.run_js({"ctx": self._ctx(1), "chips": [GOOD]})
        self.assertEqual("Share 1 project with 1 person", got["label"]["text"])

    def test_an_address_still_in_the_box_counts_towards_the_action(self):
        """Otherwise the button reads "add someone first" over a box with an
        address in it - and `_shareAdd` would have taken it anyway."""
        got = self.run_js({"ctx": self._ctx(3), "chips": [], "typed": GOOD})
        self.assertTrue(got["label"]["enabled"])
        self.assertIn("1 person", got["label"]["text"])

    def test_adding_to_the_list_does_not_share(self):
        """The old "Add" was the commit. The new one stages, and the
        difference has to be real rather than a relabelling."""
        got = self.run_js({"ctx": self._ctx(4), "chips": [],
                           "typed": GOOD, "stage": True})
        self.assertEqual([GOOD], got["chips"])
        self.assertEqual(0, got["calls"], "staging a recipient called the server")

    # -- what it is about to act on -------------------------------------

    def test_the_dialog_lists_the_projects_it_will_share(self):
        got = self.run_js({"ctx": self._ctx(12), "chips": [GOOD]})
        for i in (1, 7, 12):
            self.assertIn(f"SITE{i} Riverside Baseline", got["targets"])

    def test_no_project_name_is_abbreviated_away(self):
        """"and 9 more" is the thing he cannot check."""
        got = self.run_js({"ctx": self._ctx(12), "chips": [GOOD]})
        self.assertNotIn("more", got["targets"].lower())

    def test_projects_left_out_for_ownership_are_named(self):
        """Fifteen selected becoming "Sharing 12 projects" with no account
        of the other three is the silent half of a correct exclusion."""
        got = self.run_js({"ctx": self._ctx(12, notmine=3), "chips": [GOOD]})
        self.assertIn("3 other projects were left out", got["targets"])
        self.assertIn("SITE4 Harbour Survey", got["targets"])
        self.assertIn(MATE, got["targets"])

    def test_nothing_is_said_about_exclusions_when_there_are_none(self):
        got = self.run_js({"ctx": self._ctx(12, notmine=0), "chips": [GOOD]})
        self.assertNotIn("left out", got["targets"])

    # -- and what it did -------------------------------------------------

    def test_the_result_names_each_recipient_separately(self):
        got = self.run_js({"ctx": self._ctx(2), "chips": [GOOD], "result": {
            "recipients": [{"email": GOOD, "ok": True, "message": ""},
                           {"email": BAD, "ok": False,
                            "message": "No such user"}],
            "projects": ["SITE1 Riverside Baseline", "SITE2 Riverside Baseline"],
            "skipped": []}})
        self.assertIn(GOOD, got["resultHtml"])
        self.assertIn(BAD, got["resultHtml"])
        self.assertIn("not added", got["resultHtml"])
        self.assertIn("No such user", got["resultHtml"])

    def test_the_result_names_the_projects_they_reached(self):
        got = self.run_js({"ctx": self._ctx(2), "chips": [GOOD], "result": {
            "recipients": [{"email": GOOD, "ok": True, "message": ""}],
            "projects": ["SITE1 Riverside Baseline", "SITE2 Riverside Baseline"],
            "skipped": []}})
        self.assertIn("SITE2 Riverside Baseline", got["resultHtml"])


if __name__ == "__main__":
    unittest.main()
