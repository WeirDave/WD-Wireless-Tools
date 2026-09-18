"""The dev entry is in the hamburger menu of every page that has one.

**This is the test that was missing, and the defect it would have caught.**
`test_dev_toolbar_browser.py` drives one page - `cloud.html` - and asserted
the nav entry from there. Cloud Manager is one of only three pages whose
hamburger menu is called `#mainMenu`, which is the id the injection looked
for. On the other sixteen, including **Home**, the entry silently never
appeared, and he reported exactly that: "I see no link in nav hamburger menu."

One page tested, nineteen shipped. So this walks every page.

Two properties, and the second is the one that makes the first matter:

* the entry is **present** in each page's menu, and
* it is **visible with dev mode off**, because it is the way *in*. Only the
  Exit item is hidden until dev mode is on - that is WaxFrame's arrangement
  (`#navDevSection`, `.active` to reveal), and getting it backwards would
  leave no route into dev mode through the menu at all.

`?dev=1` is checked on every page too, since that is the fallback route while
anything here is wrong.

Chrome, Edge and Firefox, per the standing rule.
"""
from __future__ import annotations

import contextlib
import re
import socket
import threading
import time
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

#: Its own port range, so it never collides with the other browser test.
PORT_HINT = 8841

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

#: The menu classes `WD.toggleMenu` recognises, which is what the injection
#: targets. Kept here as one string so the test and the code agree about what
#: a nav menu is.
MENU_SELECTOR = ".main-menu, .help-menu, .wd-menu"


def pages_that_load_the_toolbar():
    """Every page that pulls in wd-dev.js, read off disk rather than listed.

    A hand-maintained list is how a page gets added and quietly skipped.
    """
    out = []
    for path in sorted(WEB.glob("*.html")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "js/wd-dev.js" in text:
            out.append(path.name)
    return out


def pages_with_a_menu():
    """Of those, the ones that actually have a hamburger menu to put it in.

    `setup.html` is the first-run screen and deliberately has none; it is not
    a failure that the entry is absent there, and `?dev=1` still works.
    """
    out = []
    for name in pages_that_load_the_toolbar():
        text = (WEB / name).read_text(encoding="utf-8", errors="ignore")
        if re.search(r'class="[^"]*\b(main-menu|help-menu|wd-menu)\b', text):
            out.append(name)
    return out


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


class EveryPage(unittest.TestCase):

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
        if cls.driver is not None:
            with contextlib.suppress(Exception):
                cls.driver.quit()
            cls.driver = None
        if cls.server is not None:
            with contextlib.suppress(Exception):
                cls.server.shutdown()
                cls.server.server_close()
            cls.server = None

    def open(self, page, query=""):
        self.driver.get("http://127.0.0.1:%d/%s%s" % (self.port, page, query))
        # The injection runs on DOMContentLoaded; give it a beat to land.
        for _ in range(40):
            if self.driver.execute_script(
                    "return !!(window.WD && window.WD.Dev);"):
                return
            time.sleep(0.05)

    def locked(self, page):
        self.open(page, "?dev=0")
        self.open(page)

    # ── the entry is there, on every page with a menu ────────────
    def test_every_page_with_a_menu_has_the_dev_entry(self):
        """One page tested, nineteen shipped. This is the correction."""
        missing = []
        for page in pages_with_a_menu():
            self.locked(page)
            found = self.driver.find_elements(By.CSS_SELECTOR, ".nav-item-dev")
            if not found:
                missing.append(page)
        self.assertEqual(missing, [],
                         "no Dev Tools entry in the hamburger menu of these "
                         "pages, so there is no way into dev mode from them")

    def test_the_entry_is_in_every_menu_a_page_carries(self):
        """Quick Walls and friends carry two - one for the drop-zone screen
        and one for the workspace - and a session can be on either."""
        short = []
        for page in pages_with_a_menu():
            self.locked(page)
            menus = len(self.driver.find_elements(By.CSS_SELECTOR, MENU_SELECTOR))
            entries = len(self.driver.find_elements(By.CSS_SELECTOR, ".nav-item-dev"))
            if entries != menus:
                short.append("%s (%d menus, %d entries)" % (page, menus, entries))
        self.assertEqual(short, [])

    def open_the_menu(self):
        """Put the page in the state he is in when he clicks the hamburger.

        Two steps, and the second one is not a fudge. Several tools hide their
        whole app screen until the tool is in use - Cloud Manager's `#appScreen`
        is `display: none` until it has a session, so on the login screen the
        topbar and its hamburger are not on the page at all. Revealing it is
        what "he is logged in and looking at the menu" means; without it this
        would be asserting that a menu he cannot see yet is visible.
        """
        self.driver.execute_script("""
          document.querySelectorAll('#appScreen, #workScreen, #wsScreen')
            .forEach(function (el) {
              if (getComputedStyle(el).display === 'none') el.style.display = 'block';
            });
          document.querySelectorAll(arguments[0]).forEach(
            function (m) { m.classList.add('open'); });
        """, MENU_SELECTOR)
        time.sleep(0.05)

    def test_the_entry_is_visible_before_dev_mode_is_on(self):
        """It is the way *in*. Hiding it along with the exit item would leave
        `?dev=1` as the only route, which is what he was describing."""
        hidden = []
        for page in pages_with_a_menu():
            self.locked(page)
            self.open_the_menu()
            entry = self.driver.find_elements(By.CSS_SELECTOR, ".nav-item-dev")
            if not entry or not any(e.is_displayed() for e in entry):
                hidden.append(page)
        self.assertEqual(hidden, [],
                         "the Dev Tools entry is not visible with dev mode "
                         "off, so it cannot be used to turn dev mode on")

    def test_the_exit_item_is_hidden_until_dev_mode_is_on(self):
        """The other half of WaxFrame's arrangement, and the thing that must
        not be true of the entry item."""
        page = pages_with_a_menu()[0]
        self.locked(page)
        self.open_the_menu()
        exits = self.driver.find_elements(By.CSS_SELECTOR, ".nav-item-exit-dev")
        self.assertTrue(exits)
        self.assertFalse(any(e.is_displayed() for e in exits))

        self.open(page, "?dev=1")
        self.open_the_menu()
        exits = self.driver.find_elements(By.CSS_SELECTOR, ".nav-item-exit-dev")
        self.assertTrue(any(e.is_displayed() for e in exits))

    def test_the_entry_matches_the_rows_around_it(self):
        """A `menu-item` in a `help-menu` would render as a stray button.
        Assert the class matches the menu it landed in."""
        wrong = []
        for page in pages_with_a_menu():
            self.locked(page)
            bad = self.driver.execute_script("""
              var out = [];
              document.querySelectorAll('.nav-item-dev').forEach(function (el) {
                var menu = el.closest('%s');
                if (!menu) { out.push('orphan'); return; }
                var want = menu.classList.contains('help-menu')
                  ? 'help-menu-item' : 'menu-item';
                if (!el.classList.contains(want)) out.push(want);
              });
              return out;
            """ % MENU_SELECTOR)
            if bad:
                wrong.append("%s %s" % (page, bad))
        self.assertEqual(wrong, [])

    def test_the_entry_opens_the_password_modal_from_any_page(self):
        """Present is not the same as wired."""
        for page in pages_with_a_menu():
            with self.subTest(page=page):
                self.locked(page)
                entry = self.driver.find_element(By.CSS_SELECTOR, ".nav-item-dev")
                self.driver.execute_script("arguments[0].click();", entry)
                modal = self.driver.find_element(By.ID, "devModal")
                self.assertIn("active", modal.get_attribute("class"),
                              "the entry did not open the modal on " + page)

    # ── the fallback route ───────────────────────────────────────
    def test_dev_one_unlocks_on_every_page_that_loads_the_toolbar(self):
        """His fallback while anything above is wrong, and it must work even
        on the pages that have no menu at all."""
        broken = []
        for page in pages_that_load_the_toolbar():
            self.open(page, "?dev=1")
            tb = self.driver.find_elements(By.ID, "devToolbar")
            if not tb or not tb[0].is_displayed():
                broken.append(page)
            self.open(page, "?dev=0")
        self.assertEqual(broken, [],
                         "?dev=1 did not show the toolbar on these pages")

    def test_a_page_without_a_menu_is_not_a_failure(self):
        """`setup.html` is the first-run screen and has no hamburger. The
        toolbar still works there; only the menu entry is absent, and this
        records that as intended rather than as a gap."""
        no_menu = [p for p in pages_that_load_the_toolbar()
                   if p not in pages_with_a_menu()]
        for page in no_menu:
            with self.subTest(page=page):
                self.open(page, "?dev=1")
                tb = self.driver.find_elements(By.ID, "devToolbar")
                self.assertTrue(tb and tb[0].is_displayed())
        # If this ever hits zero, the guard above has simply stopped being
        # needed - but it should never be most of the suite.
        self.assertLess(len(no_menu), 3, "too many pages have no nav menu")


class FirefoxNavTests(EveryPage):
    """His browser."""
    kind, binary = BROWSERS[0]


class ChromeNavTests(EveryPage):
    kind, binary = BROWSERS[1]


class EdgeNavTests(EveryPage):
    kind, binary = BROWSERS[2]


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for cls in (FirefoxNavTests, ChromeNavTests, EdgeNavTests):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    return suite


if __name__ == "__main__":
    unittest.main()
