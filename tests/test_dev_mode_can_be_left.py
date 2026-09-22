"""Every way into dev mode, and every way out of it.

"there isn't an x on the dev toolbar!" - and there was not. Dev mode had one
control that entered it and, on screen, nothing that left it. The documented
exit was a nav item, and the nav item had already been reported missing, so for
a user the mode was enterable and not leavable; the only way out was knowing to
type `?dev=0` in the address bar, which is not a user interface.

It compounded the print fault: stuck in dev mode, with the toolbar printing
onto a report that was going to installers.

**The lifecycle is the feature.** The actions on the toolbar were tested from
the start - they were never the risky part. What shipped broken twice was the
way in and the way out. So these drive the whole loop in a real browser:

    in  - the nav item, and the ?dev=1 URL
    out - the toolbar's own exit, the nav item, and the ?dev=0 URL

and then print, because leaving dev mode has to actually clear the thing that
was landing on the paper.

Entry through the nav goes through the real password modal. The plaintext is
not in this repository and is not in this file; `Dev._expectedHash` is the seam
the modal already exposes for exactly this, so the test names its own secret,
hashes it with the page's own SHA-256, and drives the real submit path. The
shipped hash is never involved and nothing here is a credential.
"""
from __future__ import annotations

from tests import browsers as _browsers

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

PORT_HINT = 8917

#: Chosen here, hashed by the page. Not the shipped password.
TEST_PW = "not-the-real-password"

try:  # pragma: no cover
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False

FIREFOX = _browsers.find("firefox")


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


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
@unittest.skipUnless(Path(FIREFOX).exists(), "Firefox is not installed here")
class DevModeLifecycle(unittest.TestCase):
    """Firefox, because it is his browser and it is where both faults landed."""

    PAGE = "report.html"

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port(PORT_HINT)
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", cls.port), partial(QuietHandler, directory=str(WEB)))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        opts = webdriver.FirefoxOptions()
        opts.binary_location = FIREFOX
        opts.add_argument("-headless")
        # 1366x768, because the menu fault only exists below about 1000px of
        # viewport: at 1080p the injected items are on screen and every one of
        # these passes against the broken build. A default-sized headless
        # window is the version of this test that proves nothing.
        opts.add_argument("-width"); opts.add_argument("1366")
        opts.add_argument("-height"); opts.add_argument("768")
        try:
            cls.driver = webdriver.Firefox(options=opts)
        except (WebDriverException, OSError) as exc:
            cls.server.shutdown()
            cls.server.server_close()
            raise unittest.SkipTest("Firefox would not start: %s" % exc)

    @classmethod
    def tearDownClass(cls):
        _browsers.shut_down(cls.driver)
        _browsers.stop_server(cls.server)

    # ── helpers ──────────────────────────────────────────────────
    def open(self, query=""):
        self.driver.get("http://127.0.0.1:%d/%s%s"
                        % (self.port, self.PAGE, query))
        for _ in range(60):
            if self.driver.execute_script("return !!(window.WD && window.WD.Dev);"):
                break
            time.sleep(0.05)
        time.sleep(0.25)

    def strip_visible(self):
        return self.driver.execute_script(
            "var t = document.getElementById('devToolbar');"
            "return !!t && !t.classList.contains('is-hidden');")

    def stored_flag(self):
        return self.driver.execute_script(
            "return localStorage.getItem('wd_dev');")

    def in_dev_mode(self):
        """Both halves, because they have drifted apart before: the flag that
        survives a reload, and the strip that is actually on the screen."""
        return self.strip_visible(), self.stored_flag()

    def open_the_hamburger(self):
        """Open the menu the way a person does, rather than forcing `.open`.

        A nav item inside a collapsed menu is not displayed, so a test that
        skips this measures nothing. Pages carry more than one menu - the
        drop-zone tools have one before a file is loaded and another after -
        so this opens each in turn and stops at the one that actually became
        visible on screen."""
        buttons = self.driver.find_elements(By.CSS_SELECTOR, '[data-action="menu"]')
        for btn in buttons:
            if not btn.is_displayed():
                continue
            btn.click()
            time.sleep(0.2)
            return True
        return False

    def visible_nav_item(self, selector):
        """The first match that is actually on screen. `find_element` returns
        document order, which on a two-menu page is the one in the menu that
        is not open."""
        for el in self.driver.find_elements(By.CSS_SELECTOR, selector):
            if el.is_displayed():
                return el
        return None

    def expect_password(self, plaintext):
        """Point the modal at a hash this test owns.

        `_hash` resolves a Promise - SHA-256 through `crypto.subtle` - while
        the submit path compares against `_expectedHash()` synchronously. So
        the digest is computed first and the seam then returns that string;
        an override that returns the Promise itself never matches anything,
        which is a quiet way for this test to pass for the wrong reason."""
        digest = self.driver.execute_async_script(
            "var done = arguments[arguments.length - 1];"
            "window.WD.Dev._hash(arguments[0]).then(done);", plaintext)
        self.driver.execute_script(
            "var d = arguments[0];"
            "window.WD.Dev._expectedHash = function () { return d; };", digest)
        return digest

    # ── the ways in ──────────────────────────────────────────────
    def test_in_by_url(self):
        self.open("?dev=0")
        self.open("?dev=1")
        self.assertEqual(self.in_dev_mode(), (True, "1"))

    def test_in_by_the_nav_item_and_the_password(self):
        """The WaxFrame route: the menu item opens the modal, the modal takes
        a password, and the toolbar appears. Driven through the real submit
        path with a hash this test chose."""
        self.open("?dev=0")
        self.assertFalse(self.strip_visible())
        self.expect_password(TEST_PW)

        self.assertTrue(self.open_the_hamburger(), "no menu button on the page")
        entry = self.visible_nav_item(".nav-item-dev")
        self.assertIsNotNone(entry, "no Dev Tools item in the open menu")
        entry.click()
        time.sleep(0.25)
        self.assertIn("active",
                      self.driver.find_element(By.ID, "devModal")
                      .get_attribute("class"),
                      "the nav item did not open the password modal")

        box = self.driver.find_element(By.ID, "devPwInput")
        box.send_keys(TEST_PW)
        unlock = self.driver.find_element(
            By.CSS_SELECTOR, '#devModal [data-fn="WD.Dev.submitDevPassword"].btn-primary')
        unlock.click()
        time.sleep(0.6)
        self.assertEqual(self.in_dev_mode(), (True, "1"),
                         "the password was accepted but dev mode did not start")

    # ── the ways out ─────────────────────────────────────────────
    def test_out_by_the_toolbar_exit(self):
        """The one he went looking for and could not find."""
        self.open("?dev=1")
        self.assertTrue(self.strip_visible())
        btn = self.driver.find_element(By.ID, "devExitBtn")
        self.assertTrue(btn.is_displayed(), "the exit control is not on screen")
        btn.click()
        time.sleep(0.3)
        self.assertEqual(self.in_dev_mode(), (False, None))

    def test_the_toolbar_exit_says_what_it_does(self):
        """An unlabelled glyph is the thing he has already objected to. The ✕
        is what he looked for; the words are what stop it reading as 'close
        this panel'."""
        self.open("?dev=1")
        label = self.driver.find_element(By.ID, "devExitBtn").text
        self.assertIn("✕", label)
        self.assertIn("Exit dev mode", label)

    def test_out_by_the_nav_item(self):
        self.open("?dev=1")
        self.assertTrue(self.open_the_hamburger(), "no menu button on the page")
        exit_item = self.visible_nav_item(".nav-item-exit-dev")
        self.assertIsNotNone(
            exit_item, "no Exit Dev Mode item in the open menu while dev is on")
        exit_item.click()
        time.sleep(0.3)
        self.assertEqual(self.in_dev_mode(), (False, None))

    def test_out_by_url(self):
        self.open("?dev=1")
        self.open("?dev=0")
        self.assertEqual(self.in_dev_mode(), (False, None))

    # ── what the exits are for ───────────────────────────────────
    def test_leaving_survives_a_reload(self):
        """Hiding the strip without clearing the flag would put it straight
        back on the next page he opens - and back onto his printout."""
        self.open("?dev=1")
        self.driver.find_element(By.ID, "devExitBtn").click()
        time.sleep(0.3)
        self.open()
        self.assertEqual(self.in_dev_mode(), (False, None))

    def test_both_nav_items_can_be_reached_in_a_short_window(self):
        """The reason the entry was reported missing.

        Not "is it in the DOM" - it always was - but whether a person can get
        a click onto it. On a 768px screen the menu ran 714px tall with no cap
        and no scroll, so the last two items sat past the bottom edge with
        nothing to scroll them into view. Asserting on the rectangle rather
        than on `is_displayed()`, which was true the whole time it was
        unreachable."""
        self.open("?dev=1")
        self.assertTrue(self.open_the_hamburger(), "no menu button on the page")
        vh = self.driver.execute_script("return window.innerHeight;")
        for selector, what in ((".nav-item-dev", "Dev Tools"),
                               (".nav-item-exit-dev", "Exit Dev Mode")):
            el = self.visible_nav_item(selector)
            self.assertIsNotNone(el, "%s is not in the open menu" % what)
            # Scroll it into view the way a person scrolls the menu, then ask
            # where it ended up. An item inside a scrollable menu is fine; one
            # in a menu that cannot scroll stays off the bottom.
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'nearest'});", el)
            rect = self.driver.execute_script(
                "var r = arguments[0].getBoundingClientRect();"
                "return [r.top, r.bottom];", el)
            self.assertGreaterEqual(rect[0], 0,
                                    "%s sits above the top of the window" % what)
            self.assertLessEqual(
                rect[1], vh,
                "%s sits below the bottom of the window and cannot be "
                "scrolled to - the menu has no height cap" % what)

    def test_the_exit_control_is_reachable_while_dev_mode_is_on(self):
        """The strip is draggable and position-persistent. An exit that can be
        dragged off-screen and left there is the same trap again."""
        self.open("?dev=1")
        btn = self.driver.find_element(By.ID, "devExitBtn")
        size = self.driver.get_window_size()
        box = self.driver.execute_script(
            "var r = arguments[0].getBoundingClientRect();"
            "return [r.left, r.top, r.right, r.bottom];", btn)
        self.assertGreaterEqual(box[0], 0, "the exit sits off the left edge")
        self.assertGreaterEqual(box[1], 0, "the exit sits above the top edge")
        self.assertLessEqual(box[2], size["width"],
                             "the exit sits off the right edge")
        self.assertLessEqual(box[3], size["height"],
                             "the exit sits below the bottom edge")


if __name__ == "__main__":
    unittest.main()
