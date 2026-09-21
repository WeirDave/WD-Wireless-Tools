"""An answer he gave once is not asked for again.

"there are three files that say they needed to be checked, and when I check
them they just go away - until it refreshes again and then they come back."

Two faults stacked, and this file holds both.

**The answer was not kept.** A comparison lived in `_compareResults`, a
`Map` in the page and nowhere else. `compare_with_cloud` returned its verdict
and recorded nothing; `sync_state.record()` was called only by the two
operations that *make* the sides identical, never by the one that *finds* them
identical. So every reload threw away an answer that had cost a whole cloud
project download, and the pair went back to "not compared yet" and re-flagged.

**And the row left as it was answered.** He is under the filter for rows
needing a decision. Running the check settles the pair, a settled pair is no
longer out of sync, so it stopped matching the filter and vanished - the
result arrived and left in the same instant. The filter was behaving
correctly; answering the question should not remove the question from the
screen before it can be read.

The fix for the second is deliberately *not* "stop the list updating". A row
answered in this sitting is listed because its answer is known and shown, and
it goes on the next explicit refresh or filter change like any other settled
pair. `test_the_chip_does_not_count_a_row_that_is_only_being_held` is the
guard on the half that would otherwise go wrong: the number telling him how
much is left must not include rows that are done.

Every project name, path and address here is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import cloud_manager as cm
from tools import sync_state as ss


def _esx(path: Path, name: str, modified_iso: str) -> None:
    """The smallest archive `esx_compare` and `_esx_meta` both accept."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps({"project": {
            "id": "proj-1", "name": name, "title": name,
            "history": {"modifiedAt": modified_iso},
        }}))
        z.writestr("accessPoints.json", json.dumps({"accessPoints": []}))
        z.writestr("floorPlans.json", json.dumps({"floorPlans": []}))


class _StubApi:
    """Answers the one call `compare_with_cloud` makes. Nothing reaches a
    real account from this file."""

    def __init__(self, download_result):
        self._download = download_result

    def download_project(self, project_id, progress_cb=None):
        return self._download

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120

PATH = r"D:\Ekahau Projects\SITE1 Riverside\SITE1 Riverside Baseline.esx"
IDENTICAL = {"identical": True, "designDiffers": False, "renamedOnly": False,
             "summary": "", "nameState": "same", "differences": []}
DIFFERS = {"identical": False, "designDiffers": True, "renamedOnly": False,
           "summary": "3 access points differ", "nameState": "same",
           "differences": [{"what": "one"}] * 400}


class TheStoreKeepsAComparisonTests(unittest.TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.f = self.dir / "sync_state.json"

    def rec(self, verdict=IDENTICAL, c=1000, l=900, path=PATH):
        ss.record_comparison("c-1", path, c, l, verdict, _path=self.f)
        return ss.load(_path=self.f)

    def got(self, c=1000, l=900, path=PATH):
        return ss.comparison_for(ss.load(_path=self.f), "c-1", path, c, l)

    def test_a_comparison_is_written_and_comes_back(self):
        self.rec()
        got = self.got()
        self.assertIsNotNone(got, "the answer was not kept")
        self.assertTrue(got["identical"])

    def test_the_date_it_was_taken_comes_back_with_it(self):
        """The row says "checked 21 Sep", which is the evidence for being calm
        about a date difference. Without a stamp it is only an opinion."""
        self.rec()
        self.assertGreater(self.got()["checkedAt"], 0)

    def test_a_comparison_that_found_differences_is_kept_too(self):
        """Worth remembering for the same reason: he asked, it cost a
        download, and the row can say when it last looked."""
        self.rec(DIFFERS)
        got = self.got()
        self.assertFalse(got["identical"])
        self.assertEqual("3 access points differ", got["summary"])

    def test_the_list_of_differences_is_not_stored(self):
        """It runs to hundreds of entries on a project that has genuinely
        moved on, and the row shows the summary."""
        self.rec(DIFFERS)
        blob = json.loads(self.f.read_text(encoding="utf-8"))
        self.assertNotIn("differences",
                         blob["pairs"]["c-1"]["comparison"]["verdict"])

    # -- it is a measurement, not a sync point --------------------------

    def test_a_comparison_is_not_mistaken_for_a_sync_point(self):
        """`classify` answers "are these two the same"; a comparison that
        found them different must not make it say yes. They are kept under
        separate keys so this cannot happen by accident."""
        self.rec(DIFFERS)
        self.assertEqual(
            ss.UNKNOWN,
            ss.verdict_for(ss.load(_path=self.f), "c-1", PATH, 1000, 900))

    def test_a_sync_point_and_a_comparison_can_both_be_held(self):
        ss.record("c-1", PATH, 1000, 900, "pull", _path=self.f)
        self.rec()
        pairs = ss.load(_path=self.f)
        self.assertEqual(ss.IN_SYNC,
                         ss.verdict_for(pairs, "c-1", PATH, 1000, 900))
        self.assertIsNotNone(
            ss.comparison_for(pairs, "c-1", PATH, 1000, 900))

    def test_an_operation_that_moves_a_date_drops_the_old_comparison(self):
        """A pull rewrites the local file, so a comparison taken before it
        describes two files that no longer exist in that state."""
        self.rec()
        ss.record("c-1", PATH, 1000, 5000, "pull", _path=self.f)
        self.assertIsNone(
            ss.comparison_for(ss.load(_path=self.f), "c-1", PATH, 1000, 5000))

    # -- and it retires rather than going stale -------------------------

    def test_it_is_retired_when_the_cloud_copy_moves(self):
        """The whole risk of remembering. An answer from 09:00 does not
        describe a project somebody edited at 10:00, and a confidently wrong
        "settled" hides the change instead of showing it."""
        self.rec()
        self.assertIsNone(self.got(c=9999))

    def test_it_is_retired_when_the_local_file_moves(self):
        self.rec()
        self.assertIsNone(self.got(l=9999))

    def test_it_is_retired_when_the_local_file_is_renamed(self):
        self.rec()
        self.assertIsNone(self.got(path=PATH.replace("Baseline", "Final")))

    def test_a_second_of_drift_does_not_retire_it(self):
        """Filesystems and APIs disagree about a second or two, and a pair
        nobody touched must not re-ask on rounding."""
        self.rec()
        self.assertIsNotNone(self.got(c=1001, l=901))

    def test_a_missing_date_on_either_side_is_no_answer(self):
        self.rec()
        self.assertIsNone(self.got(c=0))
        self.assertIsNone(self.got(l=0))

    def test_a_corrupt_entry_is_no_answer_rather_than_an_error(self):
        ss.save({"c-1": {"comparison": "not a dict"}}, _path=self.f)
        self.assertIsNone(self.got())


class TheRowCarriesTheAnswerTests(unittest.TestCase):
    """The round trip: recorded once, on the row every time after."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.f = self.dir / "sync_state.json"

    def build(self, cloud_mtime=1000, local_mtime=900):
        cloud = [{"id": "c-1", "name": "SITE1 Riverside Baseline",
                  "mtime": cloud_mtime, "owner": "me@example.invalid",
                  "code": None}]
        local = [{"path": PATH, "name": "SITE1 Riverside Baseline",
                  "mtime": local_mtime, "folder": "SITE1 Riverside"}]
        real = ss.STATE_FILE
        ss.STATE_FILE = self.f
        try:
            return cm.build_matches(cloud, local, set(), {})
        finally:
            ss.STATE_FILE = real

    def test_a_pair_never_compared_carries_no_answer(self):
        row = self.build()["matched"][0]
        self.assertIsNone(row.get("comparison"))

    def test_a_recorded_comparison_arrives_on_the_row(self):
        """This is the reload. Nothing from the page is involved - the list
        is built fresh and the answer is already on it."""
        ss.record_comparison("c-1", PATH, 1000, 900, IDENTICAL, _path=self.f)
        row = self.build()["matched"][0]
        self.assertIsNotNone(row.get("comparison"),
                             "the answer did not survive the rebuild")
        self.assertTrue(row["comparison"]["identical"])

    def test_an_answer_overtaken_by_an_edit_is_not_offered(self):
        ss.record_comparison("c-1", PATH, 1000, 900, IDENTICAL, _path=self.f)
        row = self.build(cloud_mtime=8888)["matched"][0]
        self.assertIsNone(row.get("comparison"))


class ComparingIsWhatWritesTheAnswerTests(unittest.TestCase):
    """The fault itself: `compare_with_cloud` returned a verdict and kept
    nothing.

    Everything above tests a record that something else wrote. This drives the
    real method against a stub cloud, so deleting the one line that records
    the answer fails here rather than leaving the suite green over a feature
    that never remembers anything.
    """

    ISO = "2026-09-21T10:00:00Z"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.tmp / "sync_state.json"
        self._real_state = ss.STATE_FILE
        ss.STATE_FILE = self.state
        self.addCleanup(lambda: setattr(ss, "STATE_FILE", self._real_state))

        #: In a project folder, which is the shape `get_local_esx_files`
        #: scans - the same layout his own folder has.
        folder = self.tmp / "SITE1 Riverside"
        folder.mkdir()
        self.local = folder / "SITE1 Riverside Baseline.esx"
        _esx(self.local, "SITE1 Riverside Baseline", self.ISO)
        self.cloud_bytes = self.local.read_bytes()

    def _mgr(self):
        mgr = cm.CloudManager.__new__(cm.CloudManager)
        mgr.config = {"output_dir": str(self.tmp)}
        mgr._ensure = lambda: True
        mgr.api = _StubApi({"esx": self.cloud_bytes,
                            "name": "SITE1 Riverside Baseline"})
        return mgr

    def test_comparing_records_the_answer(self):
        out = self._mgr().compare_with_cloud(str(self.local), "c-1",
                                             cloud_mtime=1000)
        self.assertNotIn("error", out, out)
        held = ss.comparison_for(ss.load(_path=self.state), "c-1",
                                 str(self.local), 1000, out["localMtime"])
        self.assertIsNotNone(held, "the comparison was thrown away")

    def test_the_answer_it_kept_is_the_answer_it_gave(self):
        out = self._mgr().compare_with_cloud(str(self.local), "c-1",
                                             cloud_mtime=1000)
        held = ss.comparison_for(ss.load(_path=self.state), "c-1",
                                 str(self.local), 1000, out["localMtime"])
        self.assertEqual(bool(out.get("identical")), bool(held["identical"]))
        self.assertEqual(bool(out.get("designDiffers")),
                         bool(held["designDiffers"]))

    def test_the_local_date_it_fingerprints_with_is_the_one_the_list_reads(self):
        """`get_local_esx_files` reports `history.modifiedAt` from inside the
        .esx, falling back to the filesystem. Recorded against any other
        number, the record is written and then never matches again - the
        memory silently never works, and comparing still looks fine."""
        out = self._mgr().compare_with_cloud(str(self.local), "c-1",
                                             cloud_mtime=1000)
        listed = cm.get_local_esx_files(str(self.tmp))
        mine = [f for f in listed
                if Path(f["path"]).name == self.local.name]
        self.assertTrue(mine, listed)
        self.assertEqual(int(mine[0]["mtime"]), int(out["localMtime"]))

    def test_with_no_cloud_date_nothing_is_stored(self):
        """There would be nothing to retire it against, and a record that
        cannot go stale is the one thing worse than no record."""
        out = self._mgr().compare_with_cloud(str(self.local), "c-1")
        self.assertNotIn("error", out, out)
        self.assertEqual({}, ss.load(_path=self.state))

    def test_a_store_that_will_not_write_does_not_lose_the_comparison(self):
        """He asked a question; an answer he can read now matters more than a
        record of it."""
        def boom(*a, **k):
            raise OSError("the disk said no")
        real = ss.record_comparison
        ss.record_comparison = boom
        try:
            out = self._mgr().compare_with_cloud(str(self.local), "c-1",
                                                 cloud_mtime=1000)
        finally:
            ss.record_comparison = real
        self.assertNotIn("error", out, out)
        self.assertTrue(out.get("identical"))


class TheAnswerIsPartOfHisSettingsTests(unittest.TestCase):

    def test_the_store_is_carried_by_the_export(self):
        """Each entry is a whole cloud project downloaded and compared. A
        reinstall that loses them asks every question again."""
        from tools import settings_backup
        self.assertIn("sync_state.json", settings_backup.EXPORT_FILES)

    def test_it_is_not_on_the_never_list(self):
        from tools import settings_backup
        self.assertNotIn("sync_state.json", settings_backup.NEVER_EXPORT)


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheRowStaysWhileHeReadsItTests(unittest.TestCase):
    """The page half, driven through the real functions.

    `compareResultFor` and the filter predicate are taken out of the shipped
    file and run; nothing here asserts that a line of source exists.
    """

    PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
function cut(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}
const sandbox = { console, JSON, Math, Set, Map, RegExp, Date, Number, String,
                  Boolean, Object, isNaN };
sandbox.rowData = {};
vm.createContext(sandbox);
vm.runInContext(
    cut('const _compareResults = new Map();', 'function compareResultFor(')
  + cut('function compareResultFor(', '/* Download the cloud copy and diff')
  + cut('function comparisonIsSettled(', 'function isOutOfSync(')
  /* The file is CRLF, so a marker carrying bare newlines matches nothing -
     and the failure reads as "the function has moved" rather than as a
     line-ending problem. Markers here are plain text for that reason. */
  + cut('function isOutOfSync(', '/* Is this cloud project filed under no site')
  , sandbox);

const row = JSON.parse(process.argv[2]);
const answered = process.argv[3] === 'yes';
if (answered) {
  vm.runInContext('_answeredHere.add(_compareKey('
    + JSON.stringify(row.cloud.id) + ',' + JSON.stringify(row.local.path)
    + '))', sandbox);
}
sandbox.__row = row;
const out = vm.runInContext(`JSON.stringify({
  cmp: compareResultFor(__row),
  outOfSync: isOutOfSync(__row),
  held: answeredHere(__row),
  listedByFilter: isOutOfSync(__row) || answeredHere(__row),
  when: typeof checkedWhen === 'function' ? checkedWhen(compareResultFor(__row)) : null,
})`, sandbox);
process.stdout.write(out);
"""

    @staticmethod
    def _row(comparison=None):
        return {"cloud": {"id": "c-1", "name": "SITE1 Riverside Baseline",
                          "mtime": 1000},
                "local": {"path": PATH, "name": "SITE1 Riverside Baseline",
                          "mtime": 900},
                "matchType": "id", "staleness": "cloud_newer",
                "comparison": comparison}

    def run_js(self, row, answered=False):
        r = subprocess.run(
            ["node", "-e", self.PROGRAM, str(CLOUD_JS), json.dumps(row),
             "yes" if answered else "no"],
            capture_output=True, text=True, encoding="utf-8",
            timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError("probe failed:\n" + (r.stderr or "")[-2500:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_without_a_stored_answer_the_row_still_needs_him(self):
        got = self.run_js(self._row())
        self.assertIsNone(got["cmp"])
        self.assertTrue(got["outOfSync"])

    def test_the_stored_answer_is_used_when_the_page_has_none(self):
        """The reload. `_compareResults` is empty - this is a fresh page - and
        the verdict comes off the row the server built."""
        got = self.run_js(self._row(dict(IDENTICAL, checkedAt=1758412800)))
        self.assertIsNotNone(got["cmp"], "the page ignored the stored answer")
        self.assertFalse(got["outOfSync"],
                         "he would be asked the same question again")

    def test_a_stored_answer_that_found_differences_still_needs_him(self):
        got = self.run_js(self._row(dict(DIFFERS, checkedAt=1758412800)))
        self.assertTrue(got["outOfSync"])

    def test_the_row_says_when_it_was_checked(self):
        got = self.run_js(self._row(dict(IDENTICAL, checkedAt=1758412800)))
        self.assertIn("checked", got["when"])

    def test_an_answer_with_no_stamp_says_nothing_about_when(self):
        """Inventing today's date for an answer of unknown age would be worse
        than staying quiet."""
        got = self.run_js(self._row(dict(IDENTICAL)))
        self.assertEqual("", got["when"])

    def test_holding_a_row_is_not_the_same_as_calling_it_unsettled(self):
        got = self.run_js(self._row(dict(IDENTICAL, checkedAt=1758412800)),
                          answered=True)
        self.assertTrue(got["held"])
        self.assertIsNotNone(got["cmp"])

    def test_the_chip_does_not_count_a_row_that_is_only_being_held(self):
        """The half that would otherwise go wrong. The number telling him how
        much is left must not include rows that are done - that is the
        "the counter disagrees with the list" bug wearing a new hat, and
        `isOutOfSync` is what the chip counts with."""
        got = self.run_js(self._row(dict(IDENTICAL, checkedAt=1758412800)),
                          answered=True)
        self.assertFalse(got["outOfSync"])


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheRowIsStillInTheRenderedListTests(unittest.TestCase):
    """The complaint, through the list he was actually looking at.

    The test above asks the two predicates separately, which is a second
    spelling of the filter and would go on passing if `renderLedger` stopped
    using them. This renders the real ledger under the real "needs a decision"
    filter and looks for the row in the HTML that comes out.
    """

    PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
function fakeEl() {
  return { innerHTML: '', textContent: '', value: '', checked: false,
    hidden: false, dataset: {}, style: {}, children: [], parentElement: null,
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){}, removeEventListener(){}, setAttribute(){},
    getAttribute(){ return null; }, removeAttribute(){}, closest(){ return null; },
    querySelector(){ return null; }, querySelectorAll(){ return []; },
    appendChild(){}, remove(){}, focus(){}, click(){}, scrollIntoView(){},
    getBoundingClientRect(){ return { top:0, left:0, width:0, height:0 }; } };
}
const sandbox = {
  console, JSON, Math, Date, Map, Set, Promise, RegExp, Intl,
  setTimeout, clearTimeout, setInterval, clearInterval,
  document: { getElementById(){ return fakeEl(); }, querySelector(){ return fakeEl(); },
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

const payload = JSON.parse(process.argv[2]);
vm.runInContext('data = ' + JSON.stringify(payload.data)
  + ';currentTab = ' + JSON.stringify(payload.tab)
  + '; activeFilter = ' + JSON.stringify(payload.filter)
  + "; activeLetter = ''; collapsed = new Set();", sandbox);
if (payload.answered) {
  vm.runInContext('_answeredHere.add(_compareKey('
    + JSON.stringify(payload.cloudId) + ',' + JSON.stringify(payload.localPath)
    + '))', sandbox);
}
process.stdout.write(vm.runInContext(
  'renderLedger(function () { return true; })', sandbox));
"""

    NEEDS_ONE = "Riverside Baseline"

    @staticmethod
    def _pair(comparison):
        return {"cloud": {"id": "c-1", "name": "SITE1 Riverside Baseline",
                          "owner": "me@example.invalid", "mtime": 1000,
                          "sharedWith": [], "meta": "2 hr ago"},
                "local": {"path": PATH, "name": "SITE1 Riverside Baseline",
                          "folder": "SITE1 Riverside", "mtime": 900,
                          "meta": "14 Aug"},
                "matchType": "id", "staleness": "cloud_newer",
                "namesDiffer": False, "comparison": comparison}

    def render(self, comparison, answered, filt="stale", tab="projects"):
        pair = self._pair(comparison)
        if tab == "sites":
            #: The Sites tree is his primary view and builds its rows through
            #: a different projection, so it needs covering separately - a
            #: field carried on one tab and dropped on the other is exactly
            #: how this reached him.
            kids = {"matched": [pair], "cloudOnly": [], "localOnly": []}
            matched = [{
                "cloud": {"id": "s-1", "name": "SITE1 Riverside",
                          "owner": "me@example.invalid", "hasSite": True,
                          "meta": "2 hr ago", "sharedWith": [],
                          "children": kids},
                "local": {"path": r"D:\Ekahau Projects\SITE1 Riverside",
                          "name": "SITE1 Riverside", "isDir": True,
                          "meta": "14 Aug", "children": kids},
                "matchType": "exact", "staleness": None,
                "namesDiffer": False}]
        else:
            matched = [pair]
        payload = {
            "data": {"currentUser": "me@example.invalid",
                     "summary": {"matched": 1}, "matched": matched,
                     "cloudOnly": [], "localOnly": [],
                     "orphans": {"cloudOnly": [], "localOnly": []}},
            "filter": filt, "answered": answered, "tab": tab,
            "cloudId": "c-1", "localPath": PATH,
        }
        r = subprocess.run(
            ["node", "-e", self.PROGRAM, str(CLOUD_JS), json.dumps(payload)],
            capture_output=True, text=True, encoding="utf-8",
            timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError("render failed:\n" + (r.stderr or "")[-2500:])
        return r.stdout

    def test_an_unchecked_pair_is_in_the_list(self):
        self.assertIn(self.NEEDS_ONE, self.render(None, False))

    def test_answering_it_is_what_used_to_take_it_away(self):
        """With the answer known and nothing holding the row, it correctly
        leaves the list - which is the filter working, and the behaviour the
        hold exists to soften."""
        html = self.render(dict(IDENTICAL, checkedAt=1758412800), False)
        self.assertNotIn(self.NEEDS_ONE, html)

    def test_a_row_answered_here_keeps_its_place(self):
        """The complaint: "when I check them they just go away". """
        html = self.render(dict(IDENTICAL, checkedAt=1758412800), True)
        self.assertIn(self.NEEDS_ONE, html,
                      "the row left the list as he answered it")

    def test_and_it_shows_the_answer_rather_than_just_sitting_there(self):
        """Holding a row that still reads "not checked" would be worse than
        letting it go - he would press the button again."""
        html = self.render(dict(IDENTICAL, checkedAt=1758412800), True)
        self.assertIn("Exact match", html)
        self.assertIn("checked", html)

    # -- and the same on the tab he actually works in --------------------

    def test_the_sites_tree_uses_the_stored_answer_too(self):
        """His primary view. It builds its rows through its own projection,
        so it can carry a field the Projects tab carries and vice versa."""
        html = self.render(dict(IDENTICAL, checkedAt=1758412800), False,
                           filt="all", tab="sites")
        self.assertIn("Exact match", html,
                      "the tree ignored the stored answer")

    def test_the_sites_tree_still_asks_when_nothing_is_stored(self):
        html = self.render(None, False, filt="all", tab="sites")
        self.assertNotIn("Exact match", html)


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheSiteCountAgreesWithTheStoredAnswerTests(unittest.TestCase):
    """The number on the folder, which is counted separately again.

    `siteDigest` builds its own rows out of named fields and counts
    "needs attention" with `isOutOfSync`. A stored answer that reaches the
    row but not the digest gives him a site saying "1 needs attention" over a
    list where nothing does - the counter-disagrees-with-the-list bug that
    has already been reported twice here.
    """

    PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
function cut(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}
const sandbox = { console, JSON, Math, Set, Map, RegExp, Date, Number, String,
                  Boolean, Object, isNaN };
sandbox.rowData = {};
vm.createContext(sandbox);
vm.runInContext(
    cut('const _compareResults = new Map();', 'function compareResultFor(')
  + cut('function compareResultFor(', '/* Download the cloud copy and diff')
  + cut('function comparisonIsSettled(', 'function isOutOfSync(')
  + cut('function isOutOfSync(', '/* Is this cloud project filed under no site')
  + cut('function siteDigest(', '\nfunction siteDigestHtml(')
  , sandbox);
sandbox.__children = JSON.parse(process.argv[2]);
process.stdout.write(vm.runInContext(
  'JSON.stringify(siteDigest(__children, {}))', sandbox));
"""

    def digest(self, comparison):
        children = {"matched": [{
            "cloud": {"id": "c-1", "name": "SITE1 Riverside Baseline",
                      "mtime": 1000},
            "local": {"path": PATH, "name": "SITE1 Riverside Baseline",
                      "mtime": 900},
            "matchType": "id", "staleness": "cloud_newer",
            "namesDiffer": False, "comparison": comparison}],
            "cloudOnly": [], "localOnly": []}
        r = subprocess.run(
            ["node", "-e", self.PROGRAM, str(CLOUD_JS), json.dumps(children)],
            capture_output=True, text=True, encoding="utf-8",
            timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError("digest failed:\n" + (r.stderr or "")[-2500:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_an_unchecked_pair_counts_as_needing_him(self):
        self.assertEqual(1, self.digest(None)["attention"])

    def test_a_pair_with_a_stored_answer_does_not(self):
        got = self.digest(dict(IDENTICAL, checkedAt=1758412800))
        self.assertEqual(0, got["attention"],
                         "the folder still says this needs a decision")
        self.assertEqual(1, got["ok"])

    def test_a_stored_answer_that_found_differences_still_counts(self):
        self.assertEqual(
            1, self.digest(dict(DIFFERS, checkedAt=1758412800))["attention"])


if __name__ == "__main__":
    unittest.main()
