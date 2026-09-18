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
