"""Marking a project External by hand, and the store behind it.

**Ownership metadata answers a different question from the one being asked.**
It says whose account a project sits in. "Is this external" is about who is
responsible for it, and the two part company often enough that he needs to be
able to say so himself - a project with no owner recorded, or one in his own
account that a contractor is actually looking after.

The case that most needed it is the one the backlog item found while it was
being checked: when the account comes back with no ``currentUser`` there is
nothing to compare an owner against, so *every* project read as internal and
the External count was a confident zero rather than an unknown.

The Python half runs the real store. The JavaScript half slices the real
``_isExternal`` and the real gutter cell out of cloud.js and runs them, because
an override that is saved and then not consulted is the whole failure this
guards against - and asserting that cloud.js *contains* ``externalOverrides``
would pass with it consulted nowhere.
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
CLOUD_HTML = ROOT / "web" / "cloud.html"

NODE_TIMEOUT_S = 120


# ─────────────────────────── the store ────────────────────────────────────

class TheStoreTests(unittest.TestCase):
    """Runs the real loader and saver against a scratch user directory.

    ``WD_USER_DIR`` is read once at import, so it is set before cloud_manager
    is imported anywhere in this process - see CLAUDE.md, "WD_USER_DIR is
    enforced, not just available". His real configuration is never reachable
    from here.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wd-extov-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)

    def setUp(self):
        from tools import cloud_manager as cm
        self.cm = cm
        # Point the module's own constant at a scratch file per test, rather
        # than at whatever the import-time user directory resolved to.
        self._dir = Path(tempfile.mkdtemp(dir=self.tmp))
        self._file = self._dir / "external_overrides.json"
        self._old_file = cm.EXTERNAL_OVERRIDE_FILE
        self._old_dir = cm.CONFIG_DIR
        cm.EXTERNAL_OVERRIDE_FILE = self._file
        cm.CONFIG_DIR = self._dir
        self.addCleanup(self._restore)

    def _restore(self):
        self.cm.EXTERNAL_OVERRIDE_FILE = self._old_file
        self.cm.CONFIG_DIR = self._old_dir

    def _api(self):
        """A CloudManager with everything but the store stubbed out.

        The three methods under test touch no network and no project, which is
        the point of them - so the object is built without __init__ rather than
        by standing up a session.
        """
        return self.cm.CloudManager.__new__(self.cm.CloudManager)

    def test_a_mark_is_saved_and_read_back(self):
        api = self._api()
        r = api.set_external_override(
            [{"cloudId": "abc", "localPath": "", "label": "Contractor survey"}],
            "external")
        self.assertTrue(r.get("ok"), r)
        self.assertEqual({"c:abc": "external"}, self.cm.external_overrides_map())

    def test_it_survives_a_restart_because_it_is_on_disk(self):
        self._api().set_external_override([{"cloudId": "abc"}], "external")
        self.assertTrue(self._file.exists())
        # Read it back through a fresh load, not from anything held in memory.
        self.assertEqual("external", self.cm.external_overrides_map()["c:abc"])

    def test_a_local_only_file_is_keyed_on_its_path(self):
        """It has no cloud id. Keying on nothing would drop the mark silently."""
        self._api().set_external_override(
            [{"cloudId": "", "localPath": r"C:\Projects\Site\Plan.esx"}], "mine")
        self.assertEqual({"l:c:/projects/site/plan.esx": "mine"},
                         self.cm.external_overrides_map())

    def test_the_path_key_ignores_slash_direction_and_case(self):
        """The same file named two ways is one project, not two marks."""
        api = self._api()
        api.set_external_override([{"localPath": r"C:\A\B.esx"}], "external")
        api.set_external_override([{"localPath": "c:/a/b.esx"}], "mine")
        self.assertEqual(1, len(self.cm.load_external_overrides()))
        self.assertEqual("mine", self.cm.external_overrides_map()["l:c:/a/b.esx"])

    def test_marking_the_same_project_twice_replaces_rather_than_stacks(self):
        api = self._api()
        api.set_external_override([{"cloudId": "abc"}], "external")
        api.set_external_override([{"cloudId": "abc"}], "mine")
        self.assertEqual(1, len(self.cm.load_external_overrides()))
        self.assertEqual("mine", self.cm.external_overrides_map()["c:abc"])

    def test_a_mark_can_be_taken_off(self):
        api = self._api()
        api.set_external_override([{"cloudId": "abc"}, {"cloudId": "def"}], "external")
        r = api.clear_external_override([{"cloudId": "abc"}])
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(1, r["removed"])
        self.assertEqual({"c:def": "external"}, self.cm.external_overrides_map())

    def test_many_projects_are_marked_in_one_call(self):
        api = self._api()
        items = [{"cloudId": "id-%d" % i, "label": "P%d" % i} for i in range(25)]
        r = api.set_external_override(items, "external")
        self.assertEqual(25, r["marked"])
        self.assertEqual(25, len(self.cm.external_overrides_map()))

    def test_an_unknown_value_is_refused(self):
        r = self._api().set_external_override([{"cloudId": "abc"}], "maybe")
        self.assertIn("error", r)
        self.assertEqual([], self.cm.load_external_overrides())

    def test_an_item_with_no_identity_at_all_is_refused(self):
        r = self._api().set_external_override([{"cloudId": "", "localPath": ""}], "external")
        self.assertIn("error", r)

    def test_a_corrupt_file_reads_as_no_marks_rather_than_raising(self):
        """A file nobody can parse must not take the whole listing down."""
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text("{ not json", encoding="utf-8")
        self.assertEqual([], self.cm.load_external_overrides())
        self.assertEqual({}, self.cm.external_overrides_map())

    def test_entries_with_a_nonsense_value_are_dropped_on_read(self):
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps({"entries": [
            {"key": "c:ok", "value": "external"},
            {"key": "c:bad", "value": "sideways"},
            {"value": "external"},
        ]}), encoding="utf-8")
        self.assertEqual({"c:ok": "external"}, self.cm.external_overrides_map())

    def test_nothing_about_a_mark_reaches_the_project(self):
        """It is an annotation on this installation's view.

        The three methods must not carry an api call between them - marking a
        project External is not something Ekahau should ever learn about, and
        it must work on a project he does not own, which is the case it exists
        for.
        """
        import inspect
        for name in ("set_external_override", "clear_external_override",
                     "list_external_overrides"):
            src = inspect.getsource(getattr(self.cm.CloudManager, name))
            with self.subTest(method=name):
                self.assertNotIn("self.api", src)
                self.assertNotIn("self._ensure", src)


class TheStoreIsRegisteredTests(unittest.TestCase):
    """CLOUD_ACTIONS is a dictionary literal nobody executes.

    A method that exists and is not routed is unreachable from the page, and a
    lambda reading the wrong key is invisible to a test of the function it
    calls - which is why the route table is exercised rather than read.
    """

    def test_the_three_actions_are_routed_to_the_right_methods(self):
        import server
        for action in ("set_external_override", "clear_external_override",
                       "list_external_overrides"):
            with self.subTest(action=action):
                self.assertIn(action, server.CLOUD_ACTIONS)

    def test_the_route_passes_the_arguments_the_page_sends(self):
        import server

        seen = {}

        class FakeCm:
            def set_external_override(self, items, value):
                seen["set"] = (items, value)
                return {"ok": True}

            def clear_external_override(self, items):
                seen["clear"] = items
                return {"ok": True}

        real = server.cm
        server.cm = FakeCm()
        try:
            server.CLOUD_ACTIONS["set_external_override"](
                {"items": [{"cloudId": "abc"}], "value": "external"})
            server.CLOUD_ACTIONS["clear_external_override"](
                {"items": [{"cloudId": "abc"}]})
        finally:
            server.cm = real
        self.assertEqual(([{"cloudId": "abc"}], "external"), seen["set"])
        self.assertEqual([{"cloudId": "abc"}], seen["clear"])


# ───────────────────────── the page consults it ───────────────────────────

NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
globalThis.window = globalThis;

const e = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const a = e;
const j = s => String(s == null ? '' : s).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
const pj = j;
globalThis.e = e; globalThis.a = a; globalThis.j = j; globalThis.pj = pj;
globalThis.currentTab = 'projects';
function ic() { return ''; }

// The real key builder, the real override lookup and the real _isExternal.
eval(slice('function _ovKey(cloudObj, localObj)', '\n/* Projects you own'));
// The real badge, which is where a mark becomes visible and undoable.
eval(slice('function externalBadgeHtml(r)', '\n/* Where this project lives'));

globalThis.data = { currentUser: 'me@example.com', externalOverrides: {} };
function setOverrides(map) { data.externalOverrides = map || {}; }
function setUser(u) { data.currentUser = u; }
globalThis.setOverrides = setOverrides;
globalThis.setUser = setUser;

const MINE = { id: 'c-mine', name: 'My Project', owner: 'me@example.com' };
const THEIRS = { id: 'c-theirs', name: 'Their Project', owner: 'them@example.com' };
const NOOWNER = { id: 'c-noowner', name: 'Unowned Project', owner: '' };
const LOCAL = { path: 'C:\\Projects\\Site\\Plan.esx', name: 'Plan' };
globalThis.MINE = MINE; globalThis.THEIRS = THEIRS;
globalThis.NOOWNER = NOOWNER; globalThis.LOCAL = LOCAL;

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function eq(what, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) failures.push(what + '\n     got:  ' + g + '\n     want: ' + w);
}
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
"""


def run_node(checks: str) -> subprocess.CompletedProcess:
    program = NODE_PRELUDE + "eval(" + json.dumps(checks) + ");"
    try:
        return subprocess.run(["node", "-e", program, str(CLOUD_JS)],
                              capture_output=True, text=True,
                              encoding="utf-8", timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(f"node did not finish within {NODE_TIMEOUT_S}s") from exc


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ThePageConsultsTheOverrideTests(unittest.TestCase):
    def run_checks(self, checks: str):
        proc = run_node(checks)
        if proc.returncode != 0:
            self.fail((proc.stderr or proc.stdout or "node failed").strip())

    def test_without_a_mark_nothing_changes(self):
        self.run_checks(r"""
          setOverrides({});
          eq('mine is not external', _isExternal(MINE, null), false);
          eq('theirs is external', _isExternal(THEIRS, null), true);
          done();
        """)

    def test_a_mark_makes_his_own_project_external(self):
        self.run_checks(r"""
          setOverrides({ 'c:c-mine': 'external' });
          eq('marked external wins', _isExternal(MINE, null), true);
          done();
        """)

    def test_a_mark_makes_somebody_elses_project_his(self):
        self.run_checks(r"""
          setOverrides({ 'c:c-theirs': 'mine' });
          eq('marked mine wins', _isExternal(THEIRS, null), false);
          done();
        """)

    def test_the_mark_answers_when_the_account_has_no_current_user(self):
        """The case the backlog item singled out.

        With no signed-in user there is nothing to compare an owner against, so
        every project used to read as internal - a confident zero rather than
        an unknown. A mark is the one thing that can still say otherwise.
        """
        self.run_checks(r"""
          setUser('');
          setOverrides({});
          eq('nothing looks external, as before', _isExternal(THEIRS, null), false);
          setOverrides({ 'c:c-theirs': 'external' });
          eq('but a mark still answers', _isExternal(THEIRS, null), true);
          done();
        """)

    def test_a_project_with_no_owner_recorded_can_be_marked(self):
        self.run_checks(r"""
          setOverrides({});
          eq('unknown reads as internal', _isExternal(NOOWNER, null), false);
          setOverrides({ 'c:c-noowner': 'external' });
          eq('and the mark is honoured', _isExternal(NOOWNER, null), true);
          done();
        """)

    def test_a_local_only_file_is_keyed_the_same_way_the_server_keys_it(self):
        """Both ends have to agree, or a mark applies to nothing and says
        nothing about having failed."""
        self.run_checks(r"""
          eq('backslashes and case are normalised',
             _ovKey(null, LOCAL), 'l:c:/projects/site/plan.esx');
          eq('a cloud id wins over a path', _ovKey(MINE, LOCAL), 'c:c-mine');
          setOverrides({ 'l:c:/projects/site/plan.esx': 'external' });
          eq('and the lookup finds it', _isExternal(null, LOCAL), true);
          done();
        """)

    def test_a_listing_with_no_overrides_at_all_is_not_an_error(self):
        self.run_checks(r"""
          data.externalOverrides = undefined;
          eq('falls back to the owner', _isExternal(THEIRS, null), true);
          eq('and to nothing for his own', _isExternal(MINE, null), false);
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TheMarkIsVisibleAndUndoableTests(unittest.TestCase):
    """A persistent decision that leaves no trace on the row is the worst of
    both: the counts move, the stripe moves, and nothing says why."""

    def run_checks(self, checks: str):
        proc = run_node(checks)
        if proc.returncode != 0:
            self.fail((proc.stderr or proc.stdout or "node failed").strip())

    def test_an_unmarked_row_carries_no_badge(self):
        self.run_checks(r"""
          setOverrides({});
          eq('nothing is drawn', externalBadgeHtml({ cloud: THEIRS }), '');
          done();
        """)

    def test_a_marked_row_says_so_in_words(self):
        self.run_checks(r"""
          setOverrides({ 'c:c-mine': 'external' });
          const h = externalBadgeHtml({ cloud: MINE });
          check('it says what it is: ' + h, h.indexOf('Marked External') !== -1);
          setOverrides({ 'c:c-theirs': 'mine' });
          const h2 = externalBadgeHtml({ cloud: THEIRS });
          check('and the other way: ' + h2, h2.indexOf('Marked mine') !== -1);
          done();
        """)

    def test_clicking_the_badge_clears_that_projects_mark(self):
        """The handler is pulled back out of the rendered markup and run.

        A badge whose onclick names a function that does not exist, or that is
        handed the wrong arguments, renders perfectly and does nothing - which
        is how an inert button shipped green before.
        """
        self.run_checks(r"""
          setOverrides({ 'c:c-mine': 'external' });
          const h = externalBadgeHtml({ cloud: MINE, local: LOCAL });
          const m = h.match(/onclick="([^"]*)"/);
          check('the badge has a handler', !!m);
          const call = m[1].replace(/&quot;/g, '"').replace(/&amp;/g, '&');

          const got = [];
          globalThis.event = { stopPropagation() {} };
          globalThis.clearExternalMark = function (cloudId, localPath) {
            got.push([cloudId, localPath]);
          };
          eval(call);
          eq('called once with this project', got,
             [['c-mine', 'C:\\Projects\\Site\\Plan.esx']]);
          done();
        """)

    def test_a_project_named_with_an_apostrophe_still_clears(self):
        """A path with a backslash and a name with a quote are what turn a
        present control into a dead one."""
        self.run_checks(r"""
          const odd = { id: "it's-a-b\\c", name: "O'Brien" };
          setOverrides({ ["c:" + odd.id]: 'external' });
          const h = externalBadgeHtml({ cloud: odd });
          const m = h.match(/onclick="([^"]*)"/);
          check('there is a handler', !!m);
          const got = [];
          globalThis.event = { stopPropagation() {} };
          globalThis.clearExternalMark = function (id) { got.push(id); };
          eval(m[1].replace(/&quot;/g, '"').replace(/&amp;/g, '&'));
          eq('the id survived escaping', got, ["it's-a-b\\c"]);
          done();
        """)


def buttons_on(page) -> dict:
    """Every ``<button>`` on a page, as ``{id, label, onclick, title}``.

    Parsed rather than matched as text. A substring check passes on a control
    that is commented out, that appears twice, or whose label and handler
    belong to two different buttons - and the last of those is exactly what an
    inert control looks like from outside.
    """
    out = {}
    text = page.read_text(encoding="utf-8")
    for m in re.finditer(r"<button\b([^>]*)>(.*?)</button>", text, re.S):
        attrs = dict(re.findall(r'(\w[\w-]*)="([^"]*)"', m.group(1)))
        label = re.sub(r"<[^>]*>", "", m.group(2))
        for ent, ch in (("&hellip;", "…"), ("&amp;", "&"),
                        ("&rsquo;", "’"), ("&#8594;", "→")):
            label = label.replace(ent, ch)
        key = attrs.get("id") or re.sub(r"\s+", " ", label).strip()
        out[key] = {"id": attrs.get("id", ""),
                    "label": re.sub(r"\s+", " ", label).strip(),
                    "onclick": attrs.get("onclick", ""),
                    "title": attrs.get("title", "")}
    return out


class TheControlExistsWhereTheTextSaysItIsTests(unittest.TestCase):
    """The controls that set a mark, taken off the parsed page and run.

    Asserting that the page *contains* the handler's name would pass on a
    button wired to nothing, which is how an inert control shipped before. So
    the ``onclick`` is pulled out of the parsed markup and executed, and what
    arrives is what is checked.
    """

    def setUp(self):
        self.buttons = buttons_on(CLOUD_HTML)

    def test_the_menu_offers_both_directions(self):
        ext = self.buttons.get("bulkMarkExternalBtn")
        mine = self.buttons.get("bulkMarkMineBtn")
        self.assertIsNotNone(ext, "no Mark as External control on the page")
        self.assertIsNotNone(mine, "no Mark as mine control on the page")
        self.assertEqual("Mark as External…", ext["label"])
        self.assertEqual("Mark as mine…", mine["label"])

    def test_the_menu_says_nothing_is_written_to_the_cloud(self):
        """It is the question anyone has at a control that sounds as though it
        changes ownership, and the answer is no."""
        for key in ("bulkMarkExternalBtn", "bulkMarkMineBtn"):
            with self.subTest(control=key):
                self.assertIn("Nothing is written to Ekahau Cloud",
                              self.buttons[key]["title"])

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_clicking_each_one_asks_for_the_mark_it_names(self):
        """The two differ by one argument, and that argument is the control.

        The same handler wired with the other value renders perfectly and does
        the opposite of what its label says, which nothing about the markup
        would reveal.
        """
        clicks = json.dumps([self.buttons["bulkMarkExternalBtn"]["onclick"],
                             self.buttons["bulkMarkMineBtn"]["onclick"]])
        proc = run_node("""
          const got = [];
          globalThis.bulkMarkExternal = function (v) { got.push(v); };
          %s.forEach(function (src) { eval(src); });
          eq('one call each, in the order the menu lists them', got,
             ['external', 'mine']);
          done();
        """ % clicks)
        if proc.returncode != 0:
            self.fail((proc.stderr or proc.stdout or "node failed").strip())

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_both_ends_of_the_call_are_real(self):
        """A handler that exists, and an API map entry naming the action the
        server registered. Either one missing leaves the control inert."""
        proc = run_node(r"""
          // `const` declared inside eval() stays inside it, so the map is
          // handed out explicitly rather than assumed to have leaked.
          eval(slice('const API_MAP = {', '\nasync function pyApi(')
               + ';globalThis.API_MAP = API_MAP;');
          eval(slice('async function bulkMarkExternal(',
                     '\nasync function clearExternalMark('));
          check('the bulk handler exists', typeof bulkMarkExternal === 'function');
          eq('set is routed', API_MAP.set_external_override[0], 'set_external_override');
          eq('clear is routed', API_MAP.clear_external_override[0], 'clear_external_override');
          eq('set sends items and a value',
             API_MAP.set_external_override[1], ['items', 'value']);
          eq('clear sends items', API_MAP.clear_external_override[1], ['items']);
          done();
        """)
        if proc.returncode != 0:
            self.fail((proc.stderr or proc.stdout or "node failed").strip())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
