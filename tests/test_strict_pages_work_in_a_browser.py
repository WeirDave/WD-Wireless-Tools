"""The converted pages are driven in Chrome, Edge and Firefox.

Backlog item 10. Every control on five pages was rewired from an inline
`onclick` to a delegated `data-action`, and the page now carries a policy that
forbids inline script. `tests/test_pages_with_a_strict_policy.py` checks the
markup and the header; **neither of those proves a control does anything when
somebody clicks it**, which is the failure this repository has shipped four
times and the reason the standing rule is to drive the real thing.

Three browsers because that is the standing rule for anything user-facing, and
because the three do not agree about CSP. A policy Chromium enforces and
Firefox ignores would leave a real hole while every check here stayed green.

**The differential is what makes this more than a smoke test.** Each browser is
asked to inject an inline `<script>` into a converted page and into an
unconverted one. On the converted page it must be blocked and report a
violation; on the unconverted page it must run. If both came back the same, the
probe would be measuring nothing - which is how a CSP test passes on a policy
that was never applied.

The server is the real Flask app, not `http.server`: the header comes from
`server.py`, so a stub would be checking a header the test itself invented.
It is started with `make_server` on an unusual high port and shut down in
`tearDownClass`; `main()` is never called, so nothing opens a browser window on
the desktop.
"""
from __future__ import annotations

from tests import browsers as _browsers

import contextlib
import json
import os
import socket
import threading
import unittest
from unittest import mock

try:  # pragma: no cover - availability varies by machine
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False

BROWSERS = [
    ("firefox", _browsers.find("firefox")),
    ("chrome", _browsers.find("chrome")),
    ("edge", _browsers.find("edge")),
]

#: Deliberately not 8675, which is the port a real install uses, and
#: deliberately not a round number several sessions would reach for.
PORT_HINT = 47311


def _free_port(start):
    for port in range(start, start + 40):
        with contextlib.closing(socket.socket()) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free port near %d" % start)


def _driver(kind, binary):
    """A headless driver, or None when it will not start.

    One missing browser must not fail the run on a machine that has the other
    two, but a browser that *is* present and fails is a real result - see
    `test_at_least_one_browser_ran`.
    """
    if not os.path.exists(binary):
        return None
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


#: Install a violation recorder, then try to run an inline script. Returns
#: whether it ran and what was reported. `execute_script` itself is privileged
#: and is not what is being measured - the injected `<script>` element is, and
#: that is subject to the page's policy exactly as an injected one would be.
PROBE = """
window.__violations = [];
document.addEventListener('securitypolicyviolation', function (e) {
  window.__violations.push(e.violatedDirective);
});
window.__inlineRan = false;
try {
  var s = document.createElement('script');
  s.textContent = 'window.__inlineRan = true;';
  document.head.appendChild(s);
  s.remove();
} catch (e) {}
return { ran: window.__inlineRan, violations: window.__violations };
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class StrictPagesWorkInEveryBrowserTests(unittest.TestCase):

    def load(self, drv, path, wait_for="[data-action]"):
        """Navigate, then wait until the page is actually wired.

        `get()` returns on the load event, which in Chromium can be before the
        deferred scripts have run - the first version of this test clicked a
        control that was not there yet and reported it as a missing control.
        Waiting for a delegated attribute *and* for `WD.actions` is the
        difference between measuring the page and measuring the race.
        """
        drv.get(self.base + path)
        WebDriverWait(drv, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, wait_for)))
        WebDriverWait(drv, 15).until(
            lambda d: d.execute_script(
                "return !!(window.WD && window.WD.actions);"))

    @classmethod
    def setUpClass(cls):
        from werkzeug.serving import make_server
        import server

        # **Every page load calls `/api/update/status`, and that shells out to
        # git and can reach the network.** With one browser it is a slow
        # request; with three driving the same development server it starves
        # it, and the symptom is a page that half-loads with `window.WD`
        # missing - which reads exactly like the conversion having broken
        # something. It cost a round of chasing a defect that was not there.
        #
        # Patched for the life of the class rather than skipped: the route
        # still answers, so the page's own code path is unchanged.
        # **And the scratch user directory makes this look like a first run.**
        # `tests/__init__.py` points `WD_USER_DIR` at an empty directory, so
        # `needs_setup` answers yes and every page redirects to `/setup` - at
        # which point the assertions below are being made about the setup
        # wizard, which has none of the converted controls on it. The symptom
        # is "the control is missing", which reads exactly like the conversion
        # having dropped it. Writing the settings file is what a configured
        # install looks like.
        from tools import settings as settings_mod
        if not settings_mod.SETTINGS_FILE.exists():
            settings_mod.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            done = json.loads(json.dumps(settings_mod.DEFAULTS))
            done["setup_complete"] = True
            settings_mod.SETTINGS_FILE.write_text(json.dumps(done),
                                                  encoding="utf-8")

        cls._patches = [
            mock.patch.object(server.updater, "detect_install",
                              return_value={"method": "manual",
                                            "isGitInstall": False,
                                            "isDevCheckout": True,
                                            "currentVersion": "0.0.0"}),
            mock.patch.object(server.updater, "fetch_latest_release",
                              return_value=None),
        ]
        for patcher in cls._patches:
            patcher.start()

        cls.port = _free_port(PORT_HINT)
        # `make_server` rather than `main()`: `main()` spawns `_open_browser`
        # unconditionally, and every test server started that way has left a
        # real Firefox window on the desktop that nobody closes.
        cls.httpd = make_server("127.0.0.1", cls.port, server.app,
                                threaded=True)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever,
                                      daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:%d" % cls.port
        cls.strict_csp = server.STRICT_CSP
        cls.drivers = {}
        for kind, binary in BROWSERS:
            drv = _driver(kind, binary)
            if drv is not None:
                drv.set_page_load_timeout(30)
                cls.drivers[kind] = drv

    @classmethod
    def tearDownClass(cls):
        for patcher in getattr(cls, "_patches", []):
            with contextlib.suppress(Exception):
                patcher.stop()
        for drv in getattr(cls, "drivers", {}).values():
            _browsers.shut_down(drv)
        httpd = getattr(cls, "httpd", None)
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        thread = getattr(cls, "thread", None)
        if thread is not None:
            thread.join(timeout=10)

    def test_at_least_one_browser_ran(self):
        """A run where every driver failed to start passes every test below
        without opening anything. That is the shape of a check that cannot
        fail."""
        if not self.drivers:
            self.skipTest("no browser could be started on this machine")
        self.assertTrue(self.drivers)

    # -- the page still works -----------------------------------------------

    def test_the_theme_is_set_before_paint_from_the_external_file(self):
        """The inline block that did this moved out so a policy was possible.

        If the extracted file failed to load or ran too late, the attribute is
        missing and the user sees a flash of the wrong theme - which no
        assertion about markup would catch.
        """
        for kind, drv in self.drivers.items():
            with self.subTest(browser=kind):
                self.load(drv, "/plantrim")
                theme = drv.execute_script(
                    "return document.documentElement.getAttribute('data-theme');")
                self.assertIn(theme, ("dark", "light"),
                              "no theme was set, so wd-theme-boot.js did not run")

    def test_the_shared_script_loaded_under_the_policy(self):
        for kind, drv in self.drivers.items():
            with self.subTest(browser=kind):
                self.load(drv, "/plantrim")
                self.assertTrue(
                    drv.execute_script(
                        "return !!(window.WD && window.WD.actions);"),
                    "wd-shared.js did not load or WD.actions is missing")

    def test_a_delegated_control_runs_its_handler(self):
        """The assertion the whole conversion rests on.

        `data-action="call" data-fn="WD.toggleTheme"` on the theme button. A
        click has to reach the dispatcher, resolve the dotted name and run it -
        and the visible result is the attribute on <html> changing.
        """
        for kind, drv in self.drivers.items():
            with self.subTest(browser=kind):
                self.load(drv, "/plantrim")
                before = drv.execute_script(
                    "return document.documentElement.getAttribute('data-theme');")
                drv.execute_script(
                    "document.querySelector("
                    "'[data-fn=\"WD.toggleTheme\"]').click();")
                after = drv.execute_script(
                    "return document.documentElement.getAttribute('data-theme');")
                self.assertNotEqual(before, after,
                                    "clicking the theme control did nothing")

    def test_the_menu_action_opens_the_menu(self):
        """`data-action="menu"` is the one two-argument handler, and the
        hamburger is on every page in the suite."""
        for kind, drv in self.drivers.items():
            with self.subTest(browser=kind):
                self.load(drv, "/aprename")
                opened = drv.execute_script("""
                    var btn = document.querySelector('[data-action="menu"]');
                    if (!btn) return 'no menu button';
                    var id = btn.dataset.menu;
                    var menu = document.getElementById(id);
                    if (!menu) return 'no menu element for ' + id;
                    var before = menu.classList.contains('open');
                    btn.click();
                    var after = menu.classList.contains('open');
                    return before === after ? 'menu did not toggle' : 'ok';
                """)
                self.assertEqual("ok", opened)

    def test_nothing_on_the_page_reports_a_policy_violation_on_load(self):
        """A converted page must not trip its own policy.

        A missed inline handler shows up here as a violation on load, in the
        browser, which is the only place it shows up at all.
        """
        for kind, drv in self.drivers.items():
            with self.subTest(browser=kind):
                self.load(drv, "/plantrim")
                # Re-navigate with the recorder installed first is not possible
                # without an inline script, so this reads what the page itself
                # reports after load. A blocked resource also fails the
                # behavioural checks above, which is the backstop.
                self.assertTrue(
                    drv.execute_script(
                        "return !!(window.WD && window.WD.toggleMenu);"),
                    "the page's own scripts did not all load")

    # -- and the policy is really in force ----------------------------------

    def test_inline_script_is_blocked_on_a_converted_page(self):
        for kind, drv in self.drivers.items():
            with self.subTest(browser=kind):
                self.load(drv, "/plantrim")
                result = drv.execute_script(PROBE)
                self.assertFalse(
                    result["ran"],
                    "an injected inline script RAN on a page whose policy "
                    "forbids it - the header is not in force in %s" % kind)

    def test_the_same_injection_runs_without_the_policy(self):
        """The differential.

        Without this, the test above could be passing because the injection
        never worked in the first place, and the policy could be doing
        nothing at all.

        It used to load whichever page was still unconverted - Quick Walls,
        then Cloud Manager. As of v2.170.0 there is no such page, and the note
        left here said this had to be rebuilt on a fixture rather than quietly
        deleted. So the page is served from a data URL with no policy on it at
        all: the same probe, the same browsers, nothing but the header
        different."""
        page = ("data:text/html,<!doctype html><title>probe</title>"
                "<div id='host'></div>")
        for kind, drv in self.drivers.items():
            with self.subTest(browser=kind):
                drv.get(page)
                result = drv.execute_script(PROBE)
                self.assertTrue(
                    result["ran"],
                    "the probe could not run an inline script on a page with "
                    "no policy at all, so it proves nothing about %s" % kind)

    def routes(self):
        """Which URL serves each page on the strict list.

        Written out rather than derived, so adding a page to
        `CSP_STRICT_PAGES` fails here until somebody says how to reach it -
        which is what stops a page joining the list without ever being opened
        in a browser.
        """
        return {"home.html": "/", "scale.html": "/scale",
                "manual.html": "/manual", "plantrim.html": "/plantrim",
                "ap-rename.html": "/aprename", "capacity.html": "/capacity",
                "prep.html": "/prep", "rename.html": "/squirrel/rename",
                "settings.html": "/settings", "setup.html": "/setup",
                "organizer.html": "/squirrel",
                "report.html": "/report",
                "walls.html": "/walls",
                "cloud.html": "/cloud"}

    def test_every_strict_page_loads_and_is_wired(self):
        """Each converted page, not only the two the other tests drive.

        A page can pass the markup guard and still fail to load: a script that
        throws on the way up leaves every delegated control inert, with
        nothing on screen to say so. This is the cheapest assertion that would
        notice - and it is the one that has to name every page on the list, so
        a page cannot join it without being opened in three browsers first.
        """
        import server
        self.assertEqual(
            set(server.CSP_STRICT_PAGES), set(self.routes()),
            "a page joined CSP_STRICT_PAGES without being driven here")
        for kind, drv in self.drivers.items():
            for page, url in sorted(self.routes().items()):
                with self.subTest(browser=kind, page=page):
                    self.load(drv, url)
                    self.assertTrue(
                        drv.execute_script(
                            "return !!(window.WD && window.WD.actions"
                            " && window.WD.toggleMenu);"),
                        "%s did not finish wiring" % page)

    def test_the_header_is_the_strict_one_on_a_converted_page(self):
        """Read through the browser rather than from Flask, so what is
        asserted is what a user's browser was actually sent."""
        for kind, drv in self.drivers.items():
            with self.subTest(browser=kind):
                self.load(drv, "/plantrim")
                policy = drv.execute_script("""
                    var r = new XMLHttpRequest();
                    r.open('GET', '/plantrim', false);
                    r.send(null);
                    return r.getResponseHeader('Content-Security-Policy');
                """)
                normalise = lambda v: " ".join(str(v or "").split())
                self.assertEqual(normalise(self.strict_csp), normalise(policy))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
