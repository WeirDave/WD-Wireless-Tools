"""Fixing the difference, rather than remembering that it does not matter.

"Once a pair is checked and determined that there's not really a difference
between the two, why would it come up unless something is different? How come
we're not **fixing** the difference, if it's something we can identify - like
a date, or the internal project number or name?"

He is right, and the comparison memory shipped in v2.165.0 is the lesser fix:
it remembers the answer and goes on showing the question. When the only things
that differ are the project name written inside the .esx and the modified
date, those are ours to write, so the pair can be made to stop differing.

**This is not a second implementation.** `tools/cloud_realign.py` already does
exactly this work - it was written as a function taking a `CloudManager`
precisely so it could be reached from somewhere other than the dev toolbar.
What is added is a scope: `only`, a set of cloud ids, so the same operation
runs over the rows he picked instead of the whole account. There is one copy
of "write to his project files" and this is it.

**The direction is a decision.** It writes the local file and never the cloud.
Renaming the cloud project would stamp Ekahau's own `modifiedAt` on it, so the
pair would read "cloud newer" again the instant it was fixed - the discrepancy
moved rather than removed, which is the inversion to avoid. Taking the cloud's
name and date *into* the local file leaves both sides agreeing and neither of
them newer.

**What it must never do** is touch a pair whose design really differs, or one
where his local copy is the newer of the two - that second one is his own
edit, and overwriting its name and date with the cloud's would throw the edit
away without ever saying so.

Every project, site, address and date here is invented, and no test reaches a
real account or writes outside its own temporary directory.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from tools import cloud_manager, cloud_realign

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120

OLD_ISO = "2026-08-01T09:00:00.000Z"
NEW_ISO = "2026-09-01T09:00:00.000Z"


def write_esx(path: Path, *, name: str, modified_iso: str,
              project_id: str = "00000000-0000-4000-8000-0000000000aa",
              ap_count: int = 2, image: bytes = b"floor-plan-bytes") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    members = {
        "project.json": json.dumps({"project": {
            "id": project_id, "name": name, "title": name,
            "history": {"createdBy": "surveyor@example.invalid",
                        "modifiedAt": modified_iso},
        }}).encode("utf-8"),
        "accessPoints.json": json.dumps({"accessPoints": [
            {"id": "ap-%d" % i, "name": "AP %d" % (i + 1)}
            for i in range(ap_count)]}).encode("utf-8"),
        "floorPlans.json": json.dumps({"floorPlans": [
            {"id": "floor-1", "name": "Level 1"}]}).encode("utf-8"),
        "image-floor-1": image,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for member, raw in members.items():
            z.writestr(member, raw)
    return path


class RecordingAPI:
    """Reads are answered; every write raises. A reconcile that reached for
    `rename_project` would fail here rather than quietly succeed."""

    user_email = "surveyor@example.invalid"

    def __init__(self, projects, downloads):
        self.projects = projects
        self.downloads = downloads
        self.calls = []

    def get_projects(self):
        self.calls.append("get_projects")
        return list(self.projects)

    def get_dataset_listing(self):
        return []

    def download_project(self, project_id, progress_cb=None):
        self.calls.append("download_project")
        if project_id not in self.downloads:
            return {"error": "no such project"}
        return {"esx": self.downloads[project_id]}

    def __getattr__(self, name):
        if name in ("upload_project", "rename_project", "rename_site",
                    "delete_project", "delete_dataset", "replace_project"):
            def go(*a, **k):
                raise AssertionError("reconcile must never call %s" % name)
            return go
        raise AttributeError(name)


class TwoPairs(unittest.TestCase):
    """Two matched pairs, so "only the one he picked" is a real assertion."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.out = self.root / "Projects"
        self.site = self.out / "SITE1 Riverside"
        self.site.mkdir(parents=True)
        cloud_manager._ESX_META_CACHE.clear()
        cloud_manager._ESX_TYPE_CACHE.clear()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(cloud_manager._ESX_META_CACHE.clear)

    def build(self, pairs):
        """`pairs` is a list of dicts describing each side."""
        projects, downloads = [], []
        self.paths = {}
        listing = []
        for spec in pairs:
            cid = spec["cloudId"]
            local = self.site / ("%s.esx" % spec["localName"])
            write_esx(local, name=spec.get("localInternal",
                                           spec["localName"]),
                      modified_iso=spec["localIso"],
                      project_id=cid, ap_count=spec.get("localAps", 2))
            self.paths[cid] = local

            tmp = self.root / ("cloud-%s.esx" % cid)
            write_esx(tmp, name=spec["cloudName"],
                      modified_iso=spec["cloudIso"],
                      project_id=cid, ap_count=spec.get("cloudAps", 2))
            downloads.append((cid, tmp.read_bytes()))
            tmp.unlink()

            listing.append({"id": cid, "name": spec["cloudName"],
                            "statistics": {"size": 2048},
                            "history": {
                                "createdBy": "surveyor@example.invalid",
                                "modifiedAt": spec["cloudIso"]}})
        self.api = RecordingAPI(listing, dict(downloads))
        self.cm = cloud_manager.CloudManager()
        self.cm.api = self.api
        self.cm.config = {"output_dir": str(self.out)}

    def internal(self, cid):
        with zipfile.ZipFile(self.paths[cid]) as z:
            proj = json.loads(z.read("project.json"))["project"]
        return proj.get("name"), (proj.get("history") or {}).get("modifiedAt")

    def run_it(self, only, dry_run=False):
        return cloud_realign.realign(self.cm, dry_run=dry_run, only=only)

    #: One pair the cloud renamed (reconcilable), one untouched.
    TWO = [
        {"cloudId": "c-1", "localName": "SITE1 Riverside Baseline",
         "localInternal": "SITE1 Riverside Baseline",
         "cloudName": "SITE1 Riverside Final",
         "localIso": OLD_ISO, "cloudIso": NEW_ISO},
        {"cloudId": "c-2", "localName": "SITE2 Harbour Baseline",
         "cloudName": "SITE2 Harbour Final",
         "localIso": OLD_ISO, "cloudIso": NEW_ISO},
    ]

    # -- the scope ------------------------------------------------------

    def test_only_the_pair_he_picked_is_written(self):
        self.build(self.TWO)
        before = self.internal("c-2")
        out = self.run_it(["c-1"])
        self.assertEqual(1, len(out["aligned"]), out)
        self.assertEqual("c-1", out["aligned"][0]["cloudId"])
        self.assertEqual(before, self.internal("c-2"),
                         "it wrote to a pair he had not selected")

    def test_the_picked_pair_really_changes(self):
        self.build(self.TWO)
        self.run_it(["c-1"])
        name, iso = self.internal("c-1")
        self.assertEqual("SITE1 Riverside Final", name)
        self.assertEqual(NEW_ISO, iso)

    def test_the_date_the_list_compares_is_the_one_that_moves(self):
        """The trap the repair script already documents: setting only the
        file's date on disk changes nothing a row displays, because the list
        reads `history.modifiedAt` from inside the archive."""
        self.build(self.TWO)
        self.run_it(["c-1"])
        cloud_manager._ESX_META_CACHE.clear()
        files = {f["path"]: f for f in
                 cloud_manager.get_local_esx_files(str(self.out))}
        mine = files[str(self.paths["c-1"])]
        cloud_unix = int(cloud_manager._parse_cloud_mtime(
            {"history": {"modifiedAt": NEW_ISO}}) or 0)
        self.assertAlmostEqual(cloud_unix, int(mine["mtime"]), delta=2)

    def test_an_empty_selection_writes_nothing(self):
        """`only=[]` must mean "none", never "all" - the difference between
        a no-op and a sweep of his whole account."""
        self.build(self.TWO)
        before = [self.internal("c-1"), self.internal("c-2")]
        out = self.run_it([])
        self.assertEqual([], out["aligned"])
        self.assertEqual(before, [self.internal("c-1"), self.internal("c-2")])

    # -- what it refuses, and says --------------------------------------

    def test_a_pair_where_his_copy_is_newer_is_refused_by_name(self):
        """His own edit. Taking the cloud's name and date over it would
        discard the edit and report success."""
        self.build([{"cloudId": "c-1", "localName": "SITE1 Riverside Baseline",
                     "cloudName": "SITE1 Riverside Final",
                     "localIso": NEW_ISO, "cloudIso": OLD_ISO}])
        before = self.internal("c-1")
        out = self.run_it(["c-1"])
        self.assertEqual([], out["aligned"])
        self.assertEqual(1, len(out["skipped"]))
        self.assertIn("newer one", out["skipped"][0]["reason"])
        self.assertEqual(before, self.internal("c-1"))

    def test_a_pair_that_already_agrees_is_reported_as_needing_nothing(self):
        self.build([{"cloudId": "c-1", "localName": "SITE1 Riverside Final",
                     "cloudName": "SITE1 Riverside Final",
                     "localIso": NEW_ISO, "cloudIso": NEW_ISO}])
        out = self.run_it(["c-1"])
        self.assertEqual([], out["aligned"])
        self.assertIn("already agree", out["skipped"][0]["reason"])

    def test_an_id_that_is_not_a_matched_pair_is_named_rather_than_dropped(self):
        self.build(self.TWO)
        out = self.run_it(["c-1", "not-a-real-id"])
        reasons = {s["cloudId"]: s["reason"] for s in out["skipped"]}
        self.assertIn("not-a-real-id", reasons)
        self.assertIn("Not a matched pair", reasons["not-a-real-id"])

    def test_a_real_design_difference_is_never_written(self):
        """The one thing this must not touch."""
        self.build([{"cloudId": "c-1", "localName": "SITE1 Riverside Baseline",
                     "cloudName": "SITE1 Riverside Final",
                     "localIso": OLD_ISO, "cloudIso": NEW_ISO,
                     "localAps": 2, "cloudAps": 9}])
        before = self.internal("c-1")
        out = self.run_it(["c-1"])
        self.assertEqual([], out["aligned"])
        self.assertIn("genuinely differ", out["skipped"][0]["reason"])
        self.assertEqual(before, self.internal("c-1"))

    def test_the_preview_writes_nothing(self):
        self.build(self.TWO)
        before = self.internal("c-1")
        out = self.run_it(["c-1"], dry_run=True)
        self.assertEqual(1, len(out["aligned"]))
        self.assertTrue(out["dryRun"])
        self.assertEqual(before, self.internal("c-1"),
                         "the preview wrote to his file")

    def test_the_preview_says_what_it_would_change(self):
        self.build(self.TWO)
        out = self.run_it(["c-1"], dry_run=True)
        actions = " | ".join(out["aligned"][0]["actions"])
        self.assertIn("name", actions.lower())
        self.assertIn("date", actions.lower())

    def test_nothing_is_written_to_the_cloud(self):
        """`RecordingAPI` raises on every write, so this asserts the absence
        by construction rather than by reading the source."""
        self.build(self.TWO)
        self.run_it(["c-1"])
        self.assertNotIn("rename_project", self.api.calls)
        self.assertEqual({"get_projects", "download_project"},
                         set(self.api.calls) - {"get_dataset_listing"})

    def test_the_three_lists_still_add_up(self):
        """The invariant that makes "nothing went missing between the preview
        and the run" checkable. The selection filter sets rows aside before
        the loop, so they have to be counted as examined too."""
        self.build(self.TWO)
        out = self.run_it(["c-1", "c-2", "not-a-real-id"])
        self.assertEqual(
            out["examined"],
            len(out["aligned"]) + len(out["skipped"]) + len(out["failed"]))

    def test_running_it_twice_changes_nothing_the_second_time(self):
        self.build(self.TWO)
        self.run_it(["c-1"])
        after_first = self.internal("c-1")
        out = self.run_it(["c-1"])
        self.assertEqual([], out["aligned"])
        self.assertEqual(after_first, self.internal("c-1"))


class TheRouteHandsOverTheRightArgumentsTests(unittest.TestCase):
    """`CLOUD_ACTIONS` is a dictionary of lambdas nobody executes.

    A perfect function reached through a lambda that reads the wrong key is
    handed the wrong argument, and here one of those keys decides whether
    anything is written at all.
    """

    def setUp(self):
        import server
        self.server = server
        self.calls = []
        real = server.cloud_realign.realign
        def spy(cm, **kw):
            self.calls.append(kw)
            return {"ok": True, "aligned": [], "skipped": [], "failed": []}
        server.cloud_realign.realign = spy
        self.addCleanup(lambda: setattr(server.cloud_realign, "realign", real))

    def call(self, payload):
        self.server.CLOUD_ACTIONS["reconcile_pairs"](payload)
        return self.calls[-1]

    def test_the_route_exists(self):
        self.assertIn("reconcile_pairs", self.server.CLOUD_ACTIONS)

    def test_the_selected_ids_reach_the_scope(self):
        got = self.call({"cloudIds": ["c-1", "c-2"], "dryRun": True})
        self.assertEqual(["c-1", "c-2"], list(got["only"]))

    def test_an_explicit_false_is_the_only_thing_that_writes(self):
        self.assertFalse(self.call({"cloudIds": ["c-1"], "dryRun": False})["dry_run"])

    def test_an_absent_flag_previews_rather_than_writes(self):
        """The default has to be the safe one. `bool(d.get("dryRun"))` would
        make a missing field mean "write to his projects", which is the exact
        shape the dev toolbar's own route was careful to avoid."""
        self.assertTrue(self.call({"cloudIds": ["c-1"]})["dry_run"])

    def test_a_missing_selection_scopes_to_nothing_not_everything(self):
        """`only=None` sweeps the whole account. A payload with no ids must
        never become that."""
        got = self.call({})
        self.assertIsNotNone(got["only"])
        self.assertEqual([], list(got["only"]))


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheRowOffersItWhenItCanWorkTests(unittest.TestCase):
    """Rendered by the real row code, with the handler pulled back out."""

    PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
function fakeEl() {
  return { innerHTML: '', textContent: '', value: '', checked: false,
    hidden: false, disabled: false, dataset: {}, style: {}, children: [],
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){}, setAttribute(){}, getAttribute(){ return null; },
    querySelector(){ return null; }, querySelectorAll(){ return []; },
    appendChild(){}, remove(){}, focus(){}, click(){} };
}
const sandbox = {
  console, JSON, Math, Date, Map, Set, Promise, RegExp, Intl,
  setTimeout, clearTimeout, setInterval, clearInterval,
  document: { getElementById(){ return fakeEl(); },
    querySelector(){ return fakeEl(); }, querySelectorAll(){ return []; },
    createElement(){ return fakeEl(); }, addEventListener(){},
    body: fakeEl(), documentElement: fakeEl() },
  navigator: { platform: 'Win32', clipboard: { writeText: async () => {} } },
  location: { href: 'file:///cloud.html', search: '', hash: '' },
  localStorage: { getItem: () => null, setItem(){}, removeItem(){} },
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  alert(){}, confirm(){ return true; },
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

vm.runInContext("data = {currentUser:'me@example.invalid',matched:[],"
  + "cloudOnly:[],localOnly:[],orphans:{cloudOnly:[],localOnly:[]}};"
  + "currentTab = 'projects';", sandbox);
sandbox.__row = JSON.parse(process.argv[2]);
const html = vm.runInContext('rowDetailHtml(__row, "")', sandbox);

// Pull the handler back out of the markup and run it against a recorder.
// The control is delegated: its handler is named and its argument is a
// JSON list on the element, so nothing is evaluated out of the markup.
const tag = (html.match(/<[^>]*data-fn="reconcileNow"[^>]*>/) || [])[0];
let called = null;
const m = tag ? true : null;
if (tag) {
  const raw = (tag.match(/data-args-json="([^"]*)"/) || [])[1] || '[]';
  const args = JSON.parse(raw.replace(/&quot;/g, '"').replace(/&#39;/g, "'")
                             .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
                             .replace(/&amp;/g, '&'));
  sandbox.reconcileNow = (arg) => { called = arg; };
  try { sandbox.reconcileNow.apply(null, args); }
  catch (e) { called = { error: e.message }; }
}
process.stdout.write(JSON.stringify({
  html: html, offered: !!m, called: called,
}));
"""

    @staticmethod
    def _row(cmp_result, staleness="cloud_newer"):
        return {"kind": "projects", "status": "synced", "matchType": "id",
                "staleness": staleness, "differenceKind": "content",
                "namesDiffer": False, "comparison": cmp_result,
                "cloud": {"id": "c-1", "name": "SITE1 Riverside Final",
                          "mtime": 2000, "owner": "me@example.invalid"},
                "local": {"path": r"D:\E\SITE1 Riverside\SITE1 Riverside.esx",
                          "name": "SITE1 Riverside", "mtime": 1000}}

    def run_js(self, row):
        r = subprocess.run(
            ["node", "-e", self.PROGRAM, str(CLOUD_JS), json.dumps(row)],
            capture_output=True, text=True, encoding="utf-8",
            timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError("probe failed:\n" + (r.stderr or "")[-2500:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    IDENTICAL = {"identical": False, "designDiffers": False,
                 "renamedOnly": True, "summary": "Only the name differs",
                 "nameState": "internal_only", "checkedAt": 1758412800}
    DIFFERS = {"identical": False, "designDiffers": True, "renamedOnly": False,
               "summary": "3 access points differ", "nameState": "same",
               "checkedAt": 1758412800}

    def test_it_is_offered_when_the_contents_are_proven_identical(self):
        got = self.run_js(self._row(self.IDENTICAL))
        self.assertTrue(got["offered"], got["html"][:400])
        self.assertIn("Make them match", got["html"])

    def test_the_handler_receives_the_pair(self):
        """The control is verified by running it, not by finding its name."""
        got = self.run_js(self._row(self.IDENTICAL))
        self.assertEqual({"cloudId": "c-1",
                          "name": "SITE1 Riverside Final"}, got["called"])

    def test_it_is_not_offered_when_the_design_really_differs(self):
        """Writing to his file on a pair that genuinely changed is the one
        thing this must never do, and not offering it is the first guard."""
        got = self.run_js(self._row(self.DIFFERS))
        self.assertFalse(got["offered"], got["html"][:400])

    def test_it_is_not_offered_before_anything_has_been_compared(self):
        """Without a comparison there is no proof, and the date alone is not
        evidence the contents match."""
        got = self.run_js(self._row(None))
        self.assertFalse(got["offered"], got["html"][:400])

    def test_it_is_not_offered_when_his_copy_is_the_newer_one(self):
        got = self.run_js(self._row(self.IDENTICAL, staleness="local_newer"))
        self.assertFalse(got["offered"], got["html"][:400])


class TheRowWritesOnceAndDoesNotAskAgainTests(unittest.TestCase):
    """"Why does the make them match button prompt me again to make them
    match?"

    The row ran the bulk path: a preview - a second download and compare -
    then a confirm whose button carried the same label, then the live pass.
    The row only offers the action once a comparison has proved the designs
    identical, and the live pass re-checks before writing, so the second
    question protected nothing. The row goes straight to the live pass now;
    bulk, whose rows may never have been compared, keeps its preview.

    Both are run for real against recorders: the server calls that arrive,
    their `dry_run` flag in order, and whether a modal was opened.
    """

    PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
function fakeEl() {
  return { innerHTML: '', textContent: '', value: '', checked: false,
    hidden: false, disabled: false, dataset: {}, style: {}, children: [],
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){}, setAttribute(){}, getAttribute(){ return null; },
    querySelector(){ return null; }, querySelectorAll(){ return []; },
    appendChild(){}, remove(){}, focus(){}, click(){} };
}
const sandbox = {
  console, JSON, Math, Date, Map, Set, Promise, RegExp, Intl,
  setTimeout, clearTimeout, setInterval, clearInterval,
  document: { getElementById(){ return fakeEl(); },
    querySelector(){ return fakeEl(); }, querySelectorAll(){ return []; },
    createElement(){ return fakeEl(); }, addEventListener(){},
    body: fakeEl(), documentElement: fakeEl() },
  navigator: { platform: 'Win32', clipboard: { writeText: async () => {} } },
  location: { href: 'file:///cloud.html', search: '', hash: '' },
  localStorage: { getItem: () => null, setItem(){}, removeItem(){} },
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  alert(){}, confirm(){ return true; },
  requestAnimationFrame: (f) => setTimeout(f, 0),
  WD: { esc: s => String(s == null ? '' : s), applyVersions(){}, toast(){} },
};
sandbox.WD.escAttr = sandbox.WD.esc;
sandbox.WD.escJsStr = s => String(s == null ? '' : s);
sandbox.window = sandbox;
vm.createContext(sandbox);
try { vm.runInContext(source, sandbox, { filename: 'cloud.js' }); }
catch (err) { if (!/addEventListener|null|undefined/.test(err.message)) throw err; }

const reply = JSON.parse(process.argv[3]);
const calls = [], modals = [], toasts = [];
sandbox.pyApi = async (method, ids, dryRun) => {
  calls.push({ method, ids, dryRun });
  return dryRun ? reply.preview : reply.live;
};
sandbox.opEnqueue = (spec) => ({ promise: spec.run('op-1') });
sandbox.showConfirmModal = async (title, body, label) => {
  modals.push({ title, label }); return true;
};
sandbox.toast = (msg, kind) => { toasts.push({ msg, kind }); };
sandbox._scheduleOpRefresh = () => {};

(async () => {
  const which = process.argv[2];
  const pair = { cloudId: 'c-1', name: 'SITE1 Riverside Final' };
  if (which === 'row') await sandbox.reconcileNow(pair);
  else await sandbox.reconcilePairs([pair]);
  process.stdout.write(JSON.stringify({ calls, modals, toasts }));
})().catch(e => { console.error(e.stack || e.message); process.exit(1); });
"""

    ALIGNED = {"ok": True, "aligned": [{"cloudId": "c-1",
                                        "name": "SITE1 Riverside",
                                        "actions": ["Set the modified date "
                                                    "to the cloud's"]}],
               "skipped": [], "failed": []}
    REFUSED = {"ok": True, "aligned": [], "failed": [],
               "skipped": [{"cloudId": "c-1", "name": "SITE1 Riverside",
                            "reason": "The designs genuinely differ - "
                                      "2 access points moved."}]}

    def run_js(self, which, preview=None, live=None):
        reply = {"preview": preview or self.ALIGNED, "live": live or self.ALIGNED}
        r = subprocess.run(
            ["node", "-e", self.PROGRAM, str(CLOUD_JS), which, json.dumps(reply)],
            capture_output=True, text=True, encoding="utf-8",
            timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip()[-2500:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_row_makes_one_live_call_and_opens_no_modal(self):
        got = self.run_js("row")
        self.assertEqual([{"method": "reconcile_pairs", "ids": ["c-1"],
                           "dryRun": False}], got["calls"])
        self.assertEqual([], got["modals"])

    def test_the_row_says_it_is_done(self):
        got = self.run_js("row")
        self.assertTrue(any(t["kind"] == "success" and "now matches" in t["msg"]
                            for t in got["toasts"]), got["toasts"])

    def test_a_refusal_at_write_time_is_shown_with_its_reason(self):
        """The server is the guard now, so what it refuses has to reach him
        in its own words rather than as a count."""
        got = self.run_js("row", live=self.REFUSED)
        self.assertTrue(any("genuinely differ" in t["msg"] for t in got["toasts"]),
                        got["toasts"])
        self.assertFalse(any(t["kind"] == "success" for t in got["toasts"]))

    def test_bulk_still_previews_then_asks_then_writes(self):
        got = self.run_js("bulk")
        self.assertEqual([True, False], [c["dryRun"] for c in got["calls"]])
        self.assertEqual(1, len(got["modals"]))


if __name__ == "__main__":
    unittest.main()
