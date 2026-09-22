"""Setup is scaled up, and merging its CSS with Settings' would silently undo it.

Backlog item 8 moved 831 lines of embedded CSS into `wd-tools.css`. Eleven
selectors were defined in *both* `settings.html` and `setup.html`, and six of
them had **drifted on purpose**: Setup is the first-run wizard and is larger
throughout - bigger type, more padding, bigger dots and hit areas.

In one stylesheet those six collide, and whichever is written second wins on
both pages. The failure is quiet in the worst way: Settings looks slightly
wrong, or Setup looks slightly small, and neither is obviously broken. The
entry exists because "move the CSS out of the pages" *invites* exactly that
merge.

**Neither page can be told apart by its body class - both carry `tool-home`.**
What separates them is `.setup-wrap`, the wrapper Setup already had, so Setup's
six are scoped to it.

**Three of the six are never in the initial DOM.** `.sf-item`, `.sf-handle` and
`.sf-remove` are built by `renderSubfolders()` into a list container, so a
capture of the page as loaded says nothing about them - which is why this
renders the real markup into the real container before measuring anything.

Chrome, Edge and Firefox, per the standing rule.
"""
from __future__ import annotations

from tests import browsers as _browsers

import contextlib
import json
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

#: Its own port range, clear of 8675 (his own instance) and of the other
#: browser tests here.
PORT_HINT = 8967

BROWSERS = [
    ("firefox", _browsers.find("firefox")),
    ("chrome", _browsers.find("chrome")),
    ("edge", _browsers.find("edge")),
]

try:  # pragma: no cover - availability varies by machine
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False


#: The markup `renderSubfolders()` builds, on both pages. Copied in shape from
#: settings-page.js and setup.js, which produce the same list items into their
#: own container - `#sSfList` on Settings, `#sfList` on Setup.
INJECT = """
var list = document.getElementById(arguments[0]);
if (!list) { return JSON.stringify({error: 'no container ' + arguments[0]}); }
list.innerHTML =
  '<li class="sf-item" data-idx="0">' +
    '<span class="sf-handle">&#9776;</span>' +
    '<input type="text" value="Reports">' +
    '<button class="sf-remove">&times;</button>' +
  '</li>';
var item = list.querySelector('.sf-item');
var handle = list.querySelector('.sf-handle');
var input = list.querySelector('.sf-item input[type="text"]');
var remove = list.querySelector('.sf-remove');
var status = document.querySelector('.cloud-status');
var dot = document.querySelector('.cloud-status .dot');
function grab(el, props) {
  if (!el) return null;
  var cs = getComputedStyle(el), out = {};
  props.forEach(function (p) { out[p] = cs.getPropertyValue(p); });
  return out;
}
return JSON.stringify({
  item:   grab(item,   ['gap', 'padding-top', 'padding-left', 'border-radius']),
  handle: grab(handle, ['font-size']),
  input:  grab(input,  ['font-size', 'padding-top', 'padding-left', 'border-radius']),
  remove: grab(remove, ['font-size', 'padding-top', 'padding-left']),
  status: grab(status, ['gap', 'padding-top', 'padding-left', 'border-radius', 'font-size']),
  dot:    grab(dot,    ['width', 'height']),
});
"""

#: What each side must compute to. Taken from the two blocks as they were
#: before the move, so this pins the drift rather than whatever the merge
#: happened to leave behind.
EXPECTED = {
    "settings": {
        "item": {"gap": "8px", "padding-top": "8px", "padding-left": "10px",
                 "border-radius": "6px"},
        "handle": {"font-size": "16px"},
        "input": {"font-size": "13px", "padding-top": "6px",
                  "padding-left": "8px", "border-radius": "4px"},
        "remove": {"font-size": "16px", "padding-top": "2px",
                   "padding-left": "4px"},
        "status": {"gap": "10px", "padding-top": "10px", "padding-left": "12px",
                   "border-radius": "6px", "font-size": "13px"},
        "dot": {"width": "8px", "height": "8px"},
    },
    "setup": {
        "item": {"gap": "10px", "padding-top": "10px", "padding-left": "14px",
                 "border-radius": "8px"},
        "handle": {"font-size": "20px"},
        "input": {"font-size": "15px", "padding-top": "10px",
                  "padding-left": "12px", "border-radius": "6px"},
        "remove": {"font-size": "20px", "padding-top": "4px",
                   "padding-left": "6px"},
        "status": {"gap": "12px", "padding-top": "14px", "padding-left": "18px",
                   "border-radius": "8px", "font-size": "15px"},
        "dot": {"width": "10px", "height": "10px"},
    },
}

PAGES = {"settings": ("settings.html", "sSfList"),
         "setup": ("setup.html", "sfList")}


def _free_port(start):
    for port in range(start, start + 40):
        with contextlib.closing(socket.socket()) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free port near %d" % start)


class _StubApi(SimpleHTTPRequestHandler):
    """web/ as files, /api/* as JSON. Never server.py, which opens a browser
    window on his desktop that nobody closes.

    Answering ``settings/get`` matters: with it refused the page decides it is
    the hosted build and skips server-backed markup, so the container these
    tests write into may never be rendered.
    """

    def log_message(self, *a):
        pass

    def _json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.path.startswith("/api/"):
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        if self.path == "/api/settings/get":
            self._json({"ok": True, "settings": {"report": {}, "aprename": {}}})
        else:
            self._json({"ok": True})

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._json({"ok": True, "exists": False})
            return
        super().do_GET()


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class SetupStaysBiggerThanSettingsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port(PORT_HINT)
        cls.httpd = ThreadingHTTPServer(
            ("127.0.0.1", cls.port), partial(_StubApi, directory=str(WEB)))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    @staticmethod
    def _driver(kind, binary):
        if not Path(binary).exists():
            return None
        try:
            if kind == "firefox":
                o = webdriver.FirefoxOptions()
                o.binary_location = binary
                o.add_argument("-headless")
                return webdriver.Firefox(options=o)
            if kind == "chrome":
                o = webdriver.ChromeOptions()
                o.binary_location = binary
                o.add_argument("--headless=new")
                o.add_argument("--no-sandbox")
                return webdriver.Chrome(options=o)
            o = webdriver.EdgeOptions()
            o.binary_location = binary
            o.add_argument("--headless=new")
            return webdriver.Edge(options=o)
        except (WebDriverException, OSError):
            return None

    def _measure(self, driver, which):
        page, container = PAGES[which]
        driver.get("http://127.0.0.1:%d/%s" % (self.port, page))
        time.sleep(1.0)
        got = json.loads(driver.execute_script(INJECT, container))
        self.assertNotIn("error", got, "%s: %s" % (which, got.get("error")))
        return got

    def _each_browser(self):
        started = 0
        for kind, binary in BROWSERS:
            driver = self._driver(kind, binary)
            if driver is None:
                continue
            started += 1
            try:
                yield kind, driver
            finally:
                with contextlib.suppress(Exception):
                    driver.quit()
        if not started:
            self.skipTest("none of Chrome, Edge or Firefox could be started")

    def test_both_pages_compute_the_sizes_their_own_block_asked_for(self):
        """The whole check, in one pass per browser.

        Every part is measured on both pages and compared against what that
        page's own block said before the move, so a merge in either direction
        fails: Settings inflated to Setup's numbers, or Setup shrunk to
        Settings'.
        """
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                for which in ("settings", "setup"):
                    got = self._measure(driver, which)
                    for part, props in EXPECTED[which].items():
                        self.assertIsNotNone(
                            got.get(part),
                            "%s/%s: %s is not on the page at all"
                            % (kind, which, part))
                        for prop, want in props.items():
                            self.assertEqual(
                                want, got[part][prop],
                                "%s / %s / %s / %s" % (kind, which, part, prop))

    def test_the_two_pages_really_do_differ(self):
        """The guard, stated as the thing that must stay true.

        If a later pass merges the six into one rule, every assertion above
        still describes a coherent page - it is just the wrong one. This fails
        the moment the two agree, whichever way the merge went.
        """
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                st = self._measure(driver, "settings")
                su = self._measure(driver, "setup")
                same = []
                for part in EXPECTED["settings"]:
                    for prop in EXPECTED["settings"][part]:
                        if st[part][prop] == su[part][prop]:
                            same.append("%s.%s" % (part, prop))
                self.assertEqual(
                    [], same,
                    "%s: Settings and Setup now agree on %s - the six drifted "
                    "selectors have been merged, which is the thing backlog "
                    "item 8 existed to prevent" % (kind, ", ".join(same)))

    def test_setup_is_the_larger_of_the_two_everywhere(self):
        """Direction, not just difference. A merge that happened to leave two
        different-but-wrong values would satisfy the test above."""
        numeric = [("handle", "font-size"), ("input", "font-size"),
                   ("status", "font-size"), ("dot", "width"), ("dot", "height"),
                   ("item", "padding-left"), ("status", "padding-left")]
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                st = self._measure(driver, "settings")
                su = self._measure(driver, "setup")
                for part, prop in numeric:
                    a = float(st[part][prop].replace("px", ""))
                    b = float(su[part][prop].replace("px", ""))
                    self.assertGreater(
                        b, a, "%s: setup %s %s (%s) is not larger than "
                              "settings' (%s)" % (kind, part, prop, b, a))


class TheScopeThatSeparatesThemTests(unittest.TestCase):
    """`.setup-wrap` is what makes the split work, so it has to stay.

    Both pages carry `body.tool-home`, so the body class cannot separate them.
    If Setup's wrapper is ever renamed, the six scoped rules stop matching and
    Setup silently takes Settings' sizes - and the browser tests above are the
    only thing that would notice.
    """

    def test_setup_still_has_exactly_one_of_the_wrapper_it_is_scoped_to(self):
        """Exactly one, because the scope is an ancestor selector.

        A second `.setup-wrap` would not break the rules, but it would mean the
        page had been restructured under them, which is the moment to re-read
        this file rather than to find out from the browser tests above.
        """
        html = (WEB / "setup.html").read_text(encoding="utf-8")
        self.assertEqual(1, len(re.findall(r'class="setup-wrap"', html)))

    def test_the_six_are_scoped_to_it_in_the_stylesheet(self):
        """Each scoped rule is looked up and has to carry declarations.

        Asked through `rule_for`, so it matches the whole selector rather than
        a substring of one - `.setup-wrap .sf-item` must exist as its own rule,
        not merely appear inside `.setup-wrap .sf-item input`.
        """
        from tests.css_source import rule_for
        for sel in (".setup-wrap .cloud-status", ".setup-wrap .cloud-status .dot",
                    ".setup-wrap .sf-item", '.setup-wrap .sf-item input[type="text"]',
                    ".setup-wrap .sf-handle", ".setup-wrap .sf-remove"):
            with self.subTest(selector=sel):
                body = rule_for("setup.html", sel)
                self.assertTrue(body.strip(),
                                "%s is not a rule with declarations" % sel)

    def test_both_pages_still_carry_the_same_body_class(self):
        """The reason the scope is a wrapper rather than a body class.

        If this ever stops being true, a body-class scope becomes available and
        is the tidier answer - but it is not available today, and a test that
        merely looked for `tool-home` somewhere in the file would not notice
        the day one of them gained a second class.
        """
        classes = {}
        for page in ("settings.html", "setup.html"):
            html = (WEB / page).read_text(encoding="utf-8")
            classes[page] = re.search(r"<body class=\"([^\"]*)\"", html).group(1)
        self.assertEqual({"settings.html": "tool-home", "setup.html": "tool-home"},
                         classes)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
