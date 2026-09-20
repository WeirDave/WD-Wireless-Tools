"""Cloud Manager's owner filter: what it opens on, and what it says it is doing.

This filter has been wrong in both directions, so both are guarded here.

It used to persist whatever was last clicked in the toolbar. A stray click on
"Mine" then stuck that machine on "Mine" for good, while another machine still
opened on everything, and a fully-populated Sites tab looked like it held three
sites. It read as missing data rather than as a filter, because nothing on
screen said a filter was on. The fix at the time was to stop persisting it at
all - which cost anyone who genuinely works in their own projects a click on
every single load.

The setting restores the useful half without the trap, and the split is the
whole design:

* Settings decides what the list *opens* on. It lives in the suite settings
  file, not in localStorage, because a per-browser copy is precisely how two
  machines came to disagree about how many sites there were.
* The toolbar toggle decides what is *on screen now*, and is forgotten on
  reload. Nothing in the toolbar writes to the settings file.
* Anything narrower than All says so on screen, in words, for as long as it is
  on. CLAUDE.md makes this the condition of persisting the filter at all, so it
  is asserted here rather than left to review.
* A listing that arrives without owner information cannot answer "Mine", so the
  filter turns itself off and says why - otherwise a saved default of "Mine"
  would render an empty page indistinguishable from an empty cloud account.
"""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
CLOUD_HTML = ROOT / "web" / "cloud.html"
SETTINGS_PY = ROOT / "tools" / "settings.py"

NODE_TIMEOUT_S = 120

# Everything the sliced-out block reaches for that lives elsewhere in the page.
NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
const block = slice('const OWNER_FILTERS', '\nlet lastChkIndex')
            + slice('function emptyLedgerMessage()', '\nfunction buildPassOwner');

const notice = { hidden: true, className: '', innerHTML: '' };
globalThis.document = {
  getElementById: (id) => (id === 'ownerFilterNotice' ? notice : null),
  querySelectorAll: () => [],
  querySelector: () => null,
};
/* `emptyLedgerMessage` names the narrowest thing that emptied the list, and
   both the search box and the A-Z letter come ahead of the owner filter in
   that order. Neither is on here, which is what keeps these tests on the
   branch they are about - the same reason `activeFilter` is pinned below.
   Both live outside this slice, so the probe supplies them. */
globalThis.activeLetter = null;
globalThis._activeSearchTerm = () => '';
globalThis._activeFilterLabel = () => '';
globalThis.e = (s) => String(s);
// `emptyLedgerMessage` also names the Not Shared filter when that is what
// emptied the list, so the block reaches for this too. 'all' keeps these
// tests on the owner-filter branch, which is what they are about.
globalThis.activeFilter = 'all';
globalThis.data = null;
globalThis.currentTab = 'sites';
globalThis.updateDashboard = () => {};
/* The toolbar saves the filter now, through the same helper every other cloud
   preference uses. It lives outside this slice, so the probe supplies it and
   records what was asked for. */
globalThis.saved = [];
globalThis._persistCloudPref = (patch) => {
  globalThis.saved.push(patch);
  return Promise.resolve(globalThis.persistOk !== false);
};
globalThis.persistOk = true;
globalThis.renderRows = () => {};
let apiReply = () => Promise.resolve({ ok: true, settings: { cloud: {} } });
globalThis.WD = { api: (...a) => apiReply(...a) };
globalThis.window = globalThis;

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
"""


def run_node(program: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["node", "-e", program, str(CLOUD_JS)],
                              capture_output=True, text=True,
                              timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"node did not finish within {NODE_TIMEOUT_S}s. That is a Node "
            f"startup timeout, not a failure of the code under test."
        ) from exc


class OwnerFilterBehaviour(unittest.TestCase):
    """Driven through the real functions, not by reading the source."""

    def run_block(self, checks: str):
        program = NODE_PRELUDE + "eval(block + " + _js_string(checks) + ");"
        result = run_node(program)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_the_list_opens_on_the_saved_default(self):
        self.run_block("""
          apiReply = () => Promise.resolve(
            { ok: true, settings: { cloud: { default_owner_filter: 'mine' } } });
          loadDefaultOwnerFilter().then(() => {
            check('saved default was not applied: ' + ownerFilter(),
                  ownerFilter() === 'mine');
            check('defaultOwnerFilter() disagrees with what was applied',
                  defaultOwnerFilter() === 'mine');
            done();
          });
        """)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_the_toolbar_choice_is_remembered(self):
        """This asserted the opposite until v2.119.0, and it was right to.

        The toolbar toggle was deliberately in-memory: a per-browser copy had
        once got stuck on "Mine" and looked like missing data, and the test
        warned that "if this ever inverts, a stray click becomes permanent
        again."

        It is inverted now because the other side of that trade was costing him
        every single update - "it does not save my choice of the owner being on
        Mine, which is really frustrating" - and because the thing that made a
        stuck filter dangerous has been fixed separately. It was never the
        saving; it was that a saved filter could be *silently* in force. Since
        v2.51.0 a narrowed view announces itself above the list, so a stray
        click is a sentence at the top of the page rather than three sites
        going missing.

        That announcement is therefore the other half of this contract, and it
        is asserted here rather than left to the neighbouring test.
        """
        self.run_block("""
          apiReply = () => Promise.resolve(
            { ok: true, settings: { cloud: { default_owner_filter: 'mine' } } });
          loadDefaultOwnerFilter().then(() => {
            setOwnerFilterUI('others');
            check('the toolbar did not change the screen',
                  ownerFilter() === 'others');
            check('the choice was not written: ' + JSON.stringify(saved),
                  saved.length === 1 && saved[0].default_owner_filter === 'others');
            check('the toolbar did not become the new default',
                  defaultOwnerFilter() === 'others');
            check('a narrowed view that is now saved does not say so',
                  notice.hidden === false
                  && /saved default/i.test(String(notice.innerHTML)));
            done();
          });
        """)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_a_filter_that_could_not_be_saved_says_it_is_only_for_this_visit(self):
        """Losing the preference is survivable; claiming to have saved it is
        not. The filter is applied either way - only the remembering failed -
        so the notice has to stop calling it the saved default."""
        self.run_block("""
          apiReply = () => Promise.resolve(
            { ok: true, settings: { cloud: { default_owner_filter: 'all' } } });
          persistOk = false;
          loadDefaultOwnerFilter().then(() => {
            setOwnerFilterUI('mine');
            return new Promise(r => setTimeout(r, 0));
          }).then(() => {
            check('the filter was not applied: ' + ownerFilter(),
                  ownerFilter() === 'mine');
            check('a filter that was not saved still claims to be the default',
                  !/saved default/i.test(String(notice.innerHTML)));
            done();
          });
        """)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_an_unreadable_or_nonsense_setting_shows_everything(self):
        """All is the safe way to be wrong: it hides nothing."""
        self.run_block("""
          apiReply = () => Promise.resolve(
            { ok: true, settings: { cloud: { default_owner_filter: 'everyone' } } });
          loadDefaultOwnerFilter().then(() => {
            check('a value that is not one of the three was trusted: ' + ownerFilter(),
                  ownerFilter() === 'all');
            apiReply = () => Promise.reject(new Error('no server'));
            return loadDefaultOwnerFilter();
          }).then(() => {
            check('a failed settings read did not fall back to all',
                  ownerFilter() === 'all');
            done();
          });
        """)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_a_listing_with_no_owners_turns_the_filter_off_and_says_why(self):
        """Otherwise a saved "Mine" looks exactly like an empty cloud account."""
        self.run_block("""
          apiReply = () => Promise.resolve(
            { ok: true, settings: { cloud: { default_owner_filter: 'mine' } } });
          loadDefaultOwnerFilter().then(() => {
            globalThis.data = { currentUser: '', matched: [] };
            reconcileOwnerFilterWithData();
            check('the filter stayed on with nothing to filter by: ' + ownerFilter(),
                  ownerFilter() === 'all');
            check('it went quiet instead of explaining itself',
                  notice.hidden === false && /Ekahau Cloud did not say/.test(notice.innerHTML));

            globalThis.data = { currentUser: 'me@example.com', matched: [] };
            setOwnerFilterUI('mine');
            reconcileOwnerFilterWithData();
            check('a listing that does name an owner had the filter taken away',
                  ownerFilter() === 'mine');
            done();
          });
        """)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_a_narrowed_view_is_announced_and_names_how_long_it_lasts(self):
        """CLAUDE.md's condition for persisting this filter at all.

        The old bug was not that rows were hidden - it was that nothing said so.
        The notice also has to distinguish the two cases, because "it will be
        like this tomorrow" and "it resets when you reload" call for different
        actions from the reader.
        """
        self.run_block("""
          apiReply = () => Promise.resolve(
            { ok: true, settings: { cloud: { default_owner_filter: 'mine' } } });
          loadDefaultOwnerFilter().then(() => {
            syncOwnerToggle();
            /* Mine is the shipped default now, so announcing it would fire
               on every load of the ordinary case - which is how a notice
               stops being read at all. */
            check('the ordinary default was announced anyway',
                  notice.hidden === true);

            setOwnerFilterUI('others');
            check('a genuinely unusual narrowing said nothing',
                  notice.hidden === false && /Owner filter: Others/.test(notice.innerHTML));
            check('a saved override was not described as saved',
                  /saved default/i.test(notice.innerHTML));
            check('it did not offer a way back to everything',
                  /setOwnerFilterUI/.test(notice.innerHTML));

            /* All is the state worth flagging now. Nothing is hidden, but
               the list carries other people's projects and the actions that
               change a project are unavailable on those - which is better
               said once above the list than discovered per row. */
            setOwnerFilterUI('all');
            check('showing every owner said nothing about it',
                  notice.hidden === false);
            check('it did not say why some actions will be unavailable',
                  /only lets the owner change a project/.test(notice.innerHTML));
            done();
          });
        """)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_every_notice_says_how_long_the_choice_lasts(self):
        """The toolbar toggle is in-memory and a reload resets it - which is
        also what an upgrade looks like.

        `All` was the one state that never said so: its branch returned early
        with the ownership warning and nothing about impermanence. Switching
        to All, restarting and landing back on Mine was therefore
        indistinguishable from a setting that would not save, and cost an
        afternoon of looking for a persistence bug that does not exist.

        Asserted over every state that shows a notice rather than over the
        branch that was wrong, because the next branch added here will have
        the same obligation.
        """
        self.run_block("""
          apiReply = () => Promise.resolve(
            { ok: true, settings: { cloud: { default_owner_filter: 'mine' } } });
          loadDefaultOwnerFilter().then(() => {
            ['all', 'others', 'mine'].forEach((f) => {
              setOwnerFilterUI(f);
              if (notice.hidden) return;          // Mine at its default says nothing
              check('the ' + f + ' notice never says how long it lasts',
                    /this visit|on again next time/i.test(notice.innerHTML));
            });
            done();
          });
        """)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_a_filter_the_page_forced_does_not_promise_to_go_back(self):
        """When the listing comes back with no owner, the page turns the
        filter off itself. It will do the same on the next load, so telling
        him it reverts to his default would be false - and that case already
        carries its own explanation."""
        self.run_block("""
          apiReply = () => Promise.resolve(
            { ok: true, settings: { cloud: { default_owner_filter: 'mine' } } });
          loadDefaultOwnerFilter().then(() => {
            globalThis.data = { currentUser: '', matched: [] };
            reconcileOwnerFilterWithData();
            syncOwnerToggle();
            check('the forced state did not explain itself',
                  notice.hidden === false);
            check('it lost the reason the filter was taken away',
                  /did not say which account/.test(notice.innerHTML));
            /* Neither half of the how-long sentence belongs here. "Just for
               this visit" promises a return that will not happen, and "this
               is your saved default" is simply false - All is not his
               default, the page chose it. */
            check('it promised to go back to a default it cannot go back to',
                  /this visit/i.test(notice.innerHTML) === false);
            check('it called All his saved default, which it is not',
                  /saved default/i.test(notice.innerHTML) === false);
            done();
          });
        """)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_an_empty_list_names_the_filter_that_emptied_it(self):
        self.run_block("""
          apiReply = () => Promise.resolve(
            { ok: true, settings: { cloud: { default_owner_filter: 'mine' } } });
          loadDefaultOwnerFilter().then(() => {
            const msg = emptyLedgerMessage();
            check('an empty list did not name the owner filter: ' + msg,
                  /Mine/.test(msg) && /saved default/.test(msg));
            check('an empty list did not offer a way out',
                  /setOwnerFilterUI/.test(msg));
            setOwnerFilterUI('all');
            check('the plain message changed when no owner filter was on',
                  emptyLedgerMessage().indexOf('owner filter') === -1);
            done();
          });
        """)


    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_the_page_opens_on_his_own_work_before_the_server_answers(self):
        """Run, not read.

        The page holds its own copy of the default for the moment before the
        settings call returns. If that copy said `all` while the server
        shipped `mine`, every load would flash the whole account - and on a
        slow read, that is a list he might act on.
        """
        self.run_block("""
          check('the page starts on something other than his own work',
                ownerFilter() === 'mine' && defaultOwnerFilter() === 'mine');
          done();
        """)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_the_notice_stays_off_the_duplicates_tab(self):
        """Duplicates is a different list, which this filter does not touch."""
        self.run_block("""
          apiReply = () => Promise.resolve(
            { ok: true, settings: { cloud: { default_owner_filter: 'mine' } } });
          loadDefaultOwnerFilter().then(() => {
            //: Others, because Mine is the default and says nothing.
            setOwnerFilterUI('others');
            globalThis.currentTab = 'duplicates';
            syncOwnerToggle();
            check('a banner about hidden sites appeared over the duplicate list',
                  notice.hidden === true);
            globalThis.currentTab = 'sites';
            syncOwnerToggle();
            check('it did not come back on the list it does describe',
                  notice.hidden === false);
            done();
          });
        """)


class OwnerFilterWiring(unittest.TestCase):
    def setUp(self):
        self.js = CLOUD_JS.read_text(encoding="utf-8")
        self.html = CLOUD_HTML.read_text(encoding="utf-8")

    def test_the_shipped_default_is_mine(self):
        """"the default for this whole entire thing should always be the
        user's files, not everyone else's files."

        This asserted `all`, on the reasoning that Mine was one person's
        preference and the built-in should hide nothing. Two things overturned
        it. He has been re-setting it on every launch for months - "I've hated
        it - that's why I always hit it on Mine" - and All turned out not to
        be neutral: it is the state in which the list carries colleagues'
        projects, so it is the state in which an offered action can be refused
        by Ekahau. Auto-assign proposed three and got three 403s.
        """
        from tools import settings as st
        self.assertEqual("mine",
                         st.DEFAULTS["cloud"]["default_owner_filter"])


    def test_the_default_is_not_kept_per_browser(self):
        """localStorage is how two machines came to disagree in the first place."""
        for key in ("wd-owner-filter", "wd-owner", "owner-filter"):
            with self.subTest(key=key):
                self.assertNotIn(key, self.js)
        self.assertIn("settings/get", self.js)
        self.assertIn("default_owner_filter", self.js)

    def test_the_toolbar_toggle_never_writes_the_setting(self):
        start = self.js.index("function setOwnerFilterUI(v)")
        body = self.js[start:self.js.index("\n}", start)]
        self.assertNotIn("settings/update", body,
                         "clicking Owner in the toolbar must not change what "
                         "the page opens on next time")

    def test_the_notice_cannot_be_skipped_when_the_toggle_moves(self):
        start = self.js.index("function syncOwnerToggle()")
        body = self.js[start:self.js.index("\n}", start)]
        self.assertIn("renderOwnerFilterNotice()", body,
                      "every path that changes the filter goes through here, "
                      "so this is what keeps the on-screen notice honest")

    def test_the_page_has_somewhere_to_put_the_notice(self):
        self.assertIn('id="ownerFilterNotice"', self.html)
        self.assertIn('role="status"', self.html)

    def test_settings_offers_all_three_and_explains_the_split(self):
        for value in ("all", "mine", "others"):
            with self.subTest(value=value):
                self.assertIn(f'name="setowner" value="{value}"', self.html)
        self.assertIn("until you reload", self.html,
                      "the modal has to say that the toolbar buttons are "
                      "temporary and this one is not")


def _js_string(text: str) -> str:
    """A JS string literal holding *text*, safe for -e on any platform."""
    import json
    return json.dumps(text)


if __name__ == "__main__":
    unittest.main()
