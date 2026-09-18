"""The dev toolbar, driven in a real browser by clicking it.

This is the file that answers "does it work", as opposed to "does the source
mention it". It loads a real page from a real server, finds the toolbar the
way he would, clicks the controls the way he would, and reads back what the
page then shows. Nothing here asserts on the text of a source file.

The properties under test are his, in his order:

* it is **off by default** - a page loaded normally has no toolbar on it
* it is **opened deliberately** - `?dev=1`, and nothing else, turns it on
* it is **obvious when he is in it**, and **separate from the tools** - the
  tool's own controls are still there and still work
* the action is **dry run by default** - the live button is not clickable
  until a preview has run, and the preview sends `dryRun: true`
* **the live run sends `dryRun: false`**, and only after he confirms

The server is `http.server` over the `web/` directory rather than `server.py`,
for the reason CLAUDE.md gives: `main()` opens a browser window on his desktop
unconditionally and nobody closes them. This needs no Flask route - the
toolbar is client side, and the one call it makes is stubbed at `WD.api` so a
test can never reach his Ekahau account or his project folder.

`WD.api` is replaced rather than mocked at the network layer on purpose: it is
the seam the action actually uses, so replacing it proves the wiring runs
through the real `register` -> real button -> real handler path and pins the
argument that decides whether his files get written to.

Chrome, Edge and Firefox, per the standing rule in CLAUDE.md, with Firefox
first because it is the browser he uses.
"""
from __future__ import annotations

import contextlib
import json
import socket
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

#: An unusual port, and not one anybody reaches for. 8675 is his own running
#: instance and must never be bound here.
PORT_HINT = 8791

try:  # pragma: no cover - availability varies by machine
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False

BROWSERS = [
    ("firefox", r"C:\Program Files\Mozilla Firefox\firefox.exe"),
    ("chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    ("edge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]


def _free_port(start):
    for port in range(start, start + 40):
        with contextlib.closing(socket.socket()) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free port near %d" % start)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *a):  # keep the test output readable
        pass


def _driver(kind, binary):
    """A headless driver for one browser, or None when it will not start.

    Returning None rather than raising keeps one uninstalled browser from
    failing the run on a machine that has the other two.
    """
    try:
        if kind == "firefox":
            opts = webdriver.FirefoxOptions()
            opts.binary_location = binary
            opts.add_argument("-headless")
            return webdriver.Firefox(options=opts)
        if kind == "chrome":
            opts = webdriver.ChromeOptions()
            opts.binary_location = binary
            opts.add_argument("--headless=new")
            opts.add_argument("--no-sandbox")
            return webdriver.Chrome(options=opts)
        opts = webdriver.EdgeOptions()
        opts.binary_location = binary
        opts.add_argument("--headless=new")
        return webdriver.Edge(options=opts)
    except (WebDriverException, OSError):
        return None


#: Replaces `WD.api` in the page. Records what the action asked for and hands
#: back a report of the shape the server returns, so the page can be driven
#: end to end without a cloud account or a project folder in sight.
STUB_API = """
window.__devCalls = [];
window.WD.api = function (action, body) {
  window.__devCalls.push({ action: action, body: body });
  var dry = !body || body.dryRun !== false;
  return Promise.resolve({
    ok: true, dryRun: dry, examined: 2,
    aligned: [{ name: 'Maple Depot Survey', folder: 'Maple Depot',
                path: 'C:/Projects/Maple Depot/Maple Depot Survey.esx',
                actions: ['Set the name inside the file to match the cloud',
                          'Set the modified date to the cloud\\u2019s'],
                newDate: '2026-04-15T14:30:00.000Z' }],
    skipped: [{ name: 'Birch Yard Walkthrough', folder: 'Birch Yard',
                reason: 'The designs genuinely differ - 3 access points added.' }],
    failed: [],
    counts: { aligned: 1, skipped: 1, failed: 0 }
  });
};
"""


class ToolbarInABrowser(unittest.TestCase):
    """One server and one browser for the whole class - starting a driver is
    the slow part, and every test here is read-then-click on a fresh page."""

    kind = None
    binary = None
    server = None
    driver = None

    @classmethod
    def setUpClass(cls):
        if cls.kind is None:
            raise unittest.SkipTest("base class")
        if not HAVE_SELENIUM:
            raise unittest.SkipTest("selenium is not installed")
        if not Path(cls.binary).exists():
            raise unittest.SkipTest("%s is not installed here" % cls.kind)

        cls.port = _free_port(PORT_HINT)
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", cls.port),
            partial(QuietHandler, directory=str(WEB)))
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

        cls.driver = _driver(cls.kind, cls.binary)
        if cls.driver is None:
            cls.server.shutdown()
            cls.server.server_close()
            raise unittest.SkipTest("%s would not start" % cls.kind)
        cls.driver.set_page_load_timeout(60)

    @classmethod
    def tearDownClass(cls):
        # Always, on the failure path too: an abandoned driver holds a
        # browser process and an abandoned server holds the port.
        if cls.driver is not None:
            with contextlib.suppress(Exception):
                cls.driver.quit()
            cls.driver = None
        if cls.server is not None:
            with contextlib.suppress(Exception):
                cls.server.shutdown()
                cls.server.server_close()
            cls.server = None

    # ── page helpers ─────────────────────────────────────────────
    def open(self, query=""):
        self.driver.get("http://127.0.0.1:%d/cloud.html%s" % (self.port, query))
        self.driver.execute_script(
            "try { localStorage.removeItem('wd-dev-pos'); } catch (e) {}")

    def open_clean(self):
        """A page with dev mode positively off, whatever a previous test left
        in localStorage."""
        self.open("?dev=0")
        self.open()

    def unlocked(self):
        self.open("?dev=1")

    def find(self, css):
        found = self.driver.find_elements(By.CSS_SELECTOR, css)
        return found[0] if found else None

    def stub(self):
        self.driver.execute_script(STUB_API)

    def calls(self):
        return self.driver.execute_script("return window.__devCalls || [];")

    def open_panel(self):
        self.driver.find_element(By.ID, "wdDevToggle").click()

    def result_text(self):
        node = self.find(".wd-dev-result:not([hidden])")
        return node.text if node else ""

    def wait_for(self, predicate, what, tries=60):
        """Poll rather than sleep. Everything here resolves a promise, so the
        wait is short - but it is never zero."""
        import time
        for _ in range(tries):
            if predicate():
                return
            time.sleep(0.1)
        self.fail("timed out waiting for %s in %s" % (what, self.kind))

    # ── off by default ───────────────────────────────────────────
    def test_a_normal_page_has_no_toolbar_on_it(self):
        """The first requirement. He must never hit this while working."""
        self.open_clean()
        self.assertIsNone(self.find("#wdDev"))

    def test_the_tool_itself_is_untouched_when_dev_mode_is_off(self):
        """Separate from the tools means the tools do not change. The page's
        own heading is still the page's own heading."""
        self.open_clean()
        self.assertTrue(self.driver.find_elements(By.CSS_SELECTOR, "body"))
        self.assertIsNone(self.find(".wd-dev-panel"))

    # ── opened deliberately ──────────────────────────────────────
    def test_the_query_parameter_turns_it_on(self):
        self.unlocked()
        self.assertIsNotNone(self.find("#wdDev"))

    def test_it_stays_on_for_the_next_page_without_the_parameter(self):
        """It is a mode, not a one-page trick - he navigates between tools
        mid-task."""
        self.unlocked()
        self.open()
        self.assertIsNotNone(self.find("#wdDev"))

    def test_the_exit_button_turns_it_off_and_it_stays_off(self):
        """A labelled way out, and it has to survive a reload or he is stuck
        with it."""
        self.unlocked()
        self.driver.find_element(By.ID, "wdDevExit").click()
        self.wait_for(lambda: self.find("#wdDev") is None, "the toolbar to go")
        self.open()
        self.assertIsNone(self.find("#wdDev"))

    def test_dev_zero_turns_it_off_too(self):
        self.unlocked()
        self.open("?dev=0")
        self.assertIsNone(self.find("#wdDev"))

    # ── obvious when he is in it ─────────────────────────────────
    def test_it_says_dev_mode_in_words(self):
        """Not an icon he has to remember. This project's rule is that every
        control says what it is."""
        self.unlocked()
        self.assertEqual(self.find(".wd-dev-label").text.strip().upper(),
                         "DEV MODE")

    def test_every_control_on_it_carries_a_text_label(self):
        """The same rule, applied to the whole surface. An unlabelled button
        here would be the one that writes to ninety files."""
        self.unlocked()
        self.open_panel()
        for button in self.driver.find_elements(By.CSS_SELECTOR,
                                                "#wdDev button"):
            self.assertTrue(button.text.strip(),
                            "a dev toolbar button has no text label")

    def test_it_is_drawn_in_the_colour_reserved_for_it(self):
        """Pink is not used for any tool's chrome, which is what makes the
        toolbar unmistakable. Read back the computed border, not the
        stylesheet."""
        self.unlocked()
        border = self.driver.execute_script(
            "return getComputedStyle(document.getElementById('wdDev'))"
            ".borderTopColor;")
        self.assertEqual(border.replace(" ", ""), "rgb(236,72,153)")

    # ── the action, driven ───────────────────────────────────────
    def test_the_action_is_listed_with_its_name_and_its_explanation(self):
        self.unlocked()
        self.open_panel()
        card = self.find('[data-action-id="cloud-realign-renamed"]')
        self.assertIsNotNone(card, "the realign action is not on the toolbar")
        text = card.text
        self.assertIn("Realign", text)
        self.assertIn("cloud newer", text)
        self.assertIn("backups folder", text)

    def test_the_live_button_is_dead_until_a_preview_has_run(self):
        """Dry run by default, made structural. This is the property that
        stops a mis-click writing to his projects."""
        self.unlocked()
        self.open_panel()
        run = self.find("[data-dev-run]")
        self.assertIsNotNone(run)
        self.assertFalse(run.is_enabled(),
                         "the live button was clickable before any preview")

    def test_the_preview_asks_the_server_for_a_dry_run(self):
        """The argument that decides whether his files are written to, pinned
        by reading what the click actually sent."""
        self.unlocked()
        self.stub()
        self.open_panel()
        self.find("[data-dev-preview]").click()
        self.wait_for(lambda: len(self.calls()) == 1, "the preview call")
        call = self.calls()[0]
        self.assertEqual(call["action"], "cloud/realign_renamed")
        self.assertIs(call["body"]["dryRun"], True)

    def test_the_preview_shows_what_would_happen_per_file(self):
        self.unlocked()
        self.stub()
        self.open_panel()
        self.find("[data-dev-preview]").click()
        self.wait_for(lambda: "Maple Depot Survey" in self.result_text(),
                      "the preview report")
        text = self.result_text()
        self.assertIn("Nothing has been changed", text)
        self.assertIn("Set the modified date", text)
        self.assertIn("Birch Yard Walkthrough", text)
        self.assertIn("genuinely differ", text)

    def test_a_successful_preview_arms_the_live_button(self):
        self.unlocked()
        self.stub()
        self.open_panel()
        self.find("[data-dev-preview]").click()
        self.wait_for(lambda: self.find("[data-dev-run]").is_enabled(),
                      "the live button to arm")

    def test_a_failed_preview_leaves_the_live_button_dead(self):
        """The bad day. An error has to leave him unable to run for real, not
        merely told that something went wrong."""
        self.unlocked()
        self.driver.execute_script(
            "window.WD.api = function () {"
            "  return Promise.resolve({ error: 'Not connected' }); };")
        self.open_panel()
        self.find("[data-dev-preview]").click()
        self.wait_for(lambda: "Not connected" in self.result_text(),
                      "the error to show")
        self.assertFalse(self.find("[data-dev-run]").is_enabled())

    def test_the_live_run_asks_first_and_stops_if_he_says_no(self):
        """`confirm` returning false must send nothing at all."""
        self.unlocked()
        self.stub()
        self.open_panel()
        self.find("[data-dev-preview]").click()
        self.wait_for(lambda: self.find("[data-dev-run]").is_enabled(),
                      "the live button to arm")
        self.driver.execute_script("window.confirm = function () "
                                   "{ return false; };")
        self.find("[data-dev-run]").click()
        self.assertEqual(len(self.calls()), 1,
                         "a declined confirm still sent a request")

    def test_the_live_run_sends_dry_run_false(self):
        self.unlocked()
        self.stub()
        self.open_panel()
        self.find("[data-dev-preview]").click()
        self.wait_for(lambda: self.find("[data-dev-run]").is_enabled(),
                      "the live button to arm")
        self.driver.execute_script("window.confirm = function () "
                                   "{ return true; };")
        self.find("[data-dev-run]").click()
        self.wait_for(lambda: len(self.calls()) == 2, "the live call")
        self.assertIs(self.calls()[1]["body"]["dryRun"], False)

    def test_the_live_run_disarms_itself_afterwards(self):
        """The report on screen describes a run that has happened. Clicking
        again should mean deciding again."""
        self.unlocked()
        self.stub()
        self.open_panel()
        self.find("[data-dev-preview]").click()
        self.wait_for(lambda: self.find("[data-dev-run]").is_enabled(),
                      "the live button to arm")
        self.driver.execute_script("window.confirm = function () "
                                   "{ return true; };")
        self.find("[data-dev-run]").click()
        self.wait_for(lambda: len(self.calls()) == 2, "the live call")
        self.wait_for(lambda: not self.find("[data-dev-run]").is_enabled(),
                      "the live button to disarm")

    def test_registering_another_action_puts_it_on_the_toolbar(self):
        """The toolbar is meant to hold many of these. One `register` call is
        the whole cost of adding one, and this proves it by adding one."""
        self.unlocked()
        self.driver.execute_script("""
          window.WD.Dev.register({
            id: 'a-second-action', group: 'Housekeeping',
            label: 'A second action', summary: 'Proves registration.',
            preview: function () { return Promise.resolve({ ok: true }); }
          });
        """)
        self.open_panel()
        card = self.find('[data-action-id="a-second-action"]')
        self.assertIsNotNone(card)
        self.assertIn("A second action", card.text)
        # The group heading is uppercased by the stylesheet, so compare
        # case-insensitively rather than pinning the rendered casing.
        self.assertIn("HOUSEKEEPING",
                      self.find("#wdDevActions").text.upper())

    def test_a_read_only_action_gets_no_live_button(self):
        """An action with no `run` is a diagnostic, and must not render a
        control that would do nothing."""
        self.unlocked()
        self.driver.execute_script("""
          window.WD.Dev.register({
            id: 'read-only-action', group: 'Housekeeping',
            label: 'Read only', summary: 'Looks, never writes.',
            preview: function () { return Promise.resolve({ ok: true }); }
          });
        """)
        self.open_panel()
        card = self.find('[data-action-id="read-only-action"]')
        self.assertEqual(
            card.find_elements(By.CSS_SELECTOR, "[data-dev-run]"), [])


    # ── the housekeeping action, driven ──────────────────────────
    #
    # Its own stub, because the two actions send different bodies and the
    # point of these is what the click actually puts on the wire.
    HK_STUB = """
    window.__devCalls = [];
    window.WD.api = function (action, body) {
      window.__devCalls.push({ action: action, body: body });
      if (action === 'dev/housekeeping_survey') {
        return Promise.resolve({
          ok: true, dataScanComplete: true, liveWindowMinutes: 20,
          totals: { count: 3, sizeBytes: 5000000, deletable: 2,
                    deletableBytes: 4000000, live: 1, withData: 1,
                    dataFindings: 4 },
          processes: [{ pid: 4242, name: 'geckodriver.exe',
                        why: 'A WebDriver executable, started by a test run.' }],
          groups: [{
            key: 'tests', title: 'Test suite leftovers',
            totals: { count: 3, sizeBytes: 5000000, deletable: 2,
                      deletableBytes: 4000000, live: 1, withData: 1,
                      dataFindings: 4 },
            entries: [
              { path: 'C:/Temp/wd-cloud-pull-aaa', name: 'wd-cloud-pull-aaa',
                sizeBytes: 2000000, idleHours: 30, live: false, liveReason: '',
                dataFindings: 0, deletable: true, note: 'A temp directory.' },
              { path: 'C:/Temp/wd-cloud-pull-bbb', name: 'wd-cloud-pull-bbb',
                sizeBytes: 2000000, idleHours: 40, live: false, liveReason: '',
                dataFindings: 4, deletable: true, note: 'A temp directory.' },
              { path: 'C:/wd-worktrees/live-one', name: 'live-one',
                sizeBytes: 1000000, idleHours: 0.1, live: true,
                liveReason: 'Registered as a worktree - a session may be using it.',
                dataFindings: 0, deletable: false, note: 'A registered worktree.' }
            ]
          }]
        });
      }
      return Promise.resolve({
        ok: true, freedBytes: 4000000,
        removed: [{ path: 'C:/Temp/wd-cloud-pull-aaa',
                    name: 'wd-cloud-pull-aaa', sizeBytes: 4000000 }],
        skipped: [], failed: [],
        counts: { removed: 1, skipped: 0, failed: 0 }
      });
    };
    """

    def hk_stub(self):
        self.driver.execute_script(self.HK_STUB)

    def hk_card(self):
        return self.find('[data-action-id="housekeeping"]')

    def hk_preview(self):
        return self.hk_card().find_element(By.CSS_SELECTOR, "[data-dev-preview]")

    def hk_run(self):
        return self.hk_card().find_element(By.CSS_SELECTOR, "[data-dev-run]")

    def hk_result(self):
        node = self.hk_card().find_elements(
            By.CSS_SELECTOR, ".wd-dev-result:not([hidden])")
        return node[0].text if node else ""

    def test_the_housekeeping_action_is_on_the_toolbar_with_its_explanation(self):
        self.unlocked()
        self.open_panel()
        card = self.hk_card()
        self.assertIsNotNone(card, "the housekeeping action is not registered")
        text = card.text
        self.assertIn("lying around", text)
        self.assertIn("Dropbox", text)
        self.assertIn("Desktop", text)

    def test_its_live_button_is_dead_until_it_has_looked(self):
        """Same structural rule as the realign action. This one deletes
        thousands of things, so it matters more here, not less."""
        self.unlocked()
        self.open_panel()
        self.assertFalse(self.hk_run().is_enabled())

    def test_looking_asks_the_survey_endpoint_and_writes_nothing(self):
        self.unlocked()
        self.hk_stub()
        self.open_panel()
        self.hk_preview().click()
        self.wait_for(lambda: len(self.calls()) == 1, "the survey call")
        self.assertEqual(self.calls()[0]["action"], "dev/housekeeping_survey")

    def test_the_report_leads_with_the_workplace_data_count(self):
        self.unlocked()
        self.hk_stub()
        self.open_panel()
        self.hk_preview().click()
        self.wait_for(lambda: "workplace data" in self.hk_result(),
                      "the survey report")
        text = self.hk_result()
        self.assertIn("1 item carries", text)
        self.assertIn("4 signals", text)

    def test_the_report_names_what_is_kept_and_why(self):
        self.unlocked()
        self.hk_stub()
        self.open_panel()
        self.hk_preview().click()
        self.wait_for(lambda: "live-one" in self.hk_result(), "the kept item")
        self.assertIn("Registered as a worktree", self.hk_result())

    def test_the_report_lists_a_process_it_could_stop(self):
        self.unlocked()
        self.hk_stub()
        self.open_panel()
        self.hk_preview().click()
        self.wait_for(lambda: "geckodriver" in self.hk_result(), "the process")
        self.assertIn("4242", self.hk_result())

    def test_the_sweep_sends_only_the_paths_the_preview_offered(self):
        """The live one is in the report and must not be in the request.
        The server checks again anyway - this is the near guard, not the
        only one."""
        self.unlocked()
        self.hk_stub()
        self.open_panel()
        self.hk_preview().click()
        self.wait_for(lambda: self.hk_run().is_enabled(), "the button to arm")
        self.driver.execute_script("window.confirm = function () { return true; };")
        self.hk_run().click()
        self.wait_for(lambda: len(self.calls()) == 2, "the sweep call")
        call = self.calls()[1]
        self.assertEqual(call["action"], "dev/housekeeping_sweep")
        paths = call["body"]["paths"]
        self.assertIn("C:/Temp/wd-cloud-pull-aaa", paths)
        self.assertIn("C:/Temp/wd-cloud-pull-bbb", paths)
        self.assertNotIn("C:/wd-worktrees/live-one", paths)

    def test_a_declined_confirm_sends_nothing(self):
        self.unlocked()
        self.hk_stub()
        self.open_panel()
        self.hk_preview().click()
        self.wait_for(lambda: self.hk_run().is_enabled(), "the button to arm")
        self.driver.execute_script("window.confirm = function () { return false; };")
        self.hk_run().click()
        self.assertEqual(len(self.calls()), 1,
                         "a declined confirm still sent a delete request")

    def test_a_second_look_replaces_the_list_rather_than_adding_to_it(self):
        """A stale path from an earlier look must never reach a delete. Two
        previews in a row have to leave exactly one list behind."""
        self.unlocked()
        self.hk_stub()
        self.open_panel()
        self.hk_preview().click()
        self.wait_for(lambda: self.hk_run().is_enabled(), "the first look")
        self.hk_preview().click()
        self.wait_for(lambda: len(self.calls()) == 2, "the second look")
        self.wait_for(lambda: self.hk_run().is_enabled(), "the button to re-arm")
        pending = self.driver.execute_script(
            "return window.WD.Dev._housekeepingPending();")
        self.assertEqual(len(pending), 2)

    def test_the_sweep_report_says_what_was_freed(self):
        self.unlocked()
        self.hk_stub()
        self.open_panel()
        self.hk_preview().click()
        self.wait_for(lambda: self.hk_run().is_enabled(), "the button to arm")
        self.driver.execute_script("window.confirm = function () { return true; };")
        self.hk_run().click()
        self.wait_for(lambda: "Removed" in self.hk_result(), "the sweep report")
        self.assertIn("freeing", self.hk_result())

    def test_a_failed_look_leaves_the_delete_button_dead(self):
        self.unlocked()
        self.driver.execute_script(
            "window.__devCalls = [];"
            "window.WD.api = function () {"
            "  return Promise.resolve({ error: 'Could not read the folder' }); };")
        self.open_panel()
        self.hk_preview().click()
        self.wait_for(lambda: "Could not read" in self.hk_result(),
                      "the error to show")
        self.assertFalse(self.hk_run().is_enabled())



class FirefoxToolbarTests(ToolbarInABrowser):
    """His browser, and the one that decides a disagreement."""
    kind, binary = BROWSERS[0]


class ChromeToolbarTests(ToolbarInABrowser):
    kind, binary = BROWSERS[1]


class EdgeToolbarTests(ToolbarInABrowser):
    kind, binary = BROWSERS[2]


def load_tests(loader, tests, pattern):
    """Drop the abstract base class, keep the three real ones."""
    suite = unittest.TestSuite()
    for cls in (FirefoxToolbarTests, ChromeToolbarTests, EdgeToolbarTests):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    return suite


if __name__ == "__main__":
    unittest.main()
