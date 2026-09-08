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
};
globalThis.e = (s) => String(s);
globalThis.data = null;
globalThis.currentTab = 'sites';
globalThis.updateDashboard = () => {};
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
    def test_the_toolbar_is_a_visit_long_override_not_a_new_default(self):
        """The historic bug, from the other side.

        Clicking Others must change the screen and nothing else; reloading has
        to come back to whatever Settings says. If this ever inverts, a stray
        click becomes permanent again.
        """
        self.run_block("""
          apiReply = () => Promise.resolve(
            { ok: true, settings: { cloud: { default_owner_filter: 'mine' } } });
          loadDefaultOwnerFilter().then(() => {
            setOwnerFilterUI('others');
            check('the toolbar did not change the screen',
                  ownerFilter() === 'others');
            check('the toolbar rewrote the saved default',
                  defaultOwnerFilter() === 'mine');
            return loadDefaultOwnerFilter();      // a reload
          }).then(() => {
            check('the override survived a reload: ' + ownerFilter(),
                  ownerFilter() === 'mine');
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
            check('a saved narrowing said nothing',
                  notice.hidden === false && /Owner filter: Mine/.test(notice.innerHTML));
            check('it did not say the narrowing is the saved default',
                  /saved default/.test(notice.innerHTML));
            check('it did not offer a way back to everything',
                  /setOwnerFilterUI/.test(notice.innerHTML));

            setOwnerFilterUI('others');
            check('a hand-made override was described as permanent',
                  /this visit/i.test(notice.innerHTML));

            setOwnerFilterUI('all');
            check('the notice stayed up when nothing was being hidden',
                  notice.hidden === true);
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
    def test_the_notice_stays_off_the_duplicates_tab(self):
        """Duplicates is a different list, which this filter does not touch."""
        self.run_block("""
          apiReply = () => Promise.resolve(
            { ok: true, settings: { cloud: { default_owner_filter: 'mine' } } });
          loadDefaultOwnerFilter().then(() => {
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

    def test_the_shipped_default_is_all(self):
        """Everyone else's app must open exactly as it did before.

        "Mine" is one person's preference; making it the built-in would hide
        shared work from every other installation on first launch.
        """
        text = SETTINGS_PY.read_text(encoding="utf-8")
        self.assertIn('"default_owner_filter": "all",', text)

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
