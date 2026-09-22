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
import socket
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
#: An odd high port of this file's own - 8675 is his running instance.
PORT_HINT = 8847

try:  # pragma: no cover - availability varies by machine
    from selenium import webdriver
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False


def _free_port(start):
    for port in range(start, start + 40):
        with contextlib.closing(socket.socket()) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free port near %d" % start)


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


def _driver(kind, binary):
    try:
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

        cls.port = _free_port(PORT_HINT)
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", cls.port), partial(StubBackend, directory=str(WEB)))
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
        self.assertEqual([], misses, "\n".join(misses))

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
                try:
                    summary.click()
                except Exception as exc:
                    refused.append("%s: the menu itself would not open (%s)"
                                   % (label, type(exc).__name__))
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

del MenuItemsCanBeClicked   # the base itself is not a case to run


if __name__ == "__main__":
    unittest.main()
