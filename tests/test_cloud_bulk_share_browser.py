"""The share dialog, opened and applied in a real browser.

The path he described: a filtered list, select the cloud side, the
move/share/mark/overwrite menu, Share. "The dialog box appears but there is
no Apply. I add both the recent names and the only option is Add or Close."

The tests beside this one run the functions; this one opens the page, opens
the dialog, clicks the remembered names the way he did, and reads what is on
the screen - because "the dialog has no control I can press" is a statement
about the screen, and the functions were all working.

**The stub answers `/api/settings/get`.** A stub server that does not leaves
`settingsAvailable` false, the page concludes it is the serverless build and
skips every server-backed path in it - so the page would load, the test would
pass, and the feature under test would never be reached. That has happened
here before.

Nothing reaches a real account: every request is served by the stub below,
and every address, project and person is invented.
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
#: Deliberately an odd high port, and a different one per session - 8675 is
#: his own running instance.
PORT_HINT = 8791

try:  # pragma: no cover - availability varies by machine
    from selenium import webdriver
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False

BROWSERS = [
    ("firefox", _browsers.find("firefox")),
    ("chrome", _browsers.find("chrome")),
    ("edge", _browsers.find("edge")),
]

ME = "me@example.invalid"
MATE = "colleague@example.invalid"
RECENT = ["firstcontact@example.invalid", "secondcontact@example.invalid"]


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
    """`web/` plus the handful of endpoints this page asks for."""

    shared = []

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
        if self.path.startswith("/api/settings/get"):
            return self._send({"ok": True, "settings": {}})
        return super().do_GET()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            data = {}
        if self.path.endswith("/recent_recipients"):
            return self._send({"ok": True, "recipients":
                               [{"email": e} for e in RECENT]})
        if self.path.endswith("/bulk_share"):
            StubBackend.shared.append(data)
            emails = data.get("args", [None, []])[1] if "args" in data else []
            emails = emails or data.get("emails") or []
            return self._send({
                "ok": True, "ownedCount": 2, "ownedIds": ["p1", "p2"],
                "skipped": [],
                "recipients": [{"email": e, "ok": True, "message": ""}
                               for e in emails],
                "emailsAdded": emails, "emailsRefused": [],
            })
        if self.path.startswith("/api/settings"):
            return self._send({"ok": True, "settings": {}})
        return self._send({"ok": True})


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
        opts.add_argument("--no-sandbox")
        return webdriver.Edge(options=opts)
    except Exception:  # pragma: no cover - a missing driver is a skip
        return None


#: Open the dialog the way the toolbar does, with a selection of two of his
#: own projects and one of somebody else's left out of it.
OPEN = """
window._bulkShareOwnedIds = ['p1', 'p2'];
window._bulkShareOwned = [
  { id: 'p1', name: 'SITE1 Riverside Baseline' },
  { id: 'p2', name: 'SITE2 Harbour Baseline' }];
window._bulkShareNotMine = [
  { id: 'x1', name: 'SITE9 Northgate Survey', owner: %s }];
return openBulkShare().then(() => true);
""" % json.dumps(MATE)


class ShareDialogInABrowser(unittest.TestCase):

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
        #: Registered before the driver starts, so a browser that will not
        #: launch cannot leave the port held.
        cls.addClassCleanup(cls._stop_server)
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

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
        StubBackend.shared = []
        self.driver.get(f"http://127.0.0.1:{self.port}/cloud.html")
        #: The app screen is hidden until there is a session, so the toolbar
        #: and its menus are not on the page at all before this.
        self.driver.execute_script("""
          const app = document.getElementById('appScreen');
          if (app) app.style.display = 'flex';
          const login = document.getElementById('loginScreen');
          if (login) login.style.display = 'none';
          const who = document.getElementById('userEmail');
          if (who) who.textContent = arguments[0];
        """, ME)
        self.driver.execute_script(OPEN)

    def js(self, script):
        return self.driver.execute_script("return " + script)

    # -- the control he could not find ----------------------------------

    def test_the_dialog_is_open(self):
        self.assertTrue(self.js(
            "!document.getElementById('shareModal').hidden"))

    def test_there_is_a_control_that_shares(self):
        """The report: "there is no Apply ... the only option is Add or
        Close"."""
        self.assertTrue(self.js("!!document.getElementById('shareApplyBtn')"),
                        "the dialog still has nothing that commits")

    def test_it_is_disabled_until_somebody_is_named(self):
        self.assertTrue(self.js(
            "document.getElementById('shareApplyBtn').disabled"))

    def test_it_says_why_it_is_disabled(self):
        self.assertIn("at least one person",
                      self.js("document.getElementById('shareApplyBtn').title"))

    def test_picking_the_remembered_names_arms_it(self):
        """Exactly what he did: "I add both the recent names"."""
        self.driver.execute_script(
            "_sharePick(arguments[0]); _sharePick(arguments[1]);", *RECENT)
        self.assertFalse(self.js(
            "document.getElementById('shareApplyBtn').disabled"),
            "adding two recipients left the control dead")

    def test_it_names_what_it_will_do(self):
        self.driver.execute_script(
            "_sharePick(arguments[0]); _sharePick(arguments[1]);", *RECENT)
        self.assertEqual(
            "Share 2 projects with 2 people",
            self.js("document.getElementById('shareApplyBtn').textContent"))

    # -- what it is about to act on -------------------------------------

    def test_the_dialog_lists_the_projects(self):
        html = self.js("document.getElementById('shareTargets').innerHTML")
        self.assertIn("SITE1 Riverside Baseline", html)
        self.assertIn("SITE2 Harbour Baseline", html)

    def test_it_accounts_for_the_one_left_out(self):
        html = self.js("document.getElementById('shareTargets').innerHTML")
        self.assertIn("left out", html)
        self.assertIn("SITE9 Northgate Survey", html)

    # -- and it goes through --------------------------------------------

    def test_pressing_it_shares_and_reports_who_got_access(self):
        self.driver.execute_script(
            "_sharePick(arguments[0]); _sharePick(arguments[1]);", *RECENT)
        self.driver.execute_script(
            "document.getElementById('shareApplyBtn').click();")
        import time
        for _ in range(60):
            html = self.js("document.getElementById('shareTargets').innerHTML")
            if "Result" in html:
                break
            time.sleep(0.25)
        else:  # pragma: no cover
            self.fail("no result appeared: " + html[:400])
        self.assertTrue(StubBackend.shared, "nothing was sent to the server")
        for who in RECENT:
            self.assertIn(who, html)
        self.assertIn("SITE1 Riverside Baseline", html)


def _case(kind, binary):
    name = "%sShareDialogTests" % kind.capitalize()
    return type(name, (ShareDialogInABrowser,),
                {"kind": kind, "binary": binary})


FirefoxShareDialogTests = _case(*BROWSERS[0])
ChromeShareDialogTests = _case(*BROWSERS[1])
EdgeShareDialogTests = _case(*BROWSERS[2])

del ShareDialogInABrowser   # the base itself is not a case to run


if __name__ == "__main__":
    unittest.main()
