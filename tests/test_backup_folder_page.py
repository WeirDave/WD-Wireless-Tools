"""Click the controls on the Backup Folder tab and watch what arrives.

The tab exists to put a file back. Every assertion here therefore runs the
real render function, pulls the `onclick` back **out of the rendered markup**,
and executes that string - so a handler that is missing, misnamed, takes
different arguments, or bails before reaching the server fails the test.
Nothing here asserts that `cloud.js` contains `bakRestore(`.

Three things it is specifically built to catch, each one a defect this
repository has already paid for:

* **A control that renders and does nothing.** `Local -> Cloud` shipped
  looking perfect and was inert for every pair he owned, and the tests were
  green throughout because they asserted the markup contained the call.
* **A dialog that names the wrong place.** Five dialogs told him the wrong
  location for a file he had just overwritten. So the confirm is checked
  against the item's own `restoreTo` - the field the server restores to -
  rather than against a sentence somebody pinned.
* **A path that kills the handler.** Real project folders carry apostrophes
  and backslashes. The row markup carries an index rather than a path for
  exactly that reason, and `WD.escJsStr` here is the **real** one, sliced out
  of `wd-shared.js`, so a quoting change that breaks a handler breaks this.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
SHARED_JS = ROOT / "web" / "assets" / "js" / "wd-shared.js"
NODE_TIMEOUT_S = 120

NODE_SCRIPT = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
const shared = fs.readFileSync(process.argv[3], 'utf8');

function slice(src, from, to) {
  const a = src.indexOf(from);
  const b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}

// The tab, plus the three date/size formatters that sit directly under it -
// stubbing those would test the stubs, and "3 days ago" on the wrong row is
// exactly the sort of thing nobody notices until it is on a screen.
const block = slice(source, 'let bakData = null;', '\nfunction toggleFolder(');

// The real escapers. A path with an apostrophe in it is not a hypothetical.
const WD = {};
eval(slice(shared, '  WD.escAttr = function (s) {', '  WD.safeColor ='));
WD.esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

// ── the seams ───────────────────────────────────────────────────────────────
const apiCalls = [];
const confirms = [];
const toasts = [];
let confirmAnswer = true;
let apiResult = { ok: true };
let drawn = '';

WD.api = async (action, body) => { apiCalls.push([action, body]); return apiResult; };
function toast(msg, kind) { toasts.push({ msg: String(msg), kind: kind }); }
async function showConfirmModal(title, body, label) {
  confirms.push({ title: String(title), body: String(body), label: String(label) });
  return confirmAnswer;
}
function updateDashboard() {}

// A document just big enough for the tab to draw into.
const els = {};
function el(id) {
  if (!els[id]) els[id] = { id, value: '', innerHTML: '', textContent: '',
                            checked: false, hidden: false, title: '' };
  return els[id];
}
el('searchBox').value = '';
const rows = el('rowsContainer');
Object.defineProperty(rows, 'innerHTML', {
  get() { return drawn; }, set(v) { drawn = String(v); },
});
const document = {
  getElementById: (id) => el(id),
  querySelector: () => null,
  querySelectorAll: () => [],
  scrollingElement: { scrollTop: 0 },
  documentElement: { scrollTop: 0 },
};

const fn = new Function('WD', 'document', 'toast', 'showConfirmModal', 'updateDashboard',
  'let currentTab = "backups";\nlet activeFilter = "all";\n'
  + 'function e(s){return WD.esc(s);}\n'
  + 'function a(s){return WD.escAttr(s);}\n'
  + 'function j(s){return WD.escJsStr(s);}\n'
  + block
  + '\nreturn { onBackups, renderBackups, bakGroupHtml, bakRestore, bakReveal,'
  + ' bakDeleteOne, bakDeleteChecked, bakCheck, bakSelectAll, bakToggleGroup,'
  + ' bakIsProject, bakShortPath, bakCheckedItems,'
  + ' setFilter_: (f) => { activeFilter = f; },'
  + ' drawnRows: () => bakIndex.length };');
const api = fn(WD, document, toast, showConfirmModal, updateDashboard);

// ── the payload, shaped exactly as `/api/backups/list` returns it ───────────
const ROOTC = "C:\\Users\\wduser\\Ekahau Projects";
const listing = {
  ok: true, keep: 3, count: 4, bytes: 1024 * 1024 * 9, human: '9.0 MB',
  roots: [ROOTC],
  groups: [
    {
      key: (ROOTC + "\\o'brien's site\\north survey.esx").toLowerCase(),
      target: ROOTC + "\\O'Brien's Site\\North Survey.esx",
      name: "North Survey.esx",
      folder: ROOTC + "\\O'Brien's Site",
      exists: true, kind: 'file',
      bytes: 1024 * 1024 * 8, count: 2, newest: '20260214-101500',
      items: [
        { path: ROOTC + "\\backups\\O'Brien's Site\\North Survey.previous-20260214-101500.esx",
          name: "North Survey.previous-20260214-101500.esx",
          folder: ROOTC + "\\backups\\O'Brien's Site",
          stamp: '20260214-101500', when: 1771063200, bytes: 1024 * 1024 * 5,
          kind: 'file', restoreTo: ROOTC + "\\O'Brien's Site\\North Survey.esx",
          targetExists: true },
        { path: ROOTC + "\\backups\\O'Brien's Site\\North Survey.previous-20260101-090000.esx",
          name: "North Survey.previous-20260101-090000.esx",
          folder: ROOTC + "\\backups\\O'Brien's Site",
          stamp: '20260101-090000', when: 1767258000, bytes: 1024 * 1024 * 3,
          kind: 'file', restoreTo: ROOTC + "\\O'Brien's Site\\North Survey.esx",
          targetExists: true },
      ],
    },
    {
      key: (ROOTC + "\\lakeside\\lakeside design.esx").toLowerCase(),
      target: ROOTC + "\\Lakeside\\Lakeside Design.esx",
      name: "Lakeside Design.esx",
      folder: ROOTC + "\\Lakeside",
      exists: false, kind: 'file',
      bytes: 1024 * 512, count: 1, newest: '20260102-080000',
      items: [
        { path: ROOTC + "\\backups\\Lakeside\\Lakeside Design.previous-20260102-080000.esx",
          name: "Lakeside Design.previous-20260102-080000.esx",
          folder: ROOTC + "\\backups\\Lakeside",
          stamp: '20260102-080000', when: 1767344400, bytes: 1024 * 512,
          kind: 'file', restoreTo: ROOTC + "\\Lakeside\\Lakeside Design.esx",
          targetExists: false },
      ],
    },
    {
      key: 'c:\\tools\\wd-wireless-tools',
      target: 'C:\\Tools\\WD-Wireless-Tools',
      name: 'WD-Wireless-Tools',
      folder: 'C:\\Tools',
      exists: true, kind: 'install',
      bytes: 1024 * 1024 * 40, count: 1, newest: '20260110-120000',
      items: [
        { path: 'C:\\Tools\\WD-Wireless-Tools.previous-v2.136.3-20260110-120000',
          name: 'WD-Wireless-Tools.previous-v2.136.3-20260110-120000',
          folder: 'C:\\Tools', stamp: '20260110-120000', when: 1768046400,
          bytes: 1024 * 1024 * 40, kind: 'install',
          restoreTo: 'C:\\Tools\\WD-Wireless-Tools', targetExists: true },
      ],
    },
  ],
};

function draw() {
  apiCalls.length = 0; confirms.length = 0; toasts.length = 0;
  api.onBackups('backups', JSON.parse(JSON.stringify(listing)));
  return drawn;
}

/* Pull a handler back out of the drawn page and run it. This is the step a
   substring assertion cannot do, and the one that catches a control that is
   on screen and dead. */
function clickIn(html, pattern) {
  const m = pattern.exec(html);
  if (!m) return null;
  return new Function('api', 'return api.' + m[1] + ';');
}
async function click(html, pattern) {
  const f = clickIn(html, pattern);
  if (!f) throw new Error('no handler matched ' + pattern + ' in: ' + html.slice(0, 400));
  return await f(api);
}

(async () => {
  const out = {};

  // ── the list draws, and draws every generation ────────────────────────────
  let html = draw();
  out.rowsDrawn = api.drawnRows();
  out.groupHeads = (html.match(/class="bak-head"/g) || []).length;
  out.restoreButtons = (html.match(/onclick="bakRestore\(/g) || []).length;
  out.deleteButtons = (html.match(/onclick="bakDeleteOne\(/g) || []).length;
  out.showButtons = (html.match(/onclick="bakReveal\(/g) || []).length;
  out.saysOriginalGone = /original gone/.test(html);
  out.saysPreviousInstall = /previous install/.test(html);
  out.quotesRetention = /newest <b>3<\/b>/.test(html);

  // ── restore: the first row, clicked for real ──────────────────────────────
  html = draw();
  confirmAnswer = true;
  apiResult = { ok: true, restored: listing.groups[0].items[0].restoreTo,
                kept: 'somewhere', replaced: true };
  await click(html, /onclick="(bakRestore\(0\))"/);
  out.restoreAsked = confirms.length;
  out.restoreConfirmBody = confirms.length ? confirms[0].body : '';
  out.restoreCalls = apiCalls.slice();
  out.restoreToasts = toasts.slice();

  // ── a refused confirm must write nothing ──────────────────────────────────
  html = draw();
  confirmAnswer = false;
  await click(html, /onclick="(bakRestore\(0\))"/);
  out.refusedCalls = apiCalls.slice();
  confirmAnswer = true;

  // ── an error from the server is reported, not swallowed ───────────────────
  html = draw();
  apiResult = { error: 'That backup is no longer on disk. Refresh the list.' };
  await click(html, /onclick="(bakRestore\(0\))"/);
  out.errorToasts = toasts.slice();
  apiResult = { ok: true, restored: 'x', replaced: false };

  // ── the second generation is a different file, not the first again ────────
  html = draw();
  await click(html, /onclick="(bakRestore\(1\))"/);
  out.secondRestoreCalls = apiCalls.slice();

  // ── delete: one row ───────────────────────────────────────────────────────
  html = draw();
  apiResult = { ok: true, count: 1, freed: 10, human: '10 B', skipped: [] };
  await click(html, /onclick="(bakDeleteOne\(0\))"/);
  out.deleteConfirmBody = confirms.length ? confirms[0].body : '';
  out.deleteCalls = apiCalls.slice();

  // ── delete: everything ticked, across groups ──────────────────────────────
  html = draw();
  api.bakCheck(0, true);
  api.bakCheck(2, true);
  await api.bakDeleteChecked();
  out.bulkCalls = apiCalls.slice();
  out.bulkConfirmTitle = confirms.length ? confirms[0].title : '';

  // ── nothing ticked says so rather than deleting everything ────────────────
  html = draw();
  api.bakSelectAll(false);
  await api.bakDeleteChecked();
  out.emptyBulkCalls = apiCalls.slice();
  out.emptyBulkToasts = toasts.slice();

  // ── show in explorer ──────────────────────────────────────────────────────
  html = draw();
  await click(html, /onclick="(bakReveal\(0\))"/);
  out.revealCalls = apiCalls.slice();

  // ── an install backup offers no restore, and the delete warns ─────────────
  //: Its own group markup for the first three, because that is where the
  //: absence has to show; the delete is clicked out of the *whole* page, so
  //: the index it carries is the one the drawn list actually holds.
  html = draw();
  const installHtml = api.bakGroupHtml(listing.groups[2], 3);
  out.installHasRestore = /bakRestore\(/.test(installHtml);
  out.installHasDelete = /bakDeleteOne\(/.test(installHtml);
  out.installSaysWhere = /restore from About/.test(installHtml);
  await click(html, /onclick="(bakDeleteOne\(3\))"/);
  out.installDeleteBody = confirms.length ? confirms[0].body : '';
  out.installDeletePath = apiCalls.length && apiCalls[0][1].paths
    ? apiCalls[0][1].paths[0] : '';

  // ── the folder head toggles, with an apostrophe and backslashes in the key
  html = draw();
  //: Counted, not tested for presence: three groups are drawn open, so
  //: "is there an expanded group" is true whichever one the click shut.
  out.openBefore = (html.match(/bak-group expanded/g) || []).length;
  //: `[^"]*` rather than a lazy match: the key has been through the real
  //: `escJsStr`, so an apostrophe in it arrives as \' and a lazy match would
  //: stop on the escape and hand back a broken call. The attribute's own
  //: closing quote is the only reliable boundary.
  await click(html, /onclick="(bakToggleGroup\([^"]*\))"/);
  out.openAfter = (drawn.match(/bak-group expanded/g) || []).length;

  // ── a place that could not be read is admitted to, as a count ─────────────
  listing.unreadable = 2;
  html = draw();
  out.blockedNote = /bak-blocked-note/.test(html);
  out.blockedSaysHowMany = /2 places/.test(html);
  out.blockedNamesNoPath = !/\$Recycle|S-1-5-21|C:\\/.test(
    (/<div class="bak-blocked-note">[\s\S]*?<\/div>/.exec(html) || [''])[0]);
  listing.unreadable = 0;
  html = draw();
  out.noNoteWhenNothingBlocked = !/bak-blocked-note/.test(html);

  // ── the filters pick the rows they say they do ────────────────────────────
  api.setFilter_('bak-install');
  api.renderBackups();
  out.installFilterRows = api.drawnRows();
  api.setFilter_('bak-missing');
  api.renderBackups();
  out.missingFilterRows = api.drawnRows();
  api.setFilter_('bak-project');
  api.renderBackups();
  out.projectFilterRows = api.drawnRows();
  api.setFilter_('all');

  // ── the path shown on a row is the part that differs ──────────────────────
  out.shortened = api.bakShortPath(ROOTC + "\\O'Brien's Site");

  console.log(JSON.stringify(out));
})().catch(err => { console.log(JSON.stringify({ fatal: String(err && err.stack || err) })); });
"""


class BackupFolderPageTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(NODE_SCRIPT)
            cls.script = fh.name
        try:
            proc = subprocess.run(
                ["node", cls.script, str(CLOUD_JS), str(SHARED_JS)],
                capture_output=True, text=True, encoding="utf-8",
                timeout=NODE_TIMEOUT_S)
        except FileNotFoundError:
            raise unittest.SkipTest("node is not installed")
        if proc.returncode != 0:
            raise AssertionError("node failed: " + (proc.stderr or "")[-3000:])
        cls.out = json.loads(proc.stdout.strip().splitlines()[-1])
        if cls.out.get("fatal"):
            raise AssertionError("the page threw: " + cls.out["fatal"])

    # ── it draws ────────────────────────────────────────────────────────────
    def test_every_generation_of_every_file_gets_a_row(self):
        self.assertEqual(self.out["rowsDrawn"], 4)
        self.assertEqual(self.out["groupHeads"], 3)

    def test_every_file_backup_offers_a_restore_and_every_row_a_delete(self):
        self.assertEqual(self.out["restoreButtons"], 3)   # not the install
        self.assertEqual(self.out["deleteButtons"], 4)
        self.assertEqual(self.out["showButtons"], 4)

    def test_the_two_states_worth_knowing_are_on_screen(self):
        self.assertTrue(self.out["saysOriginalGone"])
        self.assertTrue(self.out["saysPreviousInstall"])

    def test_the_page_says_how_many_generations_are_kept(self):
        """Why there are three of something and not thirty is the first
        question this list provokes, so it is answered on it."""
        self.assertTrue(self.out["quotesRetention"])

    # ── restore ─────────────────────────────────────────────────────────────
    def test_clicking_restore_asks_first_and_then_calls_the_server(self):
        self.assertEqual(self.out["restoreAsked"], 1)
        self.assertEqual(self.out["restoreCalls"][0],
                         ["backups/restore",
                          {"path": "C:\\Users\\wduser\\Ekahau Projects\\backups\\"
                                   "O'Brien's Site\\North Survey.previous-"
                                   "20260214-101500.esx"}])

    def test_the_list_is_re_read_after_a_restore(self):
        """Restoring writes a new backup of the file it replaced. A list that
        does not show it is a list that is already wrong."""
        self.assertIn("backups/list", [c[0] for c in self.out["restoreCalls"]])

    def test_the_confirm_names_the_path_the_restore_will_write_to(self):
        """Not a sentence somebody pinned - the destination itself, read off
        the same field the server writes to."""
        body = self.out["restoreConfirmBody"]
        self.assertIn("C:\\Users\\wduser\\Ekahau Projects\\O'Brien's Site\\"
                      "North Survey.esx", body.replace("&#39;", "'"))

    def test_the_confirm_says_the_file_being_replaced_is_kept(self):
        self.assertIn("kept", self.out["restoreConfirmBody"])

    def test_saying_no_writes_nothing(self):
        self.assertEqual(self.out["refusedCalls"], [])

    def test_a_server_error_reaches_the_screen(self):
        kinds = [t["kind"] for t in self.out["errorToasts"]]
        self.assertIn("error", kinds)
        self.assertTrue(any("no longer on disk" in t["msg"]
                            for t in self.out["errorToasts"]))

    def test_the_row_that_was_clicked_is_the_one_that_is_restored(self):
        """An index that drifts by one restores the wrong generation, which
        is a silent, destructive way to be wrong."""
        path = self.out["secondRestoreCalls"][0][1]["path"]
        self.assertIn("20260101-090000", path)

    # ── delete ──────────────────────────────────────────────────────────────
    def test_deleting_one_names_it_and_sends_that_one_path(self):
        self.assertEqual(self.out["deleteCalls"][0][0], "backups/delete")
        self.assertEqual(len(self.out["deleteCalls"][0][1]["paths"]), 1)
        self.assertIn("cannot be undone", self.out["deleteConfirmBody"])

    def test_deleting_the_ticked_rows_sends_exactly_those_rows(self):
        paths = self.out["bulkCalls"][0][1]["paths"]
        self.assertEqual(len(paths), 2)
        self.assertTrue(any("20260214-101500" in p for p in paths))
        self.assertTrue(any("Lakeside" in p for p in paths))
        self.assertIn("2", self.out["bulkConfirmTitle"])

    def test_deleting_with_nothing_ticked_deletes_nothing(self):
        self.assertEqual(self.out["emptyBulkCalls"], [])
        self.assertTrue(any("Tick" in t["msg"] for t in self.out["emptyBulkToasts"]))

    def test_deleting_a_previous_install_says_what_that_costs(self):
        self.assertIn("way back from a bad update", self.out["installDeleteBody"])
        self.assertIn("previous-v2.136.3", self.out["installDeletePath"])

    # ── the rest of the row ─────────────────────────────────────────────────
    def test_show_opens_the_folder_the_copy_sits_in(self):
        self.assertEqual(self.out["revealCalls"][0][0], "backups/reveal")
        self.assertIn("backups", self.out["revealCalls"][0][1]["path"])

    def test_an_install_backup_is_not_offered_a_restore_it_cannot_do(self):
        """Rolling an install back has to stop the server first, which this
        page cannot do - so it points at About rather than at a dead button."""
        self.assertFalse(self.out["installHasRestore"])
        self.assertTrue(self.out["installHasDelete"])
        self.assertTrue(self.out["installSaysWhere"])

    def test_a_folder_name_with_an_apostrophe_still_toggles(self):
        """The handler carries an index rather than a path for this reason.
        A key quoted straight into an onclick breaks on the first project
        named after somebody."""
        self.assertEqual(self.out["openBefore"], 3)
        self.assertEqual(self.out["openAfter"], 2)

    def test_each_filter_shows_the_rows_it_names(self):
        self.assertEqual(self.out["installFilterRows"], 1)
        self.assertEqual(self.out["missingFilterRows"], 1)
        self.assertEqual(self.out["projectFilterRows"], 3)

    def test_a_place_that_could_not_be_read_is_admitted_to(self):
        """A scan that skipped something and said nothing reports a total
        that is quietly too low, which is worse than a larger number."""
        self.assertTrue(self.out["blockedNote"])
        self.assertTrue(self.out["blockedSaysHowMany"])

    def test_the_blocked_note_is_a_count_and_never_a_path(self):
        """The first report of this arrived as a Windows profile SID pasted
        across the page. The reason belongs on screen; the path does not."""
        self.assertTrue(self.out["blockedNamesNoPath"])

    def test_nothing_is_said_when_everything_was_readable(self):
        self.assertTrue(self.out["noNoteWhenNothingBlocked"])

    def test_the_path_on_a_row_drops_the_part_every_row_shares(self):
        self.assertEqual(self.out["shortened"], "O'Brien's Site")


if __name__ == "__main__":
    unittest.main()
