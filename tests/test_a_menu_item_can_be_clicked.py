"""Every dropdown item can be reached by a mouse, not just by a script.

**This is the difference between the two, and it is the whole reason the file
exists.** `element.click()` in JavaScript dispatches the event straight at the
element, whatever is painted on top of it and whether or not the element is
visible at all. The browser's own hit testing - what happens when a person
moves a mouse to a place on the screen and presses - does not. So a control
can be completely unreachable and every script-driven test of it stays green.

That is not hypothetical. In v2.168.1, shipped, `.wd-menu` was carrying a
`max-height` and `overflow-y: auto` meant for the navigation menus. The class
is not a navigation menu: it is Cloud Manager's `<details>` wrapper, and
`overflow-y: auto` on it made it a scroll container, which clips its
absolutely positioned panel to the 28px "Select" button. The panel was laid
out with correct coordinates and painted nowhere. Select was dead, and so was
the whole move/share/mark/overwrite menu - Move to site, Merge folders,
Share, Mark as External, Mark as mine, Make matching pairs agree, Overwrite
from cloud. Reported as "it's all wonky ... no function". Measured in
Firefox, Chrome and Edge; none of them differed.

Two questions are asked of each item, because they fail differently:

  * `document.elementFromPoint` at the item's own centre has to return the
    item. That catches clipping, a panel painted behind something, and a
    transparent overlay sitting across it.
  * Selenium's `click()` has to succeed. It scrolls the element into view and
    clicks the point, through the browser, so it refuses exactly where a
    person's mouse would miss - `ElementNotInteractableException` is what this
    defect produced.

Nothing here reaches a real account: the page is served from `web/` by the
stub below and no cloud data is loaded. The menus are in the markup, so the
question is answerable without one.
"""
from __future__ import annotations

from tests import browsers as _browsers

import contextlib
import json
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

try:  # pragma: no cover - availability varies by machine
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False


class StubBackend(SimpleHTTPRequestHandler):
    """`web/`, plus the one endpoint the page needs to believe in a server.

    Without an answer to `/api/settings/get` the page decides it is the
    serverless build and never finishes setting itself up.
    """

    def log_message(self, *a):
        pass

    def _send(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._send({"ok": True, "settings": {}})
        return super().do_GET()

    def do_POST(self):
        with contextlib.suppress(Exception):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
        return self._send({"ok": True})


class QuietServer(_browsers.ExclusiveServer):
    """A browser that abandons a download is not a failure.

    Chrome fetches the page's multi-size favicon after the load event, and the
    click test reloads the page once per item - so the next reload regularly
    cuts that download off. The default handler prints a full
    `ConnectionAbortedError` traceback for it, which sat directly above the one
    real failure this file has had in CI and read as its cause. It was not.
    """

    def handle_error(self, request, client_address):
        import sys
        if isinstance(sys.exc_info()[1], (ConnectionAbortedError,
                                           ConnectionResetError,
                                           BrokenPipeError)):
            return
        super().handle_error(request, client_address)


#: How long a freshly revealed menu gets to become clickable. The bar is
#: shown by script a moment before the click, and on a loaded CI runner Chrome
#: once refused that click as not interactable - one run in many, never
#: reproduced locally in over 300 attempts.
SETTLE_S = 5

#: What the page looked like when a menu would not open, so that a failure
#: explains itself instead of only naming an exception.
WHY_NOT = """
const s = arguments[0], r = s.getBoundingClientRect();
const app = document.getElementById('appScreen');
const bar = document.getElementById('selectionBar');
const at = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
return JSON.stringify({
  ready: document.readyState, path: location.pathname,
  app: app && getComputedStyle(app).display,
  barHidden: bar ? bar.hidden : null,
  rect: [r.left, r.top, r.width, r.height].map(Math.round),
  viewport: [innerWidth, innerHeight],
  at: at ? at.tagName.toLowerCase() + (at.id ? '#' + at.id : '') : null,
});
"""


def _driver(kind, binary):
    try:
        if kind == "safari":
            return _browsers.safari_driver()
        if kind == "firefox":
            opts = webdriver.FirefoxOptions()
            opts.binary_location = binary
            opts.add_argument("-headless")
            opts.add_argument("--width=1920")
            opts.add_argument("--height=960")
            return webdriver.Firefox(options=opts)
        if kind == "chrome":
            opts = webdriver.ChromeOptions()
            opts.binary_location = binary
            opts.add_argument("--headless=new")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--window-size=1920,960")
            return webdriver.Chrome(options=opts)
        opts = webdriver.EdgeOptions()
        opts.binary_location = binary
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--window-size=1920,960")
        return webdriver.Edge(options=opts)
    except Exception:  # pragma: no cover - a missing driver is a skip
        return None


#: Show the app, and show the selection bar, without needing a session or a
#: selection - the menus are in the markup either way and the question here is
#: whether they can be pressed.
REVEAL = """
const app = document.getElementById('appScreen');
if (app) app.style.display = 'flex';
const login = document.getElementById('loginScreen');
if (login) login.style.display = 'none';
const bar = document.getElementById('selectionBar');
if (bar) bar.hidden = false;
return document.querySelectorAll('details.wd-menu').length;
"""

#: What is actually painted where this item claims to be.
WHAT_IS_THERE = """
const it = arguments[0];
const r = it.getBoundingClientRect();
if (!r.width || !r.height) return {painted: false, found: null};
const hit = document.elementFromPoint(r.left + Math.min(30, r.width / 2),
                                      r.top + r.height / 2);
return {
  painted: true,
  isTheItem: !!(hit && (hit === it || it.contains(hit))),
  found: hit ? (hit.tagName.toLowerCase() + (hit.id ? '#' + hit.id : '')
                + (hit.className && hit.className.split
                   ? '.' + hit.className.split(' ').filter(Boolean).join('.')
                   : '')) : null,
};
"""


class MenuItemsCanBeClicked(unittest.TestCase):

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

        cls.server = QuietServer(
            ("127.0.0.1", 0), partial(StubBackend, directory=str(WEB)))
        cls.port = cls.server.server_address[1]
        cls.addClassCleanup(cls._stop_server)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

        cls.driver = _driver(cls.kind, cls.binary)
        if cls.driver is None:
            raise unittest.SkipTest("%s would not start" % cls.kind)
        cls.addClassCleanup(cls._stop_driver)
        cls.driver.set_page_load_timeout(60)

    @classmethod
    def _stop_driver(cls):
        _browsers.shut_down(cls.driver)
        cls.driver = None

    @classmethod
    def _stop_server(cls):
        _browsers.stop_server(cls.server)
        cls.server = None

    def setUp(self):
        self.driver.get("http://127.0.0.1:%d/cloud.html" % self.port)
        self.menus = self.driver.execute_script(REVEAL)

    def _each_menu(self):
        return self.driver.find_elements("css selector", "details.wd-menu")

    def test_the_page_has_the_dropdowns_this_is_about(self):
        self.assertGreaterEqual(
            self.menus, 2,
            "cloud.html no longer has the dropdowns this guards - if they were "
            "renamed, rename them here too rather than deleting the check")

    def test_every_item_is_where_it_says_it_is(self):
        """The browser's own hit testing has to find the item at its own centre.

        A clipped panel still reports sensible coordinates; this is what
        notices that nothing is painted at them.
        """
        misses = self._misplaced()
        self.assertEqual([], misses, "\n".join(misses))

    def test_they_are_still_reachable_on_a_short_screen(self):
        """The same question at 1366x768, which is the size that matters.

        The rule that caused this was a `max-height` written for a window too
        short to hold a long menu - and the browsers here are fixed at 960
        tall, so the one shape of regression this file exists for is the one
        its own viewport cannot show. A cap that engages only below some
        height would pass every other case in this file.

        Restoring the size is a cleanup rather than a line at the end,
        because a failure part way through would otherwise leave every later
        test in the class running at a size it never asked for.
        """
        was = self.driver.get_window_size()
        self.addCleanup(self.driver.set_window_size,
                        was["width"], was["height"])
        self.driver.set_window_size(1366, 768)
        self.setUp()
        misses = self._misplaced()
        self.assertEqual(
            [], misses,
            "at 1366x768 these items are drawn where nothing can reach them:"
            + "\n" + "\n".join(misses))

    def _misplaced(self):
        """Every item whose own centre belongs to something else."""
        misses = []
        for menu in self._each_menu():
            label = self.driver.execute_script(
                "return arguments[0].querySelector('summary').textContent"
                ".trim();", menu)
            self.driver.execute_script("arguments[0].open = true;", menu)
            for item in menu.find_elements("css selector", ".wd-menu-item"):
                text = self.driver.execute_script(
                    "return arguments[0].textContent.trim();", item)
                found = self.driver.execute_script(WHAT_IS_THERE, item)
                if not found.get("painted"):
                    misses.append("%s / %s: nothing is drawn there at all"
                                  % (label, text))
                elif not found.get("isTheItem"):
                    misses.append("%s / %s: the point belongs to %s"
                                  % (label, text, found.get("found")))
            self.driver.execute_script("arguments[0].open = false;", menu)
        return misses

    def test_every_item_accepts_a_real_click(self):
        """And the browser has to let a mouse press it.

        Deliberately a real `click()` rather than a scripted one: the scripted
        one passed all the way through the release where none of these
        worked.
        """
        refused = []
        shape = self.driver.execute_script("""
          return Array.from(document.querySelectorAll('details.wd-menu'))
            .map(m => [m.querySelector('summary').textContent.trim(),
                       m.querySelectorAll('.wd-menu-item').length]);
        """)
        for index, (label, count) in enumerate(shape):
            for position in range(count):
                # **A fresh page for every item.** These handlers run for
                # real: some clear the selection, which takes the selection
                # bar and the menu inside it off the page, and some open a
                # dialog that then covers the menu. Both are correct, and
                # both would read here as a control that could not be
                # pressed. Reloading asks only the question this is about.
                self.setUp()
                menu = self._each_menu()[index]
                summary = menu.find_element("css selector", "summary")
                # Waiting on the summary cannot hide the defect this file is
                # about: in v2.168.1 the Select button itself worked and the
                # items it opened were unreachable. A summary that never
                # becomes clickable still fails, a few seconds later.
                with contextlib.suppress(TimeoutException):
                    WebDriverWait(self.driver, SETTLE_S).until(
                        EC.element_to_be_clickable(summary))
                try:
                    summary.click()
                except Exception as exc:
                    refused.append("%s: the menu itself would not open (%s) %s"
                                   % (label, type(exc).__name__,
                                      self.driver.execute_script(WHY_NOT, summary)))
                    break
                item = self._each_menu()[index].find_elements(
                    "css selector", ".wd-menu-item")[position]
                text = self.driver.execute_script(
                    "return arguments[0].textContent.trim();", item)
                try:
                    item.click()
                except Exception as exc:
                    refused.append("%s / %s: %s"
                                   % (label, text, type(exc).__name__))
        self.assertEqual([], refused, "\n".join(refused))

    def test_the_wrapper_is_not_a_scroll_container(self):
        """The shape of the defect, stated directly.

        The two checks above are the ones that matter and would catch a
        different cause too. This one names what went wrong, so that
        re-introducing it fails with a sentence rather than with a list of
        unreachable items.
        """
        bad = self.driver.execute_script("""
          return Array.from(document.querySelectorAll('.wd-menu')).map(m => {
            const cs = getComputedStyle(m);
            return (cs.overflowX !== 'visible' || cs.overflowY !== 'visible')
              ? [m.id || m.querySelector('summary').textContent.trim(),
                 cs.overflowX, cs.overflowY] : null;
          }).filter(Boolean);
        """)
        self.assertEqual(
            [], bad,
            "a .wd-menu with a non-visible overflow clips its own panel away: "
            + json.dumps(bad))


def _case(kind, binary):
    return type("%sMenuItemsCanBeClickedTests" % kind.capitalize(),
                (MenuItemsCanBeClicked,), {"kind": kind, "binary": binary})


FirefoxMenuItemsCanBeClickedTests = _case("firefox", _browsers.find("firefox"))
ChromeMenuItemsCanBeClickedTests = _case("chrome", _browsers.find("chrome"))
EdgeMenuItemsCanBeClickedTests = _case("edge", _browsers.find("edge"))
SafariMenuItemsCanBeClickedTests = (_case(*_browsers.triple()[3])
    if len(_browsers.triple()) > 3 else None)

del MenuItemsCanBeClicked   # the base itself is not a case to run


if __name__ == "__main__":
    unittest.main()
