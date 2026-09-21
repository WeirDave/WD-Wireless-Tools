"""The dev toolbar, driven in a real browser by clicking it.

**These check WaxFrame Professional's method, not a reinterpretation of it.**
An earlier build reshaped the toolbar into a vertical panel of named actions
and dropped the password gate, and he said plainly that was not what he asked
for: he has two products and wants them to work the same way. So each class
below names the WaxFrame behaviour it is holding in place.

The properties, and where each comes from:

* **the gate** - `localStorage['wd_dev']`, set by a SHA-256 password modal
  opened from an Advanced nav item, with a second nav item to leave; a wrong
  password closes the modal and says nothing (WaxFrame `submitDevPassword`)
* **the strip** - one horizontal row, a `⚙ DEV` label that is also the drag
  handle, `|` separators, and buttons whose labels read as plain language,
  each opening a panel rather than doing anything itself
* **declarative registration** - `data-action="call"` + `data-fn="a.b.c"`,
  run by one delegated listener, resolved by walking a dotted path over
  `window` rather than by `eval` (WaxFrame `callAction` / `resolveDotted`)
* **drag and remember** - position in `localStorage['wd_dev_toolbar_pos']`
  (WaxFrame `attachDevToolbarDrag`)

And the things that are his rather than WaxFrame's, kept deliberately:
`--pink`/`--lime`, `?dev=1` with no key chord, and the two-stage dry run on
anything that writes.

The server is `http.server` over `web/`, never `server.py`, which opens a
browser window nobody closes. `WD.api` is stubbed - it is the seam the
handlers use - so a test can never reach his Ekahau account or his disk.

Chrome, Edge and Firefox, per the standing rule, Firefox first.
"""
from __future__ import annotations

import contextlib
import socket
import threading
import time
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

#: An unusual port. 8675 is his own running instance and must never be bound.
PORT_HINT = 8791

#: **There is no password in this file, deliberately.** The gate uses the same
#: hash as WaxFrame Professional now - his password, shared across both
#: products at his request - and the plaintext belongs in neither repository.
#:
#: So the positive path is driven without knowing it: the test hashes a string
#: it chose, points `WD.Dev._expectedHash` at that value, and submits. Every
#: line of the real submit path runs - the input is read, hashed with the real
#: SHA-256, compared, and on a match the flag is written and the toolbar
#: mounts. What is not asserted is that one particular secret opens it, and
#: that was never the interesting claim. That the shipped constant is the one
#: WaxFrame uses is checked separately, by comparing the two files.
TEST_PASSPHRASE = "a-string-this-test-invented"

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
    def log_message(self, *a):
        pass


def _driver(kind, binary):
    """A headless driver, or None when it will not start - so one missing
    browser cannot fail the run on a machine that has the other two."""
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


#: Replaces `WD.api`, recording what each handler asked for and answering with
#: the shape the server returns. Both endpoints, because the strip carries
#: both actions at once now.
STUB_API = """
window.__devCalls = [];
window.WD.api = function (action, body) {
  window.__devCalls.push({ action: action, body: body });
  if (action === 'cloud/realign_renamed') {
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
      failed: [], counts: { aligned: 1, skipped: 1, failed: 0 }
    });
  }
  if (action === 'dev/housekeeping_survey') {
    return Promise.resolve({
      ok: true, dataScanComplete: true, liveWindowMinutes: 20,
      totals: { count: 3, sizeBytes: 5000000, deletable: 2,
                deletableBytes: 4000000, live: 1, withData: 1, dataFindings: 4 },
      processes: [{ pid: 4242, name: 'geckodriver.exe',
                    why: 'A WebDriver executable, started by a test run.' }],
      groups: [{ key: 'tests', title: 'Test suite leftovers',
        totals: { count: 3, sizeBytes: 5000000, deletable: 2,
                  deletableBytes: 4000000, live: 1, withData: 1, dataFindings: 4 },
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
        ] }]
    });
  }
  return Promise.resolve({
    ok: true, freedBytes: 4000000,
    removed: [{ path: 'C:/Temp/wd-cloud-pull-aaa', name: 'wd-cloud-pull-aaa',
                sizeBytes: 4000000 }],
    skipped: [], failed: [], counts: { removed: 1, skipped: 0, failed: 0 }
  });
};
"""


class ToolbarInABrowser(unittest.TestCase):
    """One server and one browser per class - starting a driver is the slow
    part and every test here is open-then-click on a fresh page."""

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
            ("127.0.0.1", cls.port), partial(QuietHandler, directory=str(WEB)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

        cls.driver = _driver(cls.kind, cls.binary)
        if cls.driver is None:
            cls.server.shutdown()
            cls.server.server_close()
            raise unittest.SkipTest("%s would not start" % cls.kind)
        cls.driver.set_page_load_timeout(60)

    @classmethod
    def tearDownClass(cls):
        # Always, on the failure path too: an abandoned driver holds a browser
        # process and an abandoned server holds the port.
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

    def locked(self):
        """Dev mode positively off, whatever an earlier test left behind."""
        self.open("?dev=0")
        self.open()

    def unlocked(self):
        self.open("?dev=1")
        self.wait_for(lambda: self.find("#devToolbar") is not None,
                      "the toolbar to mount")

    def find(self, css):
        found = self.driver.find_elements(By.CSS_SELECTOR, css)
        return found[0] if found else None

    def visible(self, css):
        el = self.find(css)
        return el is not None and el.is_displayed()

    def stub(self):
        self.driver.execute_script(STUB_API)

    def calls(self):
        return self.driver.execute_script("return window.__devCalls || [];")

    def result_text(self):
        body = self.find("#devResultBody")
        return body.text if body else ""

    def wait_for(self, predicate, what, tries=80):
        for _ in range(tries):
            try:
                if predicate():
                    return
            except Exception:
                pass
            time.sleep(0.1)
        self.fail("timed out waiting for %s in %s" % (what, self.kind))

    def click(self, css):
        el = self.find(css)
        self.assertIsNotNone(el, "no element for %s" % css)
        self.driver.execute_script("arguments[0].click();", el)

    # ══ the gate ══════════════════════════════════════════════════
    def test_a_normal_page_has_no_toolbar_on_it(self):
        """Off by default. He must never hit this while working."""
        self.locked()
        self.assertFalse(self.visible("#devToolbar"))

    def test_the_nav_offers_dev_tools_under_advanced(self):
        """WaxFrame's entry point: an Advanced section in the nav menu."""
        self.locked()
        item = self.find(".menu-item.nav-item-dev")
        self.assertIsNotNone(item, "no Dev Tools nav item")
        # `textContent`, not `.text`: the menu is collapsed until the
        # hamburger is clicked, and Selenium reports "" for anything not
        # displayed. The question here is whether the item exists and is
        # labelled, not whether the menu happens to be open.
        self.assertIn("Dev Tools", item.get_attribute("textContent"))

    def test_the_exit_item_is_hidden_until_dev_mode_is_on(self):
        """WaxFrame's `#navDevSection`, `.active` to reveal - but a class here
        rather than an id, because a page can carry two menus and two elements
        sharing an id is how the second one stops being findable."""
        self.locked()
        self.assertFalse(self.visible(".nav-dev-section"))
        self.unlocked()
        sections = self.driver.find_elements(By.CSS_SELECTOR, ".nav-dev-section")
        self.assertTrue(sections)
        for section in sections:
            self.assertIn("active", section.get_attribute("class"))

    def test_the_nav_item_opens_the_password_modal(self):
        self.locked()
        self.click(".menu-item.nav-item-dev")
        self.wait_for(lambda: self.visible("#devModal"), "the password modal")

    def test_a_wrong_password_says_nothing_and_stays_locked(self):
        """WaxFrame closes the modal and reports nothing. Telling a guesser
        they were close is worse than saying nothing."""
        self.locked()
        self.click(".menu-item.nav-item-dev")
        self.wait_for(lambda: self.visible("#devModal"), "the modal")
        self.find("#devPwInput").send_keys("not-the-password")
        self.click("#devModal .btn-primary")
        self.wait_for(lambda: not self.visible("#devModal"), "the modal to close")
        self.assertFalse(self.visible("#devToolbar"))
        self.assertIsNone(self.driver.execute_script(
            "return localStorage.getItem('wd_dev');"))

    def arm_with_a_known_phrase(self):
        """Point the gate at a hash this test knows, computed by the page's
        own SHA-256. Nothing about the real constant is needed, or learned.

        An async script, because hashing returns a promise - `execute_script`
        would hand back `undefined` before it resolved and the test would then
        be asserting about a gate that had not been re-pointed at all.
        """
        self.driver.set_script_timeout(20)
        return self.driver.execute_async_script("""
          var phrase = arguments[0], done = arguments[1];
          window.WD.Dev._hash(phrase).then(function (h) {
            window.WD.Dev._expectedHash = function () { return h; };
            done(h);
          });
        """, TEST_PASSPHRASE)

    def test_a_matching_password_unlocks_it(self):
        """The whole submit path, run for real, without the secret."""
        self.locked()
        self.click(".menu-item.nav-item-dev")
        self.wait_for(lambda: self.visible("#devModal"), "the modal")
        self.arm_with_a_known_phrase()
        self.find("#devPwInput").send_keys(TEST_PASSPHRASE)
        self.click("#devModal .btn-primary")
        self.wait_for(lambda: self.visible("#devToolbar"), "the toolbar")
        self.assertEqual(self.driver.execute_script(
            "return localStorage.getItem('wd_dev');"), "1")

    def test_the_input_is_hashed_rather_than_compared_as_text(self):
        """The gate compares a SHA-256, not the string. Typing the hash
        itself must not open it - if it did, the comparison would be against
        whatever was typed rather than against a digest of it."""
        self.locked()
        self.click(".menu-item.nav-item-dev")
        self.wait_for(lambda: self.visible("#devModal"), "the modal")
        digest = self.arm_with_a_known_phrase()
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.find("#devPwInput").send_keys(digest)
        self.click("#devModal .btn-primary")
        self.wait_for(lambda: not self.visible("#devModal"), "the modal to close")
        self.assertFalse(self.visible("#devToolbar"))

    def test_enter_submits_the_password(self):
        """WaxFrame wires the input with `data-key-action="enter-call"`."""
        self.locked()
        self.click(".menu-item.nav-item-dev")
        self.wait_for(lambda: self.visible("#devModal"), "the modal")
        self.arm_with_a_known_phrase()
        field = self.find("#devPwInput")
        field.send_keys(TEST_PASSPHRASE)
        field.send_keys("\ue007")          # Enter
        self.wait_for(lambda: self.visible("#devToolbar"), "the toolbar")

    def test_the_query_parameter_also_unlocks(self):
        """His, not WaxFrame's: a deliberate way in that is not a key chord."""
        self.locked()
        self.unlocked()
        self.assertTrue(self.visible("#devToolbar"))

    def test_it_stays_on_across_pages(self):
        self.unlocked()
        self.open()
        self.wait_for(lambda: self.visible("#devToolbar"), "the toolbar")

    def test_the_nav_exit_item_turns_it_off_and_it_stays_off(self):
        self.unlocked()
        self.click(".menu-item.nav-item-exit-dev")
        self.wait_for(lambda: not self.visible("#devToolbar"), "it to go")
        self.open()
        self.assertFalse(self.visible("#devToolbar"))

    def test_dev_zero_turns_it_off_too(self):
        self.unlocked()
        self.open("?dev=0")
        self.assertFalse(self.visible("#devToolbar"))

    # ══ the strip ═════════════════════════════════════════════════
    def test_it_is_one_horizontal_row(self):
        """WaxFrame's shape, and the thing the earlier build replaced with a
        vertical panel. Measured, not asserted from the stylesheet."""
        self.unlocked()
        display = self.driver.execute_script(
            "var s = getComputedStyle(document.getElementById('devToolbar'));"
            "return [s.display, s.flexDirection, s.position];")
        self.assertEqual(display[0], "flex")
        self.assertEqual(display[1], "row")
        self.assertEqual(display[2], "fixed")

    def test_the_label_reads_dev(self):
        self.unlocked()
        self.assertIn("DEV", self.find(".dev-toolbar-label").text.upper())

    def test_the_buttons_are_separated_into_groups(self):
        """WaxFrame groups its buttons with `|` separators."""
        self.unlocked()
        seps = self.driver.find_elements(By.CSS_SELECTOR, ".dev-toolbar-sep")
        self.assertGreaterEqual(len(seps), 1)

    def test_every_button_carries_a_title_and_a_label(self):
        """WaxFrame puts a `title` on every dev-toolbar button, and this
        project's own rule is that every control says what it is. The label
        is what has to carry the meaning now - see
        `test_every_strip_button_reads_as_plain_language` - and the title is
        a courtesy on top of it."""
        self.unlocked()
        buttons = self.driver.find_elements(By.CSS_SELECTOR, "#devToolbar button")
        self.assertGreaterEqual(len(buttons), 3)
        for b in buttons:
            label = (b.get_attribute("textContent") or "").strip()
            self.assertTrue(label, "a dev toolbar button has no label")
            self.assertTrue((b.get_attribute("title") or "").strip(),
                            "a dev toolbar button has no title: %r" % label)

    def test_it_is_drawn_in_the_colour_reserved_for_it(self):
        """Pink is his, not WaxFrame's amber - no tool uses it for chrome."""
        self.unlocked()
        border = self.driver.execute_script(
            "return getComputedStyle(document.getElementById('devToolbar'))"
            ".borderTopColor;")
        self.assertEqual(border.replace(" ", ""), "rgb(236,72,153)")

    def test_the_tool_underneath_is_untouched(self):
        self.unlocked()
        self.assertIsNotNone(self.find(".topbar"))
        self.assertIsNotNone(self.find("#mainMenu"))

    # ══ the dispatcher ════════════════════════════════════════════
    def test_a_data_action_call_runs_the_named_function(self):
        """WaxFrame's registration method, driven: a button carrying
        `data-action="call"` and `data-fn` runs that function when clicked."""
        self.unlocked()
        self.driver.execute_script("""
          window.__ran = [];
          window.WD.Dev.__probe = function () { window.__ran.push('plain'); };
          var b = document.createElement('button');
          b.id = 'probeBtn';
          b.setAttribute('data-action', 'call');
          b.setAttribute('data-fn', 'WD.Dev.__probe');
          b.textContent = 'probe';
          document.getElementById('devToolbar').appendChild(b);
        """)
        self.click("#probeBtn")
        self.wait_for(lambda: self.driver.execute_script("return window.__ran;"),
                      "the dispatched call")
        self.assertEqual(
            self.driver.execute_script("return window.__ran;"), ["plain"])

    def test_a_data_arg_is_passed_through(self):
        self.unlocked()
        self.driver.execute_script("""
          window.__arg = null;
          window.WD.Dev.__probeArg = function (v) { window.__arg = v; };
          var b = document.createElement('button');
          b.id = 'probeArgBtn';
          b.setAttribute('data-action', 'call');
          b.setAttribute('data-fn', 'WD.Dev.__probeArg');
          b.setAttribute('data-arg', 'hello');
          b.textContent = 'probe';
          document.getElementById('devToolbar').appendChild(b);
        """)
        self.click("#probeArgBtn")
        self.wait_for(lambda: self.driver.execute_script("return window.__arg;"),
                      "the argument")
        self.assertEqual(self.driver.execute_script("return window.__arg;"),
                         "hello")

    def test_a_dotted_name_resolves_and_keeps_its_receiver(self):
        """`WD.Dev.foo` must be called with `WD.Dev` as `this`, which is why
        WaxFrame binds it. `WF_DEBUG.bundleForScout` relies on the same."""
        self.unlocked()
        ok = self.driver.execute_script("""
          window.WD.Dev.__marker = 'mine';
          window.WD.Dev.__probeThis = function () { return this.__marker; };
          var fn = window.WD.Dev._resolveDotted('WD.Dev.__probeThis');
          return fn();
        """)
        self.assertEqual(ok, "mine")

    def test_resolving_an_unknown_name_is_harmless(self):
        """A name is a string until something calls it. An unknown one must
        not throw - WaxFrame returns undefined and the dispatcher stops."""
        self.unlocked()
        result = self.driver.execute_script(
            "return typeof window.WD.Dev._resolveDotted('no.such.thing');")
        self.assertEqual(result, "undefined")

    def test_a_delegated_control_outside_the_dev_root_fires_exactly_once(self):
        """There are two dispatchers now, and double-firing is the hazard.

        This used to assert that a `data-action` outside `#wdDevRoot` fired
        **zero** times, on the stated reasoning that "the suite wires its own
        controls with inline onclick, and this must not intercept one of
        those". Backlog item 10 is the work that makes that premise false: the
        suite is moving off inline handlers precisely because a
        Content-Security-Policy worth having forbids them, and `WD.actions` in
        `wd-shared.js` is now the document-wide dispatcher that handles them.

        So the property worth holding changed shape rather than going away.
        The dev toolbar's dispatcher is still scoped to `#wdDevRoot`; what
        matters is that the two do not both claim the same element, because a
        handler that runs twice is a delete that happens twice. `WD.actions`
        skips the dev root for exactly this reason, and this is the assertion
        that would notice if it stopped.
        """
        self.unlocked()
        fired = self.driver.execute_script("""
          window.__outside = 0;
          window.__outsideFn = function () { window.__outside += 1; };
          var b = document.createElement('button');
          b.id = 'outsideBtn';
          b.setAttribute('data-action', 'call');
          b.setAttribute('data-fn', '__outsideFn');
          document.body.appendChild(b);
          b.click();
          b.remove();
          return window.__outside;
        """)
        self.assertEqual(
            1, fired,
            "a delegated control outside the dev root fired %d times - 0 means "
            "WD.actions is not mounted, 2 means both dispatchers claimed it"
            % fired)

    def test_a_control_inside_the_dev_root_is_not_handled_twice(self):
        """The other half of the same seam.

        `wd-dev.js` handles `#wdDevRoot` and `WD.actions` skips it. If that
        skip went, every dev-toolbar button would run its handler twice - and
        the toolbar's handlers include ones that delete files.
        """
        self.unlocked()
        fired = self.driver.execute_script("""
          window.__inside = 0;
          window.__insideFn = function () { window.__inside += 1; };
          var root = document.getElementById('wdDevRoot');
          if (!root) return -1;
          var b = document.createElement('button');
          b.setAttribute('data-action', 'call');
          b.setAttribute('data-fn', '__insideFn');
          root.appendChild(b);
          b.click();
          b.remove();
          return window.__inside;
        """)
        self.assertNotEqual(-1, fired, "no #wdDevRoot on the page")
        self.assertEqual(
            1, fired,
            "a control inside the dev root fired %d times - 2 means "
            "WD.actions stopped skipping #wdDevRoot" % fired)

    # ══ drag ══════════════════════════════════════════════════════
    def test_the_position_is_remembered(self):
        """WaxFrame stores `{top,left}` and restores it on the next load."""
        self.unlocked()
        self.driver.execute_script(
            "localStorage.setItem('wd_dev_toolbar_pos',"
            " JSON.stringify({ top: 200, left: 120 }));")
        self.open()
        self.wait_for(lambda: self.visible("#devToolbar"), "the toolbar")
        left = self.driver.execute_script(
            "return document.getElementById('devToolbar').style.left;")
        self.assertEqual(left, "120px")

    def test_leaving_dev_mode_forgets_the_position(self):
        self.unlocked()
        self.driver.execute_script(
            "localStorage.setItem('wd_dev_toolbar_pos',"
            " JSON.stringify({ top: 200, left: 120 }));")
        self.click(".menu-item.nav-item-exit-dev")
        self.wait_for(lambda: not self.visible("#devToolbar"), "it to go")
        self.assertIsNone(self.driver.execute_script(
            "return localStorage.getItem('wd_dev_toolbar_pos');"))

    # ══ the strip says what it is ═════════════════════════════════
    def test_every_strip_button_reads_as_plain_language(self):
        """He opened the first build and said "there are items in here and I
        don't know what they do." A label has to be a phrase, not an emoji
        with the explanation hidden in a tooltip - his rule is that every
        control says what it is, and that nothing a decision rests on hides
        behind a hover."""
        self.unlocked()
        buttons = self.driver.find_elements(By.CSS_SELECTOR, "#devToolbar button")
        self.assertGreaterEqual(len(buttons), 3)
        for b in buttons:
            label = (b.get_attribute("textContent") or "").strip()
            words = [w for w in label.replace("\u2026", " ").split()
                     if any(c.isalpha() for c in w)]
            self.assertGreaterEqual(
                len(words), 2,
                "a dev toolbar button is not a readable phrase: %r" % label)

    def test_nothing_in_the_strip_writes_to_anything(self):
        """Every strip button opens a panel. The controls that write live
        inside it, under the explanation, so he cannot reach one without
        having scrolled past what it does."""
        self.unlocked()
        self.stub()
        for btn in self.driver.find_elements(By.CSS_SELECTOR, "#devToolbar button"):
            self.driver.execute_script("arguments[0].click();", btn)
            self.wait_for(lambda: self.visible("#devResultModal"),
                          "a panel for " + (btn.get_attribute("id") or "?"))
            self.click("#devResultModal .btn")
            self.wait_for(lambda: not self.visible("#devResultModal"), "it to close")
        self.assertEqual(self.calls(), [],
                         "a strip button reached the server on its own")

    # ══ the panels explain themselves ═════════════════════════════
    def open_realign(self):
        self.click("#wdRealignOpenBtn")
        self.wait_for(lambda: self.find("#wdRealignPreviewBtn") is not None,
                      "the realign panel")

    def open_housekeeping(self):
        self.click("#wdHousekeepOpenBtn")
        self.wait_for(lambda: self.find("#wdHousekeepLookBtn") is not None,
                      "the housekeeping panel")

    def panel_text(self):
        body = self.find("#devResultBody")
        return body.text if body else ""

    def test_the_realign_panel_explains_itself_before_he_can_run_it(self):
        """It rewrites ninety live project files. He should not have to ask
        anyone what it does."""
        self.unlocked()
        self.open_realign()
        text = self.panel_text().lower()
        for needed in ("cloud newer", "no copy is kept", "nothing is uploaded",
                       "preview", "modified date"):
            self.assertIn(needed, text,
                          "the realign panel never says %r" % needed)

    def test_the_realign_panel_is_readable_without_hovering(self):
        """Nothing that matters may live in a `title`."""
        self.unlocked()
        self.open_realign()
        facts = self.driver.find_elements(By.CSS_SELECTOR, ".dev-panel-facts dd")
        self.assertGreaterEqual(len(facts), 4)
        for f in facts:
            self.assertTrue(f.is_displayed())
            self.assertGreater(len(f.text.strip()), 30)

    def test_the_housekeeping_panel_explains_what_it_will_not_touch(self):
        self.unlocked()
        self.open_housekeeping()
        text = self.panel_text().lower()
        for needed in ("dropbox", "desktop", "project folders", "look first"):
            self.assertIn(needed, text)

    def test_read_only_and_writing_controls_look_different(self):
        """Lime for the one that changes nothing, pink for the one that
        writes. The distinction was his, and it survives the rebuild."""
        self.unlocked()
        self.open_realign()
        safe = self.driver.execute_script(
            "return getComputedStyle(document.getElementById("
            "'wdRealignPreviewBtn')).borderTopColor;")
        write = self.driver.execute_script(
            "return getComputedStyle(document.getElementById("
            "'wdRealignRunBtn')).borderTopColor;")
        self.assertNotEqual(safe, write)
        self.assertEqual(safe.replace(" ", ""), "rgb(132,204,22)")   # --lime

    def test_the_safe_control_says_it_changes_nothing(self):
        self.unlocked()
        self.open_realign()
        label = self.find("#wdRealignPreviewBtn").text.lower()
        self.assertIn("changes nothing", label)

    # ══ realign, and the two-stage dry run ════════════════════════
    def test_the_realign_live_button_is_dead_until_a_preview_runs(self):
        """His requirement, in WaxFrame's idiom: the live control is rendered
        `disabled` and only its own preview turns it on."""
        self.unlocked()
        self.open_realign()
        self.assertFalse(self.find("#wdRealignRunBtn").is_enabled())

    def test_the_realign_preview_asks_for_a_dry_run(self):
        self.unlocked()
        self.stub()
        self.open_realign()
        self.click("#wdRealignPreviewBtn")
        self.wait_for(lambda: len(self.calls()) == 1, "the preview call")
        call = self.calls()[0]
        self.assertEqual(call["action"], "cloud/realign_renamed")
        self.assertIs(call["body"]["dryRun"], True)

    def test_the_realign_preview_shows_its_report(self):
        self.unlocked()
        self.stub()
        self.open_realign()
        self.click("#wdRealignPreviewBtn")
        self.wait_for(lambda: "Maple Depot Survey" in self.panel_text(),
                      "the preview report")
        text = self.panel_text()
        self.assertIn("Nothing has been changed", text)
        self.assertIn("genuinely differ", text)

    def test_a_clean_preview_arms_the_realign_live_button_and_names_the_count(self):
        """"Align 1 project for real" tells him more than "Align them for
        real" at the moment it matters."""
        self.unlocked()
        self.stub()
        self.open_realign()
        self.click("#wdRealignPreviewBtn")
        self.wait_for(lambda: self.find("#wdRealignRunBtn").is_enabled(),
                      "the live button to arm")
        self.assertIn("1 project", self.find("#wdRealignRunBtn").text)

    def test_a_preview_with_nothing_to_do_leaves_the_live_button_dead(self):
        """Arming a button that would rewrite nothing is an invitation to
        press it and wonder what happened."""
        self.unlocked()
        self.driver.execute_script("""
          window.__devCalls = [];
          window.WD.api = function (a, b) {
            window.__devCalls.push({ action: a, body: b });
            return Promise.resolve({ ok: true, dryRun: true, examined: 0,
              aligned: [], skipped: [], failed: [],
              counts: { aligned: 0, skipped: 0, failed: 0 } });
          };
        """)
        self.open_realign()
        self.click("#wdRealignPreviewBtn")
        self.wait_for(lambda: "Nothing to do" in self.panel_text(), "the report")
        self.assertFalse(self.find("#wdRealignRunBtn").is_enabled())

    def test_a_failed_preview_leaves_the_realign_live_button_dead(self):
        self.unlocked()
        self.driver.execute_script(
            "window.__devCalls = [];"
            "window.WD.api = function () {"
            "  return Promise.resolve({ error: 'Not connected' }); };")
        self.open_realign()
        self.click("#wdRealignPreviewBtn")
        self.wait_for(lambda: "Not connected" in self.panel_text(), "the error")
        self.assertFalse(self.find("#wdRealignRunBtn").is_enabled())

    def test_the_realign_live_run_sends_dry_run_false(self):
        self.unlocked()
        self.stub()
        self.open_realign()
        self.click("#wdRealignPreviewBtn")
        self.wait_for(lambda: self.find("#wdRealignRunBtn").is_enabled(), "arm")
        self.driver.execute_script("window.confirm = function () { return true; };")
        self.click("#wdRealignRunBtn")
        self.wait_for(lambda: len(self.calls()) == 2, "the live call")
        self.assertIs(self.calls()[1]["body"]["dryRun"], False)

    def test_a_declined_confirm_sends_no_realign(self):
        self.unlocked()
        self.stub()
        self.open_realign()
        self.click("#wdRealignPreviewBtn")
        self.wait_for(lambda: self.find("#wdRealignRunBtn").is_enabled(), "arm")
        self.driver.execute_script("window.confirm = function () { return false; };")
        self.click("#wdRealignRunBtn")
        self.assertEqual(len(self.calls()), 1)

    def test_the_realign_live_button_disarms_after_a_run(self):
        self.unlocked()
        self.stub()
        self.open_realign()
        self.click("#wdRealignPreviewBtn")
        self.wait_for(lambda: self.find("#wdRealignRunBtn").is_enabled(), "arm")
        self.driver.execute_script("window.confirm = function () { return true; };")
        self.click("#wdRealignRunBtn")
        self.wait_for(lambda: len(self.calls()) == 2, "the live call")
        self.wait_for(lambda: not self.find("#wdRealignRunBtn").is_enabled(),
                      "it to disarm")

    # ══ knowing it is running, and knowing it is done ═════════════
    def slow_realign(self):
        """A realign that does not answer immediately, with the server's
        progress endpoint answering as the real one does. Ninety cloud
        downloads take minutes; this is the shape of that wait."""
        self.driver.execute_script("""
          window.__devCalls = [];
          window.__resolve = null;
          window.WD.api = function (a, b) {
            window.__devCalls.push({ action: a, body: b });
            return new Promise(function (res) { window.__resolve = res; });
          };
          var realFetch = window.fetch;
          window.fetch = function (url) {
            if (String(url).indexOf('/api/cloud/progress') === 0) {
              return Promise.resolve({ json: function () {
                return Promise.resolve({ current: 34, total: 90,
                  message: 'Checking 34 of 90…' });
              } });
            }
            return realFetch.apply(this, arguments);
          };
        """)

    def test_it_says_where_it_has_got_to_while_it_runs(self):
        """**The server was already reporting this and nothing listened.**
        `cloud_realign` calls its progress callback once per pair and
        `server.py` exposes it at `/api/cloud/progress`; the toolbar sent no
        `opId`, so ninety downloads happened behind a button reading
        "Aligning..." and nothing else. On a fleet this size that is minutes
        of a screen indistinguishable from a hung one."""
        self.unlocked()
        self.slow_realign()
        self.open_realign()
        self.click("#wdRealignPreviewBtn")
        self.wait_for(lambda: "Checking 34 of 90" in self.panel_text(),
                      "the progress line")
        # Scoped to the panel: Cloud Manager's own ops deck has a
        # `.progress-fill` too, and an unscoped query finds that one instead.
        pct = self.driver.execute_script(
            "var f = document.getElementById('devPanelOut')"
            "          .querySelector('.progress-fill');"
            "return f ? f.style.width : null;")
        self.assertEqual(pct, "38%")

    def test_the_request_carries_an_op_id_so_progress_can_be_found(self):
        """The id is what ties the poll to the run. Without it the server
        writes progress into a slot nobody reads."""
        self.unlocked()
        self.slow_realign()
        self.open_realign()
        self.click("#wdRealignPreviewBtn")
        self.wait_for(lambda: len(self.calls()) == 1, "the call")
        self.assertTrue(self.calls()[0]["body"].get("opId"),
                        "no opId sent, so nothing can report progress")

    def test_the_polling_stops_when_the_run_returns(self):
        """A poller left running would keep overwriting the report he is
        trying to read."""
        self.unlocked()
        self.slow_realign()
        self.open_realign()
        self.click("#wdRealignPreviewBtn")
        self.wait_for(lambda: "Checking 34 of 90" in self.panel_text(), "progress")
        self.driver.execute_script("""
          window.__resolve({ ok: true, dryRun: true, examined: 1,
            aligned: [{ name: 'Maple Depot Survey', folder: 'Maple Depot',
                        actions: ['Set the modified date to the cloud’s'] }],
            skipped: [], failed: [],
            counts: { aligned: 1, skipped: 0, failed: 0 } });
        """)
        self.wait_for(lambda: "Maple Depot Survey" in self.panel_text(), "the report")
        time.sleep(0.6)      # longer than the 250ms poll interval
        self.assertIn("Maple Depot Survey", self.panel_text())
        self.assertNotIn("Checking 34 of 90", self.panel_text())

    def test_a_finished_run_says_so_in_words(self):
        """"How will I know after the alignment is complete?" A report
        appearing where a progress bar was is a weak signal."""
        self.unlocked()
        self.stub()
        self.open_realign()
        self.click("#wdRealignPreviewBtn")
        self.wait_for(lambda: self.find("#wdRealignRunBtn").is_enabled(), "arm")
        self.driver.execute_script("window.confirm = function () { return true; };")
        self.click("#wdRealignRunBtn")
        self.wait_for(lambda: "Finished" in self.panel_text(), "the done banner")
        text = self.panel_text()
        self.assertIn("in step with the cloud", text)
        self.assertIn("stop reporting the cloud as newer", text)
        self.assertIn("Nothing was uploaded", text)

    def test_the_finished_run_retitles_the_panel(self):
        """The heading agrees with the banner, so a glance is enough."""
        self.unlocked()
        self.stub()
        self.open_realign()
        self.click("#wdRealignPreviewBtn")
        self.wait_for(lambda: self.find("#wdRealignRunBtn").is_enabled(), "arm")
        self.driver.execute_script("window.confirm = function () { return true; };")
        self.click("#wdRealignRunBtn")
        self.wait_for(
            lambda: "finished" in self.find("#devResultTitle").text.lower(),
            "the retitled panel")

    def test_a_preview_never_claims_to_have_finished_anything(self):
        """The two states must not read alike - that is the whole point of
        the banner."""
        self.unlocked()
        self.stub()
        self.open_realign()
        self.click("#wdRealignPreviewBtn")
        self.wait_for(lambda: "Nothing has been changed" in self.panel_text(),
                      "the preview")
        self.assertNotIn("Finished", self.panel_text())

    # ══ housekeeping ══════════════════════════════════════════════
    def test_the_housekeeping_delete_button_is_dead_until_it_has_looked(self):
        self.unlocked()
        self.open_housekeeping()
        self.assertFalse(self.find("#wdHousekeepSweepBtn").is_enabled())

    def test_looking_asks_the_survey_endpoint(self):
        self.unlocked()
        self.stub()
        self.open_housekeeping()
        self.click("#wdHousekeepLookBtn")
        self.wait_for(lambda: len(self.calls()) == 1, "the survey call")
        self.assertEqual(self.calls()[0]["action"], "dev/housekeeping_survey")

    def test_the_look_leads_with_the_workplace_data_count(self):
        self.unlocked()
        self.stub()
        self.open_housekeeping()
        self.click("#wdHousekeepLookBtn")
        self.wait_for(lambda: "workplace data" in self.panel_text(), "the report")
        text = self.panel_text()
        self.assertIn("1 item carries", text)
        self.assertIn("4 signals", text)
        self.assertIn("live-one", text)
        self.assertIn("Registered as a worktree", text)

    def test_the_sweep_sends_only_what_the_look_offered(self):
        """The live one is in the report and must not be in the request. The
        server re-checks anyway - this is the near guard, not the only one."""
        self.unlocked()
        self.stub()
        self.open_housekeeping()
        self.click("#wdHousekeepLookBtn")
        self.wait_for(lambda: self.find("#wdHousekeepSweepBtn").is_enabled(), "arm")
        self.driver.execute_script("window.confirm = function () { return true; };")
        self.click("#wdHousekeepSweepBtn")
        self.wait_for(lambda: len(self.calls()) == 2, "the sweep call")
        call = self.calls()[1]
        self.assertEqual(call["action"], "dev/housekeeping_sweep")
        paths = call["body"]["paths"]
        self.assertIn("C:/Temp/wd-cloud-pull-aaa", paths)
        self.assertNotIn("C:/wd-worktrees/live-one", paths)

    def test_reopening_the_panel_keeps_the_result_and_stays_armed(self):
        """**This used to clear itself, and he said so plainly:** he looked,
        closed the panel, came back, and had to look again from scratch with
        the delete button greyed out - "this is counterproductive".

        Keeping it is safe because the client is not the guard: `sweep`
        re-derives the whole list at write time and skips anything that is no
        longer deletable. Disarming on close bought nothing and cost him the
        run.
        """
        self.unlocked()
        self.stub()
        self.open_housekeeping()
        self.click("#wdHousekeepLookBtn")
        self.wait_for(lambda: self.find("#wdHousekeepSweepBtn").is_enabled(), "arm")
        before = self.driver.execute_script(
            "return window.WD.Dev._housekeepingPending();")

        self.click("#devResultModal .btn")
        self.open_housekeeping()

        self.assertEqual(
            self.driver.execute_script(
                "return window.WD.Dev._housekeepingPending();"), before)
        self.assertTrue(self.find("#wdHousekeepSweepBtn").is_enabled())
        self.assertIn("Delete 2 items", self.find("#wdHousekeepSweepBtn").text)

    def test_a_remembered_result_says_when_it_was_taken(self):
        """Showing an old answer as though it were fresh would be worse than
        clearing it. It says when, and that the server re-checks anyway."""
        self.unlocked()
        self.stub()
        self.open_housekeeping()
        self.click("#wdHousekeepLookBtn")
        self.wait_for(lambda: self.find("#wdHousekeepSweepBtn").is_enabled(), "arm")
        self.click("#devResultModal .btn")
        self.open_housekeeping()
        text = self.panel_text()
        self.assertIn("just now", text)
        self.assertIn("re-checks every file", text)

    def test_the_realign_preview_survives_closing_the_panel_too(self):
        """The expensive one. A realign preview downloads ninety cloud
        projects to prove them identical; throwing that away because he shut
        a dialog is the costliest version of this bug."""
        self.unlocked()
        self.stub()
        self.open_realign()
        self.click("#wdRealignPreviewBtn")
        self.wait_for(lambda: self.find("#wdRealignRunBtn").is_enabled(), "arm")
        self.click("#devResultModal .btn")
        self.open_realign()
        self.assertTrue(self.find("#wdRealignRunBtn").is_enabled())
        self.assertIn("1 project", self.find("#wdRealignRunBtn").text)
        self.assertIn("Maple Depot Survey", self.panel_text())

    def test_the_controls_stay_on_screen_however_long_the_report_is(self):
        """**The other half of what he hit.** The controls used to sit inside
        the scrolling body above the output. A housekeeping report is six
        screens tall, so once he scrolled down to read it the armed button was
        off the top with nothing to say it existed - "there was no way to make
        it run for real". A control he has to scroll back up to find is a
        control he does not have.
        """
        self.unlocked()
        self.stub()
        self.open_housekeeping()
        self.click("#wdHousekeepLookBtn")
        self.wait_for(lambda: self.find("#wdHousekeepSweepBtn").is_enabled(), "arm")

        # The footer is outside the scroll, which is what makes this hold at
        # any report length.
        self.assertFalse(self.driver.execute_script(
            "return !!document.getElementById('devResultBody')"
            "  .querySelector('#wdHousekeepSweepBtn');"),
            "the live control is inside the scrolling body again")

        # Scroll the report to its end, the way he does after reading it.
        self.driver.execute_script(
            "var b = document.getElementById('devResultBody');"
            "b.scrollTop = b.scrollHeight;")
        time.sleep(0.2)
        on_screen = self.driver.execute_script("""
          var r = document.getElementById('wdHousekeepSweepBtn')
                    .getBoundingClientRect();
          return r.width > 0 && r.height > 0 &&
                 r.top >= 0 && r.bottom <= window.innerHeight;
        """)
        self.assertTrue(on_screen,
                        "the delete control is off screen once the report is "
                        "scrolled - he cannot reach it")

    def test_a_finished_sweep_does_not_leave_a_reusable_list(self):
        """Keeping a *preview* is the fix; keeping a spent delete list is not.
        After a sweep the pending list is empty and the button is dead until
        the next Look."""
        self.unlocked()
        self.stub()
        self.open_housekeeping()
        self.click("#wdHousekeepLookBtn")
        self.wait_for(lambda: self.find("#wdHousekeepSweepBtn").is_enabled(), "arm")
        self.driver.execute_script("window.confirm = function () { return true; };")
        self.click("#wdHousekeepSweepBtn")
        self.wait_for(lambda: len(self.calls()) == 2, "the sweep call")
        self.click("#devResultModal .btn")
        self.open_housekeeping()
        self.assertEqual(
            self.driver.execute_script(
                "return window.WD.Dev._housekeepingPending();"), [])
        self.assertFalse(self.find("#wdHousekeepSweepBtn").is_enabled())

    def test_a_declined_confirm_sends_no_sweep(self):
        self.unlocked()
        self.stub()
        self.open_housekeeping()
        self.click("#wdHousekeepLookBtn")
        self.wait_for(lambda: self.find("#wdHousekeepSweepBtn").is_enabled(), "arm")
        self.driver.execute_script("window.confirm = function () { return false; };")
        self.click("#wdHousekeepSweepBtn")
        self.assertEqual(len(self.calls()), 1)

    def test_a_failed_look_leaves_the_delete_button_dead(self):
        self.unlocked()
        self.driver.execute_script(
            "window.__devCalls = [];"
            "window.WD.api = function () {"
            "  return Promise.resolve({ error: 'Could not read the folder' }); };")
        self.open_housekeeping()
        self.click("#wdHousekeepLookBtn")
        self.wait_for(lambda: "Could not read" in self.panel_text(), "the error")
        self.assertFalse(self.find("#wdHousekeepSweepBtn").is_enabled())

    # ══ the panel modal ═══════════════════════════════════════════
    def test_a_panel_opens_and_closes_again(self):
        """WaxFrame shows detail in a modal rather than growing the strip."""
        self.unlocked()
        self.stub()
        self.open_housekeeping()
        self.assertTrue(self.visible("#devResultModal"))
        self.click("#devResultModal .btn")
        self.wait_for(lambda: not self.visible("#devResultModal"), "it to close")

    def test_about_dev_says_how_to_leave(self):
        """If the app tells him how to get out, that route has to work."""
        self.unlocked()
        self.click("#wdDevAboutBtn")
        self.wait_for(lambda: "Exit Dev Mode" in self.panel_text(),
                      "the about panel")
        self.assertIn("?dev=1", self.panel_text())


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
